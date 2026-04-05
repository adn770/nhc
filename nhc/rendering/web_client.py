"""WebSocket-based GameClient implementation.

Translates game events into JSON messages sent over WebSocket, and
receives player actions from the browser client.

Communication happens through queues:
- _out_queue: game thread puts JSON strings, sender thread sends via WS
- _in_queue: WS handler thread puts raw JSON strings, game thread reads
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
from typing import TYPE_CHECKING, Any

from nhc.dungeon.model import (
    CircleShape,
    HybridShape,
    OctagonShape,
    PillShape,
    Rect,
    TempleShape,
    Terrain,
)
from nhc.i18n import t as tr
from nhc.rendering.client import GameClient
from nhc.rendering.svg import render_floor_svg

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)


def _is_floor(level, x: int, y: int) -> bool:
    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    return t.terrain in (Terrain.FLOOR, Terrain.WATER, Terrain.GRASS)


_VISIBLE_DOOR_FEATURES = frozenset(
    {"door_closed", "door_open", "door_locked"})

_DOOR_FEATURES = frozenset(
    {"door_closed", "door_open", "door_locked", "door_secret"})

_POLYGON_TERRAINS = (
    Terrain.FLOOR, Terrain.WATER, Terrain.GRASS)


def _is_walkable(level, x: int, y: int) -> bool:
    """True iff the tile does NOT host a wall line from a
    neighbour's perspective. Mirrors svg.py's `_walkable`:
    FLOOR/WATER/GRASS terrain plus visible doors (closed, open,
    locked). Secret doors look like walls and are treated as
    non-walkable here so adjacent floor tiles see the usual
    wall-line at their shared edge.
    """
    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    if t.terrain not in _POLYGON_TERRAINS:
        return False
    if t.feature in _VISIBLE_DOOR_FEATURES:
        return True
    return t.feature != "door_secret"


def _in_polygon(level, x: int, y: int) -> bool:
    """True iff the tile should be part of the clearHatch
    polygon when visible/explored. All floor-family terrains
    qualify. Door tiles are further filtered by
    :func:`_door_polygon_gate` so they only join the polygon
    from the side the player can actually walk in from.
    """
    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    return t.terrain in _POLYGON_TERRAINS


# Offset from a door tile to the neighbour on the side opposite
# door_side. That neighbour is the "approach" side — the tile a
# player would step through to reach the door. Including the
# door tile in the polygon only when the approach side is in
# view keeps the polygon faithful to what the player can
# actually walk to from their current position.
_DOOR_OPPOSITE = {
    "east": (-1, 0),
    "west": (1, 0),
    "north": (0, 1),
    "south": (0, -1),
}


def _door_polygon_gate(level, x: int, y: int, field: str) -> bool:
    """Decide whether a door tile should join the polygon.

    Non-door tiles always return True. For door tiles, the
    neighbour opposite `door_side` must have the given flag
    (`visible` for per-turn reveal, `explored` for the bulk
    floor-init reveal). From the corridor/approach side the
    flag is set → door joins the polygon → the three-bit wall
    mask covers the door tile and its wall frame. From the far
    side the flag is unset → door stays out of the polygon →
    the far room's own wall halo at the shared edge renders
    the door visual without bleeding the corridor beyond.
    """
    tile = level.tile_at(x, y)
    if not tile or tile.feature not in _DOOR_FEATURES:
        return True
    if not tile.door_side:
        return True
    offset = _DOOR_OPPOSITE.get(tile.door_side)
    if offset is None:
        return True
    nb = level.tile_at(x + offset[0], y + offset[1])
    if nb is None:
        return False
    return bool(getattr(nb, field, False))


# Wall-edge bitmask: bit 0=N, 1=E, 2=S, 3=W. An edge is a wall
# iff the neighbour in that direction is not walkable (for
# ordinary tiles) or iff it is one of the two edges orthogonal
# to the door's own edge (for door tiles).
_WALL_N = 1
_WALL_E = 2
_WALL_S = 4
_WALL_W = 8


def _edge_is_wall(
    level, x: int, y: int,
    poly_cells: set[tuple[int, int]] | None = None,
) -> bool:
    """True iff the edge facing tile (x, y) contributes a wall
    line to its neighbour. Non-walkable tiles (walls, void) do.
    Door tiles of every kind — closed, open, locked, and secret
    — also do: a door replaces a wall segment, so the adjacent
    floor tile must still report a wall on that side. Keeping
    the bit set means the clearHatch polygon stays continuous
    across every door, even when the door tile itself is gated
    out of the polygon on the far side — the offset wall line
    runs straight past the door instead of notching inward
    where it sits.

    When *poly_cells* is supplied, a neighbour that is already
    in the polygon cell set is interior to the polygon and
    returns False regardless of walkability. This lets
    rect-expansion tiles (WALL tiles inside a circle/octagon
    room's bounding rect that have been explicitly added to the
    polygon) read as interior edges rather than spurious walls.
    Doors still short-circuit to True so the door frame rule
    wins over the expansion membership check.
    """
    t = level.tile_at(x, y)
    if t and t.feature in _DOOR_FEATURES:
        return True
    if poly_cells is not None and (x, y) in poly_cells:
        return False
    return not _is_walkable(level, x, y)


def _wall_mask(
    level, x: int, y: int,
    poly_cells: set[tuple[int, int]] | None = None,
) -> int:
    t = level.tile_at(x, y)
    if t and t.feature in _DOOR_FEATURES and t.door_side:
        # Door tiles get wall bits on three edges: the two
        # orthogonal edges (where the wall column continues)
        # and the door's own edge (where either the door visual
        # or the secret-door wall visual is drawn by the
        # client). The edge opposite to door_side is the
        # through direction — the side the player enters from
        # — and is left clear. In practice that neighbour is
        # always part of the FOV polygon too, so the edge is
        # interior and never traced regardless; leaving the
        # opposite bit off keeps the rule faithful to the
        # FOV-driven "only reveal what you see from your side"
        # behaviour.
        side = t.door_side
        if side == "east":
            return _WALL_N | _WALL_E | _WALL_S
        if side == "west":
            return _WALL_N | _WALL_W | _WALL_S
        if side == "north":
            return _WALL_N | _WALL_E | _WALL_W
        if side == "south":
            return _WALL_E | _WALL_S | _WALL_W
    mask = 0
    if _edge_is_wall(level, x, y - 1, poly_cells):
        mask |= _WALL_N
    if _edge_is_wall(level, x + 1, y, poly_cells):
        mask |= _WALL_E
    if _edge_is_wall(level, x, y + 1, poly_cells):
        mask |= _WALL_S
    if _edge_is_wall(level, x - 1, y, poly_cells):
        mask |= _WALL_W
    return mask


_EXPAND_SHAPES = (CircleShape, OctagonShape, PillShape, TempleShape)


def _rect_cells(rect: "Rect") -> set[tuple[int, int]]:
    return {
        (x, y)
        for y in range(rect.y, rect.y2)
        for x in range(rect.x, rect.x2)
    }


def _polygon_rect_expansions(
    level: "Level",
) -> list[tuple[set[tuple[int, int]], set[tuple[int, int]]]]:
    """Per-room rectangular expansions for the clearHatch
    polygon.

    Circle and octagon rooms paint walls that extend beyond
    their floor tiles — into the rect corners clipped by the
    shape. Those corner tiles remain WALL/VOID terrain and are
    excluded from the normal polygon, so the hatching bleeds
    through the wall stroke. To fix it, treat each such room
    as its bounding rect for polygon purposes. For hybrid rooms
    the same expansion is applied per half: only the sub-halves
    whose shape is circle/octagon get inflated; rect sub-halves
    already cover their half naturally via floor_tiles.

    Returns a list of ``(rect_cells, trigger_cells)``: the tile
    set to include in the polygon and the sub-shape's own floor
    tiles whose visibility (or explored-ness) gates the
    expansion on. A room only expands once the player has
    actually entered it — otherwise memory of a still-hidden
    circular room would leak rect coverage onto the map.
    """
    out: list[tuple[set[tuple[int, int]], set[tuple[int, int]]]] = []
    for room in level.rooms:
        shape = room.shape
        rect = room.rect
        if shape is None:
            continue
        if isinstance(shape, _EXPAND_SHAPES):
            out.append((_rect_cells(rect), shape.floor_tiles(rect)))
            continue
        if isinstance(shape, HybridShape):
            if shape.split == "vertical":
                mid = rect.x + rect.width // 2
                left_rect = Rect(
                    rect.x, rect.y, mid - rect.x, rect.height,
                )
                right_rect = Rect(
                    mid, rect.y, rect.x2 - mid, rect.height,
                )
            else:
                mid = rect.y + rect.height // 2
                left_rect = Rect(
                    rect.x, rect.y, rect.width, mid - rect.y,
                )
                right_rect = Rect(
                    rect.x, mid, rect.width, rect.y2 - mid,
                )
            for sub, sub_rect in (
                (shape.left, left_rect),
                (shape.right, right_rect),
            ):
                if isinstance(sub, _EXPAND_SHAPES):
                    out.append((
                        _rect_cells(sub_rect),
                        sub.floor_tiles(sub_rect),
                    ))
    return out


def _active_expansion_cells(
    level: "Level",
    expansions: list[
        tuple[set[tuple[int, int]], set[tuple[int, int]]]
    ],
    field: str,
) -> set[tuple[int, int]]:
    """Union of rect-expansion cells whose trigger floor tiles
    have the given visibility field set on at least one tile."""
    active: set[tuple[int, int]] = set()
    for rect_cells, trigger_cells in expansions:
        for (tx, ty) in trigger_cells:
            tile = level.tile_at(tx, ty)
            if tile and getattr(tile, field, False):
                active |= rect_cells
                break
    return active


class _WebNarrativeLog:
    """Minimal narrative log for typed mode in the web client.

    Mechanical messages (player input echo) are sent to the browser
    as regular messages so they appear in the history log.
    """

    def __init__(self, client: "WebClient") -> None:
        self._client = client

    def add_mechanical(self, text: str) -> None:
        self._client.add_message(text)


class WebClient(GameClient):
    """GameClient that communicates over a WebSocket connection.

    The WebSocket is managed by ws.py — this class only uses queues.
    """

    def __init__(
        self, game_mode: str = "classic", lang: str = "ca",
    ) -> None:
        self.game_mode = game_mode
        self.edge_doors = True  # web: doors on tile edges
        self.lang = lang
        self.messages: list[str] = []
        self.floor_svg: str = ""
        self.floor_svg_id: str = ""
        self._last_static_stats: dict | None = None
        self._last_inv_hash: int = 0
        self._last_fov: set[tuple[int, int]] = set()
        self._last_walk: dict[tuple[int, int], int] = {}
        self._base_url: str = ""
        self._ws = None
        self._in_queue: queue.Queue = queue.Queue()
        self._out_queue: queue.Queue = queue.Queue()
        self.narrative_log = _WebNarrativeLog(self)

    def set_ws(self, ws, base_url: str = "") -> None:
        """Attach the WebSocket (kept for reference only)."""
        self._ws = ws
        if base_url:
            self._base_url = base_url

    # ── Helpers ──────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        """Queue a JSON message for the sender thread."""
        data = json.dumps(msg)
        msg_type = msg.get("type", "?")
        if msg_type == "floor":
            logger.debug("QUEUE SEND: type=floor, %d bytes", len(data))
        elif msg_type == "state":
            n_ent = len(msg.get("entities", []))
            logger.debug("QUEUE SEND: type=state, %d entities, turn=%s",
                         n_ent, msg.get("turn"))
        else:
            logger.debug("QUEUE SEND: type=%s", msg_type)
        self._out_queue.put(data)

    def _recv(self) -> dict:
        """Read from the input queue (blocking)."""
        try:
            raw = self._in_queue.get(timeout=30)
            if isinstance(raw, dict):
                return raw
            msg = json.loads(raw)
            logger.debug("QUEUE RECV: %s", msg.get("type", "?"))
            return msg
        except queue.Empty:
            logger.debug("QUEUE RECV: timeout")
            return {}
        except Exception:
            logger.exception("QUEUE RECV: error")
            return {}

    def _gather_entities(
        self, world: "World", level: "Level",
        player_id: int = -1,
    ) -> list[dict]:
        """Build entity list for the client.

        Always includes the player regardless of visibility checks.
        """
        entities = []
        for eid in list(world._entities):
            pos = world.get_component(eid, "Position")
            rend = world.get_component(eid, "Renderable")
            if not pos or not rend:
                continue
            # Hidden traps are invisible until detected
            trap = world.get_component(eid, "Trap")
            if trap and trap.hidden:
                continue
            # Always include player; others need visible tile
            if eid != player_id:
                tile = level.tile_at(pos.x, pos.y)
                if not tile or not tile.visible:
                    continue
            entry = {
                "id": eid,
                "x": pos.x,
                "y": pos.y,
                "glyph": rend.glyph,
                "color": rend.color,
            }
            health = world.get_component(eid, "Health")
            if health:
                entry["hp"] = health.current
                entry["max_hp"] = health.maximum
            desc = world.get_component(eid, "Description")
            if desc:
                entry["name"] = desc.name
            entities.append(entry)
        return entities

    def _gather_stats(
        self, world: "World", player_id: int, turn: int,
        level: "Level",
    ) -> dict:
        """Collect player stats for the status bar."""
        health = world.get_component(player_id, "Health")
        stats = world.get_component(player_id, "Stats")
        equip = world.get_component(player_id, "Equipment")
        player = world.get_component(player_id, "Player")
        pdesc = world.get_component(player_id, "Description")

        def _name(eid):
            if eid is None:
                return ""
            d = world.get_component(eid, "Description")
            return d.name if d else "???"

        weapon = tr("combat.unarmed")
        if equip and equip.weapon is not None:
            weapon = _name(equip.weapon)

        dex = stats.dexterity if stats else 0
        ac = 10 + dex
        if equip:
            if equip.armor is not None:
                a = world.get_component(equip.armor, "Armor")
                if a:
                    ac = a.defense + a.magic_bonus + dex
            for slot in ("shield", "helmet"):
                eid = getattr(equip, slot)
                if eid is not None:
                    a = world.get_component(eid, "Armor")
                    if a:
                        ac += a.defense + a.magic_bonus

        ac_label = tr("ui.ac")

        # Gather inventory items (non-equipped)
        inv = world.get_component(player_id, "Inventory")
        equipped_ids = set()
        armor_name = shield_name = helmet_name = ""
        ring_left_name = ring_right_name = ""
        if equip:
            for attr in ("weapon", "armor", "shield", "helmet",
                         "ring_left", "ring_right"):
                eid = getattr(equip, attr)
                if eid is not None:
                    equipped_ids.add(eid)
            armor_name = _name(equip.armor) if equip.armor else ""
            shield_name = _name(equip.shield) if equip.shield else ""
            helmet_name = _name(equip.helmet) if equip.helmet else ""
            ring_left_name = _name(equip.ring_left) \
                if equip.ring_left else ""
            ring_right_name = _name(equip.ring_right) \
                if equip.ring_right else ""

        items = []
        total_used = 0
        max_slots = inv.max_slots if inv else 10
        if inv:
            for item_id in inv.slots:
                slot_cost = 1
                wpn = world.get_component(item_id, "Weapon")
                if wpn:
                    slot_cost = wpn.slots
                arm = world.get_component(item_id, "Armor")
                if arm:
                    slot_cost = arm.slots
                total_used += slot_cost

                d = world.get_component(item_id, "Description")
                # Build type flags
                types = []
                if wpn:
                    types.append("weapon")
                if arm:
                    slot_type = arm.slot  # "body", "shield", "helmet"
                    types.append(
                        "armor" if slot_type == "body" else slot_type
                    )
                cons = world.get_component(item_id, "Consumable")
                if cons:
                    types.append("consumable")
                wnd = world.get_component(item_id, "Wand")
                if wnd:
                    types.append("wand")
                ring = world.get_component(item_id, "Ring")
                if ring:
                    types.append("ring")
                if world.has_component(item_id, "Throwable"):
                    types.append("throwable")

                charges = None
                if wnd:
                    charges = [wnd.charges, wnd.max_charges]

                if item_id not in equipped_ids:
                    items.append({
                        "id": item_id,
                        "name": d.name if d else "???",
                        "equipped": False,
                        "types": types,
                        "charges": charges,
                    })

        # Build equipped items list for inventory panel
        equipped_items = []
        if equip:
            slot_type_map = {
                "weapon": "weapon",
                "armor": "armor",
                "shield": "shield",
                "helmet": "helmet",
                "ring_left": "ring",
                "ring_right": "ring",
            }
            for attr, typ in slot_type_map.items():
                eid = getattr(equip, attr)
                if eid is not None:
                    d = world.get_component(eid, "Description")
                    equipped_items.append({
                        "id": eid,
                        "name": d.name if d else "???",
                        "equipped": True,
                        "types": [typ],
                    })

        static = {
            "char_name": pdesc.name if pdesc else "?",
            "char_bg": pdesc.short if pdesc else "",
            "level_name": level.name,
            "depth": level.depth,
            "hp_max": health.maximum if health else 0,
            "str": stats.strength if stats else 0,
            "dex": dex,
            "con": stats.constitution if stats else 0,
            "int": stats.intelligence if stats else 0,
            "wis": stats.wisdom if stats else 0,
            "cha": stats.charisma if stats else 0,
            "xp_next": player.xp_to_next if player else 1000,
            "slots_max": max_slots,
            "ac_label": ac_label,
        }
        hunger = world.get_component(player_id, "Hunger")
        dynamic = {
            "turn": turn,
            "hunger": hunger.current if hunger else 900,
            "hunger_max": hunger.maximum if hunger else 1200,
            "plevel": player.level if player else 1,
            "xp": player.xp if player else 0,
            "gold": player.gold if player else 0,
            "hp": health.current if health else 0,
            "weapon": weapon,
            "armor_name": armor_name,
            "shield_name": shield_name,
            "helmet_name": helmet_name,
            "ring_left_name": ring_left_name,
            "ring_right_name": ring_right_name,
            "ac": ac,
            "items": items,
            "equipped_items": equipped_items,
            "slots_used": total_used,
        }
        return static, dynamic

    def _ui_labels(self) -> dict[str, str]:
        """Return all translated UI labels for the web client.

        Delivered once via /labels.json at game start.  Covers
        toolbar tooltips, context menus, inventory panel, help
        dialog, game over screen, loading text, and other
        player-facing chrome.
        """
        return {
            # Context menu actions
            "use": tr("ui.action_use"),
            "quaff": tr("ui.action_quaff"),
            "zap": tr("ui.action_zap"),
            "equip": tr("ui.action_equip"),
            "unequip": tr("ui.action_unequip"),
            "drop": tr("ui.action_drop"),
            "throw": tr("ui.action_throw"),
            # Toolbar
            "toolbar_pickup": tr("ui.toolbar_pickup"),
            "toolbar_inventory": tr("ui.toolbar_inventory"),
            "toolbar_quaff": tr("ui.toolbar_quaff"),
            "toolbar_use_item": tr("ui.toolbar_use_item"),
            "toolbar_equip": tr("ui.toolbar_equip"),
            "toolbar_drop": tr("ui.toolbar_drop"),
            "toolbar_throw": tr("ui.toolbar_throw"),
            "toolbar_zap": tr("ui.toolbar_zap"),
            "toolbar_search": tr("ui.toolbar_search"),
            "toolbar_wait": tr("ui.toolbar_wait"),
            "toolbar_pick_lock": tr("ui.toolbar_pick_lock"),
            "toolbar_force_door": tr("ui.toolbar_force_door"),
            "toolbar_close_door": tr("ui.toolbar_close_door"),
            "toolbar_farlook": tr("ui.toolbar_farlook"),
            "toolbar_descend": tr("ui.toolbar_descend"),
            "toolbar_ascend": tr("ui.toolbar_ascend"),
            "toolbar_zoom_in": tr("ui.toolbar_zoom_in"),
            "toolbar_zoom_out": tr("ui.toolbar_zoom_out"),
            "toolbar_restart": tr("ui.toolbar_restart"),
            "toolbar_debug": tr("ui.toolbar_debug"),
            # Inventory panel
            "empty": tr("ui.empty"),
            "inventory_title": tr("ui.inventory_title"),
            "equipment_section": tr("ui.equipment_section"),
            "backpack_section": tr("ui.backpack_section"),
            "inventory_empty": tr("ui.inventory_empty"),
            "close_button": tr("ui.close_button"),
            # Help dialog
            "help_title": tr("ui.help_title"),
            "help_loading": tr("ui.help_loading"),
            "help_close_hint": tr("ui.help_close_hint"),
            "help_unavailable": tr("ui.help_unavailable"),
            "help_button": tr("ui.help_button"),
            # Game over
            "victory_title": tr("ui.victory_title"),
            "death_title": tr("ui.death_title"),
            "death_cause": tr("ui.death_cause"),
            "end_footer": tr("ui.end_footer"),
            "game_continue": tr("ui.game_continue"),
            # Loading / farlook / help command
            "loading_generate": tr("ui.loading_generate"),
            "loading_resume": tr("ui.loading_resume"),
            "farlook_hint": tr("ui.farlook_hint"),
            "help_command": tr("ui.help_command"),
            # Restart confirmation
            "restart_confirm": tr("ui.restart_confirm"),
            "restart_yes": tr("ui.restart_yes"),
            "restart_cancel": tr("ui.restart_cancel"),
            # Mode indicator
            "mode_classic_tag": tr("ui.mode_classic_tag"),
            "mode_typed_tag": tr("ui.mode_typed_tag"),
            # Input
            "input_placeholder": tr("ui.input_placeholder"),
            # Status bar abbreviations
            "lv": tr("stats.lv"),
            "xp": tr("stats.xp"),
            # Ability score abbreviations
            "stat_str": tr("stats.str"),
            "stat_dex": tr("stats.dex"),
            "stat_con": tr("stats.con"),
            "stat_int": tr("stats.int"),
            "stat_wis": tr("stats.wis"),
            "stat_cha": tr("stats.cha"),
            # Hunger states
            "hunger_satiated": tr("ui.hunger_satiated"),
            "hunger_normal": tr("ui.hunger_normal"),
            "hunger_hungry": tr("ui.hunger_hungry"),
            "hunger_starving": tr("ui.hunger_starving"),
            # Ranking / leaderboard
            "ranking_button": tr("ui.ranking_button"),
            "ranking_title": tr("ui.ranking_title"),
            "ranking_empty": tr("ui.ranking_empty"),
            "ranking_col_rank": tr("ui.ranking_col_rank"),
            "ranking_col_name": tr("ui.ranking_col_name"),
            "ranking_col_score": tr("ui.ranking_col_score"),
            "ranking_col_depth": tr("ui.ranking_col_depth"),
            "ranking_col_turns": tr("ui.ranking_col_turns"),
            "ranking_col_fate": tr("ui.ranking_col_fate"),
            "ranking_fate_won": tr("ui.ranking_fate_won"),
            "ranking_fate_died": tr("ui.ranking_fate_died"),
            "ranking_close": tr("ui.ranking_close"),
        }

    def _gather_doors(
        self, level: "Level",
    ) -> list[dict]:
        """Build door list for the client."""
        doors = []
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tile_at(x, y)
                if not tile or not tile.visible:
                    continue
                if tile.feature not in ("door_closed", "door_open",
                                        "door_locked", "door_secret"):
                    continue
                side = tile.door_side
                # vertical = wall runs top-bottom (side is east/west)
                vertical = side in ("east", "west")
                # Map door_side to the edge of the tile the wall is on
                edge_map = {
                    "east": "right", "west": "left",
                    "south": "bottom", "north": "top",
                }
                edge = edge_map.get(side, "left")
                doors.append({
                    "x": x, "y": y,
                    "state": tile.feature,
                    "vertical": vertical,
                    "edge": edge,
                })
        return doors

    def _gather_fov(self, level: "Level") -> list[list[int]]:
        """Build list of visible tile coordinates."""
        visible = []
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tile_at(x, y)
                if tile and tile.visible:
                    visible.append([x, y])
        return visible

    def _gather_hatch_debug(
        self, level: "Level",
    ) -> dict:
        """Debug snapshot of the clearHatch polygon pipeline.

        Returns the current walkable tile set, the raw tile-
        perimeter loops, the expanded (2px wall-offset) loops,
        and verbose per-tile detail for every tile that is a
        door or orthogonally adjacent to one. The geometry is
        computed by :mod:`nhc.rendering.hatch_polygon`, which
        is a line-for-line Python port of the JS algorithm in
        ``map.js``, so the debug export mirrors exactly what
        the browser draws.
        """
        from nhc.rendering.hatch_polygon import (
            build_tile_set_polygons,
            offset_loop,
        )

        # Must match map.js constants.
        cell_size = 32
        padding = 32
        offset_px = 2

        walk = self._gather_walk(level)
        walls_map: dict[tuple[int, int], int] = {
            (e[0], e[1]): e[2] for e in walk
        }

        raw_loops = build_tile_set_polygons(
            walls_map, cell_size, padding)
        expanded_loops = [
            offset_loop(loop, offset_px) for loop in raw_loops
        ]

        # Per-tile detail for doors and tiles touching a door.
        directions = (
            ("n", 0, -1),
            ("e", 1, 0),
            ("s", 0, 1),
            ("w", -1, 0),
        )

        def _tile_summary(tx: int, ty: int) -> dict:
            t = level.tile_at(tx, ty)
            if t is None:
                return {"x": tx, "y": ty, "in_bounds": False}
            return {
                "x": tx, "y": ty,
                "terrain": t.terrain.name,
                "feature": t.feature,
                "door_side": t.door_side or None,
                "visible": bool(t.visible),
                "explored": bool(t.explored),
                "walkable": _is_walkable(level, tx, ty),
                "in_polygon": _in_polygon(level, tx, ty),
            }

        door_neighbourhood: list[dict] = []
        for (x, y), mask in walls_map.items():
            tile = level.tile_at(x, y)
            is_door = (tile is not None
                       and tile.feature in _DOOR_FEATURES)
            adj_door = False
            for _, dx, dy in directions:
                nb = level.tile_at(x + dx, y + dy)
                if nb and nb.feature in _DOOR_FEATURES:
                    adj_door = True
                    break
            if not (is_door or adj_door):
                continue
            entry = _tile_summary(x, y)
            entry["wall_mask"] = mask
            entry["is_door"] = is_door
            entry["adjacent_to_door"] = adj_door
            entry["neighbours"] = {
                name: _tile_summary(x + dx, y + dy)
                for name, dx, dy in directions
            }
            if is_door:
                entry["door_polygon_gate"] = _door_polygon_gate(
                    level, x, y, "visible")
            door_neighbourhood.append(entry)
        door_neighbourhood.sort(key=lambda e: (e["y"], e["x"]))

        return {
            "cell_size": cell_size,
            "padding": padding,
            "offset_px": offset_px,
            "tile_count": len(walk),
            "loop_count": len(raw_loops),
            "walls": walk,
            "loops_raw": [
                [e.to_dict() for e in loop] for loop in raw_loops
            ],
            "loops_expanded": [
                [{"x": x, "y": y} for (x, y) in loop]
                for loop in expanded_loops
            ],
            "door_neighbourhood": door_neighbourhood,
        }

    def _gather_walk(
        self, level: "Level",
    ) -> list[list[int]]:
        """Visible polygon-eligible tiles with 4-bit wall masks.

        Each entry is [x, y, mask] where mask has bit 0=N, 1=E,
        2=S, 3=W set iff that tile edge is a wall line. For
        ordinary floor tiles this tracks svg.py's wall-line
        rule; for door tiles the three edges flanking the door
        are walls and the door is only included when the
        approach-side neighbour is also visible — so it joins
        the corridor polygon without leaking into the room on
        the far side. Circle and octagon rooms expand to their
        bounding rect (or half-rect for circular/octagonal sub-
        halves of hybrid rooms) so the walls drawn beyond the
        tile footprint are still covered by clearHatch.
        """
        expansions = _polygon_rect_expansions(level)
        expansion_cells = _active_expansion_cells(
            level, expansions, "visible")
        normal_cells: set[tuple[int, int]] = set()
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tile_at(x, y)
                if not tile or not tile.visible:
                    continue
                if not _in_polygon(level, x, y):
                    continue
                if not _door_polygon_gate(level, x, y, "visible"):
                    continue
                normal_cells.add((x, y))
        poly_cells = normal_cells | expansion_cells
        out: list[list[int]] = []
        for (x, y) in sorted(poly_cells):
            mask = _wall_mask(level, x, y, poly_cells)
            out.append([x, y, mask])
        return out

    def _gather_explored(
        self, level: "Level",
    ) -> list[list[int]]:
        """All explored tiles with a wall-mask sentinel.

        Used only on floor init and reconnects. Each entry is
        [x, y, mask]: mask = 0..15 for polygon-eligible tiles
        (including doors that pass the approach-side gate, and
        rect-expansion tiles from visited circle/octagon rooms),
        or -1 for non-polygon tiles (walls/void, plus door
        tiles that were only seen from the far side). The
        client splits the list into two structures: all keys
        feed the drawFog dim-memory set, mask >= 0 entries feed
        the bulk clearHatch polygon.
        """
        expansions = _polygon_rect_expansions(level)
        expansion_cells = _active_expansion_cells(
            level, expansions, "explored")
        normal_cells: set[tuple[int, int]] = set()
        explored_tiles: list[tuple[int, int]] = []
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tile_at(x, y)
                if not tile or not tile.explored:
                    continue
                explored_tiles.append((x, y))
                if (_in_polygon(level, x, y)
                        and _door_polygon_gate(
                            level, x, y, "explored")):
                    normal_cells.add((x, y))
        poly_cells = normal_cells | expansion_cells
        # Expansion cells may reference WALL tiles whose
        # `explored` flag is unset — emit them alongside the
        # explored tiles so drawFog and clearHatch stay in sync.
        emitted: set[tuple[int, int]] = set(explored_tiles)
        for cell in expansion_cells:
            if cell not in emitted:
                explored_tiles.append(cell)
                emitted.add(cell)
        out: list[list[int]] = []
        for (x, y) in explored_tiles:
            if (x, y) in poly_cells:
                mask = _wall_mask(level, x, y, poly_cells)
            else:
                mask = -1
            out.append([x, y, mask])
        return out

    def _gather_debug_data(self, level: "Level") -> dict:
        """Build debug overlay data for god mode panel."""

        # Rooms
        rooms = []
        for i, room in enumerate(level.rooms):
            r = room.rect
            shape = room.shape
            name = type(shape).__name__.replace("Shape", "").lower()
            if isinstance(shape, HybridShape):
                left = type(shape.left).__name__.replace(
                    "Shape", "").lower()
                right = type(shape.right).__name__.replace(
                    "Shape", "").lower()
                axis = "v" if shape.split == "vertical" else "h"
                name = f"hybrid({left}+{right},{axis})"
            rooms.append({
                "index": i, "x": r.x, "y": r.y,
                "w": r.width, "h": r.height, "shape": name,
            })

        # Corridors — flood-fill connected corridor tiles
        corridor_tiles: set[tuple[int, int]] = set()
        for y, row in enumerate(level.tiles):
            for x, tile in enumerate(row):
                if tile.terrain == Terrain.FLOOR and tile.is_corridor:
                    corridor_tiles.add((x, y))

        corridors = []
        visited: set[tuple[int, int]] = set()
        for start in sorted(corridor_tiles):
            if start in visited:
                continue
            seg: list[tuple[int, int]] = []
            queue = [start]
            while queue:
                pos = queue.pop()
                if pos in visited:
                    continue
                visited.add(pos)
                seg.append(pos)
                px, py = pos
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (px + dx, py + dy)
                    if nb in corridor_tiles and nb not in visited:
                        queue.append(nb)
            seg.sort()
            mid = seg[len(seg) // 2]
            corridors.append({
                "index": len(corridors),
                "cx": mid[0], "cy": mid[1],
                "tile_count": len(seg),
            })

        # Doors — all door tiles with index and type
        abbrev = {
            "door_closed": "C", "door_open": "O",
            "door_secret": "S", "door_locked": "L",
        }
        doors = []
        for y, row in enumerate(level.tiles):
            for x, tile in enumerate(row):
                if tile.feature in abbrev:
                    doors.append({
                        "index": len(doors), "x": x, "y": y,
                        "kind": abbrev[tile.feature],
                        "side": tile.door_side,
                    })

        return {
            "level_id": level.id,
            "level_depth": level.depth,
            "floor_svg_id": self.floor_svg_id,
            "rooms": rooms,
            "corridors": corridors,
            "doors": doors,
            "fov_radius": 8,
            "map_width": level.width,
            "map_height": level.height,
        }

    # ── Lifecycle ────────────────────────────────────────────────

    def initialize(self) -> None:
        """Called during Game.initialize() — WS not connected yet.

        Floor SVG is sent later from ws.py when the WS connects.
        """
        logger.debug("WebClient.initialize() — floor_svg=%d bytes",
                      len(self.floor_svg) if self.floor_svg else 0)

    def shutdown(self) -> None:
        """Notify client that the session is ending."""
        self._send({"type": "shutdown"})

    def send_floor_change(
        self, level: "Level", world: "World",
        player_id: int, turn: int, seed: int = 0,
        floor_svg: str | None = None,
        floor_svg_id: str | None = None,
        hatch_distance: float = 2.0,
    ) -> None:
        """Send new floor SVG to the client.

        Called on floor transitions (descend/ascend stairs).
        If *floor_svg* is provided, skips rendering (cache hit).
        Resets FOV/hatch delta tracking so the next render sends
        full state for the new level.
        """
        import uuid as _uuid
        if floor_svg and floor_svg_id:
            self.floor_svg = floor_svg
            self.floor_svg_id = floor_svg_id
            logger.info("Floor SVG cache hit: %s (%d bytes)",
                        floor_svg_id, len(floor_svg))
        else:
            self.floor_svg = render_floor_svg(
                level, seed=seed, hatch_distance=hatch_distance,
            )
            self.floor_svg_id = _uuid.uuid4().hex[:12]
            logger.info("Floor SVG rendered: %s (%d bytes)",
                        self.floor_svg_id, len(self.floor_svg))

        # Reset delta tracking for the new floor
        self._last_fov = set()
        walk = self._gather_walk(level)
        self._last_walk = {(e[0], e[1]): e[2] for e in walk}

        entities = self._gather_entities(world, level, player_id)
        fov = self._gather_fov(level)
        doors = self._gather_doors(level)
        explored = self._gather_explored(level)

        meta = level.metadata
        self._send({
            "type": "floor",
            "floor_url": (f"{self._base_url}"
                          f"/floor/{self.floor_svg_id}.svg"),
            "hatch_url": "/api/hatch.svg",
            "entities": entities,
            "doors": doors,
            "fov": fov,
            "walk": walk,
            "explored": explored,
            "turn": turn,
            "theme": meta.theme if meta else "dungeon",
            "feeling": meta.feeling if meta else "normal",
        })

    # ── Display ──────────────────────────────────────────────────

    def add_message(self, text: str) -> None:
        logger.info("MSG: %s", text)
        self.messages.append(text)
        if len(self.messages) > 200:
            self.messages = self.messages[-200:]
        self._send({"type": "message", "text": text})

    def render(
        self,
        world: "World",
        level: "Level",
        player_id: int,
        turn: int,
    ) -> None:
        entities = self._gather_entities(world, level, player_id)
        fov_list = self._gather_fov(level)
        doors = self._gather_doors(level)
        static, dynamic = self._gather_stats(
            world, player_id, turn, level)

        # FOV delta encoding — send add/del instead of full list
        current_fov = {(t[0], t[1]) for t in fov_list}
        prev_fov = self._last_fov
        fov_add = current_fov - prev_fov
        fov_del = prev_fov - current_fov
        self._last_fov = current_fov

        # Walkable-visible + wall-mask delta tracking. Drives
        # the client's clearHatch polygon: wall-edges get the
        # 10% outward offset; non-wall boundary edges stay flush.
        walk_list = self._gather_walk(level)
        current_walk = {(e[0], e[1]): e[2] for e in walk_list}
        prev_walk = self._last_walk
        walk_add_items = [
            [x, y, m] for (x, y), m in current_walk.items()
            if prev_walk.get((x, y)) != m
        ]
        walk_del_items = [
            [x, y] for (x, y) in prev_walk
            if (x, y) not in current_walk
        ]
        self._last_walk = current_walk

        state_msg: dict = {
            "type": "state",
            "entities": entities,
            "doors": doors,
            "turn": turn,
        }
        if (not prev_fov
                or len(fov_add) + len(fov_del)
                > len(current_fov) * 0.5):
            # First send or large change — send full FOV
            state_msg["fov"] = fov_list
        else:
            state_msg["fov_add"] = [[x, y] for x, y in fov_add]
            state_msg["fov_del"] = [[x, y] for x, y in fov_del]
        if (not prev_walk
                or len(walk_add_items) + len(walk_del_items)
                > len(current_walk) * 0.5):
            state_msg["walk"] = walk_list
        else:
            if walk_add_items:
                state_msg["walk_add"] = walk_add_items
            if walk_del_items:
                state_msg["walk_del"] = walk_del_items
        self._send(state_msg)
        # Send static stats only when they change
        if static != self._last_static_stats:
            self._send({"type": "stats_init", **static})
            self._last_static_stats = static
        # Only include inventory when it changes
        inv_hash = hash(str(dynamic.get("items", [])))
        if inv_hash != self._last_inv_hash:
            self._last_inv_hash = inv_hash
        else:
            dynamic.pop("items", None)
        self._send({"type": "stats", **dynamic})

    def scroll_messages(self, direction: int) -> None:
        self._send({"type": "scroll", "direction": direction})

    def show_help(self) -> None:
        self._send({"type": "help"})

    def show_end_screen(
        self, won: bool, turn: int, killed_by: str = "",
    ) -> None:
        self._send({
            "type": "game_over",
            "won": won,
            "turn": turn,
            "killed_by": killed_by,
        })
        # Wait for client acknowledgment before game loop exits
        if self._ws:
            time.sleep(0.5)  # give sender thread time to flush
            self._recv()  # wait for client ack

    # ── Input ────────────────────────────────────────────────────

    async def get_input(self) -> tuple[str, Any]:
        """Wait for player action from input queue.

        Blocks until a real player action arrives. Timeouts and
        empty messages are retried so they don't consume turns.
        Returns ("disconnect", None) when the WebSocket disconnects.
        """
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, self._recv)
            msg_type = msg.get("type", "")
            if msg_type == "disconnect":
                return ("disconnect", None)
            if msg_type == "action":
                return (msg.get("intent", "wait"), msg.get("data"))
            if msg_type == "typed":
                return ("typed", msg.get("text", ""))
            if msg_type == "click":
                return ("click", {"x": msg.get("x"), "y": msg.get("y")})
            if msg_type == "item_action":
                return ("item_action", {
                    "action": msg.get("action"),
                    "item_id": msg.get("item_id"),
                })
            # Empty/timeout/unknown: retry, don't return "wait"

    async def get_typed_input(
        self,
        world: "World",
        level: "Level",
        player_id: int,
        turn: int,
    ) -> str | tuple[str, Any]:
        """Wait for typed input from the browser."""
        self.render(world, level, player_id, turn)
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, self._recv)
            msg_type = msg.get("type", "")
            if msg_type == "typed":
                return msg.get("text", "")
            if msg_type == "action":
                return (msg.get("intent", "wait"), msg.get("data"))
            # Empty/timeout: retry

    # ── Menus ────────────────────────────────────────────────────

    def _request_menu(
        self, title: str, items: list[tuple[int, str]],
    ) -> int | None:
        """Send a menu to the client and wait for selection."""
        options = [{"id": eid, "name": name} for eid, name in items]
        self._send({
            "type": "menu",
            "title": title,
            "options": options,
        })
        resp = self._recv()
        if resp.get("type") == "menu_select":
            return resp.get("choice")
        return None

    def show_inventory_menu(
        self, world: "World", player_id: int, prompt: str = "",
    ) -> int | None:
        inv = world.get_component(player_id, "Inventory")
        if not inv or not inv.slots:
            return None
        items = []
        for item_id in inv.slots:
            desc = world.get_component(item_id, "Description")
            items.append((item_id, desc.name if desc else "???"))
        title = prompt or tr("ui.use_which")
        return self._request_menu(title, items)

    def show_filtered_inventory(
        self, world: "World", player_id: int,
        title: str,
        filter_component: str | None = None,
    ) -> int | None:
        inv = world.get_component(player_id, "Inventory")
        if not inv or not inv.slots:
            return None
        items = []
        for item_id in inv.slots:
            if filter_component and not world.has_component(
                item_id, filter_component,
            ):
                continue
            desc = world.get_component(item_id, "Description")
            items.append((item_id, desc.name if desc else "???"))
        if not items:
            return None
        return self._request_menu(title, items)

    def show_ground_menu(
        self, items: list[tuple[int, str]],
    ) -> int | None:
        if not items:
            return None
        return self._request_menu(tr("ui.pickup_which"), items)

    def show_target_menu(
        self, world: "World", level: "Level", player_id: int,
        title: str,
    ) -> int | None:
        pos = world.get_component(player_id, "Position")
        if not pos:
            return None
        targets = []
        for eid, ai, cpos in world.query("AI", "Position"):
            if cpos is None:
                continue
            tile = level.tile_at(cpos.x, cpos.y)
            if not tile or not tile.visible:
                continue
            desc = world.get_component(eid, "Description")
            targets.append((eid, desc.name if desc else "???"))
        if not targets:
            return None
        return self._request_menu(title, targets)

    def show_selection_menu(
        self, title: str, items: list[tuple[int, str]],
    ) -> int | None:
        return self._request_menu(title, items)

    # ── Interactive modes ────────────────────────────────────────

    def farlook_mode(
        self, world: "World", level: "Level", player_id: int,
        turn: int, start_x: int, start_y: int,
    ) -> None:
        self._send({
            "type": "farlook",
            "start_x": start_x,
            "start_y": start_y,
        })
        self._recv()

    def fullmap_mode(
        self, world: "World", level: "Level", player_id: int,
        turn: int,
    ) -> None:
        tiles = []
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tile_at(x, y)
                if tile:
                    tiles.append([x, y])
        self._send({"type": "fullmap", "tiles": tiles})
        self._recv()
