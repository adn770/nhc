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

    # Add a door at (6,3)
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

    def test_contains_background(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "#EDE0CE" in svg  # parchment background

    def test_contains_room_shadow(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "#999999" in svg  # shadow color

    def test_contains_floor_fills(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "#FFFFFF" in svg  # room floor
        assert "#F5F0E8" in svg  # corridor floor

    def test_contains_walls(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "stroke-linecap" in svg
        assert "#000000" in svg  # wall color

    def test_contains_door(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "#8B4513" in svg  # door brown

    def test_contains_stairs(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "polygon" in svg  # stair arrow

    def test_contains_hatching(self):
        level = _make_level()
        svg = render_floor_svg(level, seed=42)
        assert "#C0C0C0" in svg  # hatch color

    def test_viewbox_dimensions(self):
        level = _make_level(width=10, height=8)
        svg = render_floor_svg(level)
        expected_w = 10 * CELL + 2 * PADDING
        expected_h = 8 * CELL + 2 * PADDING
        assert f'viewBox="0 0 {expected_w} {expected_h}"' in svg

    def test_locked_door_color(self):
        level = _make_level()
        level.tiles[3][6].feature = "door_locked"
        svg = render_floor_svg(level)
        assert "#B22222" in svg  # locked door red

    def test_water_tiles(self):
        level = _make_level()
        level.tiles[4][3] = Tile(terrain=Terrain.WATER)
        svg = render_floor_svg(level)
        assert "#AEC6CF" in svg  # water color
        assert "circle" in svg  # water ripples

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
