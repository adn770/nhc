"""Autosave on every overland hex step.

Game.apply_hex_step validates the target, runs the MoveHexAction,
advances hex_player_position, and writes an autosave. The autosave
round-trips via the pickle+zlib path added in M-1.9.
"""

from __future__ import annotations

import pytest

from nhc.core.autosave import has_autosave, auto_restore
from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.i18n import init as i18n_init


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


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(mode: GameMode, tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=mode,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


# ---------------------------------------------------------------------------
# apply_hex_step: validation, state, autosave
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_hex_step_moves_player(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    origin = g.hex_player_position
    # Pick an in-bounds neighbour.
    target = HexCoord(origin.q + 1, origin.r)
    ok = await g.apply_hex_step(target)
    assert ok
    assert g.hex_player_position == target


@pytest.mark.asyncio
async def test_apply_hex_step_writes_autosave(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    origin = g.hex_player_position
    target = HexCoord(origin.q + 1, origin.r)
    # No autosave before the step (initialize() does not autosave).
    assert not has_autosave(tmp_path)
    ok = await g.apply_hex_step(target)
    assert ok
    assert has_autosave(tmp_path)


@pytest.mark.asyncio
async def test_apply_hex_step_rejects_non_adjacent(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    origin = g.hex_player_position
    # Two steps away.
    target = HexCoord(origin.q + 2, origin.r)
    ok = await g.apply_hex_step(target)
    assert not ok
    assert g.hex_player_position == origin
    # Rejected step must NOT write an autosave.
    assert not has_autosave(tmp_path)


@pytest.mark.asyncio
async def test_apply_hex_step_advances_day_clock(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    day0 = g.hex_world.day
    time0 = g.hex_world.time
    origin = g.hex_player_position
    target = HexCoord(origin.q + 1, origin.r)
    await g.apply_hex_step(target)
    # At least some clock advance happened (exact segments depend
    # on destination biome).
    assert (g.hex_world.day, g.hex_world.time) != (day0, time0)


# ---------------------------------------------------------------------------
# Round-trip: restore from an autosave written by a hex step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autosave_from_hex_step_restores_hex_world(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    target = HexCoord(
        g.hex_player_position.q + 1,
        g.hex_player_position.r,
    )
    await g.apply_hex_step(target)
    assert has_autosave(tmp_path)
    # Rebuild a fresh Game in a fresh dir to simulate a reload.
    g2 = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    assert auto_restore(g2, tmp_path)
    assert g2.world_mode is GameMode.HEX_EASY
    assert g2.hex_world is not None
    assert g2.hex_player_position == target


# ---------------------------------------------------------------------------
# Mode guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_hex_step_rejects_dungeon_mode(tmp_path) -> None:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.DUNGEON,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize(generate=True)
    # Even picking a "plausible" coord should raise, regardless.
    with pytest.raises(RuntimeError):
        await g.apply_hex_step(HexCoord(0, 0))
