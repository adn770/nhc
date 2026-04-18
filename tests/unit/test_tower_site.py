"""Tests for the tower site assembler (M11).

See design/building_generator.md section 5.1. A tower is one
Building with 2-6 floors sharing a circular, octagonal, or square
base shape. No enclosure; one entry door on the ground-floor
perimeter; wood top floor when the tower has 3+ floors; optional
descent to a subterranean dungeon.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import (
    CircleShape, Level, OctagonShape, RectShape, Terrain,
)
from nhc.dungeon.site import Enclosure, Site
from nhc.dungeon.sites.tower import (
    TOWER_DESCENT_PROBABILITY,
    TOWER_FLOOR_COUNT_RANGE,
    assemble_tower,
)


class TestSiteDataclass:
    def test_basic_construction(self):
        surface = Level.create_empty("s", "S", 0, 5, 5)
        site = Site(
            id="s1", kind="tower", buildings=[], surface=surface,
        )
        assert site.id == "s1"
        assert site.kind == "tower"
        assert site.buildings == []
        assert site.enclosure is None

    def test_enclosure_dataclass(self):
        enc = Enclosure(
            kind="fortification",
            polygon=[(0, 0), (5, 0), (5, 5), (0, 5)],
        )
        assert enc.kind == "fortification"
        assert len(enc.polygon) == 4
        assert enc.gates == []


class TestAssembleTowerBasics:
    def test_returns_site_with_tower_kind(self):
        site = assemble_tower("t1", random.Random(1))
        assert isinstance(site, Site)
        assert site.kind == "tower"

    def test_has_exactly_one_building(self):
        site = assemble_tower("t1", random.Random(1))
        assert len(site.buildings) == 1

    def test_no_enclosure(self):
        site = assemble_tower("t1", random.Random(1))
        assert site.enclosure is None

    def test_building_wall_material_is_brick_or_stone(self):
        site = assemble_tower("t1", random.Random(1))
        assert site.buildings[0].wall_material in ("brick", "stone")


class TestTowerFloorCount:
    def test_floor_count_in_spec_range(self):
        lo, hi = TOWER_FLOOR_COUNT_RANGE
        for seed in range(30):
            site = assemble_tower("t1", random.Random(seed))
            n = len(site.buildings[0].floors)
            assert lo <= n <= hi

    def test_multiple_floor_counts_observed(self):
        counts: set[int] = set()
        for seed in range(60):
            counts.add(
                len(assemble_tower("t1", random.Random(seed))
                    .buildings[0].floors)
            )
        assert len(counts) >= 3


class TestTowerShape:
    def test_shape_in_allowed_pool(self):
        allowed = {"CircleShape", "OctagonShape", "RectShape"}
        for seed in range(30):
            site = assemble_tower("t1", random.Random(seed))
            assert (
                type(site.buildings[0].base_shape).__name__ in allowed
            )

    def test_rect_base_is_square(self):
        """When the base is a RectShape, w == h (doc rule)."""
        for seed in range(80):
            site = assemble_tower("t1", random.Random(seed))
            b = site.buildings[0]
            if isinstance(b.base_shape, RectShape):
                assert b.base_rect.width == b.base_rect.height
                return
        pytest.skip("No RectShape tower in 80 seeds")


class TestTowerFloorGeometry:
    def test_all_floors_have_footprint_floor_tiles(self):
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        footprint = b.base_shape.floor_tiles(b.base_rect)
        for floor in b.floors:
            for (x, y) in footprint:
                assert (
                    floor.tiles[y][x].terrain == Terrain.FLOOR
                ), f"footprint tile ({x},{y}) not FLOOR"

    def test_all_floors_point_to_building(self):
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        for i, floor in enumerate(b.floors):
            assert floor.building_id == b.id
            assert floor.floor_index == i


class TestTowerStairs:
    def test_every_adjacent_pair_is_linked(self):
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        n = len(b.floors)
        internal = {
            (l.from_floor, l.to_floor) for l in b.stair_links
            if isinstance(l.to_floor, int)
        }
        for i in range(n - 1):
            assert (i, i + 1) in internal

    def test_stair_tiles_feature_marked_on_both_floors(self):
        """Tower stairs use dungeon-depth semantics: the lower
        physical floor carries stairs_down (depth increases as you
        climb), so the engine's 'descend' action walks the player
        up the tower."""
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        for link in b.stair_links:
            if not isinstance(link.to_floor, int):
                continue
            lo = b.floors[link.from_floor]
            hi = b.floors[link.to_floor]
            lx, ly = link.from_tile
            ux, uy = link.to_tile
            assert lo.tiles[ly][lx].feature == "stairs_down"
            assert hi.tiles[uy][ux].feature == "stairs_up"

    def test_building_validate_passes(self):
        site = assemble_tower("t1", random.Random(1))
        site.buildings[0].validate()


class TestTowerInteriorFloor:
    def test_tall_tower_has_wood_top_floor(self):
        for seed in range(80):
            site = assemble_tower("t1", random.Random(seed))
            floors = site.buildings[0].floors
            if len(floors) >= 3:
                assert floors[-1].interior_floor == "wood"

    def test_two_floor_tower_all_stone(self):
        for seed in range(200):
            site = assemble_tower("t1", random.Random(seed))
            floors = site.buildings[0].floors
            if len(floors) == 2:
                for f in floors:
                    assert f.interior_floor == "stone"
                return
        pytest.skip("No 2-floor tower generated in 200 seeds")

    def test_lower_floors_of_tall_tower_are_stone(self):
        for seed in range(80):
            site = assemble_tower("t1", random.Random(seed))
            floors = site.buildings[0].floors
            if len(floors) >= 3:
                for f in floors[:-1]:
                    assert f.interior_floor == "stone"


class TestTowerEntryDoor:
    def test_ground_floor_has_at_least_one_door(self):
        site = assemble_tower("t1", random.Random(1))
        ground = site.buildings[0].floors[0]
        doors = [
            (x, y) for y, row in enumerate(ground.tiles)
            for x, t in enumerate(row) if t.feature == "door_closed"
        ]
        assert len(doors) >= 1

    def test_door_lives_on_perimeter(self):
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        perim = b.shared_perimeter()
        ground = b.floors[0]
        for y, row in enumerate(ground.tiles):
            for x, t in enumerate(row):
                if t.feature == "door_closed":
                    assert (x, y) in perim

    def test_upper_floors_have_no_outside_door(self):
        """Only the ground floor has the entry door feature."""
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        for floor in b.floors[1:]:
            for row in floor.tiles:
                for t in row:
                    assert t.feature != "door_closed"


class TestTowerDescent:
    def test_descent_probability_roughly_matches_spec(self):
        count = 0
        trials = 300
        for seed in range(trials):
            site = assemble_tower("t1", random.Random(seed))
            if site.buildings[0].descent is not None:
                count += 1
        ratio = count / trials
        # Spec says ~30%; allow wide tolerance given small sample.
        assert abs(ratio - TOWER_DESCENT_PROBABILITY) < 0.12, (
            f"descent ratio {ratio:.2f} vs "
            f"spec {TOWER_DESCENT_PROBABILITY}"
        )

    def test_descent_produces_descent_stair_link(self):
        """When a tower has a descent, there is exactly one descent
        StairLink pointing at the DungeonRef."""
        from nhc.hexcrawl.model import DungeonRef
        for seed in range(200):
            site = assemble_tower("t1", random.Random(seed))
            b = site.buildings[0]
            if b.descent is None:
                continue
            descent_links = [
                l for l in b.stair_links
                if isinstance(l.to_floor, DungeonRef)
            ]
            assert len(descent_links) == 1
            assert descent_links[0].to_floor is b.descent
            assert descent_links[0].from_floor == 0
            return
        pytest.skip("No descent tower in 200 seeds")


class TestTowerDeterminism:
    def test_same_seed_same_floor_count(self):
        s1 = assemble_tower("t1", random.Random(42))
        s2 = assemble_tower("t1", random.Random(42))
        assert len(s1.buildings[0].floors) == len(
            s2.buildings[0].floors
        )

    def test_same_seed_same_base_shape_class(self):
        s1 = assemble_tower("t1", random.Random(42))
        s2 = assemble_tower("t1", random.Random(42))
        assert (
            type(s1.buildings[0].base_shape)
            is type(s2.buildings[0].base_shape)
        )

    def test_different_seeds_likely_differ(self):
        """Over several seeds, tower shapes or floor counts vary."""
        sigs: set[tuple[str, int]] = set()
        for seed in range(10):
            site = assemble_tower("t1", random.Random(seed))
            b = site.buildings[0]
            sigs.add(
                (type(b.base_shape).__name__, len(b.floors)),
            )
        assert len(sigs) > 1
