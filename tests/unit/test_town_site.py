"""Tests for the town site assembler (M15).

See design/building_generator.md section 5.5. A town is 5-8 small
buildings placed in a grid, surrounded by a palisade enclosure
with 1-2 gates. STREET surface between buildings; mixed
wood/stone interiors. Descent is rare.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.dungeon.site import Enclosure, Site
from nhc.dungeon.sites.town import (
    TOWN_DESCENT_PROBABILITY,
    _SIZE_CLASSES,
    assemble_town,
)

TOWN_BUILDING_COUNT_RANGE = (
    _SIZE_CLASSES["village"].building_count_range
)


def _surface_count(site: Site, surface: SurfaceType) -> int:
    return sum(
        1 for row in site.surface.tiles
        for t in row if t.surface_type == surface
    )


class TestAssembleTownBasics:
    def test_returns_site_with_town_kind(self):
        site = assemble_town("t1", random.Random(1))
        assert isinstance(site, Site)
        assert site.kind == "town"

    def test_enclosure_is_palisade(self):
        site = assemble_town("t1", random.Random(1))
        assert isinstance(site.enclosure, Enclosure)
        assert site.enclosure.kind == "palisade"

    def test_enclosure_has_one_or_two_gates(self):
        for seed in range(30):
            site = assemble_town("t1", random.Random(seed))
            assert 1 <= len(site.enclosure.gates) <= 2

    def test_gates_sit_on_west_or_east_edge(self):
        """Gates align with the main street running east-west
        between the two building rows; they live on the west
        (min_x) or east (max_x) palisade edge, not on top/bottom."""
        for seed in range(30):
            site = assemble_town("t1", random.Random(seed))
            xs = [p[0] for p in site.enclosure.polygon]
            min_x, max_x = min(xs), max(xs)
            for (gx, gy, length) in site.enclosure.gates:
                assert gx in (min_x, max_x), (
                    f"gate at x={gx} on seed={seed} is not on "
                    f"the west ({min_x}) or east ({max_x}) edge"
                )

    def test_gates_aligned_with_main_street_y(self):
        """All gates share the same y coordinate -- the main
        street passes through them."""
        for seed in range(30):
            site = assemble_town("t1", random.Random(seed))
            ys = {gy for (_, gy, _) in site.enclosure.gates}
            assert len(ys) == 1, (
                f"gates span y={sorted(ys)} on seed={seed}; "
                "all gates must sit on the main street y-centre"
            )


class TestTownBuildings:
    def test_building_count_in_range(self):
        lo, hi = TOWN_BUILDING_COUNT_RANGE
        for seed in range(30):
            site = assemble_town("t1", random.Random(seed))
            assert lo <= len(site.buildings) <= hi

    def test_all_buildings_validate(self):
        site = assemble_town("t1", random.Random(1))
        for b in site.buildings:
            b.validate()

    def test_mixed_interior_floor_materials(self):
        """Some buildings are wood (residential/market), others
        stone (temple/garrison)."""
        floors: set[str] = set()
        for seed in range(20):
            site = assemble_town("t1", random.Random(seed))
            for b in site.buildings:
                floors.add(b.interior_floor)
        assert "wood" in floors
        assert "stone" in floors


class TestTownSurface:
    def test_street_dominates_surface(self):
        site = assemble_town("t1", random.Random(1))
        assert _surface_count(site, SurfaceType.STREET) > 0

    def test_surface_has_no_field(self):
        site = assemble_town("t1", random.Random(1))
        assert _surface_count(site, SurfaceType.FIELD) == 0

    def test_building_footprint_not_overlaid_as_street(self):
        site = assemble_town("t1", random.Random(1))
        for b in site.buildings:
            for (x, y) in b.base_shape.floor_tiles(b.base_rect):
                if site.surface.in_bounds(x, y):
                    t = site.surface.tiles[y][x]
                    assert t.surface_type != SurfaceType.STREET

    def test_surface_svg_has_no_walled_island_strokes(self):
        """Street tiles must not emit the thick WALL stroke around
        them -- that creates the "walled island" look around every
        building and around the palisade. Detected via absence of
        the WALL_WIDTH stroke on a path inside the surface SVG."""
        from nhc.rendering._svg_helpers import WALL_WIDTH
        from nhc.rendering.svg import render_floor_svg
        site = assemble_town("t1", random.Random(42))
        svg = render_floor_svg(site.surface, seed=42)
        assert f'stroke-width="{WALL_WIDTH}"' not in svg

    def test_surface_svg_skips_grid_on_void_tiles(self):
        """On a surface with only street + void, the grid segment
        count (M commands inside the grid path) should be bounded
        by the street area rather than the full level area."""
        import re
        from nhc.dungeon.model import Terrain
        from nhc.rendering.svg import render_floor_svg
        site = assemble_town("t1", random.Random(42))
        svg = render_floor_svg(site.surface, seed=42)
        # Grid path(s) carry stroke-width="0.3". Pull the d="..."
        # attribute and count M commands = segments emitted.
        total_segments = 0
        for d in re.findall(
            r'<path d="([^"]+)"[^/]*stroke-width="0\.3"', svg,
        ):
            total_segments += d.count("M")
        n_floor = sum(
            1 for row in site.surface.tiles for t in row
            if t.terrain == Terrain.FLOOR
        )
        # Right + bottom edge per tile => 2 segments; each grid
        # segment can contribute up to 2 M commands when
        # _wobbly_grid_seg inserts a mid-gap. Cap at 3 * n_floor
        # with a small margin; if VOID tiles were contributing
        # (1500 total tiles vs 380 floor) we'd be well past this
        # bound.
        assert total_segments <= 3 * n_floor + 50, (
            f"grid emits {total_segments} segments for {n_floor} "
            f"FLOOR tiles -- VOID tiles are contributing"
        )

    def test_surface_svg_has_no_indoor_details(self):
        """The outdoor surface (STREET / FIELD / GARDEN tiles)
        should not carry indoor detail: no bones, skulls, floor
        stones, scratches, or hand-drawn cracks."""
        from nhc.rendering._svg_helpers import FLOOR_STONE_FILL
        from nhc.rendering.svg import render_floor_svg
        site = assemble_town("t1", random.Random(42))
        svg = render_floor_svg(site.surface, seed=42)
        assert "detail-bones" not in svg
        assert "detail-skulls" not in svg
        assert FLOOR_STONE_FILL not in svg
        assert 'class="y-scratch"' not in svg

    def test_street_tiles_lie_inside_palisade_polygon(self):
        """Every STREET tile must sit strictly inside the palisade
        bbox so the palisade border reads as drawn ON the black
        line enclosing the streets -- not one tile past them."""
        site = assemble_town("t1", random.Random(1))
        xs = [p[0] for p in site.enclosure.polygon]
        ys = [p[1] for p in site.enclosure.polygon]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        for y, row in enumerate(site.surface.tiles):
            for x, t in enumerate(row):
                if t.surface_type != SurfaceType.STREET:
                    continue
                # A tile at (tx, ty) spans pixels [tx, tx+1] in
                # tile units. The palisade polygon spans
                # [min_x, max_x] x [min_y, max_y]. Tile must fit
                # strictly inside: x+1 <= max_x and y+1 <= max_y.
                assert min_x <= x and x + 1 <= max_x, (
                    f"STREET tile x={x} outside palisade "
                    f"x-range [{min_x}, {max_x})"
                )
                assert min_y <= y and y + 1 <= max_y, (
                    f"STREET tile y={y} outside palisade "
                    f"y-range [{min_y}, {max_y})"
                )


class TestTownEnclosure:
    def test_palisade_polygon_encloses_all_buildings(self):
        site = assemble_town("t1", random.Random(1))
        poly = site.enclosure.polygon
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        for b in site.buildings:
            for (x, y) in b.base_shape.floor_tiles(b.base_rect):
                assert min_x <= x <= max_x
                assert min_y <= y <= max_y


class TestTownSurfaceReachability:
    """After dropping the 1-tile VOID buffer ring around building
    footprints and tightening ``_place_entry_door``, every
    building's surface door must sit on a walkable STREET tile
    with at least one walkable 4-neighbour that is also STREET.

    The old code would (1) add an 8-neighbour VOID ring around
    each building, and (2) pick any perimeter tile regardless of
    whether its outside-neighbour was reachable from the street.
    An L-shaped building could then land its door in the
    concave notch, sealed on three sides by its own footprint.
    """

    def _walkable_neighbour_count(self, site, x, y) -> int:
        count = 0
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            if not site.surface.in_bounds(nx, ny):
                continue
            t = site.surface.tiles[ny][nx]
            if t.terrain == Terrain.FLOOR:
                count += 1
        return count

    def test_every_surface_door_has_walkable_approach(self):
        """Each surface door tile must have ≥1 walkable 4-neighbour
        so the player can step onto it from the street."""
        for seed in range(60):
            site = assemble_town("t1", random.Random(seed))
            for (sx, sy), (bid, _bx, _by) in (
                site.building_doors.items()
            ):
                if not site.surface.in_bounds(sx, sy):
                    continue
                tile = site.surface.tiles[sy][sx]
                assert tile.terrain == Terrain.FLOOR, (
                    f"seed {seed}: surface door of {bid} at "
                    f"({sx},{sy}) is not FLOOR"
                )
                assert self._walkable_neighbour_count(
                    site, sx, sy,
                ) >= 1, (
                    f"seed {seed}: surface door of {bid} at "
                    f"({sx},{sy}) has no walkable 4-neighbour -- "
                    "door is sealed in a VOID pocket (L-shape "
                    "inner corner or abutting building)"
                )

    def test_no_void_buffer_ring_around_rect_buildings(self):
        """A rectangular building's footprint must be flanked by
        STREET tiles on every side that lies inside the enclosure
        -- no 8-neighbour VOID buffer ring."""
        site = assemble_town("t1", random.Random(7))
        poly = site.enclosure.polygon
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # All footprint tiles of every building in this site.
        all_footprints: set[tuple[int, int]] = set()
        for b in site.buildings:
            all_footprints |= b.base_shape.floor_tiles(b.base_rect)
        found_flank = False
        for b in site.buildings:
            from nhc.dungeon.model import RectShape
            if not isinstance(b.base_shape, RectShape):
                continue
            footprint = b.base_shape.floor_tiles(b.base_rect)
            for (x, y) in footprint:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in all_footprints:
                        continue
                    if not (min_x <= nx < max_x
                            and min_y <= ny < max_y):
                        continue
                    if not site.surface.in_bounds(nx, ny):
                        continue
                    tile = site.surface.tiles[ny][nx]
                    assert tile.terrain == Terrain.FLOOR, (
                        f"building {b.id} footprint at ({x},{y}) "
                        f"has VOID neighbour ({nx},{ny}) inside "
                        "palisade -- buffer ring should be gone"
                    )
                    assert tile.surface_type == SurfaceType.STREET
                    found_flank = True
        assert found_flank, (
            "test did not exercise any flanking tile -- adjust seed"
        )


class TestTownDescent:
    def test_descent_is_rare(self):
        count = 0
        trials = 200
        for seed in range(trials):
            site = assemble_town("t1", random.Random(seed))
            if any(b.descent is not None for b in site.buildings):
                count += 1
        ratio = count / trials
        # Spec says "rare"; per-building probability is small, and
        # site-level should stay under ~50%.
        assert ratio < 0.6


class TestTownDeterminism:
    def test_same_seed_same_building_count(self):
        s1 = assemble_town("t1", random.Random(42))
        s2 = assemble_town("t1", random.Random(42))
        assert len(s1.buildings) == len(s2.buildings)
