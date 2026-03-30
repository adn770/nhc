"""WebSocket-based GameClient implementation.

Translates game events into JSON messages sent over WebSocket, and
receives player actions from the browser client.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import TYPE_CHECKING, Any

from nhc.rendering.client import GameClient

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)


class WebClient(GameClient):
    """GameClient that communicates over a WebSocket connection.

    The WebSocket object is set after construction via set_ws(),
    since the Game is created before the WS handshake completes.
    """

    def __init__(
        self, game_mode: str = "classic", lang: str = "ca",
    ) -> None:
        self.game_mode = game_mode
        self.lang = lang
        self.messages: list[str] = []
        self.floor_svg: str = ""
        self._ws = None
        self._input_queue: queue.Queue = queue.Queue()
        self._menu_response: queue.Queue = queue.Queue()

    def set_ws(self, ws) -> None:
        """Attach the WebSocket after handshake."""
        self._ws = ws

    # ── Helpers ──────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        """Send a JSON message to the browser."""
        if self._ws:
            data = json.dumps(msg)
            msg_type = msg.get("type", "?")
            if msg_type == "floor":
                logger.debug("WS SEND: type=floor, %d bytes", len(data))
            elif msg_type == "state":
                n_ent = len(msg.get("entities", []))
                logger.debug("WS SEND: type=state, %d entities, turn=%s",
                             n_ent, msg.get("turn"))
            else:
                logger.debug("WS SEND: type=%s", msg_type)
            self._ws.send(data)
        else:
            logger.warning("WS SEND failed: no websocket attached (type=%s)",
                           msg.get("type", "?"))

    def _recv(self) -> dict:
        """Receive a JSON message from the browser (blocking)."""
        if self._ws:
            raw = self._ws.receive()
            if raw:
                msg = json.loads(raw)
                logger.debug("WS RECV: %s", msg.get("type", raw[:80]))
                return msg
            logger.debug("WS RECV: empty/None")
        else:
            logger.warning("WS RECV: no websocket attached")
        return {}

    def _gather_entities(
        self, world: "World", level: "Level",
    ) -> list[dict]:
        """Build entity list for the client."""
        from nhc.entities.components import (
            Health, Position, Renderable,
        )
        entities = []
        for eid in list(world._entities):
            pos = world.get_component(eid, "Position")
            rend = world.get_component(eid, "Renderable")
            if not pos or not rend:
                continue
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
        entities = self._gather_entities(world, level)
        fov = self._gather_fov(level)
        self._send({
            "type": "state",
            "entities": entities,
            "fov": fov,
            "turn": turn,
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

    # ── Input ────────────────────────────────────────────────────

    async def get_input(self) -> tuple[str, Any]:
        """Wait for player action from WebSocket."""
        import asyncio
        loop = asyncio.get_event_loop()
        msg = await loop.run_in_executor(None, self._recv)
        msg_type = msg.get("type", "")
        if msg_type == "action":
            return (msg.get("intent", "wait"), msg.get("data"))
        if msg_type == "typed":
            return ("typed", msg.get("text", ""))
        if msg_type == "click":
            return ("click", {"x": msg.get("x"), "y": msg.get("y")})
        return ("wait", None)

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
        msg = await loop.run_in_executor(None, self._recv)
        msg_type = msg.get("type", "")
        if msg_type == "typed":
            return msg.get("text", "")
        if msg_type == "action":
            return (msg.get("intent", "wait"), msg.get("data"))
        return ("wait", None)

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
        # Wait for client to exit farlook
        self._recv()

    def fullmap_mode(
        self, world: "World", level: "Level", player_id: int,
        turn: int,
    ) -> None:
        # Send full map data (all tiles, not just visible)
        tiles = []
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tile_at(x, y)
                if tile:
                    tiles.append([x, y])
        self._send({"type": "fullmap", "tiles": tiles})
        self._recv()
