"""Tests for EdgeSegment dataclass, elevation on HexCell, and
rivers/paths on HexWorld.

Covers the data model additions for the rivers-and-paths feature:
- EdgeSegment stores type + entry/exit edge indices
- HexCell carries elevation and edge segments
- HexWorld carries river and path coordinate sequences
- Both generators store elevation per cell
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
    HexWorld,
)


# ---------------------------------------------------------------------------
# EdgeSegment
# ---------------------------------------------------------------------------


def test_edge_segment_river() -> None:
    seg = EdgeSegment(type="river", entry_edge=0, exit_edge=3)
    assert seg.type == "river"
    assert seg.entry_edge == 0
    assert seg.exit_edge == 3


def test_edge_segment_path() -> None:
    seg = EdgeSegment(type="path", entry_edge=1, exit_edge=4)
    assert seg.type == "path"
    assert seg.entry_edge == 1
    assert seg.exit_edge == 4


def test_edge_segment_source_has_none_entry() -> None:
    """River sources originate at the hex center (entry=None)."""
    seg = EdgeSegment(type="river", entry_edge=None, exit_edge=2)
    assert seg.entry_edge is None
    assert seg.exit_edge == 2


def test_edge_segment_sink_has_none_exit() -> None:
    """River sinks terminate at the hex center (exit=None)."""
    seg = EdgeSegment(type="river", entry_edge=5, exit_edge=None)
    assert seg.entry_edge == 5
    assert seg.exit_edge is None


def test_edge_segment_path_endpoint() -> None:
    """Path endpoints at settlements have None for the terminal edge."""
    seg = EdgeSegment(type="path", entry_edge=None, exit_edge=3)
    assert seg.entry_edge is None


# ---------------------------------------------------------------------------
# HexCell elevation + edges
# ---------------------------------------------------------------------------


def test_hexcell_default_elevation_is_zero() -> None:
    c = HexCell(coord=HexCoord(0, 0), biome=Biome.GREENLANDS)
    assert c.elevation == 0.0


def test_hexcell_elevation_set() -> None:
    c = HexCell(
        coord=HexCoord(1, 2),
        biome=Biome.MOUNTAIN,
        elevation=0.75,
    )
    assert c.elevation == 0.75


def test_hexcell_default_edges_empty() -> None:
    c = HexCell(coord=HexCoord(0, 0), biome=Biome.GREENLANDS)
    assert c.edges == []


def test_hexcell_edges_mutable() -> None:
    c = HexCell(coord=HexCoord(0, 0), biome=Biome.GREENLANDS)
    seg = EdgeSegment(type="river", entry_edge=0, exit_edge=3)
    c.edges.append(seg)
    assert len(c.edges) == 1
    assert c.edges[0] is seg


def test_hexcell_multiple_edges() -> None:
    """A hex can have both a river and a path crossing it."""
    c = HexCell(coord=HexCoord(2, 3), biome=Biome.GREENLANDS)
    c.edges.append(EdgeSegment(type="river", entry_edge=0, exit_edge=3))
    c.edges.append(EdgeSegment(type="path", entry_edge=1, exit_edge=4))
    assert len(c.edges) == 2
    types = {seg.type for seg in c.edges}
    assert types == {"river", "path"}


def test_hexcell_edges_default_factory_independent() -> None:
    """Each HexCell gets its own edges list (no shared mutable default)."""
    a = HexCell(coord=HexCoord(0, 0), biome=Biome.GREENLANDS)
    b = HexCell(coord=HexCoord(1, 1), biome=Biome.FOREST)
    a.edges.append(EdgeSegment(type="river", entry_edge=0, exit_edge=3))
    assert b.edges == []


# ---------------------------------------------------------------------------
# HexWorld rivers + paths
# ---------------------------------------------------------------------------


def _make_world() -> HexWorld:
    return HexWorld(pack_id="test", seed=1, width=4, height=4)


def test_hexworld_default_rivers_empty() -> None:
    w = _make_world()
    assert w.rivers == []


def test_hexworld_default_paths_empty() -> None:
    w = _make_world()
    assert w.paths == []


def test_hexworld_rivers_store_coord_sequences() -> None:
    w = _make_world()
    river = [HexCoord(2, 0), HexCoord(2, 1), HexCoord(2, 2)]
    w.rivers.append(river)
    assert len(w.rivers) == 1
    assert w.rivers[0] == river


def test_hexworld_paths_store_coord_sequences() -> None:
    w = _make_world()
    path = [HexCoord(0, 0), HexCoord(1, 0), HexCoord(2, 0)]
    w.paths.append(path)
    assert len(w.paths) == 1
    assert w.paths[0] == path


def test_hexworld_rivers_independent_instances() -> None:
    a = _make_world()
    b = _make_world()
    a.rivers.append([HexCoord(0, 0)])
    assert b.rivers == []


# ---------------------------------------------------------------------------
# Elevation in generators
# ---------------------------------------------------------------------------


@pytest.fixture
def bsp_pack(tmp_path: Path):
    from nhc.hexcrawl.pack import load_pack
    p = tmp_path / "pack.yaml"
    p.write_text(textwrap.dedent("""
        id: testland
        version: 1
        attribution: test
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
            min: 3
            max: 5
          wonder:
            min: 1
            max: 3
    """))
    return load_pack(p)


@pytest.fixture
def perlin_pack(tmp_path: Path):
    from nhc.hexcrawl.pack import load_pack
    p = tmp_path / "pack.yaml"
    p.write_text(textwrap.dedent("""
        id: testland-perlin
        version: 1
        attribution: test
        map:
          generator: perlin_regions
          width: 8
          height: 8
          elevation_scale: 0.08
          moisture_scale: 0.12
          octaves: 4
        features:
          hub: 1
          village:
            min: 1
            max: 2
          dungeon:
            min: 3
            max: 5
          wonder:
            min: 1
            max: 3
    """))
    return load_pack(p)


def test_bsp_cells_have_elevation(bsp_pack) -> None:
    from nhc.hexcrawl.generator import generate_test_world
    w = generate_test_world(seed=42, pack=bsp_pack)
    # Every cell should have a non-default elevation.
    for cell in w.cells.values():
        assert isinstance(cell.elevation, float)
    # At least some variation across the map.
    elevations = {cell.elevation for cell in w.cells.values()}
    assert len(elevations) > 1, "all cells have identical elevation"


def test_bsp_mountain_higher_than_water(bsp_pack) -> None:
    from nhc.hexcrawl.generator import generate_test_world
    w = generate_test_world(seed=42, pack=bsp_pack)
    mountains = [c for c in w.cells.values() if c.biome is Biome.MOUNTAIN]
    greens = [c for c in w.cells.values() if c.biome is Biome.GREENLANDS]
    if mountains and greens:
        avg_mtn = sum(c.elevation for c in mountains) / len(mountains)
        avg_grn = sum(c.elevation for c in greens) / len(greens)
        assert avg_mtn > avg_grn


def test_perlin_cells_have_elevation(perlin_pack) -> None:
    from nhc.hexcrawl.generator import generate_perlin_world
    w = generate_perlin_world(seed=42, pack=perlin_pack)
    for cell in w.cells.values():
        assert isinstance(cell.elevation, float)
    elevations = [cell.elevation for cell in w.cells.values()]
    # Perlin noise should produce a spread of values.
    assert max(elevations) - min(elevations) > 0.3


def test_perlin_elevation_correlates_with_biome(perlin_pack) -> None:
    from nhc.hexcrawl.generator import generate_perlin_world
    w = generate_perlin_world(seed=42, pack=perlin_pack)
    mountains = [c for c in w.cells.values() if c.biome is Biome.MOUNTAIN]
    if mountains:
        avg = sum(c.elevation for c in mountains) / len(mountains)
        assert avg >= 0.65, f"mountain avg elevation {avg} too low"
