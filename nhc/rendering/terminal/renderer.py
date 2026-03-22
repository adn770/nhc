"""Curses/blessed terminal renderer implementation.

Screen layout (3 zones):

  Zone 1: MAP (full width × available height, centered on player)
  ─────────────────────────────────────────────────────────────────
  Zone 2: STATUS (3 lines + separator)
    📍 Location │ ⬇ Depth │ ⏳ Turn │ ❤️ HP bar
    💪 STR  🏃 DEX  🛡️ CON  🧠 INT  👁️ WIS  ✨ CHA │ ⚔️ Wpn │ 🛡️ AC
    🎒 Inventory items
  ─────────────────────────────────────────────────────────────────
  Zone 3: MESSAGES (4 lines, scrollable with [ and ])
"""

from __future__ import annotations

import asyncio
from typing import Any

import logging

from blessed import Terminal

from nhc.i18n import t as tr

logger = logging.getLogger(__name__)

from nhc.core.ecs import World
from nhc.dungeon.model import Level, Terrain
from nhc.rendering.terminal import glyphs as _glyphs
from nhc.rendering.terminal.glyphs import (
    FEATURE_GLYPHS,
    dim_color_fn,
    wall_glyph,
)
from nhc.rendering.terminal.help_overlay import show_help as _show_help
from nhc.rendering.terminal.input import map_key_to_intent
from nhc.rendering.terminal.input_line import TextInput, render_input_line
from nhc.rendering.terminal.narrative_log import (
    NarrativeLog,
    render_narrative_log,
)
from nhc.rendering.terminal.panels import render_messages, render_status

# Zone sizes (separators included)
STATUS_HEIGHT = 4   # separator + 3 lines
MSG_SEP = 1         # separator above messages
LOG_HEIGHT = 6      # message/narrative log lines (both modes)
INPUT_HEIGHT = 1    # input line (typed mode only, within LOG_HEIGHT)

# Chrome is the same in both modes — the input line borrows
# the last line of the log area so the map zone never shifts.
CHROME_HEIGHT = STATUS_HEIGHT + MSG_SEP + LOG_HEIGHT

# Backwards compat aliases
CHROME_HEIGHT_CLASSIC = CHROME_HEIGHT
CHROME_HEIGHT_TYPED = CHROME_HEIGHT
MSG_HEIGHT = LOG_HEIGHT


class TerminalRenderer:
    """ASCII terminal renderer using blessed."""

    def __init__(self, color_mode: str = "256",
                 game_mode: str = "classic") -> None:
        # force_styling=True ensures 256/truecolor escapes even when
        # blessed cannot auto-detect (e.g. inside tmux/screen).
        force = color_mode == "256"
        self.term = Terminal(force_styling=force)
        self.color_mode = color_mode
        self.game_mode = game_mode
        _glyphs.set_color_mode(color_mode)
        self._messages: list[str] = []
        self._msg_scroll: int = 0  # 0 = showing latest
        # Typed mode widgets
        self.narrative_log = NarrativeLog()
        self._text_input = TextInput()

    def initialize(self) -> None:
        """Enter fullscreen mode."""
        print(self.term.enter_fullscreen, end="", flush=True)
        print(self.term.civis, end="", flush=True)

    def shutdown(self) -> None:
        """Restore terminal."""
        print(self.term.cnorm, end="", flush=True)
        print(self.term.exit_fullscreen, end="", flush=True)

    def show_help(self) -> None:
        """Display the scrollable help overlay."""
        _show_help(self.term)

    def add_message(self, text: str) -> None:
        """Add a message to the log.

        In typed mode, messages also appear in the narrative log as
        mechanical entries so the story stays complete regardless of
        whether the action came from a shortcut key or typed text.
        """
        logger.info("MSG: %s", text)
        self._messages.append(text)
        if len(self._messages) > 200:
            self._messages = self._messages[-200:]
        # Reset scroll to bottom on new message
        self._msg_scroll = 0
        # Mirror to narrative log in typed mode
        if self.game_mode == "typed":
            self.narrative_log.add_mechanical(text)

    def scroll_messages(self, direction: int) -> None:
        """Scroll message log. direction: +1 = older, -1 = newer."""
        self._msg_scroll = max(
            0,
            min(self._msg_scroll + direction,
                max(0, len(self._messages) - MSG_HEIGHT)),
        )

    def render(
        self,
        world: World,
        level: Level,
        player_id: int,
        turn: int,
    ) -> None:
        """Render the full game screen."""
        t = self.term
        pos = world.get_component(player_id, "Position")
        if not pos:
            return

        map_h = max(3, t.height - CHROME_HEIGHT)

        output = t.home + t.clear

        # ── Zone 1: Map ──
        output += self._render_map(
            world, level, pos.x, pos.y,
            0, 0, t.width, map_h,
        )

        # ── Zone 2: Status ──
        stats = self._gather_stats(world, player_id, turn, level)
        items, max_slots = self._gather_inventory(world, player_id)
        status_y = map_h
        output += render_status(t, status_y, t.width, stats, items, max_slots)

        # ── Zone 3: Log area (same height in both modes) ──
        log_y = status_y + STATUS_HEIGHT
        if self.game_mode == "typed":
            # Narrative log takes all but the last line; input gets last line
            narr_lines = LOG_HEIGHT - INPUT_HEIGHT
            output += render_narrative_log(
                t, log_y, t.width, narr_lines,
                self.narrative_log.entries,
                self.narrative_log.scroll_offset,
            )
            input_y = log_y + narr_lines
            output += render_input_line(
                t, input_y, t.width,
                self._text_input.text, self._text_input.cursor,
                mode_indicator="✏️  ",
            )
        else:
            output += render_messages(
                t, log_y, t.width, LOG_HEIGHT,
                self._messages, self._msg_scroll,
            )

        print(output, end="", flush=True)

    async def get_typed_input(
        self,
        world: World,
        level: Level,
        player_id: int,
        turn: int,
    ) -> str | tuple[str, Any]:
        """Run the text input widget until Enter or a movement key.

        Returns either a string (typed text) or a (intent, data) tuple
        if the user pressed a movement/action key.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        inp = self._text_input

        while True:
            # Render the current screen (updates input cursor)
            self.render(world, level, player_id, turn)

            # Read a single key
            val = await loop.run_in_executor(None, self._blocking_read)

            # In typed mode only sequence keys (arrows, PgUp, etc.)
            # and a small whitelist bypass the text input.  All
            # printable characters go into the text buffer.
            # When text is being edited, arrow keys control the cursor
            # and history instead of moving the character.
            # Tab always toggles mode
            if val in ("\t", "KEY_TAB"):
                return ("toggle_mode", None)

            if val.startswith("KEY_"):
                if not inp.text:
                    intent, data = map_key_to_intent(val)
                    if intent == "move":
                        return (intent, data)
            elif val == "?":
                # Only bypass when the input line is empty (otherwise
                # the user is typing a question)
                if not inp.text:
                    return ("help", None)

            # Scroll shortcuts work even in typed mode
            if val == "[":
                return ("scroll_up", None)
            if val == "]":
                return ("scroll_down", None)

            # Text editing keys
            if val == "KEY_ENTER" or val == "\n" or val == "\r":
                text = inp.submit()
                if text:
                    return text
            elif val == "KEY_ESCAPE" or val == "\x1b":
                inp.clear()
            elif val == "KEY_BACKSPACE" or val == "\x7f":
                inp.backspace()
            elif val == "KEY_DELETE":
                inp.delete()
            elif val == "KEY_LEFT":
                inp.move_left()
            elif val == "KEY_RIGHT":
                inp.move_right()
            elif val == "KEY_HOME":
                inp.home()
            elif val == "KEY_END":
                inp.end()
            elif val == "KEY_UP":
                inp.history_up()
            elif val == "KEY_DOWN":
                inp.history_down()
            elif len(val) == 1 and val.isprintable():
                inp.insert(val)

    def _render_map(
        self,
        world: World,
        level: Level,
        cam_x: int, cam_y: int,
        screen_x: int, screen_y: int,
        view_w: int, view_h: int,
    ) -> str:
        """Render the dungeon map centered on camera position."""
        t = self.term
        output = ""

        half_w = view_w // 2
        half_h = view_h // 2

        # Build a map of entity positions (only visible ones)
        entity_at: dict[tuple[int, int], tuple[str, str, int]] = {}
        for eid, rend, epos in world.query("Renderable", "Position"):
            if epos is None:
                continue
            tile = level.tile_at(epos.x, epos.y)
            if tile and tile.visible:
                key = (epos.x, epos.y)
                existing = entity_at.get(key)
                if existing is None or rend.render_order > existing[2]:
                    entity_at[key] = (rend.glyph, rend.color, rend.render_order)

        for sy in range(view_h):
            row_out = ""
            for sx in range(view_w):
                mx = cam_x - half_w + sx
                my = cam_y - half_h + sy

                tile = level.tile_at(mx, my)
                if not tile:
                    row_out += " "
                    continue

                if not tile.explored:
                    row_out += " "
                    continue

                # Entity on this tile (only if visible)
                entity = entity_at.get((mx, my))
                if entity and tile.visible:
                    glyph, color, _ = entity
                    color_fn = getattr(t, color, None) or t.white
                    row_out += color_fn(glyph)
                    continue

                # Tile feature (door, stairs, trap)
                if tile.feature and tile.feature in FEATURE_GLYPHS:
                    if tile.feature == "trap":
                        pass  # Hidden traps fall through to terrain
                    else:
                        glyph, color = FEATURE_GLYPHS[tile.feature]
                        if tile.visible:
                            cfn = getattr(t, color, None) or t.white
                        else:
                            cfn = dim_color_fn(t, _glyphs.FEATURE_DIM_RGB
                                               if self.color_mode == "256"
                                               else "bright_black")
                        row_out += cfn(glyph)
                        continue

                # Corridor tiles render as #
                if tile.is_corridor:
                    glyph, color, dim_val = _glyphs.CORRIDOR_GLYPH
                elif tile.terrain == Terrain.WALL:
                    nb_n = level.tile_at(mx, my - 1)
                    nb_s = level.tile_at(mx, my + 1)
                    nb_e = level.tile_at(mx + 1, my)
                    nb_w = level.tile_at(mx - 1, my)
                    cn = nb_n is not None and nb_n.terrain == Terrain.WALL
                    cs = nb_s is not None and nb_s.terrain == Terrain.WALL
                    ce = nb_e is not None and nb_e.terrain == Terrain.WALL
                    cw = nb_w is not None and nb_w.terrain == Terrain.WALL
                    _, color, dim_val = _glyphs.TERRAIN_GLYPHS[Terrain.WALL]
                    glyph = wall_glyph(cn, cs, ce, cw)
                else:
                    glyph, color, dim_val = _glyphs.TERRAIN_GLYPHS.get(
                        tile.terrain, ("?", "white", "bright_black"),
                    )
                if tile.visible:
                    cfn = getattr(t, color, None) or t.white
                else:
                    cfn = dim_color_fn(t, dim_val)
                row_out += cfn(glyph)

            output += t.move_xy(screen_x, screen_y + sy) + row_out

        return output

    def _gather_stats(
        self, world: World, player_id: int, turn: int, level: Level,
    ) -> dict[str, Any]:
        """Collect player stats for the status bar."""
        health = world.get_component(player_id, "Health")
        stats = world.get_component(player_id, "Stats")
        equip = world.get_component(player_id, "Equipment")

        weapon_name = "unarmed"
        if equip and equip.weapon is not None:
            desc = world.get_component(equip.weapon, "Description")
            if desc:
                weapon_name = desc.name

        player = world.get_component(player_id, "Player")
        pdesc = world.get_component(player_id, "Description")

        return {
            "char_name": pdesc.name if pdesc else "",
            "char_background": pdesc.short if pdesc else "",
            "hp": health.current if health else 0,
            "hp_max": health.maximum if health else 0,
            "turn": turn,
            "depth": level.depth,
            "level_name": level.name,
            "plevel": player.level if player else 1,
            "xp": player.xp if player else 0,
            "xp_next": player.xp_to_next if player else 20,
            "gold": player.gold if player else 0,
            "str": stats.strength if stats else 0,
            "dex": stats.dexterity if stats else 0,
            "con": stats.constitution if stats else 0,
            "int": stats.intelligence if stats else 0,
            "wis": stats.wisdom if stats else 0,
            "cha": stats.charisma if stats else 0,
            "weapon": weapon_name,
        }

    def _gather_inventory(
        self, world: World, player_id: int,
    ) -> tuple[list[str], int]:
        """Collect inventory item names."""
        inv = world.get_component(player_id, "Inventory")
        if not inv:
            return [], 11

        names = []
        for item_id in inv.slots:
            desc = world.get_component(item_id, "Description")
            if desc:
                names.append(desc.name)
            else:
                names.append("???")

        return names, inv.max_slots

    async def get_input(self) -> tuple[str, Any]:
        """Wait for keypress and return (intent, data)."""
        loop = asyncio.get_event_loop()
        val = await loop.run_in_executor(None, self._blocking_read)
        return map_key_to_intent(val)

    def _blocking_read(self) -> str:
        """Blocking key read."""
        with self.term.cbreak():
            val = self.term.inkey(timeout=None)
            if val.is_sequence:
                return val.name
            return str(val)

    def show_inventory_menu(
        self, world: World, player_id: int, prompt: str = "Use which item?",
    ) -> int | None:
        """Show inventory selection menu. Returns item EntityId or None."""
        t = self.term
        inv = world.get_component(player_id, "Inventory")
        if not inv or not inv.slots:
            return None

        items: list[tuple[int, str]] = []
        for item_id in inv.slots:
            desc = world.get_component(item_id, "Description")
            name = desc.name if desc else "???"
            items.append((item_id, name))

        # Draw menu overlay with box
        menu_x = 5
        menu_y = 3
        menu_w = 40
        output = ""
        output += t.move_xy(menu_x, menu_y) + "╭" + "─" * (menu_w - 2) + "╮"
        output += t.move_xy(menu_x, menu_y + 1)
        output += "│" + t.bold(f" 🎒 {prompt}").ljust(menu_w + 10) + "│"
        output += t.move_xy(menu_x, menu_y + 2) + "├" + "─" * (menu_w - 2) + "┤"
        for i, (_, name) in enumerate(items):
            letter = chr(ord("a") + i)
            line = f"│  {letter}) {name}"
            output += t.move_xy(menu_x, menu_y + 3 + i) + line.ljust(menu_w - 1) + "│"
        bot = menu_y + 3 + len(items)
        output += t.move_xy(menu_x, bot) + "├" + "─" * (menu_w - 2) + "┤"
        output += t.move_xy(menu_x, bot + 1)
        esc_line = "│" + t.bright_black(tr("ui.esc_cancel")).ljust(menu_w + 10) + "│"
        output += esc_line
        output += t.move_xy(menu_x, bot + 2) + "╰" + "─" * (menu_w - 2) + "╯"
        print(output, end="", flush=True)

        with t.cbreak():
            val = t.inkey(timeout=None)
            key = str(val)

        if key == "\x1b" or val.name == "KEY_ESCAPE":
            return None

        idx = ord(key) - ord("a")
        if 0 <= idx < len(items):
            return items[idx][0]
        return None

    def show_end_screen(self, won: bool, turn: int) -> None:
        """Show game over / victory screen."""
        t = self.term
        cx = t.width // 2
        cy = t.height // 2

        output = t.home + t.clear

        if won:
            title = f"⚔️  {tr('ui.victory_title')} ⚔️"
            msg = tr("ui.victory_desc")
            color = t.bright_green
        else:
            title = f"💀 {tr('ui.death_title')} 💀"
            msg = tr("ui.death_desc")
            color = t.bright_red

        output += t.move_xy(cx - 8, cy - 1) + color(t.bold(title))
        output += t.move_xy(cx - len(msg) // 2, cy + 1) + msg
        footer = tr("ui.end_footer", turn=turn)
        output += t.move_xy(cx - len(footer) // 2, cy + 3) + t.bright_black(footer)

        print(output, end="", flush=True)

        with t.cbreak():
            t.inkey(timeout=None)
