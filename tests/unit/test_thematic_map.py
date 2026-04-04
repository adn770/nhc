"""Tests for thematic map generation improvements.

Covers:
1. Cave door placement (secret doors + open passages only)
2. Organic cave wall SVG rendering (smooth bezier outlines)
3. Thematic floor details (webs, bones, skulls) per theme
"""

from __future__ import annotations

import random
import re

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.cellular import CaveShape, CellularGenerator
from nhc.dungeon.model import (
    Level, LevelMetadata, Rect, RectShape, Room, Terrain, Tile,
)
from nhc.rendering.svg import (
    CELL, _bone_detail, _cave_svg_outline, _render_floor_detail,
    _room_shapely_polygon, _room_svg_outline, _skull_detail,
    _tile_thematic_detail, _web_detail, render_floor_svg,
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
                terrain=Terrain.FLOOR, is_corridor=True,
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
    """Caves should only have secret doors and open passages."""

    def test_no_closed_doors_in_cave(self):
        """Closed doors should never appear in cave levels."""
        level = _generate_cave()
        for row in level.tiles:
            for tile in row:
                assert tile.feature != "door_closed", (
                    "Cave levels must not have door_closed features"
                )

    def test_no_locked_doors_in_cave(self):
        """Locked doors should never appear in cave levels."""
        level = _generate_cave()
        for row in level.tiles:
            for tile in row:
                assert tile.feature != "door_locked", (
                    "Cave levels must not have door_locked features"
                )

    def test_cave_may_have_secret_doors(self):
        """With enough seeds, at least one cave should have a
        secret door (~10% chance per junction)."""
        found_secret = False
        for seed in range(100):
            level = _generate_cave(seed=seed)
            for row in level.tiles:
                for tile in row:
                    if tile.feature == "door_secret":
                        found_secret = True
                        break
                if found_secret:
                    break
            if found_secret:
                break
        assert found_secret, (
            "No secret doors found in 100 cave seeds"
        )

    def test_most_junctions_are_open(self):
        """The majority of corridor-cavern junctions should be
        open passages (no door feature)."""
        total_junctions = 0
        open_junctions = 0
        for seed in range(20):
            level = _generate_cave(seed=seed)
            for y in range(1, level.height - 1):
                for x in range(1, level.width - 1):
                    tile = level.tiles[y][x]
                    if not tile.is_corridor:
                        continue
                    for dx, dy in [(-1, 0), (1, 0),
                                   (0, -1), (0, 1)]:
                        nb = level.tiles[y + dy][x + dx]
                        if (nb.terrain == Terrain.FLOOR
                                and not nb.is_corridor):
                            total_junctions += 1
                            if not tile.feature:
                                open_junctions += 1
                            break
        assert total_junctions > 0
        ratio = open_junctions / total_junctions
        assert ratio > 0.80, (
            f"Expected >80% open junctions, got {ratio:.0%}"
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


class TestCaveCorridorGaps:
    """Caves with doorless corridor openings must have gaps in
    the wall outline where corridors connect — otherwise the
    smooth contour draws a wall right through the corridor mouth."""

    def test_cave_with_corridor_has_open_wall_path(self):
        """The cave wall path must NOT be closed (no Z) when a
        corridor connects without a door."""
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        svg = render_floor_svg(level)
        # Find wall-stroke paths that contain bezier curves (the
        # cave outline).  The gapped wall path must not be closed.
        wall_paths = re.findall(
            r'<path d="(M[^"]*C[^"]*)"[^>]*stroke-width="4',
            svg)
        assert wall_paths, "No cave wall path found"
        # At least one wall path must be an open curve (no Z)
        assert any("Z" not in p for p in wall_paths), (
            "Cave wall outline should have a gap at the corridor "
            "opening (no Z close), got all-closed paths"
        )

    def test_cave_with_corridor_has_multiple_subpaths(self):
        """A cave with a corridor opening produces at least one
        wall segment.  The fill can be closed but the wall must
        have an open section."""
        level, _ = _make_cave_room_level(with_corridor=True)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        svg = render_floor_svg(level)
        # The cave has ONE corridor opening on the west side.
        # The wall outline should be a single open curve around
        # the rest of the cave.
        wall_paths = re.findall(
            r'<path d="(M[^"]*C[^"]*)"[^>]*stroke-width="4',
            svg)
        open_paths = [p for p in wall_paths if "Z" not in p]
        assert open_paths, (
            "Expected an open wall path for cave with corridor"
        )

    def test_cave_without_corridor_stays_closed(self):
        """A cave with no corridor openings keeps a closed wall."""
        level, _ = _make_cave_room_level(with_corridor=False)
        level.metadata = LevelMetadata(theme="cave", difficulty=9)
        svg = render_floor_svg(level)
        wall_paths = re.findall(
            r'<path d="(M[^"]*C[^"]*)"[^>]*stroke-width="4',
            svg)
        assert wall_paths, "No cave wall path found"
        # All wall paths for this cave should be closed
        assert all("Z" in p for p in wall_paths), (
            "Cave without corridor should have closed wall"
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
