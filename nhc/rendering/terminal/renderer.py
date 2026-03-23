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
from nhc.rendering.terminal.panels import H_LINE, render_messages, render_status

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
        """Add a message to the log, word-wrapping long lines.

        In typed mode, messages also appear in the narrative log as
        mechanical entries so the story stays complete regardless of
        whether the action came from a shortcut key or typed text.
        """
        logger.info("MSG: %s", text)
        # Word-wrap to terminal width (minus 2 for padding)
        max_w = max(40, self.term.width - 2)
        for line in self._wrap(text, max_w):
            self._messages.append(line)
        if len(self._messages) > 200:
            self._messages = self._messages[-200:]
        # Reset scroll to bottom on new message
        self._msg_scroll = 0
        # Mirror to narrative log in typed mode
        if self.game_mode == "typed":
            self.narrative_log.add_mechanical(text)

    @staticmethod
    def _wrap(text: str, width: int) -> list[str]:
        """Word-wrap text into lines that fit within width."""
        lines: list[str] = []
        for raw_line in text.split("\n"):
            raw_line = raw_line.rstrip()
            if not raw_line:
                lines.append("")
                continue
            while len(raw_line) > width:
                split = raw_line[:width].rfind(" ")
                if split <= 0:
                    split = width
                lines.append(raw_line[:split])
                raw_line = raw_line[split:].lstrip()
            if raw_line:
                lines.append(raw_line)
        return lines or [""]

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

        # ── Zone 3: Log + input (identical layout in both modes) ──
        log_y = status_y + STATUS_HEIGHT
        msg_lines = LOG_HEIGHT - INPUT_HEIGHT  # lines for messages

        # Separator
        output += t.move_xy(0, log_y) + t.bright_black(H_LINE * t.width)

        # Message lines (from unified message list)
        total = len(self._messages)
        end = total - self._msg_scroll
        start = max(0, end - msg_lines)
        visible = self._messages[start:end] if total else []
        for i in range(msg_lines):
            line_y = log_y + 1 + i
            if i < len(visible):
                output += t.move_xy(0, line_y) + f" {visible[i]}"[:t.width].ljust(t.width)
            else:
                output += t.move_xy(0, line_y) + " " * t.width

        # Input line: prompt in typed mode, blank in classic
        input_y = log_y + 1 + msg_lines
        if self.game_mode == "typed":
            output += render_input_line(
                t, input_y, t.width,
                self._text_input.text, self._text_input.cursor,
                mode_indicator="✏️  ",
            )
        else:
            hint = "TAB → typed mode  ? → help"
            padded = hint.center(t.width)
            output += t.move_xy(0, input_y) + t.color_rgb(80, 140, 210)(padded)

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

    @staticmethod
    def _wall_char_at(level: Level, x: int, y: int) -> str:
        """Pick the correct box-drawing character for a wall tile.

        Connects in a direction if the neighbor is also a WALL tile
        or a door (blocks_sight).  VOID tiles don't connect, which
        produces clean room borders.
        """
        def _is_wall(nx: int, ny: int) -> bool:
            nb = level.tile_at(nx, ny)
            if nb is None:
                return False
            if nb.terrain == Terrain.WALL:
                return True
            # Doors sit in wall-like positions
            if nb.feature in ("door_closed", "door_locked",
                              "door_secret"):
                return True
            return False

        cn = _is_wall(x, y - 1)
        cs = _is_wall(x, y + 1)
        ce = _is_wall(x + 1, y)
        cw = _is_wall(x - 1, y)

        return wall_glyph(cn, cs, ce, cw)

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
            # Hidden traps are invisible until detected
            trap = world.get_component(eid, "Trap")
            if trap and trap.hidden:
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
                # Secret doors render as walls until discovered
                if tile.feature == "door_secret":
                    _, color, dim_val = _glyphs.TERRAIN_GLYPHS[Terrain.WALL]
                    # Match wall orientation from neighbors
                    glyph = self._wall_char_at(level, mx, my)
                    if tile.visible:
                        cfn = getattr(t, color, None) or t.white
                    else:
                        cfn = dim_color_fn(t, dim_val)
                    row_out += cfn(glyph)
                    continue

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
                    _, color, dim_val = _glyphs.TERRAIN_GLYPHS[Terrain.WALL]
                    glyph = self._wall_char_at(level, mx, my)
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
        self, world: World, player_id: int, prompt: str = "",
    ) -> int | None:
        """Show full inventory selection menu."""
        inv = world.get_component(player_id, "Inventory")
        if not inv or not inv.slots:
            return None

        items: list[tuple[int, str]] = []
        for item_id in inv.slots:
            desc = world.get_component(item_id, "Description")
            items.append((item_id, desc.name if desc else "???"))

        title = prompt or tr("ui.use_which")
        return self._draw_inventory_box(title, items)

    def show_filtered_inventory(
        self, world: World, player_id: int,
        title: str,
        filter_component: str | None = None,
    ) -> int | None:
        """Show inventory filtered by component. Returns item EntityId."""
        inv = world.get_component(player_id, "Inventory")
        if not inv or not inv.slots:
            return None

        items: list[tuple[int, str]] = []
        for item_id in inv.slots:
            if filter_component and not world.has_component(
                item_id, filter_component,
            ):
                continue
            desc = world.get_component(item_id, "Description")
            name = desc.name if desc else "???"
            items.append((item_id, name))

        if not items:
            return None

        return self._draw_inventory_box(title, items)

    def _draw_inventory_box(
        self, title: str, items: list[tuple[int, str]],
    ) -> int | None:
        """Draw an inventory selection box. Returns selected EntityId."""
        t = self.term
        border = t.color_rgb(80, 140, 210)

        menu_x = 5
        menu_y = 3
        menu_w = 40
        inner = menu_w - 2

        output = ""

        # Top border with centered title
        title_text = f" {title} "
        title_len = len(title_text)
        left_fill = max(1, (inner - title_len) // 2)
        right_fill = max(0, inner - left_fill - title_len)
        output += t.move_xy(menu_x, menu_y)
        output += border(
            "╭" + "─" * left_fill + title_text + "─" * right_fill + "╮"
        )

        # Item lines
        for i, (_, name) in enumerate(items):
            letter = chr(ord("a") + i)
            entry = f"  {letter}) {name}"
            padded = entry[:inner].ljust(inner)
            output += t.move_xy(menu_x, menu_y + 1 + i)
            output += border("│") + padded + border("│")

        # Bottom border with centered ESC hint
        esc_text = " " + tr("ui.esc_cancel").strip() + " "
        esc_len = len(esc_text)
        left_fill = (inner - esc_len) // 2
        right_fill = max(0, inner - left_fill - esc_len)
        bot = menu_y + 1 + len(items)
        output += t.move_xy(menu_x, bot)
        output += border(
            "╰" + "─" * left_fill + esc_text
            + "─" * right_fill + "╯"
        )

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
