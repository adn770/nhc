"""Tests for the web API endpoints."""

import json

import pytest

from nhc.core.autosave import autosave
from nhc.web.app import create_app
from nhc.web.config import WebConfig
from nhc.web.sessions import player_id_from_token


@pytest.fixture
def client():
    config = WebConfig(max_sessions=2)
    app = create_app(config)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def client_with_data_dir(tmp_path):
    config = WebConfig(max_sessions=4, data_dir=tmp_path)
    app = create_app(config)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestGameAPI:
    def test_create_game(self, client):
        resp = client.post(
            "/api/game/new",
            json={"lang": "ca", "tileset": "classic"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "session_id" in data
        assert data["lang"] == "ca"

    def test_create_game_defaults(self, client):
        resp = client.post("/api/game/new", json={})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["lang"] == "ca"
        assert data["tileset"] == "classic"

    def test_list_games(self, client):
        client.post("/api/game/new", json={})
        resp = client.get("/api/game/list")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

    def test_delete_game(self, client):
        resp = client.post("/api/game/new", json={})
        sid = resp.get_json()["session_id"]
        resp = client.delete(f"/api/game/{sid}")
        assert resp.status_code == 200
        resp = client.get("/api/game/list")
        assert len(resp.get_json()) == 0

    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/game/bogus")
        assert resp.status_code == 404

    def test_max_sessions(self, client):
        client.post("/api/game/new", json={})
        client.post("/api/game/new", json={})
        resp = client.post("/api/game/new", json={})
        assert resp.status_code == 429

    def test_tilesets(self, client):
        resp = client.get("/api/tilesets")
        assert resp.status_code == 200
        assert "classic" in resp.get_json()

    def test_new_game_ignores_autosave(self, tmp_path, monkeypatch):
        """With --reset, new web game must not restore from autosave."""
        # Use a config with reset=True to simulate --reset flag
        config = WebConfig(max_sessions=2, reset=True)
        app = create_app(config)
        app.config["TESTING"] = True

        save_path = tmp_path / "autosave.nhc"
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_PATH", save_path,
        )
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_DIR", tmp_path,
        )

        with app.test_client() as reset_client:
            resp1 = reset_client.post("/api/game/new", json={})
            assert resp1.status_code == 201
            sid1 = resp1.get_json()["session_id"]

            # Trigger an autosave by getting the game's session
            sessions = reset_client.application.config["SESSIONS"]
            session = sessions.get(sid1)
            autosave(session.game)
            assert save_path.exists()

            # Start a second game — must NOT restore from autosave
            resp2 = reset_client.post("/api/game/new", json={})
            assert resp2.status_code == 201
            sid2 = resp2.get_json()["session_id"]
            assert sid1 != sid2
            # The autosave should be deleted (reset=True)
            assert not save_path.exists()


class TestPlayerAPI:
    def test_register_returns_token(self, client_with_data_dir):
        resp = client_with_data_dir.post("/api/player/register")
        assert resp.status_code == 201
        data = resp.get_json()
        assert "player_token" in data
        assert "player_id" in data
        assert len(data["player_id"]) == 12

    def test_register_creates_save_dir(self, client_with_data_dir, tmp_path):
        config = client_with_data_dir.application.config["NHC_CONFIG"]
        resp = client_with_data_dir.post("/api/player/register")
        data = resp.get_json()
        pid = data["player_id"]
        save_dir = config.data_dir / "players" / pid
        assert save_dir.is_dir()

    def test_login_with_valid_token(self, client_with_data_dir):
        resp = client_with_data_dir.post("/api/player/register")
        token = resp.get_json()["player_token"]

        resp = client_with_data_dir.post(
            "/api/player/login",
            json={"player_token": token},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["player_id"] == player_id_from_token(token)
        assert data["has_save"] is False
        assert data["active_session"] is None

    def test_login_missing_token(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/player/login", json={},
        )
        assert resp.status_code == 400

    def test_new_game_with_player(self, client_with_data_dir):
        resp = client_with_data_dir.post("/api/player/register")
        token = resp.get_json()["player_token"]

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201

        # Session should have the player_id
        sessions = client_with_data_dir.application.config["SESSIONS"]
        sid = resp.get_json()["session_id"]
        session = sessions.get(sid)
        assert session.player_id == player_id_from_token(token)
        assert session.save_dir is not None

    def test_two_players_independent(self, client_with_data_dir):
        r1 = client_with_data_dir.post("/api/player/register")
        r2 = client_with_data_dir.post("/api/player/register")
        pid1 = r1.get_json()["player_id"]
        pid2 = r2.get_json()["player_id"]
        assert pid1 != pid2


class TestResumeAPI:
    def test_resume_missing_token(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/game/resume", json={},
        )
        assert resp.status_code == 400

    def test_resume_no_save(self, client_with_data_dir):
        resp = client_with_data_dir.post("/api/player/register")
        token = resp.get_json()["player_token"]

        resp = client_with_data_dir.post(
            "/api/game/resume",
            json={"player_token": token},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["has_save"] is False

    def test_resume_with_autosave(self, client_with_data_dir):
        # Register and create a game
        resp = client_with_data_dir.post("/api/player/register")
        token = resp.get_json()["player_token"]
        pid = resp.get_json()["player_id"]

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        # Manually trigger an autosave for this player
        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        autosave(session.game, session.save_dir)

        # Destroy the original session (simulates disconnect cleanup)
        sessions.destroy(sid)

        # Now resume — should restore from autosave
        resp = client_with_data_dir.post(
            "/api/game/resume",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["resumed"] is True
        assert data["turn"] >= 0

    def test_resume_finds_active_session(self, client_with_data_dir):
        resp = client_with_data_dir.post("/api/player/register")
        token = resp.get_json()["player_token"]

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        # Resume with active session — should return existing session_id
        resp = client_with_data_dir.post(
            "/api/game/resume",
            json={"player_token": token},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["session_id"] == sid
        assert data["resumed"] is True
