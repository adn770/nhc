"""Tests for the web session manager."""

import time

import pytest

from nhc.web.config import WebConfig
from nhc.web.sessions import SessionManager, player_id_from_token


@pytest.fixture
def manager():
    return SessionManager(WebConfig(max_sessions=3))


class TestSessionManager:
    def test_create_session(self, manager):
        session = manager.create(lang="ca", tileset="classic")
        assert session.session_id
        assert session.lang == "ca"
        assert session.tileset == "classic"
        assert manager.active_count == 1

    def test_create_uses_defaults(self, manager):
        session = manager.create()
        assert session.lang == "ca"
        assert session.tileset == "classic"

    def test_get_session(self, manager):
        session = manager.create()
        retrieved = manager.get(session.session_id)
        assert retrieved is session

    def test_get_nonexistent(self, manager):
        assert manager.get("bogus") is None

    def test_destroy_session(self, manager):
        session = manager.create()
        assert manager.destroy(session.session_id) is True
        assert manager.active_count == 0

    def test_destroy_nonexistent(self, manager):
        assert manager.destroy("bogus") is False

    def test_max_sessions_enforced(self, manager):
        for _ in range(3):
            manager.create()
        with pytest.raises(ValueError, match="Session limit"):
            manager.create()

    def test_list_sessions(self, manager):
        s1 = manager.create(lang="en")
        s2 = manager.create(lang="ca")
        listing = manager.list_sessions()
        assert len(listing) == 2
        ids = {s["session_id"] for s in listing}
        assert s1.session_id in ids
        assert s2.session_id in ids

    def test_unique_session_ids(self, manager):
        s1 = manager.create()
        s2 = manager.create()
        assert s1.session_id != s2.session_id


class TestPlayerIdentity:
    def test_player_id_from_token_deterministic(self):
        token = "test-token-abc"
        assert player_id_from_token(token) == player_id_from_token(token)

    def test_player_id_from_token_length(self):
        pid = player_id_from_token("some-token")
        assert len(pid) == 12

    def test_different_tokens_different_ids(self):
        pid1 = player_id_from_token("token-a")
        pid2 = player_id_from_token("token-b")
        assert pid1 != pid2

    def test_create_with_player_id(self, manager):
        session = manager.create(player_id="abc123")
        assert session.player_id == "abc123"

    def test_get_by_player(self, manager):
        s1 = manager.create(player_id="player_a")
        manager.create(player_id="player_b")
        found = manager.get_by_player("player_a")
        assert found is s1

    def test_get_by_player_not_found(self, manager):
        assert manager.get_by_player("nobody") is None

    def test_session_connected_by_default(self, manager):
        session = manager.create()
        assert session.connected is True
        assert session.disconnected_at is None


class TestSessionReaper:
    def test_reap_stale_sessions(self):
        mgr = SessionManager(WebConfig(max_sessions=3))
        s1 = mgr.create()
        s1.connected = False
        s1.disconnected_at = time.time() - 3600  # 1 hour ago

        s2 = mgr.create()  # still connected

        mgr._reap_stale()
        assert mgr.get(s1.session_id) is None
        assert mgr.get(s2.session_id) is s2

    def test_reap_keeps_recent_disconnects(self):
        mgr = SessionManager(WebConfig(max_sessions=3))
        s1 = mgr.create()
        s1.connected = False
        s1.disconnected_at = time.time() - 60  # 1 minute ago

        mgr._reap_stale()
        assert mgr.get(s1.session_id) is s1

    def test_reap_on_create(self):
        mgr = SessionManager(WebConfig(max_sessions=2))
        s1 = mgr.create()
        s2 = mgr.create()
        s1.connected = False
        s1.disconnected_at = time.time() - 3600

        # Would fail without reaping (limit=2)
        s3 = mgr.create()
        assert s3 is not None
        assert mgr.active_count == 2
