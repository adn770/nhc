"""Tests for the web API endpoints."""

import json
from pathlib import Path

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


class TestHelpEndpoint:
    """``/api/help/<lang>`` reads a file off disk keyed on *lang*.
    The ``help_`` prefix already makes traversal infeasible on
    Linux, but whitelisting is cheaper and clearer than arguing
    about what the filesystem will refuse."""

    def test_supported_language(self, client):
        resp = client.get("/api/help/en")
        assert resp.status_code == 200

    def test_unknown_language_rejected(self, client):
        resp = client.get("/api/help/xx")
        assert resp.status_code == 400

    def test_traversal_attempt_rejected(self, client):
        resp = client.get("/api/help/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404)


class TestAdminListPlayersStripsTokenHash:
    """The admin panel never needs the raw ``token_hash`` — it is
    leaked to the caller today. The fix strips it from the JSON
    response, leaving only the short ``player_id`` (which is the
    hash prefix the caller already sees in URLs)."""

    _TOKEN = "admin-secret"

    def test_list_players_omits_token_hash(self, tmp_path):
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
            admin_lan_cidrs=["192.168.18.0/24"],
            trust_proxy=True,
        )
        app = create_app(config, auth_token=self._TOKEN)
        app.config["TESTING"] = True
        registry = app.config["PLAYER_REGISTRY"]
        registry.register("tester")
        with app.test_client() as c:
            resp = c.get(
                f"/api/admin/players?token={self._TOKEN}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": "192.168.18.50"},
            )
            assert resp.status_code == 200
            payload = resp.get_json()
            assert payload
            for player in payload:
                assert "token_hash" not in player
                # The short player_id is still there — the admin
                # UI needs it to identify rows.
                assert "player_id" in player


class TestTokenStripRedirect:
    """A ``?token=...`` in the URL bar persists in history, logs,
    and ``Referer`` headers. After setting the cookie we must
    redirect to the token-free URL so the sensitive value is not
    retained anywhere user-visible."""

    _TOKEN = "admin-secret"

    def _auth_app(self, tmp_path):
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
            admin_lan_cidrs=["192.168.18.0/24"],
            trust_proxy=True,
        )
        app = create_app(config, auth_token=self._TOKEN)
        app.config["TESTING"] = True
        return app

    def test_index_redirects_when_token_in_query(self, tmp_path):
        app = self._auth_app(tmp_path)
        registry = app.config["PLAYER_REGISTRY"]
        token, _pid = registry.register("tester")
        with app.test_client() as c:
            resp = c.get(f"/?token={token}",
                         follow_redirects=False)
            assert resp.status_code == 303
            assert "token=" not in resp.headers["Location"]
            # Cookie must be set on the redirect so the next GET
            # without the query param is still authenticated.
            cookies = resp.headers.get_all("Set-Cookie")
            assert any("nhc_token=" in h for h in cookies)
            assert any("HttpOnly" in h for h in cookies)

    def test_index_no_redirect_when_token_in_cookie(self, tmp_path):
        """If there's no query token, serve directly — no bounce."""
        app = self._auth_app(tmp_path)
        registry = app.config["PLAYER_REGISTRY"]
        token, _pid = registry.register("tester")
        with app.test_client() as c:
            c.set_cookie("nhc_token", token)
            resp = c.get("/", follow_redirects=False)
            assert resp.status_code == 200

    def test_admin_redirects_when_token_in_query(self, tmp_path):
        app = self._auth_app(tmp_path)
        with app.test_client() as c:
            resp = c.get(
                f"/admin?token={self._TOKEN}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": "192.168.18.50"},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert "token=" not in resp.headers["Location"]
            cookies = resp.headers.get_all("Set-Cookie")
            assert any("nhc_admin_token=" in h for h in cookies)


class TestTTSAuth:
    """The TTS synthesis endpoint must require a player token AND
    use the shared rate limiter — before the fix it accepted
    unauthenticated bulk traffic from the public internet."""

    def test_tts_status_is_public(self, tmp_path):
        """`/api/tts/status` stays public — it tells the client
        whether TTS is even compiled in, no resources consumed."""
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
            admin_lan_cidrs=["192.168.18.0/24"],
        )
        app = create_app(config, auth_token="admin")
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/api/tts/status")
            assert resp.status_code == 200

    def test_tts_synthesize_rejected_without_token(self, tmp_path):
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
            admin_lan_cidrs=["192.168.18.0/24"],
        )
        app = create_app(config, auth_token="admin")
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post(
                "/api/tts", json={"text": "hello", "lang": "en"},
            )
            assert resp.status_code in (401, 403)

    def test_tts_synthesize_accepts_valid_player(self, tmp_path):
        """When auth is on and a valid player token is presented,
        the handler proceeds past auth (may still 503 if piper
        isn't installed in the test env)."""
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
            admin_lan_cidrs=["192.168.18.0/24"],
        )
        app = create_app(config, auth_token="admin")
        app.config["TESTING"] = True
        registry = app.config["PLAYER_REGISTRY"]
        token, _pid = registry.register("tester")
        with app.test_client() as c:
            resp = c.post(
                f"/api/tts?token={token}",
                json={"text": "hello", "lang": "en"},
            )
            # 200 with TTS available, 503 if piper not installed,
            # 400 if text rejected. We only require "not an auth
            # rejection" — i.e. handler authorized the player.
            assert resp.status_code not in (401, 403)

    def test_tts_synthesize_rate_limited(self, tmp_path):
        """Authenticated calls still hit the global rate limit."""
        config = WebConfig(
            max_sessions=20, data_dir=tmp_path, auth_required=True,
            admin_lan_cidrs=["192.168.18.0/24"],
        )
        app = create_app(config, auth_token="admin")
        app.config["TESTING"] = True
        registry = app.config["PLAYER_REGISTRY"]
        token, _pid = registry.register("tester")
        with app.test_client() as c:
            # First five are allowed by the 5/60s limiter.
            for _ in range(5):
                resp = c.post(
                    f"/api/tts?token={token}",
                    json={"text": "hi", "lang": "en"},
                )
                assert resp.status_code != 429
            resp = c.post(
                f"/api/tts?token={token}",
                json={"text": "hi", "lang": "en"},
            )
            assert resp.status_code == 429


class TestAdminLanAllowlist:
    """End-to-end verification that ``create_app`` wires ProxyFix
    and the LAN allowlist together so the vulnerable "is_private()"
    LAN check is truly gone.
    """

    _TOKEN = "admin-secret"

    def _build(self, tmp_path, cidrs):
        config = WebConfig(
            max_sessions=2,
            data_dir=tmp_path,
            auth_required=True,
            admin_lan_cidrs=cidrs,
            trust_proxy=True,
        )
        app = create_app(config, auth_token=self._TOKEN)
        app.config["TESTING"] = True
        return app

    def test_reject_loopback_with_no_forwarded_header(self, tmp_path):
        """C1 regression: Caddy arriving on loopback without a real
        client IP must not be admin-eligible."""
        app = self._build(tmp_path, ["192.168.18.0/24"])
        with app.test_client() as c:
            resp = c.get(f"/admin?token={self._TOKEN}",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
            assert resp.status_code == 403

    def test_reject_public_client_via_forwarded_header(self, tmp_path):
        """C1 regression: Caddy forwarded a public IP — deny admin."""
        app = self._build(tmp_path, ["192.168.18.0/24"])
        with app.test_client() as c:
            resp = c.get(
                f"/admin?token={self._TOKEN}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": "8.8.8.8"},
            )
            assert resp.status_code == 403

    def test_allow_lan_client_via_forwarded_header(self, tmp_path):
        """Real LAN client reaching Caddy over HTTP gets admin
        (after the token-strip redirect)."""
        app = self._build(tmp_path, ["192.168.18.0/24"])
        with app.test_client() as c:
            resp = c.get(
                f"/admin?token={self._TOKEN}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": "192.168.18.50"},
                follow_redirects=True,
            )
            assert resp.status_code == 200

    def test_empty_cidrs_blocks_admin_even_from_lan(self, tmp_path):
        """Fail-closed default: no configured CIDRs → admin dark."""
        app = self._build(tmp_path, [])
        with app.test_client() as c:
            resp = c.get(
                f"/admin?token={self._TOKEN}",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": "192.168.18.50"},
            )
            assert resp.status_code == 403


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

    def test_list_players_includes_last_seen_and_duration(
            self, client_with_data_dir):
        """Admin response must carry last_seen + session_duration."""
        _token, pid = _register_player(client_with_data_dir, "Alice")
        registry = client_with_data_dir.application.config[
            "PLAYER_REGISTRY"]
        # Offline player with no session: last_seen present, duration None
        resp = client_with_data_dir.get("/api/admin/players")
        assert resp.status_code == 200
        players = resp.get_json()
        alice = next(p for p in players if p["player_id"] == pid)
        assert "last_seen" in alice
        assert "session_duration" in alice
        assert "session_started_at" in alice
        assert alice["last_seen"] == 0
        assert alice["session_duration"] is None
        assert alice["session_started_at"] is None

    def test_list_players_reports_session_duration_when_online(
            self, client_with_data_dir):
        import time as _t
        _token, pid = _register_player(client_with_data_dir, "Bob")
        # Create a game session for Bob (counts as online)
        resp = client_with_data_dir.post(
            "/api/game/new", json={"player_token": _token},
        )
        assert resp.status_code == 201
        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get_by_player(pid)
        assert session is not None
        # Force a known created_at so duration is deterministic
        session.created_at = _t.time() - 42

        resp = client_with_data_dir.get("/api/admin/players")
        bob = next(
            p for p in resp.get_json() if p["player_id"] == pid
        )
        assert bob["session_duration"] is not None
        assert bob["session_duration"] >= 40
        assert bob["session_started_at"] == session.created_at

    def test_authenticated_request_bumps_last_seen(self, tmp_path):
        """Any authenticated player route should update last_seen."""
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
        )
        app = create_app(config, auth_token="admin-secret")
        app.config["TESTING"] = True
        with app.test_client() as c:
            registry = app.config["PLAYER_REGISTRY"]
            token, pid = registry.register("Alice")
            assert registry.get(pid)["last_seen"] == 0.0

            resp = c.get(f"/api/ranking?token={token}")
            assert resp.status_code == 200
            assert registry.get(pid)["last_seen"] > 0

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

    def test_clear_player_scores(self, client_with_data_dir):
        """DELETE /api/admin/players/<pid>/scores removes entries."""
        from nhc.web.leaderboard import LeaderboardEntry

        _token, pid = _register_player(client_with_data_dir, "Alice")
        lb = client_with_data_dir.application.config["LEADERBOARD"]
        lb.submit(LeaderboardEntry(
            player_id=pid, name="Alice",
            score=500, depth=3, turn=100, won=False,
            killed_by="goblin", timestamp=1000.0,
        ))
        lb.submit(LeaderboardEntry(
            player_id="other", name="Bob",
            score=300, depth=2, turn=50, won=False,
            killed_by="rat", timestamp=1001.0,
        ))
        assert len(lb.top(10)) == 2

        resp = client_with_data_dir.delete(
            f"/api/admin/players/{pid}/scores",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["removed"] == 1

        top = lb.top(10)
        assert len(top) == 1
        assert top[0].name == "Bob"

    def test_clear_scores_nonexistent_player(self, client_with_data_dir):
        resp = client_with_data_dir.delete(
            "/api/admin/players/bogus/scores",
        )
        assert resp.status_code == 200
        assert resp.get_json()["removed"] == 0

    def test_toggle_tester_mode_enables(self, client_with_data_dir):
        _, pid = _register_player(client_with_data_dir, "Alice")
        resp = client_with_data_dir.post(
            f"/api/admin/players/{pid}/tester_mode",
            json={"enabled": True},
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok", "tester_mode": True}
        registry = client_with_data_dir.application.config[
            "PLAYER_REGISTRY"]
        assert registry.get(pid)["tester_mode"] is True

    def test_toggle_tester_mode_disables(self, client_with_data_dir):
        _, pid = _register_player(client_with_data_dir, "Alice")
        registry = client_with_data_dir.application.config[
            "PLAYER_REGISTRY"]
        registry.set_tester_mode(pid, True)
        resp = client_with_data_dir.post(
            f"/api/admin/players/{pid}/tester_mode",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.get_json()["tester_mode"] is False
        assert registry.get(pid)["tester_mode"] is False

    def test_toggle_tester_mode_unknown_player(self, client_with_data_dir):
        resp = client_with_data_dir.post(
            "/api/admin/players/bogus/tester_mode",
            json={"enabled": True},
        )
        assert resp.status_code == 404

    def test_admin_list_includes_tester_mode(self, client_with_data_dir):
        """The admin panel reads ``tester_mode`` from the listing
        endpoint to render the toggle button's state."""
        _, pid = _register_player(client_with_data_dir, "Alice")
        registry = client_with_data_dir.application.config[
            "PLAYER_REGISTRY"]
        registry.set_tester_mode(pid, True)
        resp = client_with_data_dir.get("/api/admin/players")
        assert resp.status_code == 200
        alice = next(
            p for p in resp.get_json() if p["player_id"] == pid
        )
        assert alice["tester_mode"] is True

    def test_toggle_tester_mode_default_payload(self, client_with_data_dir):
        """Missing ``enabled`` key defaults to False (disables)."""
        _, pid = _register_player(client_with_data_dir, "Alice")
        registry = client_with_data_dir.application.config[
            "PLAYER_REGISTRY"]
        registry.set_tester_mode(pid, True)
        resp = client_with_data_dir.post(
            f"/api/admin/players/{pid}/tester_mode",
            json={},
        )
        assert resp.status_code == 200
        assert registry.get(pid)["tester_mode"] is False

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
            # ``?token=...`` now triggers a 303 redirect that strips
            # the query string from history/logs before rendering.
            resp = c.get(f"/?token={token}", follow_redirects=True)
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
        # Dungeon-mode test -- the SVG cache lives on the
        # dungeon floor; hexcrawl's overland doesn't exercise it.
        token, pid = _register_player(client_with_data_dir)

        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
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
            json={
                "player_token": token,
                "reset": True,
                "world": "dungeon",
            },
        )
        assert resp.status_code == 201
        # The new game re-generates SVGs; they must not be the stale ones
        floor_svg = (save_dir / "floor.svg").read_text()
        assert "stale-floor" not in floor_svg


class TestFloorIRRoutes:
    """Phase 2.1 of plans/nhc_ir_migration_plan.md.

    The `.nir` and `.json` siblings of the existing
    `/api/game/<sid>/floor/<svg_id>.svg` route put the IR on the
    wire so debug tooling can observe it. `.json` is god-mode-gated
    because the canonical dump leaks engine internals (region ids,
    rng seeds) that regular players have no business seeing.
    """

    def _start_dungeon_game(self, c, *, god_mode=False):
        token, _pid = _register_player(c)
        resp = c.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = c.application.config["SESSIONS"]
        session = sessions.get(sid)
        if god_mode:
            session.game.set_god_mode(True)
        return sid, session.game.renderer.floor_svg_id

    def test_nir_returns_flatbuffer(self, client_with_data_dir):
        sid, svg_id = self._start_dungeon_game(client_with_data_dir)
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.nir",
        )
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/octet-stream"
        body = resp.get_data()
        # FlatBuffers stamp the file_identifier at offset 4..8.
        assert body[4:8] == b"NIR5"
        # The canonical dumper is the round-trip contract.
        from nhc.rendering.ir.dump import dump
        text = dump(body)
        assert '"major"' in text
        assert '"minor"' in text
        assert '"regions"' in text

    def test_nir_404_for_unknown_session(self, client_with_data_dir):
        resp = client_with_data_dir.get(
            "/api/game/no-such-sid/floor/no-such-id.nir",
        )
        assert resp.status_code == 404

    def test_nir_404_for_unknown_svg_id(self, client_with_data_dir):
        sid, _svg_id = self._start_dungeon_game(client_with_data_dir)
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/deadbeef.nir",
        )
        assert resp.status_code == 404

    def test_json_dump_for_god_mode(self, client_with_data_dir):
        sid, svg_id = self._start_dungeon_game(
            client_with_data_dir, god_mode=True,
        )
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.json",
        )
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith(
            "application/json"
        )
        payload = json.loads(resp.get_data(as_text=True))
        assert payload["major"] == 5
        assert payload["minor"] >= 0
        assert "regions" in payload
        assert "ops" in payload

    def test_json_404_when_not_god_mode(self, client_with_data_dir):
        sid, svg_id = self._start_dungeon_game(client_with_data_dir)
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.json",
        )
        # Mirrors /debug.json: hide the route's existence rather than
        # 403-ing — same pattern, same surface.
        assert resp.status_code == 404

    def test_json_404_for_unknown_session(self, client_with_data_dir):
        resp = client_with_data_dir.get(
            "/api/game/no-such-sid/floor/no-such-id.json",
        )
        assert resp.status_code == 404


class TestFloorPngViaIR:
    """Phase 2.2 of plans/nhc_ir_migration_plan.md.

    The .png route used to rasterise whatever sat in the SVG cache.
    Phase 2.2 makes the IR the source of truth: for floors covered
    by ``build_floor_ir`` (plain dungeon, today), the route rebuilds
    IR -> SVG via ``ir_to_svg`` and rasterises that. The cached
    composite SVG remains the fallback for building / site-surface
    floors until those branches gain IR coverage.
    """

    def _start_dungeon_game(self, c):
        token, _pid = _register_player(c)
        resp = c.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = c.application.config["SESSIONS"]
        session = sessions.get(sid)
        return sid, session, session.game.renderer.floor_svg_id

    def test_png_returns_png_bytes(self, client_with_data_dir):
        sid, _session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.png",
        )
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "image/png"
        assert resp.get_data()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_png_uses_ir_not_cached_svg(self, client_with_data_dir):
        """Mangle the cached SVG; a valid PNG still comes back.

        If the route still rasterised the cache, resvg would be
        handed `<not-an-svg/>` and would either error or produce
        garbage. A clean PNG header proves the bytes were dumped
        from the freshly-built IR via ``ir_to_svg``.
        """
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        depth = session.game.level.depth
        session.game._svg_cache[depth] = (svg_id, "<not-an-svg/>")
        session.game.renderer.floor_svg = "<not-an-svg/>"
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.png",
        )
        assert resp.status_code == 200
        assert resp.get_data()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_png_404_for_unknown_session(self, client_with_data_dir):
        resp = client_with_data_dir.get(
            "/api/game/no-such-sid/floor/no-such-id.png",
        )
        assert resp.status_code == 404

    def test_png_404_for_unknown_svg_id(self, client_with_data_dir):
        sid, _session, _svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/deadbeef.png",
        )
        assert resp.status_code == 404


class TestFloorIRArtefactsCache:
    """Phase 2.3 of plans/nhc_ir_migration_plan.md.

    The IR / IR-JSON / PNG hang off ``Game._ir_cache`` keyed by
    svg_id and lazy-populate on first request. Each test mutates
    the cached entry to a sentinel; if the route honours the cache
    the second response equals the sentinel, otherwise it would
    rebuild from the live level and return the real artefact.
    """

    def _start_dungeon_game(self, c, *, god_mode=False):
        token, _pid = _register_player(c)
        resp = c.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = c.application.config["SESSIONS"]
        session = sessions.get(sid)
        if god_mode:
            session.game.set_god_mode(True)
        return sid, session, session.game.renderer.floor_svg_id

    def test_nir_caches_on_first_request(self, client_with_data_dir):
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        # Cold cache: no entry for this svg_id yet.
        assert svg_id not in session.game._ir_cache
        # First call populates.
        resp1 = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.nir",
        )
        assert resp1.status_code == 200
        body1 = resp1.get_data()
        assert svg_id in session.game._ir_cache
        # Mutate the entry: a second call must serve this byte
        # sequence verbatim (cache hit), not rebuild from level.
        sentinel = b"NIR5" + b"\x00" * 12 + b"sentinel"
        session.game._ir_cache[svg_id].nir = sentinel
        resp2 = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.nir",
        )
        assert resp2.get_data() == sentinel
        assert resp2.get_data() != body1

    def test_json_caches_on_first_request(self, client_with_data_dir):
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir, god_mode=True,
        )
        resp1 = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.json",
        )
        assert resp1.status_code == 200
        text1 = resp1.get_data(as_text=True)
        entry = session.game._ir_cache[svg_id]
        assert entry.ir_json is not None
        # Sentinel proves the second response is served from
        # ``entry.ir_json`` rather than re-dumped from ``entry.nir``.
        entry.ir_json = '{"sentinel": true}'
        resp2 = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.json",
        )
        assert resp2.get_data(as_text=True) == '{"sentinel": true}'
        assert resp2.get_data(as_text=True) != text1

    def test_png_caches_on_first_request(self, client_with_data_dir):
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        resp1 = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.png",
        )
        assert resp1.status_code == 200
        body1 = resp1.get_data()
        entry = session.game._ir_cache[svg_id]
        assert entry.png is not None
        # Sentinel must appear verbatim on the second call —
        # rasterising again would discard it.
        sentinel = b"\x89PNG\r\n\x1a\nsentinel-pixels"
        entry.png = sentinel
        resp2 = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.png",
        )
        assert resp2.get_data() == sentinel
        assert resp2.get_data() != body1


class TestFloorIRArtefactsDiskWiring:
    """Phase 2.3.1 of plans/nhc_ir_migration_plan.md.

    The in-memory IR cache writes through to ``save_ir_artefacts``
    so a server restart can warm the cache off disk via
    ``load_ir_artefacts`` (called from the resume bootstrap).
    Write-through is gated on the live-floor svg_id — older
    cached floors share the save_dir but the disk cache is
    single-floor.
    """

    def _start_dungeon_game(self, c, *, god_mode=False):
        token, _pid = _register_player(c)
        resp = c.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = c.application.config["SESSIONS"]
        session = sessions.get(sid)
        if god_mode:
            session.game.set_god_mode(True)
        return sid, session, session.game.renderer.floor_svg_id

    def test_first_nir_writes_to_disk(self, client_with_data_dir):
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        save_dir = session.save_dir
        assert not (save_dir / "floor.nir").exists()
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.nir",
        )
        assert resp.status_code == 200
        assert (save_dir / "floor.nir").exists()
        assert (save_dir / "floor.meta.json").exists()
        assert (save_dir / "floor.nir").read_bytes() == resp.get_data()

    def test_first_png_writes_to_disk(self, client_with_data_dir):
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        save_dir = session.save_dir
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.png",
        )
        assert resp.status_code == 200
        assert (save_dir / "floor.png").exists()
        assert (save_dir / "floor.png").read_bytes() == resp.get_data()

    def test_first_json_writes_to_disk(self, client_with_data_dir):
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir, god_mode=True,
        )
        save_dir = session.save_dir
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.json",
        )
        assert resp.status_code == 200
        assert (save_dir / "floor.ir.json").exists()
        assert (save_dir / "floor.ir.json").read_text(
            encoding="utf-8",
        ) == resp.get_data(as_text=True)

    def test_svg_route_default_returns_composite(
        self, client_with_data_dir,
    ):
        """Phase 2.5 regression guard: with no ``?bare`` flag, the
        existing route still serves the cached composite SVG.

        Phase 2.18: the .svg endpoint now ships the Rust
        ``nhc_render.ir_to_svg`` output, which doesn't emit the
        per-layer ``<!-- layer.X: N elements -->`` comments the
        Python emitter wrote. The structural sanity check here
        (well-formed envelope + non-empty body) replaces the
        layer-comment probes; Phase 2.21 formalises this PSNR +
        structural-sanity gate across the parity harness.
        """
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.svg",
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert resp.headers["Content-Type"] == "image/svg+xml"
        # The composite SVG must round-trip through the IR
        # pipeline as a complete document.
        assert body.startswith("<?xml") or body.startswith("<svg")
        assert body.rstrip().endswith("</svg>")
        # At least one geometry element from the gameplay layers
        # must appear — guards against an empty envelope leaking
        # through if the dispatcher silently dropped every op.
        assert any(
            tag in body
            for tag in ("<rect", "<path", "<polygon", "<polyline",
                        "<circle", "<ellipse", "<line")
        )

    def test_svg_route_bare_skips_decoration_layers(
        self, client_with_data_dir,
    ):
        """Phase 2.19: ``?bare=1`` flows through the Rust
        ``nhc_render.ir_to_svg(buf, bare=True)`` entry point — the
        SvgPainter doesn't emit per-layer ``<!-- layer.X: -->``
        comments the Python emitter wrote. The assertion here is
        structural: the bare body must be strictly shorter than the
        full composite (decoration ops are filtered) AND remain a
        well-formed SVG document.
        """
        sid, session, svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        bare = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.svg?bare=1",
        )
        full = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.svg",
        )
        assert bare.status_code == 200
        assert full.status_code == 200
        bare_body = bare.get_data(as_text=True)
        full_body = full.get_data(as_text=True)
        assert bare.headers["Content-Type"] == "image/svg+xml"
        assert bare_body.startswith("<?xml") or bare_body.startswith("<svg")
        assert bare_body.rstrip().endswith("</svg>")
        # Decoration ops dropped → bare body strictly shorter than
        # the full composite for any non-empty fixture.
        assert len(bare_body) < len(full_body), (
            f"bare body should shrink from full composite; "
            f"bare={len(bare_body)} full={len(full_body)}"
        )

    def test_svg_route_bare_404_for_unknown_session(
        self, client_with_data_dir,
    ):
        resp = client_with_data_dir.get(
            "/api/game/no-such-sid/floor/no-such-id.svg?bare=1",
        )
        assert resp.status_code == 404

    def test_svg_route_bare_404_for_unknown_svg_id(
        self, client_with_data_dir,
    ):
        sid, _session, _svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/deadbeef.svg?bare=1",
        )
        assert resp.status_code == 404

    def test_export_floor_ir_writes_nir_and_json(
        self, client_with_data_dir, tmp_path, monkeypatch,
    ):
        """Phase 2.4.1: god-mode POST writes floor_ir_<ts>.nir +
        .json into debug/exports/ so the MCP tools can default-
        discover the latest export without an explicit path."""
        monkeypatch.chdir(tmp_path)
        sid, session, _svg_id = self._start_dungeon_game(
            client_with_data_dir, god_mode=True,
        )
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/export/floor_ir",
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        nir_path = Path(payload["path_nir"])
        json_path = Path(payload["path_json"])
        assert nir_path.exists()
        assert json_path.exists()
        # Bytes round-trip the cached IR — same source as .nir route.
        assert nir_path.read_bytes()[4:8] == b"NIR5"
        # JSON dump is canonical and parseable.
        parsed = json.loads(json_path.read_text(encoding="utf-8"))
        assert parsed["major"] == 5
        assert "regions" in parsed

    def test_export_floor_ir_404_for_non_god_mode(
        self, client_with_data_dir, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        sid, _session, _svg_id = self._start_dungeon_game(
            client_with_data_dir,
        )
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/export/floor_ir",
        )
        # Mirrors the other /export/* routes: hide the surface
        # behind a 404 rather than a 403.
        assert resp.status_code == 404

    def test_export_floor_ir_404_for_unknown_session(
        self, client_with_data_dir, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        resp = client_with_data_dir.post(
            "/api/game/no-such-sid/export/floor_ir",
        )
        assert resp.status_code == 404

    def test_resume_warms_ir_cache_from_disk(self, client_with_data_dir):
        # Set up the disk cache: start a game, hit .nir to populate
        # both in-memory and disk, autosave + destroy the session,
        # then resume and confirm the warmed-up _ir_cache entry
        # matches the on-disk bytes.
        token, _pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        sid = resp.get_json()["session_id"]
        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        save_dir = session.save_dir
        svg_id = session.game.renderer.floor_svg_id
        ir_resp = client_with_data_dir.get(
            f"/api/game/{sid}/floor/{svg_id}.nir",
        )
        nir_bytes = ir_resp.get_data()
        autosave(session.game, save_dir)
        sessions.destroy(sid)

        resp = client_with_data_dir.post(
            "/api/game/resume",
            json={"player_token": token},
        )
        assert resp.status_code == 201
        new_sid = resp.get_json()["session_id"]
        new_session = sessions.get(new_sid)
        new_svg_id = new_session.game.renderer.floor_svg_id
        # The resume flow mints a fresh svg_id; the disk-loaded IR
        # is pinned to it so subsequent route hits short-circuit.
        assert new_svg_id in new_session.game._ir_cache
        warmed = new_session.game._ir_cache[new_svg_id]
        assert warmed.nir == nir_bytes


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
        """Create a dungeon-mode game session with god mode
        enabled. Generation params / regenerate endpoints are
        dungeon-only; pass ``world=dungeon`` explicitly so the
        hexcrawl default doesn't land us on the overland map."""
        token, pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
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


class TestHenchmenEndpoint:
    def _create_god_session(self, client_with_data_dir):
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

    def test_henchmen_requires_god_mode(self, client_with_data_dir):
        resp = client_with_data_dir.post("/api/game/new", json={})
        sid = resp.get_json()["session_id"]
        resp = client_with_data_dir.get(f"/api/game/{sid}/henchmen")
        assert resp.status_code == 404

    def test_henchmen_empty_when_none_hired(
        self, client_with_data_dir,
    ):
        sid, _ = self._create_god_session(client_with_data_dir)
        resp = client_with_data_dir.get(f"/api/game/{sid}/henchmen")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"henchmen": [], "count": 0}

    def test_henchmen_returns_hired_party(
        self, client_with_data_dir,
    ):
        from nhc.entities.components import (
            AI, Description, Equipment, Health, Henchman,
            Inventory, Position, Renderable, Stats, Weapon,
        )

        sid, session = self._create_god_session(client_with_data_dir)
        world = session.game.world
        pid = session.game.player_id

        # Equipped weapon
        wid = world.create_entity({
            "Weapon": Weapon(damage="1d8", magic_bonus=1),
            "Description": Description(name="long sword"),
        })
        # Hired henchman owned by the player
        world.create_entity({
            "Position": Position(x=2, y=2),
            "Stats": Stats(strength=2, dexterity=1),
            "Health": Health(current=12, maximum=18),
            "Inventory": Inventory(slots=[], max_slots=12),
            "Equipment": Equipment(weapon=wid),
            "AI": AI(behavior="henchman", faction="human"),
            "Henchman": Henchman(
                owner=pid, level=2, hired=True,
            ),
            "Description": Description(name="Bob"),
            "Renderable": Renderable(glyph="@"),
        })

        resp = client_with_data_dir.get(f"/api/game/{sid}/henchmen")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1
        sheet = data["henchmen"][0]
        assert sheet["name"] == "Bob"
        assert sheet["level"] == 2
        assert sheet["hp"] == 12
        assert sheet["max_hp"] == 18
        assert sheet["equipment"]["weapon"]["name"] == "long sword"


class TestReportEndpoint:
    """POST /api/game/<sid>/report captures the debug bundle, injects
    the user-supplied description as report.txt at the archive root,
    and writes it to ``<data_dir>/reports/<slug>_<utc_ts>Z.tar.gz``.
    Filename stem format is fixed for server-side triage."""

    def _setup(self, c, name="Josep"):
        token, pid = _register_player(c, name)
        registry = c.application.config["PLAYER_REGISTRY"]
        registry.set_tester_mode(pid, True)
        resp = c.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        assert resp.status_code == 201
        return resp.get_json()["session_id"], pid

    def test_rejects_unauthorized_session(self, client_with_data_dir):
        token, _pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        sid = resp.get_json()["session_id"]
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/report",
            json={"description": "buggy"},
        )
        assert resp.status_code == 404

    def test_rejects_empty_description(self, client_with_data_dir):
        sid, _ = self._setup(client_with_data_dir)
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/report",
            json={"description": "   "},
        )
        assert resp.status_code == 400

    def test_rejects_missing_description(self, client_with_data_dir):
        sid, _ = self._setup(client_with_data_dir)
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/report", json={},
        )
        assert resp.status_code == 400

    def test_happy_path_writes_tarball(self, client_with_data_dir):
        sid, _ = self._setup(client_with_data_dir, name="Josep")
        config = client_with_data_dir.application.config["NHC_CONFIG"]
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/report",
            json={"description": "Floor clips under door"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "ok"
        reports_dir = config.data_dir / "reports"
        assert reports_dir.is_dir()
        files = list(reports_dir.glob("*.tar.gz"))
        assert len(files) == 1
        name = files[0].name
        # Slug prefix from player name.
        assert name.startswith("josep_")
        # UTC timestamp suffix ending in Z.
        assert name.endswith("Z.tar.gz")
        # Format: josep_YYYYMMDD_HHMMSSZ.tar.gz (stem has 15 chars
        # after slug: 8 date + _ + 6 time + Z = 16).
        stem = name.removesuffix(".tar.gz")
        assert stem.startswith("josep_")
        assert "path" in data
        assert data["path"].endswith(name)

    def test_tarball_contains_report_txt(self, client_with_data_dir):
        sid, _ = self._setup(client_with_data_dir)
        description = "Stairs missing on depth 3"
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/report",
            json={"description": description},
        )
        assert resp.status_code == 201
        config = client_with_data_dir.application.config["NHC_CONFIG"]
        path = next(
            (config.data_dir / "reports").glob("*.tar.gz"),
        )
        import io
        import tarfile
        with tarfile.open(str(path), "r:gz") as tar:
            names = tar.getnames()
            assert "report.txt" in names
            body = tar.extractfile("report.txt").read().decode("utf-8")
            assert description in body

    def test_slug_handles_special_chars(self, client_with_data_dir):
        sid, _ = self._setup(client_with_data_dir, name="Dr. Møller")
        config = client_with_data_dir.application.config["NHC_CONFIG"]
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/report",
            json={"description": "report"},
        )
        assert resp.status_code == 201
        files = list((config.data_dir / "reports").glob("*.tar.gz"))
        assert len(files) == 1
        # Expect accents stripped, non-alnum collapsed, lowercased.
        assert files[0].name.startswith("dr_moller_")

    def test_also_works_in_god_mode(self, client_with_data_dir):
        """God-mode players keep access to the report flow."""
        token, pid = _register_player(client_with_data_dir)
        registry = client_with_data_dir.application.config[
            "PLAYER_REGISTRY"]
        registry.set_god_mode(pid, True)
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        sid = resp.get_json()["session_id"]
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/report",
            json={"description": "test"},
        )
        assert resp.status_code == 201


class TestTesterModeAccess:
    """Tester mode must grant the same debug-endpoint access as god
    mode, without granting any of god mode's gameplay effects."""

    def _create_tester_session(self, c):
        token, pid = _register_player(c)
        registry = c.application.config["PLAYER_REGISTRY"]
        registry.set_tester_mode(pid, True)
        resp = c.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = c.application.config["SESSIONS"]
        session = sessions.get(sid)
        return sid, session, pid

    def test_new_game_plumbs_tester_mode_from_registry(
        self, client_with_data_dir,
    ):
        sid, session, _ = self._create_tester_session(client_with_data_dir)
        assert session.game.tester_mode is True
        assert session.game.god_mode is False

    def test_tester_mode_defaults_false_on_game(
        self, client_with_data_dir,
    ):
        token, _pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        sid = resp.get_json()["session_id"]
        sessions = client_with_data_dir.application.config["SESSIONS"]
        session = sessions.get(sid)
        assert session.game.tester_mode is False

    def test_bundle_endpoint_accessible_with_tester_mode(
        self, client_with_data_dir,
    ):
        sid, session, _ = self._create_tester_session(client_with_data_dir)
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/export/bundle",
        )
        assert resp.status_code == 200

    def test_capture_layers_accessible_with_tester_mode(
        self, client_with_data_dir,
    ):
        sid, _, _ = self._create_tester_session(client_with_data_dir)
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/capture_layers",
        )
        assert resp.status_code == 200

    def test_upload_layer_pngs_accessible_with_tester_mode(
        self, client_with_data_dir,
    ):
        sid, _, _ = self._create_tester_session(client_with_data_dir)
        resp = client_with_data_dir.post(
            f"/api/game/{sid}/export/layer_pngs",
            json={"layers": {}},
        )
        assert resp.status_code == 200

    def test_bundle_denied_without_god_or_tester(
        self, client_with_data_dir,
    ):
        """Baseline sanity: a plain authenticated player still gets 404."""
        token, _pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
        )
        sid = resp.get_json()["session_id"]
        resp = client_with_data_dir.get(
            f"/api/game/{sid}/export/bundle",
        )
        assert resp.status_code == 404

    def test_index_exposes_tester_mode_flag(self, tmp_path):
        """The index page must inject ``window.NHC_TESTER_MODE``
        so client JS can render the report button."""
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
            admin_lan_cidrs=["192.168.18.0/24"],
            trust_proxy=True,
        )
        app = create_app(config, auth_token="admin-secret")
        app.config["TESTING"] = True
        registry = app.config["PLAYER_REGISTRY"]
        token, pid = registry.register("tester")
        registry.set_tester_mode(pid, True)
        with app.test_client() as c:
            resp = c.get(f"/?token={token}")
            # Follow redirect so the rendered body comes back.
            if resp.status_code == 303:
                resp = c.get("/")
            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert "window.NHC_TESTER_MODE" in body
            assert "window.NHC_TESTER_MODE = true" in body


class TestDebugBundleAutosave:
    def test_bundle_includes_generation_params(self, client_with_data_dir):
        """Debug bundle must include generation parameters.
        Dungeon-only test; pass world explicitly so the hexcrawl
        default (no generation_params) doesn't trip the check."""
        token, pid = _register_player(client_with_data_dir)
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": token, "world": "dungeon"},
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


class TestRankingAPI:
    def test_ranking_empty(self, client_with_data_dir):
        resp = client_with_data_dir.get("/api/ranking")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"entries": []}

    def test_ranking_returns_submitted_scores(self, client_with_data_dir):
        from nhc.web.leaderboard import LeaderboardEntry
        lb = client_with_data_dir.application.config["LEADERBOARD"]
        lb.submit(LeaderboardEntry(
            player_id="p1", name="Alice",
            score=500, depth=3, turn=120, won=False,
            killed_by="goblin", timestamp=1000.0,
        ))
        lb.submit(LeaderboardEntry(
            player_id="p2", name="Bob",
            score=1200, depth=5, turn=300, won=True,
            killed_by="", timestamp=1001.0,
        ))
        resp = client_with_data_dir.get("/api/ranking")
        assert resp.status_code == 200
        entries = resp.get_json()["entries"]
        assert len(entries) == 2
        # Sorted descending by score
        assert entries[0]["name"] == "Bob"
        assert entries[0]["rank"] == 1
        assert entries[0]["won"] is True
        assert entries[1]["name"] == "Alice"
        assert entries[1]["rank"] == 2
        assert entries[1]["killed_by"] == "goblin"

    def test_ranking_limit_parameter(self, client_with_data_dir):
        from nhc.web.leaderboard import LeaderboardEntry
        lb = client_with_data_dir.application.config["LEADERBOARD"]
        for i in range(20):
            lb.submit(LeaderboardEntry(
                player_id=f"p{i}", name=f"P{i}",
                score=i * 10, depth=1, turn=10, won=False,
                killed_by="rat", timestamp=float(i),
            ))
        resp = client_with_data_dir.get("/api/ranking?limit=5")
        entries = resp.get_json()["entries"]
        assert len(entries) == 5
        assert entries[0]["score"] == 190

    def test_ranking_requires_auth_when_enabled(self, tmp_path):
        from nhc.web.auth import hash_token
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
        )
        app = create_app(config, auth_token="admin-secret")
        app.config["TESTING"] = True
        with app.test_client() as c:
            # Without a token: 401
            resp = c.get("/api/ranking")
            assert resp.status_code == 401
            # With a valid player token: 200
            registry = app.config["PLAYER_REGISTRY"]
            token, _pid = registry.register("Alice")
            resp = c.get(f"/api/ranking?token={token}")
            assert resp.status_code == 200

    def test_ranking_rejects_invalid_token(self, tmp_path):
        config = WebConfig(
            max_sessions=2, data_dir=tmp_path, auth_required=True,
        )
        app = create_app(config, auth_token="admin-secret")
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/api/ranking?token=bogus")
            assert resp.status_code == 403

    def test_ws_submits_score_on_game_end(self, client_with_data_dir):
        """_submit_final_score writes a leaderboard entry when a
        session ends (death or victory). Dungeon-mode session
        (the leaderboard records depth, which is dungeon data)."""
        from nhc.web.ws import _submit_final_score

        _token, pid = _register_player(client_with_data_dir, "Hero")
        app = client_with_data_dir.application
        # Create a real game session so session.game is populated.
        resp = client_with_data_dir.post(
            "/api/game/new",
            json={"player_token": _token, "world": "dungeon"},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = app.config["SESSIONS"]
        session = sessions.get(sid)
        session.player_id = pid

        # Simulate death at turn 42.
        session.game.game_over = True
        session.game.killed_by = "goblin"
        session.game.turn = 42

        lb = app.config["LEADERBOARD"]
        assert lb.top(10) == []
        with app.app_context():
            _submit_final_score(session)
        top = lb.top(10)
        assert len(top) == 1
        assert top[0].name == "Hero"
        assert top[0].turn == 42
        assert top[0].killed_by == "goblin"
        assert top[0].won is False
        assert top[0].depth >= 1

    def test_ws_skips_score_in_god_mode(self, client_with_data_dir):
        """God-mode runs must NOT appear in the leaderboard."""
        from nhc.web.ws import _submit_final_score

        _token, pid = _register_player(client_with_data_dir, "Cheater")
        app = client_with_data_dir.application
        resp = client_with_data_dir.post(
            "/api/game/new", json={"player_token": _token},
        )
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]
        sessions = app.config["SESSIONS"]
        session = sessions.get(sid)
        session.player_id = pid

        # Simulate death in god mode.
        session.game.game_over = True
        session.game.killed_by = "goblin"
        session.game.turn = 99
        session.game.god_mode = True

        lb = app.config["LEADERBOARD"]
        with app.app_context():
            _submit_final_score(session)
        assert lb.top(10) == [], "god-mode games must not be recorded"


class TestLabelsEndpoint:
    """Regression tests for /api/game/<sid>/labels.json under gthread.

    The thread-local i18n manager in ``nhc.i18n`` means every worker
    thread that calls ``t()`` must first call ``init(lang)``. Under
    gunicorn --worker-class gevent this happened implicitly — every
    request shared one OS thread, so the single ``i18n_init`` in
    /api/game/new carried through to all subsequent requests. After
    switching to gthread, requests land on different pool threads; a
    thread that never ran /api/game/new served /labels.json from an
    empty manager and returned the raw keys (e.g. ``ui.autodig_on``)
    instead of translated strings.
    """

    def test_labels_translated_when_called_from_fresh_thread(
        self, tmp_path,
    ):
        """Serving /labels.json from a thread that never ran
        /api/game/new must still return translated strings."""
        import threading

        from nhc.i18n import init as i18n_init

        config = WebConfig(max_sessions=4, data_dir=tmp_path)
        app = create_app(config)
        app.config["TESTING"] = True

        # Create a session on the main thread (this initializes i18n
        # for the main thread).
        with app.test_client() as c:
            resp = c.post("/api/game/new", json={"lang": "ca"})
            assert resp.status_code == 201
            sid = resp.get_json()["session_id"]

        # Run the labels request from a FRESH worker thread whose
        # thread-local i18n manager has never been initialized. This
        # is what gthread does: each pool thread starts fresh, and
        # without the endpoint-level init the manager returns raw
        # keys.
        result: dict = {}

        def _worker():
            # Sanity: ensure this thread really has no translations
            # loaded yet. The test would pass trivially if the main
            # thread's manager bled across.
            from nhc.i18n import _get_manager
            mgr = _get_manager()
            assert mgr._strings == {}, (
                "fresh thread should start with an empty manager"
            )
            with app.test_client() as c:
                resp = c.get(f"/api/game/{sid}/labels.json")
                result["status"] = resp.status_code
                result["body"] = resp.get_json()

        t = threading.Thread(target=_worker)
        t.start()
        t.join(timeout=30)

        assert result.get("status") == 200, result
        body = result["body"]
        # Catalan labels must be resolved, not returned as raw keys.
        assert body["autodig_on"] != "ui.autodig_on", (
            f"autodig_on came back as raw key: {body['autodig_on']!r}"
        )
        assert body["autodig_off"] != "ui.autodig_off", (
            f"autodig_off came back as raw key: {body['autodig_off']!r}"
        )
        assert body["toolbar_pickup"] != "ui.toolbar_pickup"
        # Spot-check the Catalan string actually arrived.
        i18n_init("ca")
        from nhc.i18n import t as tr
        assert body["autodig_off"] == tr("ui.autodig_off")
