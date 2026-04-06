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
from nhc.dungeon.model import Level, RectShape, Terrain
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
from nhc.rendering.terminal.themes import get_theme, set_theme

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


from nhc.rendering.client import GameClient


class TerminalRenderer(GameClient):
    """ASCII terminal renderer using blessed."""

    def __init__(self, color_mode: str = "256",
                 game_mode: str = "classic",
                 theme: str | None = None) -> None:
        # Set theme first (determines color depth)
        if theme:
            set_theme(theme)
        active = get_theme()
        self.color_mode = active.color_depth
        # force_styling=True ensures 256/truecolor escapes even when
        # blessed cannot auto-detect (e.g. inside tmux/screen).
        force = self.color_mode == "256"
        self.term = Terminal(force_styling=force)
        self.game_mode = game_mode
        self.edge_doors = False  # terminal: doors at tile center
        _glyphs.set_color_mode(self.color_mode)
        self._messages: list[str] = []
        self._msg_scroll: int = 0  # 0 = showing latest

    @property
    def messages(self) -> list[str]:
        return self._messages

    @messages.setter
    def messages(self, value: list[str]) -> None:
        self._messages = value
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
        items, max_slots, total_used = self._gather_inventory(
            world, player_id,
            equipped_ids=stats.get("_equipped_ids"),
        )
        status_y = map_h
        output += render_status(t, status_y, t.width, stats, items,
                                max_slots, total_used)

        # ── Zone 3: Log + input (identical layout in both modes) ──
        log_y = status_y + STATUS_HEIGHT
        msg_lines = LOG_HEIGHT - INPUT_HEIGHT  # lines for messages

        # Separator
        output += t.move_xy(0, log_y) + t.bright_black(
            get_theme().h_line * t.width)

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
        loop = asyncio.get_running_loop()
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
    def _wall_char_at(
        level: Level, x: int, y: int, rounded: bool = False,
    ) -> str:
        """Pick the correct box-drawing character for a wall tile.

        Primary connections: WALL neighbors.
        Secondary: doors count as connections only if there's no
        wall-to-wall connection on the perpendicular axis (prevents
        ─ rendering between two doors on a vertical wall segment).

        When *rounded* is True, L-shaped corners use rounded glyphs
        (╭╮╰╯) if the active theme supports them.
        """
        _DOOR_FEATS = {"door_closed", "door_open", "door_locked", "door_secret"}

        def _is_wall_only(nx: int, ny: int) -> bool:
            nb = level.tile_at(nx, ny)
            return nb is not None and nb.terrain == Terrain.WALL

        def _is_door(nx: int, ny: int) -> bool:
            nb = level.tile_at(nx, ny)
            return nb is not None and nb.feature in _DOOR_FEATS

        # First check pure wall connections
        wn = _is_wall_only(x, y - 1)
        ws = _is_wall_only(x, y + 1)
        we = _is_wall_only(x + 1, y)
        ww = _is_wall_only(x - 1, y)

        # Doors count as connections only if there's no
        # wall-to-wall connection on BOTH sides of the
        # perpendicular axis. This prevents a horizontal bar
        # between two doors on a vertical wall, while still
        # allowing corner glyphs where one perpendicular
        # neighbor is a wall and the other is void/floor.
        dn = _is_door(x, y - 1)
        ds = _is_door(x, y + 1)
        de = _is_door(x + 1, y)
        dw = _is_door(x - 1, y)

        cn = wn or (dn and not (we and ww))
        cs = ws or (ds and not (we and ww))
        ce = we or (de and not (wn and ws))
        cw = ww or (dw and not (wn and ws))

        return wall_glyph(cn, cs, ce, cw, rounded=rounded)

    def _render_map(
        self,
        world: World,
        level: Level,
        cam_x: int, cam_y: int,
        screen_x: int, screen_y: int,
        view_w: int, view_h: int,
    ) -> str:
        """Render the dungeon map centered on camera position."""
        _active_theme = get_theme()
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

        # Build set of wall positions adjacent to non-rect rooms
        # that should use rounded corner glyphs
        _rounded_walls: set[tuple[int, int]] = set()
        if _active_theme.walls_rounded:
            for room in level.rooms:
                if isinstance(room.shape, RectShape):
                    continue
                for fx, fy in room.floor_tiles():
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = fx + dx, fy + dy
                        nb = level.tile_at(nx, ny)
                        if nb and nb.terrain == Terrain.WALL:
                            _rounded_walls.add((nx, ny))

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
                    # Theme player glyph override
                    if (mx == cam_x and my == cam_y
                            and _active_theme.player_glyph):
                        glyph = _active_theme.player_glyph
                    color_fn = getattr(t, color, None) or t.white
                    cell = color_fn(glyph)
                    if mx == cam_x and my == cam_y:
                        cell = t.bold(cell)
                    row_out += cell
                    continue

                # Tile feature (door, stairs, trap)
                # Secret doors render as walls until discovered
                if tile.feature == "door_secret":
                    _, color, dim_val = _glyphs.TERRAIN_GLYPHS[Terrain.WALL]
                    # Match wall orientation from neighbors
                    glyph = self._wall_char_at(
                        level, mx, my, rounded=(mx, my) in _rounded_walls,
                    )
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
                            cfn = dim_color_fn(t, _active_theme.feature_dim)
                        row_out += cfn(glyph)
                        continue

                # Dug passages render as brown #
                if tile.dug_wall or tile.dug_floor:
                    glyph = "#"
                    color = "yellow"
                    dim_val = "bright_black"
                elif tile.is_corridor:
                    glyph, color, dim_val = _glyphs.CORRIDOR_GLYPH
                elif tile.terrain == Terrain.WALL:
                    _, color, dim_val = _glyphs.TERRAIN_GLYPHS[Terrain.WALL]
                    glyph = self._wall_char_at(
                        level, mx, my, rounded=(mx, my) in _rounded_walls,
                    )
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

        def _equip_name(eid: int | None) -> str:
            if eid is None:
                return ""
            d = world.get_component(eid, "Description")
            return d.name if d else "???"

        weapon_name = tr("combat.unarmed") if not equip or equip.weapon is None \
            else _equip_name(equip.weapon)

        # Compute AC: base 10 + DEX + armor defense + shield + helmet
        dex_bonus = stats.dexterity if stats else 0
        armor_def = 10 + dex_bonus
        equipped_ids: set[int] = set()
        if equip:
            for attr in ("weapon", "armor", "shield", "helmet",
                        "ring_left", "ring_right"):
                eid = getattr(equip, attr)
                if eid is not None:
                    equipped_ids.add(eid)
            # Body armor replaces base 10
            if equip.armor is not None:
                a = world.get_component(equip.armor, "Armor")
                if a:
                    armor_def = a.defense + a.magic_bonus + dex_bonus
            # Shield and helmet add defense + magic bonus
            if equip.shield is not None:
                a = world.get_component(equip.shield, "Armor")
                if a:
                    armor_def += a.defense + a.magic_bonus
            if equip.helmet is not None:
                a = world.get_component(equip.helmet, "Armor")
                if a:
                    armor_def += a.defense + a.magic_bonus
            # Ring bonuses to AC
            for ring_slot in ("ring_left", "ring_right"):
                ring_eid = getattr(equip, ring_slot)
                if ring_eid is not None:
                    ring = world.get_component(ring_eid, "Ring")
                    if ring and ring.effect == "evasion":
                        armor_def += 2
                    elif ring and ring.effect == "protection":
                        armor_def += 1

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
            "xp_next": player.xp_to_next if player else 1000,
            "gold": player.gold if player else 0,
            "str": stats.strength if stats else 0,
            "dex": stats.dexterity if stats else 0,
            "con": stats.constitution if stats else 0,
            "int": stats.intelligence if stats else 0,
            "wis": stats.wisdom if stats else 0,
            "cha": stats.charisma if stats else 0,
            "weapon": weapon_name,
            "armor_def": armor_def,
            "armor_name": _equip_name(equip.armor) if equip else "",
            "shield_name": _equip_name(equip.shield) if equip else "",
            "helmet_name": _equip_name(equip.helmet) if equip else "",
            "ring_left_name": _equip_name(equip.ring_left) if equip else "",
            "ring_right_name": _equip_name(equip.ring_right) if equip else "",
            "_equipped_ids": equipped_ids,
        }

    def _gather_inventory(
        self, world: World, player_id: int,
        equipped_ids: set[int] | None = None,
    ) -> tuple[list[str], int, int]:
        """Collect inventory item names, excluding equipped items.

        Returns (backpack_names, max_slots, total_slots_used).
        Total slots includes equipped items — per Knave rules all
        gear uses inventory slots whether equipped or not.
        """
        inv = world.get_component(player_id, "Inventory")
        if not inv:
            return [], 11, 0

        equipped = equipped_ids or set()
        names = []
        total_used = 0

        for item_id in inv.slots:
            # Count slot cost for ALL items
            slot_cost = 1
            wpn = world.get_component(item_id, "Weapon")
            if wpn:
                slot_cost = wpn.slots
            arm = world.get_component(item_id, "Armor")
            if arm:
                slot_cost = arm.slots
            total_used += slot_cost

            # Only show non-equipped in backpack list
            if item_id not in equipped:
                desc = world.get_component(item_id, "Description")
                names.append(desc.name if desc else "???")

        return names, inv.max_slots, total_used

    async def get_input(self) -> tuple[str, Any]:
        """Wait for keypress and return (intent, data)."""
        loop = asyncio.get_running_loop()
        val = await loop.run_in_executor(None, self._blocking_read)
        return map_key_to_intent(val)

    def _blocking_read(self) -> str:
        """Blocking key read."""
        with self.term.cbreak():
            val = self.term.inkey(timeout=None)
            if val.is_sequence:
                return val.name
            return str(val)

    def farlook_mode(
        self, world: World, level: Level, player_id: int, turn: int,
        start_x: int, start_y: int,
    ) -> None:
        """Interactive cursor to examine visible tiles.

        Arrow keys move the cursor, ESC/Enter/x exits.
        Displays information about creatures, items, and features
        at the cursor position.
        """
        t = self.term
        cx, cy = start_x, start_y
        pos = world.get_component(player_id, "Position")
        if not pos:
            return

        map_h = max(3, t.height - CHROME_HEIGHT)
        half_w = t.width // 2
        half_h = map_h // 2

        while True:
            # Render normal screen first
            self.render(world, level, player_id, turn)

            # Draw cursor on map
            scr_x = (cx - pos.x) + half_w
            scr_y = (cy - pos.y) + half_h
            if 0 <= scr_x < t.width and 0 <= scr_y < map_h:
                print(
                    t.move_xy(scr_x, scr_y) + t.reverse(" "),
                    end="", flush=True,
                )

            # Build description for cursor tile
            tile = level.tile_at(cx, cy)
            desc_parts: list[str] = []

            if tile and tile.visible:
                # Creatures
                for eid, _, cpos in world.query("AI", "Position"):
                    if cpos and cpos.x == cx and cpos.y == cy:
                        d = world.get_component(eid, "Description")
                        h = world.get_component(eid, "Health")
                        if d:
                            hp_str = ""
                            if h:
                                pct = h.current / h.maximum
                                if pct >= 1.0:
                                    hp_str = tr("health_status.uninjured")
                                elif pct > 0.5:
                                    hp_str = tr(
                                        "health_status.lightly_wounded")
                                elif pct > 0.25:
                                    hp_str = tr(
                                        "health_status.badly_wounded")
                                else:
                                    hp_str = tr("health_status.near_death")
                            desc_parts.append(
                                (d.short or d.name) + hp_str)

                # Chests
                for eid in list(world._entities):
                    epos = world.get_component(eid, "Position")
                    if (epos and epos.x == cx and epos.y == cy
                            and world.has_component(eid, "Chest")):
                        d = world.get_component(eid, "Description")
                        if d:
                            desc_parts.append(d.short or d.name)

                # Items on floor
                for eid, _, ipos in world.query("Description", "Position"):
                    if ipos and ipos.x == cx and ipos.y == cy:
                        if (not world.has_component(eid, "AI")
                                and not world.has_component(eid, "BlocksMovement")
                                and not world.has_component(eid, "Trap")
                                and eid != player_id):
                            d = world.get_component(eid, "Description")
                            if d:
                                desc_parts.append(d.short or d.name)

                # Tile feature
                if tile.feature and tile.feature != "door_secret":
                    fname = tr(f"feature.{tile.feature}")
                    if fname.startswith("feature."):
                        fname = tile.feature.replace("_", " ")
                    desc_parts.append(fname)

                # Terrain
                if not desc_parts:
                    terrain_name = tile.terrain.name.lower()
                    if tile.is_corridor:
                        terrain_name = "corridor"
                    desc_parts.append(terrain_name)

            # Display description on the input line
            info = f" ({cx},{cy}) {', '.join(desc_parts)}"
            input_y = map_h + STATUS_HEIGHT + LOG_HEIGHT
            print(
                t.move_xy(0, input_y)
                + t.bold(info[:t.width].ljust(t.width)),
                end="", flush=True,
            )

            # Read key
            with t.cbreak():
                val = t.inkey(timeout=None)
                key = val.name if val.is_sequence else str(val)

            if key in ("KEY_ESCAPE", "\x1b", "\n", "\r", "KEY_ENTER",
                        "x", "q"):
                break

            # Compute proposed new position
            nx, ny = cx, cy
            if key in ("KEY_UP", "k"):
                ny -= 1
            elif key in ("KEY_DOWN", "j"):
                ny += 1
            elif key in ("KEY_LEFT", "h"):
                nx -= 1
            elif key in ("KEY_RIGHT", "l"):
                nx += 1
            elif key == "y":
                nx -= 1; ny -= 1
            elif key == "u":
                nx += 1; ny -= 1
            elif key == "b":
                nx -= 1; ny += 1
            elif key == "n":
                nx += 1; ny += 1

            # Only move cursor to visible tiles
            new_tile = level.tile_at(nx, ny)
            if new_tile and new_tile.visible:
                cx, cy = nx, ny

    def fullmap_mode(
        self, world: World, level: Level, player_id: int, turn: int,
    ) -> None:
        """God mode: display the entire map with scrollable camera.

        Arrow keys pan the view, ESC/M exits.
        """
        t = self.term
        pos = world.get_component(player_id, "Position")
        if not pos:
            return

        map_h = max(3, t.height - CHROME_HEIGHT)
        cam_x, cam_y = pos.x, pos.y

        while True:
            output = t.home + t.clear
            output += self._render_map(
                world, level, cam_x, cam_y,
                0, 0, t.width, map_h,
            )

            # Info line at bottom
            info = (f" GOD MAP ({cam_x},{cam_y})"
                    f"  arrows/hjkl: pan  M/ESC: exit")
            input_y = map_h
            output += t.move_xy(0, input_y) + t.bold(
                info[:t.width].ljust(t.width))

            print(output, end="", flush=True)

            with t.cbreak():
                val = t.inkey(timeout=None)
                key = val.name if val.is_sequence else str(val)

            if key in ("KEY_ESCAPE", "\x1b", "M", "m", "q"):
                break

            # Pan camera
            step = 5
            if key in ("KEY_UP", "k"):
                cam_y = max(0, cam_y - step)
            elif key in ("KEY_DOWN", "j"):
                cam_y = min(level.height - 1, cam_y + step)
            elif key in ("KEY_LEFT", "h"):
                cam_x = max(0, cam_x - step)
            elif key in ("KEY_RIGHT", "l"):
                cam_x = min(level.width - 1, cam_x + step)
            elif key == "y":
                cam_x = max(0, cam_x - step)
                cam_y = max(0, cam_y - step)
            elif key == "u":
                cam_x = min(level.width - 1, cam_x + step)
                cam_y = max(0, cam_y - step)
            elif key == "b":
                cam_x = max(0, cam_x - step)
                cam_y = min(level.height - 1, cam_y + step)
            elif key == "n":
                cam_x = min(level.width - 1, cam_x + step)
                cam_y = min(level.height - 1, cam_y + step)
            elif key == "c":
                # Center on player
                cam_x, cam_y = pos.x, pos.y

    def show_ground_menu(
        self, items: list[tuple[int, str]],
    ) -> int | None:
        """Show a selection menu for items on the ground."""
        if not items:
            return None
        title = tr("ui.pickup_which")
        return self.show_selection_menu(title, items)

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
        return self.show_selection_menu(title, items)

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

        return self.show_selection_menu(title, items)

    def show_selection_menu(
        self, title: str, items: list[tuple[int, str]],
    ) -> int | None:
        """Draw a selection box. Returns selected EntityId."""
        theme = get_theme()
        t = self.term
        border = t.color_rgb(80, 140, 210) if theme.color_depth == "256" \
            else t.bright_cyan

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
            theme.box_tl + theme.box_h * left_fill
            + title_text + theme.box_h * right_fill + theme.box_tr
        )

        # Item lines
        for i, (_, name) in enumerate(items):
            letter = chr(ord("a") + i)
            entry = f"  {letter}) {name}"
            padded = entry[:inner].ljust(inner)
            output += t.move_xy(menu_x, menu_y + 1 + i)
            output += border(theme.box_v) + padded + border(theme.box_v)

        # Bottom border with centered ESC hint
        esc_text = " " + tr("ui.esc_cancel").strip() + " "
        esc_len = len(esc_text)
        left_fill = (inner - esc_len) // 2
        right_fill = max(0, inner - left_fill - esc_len)
        bot = menu_y + 1 + len(items)
        output += t.move_xy(menu_x, bot)
        output += border(
            theme.box_bl + theme.box_h * left_fill + esc_text
            + theme.box_h * right_fill + theme.box_br
        )

        print(output, end="", flush=True)

        with t.cbreak():
            val = t.inkey(timeout=None)
            key = str(val)

        if key == "\x1b" or val.name == "KEY_ESCAPE":
            return None

        if len(key) != 1:
            return None

        idx = ord(key) - ord("a")
        if 0 <= idx < len(items):
            return items[idx][0]
        return None

    def show_target_menu(
        self, world: World, level: Level, player_id: int,
        title: str,
    ) -> int | None:
        """Show a list of visible creatures to target. Returns entity ID."""
        pos = world.get_component(player_id, "Position")
        if not pos:
            return None

        targets: list[tuple[int, str]] = []
        for eid, ai, cpos in world.query("AI", "Position"):
            if cpos is None:
                continue
            tile = level.tile_at(cpos.x, cpos.y)
            if not tile or not tile.visible:
                continue
            desc = world.get_component(eid, "Description")
            name = desc.name if desc else "???"
            targets.append((eid, name))

        if not targets:
            return None

        return self.show_selection_menu(title, targets)

    def show_end_screen(
        self, won: bool, turn: int, killed_by: str = "",
    ) -> None:
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
            if killed_by:
                msg = tr("ui.death_cause", cause=killed_by)
            else:
                msg = tr("ui.death_desc")
            color = t.bright_red

        output += t.move_xy(cx - 8, cy - 1) + color(t.bold(title))
        output += t.move_xy(cx - len(msg) // 2, cy + 1) + msg
        footer = tr("ui.end_footer", turn=turn)
        output += t.move_xy(cx - len(footer) // 2, cy + 3) + t.bright_black(footer)

        print(output, end="", flush=True)

        with t.cbreak():
            t.inkey(timeout=None)
