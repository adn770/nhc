"""Tests for web authentication."""

import pytest
from flask import Flask, g, jsonify

from nhc.web.auth import (
    _is_lan, generate_token, hash_token,
    require_admin, require_auth, require_player,
)
from nhc.web.registry import PlayerRegistry


class TestTokens:
    def test_generate_token_is_unique(self):
        t1 = generate_token()
        t2 = generate_token()
        assert t1 != t2

    def test_generate_token_length(self):
        token = generate_token()
        assert len(token) >= 32

    def test_hash_is_deterministic(self):
        token = "test_token_123"
        h1 = hash_token(token)
        h2 = hash_token(token)
        assert h1 == h2

    def test_hash_differs_for_different_tokens(self):
        h1 = hash_token("token_a")
        h2 = hash_token("token_b")
        assert h1 != h2


class TestAuthMiddleware:
    """Test auth enforcement on Flask routes."""

    @pytest.fixture
    def app_with_auth(self):
        token = "secret_test_token"
        valid = {hash_token(token)}

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/protected")
        @require_auth(valid)
        def protected():
            return jsonify({"status": "ok"})

        return app, token

    def test_no_token_returns_401(self, app_with_auth):
        app, _ = app_with_auth
        with app.test_client() as c:
            resp = c.get("/protected")
            assert resp.status_code == 401

    def test_wrong_token_returns_403(self, app_with_auth):
        app, _ = app_with_auth
        with app.test_client() as c:
            resp = c.get("/protected",
                         headers={"Authorization": "Bearer wrong"})
            assert resp.status_code == 403

    def test_valid_bearer_header(self, app_with_auth):
        app, token = app_with_auth
        with app.test_client() as c:
            resp = c.get("/protected",
                         headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200

    def test_valid_cookie(self, app_with_auth):
        app, token = app_with_auth
        with app.test_client() as c:
            c.set_cookie("nhc_token", token)
            resp = c.get("/protected")
            assert resp.status_code == 200

    def test_valid_query_param(self, app_with_auth):
        app, token = app_with_auth
        with app.test_client() as c:
            resp = c.get(f"/protected?token={token}")
            assert resp.status_code == 200


class TestIsLan:
    def test_private_ipv4(self):
        assert _is_lan("192.168.1.100")
        assert _is_lan("10.0.0.1")
        assert _is_lan("172.16.0.1")
        assert _is_lan("127.0.0.1")

    def test_public_ipv4(self):
        assert not _is_lan("8.8.8.8")
        assert not _is_lan("1.2.3.4")

    def test_loopback_ipv6(self):
        assert _is_lan("::1")

    def test_none_and_invalid(self):
        assert not _is_lan(None)
        assert not _is_lan("")
        assert not _is_lan("not-an-ip")


class TestRequireAdmin:
    @pytest.fixture
    def admin_app(self):
        token = "admin-secret"
        admin_hash = hash_token(token)
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/admin-route")
        @require_admin(admin_hash)
        def admin_route():
            return jsonify({"status": "ok"})

        return app, token

    def test_valid_admin_from_lan(self, admin_app):
        app, token = admin_app
        with app.test_client() as c:
            resp = c.get(f"/admin-route?token={token}",
                         environ_base={"REMOTE_ADDR": "192.168.1.50"})
            assert resp.status_code == 200

    def test_admin_cookie(self, admin_app):
        app, token = admin_app
        with app.test_client() as c:
            c.set_cookie("nhc_admin_token", token)
            resp = c.get("/admin-route",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
            assert resp.status_code == 200

    def test_reject_from_public_ip(self, admin_app):
        app, token = admin_app
        with app.test_client() as c:
            resp = c.get(f"/admin-route?token={token}",
                         environ_base={"REMOTE_ADDR": "8.8.8.8"})
            assert resp.status_code == 403

    def test_reject_wrong_token(self, admin_app):
        app, _ = admin_app
        with app.test_client() as c:
            resp = c.get("/admin-route?token=wrong",
                         environ_base={"REMOTE_ADDR": "192.168.1.50"})
            assert resp.status_code == 403

    def test_reject_no_token(self, admin_app):
        app, _ = admin_app
        with app.test_client() as c:
            resp = c.get("/admin-route",
                         environ_base={"REMOTE_ADDR": "192.168.1.50"})
            assert resp.status_code == 401


class TestRequirePlayer:
    @pytest.fixture
    def player_app(self, tmp_path):
        reg = PlayerRegistry(tmp_path / "players.json")
        reg.load()
        token, pid = reg.register("Tester")

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/game-route")
        @require_player(reg)
        def game_route():
            return jsonify({"player_id": g.player_id})

        return app, reg, token, pid

    def test_valid_player_token(self, player_app):
        app, _, token, pid = player_app
        with app.test_client() as c:
            resp = c.get(f"/game-route?token={token}")
            assert resp.status_code == 200
            assert resp.get_json()["player_id"] == pid

    def test_sets_g_player_id(self, player_app):
        app, _, token, pid = player_app
        with app.test_client() as c:
            resp = c.get(f"/game-route?token={token}")
            assert resp.get_json()["player_id"] == pid

    def test_reject_no_token(self, player_app):
        app, _, _, _ = player_app
        with app.test_client() as c:
            resp = c.get("/game-route")
            assert resp.status_code == 401

    def test_reject_unknown_token(self, player_app):
        app, _, _, _ = player_app
        with app.test_client() as c:
            resp = c.get("/game-route?token=bogus")
            assert resp.status_code == 403

    def test_reject_revoked_token(self, player_app):
        app, reg, token, pid = player_app
        reg.revoke(pid)
        with app.test_client() as c:
            resp = c.get(f"/game-route?token={token}")
            assert resp.status_code == 403

    def test_player_cookie(self, player_app):
        app, _, token, pid = player_app
        with app.test_client() as c:
            c.set_cookie("nhc_token", token)
            resp = c.get("/game-route")
            assert resp.status_code == 200
