"""Tests for entry edge memory.

Milestone W5: last_entry_edge recorded, flower entered from
correct edge.
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexWorld,
    EDGE_TO_RING2,
)
from nhc.hexcrawl._flowers import generate_flower


def _make_world_with_flowers() -> HexWorld:
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    for q in range(4):
        for r in range(4):
            cell = HexCell(
                coord=HexCoord(q, r), biome=Biome.GREENLANDS,
                elevation=0.3,
            )
            cell.flower = generate_flower(
                cell, {HexCoord(q, r): cell}, seed=42 + q * 100 + r,
            )
            hw.set_cell(cell)
    return hw


def test_last_entry_edge_default_empty() -> None:
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    assert hw.last_entry_edge == {}


def test_record_entry_edge_on_move() -> None:
    hw = _make_world_with_flowers()
    origin = HexCoord(1, 1)
    target = HexCoord(1, 0)  # North of origin
    hw.record_entry_edge(origin, target)
    # Entry edge for target: direction from origin to target = N (0)
    # But we store the edge the player entered FROM, which is the
    # direction from target back to origin = S (3)... no, we store
    # the direction of travel.
    # direction_index(origin, target) = index of (0, -1) = 0 (N)
    assert target in hw.last_entry_edge
    assert hw.last_entry_edge[target] == 0  # entered heading N


def test_entry_edge_used_for_flower_entry() -> None:
    hw = _make_world_with_flowers()
    origin = HexCoord(1, 1)
    target = HexCoord(1, 0)  # heading N
    hw.record_entry_edge(origin, target)
    # When entering the flower, the entry sub-hex should be
    # on the edge the player came from (south edge, index 3,
    # since they entered heading north = came from south).
    from nhc.hexcrawl._flowers import entry_sub_hex_for_edge
    sub = entry_sub_hex_for_edge(hw.last_entry_edge[target])
    # The sub should be in ring-2 on the opposite edge (south)
    # because the player approached from the south.
    # Direction 0 (N) means they came from the south side
    # → entry sub-hex should be on edge (0+3)%6 = 3 (south)
    opposite = (0 + 3) % 6
    assert sub in set(EDGE_TO_RING2[opposite])


def test_entry_defaults_to_center_without_record() -> None:
    from nhc.hexcrawl._flowers import entry_sub_hex_for_edge
    # No edge recorded → default to center
    sub = entry_sub_hex_for_edge(None)
    assert sub == HexCoord(0, 0)
