"""Tests for the WebSocket-based GameClient."""

import json
from unittest.mock import MagicMock

import pytest

from nhc.rendering.client import GameClient
from nhc.rendering.web_client import WebClient


@pytest.fixture
def client():
    wc = WebClient(game_mode="classic", lang="ca")
    ws = MagicMock()
    ws.send = MagicMock()
    wc.set_ws(ws)
    return wc


class TestWebClientInterface:
    def test_inherits_game_client(self):
        assert issubclass(WebClient, GameClient)

    def test_initial_state(self):
        wc = WebClient()
        assert wc.game_mode == "classic"
        assert wc.messages == []


class TestWebClientMessages:
    def test_add_message_sends_json(self, client):
        client.add_message("Hello dungeon")
        sent = json.loads(client._ws.send.call_args[0][0])
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
    def test_render_sends_state(self, client):
        world = MagicMock()
        world._entities = []
        level = MagicMock()
        level.height = 0
        level.width = 0
        client.render(world, level, player_id=1, turn=5)
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "state"
        assert sent["turn"] == 5
        assert "entities" in sent
        assert "fov" in sent


class TestWebClientEndScreen:
    def test_game_over_sends_json(self, client):
        client.show_end_screen(won=False, turn=42, killed_by="goblin")
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "game_over"
        assert sent["won"] is False
        assert sent["turn"] == 42
        assert sent["killed_by"] == "goblin"

    def test_victory_sends_json(self, client):
        client.show_end_screen(won=True, turn=99)
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["won"] is True


class TestWebClientMenus:
    def test_selection_menu_sends_options(self, client):
        client._ws.receive = MagicMock(
            return_value='{"type":"menu_select","choice":42}',
        )
        items = [(42, "Sword"), (43, "Shield")]
        result = client.show_selection_menu("Pick one", items)
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "menu"
        assert sent["title"] == "Pick one"
        assert len(sent["options"]) == 2
        assert result == 42

    def test_selection_menu_cancel(self, client):
        client._ws.receive = MagicMock(
            return_value='{"type":"cancel"}',
        )
        result = client.show_selection_menu("Pick", [(1, "a")])
        assert result is None


class TestWebClientShutdown:
    def test_shutdown_sends_message(self, client):
        client.shutdown()
        sent = json.loads(client._ws.send.call_args[0][0])
        assert sent["type"] == "shutdown"

    def test_initialize_is_noop(self, client):
        client.initialize()  # should not raise
