"""Roguelike fog of war: visible / revealed semantics on HexWorld.

Two concepts:

* ``revealed`` -- accumulated set of coords the player has seen at
  some point. Never shrinks. Used by the renderer to draw known-
  but-not-currently-visible hexes as dimmed.
* ``visible_cells(center)`` -- the currently-in-sight ring around
  ``center`` (center + in-bounds neighbours). What the renderer
  draws at full brightness.

``get_visible(coord)`` is the fog-respecting cell lookup: returns
the cell if the coord is revealed, else None.
"""

from __future__ import annotations

import pytest

from nhc.core.actions._hex_movement import MoveHexAction
from nhc.core.ecs import World
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexWorld,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_greenlands(start: HexCoord = HexCoord(4, 4)) -> HexWorld:
    w = HexWorld(pack_id="test", seed=1, width=8, height=8)
    for q in range(8):
        for r in range(8):
            w.set_cell(HexCell(coord=HexCoord(q, r), biome=Biome.GREENLANDS))
    w.reveal(start)
    return w


# ---------------------------------------------------------------------------
# visible_cells(center)
# ---------------------------------------------------------------------------


def test_visible_cells_center_plus_neighbors() -> None:
    w = _make_greenlands()
    c = HexCoord(4, 4)
    vis = w.visible_cells(c)
    assert c in vis
    for n in neighbors(c):
        assert n in vis
    assert len(vis) == 7


def test_visible_cells_trims_out_of_bounds() -> None:
    w = _make_greenlands(start=HexCoord(0, 0))
    vis = w.visible_cells(HexCoord(0, 0))
    # All returned coords lie inside the 8x8 grid.
    for c in vis:
        assert 0 <= c.q < 8 and 0 <= c.r < 8
    # The origin corner has 3 in-bounds neighbours (SE, S, NE on
    # flat-top axial with our convention), so 1 + 3 = 4 visible
    # cells at most. Exact neighbour count varies by corner but the
    # upper bound of 7 still holds.
    assert 1 <= len(vis) <= 7


def test_visible_cells_independent_of_revealed_state() -> None:
    # visible_cells asks "what is in sight from here right now" --
    # it does not depend on revealed history. The caller (renderer)
    # intersects with revealed as needed.
    w = _make_greenlands()
    w.revealed.clear()    # unusual but legal
    vis = w.visible_cells(HexCoord(4, 4))
    assert HexCoord(4, 4) in vis
    assert HexCoord(5, 4) in vis


# ---------------------------------------------------------------------------
# get_visible(coord) -- fog-respecting cell lookup
# ---------------------------------------------------------------------------


def test_get_visible_returns_cell_when_revealed() -> None:
    w = _make_greenlands()
    # Start hex is revealed in the fixture.
    cell = w.get_visible(HexCoord(4, 4))
    assert cell is not None
    assert cell.biome is Biome.GREENLANDS


def test_get_visible_returns_none_for_unrevealed() -> None:
    w = _make_greenlands()
    assert w.get_visible(HexCoord(7, 7)) is None


def test_get_visible_returns_none_for_out_of_bounds() -> None:
    w = _make_greenlands()
    # Out-of-bounds coords have no cell and are not in revealed.
    assert w.get_visible(HexCoord(-1, 0)) is None
    assert w.get_visible(HexCoord(99, 99)) is None


# ---------------------------------------------------------------------------
# revealed / visited invariants
# ---------------------------------------------------------------------------


def test_fog_starts_with_only_start_revealed() -> None:
    w = _make_greenlands(start=HexCoord(3, 3))
    assert w.revealed == {HexCoord(3, 3)}


def test_fog_visited_implies_revealed() -> None:
    w = _make_greenlands()
    # visit() on a fresh coord.
    c = HexCoord(2, 2)
    w.visit(c)
    assert c in w.visited
    assert c in w.revealed


@pytest.mark.asyncio
async def test_fog_reveals_neighbors_on_step() -> None:
    w = _make_greenlands()
    target = HexCoord(5, 4)
    # Neighbours of target are not revealed before the move.
    for n in neighbors(target):
        if 0 <= n.q < 8 and 0 <= n.r < 8:
            assert n not in w.revealed or n == HexCoord(4, 4)
    action = MoveHexAction(
        actor=1, origin=HexCoord(4, 4), target=target, hex_world=w,
    )
    await action.execute(world=World(), level=None)
    # After the move, target + in-bounds neighbours of target are
    # revealed.
    assert target in w.revealed
    for n in neighbors(target):
        if 0 <= n.q < 8 and 0 <= n.r < 8:
            assert n in w.revealed
