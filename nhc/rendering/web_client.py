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

from nhc.core.game import compute_hatch_clear
from nhc.dungeon.model import HybridShape, Terrain
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
        self._last_hatch_clear: set[tuple[int, int]] = set()
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
        if equip:
            for attr in ("weapon", "armor", "shield", "helmet",
                         "ring_left", "ring_right"):
                eid = getattr(equip, attr)
                if eid is not None:
                    equipped_ids.add(eid)
            armor_name = _name(equip.armor) if equip.armor else ""
            shield_name = _name(equip.shield) if equip.shield else ""
            helmet_name = _name(equip.helmet) if equip.helmet else ""

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

                items.append({
                    "id": item_id,
                    "name": d.name if d else "???",
                    "equipped": item_id in equipped_ids,
                    "types": types,
                    "charges": charges,
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
        dynamic = {
            "turn": turn,
            "plevel": player.level if player else 1,
            "xp": player.xp if player else 0,
            "gold": player.gold if player else 0,
            "hp": health.current if health else 0,
            "weapon": weapon,
            "armor_name": armor_name,
            "shield_name": shield_name,
            "helmet_name": helmet_name,
            "ac": ac,
            "items": items,
            "slots_used": total_used,
        }
        return static, dynamic

    def _action_labels(self) -> dict[str, str]:
        """Return translated context menu and toolbar labels."""
        return {
            "use": tr("ui.action_use"),
            "quaff": tr("ui.action_quaff"),
            "zap": tr("ui.action_zap"),
            "equip": tr("ui.action_equip"),
            "unequip": tr("ui.action_unequip"),
            "drop": tr("ui.action_drop"),
            "throw": tr("ui.action_throw"),
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
            "toolbar_farlook": tr("ui.toolbar_farlook"),
            "toolbar_descend": tr("ui.toolbar_descend"),
            "toolbar_ascend": tr("ui.toolbar_ascend"),
            "toolbar_zoom_in": tr("ui.toolbar_zoom_in"),
            "toolbar_zoom_out": tr("ui.toolbar_zoom_out"),
            "toolbar_restart": tr("ui.toolbar_restart"),
            "toolbar_debug": tr("ui.toolbar_debug"),
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

    def _gather_hatch_clear(
        self, level: "Level",
    ) -> list[list[int]]:
        """Build list of tiles whose hatch should be cleared."""
        tiles = compute_hatch_clear(level)
        return [[x, y] for x, y in sorted(tiles)]

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
        self._last_hatch_clear = set()

        entities = self._gather_entities(world, level, player_id)
        fov = self._gather_fov(level)
        doors = self._gather_doors(level)
        hatch_clear = self._gather_hatch_clear(level)

        self._send({
            "type": "floor",
            "floor_url": (f"{self._base_url}"
                          f"/floor/{self.floor_svg_id}.svg"),
            "hatch_url": "/api/hatch.svg",
            "entities": entities,
            "doors": doors,
            "fov": fov,
            "hatch_clear": hatch_clear,
            "turn": turn,
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

        # Hatch-clear delta encoding
        hatch_list = self._gather_hatch_clear(level)
        current_hatch = {(t[0], t[1]) for t in hatch_list}
        prev_hatch = self._last_hatch_clear
        hatch_add = current_hatch - prev_hatch
        hatch_del = prev_hatch - current_hatch
        self._last_hatch_clear = current_hatch

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
        # Hatch-clear: full or delta
        if (not prev_hatch
                or len(hatch_add) + len(hatch_del)
                > len(current_hatch) * 0.5):
            state_msg["hatch_clear"] = hatch_list
        else:
            if hatch_add:
                state_msg["hatch_clear_add"] = [
                    [x, y] for x, y in hatch_add]
            if hatch_del:
                state_msg["hatch_clear_del"] = [
                    [x, y] for x, y in hatch_del]
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
