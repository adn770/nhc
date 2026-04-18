"""In-game hex debug tools (/api/game/<sid>/hex/*).

Exposes the M-4.1 pure-function helpers on the live session
through the in-game debug panel (gear icon), gated on
``Game.god_mode`` like the existing ``/regenerate`` endpoint.
Non-hex sessions and non-god-mode sessions return 400 / 404 so
the UI can surface an informative error instead of silently
failing.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import Rumor
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


def _app(tmp_path):
    config = WebConfig(max_sessions=4, data_dir=tmp_path)
    app = create_app(config)
    app.config["TESTING"] = True
    return app, app.test_client()


def _make_hex_game(tmp_path, *, god: bool = True) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
        god_mode=god,
    )
    g.initialize()
    return g


def _register_session(app, tmp_path, *, god: bool = True):
    registry = app.config["PLAYER_REGISTRY"]
    token, pid = registry.register("Tester")
    sessions = app.config["SESSIONS"]
    from nhc.web.sessions import Session
    game = _make_hex_game(tmp_path, god=god)
    session = Session(
        session_id="sid-1", lang="en",
        tileset="default", player_id=pid,
    )
    session.game = game
    sessions._sessions[session.session_id] = session
    return token, session


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth / mode guards
# ---------------------------------------------------------------------------


def test_hex_state_requires_god_mode(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path, god=False)
    resp = client.get(
        f"/api/game/{session.session_id}/hex/state",
        headers=_auth(token),
    )
    assert resp.status_code == 404, (
        "non-god sessions should mirror the regenerate endpoint "
        "and return 404"
    )


def test_hex_state_404_for_missing_session(tmp_path) -> None:
    app, client = _app(tmp_path)
    registry = app.config["PLAYER_REGISTRY"]
    token, _ = registry.register("Tester")
    resp = client.get(
        "/api/game/nope/hex/state",
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_hex_state_400_for_dungeon_session(tmp_path) -> None:
    app, client = _app(tmp_path)
    registry = app.config["PLAYER_REGISTRY"]
    token, pid = registry.register("DungeonUser")
    sessions = app.config["SESSIONS"]
    from nhc.web.sessions import Session
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.DUNGEON,
        save_dir=tmp_path,
        seed=42,
        god_mode=True,
    )
    g.hex_world = None
    session = Session(
        session_id="dungeon-sid", lang="en",
        tileset="default", player_id=pid,
    )
    session.game = g
    sessions._sessions[session.session_id] = session
    resp = client.get(
        f"/api/game/{session.session_id}/hex/state",
        headers=_auth(token),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Read-only: state
# ---------------------------------------------------------------------------


def test_hex_state_returns_snapshot(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    resp = client.get(
        f"/api/game/{session.session_id}/hex/state",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["day"] >= 1
    assert body["cells"]
    assert "player" in body


# ---------------------------------------------------------------------------
# Reveal / teleport
# ---------------------------------------------------------------------------


def test_hex_reveal_lifts_fog(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path, god=False)
    session.game.god_mode = True
    hw = session.game.hex_world
    # Re-fog: god init revealed everything; reset so reveal has
    # something to do.
    hw.revealed.clear()
    hw.revealed.add(session.game.hex_player_position)
    resp = client.post(
        f"/api/game/{session.session_id}/hex/reveal",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_revealed"] == len(hw.cells)


def test_hex_teleport_updates_player(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    resp = client.post(
        f"/api/game/{session.session_id}/hex/teleport",
        headers=_auth(token),
        json={"q": 0, "r": 1},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert session.game.hex_player_position.q == 0
    assert session.game.hex_player_position.r == 1


def test_hex_teleport_rejects_out_of_shape(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    resp = client.post(
        f"/api/game/{session.session_id}/hex/teleport",
        headers=_auth(token),
        json={"q": 99, "r": 99},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Force encounter
# ---------------------------------------------------------------------------


def test_hex_force_encounter_stages_on_pending(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    resp = client.post(
        f"/api/game/{session.session_id}/hex/force_encounter",
        headers=_auth(token),
        json={"biome": "forest", "creatures": ["goblin", "kobold"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["biome"] == "forest"
    # Live mutation: the game's pending_encounter now reflects it.
    assert session.game.pending_encounter is not None
    assert session.game.pending_encounter.creatures == [
        "goblin", "kobold",
    ]


def test_hex_force_encounter_unknown_biome_400(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    resp = client.post(
        f"/api/game/{session.session_id}/hex/force_encounter",
        headers=_auth(token),
        json={"biome": "moonlands"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Clock + rumor + cleared + seed
# ---------------------------------------------------------------------------


def test_hex_advance_clock_moves_day(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    hw = session.game.hex_world
    day0 = hw.day
    resp = client.post(
        f"/api/game/{session.session_id}/hex/advance_clock",
        headers=_auth(token),
        json={"segments": 4},
    )
    assert resp.status_code == 200
    assert hw.day == day0 + 1


def test_hex_rumor_truth_flips_existing(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    session.game.hex_world.active_rumors = [
        Rumor(id="r1", text="rumor.true_feature", truth=True),
    ]
    resp = client.post(
        f"/api/game/{session.session_id}/hex/rumor_truth",
        headers=_auth(token),
        json={"rumor_id": "r1", "truth": False},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["updated"] is True
    assert session.game.hex_world.active_rumors[0].truth is False


def test_hex_clear_dungeon_adds_to_cleared(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    coord = session.game.hex_player_position
    resp = client.post(
        f"/api/game/{session.session_id}/hex/clear_dungeon",
        headers=_auth(token),
        json={"q": coord.q, "r": coord.r},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert coord in session.game.hex_world.cleared


def test_hex_seed_dungeon_writes_feature(tmp_path) -> None:
    app, client = _app(tmp_path)
    token, session = _register_session(app, tmp_path)
    coord = session.game.hex_player_position
    resp = client.post(
        f"/api/game/{session.session_id}/hex/seed_dungeon",
        headers=_auth(token),
        json={
            "q": coord.q, "r": coord.r,
            "feature": "ruin",
            "template": "procedural:ruin",
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    cell = session.game.hex_world.cells[coord]
    assert cell.feature.value == "ruin"
    assert cell.dungeon.template == "procedural:ruin"
