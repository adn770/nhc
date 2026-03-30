"""WebSocket-based GameClient implementation.

Translates game events into JSON messages sent over WebSocket, and
receives player actions from the browser client.

Communication happens through queues:
- _out_queue: game thread puts JSON strings, sender thread sends via WS
- _in_queue: WS handler thread puts raw JSON strings, game thread reads
"""

from __future__ import annotations

import json
import logging
import queue
from typing import TYPE_CHECKING, Any

from nhc.rendering.client import GameClient

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)


def _is_floor(level, x: int, y: int) -> bool:
    from nhc.dungeon.model import Terrain
    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    return t.terrain in (Terrain.FLOOR, Terrain.WATER)


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
        self._ws = None
        self._in_queue: queue.Queue = queue.Queue()
        self._out_queue: queue.Queue = queue.Queue()
        self.narrative_log = _WebNarrativeLog(self)

    def set_ws(self, ws) -> None:
        """Attach the WebSocket (kept for reference only)."""
        self._ws = ws

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
        from nhc.i18n import t as tr
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
                if item_id not in equipped_ids:
                    d = world.get_component(item_id, "Description")
                    items.append(d.name if d else "???")

        return {
            "char_name": pdesc.name if pdesc else "?",
            "char_bg": pdesc.short if pdesc else "",
            "level_name": level.name,
            "depth": level.depth,
            "turn": turn,
            "plevel": player.level if player else 1,
            "xp": player.xp if player else 0,
            "xp_next": player.xp_to_next if player else 1000,
            "gold": player.gold if player else 0,
            "hp": health.current if health else 0,
            "hp_max": health.maximum if health else 0,
            "str": stats.strength if stats else 0,
            "dex": dex,
            "con": stats.constitution if stats else 0,
            "int": stats.intelligence if stats else 0,
            "wis": stats.wisdom if stats else 0,
            "cha": stats.charisma if stats else 0,
            "weapon": weapon,
            "armor_name": armor_name,
            "shield_name": shield_name,
            "helmet_name": helmet_name,
            "ac_label": ac_label,
            "ac": ac,
            "items": items,
            "slots_used": total_used,
            "slots_max": max_slots,
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
        fov = self._gather_fov(level)
        doors = self._gather_doors(level)
        stats = self._gather_stats(world, player_id, turn, level)
        self._send({
            "type": "state",
            "entities": entities,
            "fov": fov,
            "doors": doors,
            "turn": turn,
        })
        self._send({
            "type": "stats",
            **stats,
        })

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
            import time
            time.sleep(0.5)  # give sender thread time to flush
            self._recv()  # wait for client ack

    # ── Input ────────────────────────────────────────────────────

    async def get_input(self) -> tuple[str, Any]:
        """Wait for player action from input queue.

        Blocks until a real player action arrives. Timeouts and
        empty messages are retried so they don't consume turns.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, self._recv)
            msg_type = msg.get("type", "")
            if msg_type == "action":
                return (msg.get("intent", "wait"), msg.get("data"))
            if msg_type == "typed":
                return ("typed", msg.get("text", ""))
            if msg_type == "click":
                return ("click", {"x": msg.get("x"), "y": msg.get("y")})
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
        import asyncio
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
        from nhc.i18n import t as tr
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
        from nhc.i18n import t as tr
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
