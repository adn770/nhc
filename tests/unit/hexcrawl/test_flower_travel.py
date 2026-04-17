"""Tests for sub-hex travel system.

Milestone M9: direction-dependent fast-travel, flower entry/exit,
MoveSubHexAction, sub-hex encounter rates.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.ecs import World
from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
    HexFlower,
    HexWorld,
    MinorFeatureType,
    SubHexCell,
    TimeOfDay,
    EDGE_TO_RING2,
    FLOWER_COORDS,
)
from nhc.hexcrawl._flowers import generate_flower
from nhc.core.actions._sub_hex_movement import MoveSubHexAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world_with_flower() -> tuple[HexWorld, HexCoord]:
    """Build a small world with one hex that has a flower."""
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    for q in range(4):
        for r in range(4):
            cell = HexCell(
                coord=HexCoord(q, r),
                biome=Biome.GREENLANDS,
                elevation=0.3,
            )
            cells_dict = {HexCoord(q, r): cell}
            cell.flower = generate_flower(cell, cells_dict, seed=42 + q * 100 + r)
            hw.set_cell(cell)
    target = HexCoord(2, 2)
    return hw, target


def _make_ecs_world() -> tuple[World, int]:
    """Create an ECS world with a player entity."""
    w = World()
    pid = w.create_entity({})
    return w, pid


# ---------------------------------------------------------------------------
# HexWorld exploration state fields
# ---------------------------------------------------------------------------


def test_hexworld_exploring_hex_default_none() -> None:
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    assert hw.exploring_hex is None
    assert hw.exploring_sub_hex is None


def test_hexworld_sub_hex_revealed_default_empty() -> None:
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    assert hw.sub_hex_revealed == {}
    assert hw.sub_hex_visited == {}


def test_hexworld_enter_flower() -> None:
    hw, target = _make_world_with_flower()
    entry_sub = list(EDGE_TO_RING2[0])[0]
    hw.enter_flower(target, entry_sub)
    assert hw.exploring_hex == target
    assert hw.exploring_sub_hex == entry_sub
    assert entry_sub in hw.sub_hex_revealed.get(target, set())


def test_hexworld_exit_flower() -> None:
    hw, target = _make_world_with_flower()
    entry_sub = list(EDGE_TO_RING2[0])[0]
    hw.enter_flower(target, entry_sub)
    hw.exit_flower()
    assert hw.exploring_hex is None
    assert hw.exploring_sub_hex is None


def test_hexworld_flower_fov_ring1() -> None:
    """Entering a flower reveals current + 6 neighbors."""
    hw, target = _make_world_with_flower()
    entry_sub = HexCoord(0, 0)  # center
    hw.enter_flower(target, entry_sub)
    revealed = hw.sub_hex_revealed[target]
    # Center + 6 neighbors = 7 revealed
    expected = {entry_sub} | {
        n for n in neighbors(entry_sub) if n in FLOWER_COORDS
    }
    assert revealed == expected


# ---------------------------------------------------------------------------
# MoveSubHexAction — validation
# ---------------------------------------------------------------------------


def test_move_sub_hex_validates_adjacency() -> None:
    hw, target = _make_world_with_flower()
    hw.enter_flower(target, HexCoord(0, 0))
    ecs, pid = _make_ecs_world()
    # Adjacent move: (0,0) → (0,-1) should be valid
    action = MoveSubHexAction(
        actor=pid, origin=HexCoord(0, 0),
        target=HexCoord(0, -1), hex_world=hw,
    )
    assert action.validate_sync()


def test_move_sub_hex_rejects_non_adjacent() -> None:
    hw, target = _make_world_with_flower()
    hw.enter_flower(target, HexCoord(0, 0))
    ecs, pid = _make_ecs_world()
    action = MoveSubHexAction(
        actor=pid, origin=HexCoord(0, 0),
        target=HexCoord(0, -2), hex_world=hw,
    )
    assert not action.validate_sync()


def test_move_sub_hex_rejects_outside_flower() -> None:
    hw, target = _make_world_with_flower()
    hw.enter_flower(target, HexCoord(0, -2))
    ecs, pid = _make_ecs_world()
    # (0,-3) is outside FLOWER_COORDS
    action = MoveSubHexAction(
        actor=pid, origin=HexCoord(0, -2),
        target=HexCoord(0, -3), hex_world=hw,
    )
    assert not action.validate_sync()


# ---------------------------------------------------------------------------
# MoveSubHexAction — execution
# ---------------------------------------------------------------------------


def test_move_sub_hex_advances_clock() -> None:
    hw, target = _make_world_with_flower()
    hw.enter_flower(target, HexCoord(0, 0))
    ecs, pid = _make_ecs_world()
    old_hour = hw.hour
    action = MoveSubHexAction(
        actor=pid, origin=HexCoord(0, 0),
        target=HexCoord(0, -1), hex_world=hw,
    )
    action.execute_sync()
    # Greenlands sub-hex costs 1.0 hours
    assert hw.hour == old_hour + 1 or (
        hw.hour == (old_hour + 1) % 24
    )


def test_move_sub_hex_updates_position() -> None:
    hw, target = _make_world_with_flower()
    hw.enter_flower(target, HexCoord(0, 0))
    ecs, pid = _make_ecs_world()
    action = MoveSubHexAction(
        actor=pid, origin=HexCoord(0, 0),
        target=HexCoord(0, -1), hex_world=hw,
    )
    action.execute_sync()
    assert hw.exploring_sub_hex == HexCoord(0, -1)


def test_move_sub_hex_reveals_fov() -> None:
    hw, target = _make_world_with_flower()
    hw.enter_flower(target, HexCoord(0, 0))
    ecs, pid = _make_ecs_world()
    action = MoveSubHexAction(
        actor=pid, origin=HexCoord(0, 0),
        target=HexCoord(0, -1), hex_world=hw,
    )
    action.execute_sync()
    revealed = hw.sub_hex_revealed[target]
    # Should include the new position + its ring-1 neighbors
    new_pos = HexCoord(0, -1)
    ring1 = {n for n in neighbors(new_pos) if n in FLOWER_COORDS}
    assert {new_pos} | ring1 <= revealed


def test_move_sub_hex_marks_visited() -> None:
    hw, target = _make_world_with_flower()
    hw.enter_flower(target, HexCoord(0, 0))
    ecs, pid = _make_ecs_world()
    action = MoveSubHexAction(
        actor=pid, origin=HexCoord(0, 0),
        target=HexCoord(0, -1), hex_world=hw,
    )
    action.execute_sync()
    assert HexCoord(0, -1) in hw.sub_hex_visited[target]


# ---------------------------------------------------------------------------
# Direction-dependent fast-travel cost
# ---------------------------------------------------------------------------


def test_fast_travel_uses_flower_costs() -> None:
    """When fast-traveling, cost comes from the flower's
    pre-computed fast_travel_costs dict."""
    hw, _ = _make_world_with_flower()
    cell = hw.get_cell(HexCoord(2, 2))
    assert cell.flower is not None
    # The flower should have 30 pre-computed costs
    assert len(cell.flower.fast_travel_costs) == 30
    # All costs should be > 0
    for pair, cost in cell.flower.fast_travel_costs.items():
        assert cost > 0


# ---------------------------------------------------------------------------
# Edge exit detection
# ---------------------------------------------------------------------------


def test_exit_direction_from_ring2() -> None:
    """Moving outward from a ring-2 sub-hex should indicate
    which macro edge the player is exiting through."""
    from nhc.hexcrawl._flowers import get_exit_edge
    # Standing on a ring-2 sub-hex that's on edge 0 (N),
    # moving N should give exit edge 0.
    for edge, (mid, vertex) in EDGE_TO_RING2.items():
        from nhc.hexcrawl.coords import NEIGHBOR_OFFSETS
        dq, dr = NEIGHBOR_OFFSETS[edge]
        outward_target = HexCoord(vertex.q + dq, vertex.r + dr)
        result = get_exit_edge(vertex, outward_target)
        assert result == edge, (
            f"from {vertex} toward {outward_target}: "
            f"expected edge {edge}, got {result}"
        )


def test_no_exit_for_interior_move() -> None:
    """Moving between interior sub-hexes returns None."""
    from nhc.hexcrawl._flowers import get_exit_edge
    result = get_exit_edge(HexCoord(0, 0), HexCoord(0, -1))
    assert result is None
