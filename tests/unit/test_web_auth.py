"""Tests for web authentication."""

import pytest

from nhc.web.auth import generate_token, hash_token


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
        from flask import Flask, jsonify
        from nhc.web.auth import require_auth

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
