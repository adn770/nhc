"""Integration tests for flower generation and serialization.

Milestone M8: _gen_flowers wired into generator, save round-trip.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from nhc.hexcrawl.coords import HexCoord, distance
from nhc.hexcrawl.generator import generate_test_world
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
    TimeOfDay,
    FLOWER_COORDS,
)
from nhc.hexcrawl.pack import load_pack
from nhc.hexcrawl._flowers import generate_flower
from nhc.core.save import (
    SCHEMA_VERSION,
    _serialize_hex_world,
    _deserialize_hex_world,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PACK_BODY = textwrap.dedent(
    """
    id: testland
    version: 1
    attribution: "NHC test setting"
    map:
      generator: bsp_regions
      width: 8
      height: 8
      num_regions: 5
      region_min: 6
      region_max: 16
    features:
      hub: 1
      village:
        min: 1
        max: 2
      dungeon:
        min: 2
        max: 3
      wonder:
        min: 1
        max: 1
    rivers:
      max_rivers: 2
      min_length: 3
    paths:
      connect_towers: 0.5
      connect_caves: 0.2
    """,
)


def _load_pack(tmp_path: Path) -> "PackMeta":
    pack_file = tmp_path / "pack.yaml"
    pack_file.write_text(_PACK_BODY)
    return load_pack(pack_file)


# ---------------------------------------------------------------------------
# generate_flower unit test
# ---------------------------------------------------------------------------


def test_generate_flower_produces_19_cells() -> None:
    """generate_flower on a single cell produces a valid flower."""
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.CAVE,
        elevation=0.5,
        edges=[EdgeSegment(type="river", entry_edge=0, exit_edge=3)],
    )
    cells = {parent.coord: parent}
    flower = generate_flower(parent, cells, seed=42)
    assert len(flower.cells) == 19
    assert flower.parent_coord == parent.coord


def test_generate_flower_rivers_create_edge_segments() -> None:
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.CAVE,
        elevation=0.5,
        edges=[EdgeSegment(type="river", entry_edge=0, exit_edge=3)],
    )
    cells = {parent.coord: parent}
    flower = generate_flower(parent, cells, seed=42)
    river_segs = [e for e in flower.edges if e.type == "river"]
    assert len(river_segs) == 1
    assert river_segs[0].entry_macro_edge == 0
    assert river_segs[0].exit_macro_edge == 3


def test_generate_flower_paths_create_edge_segments() -> None:
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.VILLAGE,
        elevation=0.3,
        edges=[EdgeSegment(type="path", entry_edge=1, exit_edge=4)],
    )
    cells = {parent.coord: parent}
    flower = generate_flower(parent, cells, seed=42)
    road_segs = [e for e in flower.edges if e.type == "path"]
    assert len(road_segs) == 1
    assert road_segs[0].entry_macro_edge == 1
    assert road_segs[0].exit_macro_edge == 4


def test_generate_flower_has_feature_cell_when_feature() -> None:
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.CAVE,
        elevation=0.5,
    )
    cells = {parent.coord: parent}
    flower = generate_flower(parent, cells, seed=42)
    assert flower.feature_cell is not None
    fc = flower.feature_cell
    assert flower.cells[fc].major_feature is HexFeatureType.CAVE


def test_generate_flower_no_feature_cell_when_none() -> None:
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.NONE,
        elevation=0.3,
    )
    cells = {parent.coord: parent}
    flower = generate_flower(parent, cells, seed=42)
    assert flower.feature_cell is None


def test_generate_flower_fast_travel_costs() -> None:
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.NONE,
        elevation=0.3,
    )
    cells = {parent.coord: parent}
    flower = generate_flower(parent, cells, seed=42)
    assert len(flower.fast_travel_costs) == 30


def test_generate_flower_deterministic() -> None:
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.CAVE,
        elevation=0.5,
        edges=[EdgeSegment(type="river", entry_edge=0, exit_edge=3)],
    )
    cells = {parent.coord: parent}
    f1 = generate_flower(parent, cells, seed=42)
    f2 = generate_flower(parent, cells, seed=42)
    assert list(f1.cells.keys()) == list(f2.cells.keys())
    assert f1.feature_cell == f2.feature_cell
    assert f1.fast_travel_costs == f2.fast_travel_costs


# ---------------------------------------------------------------------------
# Generator integration (generate_test_world)
# ---------------------------------------------------------------------------


def test_generator_produces_flowers_on_every_hex(tmp_path) -> None:
    pack = _load_pack(tmp_path)
    world = generate_test_world(12345, pack)
    for coord, cell in world.cells.items():
        assert cell.flower is not None, (
            f"hex ({coord.q}, {coord.r}) has no flower"
        )
        assert len(cell.flower.cells) == 19


def test_generator_river_hexes_have_sub_hex_segments(tmp_path) -> None:
    pack = _load_pack(tmp_path)
    world = generate_test_world(12345, pack)
    river_cells = [
        cell for cell in world.cells.values()
        if any(e.type == "river" for e in cell.edges)
    ]
    assert len(river_cells) > 0, "expected at least one river hex"
    for cell in river_cells:
        river_segs = [
            e for e in cell.flower.edges if e.type == "river"
        ]
        assert len(river_segs) > 0, (
            f"hex ({cell.coord.q}, {cell.coord.r}) has macro river "
            f"edges but no sub-hex river segments"
        )


def test_generator_path_hexes_have_sub_hex_segments(tmp_path) -> None:
    pack = _load_pack(tmp_path)
    world = generate_test_world(12345, pack)
    path_cells = [
        cell for cell in world.cells.values()
        if any(e.type == "path" for e in cell.edges)
    ]
    assert len(path_cells) > 0, "expected at least one path hex"
    for cell in path_cells:
        road_segs = [
            e for e in cell.flower.edges if e.type == "path"
        ]
        assert len(road_segs) > 0, (
            f"hex ({cell.coord.q}, {cell.coord.r}) has macro path "
            f"edges but no sub-hex road segments"
        )


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_schema_version_is_three() -> None:
    assert SCHEMA_VERSION == 3


def test_flower_survives_round_trip() -> None:
    """Serialize then deserialize a HexWorld with flowers."""
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    hw.hour = 14
    hw.minute = 30
    cell = HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.FOREST,
        feature=HexFeatureType.CAVE,
    )
    # Build a minimal flower
    flower_cells = {
        c: SubHexCell(
            coord=c,
            biome=Biome.FOREST,
            move_cost_hours=1.5,
        )
        for c in FLOWER_COORDS
    }
    flower_cells[HexCoord(0, 0)].major_feature = HexFeatureType.CAVE
    flower_cells[HexCoord(1, -1)].minor_feature = MinorFeatureType.CAIRN
    flower_cells[HexCoord(0, -1)].has_river = True
    flower_cells[HexCoord(1, 0)].has_road = True
    flower_cells[HexCoord(1, 0)].move_cost_hours = 0.75
    seg = SubHexEdgeSegment(
        type="river",
        path=[HexCoord(0, -2), HexCoord(0, -1), HexCoord(0, 0)],
        entry_macro_edge=0,
        exit_macro_edge=None,
    )
    flower = HexFlower(
        parent_coord=cell.coord,
        cells=flower_cells,
        edges=[seg],
        feature_cell=HexCoord(0, 0),
        fast_travel_costs={(0, 3): 5.0, (1, 4): 3.5},
    )
    cell.flower = flower
    hw.set_cell(cell)

    data = _serialize_hex_world(hw)
    hw2 = _deserialize_hex_world(data)

    assert hw2.hour == 14
    assert hw2.minute == 30
    cell2 = hw2.get_cell(HexCoord(0, 0))
    assert cell2.flower is not None
    f2 = cell2.flower
    assert len(f2.cells) == 19
    assert f2.feature_cell == HexCoord(0, 0)
    assert f2.cells[HexCoord(0, 0)].major_feature is HexFeatureType.CAVE
    assert f2.cells[HexCoord(1, -1)].minor_feature is MinorFeatureType.CAIRN
    assert f2.cells[HexCoord(0, -1)].has_river is True
    assert f2.cells[HexCoord(1, 0)].has_road is True
    assert f2.cells[HexCoord(1, 0)].move_cost_hours == 0.75
    assert len(f2.edges) == 1
    assert f2.edges[0].type == "river"
    assert f2.edges[0].path == [
        HexCoord(0, -2), HexCoord(0, -1), HexCoord(0, 0),
    ]
    assert f2.fast_travel_costs[(0, 3)] == 5.0
    assert f2.fast_travel_costs[(1, 4)] == 3.5
