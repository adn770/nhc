"""Tests for the mage-variant flavour of the mansion assembler.

A mansion with ``mage_variant=True`` appends one octagonal tower
building to the ordinary 2-4 mansion buildings. The tower has
2-3 floors and each floor carries a teleporter pair, matching the
standalone mage tower. The rest of the mansion is unchanged so
every other mansion test keeps passing.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import OctagonShape
from nhc.dungeon.sites.mansion import assemble_mansion


class TestMageMansionHasAttachedTower:
    def test_mage_mansion_has_extra_octagonal_building(self):
        for seed in range(10):
            plain = assemble_mansion("m1", random.Random(seed))
            mage = assemble_mansion(
                "m1", random.Random(seed), mage_variant=True,
            )
            assert len(mage.buildings) == len(plain.buildings) + 1
            # The extra building is the octagonal tower: it's the
            # only one with OctagonShape.
            octagons = [
                b for b in mage.buildings
                if isinstance(b.base_shape, OctagonShape)
            ]
            assert len(octagons) == 1

    def test_mage_tower_has_pads_on_every_floor(self):
        for seed in range(5):
            site = assemble_mansion(
                "m1", random.Random(seed), mage_variant=True,
            )
            tower = next(
                b for b in site.buildings
                if isinstance(b.base_shape, OctagonShape)
            )
            for floor in tower.floors:
                pad_tiles = [
                    (x, y)
                    for y in range(floor.height)
                    for x in range(floor.width)
                    if floor.tiles[y][x].feature == "teleporter_pad"
                ]
                assert len(pad_tiles) == 2
                a, b = pad_tiles
                assert floor.teleporter_pairs.get(a) == b

    def test_mage_tower_has_its_own_entry_door(self):
        """Player can reach the tower from the mansion surface
        via a distinct building_doors entry keyed to the tower's
        own building id."""
        for seed in range(5):
            site = assemble_mansion(
                "m1", random.Random(seed), mage_variant=True,
            )
            tower = next(
                b for b in site.buildings
                if isinstance(b.base_shape, OctagonShape)
            )
            tower_door_count = sum(
                1
                for (_surface_xy), (bid, _bx, _by)
                in site.building_doors.items()
                if bid == tower.id
            )
            assert tower_door_count >= 1


class TestNonMageMansionUnchanged:
    def test_plain_mansion_has_no_octagon(self):
        for seed in range(10):
            site = assemble_mansion(
                "m1", random.Random(seed), mage_variant=False,
            )
            octagons = [
                b for b in site.buildings
                if isinstance(b.base_shape, OctagonShape)
            ]
            assert octagons == []

    def test_plain_mansion_no_pads(self):
        for seed in range(10):
            site = assemble_mansion(
                "m1", random.Random(seed), mage_variant=False,
            )
            for b in site.buildings:
                for floor in b.floors:
                    pad_count = sum(
                        1
                        for row in floor.tiles
                        for t in row
                        if t.feature == "teleporter_pad"
                    )
                    assert pad_count == 0
                    assert floor.teleporter_pairs == {}
