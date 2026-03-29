"""Tests for the web API endpoints."""

import json

import pytest

from nhc.web.app import create_app
from nhc.web.config import WebConfig


@pytest.fixture
def client():
    config = WebConfig(max_sessions=2)
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
