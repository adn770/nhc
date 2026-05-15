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
    CircleShape, Level, OctagonShape, RectShape, SurfaceType, Terrain,
)
from nhc.hexcrawl.model import Biome
from nhc.sites._site import Enclosure, Site
from nhc.sites.tower import (
    TOWER_DESCENT_PROBABILITY,
    TOWER_FLOOR_COUNT_RANGE,
    TOWER_SURFACE_PADDING,
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
    def test_all_footprint_tiles_are_floor_or_interior(self):
        """Every footprint tile is walkable (FLOOR) or blocked by an
        interior wall / door — no VOID gaps inside the footprint."""
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        footprint = b.base_shape.floor_tiles(b.base_rect)
        for floor in b.floors:
            for (x, y) in footprint:
                tile = floor.tiles[y][x]
                assert tile.terrain in (Terrain.FLOOR, Terrain.WALL), (
                    f"footprint tile ({x},{y}) has terrain "
                    f"{tile.terrain}"
                )

    def test_all_floors_point_to_building(self):
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        for i, floor in enumerate(b.floors):
            assert floor.building_id == b.id
            assert floor.floor_index == i

    def test_every_floor_has_at_least_one_room(self):
        """Towers may have multiple rooms per floor after M14
        (sector / divided partitioners)."""
        for seed in range(10):
            site = assemble_tower("t1", random.Random(seed))
            for floor in site.buildings[0].floors:
                assert len(floor.rooms) >= 1

    def test_tower_interior_tag_preserved_on_first_room(self):
        """Site assembler keeps ``tower_interior`` on the first
        partitioner room so downstream consumers still find it."""
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        for i, floor in enumerate(b.floors):
            tags = floor.rooms[0].tags
            assert "tower_interior" in tags
            assert ("entrance" in tags) is (i == 0)


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
        """Tower stairs use physical semantics: the lower floor
        carries stairs_up (``<``) because walking up the stair
        physically reaches the floor above, and the upper floor
        carries stairs_down (``>``). The stair actions handle
        the depth flip internally."""
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        for link in b.stair_links:
            if not isinstance(link.to_floor, int):
                continue
            lo = b.floors[link.from_floor]
            hi = b.floors[link.to_floor]
            lx, ly = link.from_tile
            ux, uy = link.to_tile
            assert lo.tiles[ly][lx].feature == "stairs_up"
            assert hi.tiles[uy][ux].feature == "stairs_down"

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

    def test_entry_door_lives_on_perimeter(self):
        """At least one ground-floor door sits on the building
        perimeter — the surface-side entry. Other doors may be
        interior (partitioner) doors off-perimeter."""
        site = assemble_tower("t1", random.Random(1))
        b = site.buildings[0]
        perim = b.shared_perimeter()
        ground = b.floors[0]
        perim_doors = [
            (x, y) for y, row in enumerate(ground.tiles)
            for x, t in enumerate(row)
            if t.feature == "door_closed" and (x, y) in perim
        ]
        assert len(perim_doors) >= 1


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

    def test_descent_stair_feature_stays_down_after_flip(self):
        """The tower's cross-floor flip must not invert the
        descent stair; cellar entry descends physically, so the
        ground-floor descent tile must remain ``stairs_down``."""
        from nhc.hexcrawl.model import DungeonRef
        for seed in range(200):
            site = assemble_tower("t1", random.Random(seed))
            b = site.buildings[0]
            if b.descent is None:
                continue
            dlink = next(
                l for l in b.stair_links
                if isinstance(l.to_floor, DungeonRef)
            )
            fx, fy = dlink.from_tile
            assert (
                b.ground.tiles[fy][fx].feature == "stairs_down"
            )
            return
        pytest.skip("No descent tower in 200 seeds")


class TestTowerSurfaceSize:
    """Macro surface gives a meaningful buffer around the tower so
    trees and bushes have room to scatter outside the footprint."""

    def test_surface_buffer_matches_padding_on_every_side(self):
        for seed in range(10):
            site = assemble_tower(
                f"t{seed}", random.Random(seed),
            )
            b = site.buildings[0]
            assert b.base_rect.x == TOWER_SURFACE_PADDING
            assert b.base_rect.y == TOWER_SURFACE_PADDING
            right_pad = site.surface.width - (
                b.base_rect.x + b.base_rect.width
            )
            bottom_pad = site.surface.height - (
                b.base_rect.y + b.base_rect.height
            )
            assert right_pad == TOWER_SURFACE_PADDING
            assert bottom_pad == TOWER_SURFACE_PADDING

    def test_surface_has_field_tiles_around_tower(self):
        """The new surface paints GRASS+FIELD around the footprint
        so the renderer has something to draw under the trees."""
        for seed in range(5):
            site = assemble_tower(
                f"t{seed}", random.Random(seed),
            )
            field_count = sum(
                1
                for row in site.surface.tiles
                for tile in row
                if tile.terrain is Terrain.GRASS
                and tile.surface_type is SurfaceType.FIELD
            )
            assert field_count > 0, (
                f"seed={seed}: expected FIELD tiles around tower"
            )

    def test_outermost_ring_stays_void(self):
        """The 1-tile VOID margin contract per
        design/level_surface_layout.md must be preserved."""
        site = assemble_tower("t1", random.Random(1))
        w, h = site.surface.width, site.surface.height
        for x in range(w):
            assert (
                site.surface.tiles[0][x].terrain is Terrain.VOID
            )
            assert (
                site.surface.tiles[h - 1][x].terrain is Terrain.VOID
            )
        for y in range(h):
            assert (
                site.surface.tiles[y][0].terrain is Terrain.VOID
            )
            assert (
                site.surface.tiles[y][w - 1].terrain is Terrain.VOID
            )


class TestTowerSurfaceVegetation:
    """Trees and bushes scatter on the FIELD periphery; the per-
    biome density table makes forest dense and desert sparse."""

    def _count_feature(
        self, biome: Biome | None, feature: str, n_seeds: int = 30,
    ) -> int:
        total = 0
        for seed in range(n_seeds):
            site = assemble_tower(
                f"t{seed}", random.Random(seed), biome=biome,
            )
            for row in site.surface.tiles:
                total += sum(1 for t in row if t.feature == feature)
        return total

    def test_some_trees_scatter_with_default_biome(self):
        assert self._count_feature(None, "tree", n_seeds=20) > 0

    def test_some_bushes_scatter_with_default_biome(self):
        assert self._count_feature(None, "bush", n_seeds=20) > 0

    def test_forest_has_more_trees_than_mountain(self):
        forest = self._count_feature(Biome.FOREST, "tree")
        mountain = self._count_feature(Biome.MOUNTAIN, "tree")
        assert forest > 2 * mountain, (
            f"forest={forest} trees vs mountain={mountain}"
        )

    def test_sandlands_has_few_trees(self):
        """Desert variants stay nearly bare so the macro view reads
        as inhospitable."""
        sand = self._count_feature(Biome.SANDLANDS, "tree")
        greenlands = self._count_feature(Biome.GREENLANDS, "tree")
        assert sand < greenlands

    def test_vegetation_avoids_door_ring(self):
        """The 4-neighbour ring around the surface door tile stays
        clear so the entry reads cleanly."""
        for seed in range(10):
            site = assemble_tower(
                f"t{seed}", random.Random(seed),
            )
            for sx, sy in site.building_doors:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = sx + dx, sy + dy
                    if not site.surface.in_bounds(nx, ny):
                        continue
                    tile = site.surface.tiles[ny][nx]
                    assert tile.feature not in ("tree", "bush"), (
                        f"seed={seed}: vegetation at door-adjacent "
                        f"({nx},{ny})"
                    )


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
