"""Tests for the crossroad-signpost placement pass.

After flower assembly flags crossroads, any crossroad sub-hex
with no existing minor feature gets a ``SIGNPOST`` stamped on it
so signposts reliably appear where roads meet. Cells with an
existing minor feature are left alone — a crossroad that already
houses a farm keeps the farm.
"""

from __future__ import annotations

from nhc.hexcrawl._flowers import generate_flower
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome, EdgeSegment, HexCell, MinorFeatureType, SubHexCell,
)


def _neutral_cell(coord: HexCoord) -> HexCell:
    return HexCell(coord=coord, biome=Biome.GREENLANDS)


def _minimal_macro(parent: HexCell) -> dict[HexCoord, HexCell]:
    cells: dict[HexCoord, HexCell] = {parent.coord: parent}
    for nb in neighbors(parent.coord):
        cells[nb] = HexCell(coord=nb, biome=Biome.GREENLANDS)
    return cells


class TestSignpostPromotedOnCrossroads:
    def test_every_crossroad_becomes_a_signpost(self):
        """In a three-road flower, every flagged crossroad cell
        carries a SIGNPOST minor feature after generation."""
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
        assert crossroads
        for c in crossroads:
            assert c.minor_feature is MinorFeatureType.SIGNPOST, (
                f"crossroad at {c.coord} not stamped with SIGNPOST "
                f"(got {c.minor_feature})"
            )

    def test_no_crossroad_no_crossroad_flags(self):
        """Without any road convergence the crossroad flag stays
        false, so the promotion pass is a no-op. Biome-driven
        signpost placement is unaffected and runs earlier."""
        parent = _neutral_cell(HexCoord(5, 5))
        parent.edges = [
            EdgeSegment(type="path", entry_edge=0, exit_edge=3),
        ]
        flower = generate_flower(parent, _minimal_macro(parent), seed=7)
        assert not any(c.has_crossroad for c in flower.cells.values())


class TestCrossroadsOverwriteMinors:
    def test_crossroad_always_gets_signpost(self):
        """Minor placement runs before roads, so a crossroad tile
        may have accidentally picked up a biome-pool minor. The
        helper overwrites that so a signpost is reliably present
        at every junction — lost shrines are the acceptable cost
        of consistent wayfinding."""
        from nhc.hexcrawl._flowers import _stamp_crossroad_signposts

        parent = _neutral_cell(HexCoord(5, 5))
        parent.edges = [
            EdgeSegment(type="path", entry_edge=0, exit_edge=None),
            EdgeSegment(type="path", entry_edge=2, exit_edge=None),
            EdgeSegment(type="path", entry_edge=4, exit_edge=None),
        ]
        flower = generate_flower(parent, _minimal_macro(parent), seed=7)

        # Simulate a pre-claim, then re-run the helper to confirm
        # the overwrite semantics.
        preclaimed = next(
            c for c in flower.cells.values() if c.has_crossroad
        )
        preclaimed.minor_feature = MinorFeatureType.FARM
        _stamp_crossroad_signposts(flower.cells)

        assert preclaimed.minor_feature is MinorFeatureType.SIGNPOST
