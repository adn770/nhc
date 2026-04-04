"""Tests for the persistent player registry."""

import json

import pytest

from nhc.web.auth import hash_token
from nhc.web.registry import PlayerRegistry
from nhc.web.sessions import player_id_from_token


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "players.json"
    reg = PlayerRegistry(path)
    reg.load()
    return reg


class TestRegister:
    def test_register_returns_token_and_id(self, registry):
        token, pid = registry.register("Alice")
        assert len(token) > 20
        assert len(pid) == 12

    def test_register_creates_file(self, registry, tmp_path):
        registry.register("Bob")
        path = tmp_path / "players.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data["players"]) == 1
        assert data["players"][0]["name"] == "Bob"

    def test_register_stores_hash_not_token(self, registry):
        token, pid = registry.register("Carol")
        entry = registry.get(pid)
        assert entry["token_hash"] == hash_token(token)
        # Token itself should not appear in registry
        raw = registry._path.read_text()
        assert token not in raw

    def test_register_multiple(self, registry):
        registry.register("A")
        registry.register("B")
        registry.register("C")
        assert len(registry.list_all()) == 3


class TestValidation:
    def test_valid_token(self, registry):
        token, _ = registry.register("Alice")
        h = hash_token(token)
        assert registry.is_valid_token_hash(h)

    def test_unknown_hash(self, registry):
        assert not registry.is_valid_token_hash("deadbeef")

    def test_revoked_token_invalid(self, registry):
        token, pid = registry.register("Alice")
        registry.revoke(pid)
        h = hash_token(token)
        assert not registry.is_valid_token_hash(h)


class TestRevoke:
    def test_revoke_existing(self, registry):
        _, pid = registry.register("Alice")
        assert registry.revoke(pid)
        entry = registry.get(pid)
        assert entry["revoked"] is True

    def test_revoke_nonexistent(self, registry):
        assert not registry.revoke("bogus")

    def test_revoke_persists(self, tmp_path):
        path = tmp_path / "players.json"
        reg1 = PlayerRegistry(path)
        reg1.load()
        _, pid = reg1.register("Alice")
        reg1.revoke(pid)

        # Reload from disk
        reg2 = PlayerRegistry(path)
        reg2.load()
        entry = reg2.get(pid)
        assert entry["revoked"] is True


class TestPersistence:
    def test_load_roundtrip(self, tmp_path):
        path = tmp_path / "players.json"
        reg1 = PlayerRegistry(path)
        reg1.load()
        token, pid = reg1.register("Alice")

        reg2 = PlayerRegistry(path)
        reg2.load()
        assert len(reg2.list_all()) == 1
        assert reg2.get(pid)["name"] == "Alice"
        assert reg2.is_valid_token_hash(hash_token(token))

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        reg = PlayerRegistry(path)
        reg.load()
        assert reg.list_all() == []

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "players.json"
        path.write_text("not json")
        reg = PlayerRegistry(path)
        reg.load()
        assert reg.list_all() == []


class TestLanguagePreference:
    def test_new_player_has_empty_lang(self, registry):
        _, pid = registry.register("Alice")
        entry = registry.get(pid)
        assert entry["lang"] == ""

    def test_set_lang_persists(self, registry):
        _, pid = registry.register("Alice")
        assert registry.set_lang(pid, "es")
        assert registry.get(pid)["lang"] == "es"

    def test_set_lang_nonexistent(self, registry):
        assert not registry.set_lang("bogus", "en")

    def test_set_lang_survives_reload(self, tmp_path):
        path = tmp_path / "players.json"
        reg1 = PlayerRegistry(path)
        reg1.load()
        _, pid = reg1.register("Alice")
        reg1.set_lang(pid, "ca")

        reg2 = PlayerRegistry(path)
        reg2.load()
        assert reg2.get(pid)["lang"] == "ca"

    def test_legacy_player_gets_default_lang(self, tmp_path):
        """Players registered before lang field should get empty default."""
        path = tmp_path / "players.json"
        path.write_text(json.dumps({"players": [{
            "player_id": "abc123",
            "name": "Legacy",
            "token_hash": "deadbeef",
            "created_at": 0,
            "revoked": False,
            "god_mode": False,
        }]}))
        reg = PlayerRegistry(path)
        reg.load()
        assert reg.get("abc123")["lang"] == ""


class TestPlayerIdForHash:
    def test_returns_pid(self, registry):
        token, pid = registry.register("Alice")
        h = hash_token(token)
        assert registry.player_id_for_hash(h) == pid

    def test_returns_empty_for_unknown(self, registry):
        assert registry.player_id_for_hash("unknown") == ""
