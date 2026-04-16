"""Tests for MoveHexAction.

Each hex step advances the day clock by the biome cost of the
destination, reveals the destination hex plus its in-bounds
neighbours, marks the destination as visited, and emits a
HexStepEvent carrying the (actor, target) pair.
"""

from __future__ import annotations

import pytest

from nhc.core.actions._hex_movement import MoveHexAction
from nhc.core.ecs import World
from nhc.core.events import HexStepEvent
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexFeatureType,
    HexWorld,
    TimeOfDay,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world_8x8(start: HexCoord = HexCoord(4, 4)) -> HexWorld:
    """4x4 -> 8x8 hex world filled with GREENLANDS by default, start
    hex revealed. Tests override individual cell biomes as needed."""
    w = HexWorld(pack_id="test", seed=1, width=8, height=8)
    for q in range(8):
        for r in range(8):
            w.set_cell(HexCell(coord=HexCoord(q, r), biome=Biome.GREENLANDS))
    w.reveal(start)
    return w


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_hex_to_adjacent_succeeds() -> None:
    w = _make_world_8x8()
    action = MoveHexAction(
        actor=1,
        origin=HexCoord(4, 4),
        target=HexCoord(5, 4),    # SE neighbour
        hex_world=w,
    )
    assert await action.validate(world=World(), level=None)


@pytest.mark.asyncio
async def test_move_hex_to_non_adjacent_rejected() -> None:
    w = _make_world_8x8()
    action = MoveHexAction(
        actor=1,
        origin=HexCoord(4, 4),
        target=HexCoord(6, 4),    # two hexes away
        hex_world=w,
    )
    assert not await action.validate(world=World(), level=None)


@pytest.mark.asyncio
async def test_move_hex_same_hex_rejected() -> None:
    w = _make_world_8x8()
    action = MoveHexAction(
        actor=1,
        origin=HexCoord(4, 4),
        target=HexCoord(4, 4),    # no-move
        hex_world=w,
    )
    assert not await action.validate(world=World(), level=None)


@pytest.mark.asyncio
async def test_move_hex_to_out_of_bounds_rejected() -> None:
    w = _make_world_8x8(start=HexCoord(0, 0))
    action = MoveHexAction(
        actor=1,
        origin=HexCoord(0, 0),
        target=HexCoord(-1, 0),   # off the W edge
        hex_world=w,
    )
    assert not await action.validate(world=World(), level=None)


# ---------------------------------------------------------------------------
# Execute side effects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_hex_advances_clock_by_biome_cost() -> None:
    w = _make_world_8x8()
    # Destination is mountain (4 segments = 1 full day).
    w.cells[HexCoord(5, 4)].biome = Biome.MOUNTAIN
    action = MoveHexAction(
        actor=1, origin=HexCoord(4, 4), target=HexCoord(5, 4),
        hex_world=w,
    )
    await action.execute(world=World(), level=None)
    assert w.day == 2
    assert w.time is TimeOfDay.MORNING


@pytest.mark.asyncio
async def test_move_hex_greenlands_is_one_segment() -> None:
    w = _make_world_8x8()
    action = MoveHexAction(
        actor=1, origin=HexCoord(4, 4), target=HexCoord(5, 4),
        hex_world=w,
    )
    await action.execute(world=World(), level=None)
    assert w.day == 1
    assert w.time is TimeOfDay.MIDDAY


@pytest.mark.asyncio
async def test_move_hex_marks_visited() -> None:
    w = _make_world_8x8()
    target = HexCoord(5, 4)
    action = MoveHexAction(
        actor=1, origin=HexCoord(4, 4), target=target, hex_world=w,
    )
    await action.execute(world=World(), level=None)
    assert target in w.visited
    assert target in w.revealed


@pytest.mark.asyncio
async def test_move_hex_reveals_destination_neighbors() -> None:
    w = _make_world_8x8()
    target = HexCoord(5, 4)
    action = MoveHexAction(
        actor=1, origin=HexCoord(4, 4), target=target, hex_world=w,
    )
    await action.execute(world=World(), level=None)
    expected_reveal = {target} | {
        n for n in neighbors(target)
        if 0 <= n.q < w.width and 0 <= n.r < w.height
    }
    # Origin stays revealed from the initial state too.
    assert expected_reveal <= w.revealed


@pytest.mark.asyncio
async def test_move_hex_edge_reveal_trims_out_of_bounds() -> None:
    # Start at (0,0), move to (1,0). The neighbours of (1,0) that lie
    # outside the 8x8 grid must NOT be added to revealed.
    w = _make_world_8x8(start=HexCoord(0, 0))
    action = MoveHexAction(
        actor=1, origin=HexCoord(0, 0), target=HexCoord(1, 0),
        hex_world=w,
    )
    await action.execute(world=World(), level=None)
    for c in w.revealed:
        assert 0 <= c.q < w.width, c
        assert 0 <= c.r < w.height, c


@pytest.mark.asyncio
async def test_move_hex_emits_event() -> None:
    w = _make_world_8x8()
    target = HexCoord(5, 4)
    action = MoveHexAction(
        actor=7, origin=HexCoord(4, 4), target=target, hex_world=w,
    )
    events = await action.execute(world=World(), level=None)
    step_events = [e for e in events if isinstance(e, HexStepEvent)]
    assert len(step_events) == 1
    assert step_events[0].actor == 7
    assert step_events[0].target == target


@pytest.mark.asyncio
async def test_move_hex_does_not_clear_or_loot() -> None:
    # A plain move must not mutate cleared / looted sets. Those are
    # the domain of EnterHexFeatureAction / Loot actions.
    w = _make_world_8x8()
    action = MoveHexAction(
        actor=1, origin=HexCoord(4, 4), target=HexCoord(5, 4),
        hex_world=w,
    )
    await action.execute(world=World(), level=None)
    assert w.cleared == set()
    assert w.looted == set()
