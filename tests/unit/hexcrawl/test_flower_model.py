"""Tests for the sub-hex flower data model and coord helpers.

Milestone M1: FLOWER_COORDS, EDGE_TO_RING2, MinorFeatureType,
SubHexCell, SubHexEdgeSegment, HexFlower.
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord, distance, neighbors, ring
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
    HexFlower,
    HexWorld,
    MinorFeatureType,
    SubHexCell,
    SubHexEdgeSegment,
    FLOWER_COORDS,
    EDGE_TO_RING2,
    FLOWER_RADIUS,
)


# ---------------------------------------------------------------------------
# Flower coordinate set
# ---------------------------------------------------------------------------


def test_flower_coords_has_19_entries() -> None:
    assert len(FLOWER_COORDS) == 19


def test_flower_coords_ring_distribution() -> None:
    """Ring 0 = 1, ring 1 = 6, ring 2 = 12."""
    center = HexCoord(0, 0)
    by_ring = {0: 0, 1: 0, 2: 0}
    for c in FLOWER_COORDS:
        d = distance(center, c)
        assert d in by_ring, f"unexpected distance {d} for {c}"
        by_ring[d] += 1
    assert by_ring[0] == 1
    assert by_ring[1] == 6
    assert by_ring[2] == 12


def test_flower_coords_is_frozenset() -> None:
    assert isinstance(FLOWER_COORDS, frozenset)


def test_flower_coords_matches_ring_union() -> None:
    """FLOWER_COORDS must equal ring(0) | ring(1) | ring(2)."""
    center = HexCoord(0, 0)
    expected = set(ring(center, 0) + ring(center, 1) + ring(center, 2))
    assert FLOWER_COORDS == expected


def test_flower_radius_is_two() -> None:
    assert FLOWER_RADIUS == 2


# ---------------------------------------------------------------------------
# Edge-to-ring2 mapping
# ---------------------------------------------------------------------------


def test_edge_to_ring2_covers_all_six_edges() -> None:
    assert set(EDGE_TO_RING2.keys()) == {0, 1, 2, 3, 4, 5}


def test_edge_to_ring2_two_hexes_per_edge() -> None:
    for edge, pair in EDGE_TO_RING2.items():
        assert len(pair) == 2, f"edge {edge} has {len(pair)} hexes"


def test_edge_to_ring2_all_at_distance_two() -> None:
    center = HexCoord(0, 0)
    for edge, pair in EDGE_TO_RING2.items():
        for h in pair:
            assert distance(center, h) == 2, (
                f"edge {edge}: {h} not at distance 2"
            )


def test_edge_to_ring2_covers_all_ring2_hexes() -> None:
    """Every ring-2 hex appears in exactly one edge pair."""
    center = HexCoord(0, 0)
    ring2 = set(ring(center, 2))
    mapped = set()
    for pair in EDGE_TO_RING2.values():
        for h in pair:
            assert h not in mapped, f"{h} appears in multiple edges"
            mapped.add(h)
    assert mapped == ring2


def test_edge_to_ring2_entry_faces_outward() -> None:
    """Each entry hex has at least one neighbor outside the flower
    in the direction of its macro edge."""
    from nhc.hexcrawl.coords import NEIGHBOR_OFFSETS
    for edge, pair in EDGE_TO_RING2.items():
        dq, dr = NEIGHBOR_OFFSETS[edge]
        for h in pair:
            outward = HexCoord(h.q + dq, h.r + dr)
            assert outward not in FLOWER_COORDS, (
                f"edge {edge}: {h} outward neighbor {outward} "
                f"is inside the flower"
            )


# ---------------------------------------------------------------------------
# MinorFeatureType enum
# ---------------------------------------------------------------------------


def test_minor_feature_type_has_none() -> None:
    assert MinorFeatureType.NONE.value == "none"


def test_minor_feature_type_civilized_features() -> None:
    civilized = {"farm", "well", "shrine", "signpost",
                 "campsite", "orchard"}
    values = {m.value for m in MinorFeatureType}
    assert civilized <= values


def test_minor_feature_type_wilderness_features() -> None:
    wilderness = {"cairn", "animal_den", "hollow_log",
                  "mushroom_ring", "herb_patch",
                  "bone_pile", "standing_stone"}
    values = {m.value for m in MinorFeatureType}
    assert wilderness <= values


def test_minor_feature_type_encounter_features() -> None:
    encounter = {"lair", "nest", "burrow"}
    values = {m.value for m in MinorFeatureType}
    assert encounter <= values


# ---------------------------------------------------------------------------
# SubHexCell
# ---------------------------------------------------------------------------


def test_sub_hex_cell_defaults() -> None:
    c = SubHexCell(coord=HexCoord(0, 0), biome=Biome.FOREST)
    assert c.elevation == 0.0
    assert c.minor_feature is MinorFeatureType.NONE
    assert c.major_feature is HexFeatureType.NONE
    assert c.has_road is False
    assert c.has_river is False
    assert c.move_cost_hours == 1.0
    assert c.encounter_modifier == 1.0


def test_sub_hex_cell_with_feature() -> None:
    c = SubHexCell(
        coord=HexCoord(1, -1),
        biome=Biome.MOUNTAIN,
        minor_feature=MinorFeatureType.LAIR,
        encounter_modifier=3.0,
    )
    assert c.minor_feature is MinorFeatureType.LAIR
    assert c.encounter_modifier == 3.0


def test_sub_hex_cell_with_major_feature() -> None:
    c = SubHexCell(
        coord=HexCoord(0, 0),
        biome=Biome.GREENLANDS,
        major_feature=HexFeatureType.VILLAGE,
    )
    assert c.major_feature is HexFeatureType.VILLAGE


def test_sub_hex_cell_road_flag() -> None:
    c = SubHexCell(
        coord=HexCoord(1, 0),
        biome=Biome.GREENLANDS,
        has_road=True,
        move_cost_hours=0.5,
    )
    assert c.has_road is True
    assert c.move_cost_hours == 0.5


# ---------------------------------------------------------------------------
# SubHexEdgeSegment
# ---------------------------------------------------------------------------


def test_sub_hex_edge_segment_construction() -> None:
    path = [HexCoord(-1, -1), HexCoord(0, -1), HexCoord(0, 0),
            HexCoord(0, 1), HexCoord(1, 1)]
    seg = SubHexEdgeSegment(
        type="river",
        path=path,
        entry_macro_edge=0,
        exit_macro_edge=3,
    )
    assert seg.type == "river"
    assert len(seg.path) == 5
    assert seg.entry_macro_edge == 0
    assert seg.exit_macro_edge == 3


def test_sub_hex_edge_segment_source_has_none_entry() -> None:
    seg = SubHexEdgeSegment(
        type="river",
        path=[HexCoord(0, -1), HexCoord(0, 0)],
        entry_macro_edge=None,
        exit_macro_edge=3,
    )
    assert seg.entry_macro_edge is None


# ---------------------------------------------------------------------------
# HexFlower
# ---------------------------------------------------------------------------


def test_hex_flower_construction() -> None:
    parent = HexCoord(5, 3)
    cells = {
        c: SubHexCell(coord=c, biome=Biome.FOREST)
        for c in FLOWER_COORDS
    }
    flower = HexFlower(parent_coord=parent, cells=cells)
    assert flower.parent_coord == parent
    assert len(flower.cells) == 19
    assert flower.feature_cell is None
    assert flower.edges == []
    assert flower.fast_travel_costs == {}


def test_hex_flower_with_feature_cell() -> None:
    parent = HexCoord(2, 1)
    cells = {
        c: SubHexCell(coord=c, biome=Biome.GREENLANDS)
        for c in FLOWER_COORDS
    }
    feature_coord = HexCoord(0, -1)
    cells[feature_coord] = SubHexCell(
        coord=feature_coord,
        biome=Biome.GREENLANDS,
        major_feature=HexFeatureType.VILLAGE,
    )
    flower = HexFlower(
        parent_coord=parent,
        cells=cells,
        feature_cell=feature_coord,
    )
    assert flower.feature_cell == feature_coord
    assert flower.cells[feature_coord].major_feature is HexFeatureType.VILLAGE


def test_hex_flower_fast_travel_costs() -> None:
    parent = HexCoord(0, 0)
    cells = {
        c: SubHexCell(coord=c, biome=Biome.GREENLANDS)
        for c in FLOWER_COORDS
    }
    flower = HexFlower(
        parent_coord=parent,
        cells=cells,
        fast_travel_costs={(0, 3): 5.0, (1, 4): 4.5},
    )
    assert flower.fast_travel_costs[(0, 3)] == 5.0
    assert flower.fast_travel_costs[(1, 4)] == 4.5


# ---------------------------------------------------------------------------
# HexCell.flower field
# ---------------------------------------------------------------------------


def test_hex_cell_flower_default_is_none() -> None:
    cell = HexCell(coord=HexCoord(0, 0), biome=Biome.FOREST)
    assert cell.flower is None


def test_hex_cell_stores_flower() -> None:
    flower = HexFlower(
        parent_coord=HexCoord(3, 2),
        cells={
            c: SubHexCell(coord=c, biome=Biome.FOREST)
            for c in FLOWER_COORDS
        },
    )
    cell = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        flower=flower,
    )
    assert cell.flower is flower
    assert len(cell.flower.cells) == 19
