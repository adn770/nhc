"""Tests for the sub-hex ``has_crossroad`` flag.

After road routing, any sub-hex with 3+ road-carrying neighbours
inside the flower is flagged as a crossroad. The flag feeds the
signpost placement pass so signposts cluster where roads actually
meet.
"""

from __future__ import annotations

from nhc.hexcrawl._flowers import generate_flower
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome, EdgeSegment, HexCell, SubHexCell,
)


def _neutral_cell(coord: HexCoord) -> HexCell:
    return HexCell(coord=coord, biome=Biome.GREENLANDS)


def _minimal_macro(parent: HexCell) -> dict[HexCoord, HexCell]:
    """Return a macro-cell dict populated with the parent plus its
    six neighbours, all GREENLANDS so biome blending stays stable."""
    cells: dict[HexCoord, HexCell] = {parent.coord: parent}
    for nb in neighbors(parent.coord):
        cells[nb] = HexCell(coord=nb, biome=Biome.GREENLANDS)
    return cells


class TestCrossroadDefaultsFalse:
    def test_default_is_false(self):
        sc = SubHexCell(coord=HexCoord(0, 0), biome=Biome.GREENLANDS)
        assert sc.has_crossroad is False


class TestCrossroadDetection:
    def test_hub_with_three_roads_has_crossroad(self):
        """A flower carrying three paths that converge on its
        feature cell flags at least one sub-hex as a crossroad:
        the convergence point gets ≥3 road neighbours inside the
        flower."""
        parent = _neutral_cell(HexCoord(5, 5))
        parent.edges = [
            EdgeSegment(type="path", entry_edge=0, exit_edge=None),
            EdgeSegment(type="path", entry_edge=2, exit_edge=None),
            EdgeSegment(type="path", entry_edge=4, exit_edge=None),
        ]
        flower = generate_flower(parent, _minimal_macro(parent), seed=7)

        crossroads = [
            c for c in flower.cells.values() if c.has_crossroad
        ]
        assert crossroads, (
            "three-road flower produced no crossroad cells"
        )
        for c in crossroads:
            assert c.has_road
            n = sum(
                1 for nb in neighbors(c.coord)
                if nb in flower.cells and flower.cells[nb].has_road
            )
            assert n >= 3

    def test_single_road_has_no_crossroad(self):
        """A lone through-road (one entry, one exit) draws a line;
        no sub-hex picks up three road neighbours so the flag stays
        clear."""
        parent = _neutral_cell(HexCoord(5, 5))
        parent.edges = [
            EdgeSegment(type="path", entry_edge=0, exit_edge=3),
        ]
        flower = generate_flower(parent, _minimal_macro(parent), seed=7)

        crossroads = [
            c for c in flower.cells.values() if c.has_crossroad
        ]
        assert crossroads == []

    def test_crossroad_cells_always_carry_road(self):
        """``has_crossroad`` never fires on a cell without a road."""
        parent = _neutral_cell(HexCoord(5, 5))
        parent.edges = [
            EdgeSegment(type="path", entry_edge=0, exit_edge=None),
            EdgeSegment(type="path", entry_edge=2, exit_edge=None),
            EdgeSegment(type="path", entry_edge=4, exit_edge=None),
        ]
        flower = generate_flower(parent, _minimal_macro(parent), seed=7)

        for c in flower.cells.values():
            if c.has_crossroad:
                assert c.has_road

    def test_no_roads_means_no_crossroads(self):
        """A flower with no road segments at all leaves every
        ``has_crossroad`` flag false."""
        parent = _neutral_cell(HexCoord(5, 5))
        parent.edges = []
        flower = generate_flower(parent, _minimal_macro(parent), seed=7)
        for c in flower.cells.values():
            assert c.has_crossroad is False
