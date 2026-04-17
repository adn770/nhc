"""Roguelike fog of war: visible / revealed semantics on HexWorld.

Two concepts:

* ``revealed`` -- accumulated set of coords the player has seen at
  some point. Never shrinks. Used by the renderer to show explored
  hexes through the fog overlay.
* ``visible_cells(center)`` -- the single hex currently occupied by
  the player. With 5-mile hexes there is no extended field of view.

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
# visible_cells(center) -- single hex, no FOV ring
# ---------------------------------------------------------------------------


def test_visible_cells_returns_only_center() -> None:
    w = _make_greenlands()
    c = HexCoord(4, 4)
    vis = w.visible_cells(c)
    assert vis == {c}


def test_visible_cells_empty_for_out_of_bounds() -> None:
    w = _make_greenlands()
    vis = w.visible_cells(HexCoord(99, 99))
    assert vis == set()


def test_visible_cells_independent_of_revealed_state() -> None:
    w = _make_greenlands()
    w.revealed.clear()
    vis = w.visible_cells(HexCoord(4, 4))
    assert vis == {HexCoord(4, 4)}


# ---------------------------------------------------------------------------
# get_visible(coord) -- fog-respecting cell lookup
# ---------------------------------------------------------------------------


def test_get_visible_returns_cell_when_revealed() -> None:
    w = _make_greenlands()
    cell = w.get_visible(HexCoord(4, 4))
    assert cell is not None
    assert cell.biome is Biome.GREENLANDS


def test_get_visible_returns_none_for_unrevealed() -> None:
    w = _make_greenlands()
    assert w.get_visible(HexCoord(7, 7)) is None


def test_get_visible_returns_none_for_out_of_bounds() -> None:
    w = _make_greenlands()
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
    c = HexCoord(2, 2)
    w.visit(c)
    assert c in w.visited
    assert c in w.revealed


@pytest.mark.asyncio
async def test_fog_reveals_only_stepped_hex() -> None:
    """With 5-mile hexes there is no extended FOV: only the hex the
    player steps onto is revealed, not its neighbours."""
    w = _make_greenlands()
    target = HexCoord(5, 4)
    action = MoveHexAction(
        actor=1, origin=HexCoord(4, 4), target=target, hex_world=w,
    )
    await action.execute(world=World(), level=None)
    assert target in w.revealed
    # Neighbours of target are NOT revealed (only the stepped hex).
    for n in neighbors(target):
        if n == HexCoord(4, 4):
            continue  # origin was already revealed
        assert n not in w.revealed
