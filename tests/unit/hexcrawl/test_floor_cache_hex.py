"""Tests for Game._floor_cache keying under dungeon vs. hex mode.

In pure dungeon mode the cache is keyed by integer depth. In hex
mode it is keyed by ``(q, r, depth)`` so revisiting a different
hex's procedural cave at the same depth does not collide with a
previously cached one.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.i18n import init as i18n_init


class _FakeClient:
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


def _make_game(world_mode: GameMode, tmp_path) -> Game:
    return Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=world_mode,
        save_dir=tmp_path,
        seed=42,
    )


# ---------------------------------------------------------------------------
# Classic dungeon mode keeps integer keys
# ---------------------------------------------------------------------------


def test_cache_key_dungeon_mode_returns_depth(tmp_path) -> None:
    g = _make_game(GameMode.DUNGEON, tmp_path)
    assert g._cache_key(1) == 1
    assert g._cache_key(5) == 5


def test_floor_cache_classic_accepts_int_key(tmp_path) -> None:
    g = _make_game(GameMode.DUNGEON, tmp_path)
    key = g._cache_key(3)
    g._floor_cache[key] = ("level_sentinel", {"entities": "data"})
    assert g._floor_cache[3] == ("level_sentinel", {"entities": "data"})


# ---------------------------------------------------------------------------
# Hex mode keys by (q, r, depth)
# ---------------------------------------------------------------------------


def test_cache_key_hex_mode_with_position_returns_tuple(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    g.initialize()
    q, r = g.hex_player_position.q, g.hex_player_position.r
    assert g._cache_key(1) == (q, r, 1)
    assert g._cache_key(3) == (q, r, 3)


def test_cache_key_hex_mode_without_position_returns_depth(tmp_path) -> None:
    # Edge case: hex-mode Game constructed but initialize() not
    # called. hex_player_position is None; the helper degrades to
    # the integer-depth key so code that runs before init (e.g.
    # tests) doesn't blow up.
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    assert g.hex_player_position is None
    assert g._cache_key(2) == 2


def test_cache_key_different_hexes_different_keys(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    g.initialize()
    # Simulate the player at three distinct hexes. Use coords that
    # won't collide with each other regardless of where the hub
    # lands for this seed.
    g.hex_player_position = HexCoord(1, 1)
    first = g._cache_key(1)
    g.hex_player_position = HexCoord(2, 2)
    second = g._cache_key(1)
    g.hex_player_position = HexCoord(5, 3)
    third = g._cache_key(1)
    assert first != second
    assert second != third
    assert first != third


def test_floor_cache_hex_round_trip(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    g.initialize()
    g.hex_player_position = HexCoord(4, 2)
    key = g._cache_key(1)
    assert key == (4, 2, 1)
    payload = ("level_obj", {"ent": "payload"})
    g._floor_cache[key] = payload
    # Reload lookup with the same coord+depth yields the same payload.
    g.hex_player_position = HexCoord(4, 2)
    assert g._floor_cache[g._cache_key(1)] == payload


def test_floor_cache_independent_per_hex(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    g.initialize()
    g.hex_player_position = HexCoord(1, 1)
    g._floor_cache[g._cache_key(1)] = "hex_a_depth_1"
    g._floor_cache[g._cache_key(2)] = "hex_a_depth_2"
    g.hex_player_position = HexCoord(3, 3)
    g._floor_cache[g._cache_key(1)] = "hex_b_depth_1"
    # Same depth, different hex -> different cache slots.
    assert g._floor_cache[(1, 1, 1)] == "hex_a_depth_1"
    assert g._floor_cache[(1, 1, 2)] == "hex_a_depth_2"
    assert g._floor_cache[(3, 3, 1)] == "hex_b_depth_1"
