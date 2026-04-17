"""Tests for Game holding optional HexWorld plus difficulty-mode
start-hex logic.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import HexFeatureType
from nhc.i18n import init as i18n_init


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


class _FakeClient:
    """Permissive GameClient stand-in (same shape as the one in
    test_game_initialize_executor.py)."""

    game_mode = "classic"
    lang = "en"
    edge_doors = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(world_mode: GameMode, seed: int, tmp_path) -> Game:
    return Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=world_mode,
        save_dir=tmp_path,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Dungeon mode is unchanged
# ---------------------------------------------------------------------------


def test_game_dungeon_mode_has_no_hex_world(tmp_path) -> None:
    g = _make_game(GameMode.DUNGEON, seed=42, tmp_path=tmp_path)
    g.initialize(generate=True)
    assert g.world_mode is GameMode.DUNGEON
    assert g.hex_world is None
    assert g.hex_player_position is None
    # And dungeon init still ran.
    assert g.level is not None


def test_game_default_world_mode_is_dungeon(tmp_path) -> None:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        save_dir=tmp_path,
        seed=99,
    )
    assert g.world_mode is GameMode.DUNGEON


# ---------------------------------------------------------------------------
# Hex easy
# ---------------------------------------------------------------------------


def test_game_hex_easy_loads_hex_world(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, seed=42, tmp_path=tmp_path)
    g.initialize()
    assert g.world_mode is GameMode.HEX_EASY
    assert g.hex_world is not None
    from nhc.hexcrawl.generator import expected_shape_cell_count
    assert len(g.hex_world.cells) == expected_shape_cell_count(
        g.hex_world.width, g.hex_world.height,
    )


def test_game_hex_easy_player_starts_adjacent_to_hub(tmp_path) -> None:
    from nhc.hexcrawl.coords import distance
    g = _make_game(GameMode.HEX_EASY, seed=42, tmp_path=tmp_path)
    g.initialize()
    # Player starts adjacent to the hub (distance 1), not on it.
    assert distance(g.hex_player_position, g.hex_world.last_hub) == 1
    # And directly in the flower view
    assert g.hex_world.exploring_hex is not None


def test_game_hex_easy_hub_revealed(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, seed=42, tmp_path=tmp_path)
    g.initialize()
    assert g.hex_world.last_hub in g.hex_world.revealed


def test_game_hex_easy_skips_dungeon_init(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, seed=42, tmp_path=tmp_path)
    g.initialize()
    # No dungeon level; player lives on the overland until they
    # enter a hex feature (M-1.12).
    assert g.level is None


# ---------------------------------------------------------------------------
# Hex survival
# ---------------------------------------------------------------------------


def test_game_hex_survival_loads_hex_world(tmp_path) -> None:
    g = _make_game(GameMode.HEX_SURVIVAL, seed=42, tmp_path=tmp_path)
    g.initialize()
    assert g.world_mode is GameMode.HEX_SURVIVAL
    assert g.hex_world is not None


def test_game_hex_survival_player_starts_at_random_non_feature_hex(tmp_path) -> None:
    g = _make_game(GameMode.HEX_SURVIVAL, seed=42, tmp_path=tmp_path)
    g.initialize()
    pos = g.hex_player_position
    assert pos is not None
    # Not the hub; not on any other feature hex either.
    assert pos != g.hex_world.last_hub
    assert g.hex_world.cells[pos].feature is HexFeatureType.NONE


def test_game_hex_survival_hub_not_revealed(tmp_path) -> None:
    g = _make_game(GameMode.HEX_SURVIVAL, seed=42, tmp_path=tmp_path)
    g.initialize()
    assert g.hex_world.last_hub not in g.hex_world.revealed


def test_game_hex_survival_only_start_hex_revealed(tmp_path) -> None:
    g = _make_game(GameMode.HEX_SURVIVAL, seed=42, tmp_path=tmp_path)
    g.initialize()
    assert g.hex_world.revealed == {g.hex_player_position}


def test_game_hex_survival_seed_reproducibility(tmp_path) -> None:
    a = _make_game(GameMode.HEX_SURVIVAL, seed=42, tmp_path=tmp_path)
    a.initialize()
    b = _make_game(GameMode.HEX_SURVIVAL, seed=42, tmp_path=tmp_path)
    b.initialize()
    assert a.hex_player_position == b.hex_player_position
    assert a.hex_world.last_hub == b.hex_world.last_hub
