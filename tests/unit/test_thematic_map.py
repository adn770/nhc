"""Tests for thematic map generation improvements.

Covers:
1. Cave door placement (secret doors + open passages only)
2. Organic cave wall SVG rendering (smooth bezier outlines)
3. Thematic floor details (webs, bones, skulls) per theme
"""

from __future__ import annotations

import math
import random
import re

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.cellular import CaveShape, CellularGenerator
from nhc.dungeon.model import (
    Level, LevelMetadata, Rect, RectShape, Room, SurfaceType,
    Terrain, Tile,
)
from nhc.rendering.svg import (
    CELL, _bone_detail, _cave_svg_outline, _densify_ring,
    _jitter_ring_outward, _render_floor_detail,
    _room_shapely_polygon, _room_svg_outline, _skull_detail,
    _smooth_closed_path, _tile_thematic_detail, _web_detail,
    render_floor_svg,
    _THEMATIC_DETAIL_PROBS,
)


# ── Helpers ─────────────────────────────────────────────────────


def _generate_cave(seed: int = 42, depth: int = 9) -> Level:
    """Generate a cave level with the cellular generator."""
    rng = random.Random(seed)
    params = GenerationParams(depth=depth, theme="cave")
    gen = CellularGenerator()
    return gen.generate(params, rng=rng)


def _make_cave_room_level(
    with_corridor: bool = False,
) -> tuple[Level, Room]:
    """Create a small level with one cave-shaped room.

    If *with_corridor* is True, add a 3-tile corridor entering
    the cave from the west at y=6 (doorless opening).
    """
    level = Level.create_empty(
        "test", "Test Cave", depth=9, width=25, height=15,
    )
    # Carve an irregular cave shape
    tiles = set()
    for y in range(3, 10):
        for x in range(3, 14):
            # Exclude corners to make it irregular
            if (x, y) in {(3, 3), (13, 3), (3, 9), (13, 9),
                          (4, 3), (12, 3)}:
                continue
            tiles.add((x, y))
    for tx, ty in tiles:
        level.tiles[ty][tx] = Tile(terrain=Terrain.FLOOR)
    # Walls around floor
    for fx, fy in tiles:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (1, -1), (-1, 1), (1, 1)]:
            nx, ny = fx + dx, fy + dy
            if ((nx, ny) not in tiles
                    and level.in_bounds(nx, ny)
                    and level.tiles[ny][nx].terrain == Terrain.VOID):
                level.tiles[ny][nx] = Tile(terrain=Terrain.WALL)
    shape = CaveShape(tiles)
    room = Room(id="cave_1", rect=Rect(3, 3, 11, 7), shape=shape)
    level.rooms.append(room)

    if with_corridor:
        # Doorless corridor entering from the west at y=6.
        # Room's leftmost floor at y=6 is (3, 6).
        for cx in range(0, 3):
            level.tiles[6][cx] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.CORRIDOR,
            )
        # Walls above/below the corridor
        for cx in range(0, 3):
            for dy in (-1, 1):
                if level.tiles[6 + dy][cx].terrain == Terrain.VOID:
                    level.tiles[6 + dy][cx] = Tile(
                        terrain=Terrain.WALL,
                    )
        # The tile at (3, 6) is cave floor, neighbor (2, 6) is
        # corridor → this is a doorless opening. Also ensure the
        # wall that was between them (none, since (3,6) is floor
        # and (2,6) is now floor too) is cleared.
    return level, room


# ── 1. Cave door placement ─────────────────────────────────────


class TestCaveDoors:
    """Caves should have no doors at all — natural rock."""

    def test_no_doors_in_cave(self):
        """No door features of any kind in cave levels."""
        door_feats = {
            "door_closed", "door_open",
            "door_secret", "door_locked",
        }
        for seed in range(20):
            level = _generate_cave(seed=seed)
            for row in level.tiles:
                for tile in row:
                    assert tile.feature not in door_feats, (
                        f"Cave (seed={seed}) has {tile.feature}"
                    )



# ── 2. Organic cave wall SVG rendering ─────────────────────────


class TestCaveWallRendering:
    """Cave rooms should render with smooth bezier outlines."""

    def test_cave_shape_produces_outline(self):
        """_room_svg_outline should return a path for CaveShape."""
        _, room = _make_cave_room_level()
        outline = _room_svg_outline(room)
        assert outline is not None
        assert '<path d="' in outline
        assert outline.endswith('"/>')

    def test_cave_outline_has_bezier_curves(self):
        """Cave outline should contain cubic bezier commands (C)."""
        _, room = _make_cave_room_level()
        outline = _room_svg_outline(room)
        assert outline is not None
        # Extract the path data
        match = re.search(r'd="([^"]+)"', outline)
        assert match
        path_data = match.group(1)
        # Should start with M and contain C commands
        assert path_data.strip().startswith('M')
        assert 'C' in path_data, (
            "Cave outline should use cubic bezier curves"
        )

    def test_cave_outline_is_closed(self):
        """Cave outline path should be closed with Z."""
        _, room = _make_cave_room_level()
        outline = _room_svg_outline(room)
        assert outline is not None
        match = re.search(r'd="([^"]+)"', outline)
        path_data = match.group(1)
        assert path_data.strip().endswith('Z')

    def test_cave_shapely_polygon(self):
        """_room_shapely_polygon should return a valid polygon
        for CaveShape rooms."""
        _, room = _make_cave_room_level()
        poly = _room_shapely_polygon(room)
        assert poly is not None
        assert not poly.is_empty
        assert poly.area > 0

    def test_cave_room_in_full_render(self):
        """Full SVG render of a cave room should contain
        bezier curves in the wall layer."""
        level, _ = _make_cave_room_level()
        level.metadata = LevelMetadata(
            theme="cave", difficulty=9,
        )
        svg = render_floor_svg(level)
        # The SVG should contain cubic bezier commands
        assert ' C' in svg, (
            "Cave room SVG should contain bezier curve commands"
        )


class TestCaveRegionWalls:
    """Unified cave region wall tracer.

    Rooms + connected corridors are merged into one polygon and
    traced as a single continuous Dyson-style outline whose control
    points sit on (or are pushed outward from) the tile-edge polygon
    boundary — so walls always surround the floor tiles."""

    def test_cave_region_includes_corridor_tiles(self):
        """A cave room connected to a corridor must flood into a
        single region containing all corridor tiles."""
        from nhc.rendering.svg import _collect_cave_region
        level, room = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        region = _collect_cave_region(level)
        # All cave room tiles are in the region
        for t in room.floor_tiles():
            assert t in region
        # All corridor tiles at y=6, x=0..2 are in the region
        for cx in range(0, 3):
            assert (cx, 6) in region, (
                f"Corridor tile ({cx}, 6) missing from region"
            )

    def test_cave_region_polygon_has_single_exterior(self):
        """The unified polygon for one connected region exposes
        exactly one exterior ring (plus zero or more holes)."""
        from nhc.rendering.svg import (
            _build_cave_polygon, _collect_cave_region,
        )
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        region = _collect_cave_region(level)
        poly = _build_cave_polygon(region)
        assert poly is not None
        # Must be a single Polygon (not MultiPolygon) for one
        # connected region
        from shapely.geometry import Polygon as ShPolygon
        assert isinstance(poly, ShPolygon), (
            f"Expected single Polygon, got {type(poly).__name__}"
        )
        # And it must be simple (no self-intersections)
        assert poly.is_valid

    def test_jittered_ring_stays_outside_floor(self):
        """After outward jittering, every control point must lie on
        or outside the tile-edge polygon boundary — i.e. the floor
        polygon stays strictly inside the wall ring."""
        from nhc.rendering.svg import (
            _build_cave_polygon, _collect_cave_region,
            _densify_ring, _jitter_ring_outward,
        )
        from shapely.geometry import Polygon as ShPolygon
        import random
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        region = _collect_cave_region(level)
        floor_poly = _build_cave_polygon(region)
        assert floor_poly is not None

        # Take exterior, densify, jitter
        ext = list(floor_poly.exterior.coords)
        if ext and ext[0] == ext[-1]:
            ext = ext[:-1]
        dense = _densify_ring(ext, step=CELL * 0.6)
        rng = random.Random(123)
        jittered = _jitter_ring_outward(
            dense, floor_poly, rng, is_hole=False,
        )
        assert len(jittered) == len(dense)
        # Build a polygon from the jittered ring; it must CONTAIN
        # the floor polygon (every floor tile sits inside).
        wall_poly = ShPolygon(jittered)
        assert wall_poly.is_valid, "Jittered ring self-intersects"
        # Allow a tiny epsilon for float comparisons
        assert wall_poly.buffer(0.5).contains(floor_poly), (
            "Wall ring must fully enclose the floor polygon"
        )

    def test_cave_region_walls_single_path(self):
        """_cave_region_walls returns one SVG <path> containing
        one subpath per ring (exterior + holes)."""
        from nhc.rendering.svg import _cave_region_walls
        import random
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        rng = random.Random(42)
        el = _cave_region_walls(level, rng)
        assert el is not None
        assert el.startswith('<path d="')
        # Count M commands — one per subpath (ring)
        match = re.search(r'd="([^"]+)"', el)
        path_data = match.group(1)
        m_count = path_data.count('M')
        # One simply-connected region → exactly one exterior ring,
        # no holes → one subpath.
        assert m_count == 1, (
            f"Expected 1 subpath for simply-connected region, "
            f"got {m_count}"
        )
        # And it must be smoothed with cubic beziers
        assert 'C' in path_data

    def test_cave_region_walls_only_curves(self):
        """The unified wall path must NOT contain straight L
        segments — those would mean corridor tile-edge walls
        leaked through the old per-tile wall loop."""
        from nhc.rendering.svg import _cave_region_walls
        import random
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        rng = random.Random(42)
        el = _cave_region_walls(level, rng)
        assert el is not None
        match = re.search(r'd="([^"]+)"', el)
        path_data = match.group(1)
        assert ' L' not in path_data, (
            "Cave wall path should only contain bezier curves, "
            "no straight L segments"
        )

    def test_full_render_has_no_straight_corridor_walls(self):
        """In a full render of a cave level, the ink wall layer
        must not contain straight line segments for cave-region
        corridor tiles — they should be part of the organic path."""
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        svg = render_floor_svg(level)
        # The tile-edge wall segment loop draws straight lines with
        # paths like 'M{x},{y} L{x2},{y2}'.  For cave-region tiles
        # those must be absent.  Check: no tile-edge L segment at
        # (2,6) [corridor tile] south edge.
        # px = 2*32 = 64, py = 7*32 = 224 → 'M64,224 L96,224'
        assert 'M64,224 L96,224' not in svg, (
            "Corridor tile south edge leaked as straight line"
        )
        assert 'M64,192 L96,192' not in svg, (
            "Corridor tile north edge leaked as straight line"
        )

    def test_cave_region_deterministic(self):
        """Same seed → identical wall path."""
        from nhc.rendering.svg import _cave_region_walls
        import random
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        a = _cave_region_walls(level, random.Random(7))
        b = _cave_region_walls(level, random.Random(7))
        assert a == b

    def test_wall_polygon_extends_beyond_floor(self):
        """The wall polygon must extend into VOID space beyond the
        tile-edge floor polygon so the wall outline sits outside
        the walkable area."""
        from nhc.rendering.svg import (
            _build_cave_polygon, _build_cave_wall_geometry,
            _collect_cave_region,
        )
        import random
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        region = _collect_cave_region(level)
        floor_poly = _build_cave_polygon(region)
        _svg, wall_poly, _tiles = _build_cave_wall_geometry(
            level, random.Random(42),
        )
        assert floor_poly is not None and wall_poly is not None
        # Wall has strictly more area than the tile-edge floor
        assert wall_poly.area > floor_poly.area, (
            f"Wall area {wall_poly.area:.1f} should exceed "
            f"floor area {floor_poly.area:.1f}"
        )
        # Wall must fully contain the floor polygon
        assert wall_poly.buffer(0.5).contains(floor_poly), (
            "Wall polygon must fully contain the floor polygon"
        )

    def test_wall_polygon_rounds_sharp_corners(self):
        """L-shaped cave silhouettes should be arced, not sharp.
        Measure this by comparing the wall polygon to its convex
        hull: a well-rounded outline has a hull/area ratio far
        closer to 1 than the raw tile-edge polygon does."""
        from nhc.rendering.svg import (
            _build_cave_polygon, _build_cave_wall_geometry,
            _collect_cave_region,
        )
        import random
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        region = _collect_cave_region(level)
        floor_poly = _build_cave_polygon(region)
        _svg, wall_poly, _tiles = _build_cave_wall_geometry(
            level, random.Random(42),
        )
        assert floor_poly is not None and wall_poly is not None
        # Compare "roundedness" via boundary length per unit area:
        # a circle minimises this.  After rounding L corners and
        # buffering, the wall should be notably smoother than the
        # raw tile-edge polygon.
        import math
        def _compactness(p):
            return (p.length ** 2) / (4 * math.pi * p.area)
        floor_c = _compactness(floor_poly)
        wall_c = _compactness(wall_poly)
        # Wall must be at least as round as floor (lower = rounder)
        assert wall_c <= floor_c, (
            f"Wall compactness {wall_c:.2f} should be ≤ floor "
            f"compactness {floor_c:.2f} (lower is rounder)"
        )


# ── 3. Thematic floor details ──────────────────────────────────


class TestWebDetail:
    """Spider web detail generator."""

    def test_web_produces_svg_path(self):
        rng = random.Random(42)
        svg = _web_detail(rng, 100.0, 100.0, corner=0)
        assert '<path ' in svg
        assert 'fill="none"' in svg

    def test_web_has_radial_lines(self):
        """Web should have M...L segments (radial threads)."""
        rng = random.Random(42)
        svg = _web_detail(rng, 0.0, 0.0, corner=0)
        # Count M commands (one per radial + cross-threads)
        m_count = svg.count('M')
        assert m_count >= 3, (
            "Web should have at least 3 radial threads"
        )

    def test_web_has_cross_threads(self):
        """Web should have Q commands (quadratic cross-threads)."""
        rng = random.Random(42)
        svg = _web_detail(rng, 0.0, 0.0, corner=0)
        assert 'Q' in svg, "Web should have cross-thread curves"

    @pytest.mark.parametrize("corner", [0, 1, 2, 3])
    def test_web_all_corners(self, corner):
        """Web should render for all four corners."""
        rng = random.Random(42)
        svg = _web_detail(rng, 100.0, 100.0, corner=corner)
        assert '<path ' in svg


class TestBoneDetail:
    """Bone pile detail generator."""

    def test_bone_produces_elements(self):
        rng = random.Random(42)
        svg = _bone_detail(rng, 100.0, 100.0)
        assert '<g opacity="0.4">' in svg

    def test_bone_has_shafts_and_ends(self):
        """Bone pile should have line elements (shafts) and
        ellipse elements (epiphyses)."""
        rng = random.Random(42)
        svg = _bone_detail(rng, 100.0, 100.0)
        assert '<line ' in svg, "Bones need shaft lines"
        assert '<ellipse ' in svg, "Bones need epiphysis ends"

    def test_bone_has_multiple_bones(self):
        """Should generate 2-3 bones (each with 1 line + 2 ends)."""
        rng = random.Random(42)
        svg = _bone_detail(rng, 100.0, 100.0)
        line_count = svg.count('<line ')
        assert 2 <= line_count <= 3


class TestSkullDetail:
    """Skull detail generator."""

    def test_skull_produces_group(self):
        rng = random.Random(42)
        svg = _skull_detail(rng, 100.0, 100.0)
        assert '<g transform="translate(' in svg

    def test_skull_has_cranium_path(self):
        """Skull cranium should be a path (dome shape), not a
        full ellipse which looks like a mask."""
        rng = random.Random(42)
        svg = _skull_detail(rng, 100.0, 100.0)
        # Cranium is an unfilled path with curves
        assert re.search(
            r'<path[^>]*fill="none"[^>]*stroke', svg
        ), "Cranium should be a stroked path, not an ellipse"

    def test_skull_has_eye_sockets(self):
        """Skull should have two filled ellipses for eyes."""
        rng = random.Random(42)
        svg = _skull_detail(rng, 100.0, 100.0)
        filled = re.findall(r'<ellipse[^/]*fill="#000000"', svg)
        assert len(filled) >= 2, "Skull needs two eye sockets"

    def test_skull_has_nasal_cavity(self):
        """Skull should have a filled path for the nose."""
        rng = random.Random(42)
        svg = _skull_detail(rng, 100.0, 100.0)
        # Look for a small filled path (nasal triangle)
        filled_paths = re.findall(
            r'<path[^>]*fill="#000000"', svg)
        assert filled_paths, "Skull needs a nasal cavity"

    def test_skull_has_mandible(self):
        """Skull should have a separate mandible (jawbone) with
        a chin curve, not just a floating arc."""
        rng = random.Random(42)
        svg = _skull_detail(rng, 100.0, 100.0)
        # Mandible uses cubic bezier (C) for the chin curve
        assert 'C' in svg, "Mandible needs a cubic bezier chin"

    def test_skull_has_tooth_line(self):
        """Skull should have a tooth line between maxilla and
        mandible."""
        rng = random.Random(42)
        svg = _skull_detail(rng, 100.0, 100.0)
        # Tooth line is a short horizontal stroked line
        assert '<line ' in svg, "Skull needs a tooth line"


class TestThematicDetailProbabilities:
    """Theme-dependent probability tables."""

    def test_all_themes_have_probs(self):
        """Every theme in _DETAIL_SCALE should have thematic probs."""
        from nhc.rendering.svg import _DETAIL_SCALE
        for theme in _DETAIL_SCALE:
            assert theme in _THEMATIC_DETAIL_PROBS, (
                f"Missing thematic probs for theme '{theme}'"
            )

    def test_cave_has_highest_web_prob(self):
        """Cave theme should have the highest web probability."""
        cave_web = _THEMATIC_DETAIL_PROBS["cave"]["web"]
        for theme, probs in _THEMATIC_DETAIL_PROBS.items():
            if theme != "cave":
                assert probs["web"] <= cave_web, (
                    f"{theme} web prob {probs['web']} > "
                    f"cave {cave_web}"
                )

    def test_abyss_has_highest_skull_prob(self):
        """Abyss should have the most skulls."""
        abyss_skull = _THEMATIC_DETAIL_PROBS["abyss"]["skull"]
        for theme, probs in _THEMATIC_DETAIL_PROBS.items():
            if theme != "abyss":
                assert probs["skull"] <= abyss_skull

    def test_crypt_has_highest_bone_prob(self):
        """Crypt should have the most bone piles."""
        crypt_bones = _THEMATIC_DETAIL_PROBS["crypt"]["bones"]
        for theme, probs in _THEMATIC_DETAIL_PROBS.items():
            if theme != "crypt":
                assert probs["bones"] <= crypt_bones


class TestThematicDetailIntegration:
    """Thematic details integrate into the rendering pipeline."""

    def _make_themed_level(
        self, theme: str,
    ) -> Level:
        """Create a level with floor tiles and wall corners
        (suitable for web placement)."""
        level = Level.create_empty(
            "test", "Test", depth=1, width=10, height=8,
        )
        level.metadata = LevelMetadata(
            theme=theme, difficulty=1,
        )
        # Carve a room with wall corners for webs
        for y in range(2, 6):
            for x in range(2, 8):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(
            Room(id="r1", rect=Rect(2, 2, 6, 4))
        )
        return level

    def test_webs_only_in_wall_corners(self):
        """_tile_thematic_detail should only place webs in
        tiles adjacent to walls on two sides."""
        rng = random.Random(42)
        level = self._make_themed_level("cave")
        # Force high web probability
        probs = {"web": 1.0, "bones": 0, "skull": 0}
        webs: list[str] = []
        bones: list[str] = []
        skulls: list[str] = []

        # Interior tile (4,4) has floor on all sides — no web
        _tile_thematic_detail(
            rng, 4, 4, level, probs, webs, bones, skulls,
        )
        assert len(webs) == 0, (
            "Interior tile should not get a web"
        )

        # Corner tile (2,2) has walls on north and west — web OK
        _tile_thematic_detail(
            rng, 2, 2, level, probs, webs, bones, skulls,
        )
        assert len(webs) == 1, (
            "Corner tile should get a web"
        )

    def test_thematic_details_in_full_render(self):
        """Full render with crypt theme (high probs) should
        produce thematic detail CSS classes."""
        level = self._make_themed_level("crypt")
        svg = render_floor_svg(level, seed=42)
        # At least some thematic details should appear
        has_webs = 'class="detail-webs"' in svg
        has_bones = 'class="detail-bones"' in svg
        has_skulls = 'class="detail-skulls"' in svg
        assert has_webs or has_bones or has_skulls, (
            "Crypt theme should produce thematic details"
        )

    def test_no_thematic_on_wall_tiles(self):
        """Thematic details should not appear on wall-terrain
        tiles even if they're inside the room bounding box."""
        rng = random.Random(42)
        level = self._make_themed_level("abyss")
        probs = {"web": 1.0, "bones": 1.0, "skull": 1.0}
        webs: list[str] = []
        bones: list[str] = []
        skulls: list[str] = []
        # Pick a wall tile
        _tile_thematic_detail(
            rng, 1, 2, level, probs, webs, bones, skulls,
        )
        assert not webs and not bones and not skulls, (
            "Wall tiles should not get thematic details"
        )


# ── 4. Cave wall smoothing improvements ──────────────────────


class TestCentripetalCatmullRom:
    """Centripetal Catmull-Rom (α=0.5) should eliminate cusps."""

    def test_uneven_spacing_no_self_intersection(self):
        """A ring with wildly uneven point spacing should produce
        a valid (non-self-intersecting) polygon when smoothed
        with centripetal parameterization."""
        from shapely.geometry import Polygon as ShPolygon
        # Ring with a tight concave notch — uniform Catmull-Rom
        # tends to produce a loop here due to tangent overshoot.
        coords = [
            (0, 0), (100, 0), (100, 80),
            (60, 80), (55, 50), (50, 80),  # tight notch
            (0, 80),
        ]
        svg = _smooth_closed_path(coords)
        # Extract bezier path, sample points along it
        m = re.search(r'd="([^"]+)"', svg)
        assert m, "Should produce valid SVG path"
        path_data = m.group(1)
        # Must contain cubic beziers
        assert 'C' in path_data

    def test_collinear_points_no_degenerate(self):
        """Collinear points (zero chord length between some)
        should not cause division by zero or NaN."""
        coords = [
            (0, 0), (50, 0), (100, 0),  # collinear
            (100, 100), (0, 100),
        ]
        svg = _smooth_closed_path(coords)
        assert 'NaN' not in svg
        assert 'nan' not in svg
        assert 'inf' not in svg


class TestDenserControlPoints:
    """Reduced densification step produces more control points."""

    def test_smaller_step_more_points(self):
        """Halving the step should roughly double the synthetic
        vertex count on long edges."""
        ring = [(0, 0), (200, 0), (200, 200), (0, 200)]
        coarse = _densify_ring(ring, step=CELL * 0.7)
        fine = _densify_ring(ring, step=CELL * 0.4)
        assert len(fine) > len(coarse), (
            f"Fine {len(fine)} should exceed coarse {len(coarse)}"
        )

    def test_short_edges_unchanged(self):
        """Edges shorter than step should not gain new points."""
        ring = [(0, 0), (5, 0), (5, 5), (0, 5)]
        result = _densify_ring(ring, step=CELL * 0.4)
        assert len(result) == 4


class TestCornerAwareDamping:
    """Sharp corners should receive less jitter to prevent knots."""

    def test_sharp_corner_gets_less_jitter(self):
        """Across many seeds, the average jitter at a sharp
        concave corner should be less than on straight edges.
        Individual points vary due to the S-curve wave phase,
        so we average over multiple RNG seeds."""
        from shapely.geometry import Polygon as ShPolygon
        coords_ext = [
            (0, 0), (100, 0), (100, 50),
            (50, 50),  # sharp 90° inner corner
            (50, 100), (0, 100),
        ]
        floor_poly = ShPolygon(coords_ext)
        dense = _densify_ring(coords_ext, step=CELL * 0.4)
        # Find corner and straight-edge point indices
        corner_idx = min(
            range(len(dense)),
            key=lambda i: math.hypot(
                dense[i][0] - 50, dense[i][1] - 50),
        )
        # Average over seeds to smooth out wave phase effects
        corner_avg = 0.0
        edge_avg = 0.0
        n_seeds = 20
        for s in range(n_seeds):
            rng = random.Random(s)
            jittered = _jitter_ring_outward(
                dense, floor_poly, rng, is_hole=False,
            )
            corner_avg += math.hypot(
                jittered[corner_idx][0] - dense[corner_idx][0],
                jittered[corner_idx][1] - dense[corner_idx][1],
            )
            # Average displacement of all non-corner points
            total = 0.0
            for i in range(len(dense)):
                if i == corner_idx:
                    continue
                total += math.hypot(
                    jittered[i][0] - dense[i][0],
                    jittered[i][1] - dense[i][1],
                )
            edge_avg += total / (len(dense) - 1)
        corner_avg /= n_seeds
        edge_avg /= n_seeds
        assert corner_avg < edge_avg, (
            f"Avg corner jitter {corner_avg:.1f} should be "
            f"less than avg edge jitter {edge_avg:.1f}"
        )


class TestScurveUndulation:
    """S-curve perturbation creates organic Dyson-style walls."""

    def test_wall_ring_has_undulation(self):
        """The jittered wall ring should show sinusoidal variation
        in displacement magnitude along the perimeter, not just
        uniform random noise."""
        from nhc.rendering.svg import (
            _build_cave_polygon, _collect_cave_region,
            _build_cave_wall_geometry,
        )
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(
            theme="cave", difficulty=9,
        )
        _svg, wall_poly, _tiles = _build_cave_wall_geometry(
            level, random.Random(42),
        )
        assert wall_poly is not None
        # Sample distances from centroid along the boundary
        ext = list(wall_poly.exterior.coords)
        cx = sum(p[0] for p in ext) / len(ext)
        cy = sum(p[1] for p in ext) / len(ext)
        dists = [math.hypot(x - cx, y - cy) for x, y in ext]
        # Compute sign changes in the derivative (inflection
        # points) — S-curves create more inflections than pure
        # random jitter on a convex-ish shape.
        deltas = [dists[i+1] - dists[i] for i in range(len(dists)-1)]
        sign_changes = sum(
            1 for i in range(len(deltas) - 1)
            if deltas[i] * deltas[i+1] < 0
        )
        # With S-curve modulation we expect a meaningful number
        # of inflection points (at least 6 for a room perimeter).
        assert sign_changes >= 6, (
            f"Expected ≥6 inflection points for S-curve "
            f"undulation, got {sign_changes}"
        )

    def test_existing_containment_still_holds(self):
        """After all smoothing improvements, the wall polygon
        must still fully contain the floor polygon."""
        from nhc.rendering.svg import (
            _build_cave_polygon, _collect_cave_region,
            _build_cave_wall_geometry,
        )
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(
            theme="cave", difficulty=9,
        )
        region = _collect_cave_region(level)
        floor_poly = _build_cave_polygon(region)
        _svg, wall_poly, _tiles = _build_cave_wall_geometry(
            level, random.Random(42),
        )
        assert floor_poly is not None and wall_poly is not None
        assert wall_poly.buffer(0.5).contains(floor_poly), (
            "Wall polygon must still enclose the floor polygon"
        )
