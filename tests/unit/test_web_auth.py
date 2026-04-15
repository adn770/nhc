"""Tests for web authentication."""

import ipaddress

import pytest
from flask import Flask, g, jsonify

from nhc.web.auth import (
    _ip_in_networks, generate_token, hash_token,
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


class TestIpInNetworks:
    """Allowlist-style LAN check.

    Replaces the old ``is_private()`` check, which treated loopback
    and Docker bridges as "LAN" and silently bypassed the admin
    guard when the app sat behind a reverse proxy on localhost.
    """

    _LAN = [ipaddress.ip_network("192.168.18.0/24")]

    def test_ip_inside_allowed_network(self):
        assert _ip_in_networks("192.168.18.5", self._LAN)

    def test_ip_outside_allowed_network(self):
        assert not _ip_in_networks("192.168.19.5", self._LAN)
        assert not _ip_in_networks("8.8.8.8", self._LAN)

    def test_loopback_is_not_lan(self):
        """Regression for the admin LAN-guard bypass: 127.0.0.1
        is what Flask sees for every request behind a loopback
        reverse proxy; it must not satisfy the LAN check."""
        assert not _ip_in_networks("127.0.0.1", self._LAN)

    def test_docker_bridge_is_not_lan(self):
        """Regression: Docker's default bridge range (172.17.0.x)
        is what Flask sees when the reverse proxy runs in another
        container; it must not satisfy the LAN check."""
        assert not _ip_in_networks("172.17.0.2", self._LAN)

    def test_empty_networks_list_fails_closed(self):
        """With no configured LAN, deny every client."""
        assert not _ip_in_networks("192.168.18.5", [])

    def test_invalid_inputs(self):
        assert not _ip_in_networks(None, self._LAN)
        assert not _ip_in_networks("", self._LAN)
        assert not _ip_in_networks("not-an-ip", self._LAN)


class TestRequireAdmin:
    @pytest.fixture
    def admin_app(self):
        token = "admin-secret"
        admin_hash = hash_token(token)
        lan = [ipaddress.ip_network("192.168.18.0/24")]
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/admin-route")
        @require_admin(admin_hash, lan_networks=lan)
        def admin_route():
            return jsonify({"status": "ok"})

        return app, token

    def test_valid_admin_from_lan(self, admin_app):
        app, token = admin_app
        with app.test_client() as c:
            resp = c.get(f"/admin-route?token={token}",
                         environ_base={"REMOTE_ADDR": "192.168.18.50"})
            assert resp.status_code == 200

    def test_admin_cookie_from_lan(self, admin_app):
        app, token = admin_app
        with app.test_client() as c:
            c.set_cookie("nhc_admin_token", token)
            resp = c.get("/admin-route",
                         environ_base={"REMOTE_ADDR": "192.168.18.50"})
            assert resp.status_code == 200

    def test_reject_loopback_even_with_valid_token(self, admin_app):
        """C1 regression: 127.0.0.1 must be rejected."""
        app, token = admin_app
        with app.test_client() as c:
            resp = c.get(f"/admin-route?token={token}",
                         environ_base={"REMOTE_ADDR": "127.0.0.1"})
            assert resp.status_code == 403

    def test_reject_docker_bridge_even_with_valid_token(self, admin_app):
        """C1 regression: Docker bridge must be rejected."""
        app, token = admin_app
        with app.test_client() as c:
            resp = c.get(f"/admin-route?token={token}",
                         environ_base={"REMOTE_ADDR": "172.17.0.2"})
            assert resp.status_code == 403

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
                         environ_base={"REMOTE_ADDR": "192.168.18.50"})
            assert resp.status_code == 403

    def test_reject_no_token(self, admin_app):
        app, _ = admin_app
        with app.test_client() as c:
            resp = c.get("/admin-route",
                         environ_base={"REMOTE_ADDR": "192.168.18.50"})
            assert resp.status_code == 401

    def test_reject_when_no_lan_configured(self):
        """If admin_lan_cidrs is empty, deny all admin access."""
        token = "admin-secret"
        admin_hash = hash_token(token)
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/admin-route")
        @require_admin(admin_hash, lan_networks=[])
        def admin_route():
            return jsonify({"status": "ok"})

        with app.test_client() as c:
            resp = c.get(f"/admin-route?token={token}",
                         environ_base={"REMOTE_ADDR": "192.168.18.50"})
            assert resp.status_code == 403


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
