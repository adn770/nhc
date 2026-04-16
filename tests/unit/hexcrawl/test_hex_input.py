"""Server-side hex-mode input handling.

Covers:

* ``Game._process_hex_turn`` -- maps intent/data from a WS ``action``
  message to the right Game method (``apply_hex_step`` /
  ``enter_hex_feature`` / ``rest`` / disconnect).
* The classic-mode dispatch now also accepts ``hex_exit`` so the
  player can leave a dungeon from inside it without typing.
* The web ``/api/game/new`` endpoint accepts an optional ``world``
  field in the POST body and validates it.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.i18n import init as i18n_init
from nhc.web.app import create_app
from nhc.web.config import WebConfig


class _QueueClient:
    """GameClient stand-in that feeds a single scripted WS payload
    through get_input() then reports disconnect."""

    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __init__(self, script: list[tuple[str, object]]) -> None:
        # Each entry is (intent, data). We walk the list, then
        # return disconnect so the caller exits cleanly.
        self._script = list(script)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync

    async def get_input(self):
        if self._script:
            return self._script.pop(0)
        return ("disconnect", None)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(
    script: list[tuple[str, object]], tmp_path,
    mode: GameMode = GameMode.HEX_EASY,
) -> Game:
    g = Game(
        client=_QueueClient(script),
        backend=None,
        game_mode="classic",
        world_mode=mode,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


# ---------------------------------------------------------------------------
# _process_hex_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_hex_turn_moves_on_hex_step(tmp_path) -> None:
    g = _make_game([("hex_step", [1, 0])], tmp_path)
    origin = g.hex_player_position
    outcome = await g._process_hex_turn()
    assert outcome == "moved"
    assert g.hex_player_position == HexCoord(origin.q + 1, origin.r)


@pytest.mark.asyncio
async def test_process_hex_turn_ignores_non_adjacent_step(tmp_path) -> None:
    # [3, 0] is three hexes away, not adjacent.
    g = _make_game([("hex_step", [3, 0])], tmp_path)
    origin = g.hex_player_position
    outcome = await g._process_hex_turn()
    assert outcome == "ignored"
    assert g.hex_player_position == origin


@pytest.mark.asyncio
async def test_process_hex_turn_enters_feature(tmp_path) -> None:
    g = _make_game([("hex_enter", None)], tmp_path)
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave", depth=1)
    outcome = await g._process_hex_turn()
    assert outcome == "entered"
    assert g.level is not None


@pytest.mark.asyncio
async def test_process_hex_turn_enter_fails_without_dungeon(tmp_path) -> None:
    g = _make_game([("hex_enter", None)], tmp_path)
    # Player on hub (CITY) but with no DungeonRef.
    g.hex_world.cells[g.hex_player_position].dungeon = None
    outcome = await g._process_hex_turn()
    assert outcome == "ignored"
    assert g.level is None


@pytest.mark.asyncio
async def test_process_hex_turn_rest_advances_full_day(tmp_path) -> None:
    g = _make_game([("hex_rest", None)], tmp_path)
    day0 = g.hex_world.day
    outcome = await g._process_hex_turn()
    assert outcome == "rest"
    assert g.hex_world.day == day0 + 1


@pytest.mark.asyncio
async def test_process_hex_turn_disconnect(tmp_path) -> None:
    g = _make_game([("disconnect", None)], tmp_path)
    assert await g._process_hex_turn() == "disconnect"


@pytest.mark.asyncio
async def test_process_hex_turn_unknown_intent_is_ignored(tmp_path) -> None:
    g = _make_game([("quaff", None)], tmp_path)
    origin = g.hex_player_position
    outcome = await g._process_hex_turn()
    assert outcome == "ignored"
    assert g.hex_player_position == origin


# ---------------------------------------------------------------------------
# _get_classic_actions accepts hex_exit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_classic_actions_hex_exit_returns_to_overland(tmp_path) -> None:
    g = _make_game([("hex_exit", None)], tmp_path)
    # Fake "in dungeon" state: set a level.
    coord = g.hex_player_position
    g.hex_world.cells[coord].feature = HexFeatureType.CAVE
    g.hex_world.cells[coord].dungeon = DungeonRef(
        template="procedural:cave", depth=1,
    )
    await g.enter_hex_feature()
    assert g.level is not None
    actions = await g._get_classic_actions()
    # hex_exit dispatches the exit inline and returns [].
    assert actions == []
    assert g.level is None


# ---------------------------------------------------------------------------
# /api/game/new accepts world parameter
# ---------------------------------------------------------------------------


def _client(tmp_path):
    config = WebConfig(max_sessions=4, data_dir=tmp_path)
    app = create_app(config)
    app.config["TESTING"] = True
    return app.test_client(), app


def test_game_new_defaults_to_dungeon(tmp_path) -> None:
    c, _ = _client(tmp_path)
    resp = c.post("/api/game/new", json={})
    assert resp.status_code == 201
    # Dungeon mode path does not include "hex_world"; response shape
    # unchanged from pre-hex release.
    body = resp.get_json()
    assert "session_id" in body


def test_game_new_accepts_hex_easy(tmp_path) -> None:
    c, _ = _client(tmp_path)
    resp = c.post("/api/game/new", json={"world": "hex-easy"})
    assert resp.status_code == 201


def test_game_new_accepts_hex_survival(tmp_path) -> None:
    c, _ = _client(tmp_path)
    resp = c.post("/api/game/new", json={"world": "hex-survival"})
    assert resp.status_code == 201


def test_game_new_rejects_unknown_world(tmp_path) -> None:
    c, _ = _client(tmp_path)
    resp = c.post("/api/game/new", json={"world": "atlantis"})
    assert resp.status_code == 400
    assert "unknown" in resp.get_json()["error"].lower()
