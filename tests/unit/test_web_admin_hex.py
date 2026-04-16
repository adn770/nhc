"""Admin UI hex-panel endpoints (M-4.2).

Exposes the M-4.1 pure-function helpers on the live admin
session (not the autosave file) so an operator can peek at /
poke a running hex world from the /admin page. Non-hex
sessions return a 400 so the UI can surface a helpful error
instead of silently falling through.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import GameMode
from nhc.i18n import init as i18n_init
from nhc.web.app import create_app
from nhc.web.config import WebConfig


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


class _FakeClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync


def _admin_client(tmp_path):
    config = WebConfig(max_sessions=4, data_dir=tmp_path)
    app = create_app(config)
    app.config["TESTING"] = True
    return app, app.test_client()


def _make_hex_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _register_hex_session(app, test_client, tmp_path):
    """Register a player, make a session, attach a hex Game."""
    registry = app.config["PLAYER_REGISTRY"]
    token, pid = registry.register("Tester")
    sessions = app.config["SESSIONS"]
    # SessionManager.create signature may differ across builds, so
    # construct a bare session object directly and plug it in.
    from nhc.web.sessions import Session
    game = _make_hex_game(tmp_path)
    session = Session(
        session_id="test-sid",
        lang="en",
        tileset="default",
        player_id=pid,
    )
    session.game = game
    sessions._sessions[session.session_id] = session
    return token, session


# ---------------------------------------------------------------------------
# State endpoint
# ---------------------------------------------------------------------------


def test_admin_hex_state_returns_snapshot(tmp_path) -> None:
    app, client = _admin_client(tmp_path)
    _, session = _register_hex_session(app, client, tmp_path)
    resp = client.get(
        f"/api/admin/sessions/{session.session_id}/hex/state",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["day"] >= 1
    assert body["cells"], "cells must be reported"
    assert "player" in body


def test_admin_hex_state_404_for_missing_session(tmp_path) -> None:
    app, client = _admin_client(tmp_path)
    resp = client.get("/api/admin/sessions/nope/hex/state")
    assert resp.status_code == 404


def test_admin_hex_state_400_for_dungeon_session(tmp_path) -> None:
    """A dungeon-only session has no hex_world; endpoint should
    return a helpful 400 rather than crash."""
    app, client = _admin_client(tmp_path)
    registry = app.config["PLAYER_REGISTRY"]
    _, pid = registry.register("DungeonUser")
    sessions = app.config["SESSIONS"]
    from nhc.web.sessions import Session
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.DUNGEON,
        save_dir=tmp_path,
        seed=42,
    )
    g.hex_world = None
    session = Session(
        session_id="dungeon-sid", lang="en",
        tileset="default", player_id=pid,
    )
    session.game = g
    sessions._sessions[session.session_id] = session
    resp = client.get(
        f"/api/admin/sessions/{session.session_id}/hex/state",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Reveal-all action
# ---------------------------------------------------------------------------


def test_admin_hex_reveal_all_lifts_fog(tmp_path) -> None:
    app, client = _admin_client(tmp_path)
    _, session = _register_hex_session(app, client, tmp_path)
    hw = session.game.hex_world
    assert len(hw.revealed) < len(hw.cells)
    resp = client.post(
        f"/api/admin/sessions/{session.session_id}/hex/reveal",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_revealed"] == len(hw.cells)
    assert hw.revealed == set(hw.cells.keys())


# ---------------------------------------------------------------------------
# Teleport action
# ---------------------------------------------------------------------------


def test_admin_hex_teleport_updates_player(tmp_path) -> None:
    app, client = _admin_client(tmp_path)
    _, session = _register_hex_session(app, client, tmp_path)
    # Pick a coord we know exists in the staggered grid: the
    # generator seeds cells densely, so something small like
    # (0, 1) is safe.
    resp = client.post(
        f"/api/admin/sessions/{session.session_id}/hex/teleport",
        json={"q": 0, "r": 1},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    # The live session's player coord advanced to the target.
    assert session.game.hex_player_position.q == 0
    assert session.game.hex_player_position.r == 1


def test_admin_hex_teleport_rejects_out_of_shape(tmp_path) -> None:
    app, client = _admin_client(tmp_path)
    _, session = _register_hex_session(app, client, tmp_path)
    resp = client.post(
        f"/api/admin/sessions/{session.session_id}/hex/teleport",
        json={"q": 99, "r": 99},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
