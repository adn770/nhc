"""Tests for the WebSocket-based GameClient."""

import json
from unittest.mock import MagicMock

import pytest

from nhc.rendering.client import GameClient
from nhc.rendering.web_client import WebClient


@pytest.fixture
def client():
    wc = WebClient(game_mode="classic", lang="ca")
    return wc


def _drain_queue(wc):
    """Get all messages from the output queue as parsed dicts."""
    msgs = []
    while not wc._out_queue.empty():
        msgs.append(json.loads(wc._out_queue.get_nowait()))
    return msgs


def _last_sent(wc):
    """Get the last message from the output queue."""
    msgs = _drain_queue(wc)
    return msgs[-1] if msgs else None


class TestWebClientInterface:
    def test_inherits_game_client(self):
        assert issubclass(WebClient, GameClient)

    def test_initial_state(self):
        wc = WebClient()
        assert wc.game_mode == "classic"
        assert wc.messages == []


class TestWebClientMessages:
    def test_add_message_queues_json(self, client):
        client.add_message("Hello dungeon")
        sent = _last_sent(client)
        assert sent["type"] == "message"
        assert sent["text"] == "Hello dungeon"

    def test_add_message_stores_locally(self, client):
        client.add_message("test")
        assert "test" in client.messages

    def test_message_limit(self, client):
        for i in range(210):
            client.add_message(f"msg {i}")
        assert len(client.messages) == 200


class TestWebClientRender:
    def test_render_queues_state_and_stats(self, client):
        world = MagicMock()
        world._entities = []
        world.get_component = MagicMock(return_value=None)
        level = MagicMock()
        level.height = 0
        level.width = 0
        level.depth = 1
        level.name = "Test"
        client.render(world, level, player_id=1, turn=5)
        msgs = _drain_queue(client)
        types = [m["type"] for m in msgs]
        assert "state" in types
        assert "stats" in types
        state = next(m for m in msgs if m["type"] == "state")
        assert state["turn"] == 5
        stats = next(m for m in msgs if m["type"] == "stats")
        assert "line1" in stats
        assert "line2" in stats


class TestWebClientEndScreen:
    def test_game_over_queues_json(self, client):
        client.show_end_screen(won=False, turn=42, killed_by="goblin")
        sent = _last_sent(client)
        assert sent["type"] == "game_over"
        assert sent["won"] is False
        assert sent["turn"] == 42
        assert sent["killed_by"] == "goblin"

    def test_victory_queues_json(self, client):
        client.show_end_screen(won=True, turn=99)
        sent = _last_sent(client)
        assert sent["won"] is True


class TestWebClientMenus:
    def test_selection_menu_queues_options(self, client):
        # Put a response in the input queue before calling
        client._in_queue.put('{"type":"menu_select","choice":42}')
        items = [(42, "Sword"), (43, "Shield")]
        result = client.show_selection_menu("Pick one", items)
        sent = _last_sent(client)
        assert sent["type"] == "menu"
        assert sent["title"] == "Pick one"
        assert len(sent["options"]) == 2
        assert result == 42

    def test_selection_menu_cancel(self, client):
        client._in_queue.put('{"type":"cancel"}')
        result = client.show_selection_menu("Pick", [(1, "a")])
        assert result is None


class TestWebClientShutdown:
    def test_shutdown_queues_message(self, client):
        client.shutdown()
        sent = _last_sent(client)
        assert sent["type"] == "shutdown"

    def test_initialize_is_noop(self, client):
        client.initialize()  # should not raise
