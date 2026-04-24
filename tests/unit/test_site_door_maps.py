"""Tests for ``Site.building_doors`` and ``Site.interior_doors``.

Each site assembler populates ``site.building_doors`` with the
surface ``(sx, sy)`` → ``(building_id, bx, by)`` map used by the
engine to swap the active Level when the player crosses a surface
door. The surface door lives one tile outside the building's
footprint; the building-side door lives on the building's
perimeter. Mansions additionally populate ``site.interior_doors``
with the ``(building_id, x, y)`` → ``(sibling_id, mirror_x, y)``
map used for shared-wall crossings between adjacent buildings.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Terrain
from nhc.sites.farm import assemble_farm
from nhc.sites.keep import assemble_keep
from nhc.sites.mansion import assemble_mansion
from nhc.sites.tower import assemble_tower
from nhc.sites.town import assemble_town


def _adjacent(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


class TestTowerDoorMap:
    def test_building_doors_has_one_entry(self):
        for seed in range(20):
            site = assemble_tower("t1", random.Random(seed))
            assert len(site.building_doors) == 1

    def test_building_doors_maps_to_only_building(self):
        site = assemble_tower("t1", random.Random(1))
        building = site.buildings[0]
        ((sx, sy), (bid, bx, by)), = site.building_doors.items()
        assert bid == building.id
        assert _adjacent((sx, sy), (bx, by))
        assert building.ground.tiles[by][bx].feature == "door_closed"

    def test_no_interior_doors(self):
        site = assemble_tower("t1", random.Random(1))
        assert site.interior_doors == {}


class TestFarmDoorMap:
    def test_every_building_has_a_door_entry(self):
        for seed in range(20):
            site = assemble_farm("f1", random.Random(seed))
            ids = {target[0] for target in site.building_doors.values()}
            for b in site.buildings:
                assert b.id in ids

    def test_door_coords_match_building_ground_tiles(self):
        site = assemble_farm("f1", random.Random(1))
        by_id = {b.id: b for b in site.buildings}
        for (sx, sy), (bid, bx, by) in site.building_doors.items():
            assert _adjacent((sx, sy), (bx, by))
            assert (
                by_id[bid].ground.tiles[by][bx].feature == "door_closed"
            )


class TestKeepDoorMap:
    def test_every_building_has_a_door_entry(self):
        site = assemble_keep("k1", random.Random(1))
        ids = {target[0] for target in site.building_doors.values()}
        for b in site.buildings:
            assert b.id in ids

    def test_door_coords_match_building_ground_tiles(self):
        site = assemble_keep("k1", random.Random(1))
        by_id = {b.id: b for b in site.buildings}
        for (sx, sy), (bid, bx, by) in site.building_doors.items():
            assert _adjacent((sx, sy), (bx, by))
            assert (
                by_id[bid].ground.tiles[by][bx].feature == "door_closed"
            )


class TestTownDoorMap:
    def test_every_building_has_a_door_entry(self):
        site = assemble_town("t1", random.Random(1))
        ids = {target[0] for target in site.building_doors.values()}
        for b in site.buildings:
            assert b.id in ids


class TestMansionDoorMap:
    def test_each_building_has_an_entry_door(self):
        site = assemble_mansion("m1", random.Random(1))
        ids = {target[0] for target in site.building_doors.values()}
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


class TestSurfaceDoorPaint:
    """Surface tiles at each building_doors key are walkable with
    a closed-door feature and sit one tile outside the building
    footprint so the player can path to them from the open
    surface without extra connector tiles."""

    def test_keep_surface_door_tiles_are_floor_with_door(self):
        for seed in range(10):
            site = assemble_keep("k1", random.Random(seed))
            for (sx, sy) in site.building_doors.keys():
                tile = site.surface.tiles[sy][sx]
                assert tile.terrain == Terrain.FLOOR
                assert tile.feature == "door_closed"

    def test_town_surface_door_tiles_are_floor_with_door(self):
        for seed in range(10):
            site = assemble_town("t1", random.Random(seed))
            for (sx, sy) in site.building_doors.keys():
                tile = site.surface.tiles[sy][sx]
                assert tile.terrain == Terrain.FLOOR
                assert tile.feature == "door_closed"

    def test_mansion_surface_door_tiles_are_floor_with_door(self):
        for seed in range(10):
            site = assemble_mansion("m1", random.Random(seed))
            for (sx, sy) in site.building_doors.keys():
                if not site.surface.in_bounds(sx, sy):
                    continue
                tile = site.surface.tiles[sy][sx]
                assert tile.terrain == Terrain.FLOOR
                assert tile.feature == "door_closed"

    def test_farm_surface_door_tiles_are_floor_with_door(self):
        for seed in range(10):
            site = assemble_farm("f1", random.Random(seed))
            for (sx, sy) in site.building_doors.keys():
                if not site.surface.in_bounds(sx, sy):
                    continue
                tile = site.surface.tiles[sy][sx]
                assert tile.terrain == Terrain.FLOOR
                assert tile.feature == "door_closed"

    def test_surface_door_is_outside_footprint(self):
        """Surface door coords must not overlap building footprints."""
        site = assemble_keep("k1", random.Random(1))
        by_id = {b.id: b for b in site.buildings}
        for (sx, sy), (bid, _bx, _by) in site.building_doors.items():
            footprint = by_id[bid].base_shape.floor_tiles(
                by_id[bid].base_rect,
            )
            assert (sx, sy) not in footprint
