"""Tests for the mage-variant flavour of the tower assembler.

A tower with ``mage_variant=True`` is always octagonal (mages like
symmetry), and each floor carries a teleporter pair on opposite
walls so stepping onto one pad whisks the player to its sibling.
Pair entries live in ``level.teleporter_pairs`` and are symmetric.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import OctagonShape
from nhc.dungeon.sites.tower import assemble_tower


class TestMageTowerShape:
    def test_mage_variant_forces_octagon(self):
        for seed in range(20):
            site = assemble_tower(
                "t1", random.Random(seed), mage_variant=True,
            )
            assert len(site.buildings) == 1
            building = site.buildings[0]
            assert isinstance(building.base_shape, OctagonShape), (
                f"seed={seed}: expected OctagonShape, "
                f"got {type(building.base_shape).__name__}"
            )

    def test_non_mage_tower_shape_varies(self):
        """Without the flag, the tower rolls between the three
        base shapes as before — the assembler's random pool is
        untouched."""
        shapes: set[type] = set()
        for seed in range(50):
            site = assemble_tower(
                "t1", random.Random(seed), mage_variant=False,
            )
            shapes.add(type(site.buildings[0].base_shape))
        # At least two distinct shapes appear across 50 seeds.
        assert len(shapes) >= 2


class TestMageTowerTeleporters:
    def test_mage_tower_has_pads_on_every_floor(self):
        for seed in range(10):
            site = assemble_tower(
                "t1", random.Random(seed), mage_variant=True,
            )
            building = site.buildings[0]
            for floor in building.floors:
                pad_tiles = [
                    (x, y)
                    for y in range(floor.height)
                    for x in range(floor.width)
                    if floor.tiles[y][x].feature == "teleporter_pad"
                ]
                assert len(pad_tiles) == 2, (
                    f"seed={seed} floor={floor.floor_index}: "
                    f"expected 2 pads, got {len(pad_tiles)}"
                )
                # Pair map is symmetric and covers both pads.
                pairs = floor.teleporter_pairs
                a, b = pad_tiles
                assert pairs.get(a) == b
                assert pairs.get(b) == a

    def test_non_mage_tower_has_no_pads(self):
        for seed in range(10):
            site = assemble_tower(
                "t1", random.Random(seed), mage_variant=False,
            )
            building = site.buildings[0]
            for floor in building.floors:
                pad_count = sum(
                    1
                    for row in floor.tiles
                    for t in row
                    if t.feature == "teleporter_pad"
                )
                assert pad_count == 0
                assert floor.teleporter_pairs == {}


class TestMageTowerPlacement:
    def test_place_dungeons_rolls_some_mage_towers(self):
        """Across many seeds, TOWER placements produce a visible
        share of mage_variant=True to keep the flavour present
        without saturating every tower with teleporters."""
        from nhc.hexcrawl._features import place_dungeons
        from nhc.hexcrawl.coords import HexCoord
        from nhc.hexcrawl.model import (
            Biome, HexCell, HexFeatureType,
        )

        mage_hits = 0
        tower_total = 0
        for seed in range(200):
            cells: dict[HexCoord, HexCell] = {}
            hbb: dict[Biome, list[HexCoord]] = {
                b: [] for b in Biome
            }
            for q in range(6):
                for r in range(6):
                    coord = HexCoord(q, r)
                    # Mountain only → TOWER always eligible,
                    # and CAVE too (MOUNTAIN is CAVE's niche).
                    cells[coord] = HexCell(coord=coord,
                                            biome=Biome.MOUNTAIN)
                    hbb[Biome.MOUNTAIN].append(coord)
            place_dungeons(
                cells, hbb, set(), n=8, rng=random.Random(seed),
            )
            for cell in cells.values():
                if cell.feature is HexFeatureType.TOWER:
                    tower_total += 1
                    if cell.dungeon and cell.dungeon.mage_variant:
                        mage_hits += 1
        assert tower_total > 0
        # Expect a non-trivial fraction but not the majority.
        assert 0 < mage_hits < tower_total
