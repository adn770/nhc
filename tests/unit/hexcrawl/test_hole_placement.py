"""Tests for HexFeatureType.HOLE placement on the macro map.

HOLE already resolves to the bespoke ``cave`` route in
``sub_hex_entry.resolve_sub_hex_entry`` and has end-to-end flower
entry coverage in ``test_sub_hex_entry.py``. What was missing is
placement: ``place_dungeons`` never assigned HOLE to any hex, so
the feature type was effectively dead code on the overland side.

These tests lock in a biome pool and round-robin placement so a
HOLE hex actually appears in a generated world.
"""

from __future__ import annotations

import random

from nhc.hexcrawl._features import (
    FEATURE_BIOMES, place_dungeons,
)
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome, DungeonRef, HexCell, HexFeatureType,
)


def _world() -> tuple[
    dict[HexCoord, HexCell],
    dict[Biome, list[HexCoord]],
]:
    """Small grid with every biome represented."""
    cells: dict[HexCoord, HexCell] = {}
    hbb: dict[Biome, list[HexCoord]] = {b: [] for b in Biome}
    biomes = [
        Biome.GREENLANDS, Biome.HILLS, Biome.FOREST,
        Biome.MOUNTAIN, Biome.SANDLANDS, Biome.DRYLANDS,
        Biome.MARSH, Biome.DEADLANDS, Biome.ICELANDS,
    ]
    for q in range(9):
        for r in range(9):
            coord = HexCoord(q, r)
            biome = biomes[q]
            cells[coord] = HexCell(coord=coord, biome=biome)
            hbb[biome].append(coord)
    return cells, hbb


class TestHoleBiomePool:
    def test_hole_has_a_biome_pool(self):
        assert HexFeatureType.HOLE in FEATURE_BIOMES
        assert FEATURE_BIOMES[HexFeatureType.HOLE]

    def test_hole_does_not_steal_cave_mountain_niche(self):
        """CAVE is the only feature that owns MOUNTAIN as its
        primary pool; HOLE should live in softer biomes so the two
        don't saturate each other's placement pools."""
        assert Biome.MOUNTAIN not in FEATURE_BIOMES[HexFeatureType.HOLE]


class TestHolePlacement:
    def test_place_dungeons_can_stamp_a_hole(self):
        """With a generous budget and every biome in the pool,
        place_dungeons must produce at least one HOLE."""
        cells, hbb = _world()
        taken: set[HexCoord] = set()
        # Big enough to cycle past the "one of each" pass into the
        # round-robin phase.
        place_dungeons(cells, hbb, taken, n=20, rng=random.Random(1))
        holes = [
            c for c in cells.values()
            if c.feature is HexFeatureType.HOLE
        ]
        assert holes, "no HOLE hexes placed in a 20-dungeon world"

    def test_hole_dungeon_ref_uses_cave_template(self):
        cells, hbb = _world()
        taken: set[HexCoord] = set()
        place_dungeons(cells, hbb, taken, n=20, rng=random.Random(1))
        holes = [
            c for c in cells.values()
            if c.feature is HexFeatureType.HOLE
        ]
        assert holes
        for cell in holes:
            ref = cell.dungeon
            assert ref is not None
            assert ref.template == "procedural:cave"
            # No site_kind — HOLE stays on the procedural cave
            # pipeline rather than routing through a site assembler.
            assert ref.site_kind is None

    def test_hole_lands_in_eligible_biome(self):
        cells, hbb = _world()
        taken: set[HexCoord] = set()
        place_dungeons(cells, hbb, taken, n=20, rng=random.Random(1))
        eligible = set(FEATURE_BIOMES[HexFeatureType.HOLE])
        for cell in cells.values():
            if cell.feature is HexFeatureType.HOLE:
                assert cell.biome in eligible, (
                    f"HOLE placed in {cell.biome}, "
                    f"not in pool {eligible}"
                )
