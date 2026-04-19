"""Tests for ``Site.building_doors`` and ``Site.interior_doors``.

Each site assembler populates ``site.building_doors`` with the
``(x, y)`` → ``building_id`` mapping used by the engine to swap
the active Level when the player crosses a perimeter door.
Mansions additionally populate ``site.interior_doors`` with the
``(building_id, x, y)`` → ``(sibling_id, mirror_x, y)`` mapping
used for shared-wall crossings between adjacent buildings.
"""

from __future__ import annotations

import random

from nhc.dungeon.sites.farm import assemble_farm
from nhc.dungeon.sites.keep import assemble_keep
from nhc.dungeon.sites.mansion import assemble_mansion
from nhc.dungeon.sites.tower import assemble_tower
from nhc.dungeon.sites.town import assemble_town


class TestTowerDoorMap:
    def test_building_doors_has_one_entry(self):
        for seed in range(20):
            site = assemble_tower("t1", random.Random(seed))
            assert len(site.building_doors) == 1

    def test_building_doors_maps_to_only_building(self):
        site = assemble_tower("t1", random.Random(1))
        building = site.buildings[0]
        ((x, y), bid), = site.building_doors.items()
        assert bid == building.id
        assert building.ground.tiles[y][x].feature == "door_closed"

    def test_no_interior_doors(self):
        site = assemble_tower("t1", random.Random(1))
        assert site.interior_doors == {}


class TestFarmDoorMap:
    def test_every_building_has_a_door_entry(self):
        for seed in range(20):
            site = assemble_farm("f1", random.Random(seed))
            ids = {bid for bid in site.building_doors.values()}
            for b in site.buildings:
                assert b.id in ids

    def test_door_coords_match_building_ground_tiles(self):
        site = assemble_farm("f1", random.Random(1))
        by_id = {b.id: b for b in site.buildings}
        for (x, y), bid in site.building_doors.items():
            building = by_id[bid]
            assert (
                building.ground.tiles[y][x].feature == "door_closed"
            )


class TestKeepDoorMap:
    def test_every_building_has_a_door_entry(self):
        site = assemble_keep("k1", random.Random(1))
        ids = {bid for bid in site.building_doors.values()}
        for b in site.buildings:
            assert b.id in ids

    def test_door_coords_match_building_ground_tiles(self):
        site = assemble_keep("k1", random.Random(1))
        by_id = {b.id: b for b in site.buildings}
        for (x, y), bid in site.building_doors.items():
            building = by_id[bid]
            assert (
                building.ground.tiles[y][x].feature == "door_closed"
            )


class TestTownDoorMap:
    def test_every_building_has_a_door_entry(self):
        site = assemble_town("t1", random.Random(1))
        ids = {bid for bid in site.building_doors.values()}
        for b in site.buildings:
            assert b.id in ids


class TestMansionDoorMap:
    def test_each_building_has_an_entry_door(self):
        site = assemble_mansion("m1", random.Random(1))
        ids = {bid for bid in site.building_doors.values()}
        for b in site.buildings:
            assert b.id in ids

    def test_interior_doors_are_symmetric(self):
        site = assemble_mansion("m1", random.Random(1))
        for key, target in site.interior_doors.items():
            from_id, fx, fy = key
            to_id, tx, ty = target
            assert (to_id, tx, ty) in site.interior_doors
            assert (
                site.interior_doors[(to_id, tx, ty)]
                == (from_id, fx, fy)
            )

    def test_interior_door_tiles_are_door_closed(self):
        site = assemble_mansion("m1", random.Random(1))
        by_id = {b.id: b for b in site.buildings}
        for key, target in site.interior_doors.items():
            from_id, fx, fy = key
            to_id, tx, ty = target
            assert (
                by_id[from_id].ground.tiles[fy][fx].feature
                == "door_closed"
            )
            assert (
                by_id[to_id].ground.tiles[ty][tx].feature
                == "door_closed"
            )

    def test_adjacent_buildings_are_connected(self):
        """Every adjacent building pair in the mansion row shares
        at least one interior door."""
        site = assemble_mansion("m1", random.Random(1))
        for i in range(len(site.buildings) - 1):
            left = site.buildings[i].id
            right = site.buildings[i + 1].id
            has_link = any(
                key[0] == left and target[0] == right
                for key, target in site.interior_doors.items()
            )
            assert has_link, (
                f"no interior door between {left} and {right}"
            )
