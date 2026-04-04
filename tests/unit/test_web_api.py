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
        assert data["lang"] == "en"
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

    def test_regenerate_token(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/admin/players", json={"name": "Alice"},
        )
        pid = resp.get_json()["player_id"]
        old_token = resp.get_json()["token"]

        resp = client_with_data_dir.post(
            f"/api/admin/players/{pid}/regenerate",
        )
        assert resp.status_code == 200
        new_token = resp.get_json()["token"]
        assert new_token != old_token

        # Old token should no longer be valid
        registry = client_with_data_dir.application.config[
            "PLAYER_REGISTRY"]
        from nhc.web.auth import hash_token
        assert not registry.is_valid_token_hash(hash_token(old_token))
        assert registry.is_valid_token_hash(hash_token(new_token))

    def test_regenerate_revoked_fails(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/admin/players", json={"name": "Bob"},
        )
        pid = resp.get_json()["player_id"]
        client_with_data_dir.delete(f"/api/admin/players/{pid}")

        resp = client_with_data_dir.post(
            f"/api/admin/players/{pid}/regenerate",
        )
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


class TestWelcomeMessage:
    def test_index_shows_player_name(self, tmp_path):
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
        )
        app = create_app(config, auth_token="admin-secret")
        app.config["TESTING"] = True
        registry = app.config["PLAYER_REGISTRY"]
        token, pid = registry.register("Alice")

        with app.test_client() as c:
            resp = c.get(f"/?token={token}")
            assert resp.status_code == 200
            assert b"Welcome back, Alice" in resp.data

    def test_index_no_name_without_auth(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Welcome back" not in resp.data


class TestNewGameCleansUp:
    def test_new_game_destroys_stale_session(self, client_with_data_dir):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        old_sid = resp.get_json()["session_id"]

        # Mark session as suspended (simulates Q/quit)
        sessions = client_with_data_dir.application.config["SESSIONS"]
        old_session = sessions.get(old_sid)
        old_session.connected = False

        # Create new game — old session should be destroyed
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "reset": True},
        )
        assert resp.status_code == 201
        new_sid = resp.get_json()["session_id"]
        assert new_sid != old_sid
        assert sessions.get(old_sid) is None

    def test_new_game_reset_clears_stale_svg_cache(
        self, client_with_data_dir,
    ):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        # Simulate SVG cache + autosave from old game
        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        save_dir = session.save_dir
        autosave(session.game, save_dir)
        (save_dir / "floor.svg").write_text("<svg>stale-floor</svg>")
        (save_dir / "hatch.svg").write_text("<svg>stale-hatch</svg>")

        # New game with reset should NOT load stale SVGs
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "reset": True},
        )
        assert resp.status_code == 201
        # The new game re-generates SVGs; they must not be the stale ones
        floor_svg = (save_dir / "floor.svg").read_text()
        assert "stale-floor" not in floor_svg


class TestQuitSavesGame:
    def test_quit_intent_creates_autosave(self, client_with_data_dir):
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        save_dir = session.save_dir

        # Quit intent should trigger autosave
        session.game._intent_to_action("quit", None)

        assert (save_dir / "autosave.nhc").exists()


class TestGenerationParamsAPI:
    def _create_god_session(self, client_with_data_dir):
        """Create a game session with god mode enabled."""
        token, pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new", json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        session.game.set_god_mode(True)
        return sid, session

    def test_get_params_requires_god_mode(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/game/new", json={},
        )
        sid = resp.get_json()["session_id"]
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/generation_params",
        )
        assert resp.status_code == 404

    def test_get_params_after_new_game(self, client_with_data_dir):
        sid, session = self._create_god_session(client_with_data_dir)
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/generation_params",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "depth" in data
        assert "theme" in data
        assert "seed" in data
        assert data["depth"] == 1
        assert data["theme"] == "dungeon"

    def test_regenerate_requires_god_mode(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/game/new", json={},
        )
        sid = resp.get_json()["session_id"]
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/regenerate",
            json={"depth": 5},
        )
        assert resp.status_code == 404

    def test_regenerate_with_depth(self, client_with_data_dir):
        sid, session = self._create_god_session(client_with_data_dir)
        old_level_id = session.game.level.id
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/regenerate",
            json={"depth": 5},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["params"]["depth"] == 5
        assert data["params"]["theme"] == "crypt"
        assert session.game.level.id != old_level_id
        assert session.game.generation_params.depth == 5

    def test_regenerate_with_seed_reproducible(self, client_with_data_dir):
        sid, session = self._create_god_session(client_with_data_dir)
        resp1 = client_with_data_dir.post(
            f"/api/game/{sid}/regenerate",
            json={"depth": 3, "seed": 777},
        )
        rooms1 = len(session.game.level.rooms)
        resp2 = client_with_data_dir.post(
            f"/api/game/{sid}/regenerate",
            json={"depth": 3, "seed": 777},
        )
        rooms2 = len(session.game.level.rooms)
        assert rooms1 == rooms2

    def test_regenerate_updates_player_position(self, client_with_data_dir):
        sid, session = self._create_god_session(client_with_data_dir)
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/regenerate",
            json={"depth": 2},
        )
        assert resp.status_code == 200
        game = session.game
        pos = game.world.get_component(game.player_id, "Position")
        tile = game.level.tile_at(pos.x, pos.y)
        assert tile is not None
        assert tile.feature == "stairs_up"


class TestDebugBundleAutosave:
    def test_bundle_includes_generation_params(self, client_with_data_dir):
        """Debug bundle must include generation parameters."""
        token, pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new", json={"player_token": token},
        )
        sid = resp.get_json()["session_id"]
        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        session.game.set_god_mode(True)

        resp = client_with_data_dir.get(
            f"/api/game/{sid}/export/bundle",
        )
        assert resp.status_code == 200

        import io
        import tarfile
        buf = io.BytesIO(resp.data)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()
            # Separate params file
            params_files = [n for n in names
                            if "generation_params" in n]
            assert len(params_files) == 1

            # Also check it's in the game state JSON
            state_files = [n for n in names
                           if "game_state" in n]
            assert len(state_files) == 1
            state_data = json.loads(
                tar.extractfile(state_files[0]).read(),
            )
            assert "generation_params" in state_data
            assert state_data["generation_params"]["depth"] == 1

    def test_bundle_forces_autosave(self, client_with_data_dir):
        """Debug bundle must force a fresh autosave so the bundle
        always contains the current game state."""
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        session.game.set_god_mode(True)
        save_dir = session.save_dir
        save_file = save_dir / "autosave.nhc"

        # Remove any existing autosave
        if save_file.exists():
            save_file.unlink()
        assert not save_file.exists()

        resp = client_with_data_dir.get(
            f"/api/game/{sid}/export/bundle",
        )
        assert resp.status_code == 200

        # Autosave must have been created
        assert save_file.exists()

        # Bundle must contain autosave.bin
        import io
        import tarfile
        buf = io.BytesIO(resp.data)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()
            assert "autosave.nhc" in names
