"""Tests for the web API endpoints."""

import json

import pytest

from nhc.core.autosave import autosave
from nhc.web.app import create_app
from nhc.web.auth import hash_token
from nhc.web.config import WebConfig
from nhc.web.registry import PlayerRegistry
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


def _register_player(app_client, name="Tester"):
    """Register a player via the registry and return (token, pid)."""
    registry = app_client.application.config["PLAYER_REGISTRY"]
    token, pid = registry.register(name)
    # Create save dir
    config = app_client.application.config["NHC_CONFIG"]
    if config.data_dir:
        save_dir = config.data_dir / "players" / pid
        save_dir.mkdir(parents=True, exist_ok=True)
    return token, pid


class TestRateLimit:
    def test_game_new_rate_limited(self, tmp_path):
        config = WebConfig(max_sessions=20, data_dir=tmp_path)
        app = create_app(config)
        app.config["TESTING"] = True
        with app.test_client() as c:
            for _ in range(5):
                resp = c.post("/api/game/new", json={})
                assert resp.status_code == 201
            resp = c.post("/api/game/new", json={})
            assert resp.status_code == 429

    def test_admin_register_rate_limited(self, tmp_path):
        config = WebConfig(max_sessions=20, data_dir=tmp_path)
        app = create_app(config)
        app.config["TESTING"] = True
        with app.test_client() as c:
            for i in range(5):
                resp = c.post("/api/admin/players",
                              json={"name": f"Player {i}"})
                assert resp.status_code == 201
            resp = c.post("/api/admin/players",
                          json={"name": "Overflow"})
            assert resp.status_code == 429


class TestAppFactory:
    def test_app_factory_creates_app(self, tmp_path, monkeypatch):
        from nhc.web.app import app_factory
        monkeypatch.setenv("NHC_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("NHC_MAX_SESSIONS", "4")
        app = app_factory()
        assert app is not None
        cfg = app.config["NHC_CONFIG"]
        assert cfg.data_dir == tmp_path
        assert cfg.max_sessions == 4
        assert cfg.god_mode is False

    def test_app_factory_with_auth(self, tmp_path, monkeypatch):
        from nhc.web.app import app_factory
        monkeypatch.setenv("NHC_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("NHC_AUTH_TOKEN", "secret123")
        app = app_factory()
        assert app.config["NHC_CONFIG"].auth_required is True
        assert len(app.config["AUTH_HASHES"]) == 1


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["sessions"] == 0

    def test_health_counts_sessions(self, client):
        client.post("/api/game/new", json={})
        resp = client.get("/health")
        assert resp.get_json()["sessions"] == 1


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

            sessions = reset_client.application.config["SESSIONS"]
            session = sessions.get(sid1)
            autosave(session.game)
            assert save_path.exists()

            resp2 = reset_client.post("/api/game/new", json={})
            assert resp2.status_code == 201
            sid2 = resp2.get_json()["session_id"]
            assert sid1 != sid2
            assert not save_path.exists()


class TestPlayerAPI:
    def test_login_returns_player_info(self, client_with_data_dir):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post("/api/player/login")
        assert resp.status_code == 200

    def test_new_game_with_player(self, client_with_data_dir):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201

    def test_two_players_independent(self, client_with_data_dir):
        _, pid1 = _register_player(client_with_data_dir, "Alice")
        _, pid2 = _register_player(client_with_data_dir, "Bob")
        assert pid1 != pid2


class TestAdminAPI:
    def test_register_player(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/admin/players", json={"name": "Alice"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "token" in data
        assert data["name"] == "Alice"
        assert len(data["player_id"]) == 12

    def test_register_creates_save_dir(self, client_with_data_dir):
        config = client_with_data_dir.application.config["NHC_CONFIG"]
        resp = client_with_data_dir.post(
            "/api/admin/players", json={"name": "Bob"},
        )
        pid = resp.get_json()["player_id"]
        save_dir = config.data_dir / "players" / pid
        assert save_dir.is_dir()

    def test_register_requires_name(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/admin/players", json={},
        )
        assert resp.status_code == 400

    def test_list_players(self, client_with_data_dir):
        client_with_data_dir.post(
            "/api/admin/players", json={"name": "Alice"},
        )
        client_with_data_dir.post(
            "/api/admin/players", json={"name": "Bob"},
        )
        resp = client_with_data_dir.get("/api/admin/players")
        assert resp.status_code == 200
        players = resp.get_json()
        assert len(players) == 2
        names = {p["name"] for p in players}
        assert names == {"Alice", "Bob"}

    def test_revoke_player(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/admin/players", json={"name": "Alice"},
        )
        pid = resp.get_json()["player_id"]

        resp = client_with_data_dir.delete(f"/api/admin/players/{pid}")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "revoked"

    def test_revoke_nonexistent(self, client_with_data_dir):
        resp = client_with_data_dir.delete("/api/admin/players/bogus")
        assert resp.status_code == 404

    def test_list_sessions(self, client_with_data_dir):
        client_with_data_dir.post("/api/game/new", json={})
        resp = client_with_data_dir.get("/api/admin/sessions")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 1


class TestResumeAPI:
    def test_resume_no_save(self, client_with_data_dir):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/resume",
            json={"player_token": token},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["has_save"] is False

    def test_resume_with_autosave(self, client_with_data_dir):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        autosave(session.game, session.save_dir)
        sessions.destroy(sid)

        resp = client_with_data_dir.post(
            "/api/game/resume",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["resumed"] is True
        assert data["turn"] >= 0

    def test_resume_finds_active_session(self, client_with_data_dir):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        resp = client_with_data_dir.post(
            "/api/game/resume",
            json={"player_token": token},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["session_id"] == sid
        assert data["resumed"] is True
