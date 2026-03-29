"""Tests for the web session manager."""

import pytest

from nhc.web.config import WebConfig
from nhc.web.sessions import SessionManager


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
