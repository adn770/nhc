"""Tests for the SVG floor renderer."""

from nhc.dungeon.model import Level, Room, Rect, Terrain, Tile
from nhc.rendering.svg import render_floor_svg, CELL, PADDING


def _make_level(width=10, height=8):
    """Create a simple level with one room and a corridor."""
    level = Level.create_empty("test", "Test", depth=1,
                               width=width, height=height)
    # Carve a room (2,2)-(6,5)
    for y in range(2, 5):
        for x in range(2, 6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms.append(Room(id="r1", rect=Rect(2, 2, 4, 3)))

    # Carve a corridor from (6,3) to (8,3)
    for x in range(6, 9):
        level.tiles[3][x] = Tile(terrain=Terrain.FLOOR, is_corridor=True)

    # Add a closed door at (6,3)
    level.tiles[3][6].feature = "door_closed"

    # Add stairs down at (3,3)
    level.tiles[3][3].feature = "stairs_down"

    return level


class TestSVGOutput:
    def test_produces_valid_svg(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")

    def test_white_background(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "#FFFFFF" in svg

    def test_contains_room_shadow(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert 'opacity="0.08"' in svg

    def test_contains_floor_grid(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert 'opacity="0.7"' in svg  # hand-drawn grid

    def test_contains_walls(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "stroke-linecap" in svg
        assert "#000000" in svg

    def test_door_tiles_treated_as_floor(self):
        """Door tiles are walkable floor — no door-specific SVG."""
        level = _make_level()
        svg = render_floor_svg(level)
        # No door rectangles or door-specific stroke
        assert "door" not in svg.lower()

    def test_stairs_down_triangle(self):
        """Stairs down should render as a triangle with vertical lines."""
        level = _make_level()
        svg = render_floor_svg(level)
        assert "polygon" in svg  # triangle outline

    def test_stairs_up_triangle(self):
        level = _make_level()
        level.tiles[4][4] = Tile(terrain=Terrain.FLOOR)
        level.tiles[4][4].feature = "stairs_up"
        svg = render_floor_svg(level)
        assert svg.count("polygon") >= 2  # both stair types

    def test_contains_hatching(self):
        level = _make_level()
        svg = render_floor_svg(level, seed=42)
        assert "#D0D0D0" in svg  # hatch underlay

    def test_viewbox_dimensions(self):
        level = _make_level(width=10, height=8)
        svg = render_floor_svg(level)
        expected_w = 10 * CELL + 2 * PADDING
        expected_h = 8 * CELL + 2 * PADDING
        assert f'viewBox="0 0 {expected_w} {expected_h}"' in svg

    def test_locked_door_treated_as_floor(self):
        """Locked doors are also just floor in SVG."""
        level = _make_level()
        level.tiles[3][6].feature = "door_locked"
        svg = render_floor_svg(level)
        assert "door" not in svg.lower()

    def test_open_door_not_rendered(self):
        """Open doors have no SVG rendering."""
        level = Level.create_empty("t", "T", depth=1, width=5, height=5)
        for y in range(1, 4):
            for x in range(1, 4):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.tiles[2][3] = Tile(terrain=Terrain.FLOOR,
                                 feature="door_open")
        level.rooms.append(Room(id="r", rect=Rect(1, 1, 3, 3)))
        svg = render_floor_svg(level)
        # No polygon (no stairs), no door rectangle
        assert "polygon" not in svg

    def test_deterministic_with_same_seed(self):
        level = _make_level()
        svg1 = render_floor_svg(level, seed=123)
        svg2 = render_floor_svg(level, seed=123)
        assert svg1 == svg2

    def test_different_seed_different_hatching(self):
        level = _make_level()
        svg1 = render_floor_svg(level, seed=1)
        svg2 = render_floor_svg(level, seed=2)
        assert svg1 != svg2
