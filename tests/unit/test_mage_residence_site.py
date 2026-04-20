"""Mage residence assembler tests (M19).

See ``design/building_interiors.md``. The mage residence draws
from the ``mage_residence`` archetype (enriched SectorPartitioner)
on an octagon or circle footprint. Regular towers stay on
circle / octagon / square with the simple sector / divided
partitioners.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import CircleShape, OctagonShape
from nhc.dungeon.site import Site
from nhc.dungeon.sites.mage_residence import assemble_mage_residence
from nhc.dungeon.sites.tower import assemble_tower


class TestMageResidenceBasics:
    def test_returns_site_with_one_building(self):
        site = assemble_mage_residence(
            "m1", random.Random(1),
        )
        assert isinstance(site, Site)
        assert site.kind == "mage_residence"
        assert len(site.buildings) == 1

    def test_shape_is_octagon_or_circle(self):
        for seed in range(30):
            site = assemble_mage_residence(
                "m1", random.Random(seed),
            )
            shape = site.buildings[0].base_shape
            assert isinstance(shape, (CircleShape, OctagonShape))

    def test_interior_wall_material_is_stone(self):
        site = assemble_mage_residence("m1", random.Random(1))
        assert site.buildings[0].interior_wall_material == "stone"

    def test_main_sector_rotates_across_floors(self):
        """Enriched SectorPartitioner tags exactly one room per
        floor as ``"main"``; the index rotates with floor."""
        for seed in range(30):
            site = assemble_mage_residence(
                "m1", random.Random(seed),
            )
            b = site.buildings[0]
            if len(b.floors) < 2:
                continue
            mains: list[int] = []
            for floor in b.floors:
                for i, room in enumerate(floor.rooms):
                    if "main" in room.tags:
                        mains.append(i)
                        break
            if len(mains) >= 2 and len(set(mains)) >= 2:
                return
        # Every seed we tried produced a single floor or identical
        # mains — unlikely; the assertion fails loud if it happens.
        raise AssertionError(
            "no mage-residence seed produced a rotating main sector"
        )


class TestTowerStaysSimple:
    def test_tower_never_tags_main_sector(self):
        """Regular towers use simple (not enriched) sector mode —
        no ``"main"`` tag lands on any room."""
        for seed in range(20):
            site = assemble_tower("t1", random.Random(seed))
            for floor in site.buildings[0].floors:
                for room in floor.rooms:
                    assert "main" not in room.tags
