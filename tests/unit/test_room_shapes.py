"""Tests for room shape abstraction."""

import json

import pytest

from nhc.core.ecs import World
from nhc.core.save import load_game, save_game
from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, Level, OctagonShape,
    PillShape, Rect, Room, RoomShape, RectShape, TempleShape, Terrain,
    Tile, shape_from_type,
)
from nhc.entities.components import (
    Health, Player, Position, Renderable, Stats,
)
from nhc.rendering.terminal.glyphs import wall_glyph
from nhc.rendering.terminal.renderer import TerminalRenderer
from nhc.rendering.terminal.themes import get_theme, set_theme
from nhc.utils.rng import set_seed


class TestRectShape:
    def test_floor_tiles_covers_full_rect(self):
        rect = Rect(2, 3, 4, 5)
        shape = RectShape()
        tiles = shape.floor_tiles(rect)
        expected = {
            (x, y)
            for y in range(3, 8)
            for x in range(2, 6)
        }
        assert tiles == expected

    def test_floor_tiles_count(self):
        rect = Rect(0, 0, 6, 4)
        shape = RectShape()
        assert len(shape.floor_tiles(rect)) == 24

    def test_floor_tiles_min_room(self):
        rect = Rect(5, 5, 4, 4)
        shape = RectShape()
        tiles = shape.floor_tiles(rect)
        assert len(tiles) == 16

    def test_perimeter_tiles_are_edges(self):
        rect = Rect(0, 0, 4, 4)
        shape = RectShape()
        perimeter = shape.perimeter_tiles(rect)
        floor = shape.floor_tiles(rect)
        # Perimeter should be a subset of floor
        assert perimeter <= floor
        # Interior (2,2 area) should not be in perimeter
        # For a 4x4 rect, interior is (1,1), (2,1), (1,2), (2,2)
        interior = floor - perimeter
        assert len(interior) == 4
        for x, y in interior:
            assert 1 <= x <= 2
            assert 1 <= y <= 2

    def test_perimeter_tiles_small_rect(self):
        """A 2x2 rect has all tiles on the perimeter."""
        rect = Rect(0, 0, 2, 2)
        shape = RectShape()
        perimeter = shape.perimeter_tiles(rect)
        assert perimeter == shape.floor_tiles(rect)


class TestRoomShapeInterface:
    def test_rect_shape_type_name(self):
        assert RectShape.type_name == "rect"

    def test_room_default_shape_is_rect(self):
        room = Room(id="r1", rect=Rect(0, 0, 5, 5))
        assert isinstance(room.shape, RectShape)

    def test_room_floor_tiles_delegates_to_shape(self):
        rect = Rect(1, 1, 3, 3)
        room = Room(id="r1", rect=rect)
        assert room.floor_tiles() == room.shape.floor_tiles(rect)

    def test_room_with_explicit_shape(self):
        shape = RectShape()
        room = Room(id="r1", rect=Rect(0, 0, 4, 4), shape=shape)
        assert room.shape is shape

    def test_shape_is_abstract(self):
        """RoomShape cannot be instantiated directly."""
        with pytest.raises(TypeError):
            RoomShape()


class TestCircleShape:
    def test_type_name(self):
        assert CircleShape.type_name == "circle"

    def test_5x5_circle(self):
        """5x5 is the minimum size that looks circular."""
        rect = Rect(0, 0, 5, 5)
        shape = CircleShape()
        tiles = shape.floor_tiles(rect)
        # Center (2,2) must be included
        assert (2, 2) in tiles
        # Corners should be excluded
        assert (0, 0) not in tiles
        assert (4, 0) not in tiles
        assert (0, 4) not in tiles
        assert (4, 4) not in tiles

    def test_5x5_circle_tile_count(self):
        rect = Rect(0, 0, 5, 5)
        tiles = CircleShape().floor_tiles(rect)
        # pi * r^2 = pi * 4 ~ 12.6, discrete rasterization gives 13
        assert len(tiles) == 13

    def test_7x7_circle_symmetry(self):
        """Circle should be symmetric around its center."""
        rect = Rect(0, 0, 7, 7)
        tiles = CircleShape().floor_tiles(rect)
        cx, cy = 3, 3
        for x, y in tiles:
            # Reflect around center — all 4 quadrants
            assert (2 * cx - x, y) in tiles, f"H-mirror of ({x},{y})"
            assert (x, 2 * cy - y) in tiles, f"V-mirror of ({x},{y})"
            assert (2 * cx - x, 2 * cy - y) in tiles, f"Both of ({x},{y})"

    def test_9x9_circle(self):
        rect = Rect(5, 5, 9, 9)
        tiles = CircleShape().floor_tiles(rect)
        # Center must be floor
        assert (9, 9) in tiles
        # All tiles must be within bounding rect
        for x, y in tiles:
            assert 5 <= x < 14
            assert 5 <= y < 14

    def test_circle_fewer_tiles_than_rect(self):
        """Circle should have fewer floor tiles than a same-sized rect."""
        rect = Rect(0, 0, 7, 7)
        circle_tiles = CircleShape().floor_tiles(rect)
        rect_tiles = RectShape().floor_tiles(rect)
        assert len(circle_tiles) < len(rect_tiles)

    def test_circle_subset_of_rect(self):
        """All circle tiles must be within the bounding rect."""
        rect = Rect(3, 7, 8, 6)
        circle_tiles = CircleShape().floor_tiles(rect)
        rect_tiles = RectShape().floor_tiles(rect)
        assert circle_tiles <= rect_tiles

    def test_non_square_rect_still_circular(self):
        """Non-square rect produces a circle, not an ellipse."""
        rect = Rect(0, 0, 9, 5)
        tiles = CircleShape().floor_tiles(rect)
        # Uses min(9,5)=5 as diameter, centered
        # Center is at (4, 2), radius ~2
        assert (4, 2) in tiles  # center
        # Should NOT extend to far x edges (not an ellipse)
        assert (0, 2) not in tiles
        assert (8, 2) not in tiles
        # Symmetric around center
        for x, y in tiles:
            assert (8 - x, y) in tiles, f"H-mirror of ({x},{y})"

    def test_tiny_rect_produces_empty(self):
        """1x1 and 2x2 rects produce empty or near-empty circles."""
        assert len(CircleShape().floor_tiles(Rect(0, 0, 1, 1))) <= 1

    def test_circle_perimeter(self):
        """Perimeter tiles should form the outer ring."""
        rect = Rect(0, 0, 7, 7)
        shape = CircleShape()
        floor = shape.floor_tiles(rect)
        perimeter = shape.perimeter_tiles(rect)
        interior = floor - perimeter
        assert len(perimeter) > 0
        assert len(interior) > 0
        assert perimeter <= floor

    def test_room_with_circle_shape(self):
        room = Room(id="r1", rect=Rect(0, 0, 7, 7), shape=CircleShape())
        tiles = room.floor_tiles()
        assert (3, 3) in tiles
        assert (0, 0) not in tiles



class TestOctagonShape:
    def test_type_name(self):
        assert OctagonShape.type_name == "octagon"

    def test_7x7_octagon(self):
        rect = Rect(0, 0, 7, 7)
        tiles = OctagonShape().floor_tiles(rect)
        # Center must be floor
        assert (3, 3) in tiles
        # Corners should be clipped
        assert (0, 0) not in tiles
        assert (6, 0) not in tiles
        assert (0, 6) not in tiles
        assert (6, 6) not in tiles
        # Mid-edges should be floor
        assert (3, 0) in tiles  # top center
        assert (0, 3) in tiles  # left center
        assert (6, 3) in tiles  # right center
        assert (3, 6) in tiles  # bottom center

    def test_octagon_symmetry(self):
        rect = Rect(0, 0, 9, 9)
        tiles = OctagonShape().floor_tiles(rect)
        cx, cy = 4, 4
        for x, y in tiles:
            assert (2 * cx - x, y) in tiles, f"H-mirror of ({x},{y})"
            assert (x, 2 * cy - y) in tiles, f"V-mirror of ({x},{y})"

    def test_octagon_fewer_tiles_than_rect(self):
        rect = Rect(0, 0, 7, 7)
        assert len(OctagonShape().floor_tiles(rect)) < len(
            RectShape().floor_tiles(rect)
        )

    def test_octagon_more_tiles_than_circle(self):
        """Octagon is closer to a rect than a circle."""
        rect = Rect(0, 0, 9, 9)
        oct_tiles = OctagonShape().floor_tiles(rect)
        circle_tiles = CircleShape().floor_tiles(rect)
        assert len(oct_tiles) > len(circle_tiles)

    def test_octagon_subset_of_rect(self):
        rect = Rect(1, 2, 8, 8)
        assert OctagonShape().floor_tiles(rect) <= RectShape().floor_tiles(rect)

    def test_octagon_5x5(self):
        """Minimum viable octagon."""
        rect = Rect(0, 0, 5, 5)
        tiles = OctagonShape().floor_tiles(rect)
        assert (2, 2) in tiles
        assert (0, 0) not in tiles
        assert len(tiles) > 0

    def test_octagon_perimeter(self):
        rect = Rect(0, 0, 7, 7)
        shape = OctagonShape()
        floor = shape.floor_tiles(rect)
        perimeter = shape.perimeter_tiles(rect)
        assert len(perimeter) > 0
        assert perimeter <= floor


class TestPillShape:
    def test_type_name(self):
        assert PillShape.type_name == "pill"

    def test_horizontal_pill_5x9(self):
        """5 tall × 9 wide pill: straight middle + two semicircle caps."""
        rect = Rect(0, 0, 9, 5)
        tiles = PillShape().floor_tiles(rect)
        # Center must be floor
        assert (4, 2) in tiles
        # Middle band is a full rectangle between the two arc centres.
        # For d=5, r=2: left_cx=2, right_cx=6. Straight cols [2,6] are
        # fully covered across all 5 rows.
        for x in range(2, 7):
            for y in range(0, 5):
                assert (x, y) in tiles, f"middle tile ({x},{y}) missing"
        # Semicircle caps: corners of the bounding rect are excluded.
        assert (0, 0) not in tiles
        assert (0, 4) not in tiles
        assert (8, 0) not in tiles
        assert (8, 4) not in tiles
        # Tip of left semicircle (x=0, y=2) and right (x=8, y=2) are floor
        assert (0, 2) in tiles
        assert (8, 2) in tiles

    def test_vertical_pill_5x9(self):
        """9 tall × 5 wide pill: rotated, semicircle caps on top/bottom."""
        rect = Rect(0, 0, 5, 9)
        tiles = PillShape().floor_tiles(rect)
        assert (2, 4) in tiles  # center
        # Middle band across the straight section
        for y in range(2, 7):
            for x in range(0, 5):
                assert (x, y) in tiles
        # Corners of bounding rect excluded
        assert (0, 0) not in tiles
        assert (4, 0) not in tiles
        assert (0, 8) not in tiles
        assert (4, 8) not in tiles
        # Top and bottom tips included
        assert (2, 0) in tiles
        assert (2, 8) in tiles

    def test_pill_symmetry(self):
        """Horizontal pill is symmetric across both axes."""
        rect = Rect(0, 0, 11, 5)
        tiles = PillShape().floor_tiles(rect)
        cx, cy = 5, 2
        for x, y in tiles:
            assert (2 * cx - x, y) in tiles, f"H-mirror of ({x},{y})"
            assert (x, 2 * cy - y) in tiles, f"V-mirror of ({x},{y})"

    def test_pill_subset_of_rect(self):
        rect = Rect(3, 4, 11, 5)
        pill = PillShape().floor_tiles(rect)
        box = RectShape().floor_tiles(rect)
        assert pill <= box

    def test_pill_fewer_than_rect(self):
        rect = Rect(0, 0, 9, 5)
        assert len(PillShape().floor_tiles(rect)) < len(
            RectShape().floor_tiles(rect)
        )

    def test_pill_more_tiles_than_circle_when_elongated(self):
        """Elongated pills have more tiles than a circle in the same rect."""
        rect = Rect(0, 0, 9, 5)
        pill = PillShape().floor_tiles(rect)
        circle = CircleShape().floor_tiles(rect)
        assert len(pill) > len(circle)

    def test_pill_origin_offset(self):
        """Pill respects rect origin."""
        rect = Rect(10, 20, 9, 5)
        tiles = PillShape().floor_tiles(rect)
        for x, y in tiles:
            assert 10 <= x < 19
            assert 20 <= y < 25
        # center of pill
        assert (14, 22) in tiles

    def test_pill_perimeter(self):
        rect = Rect(0, 0, 9, 5)
        shape = PillShape()
        floor = shape.floor_tiles(rect)
        perimeter = shape.perimeter_tiles(rect)
        interior = floor - perimeter
        assert len(perimeter) > 0
        assert len(interior) > 0
        assert perimeter <= floor

    def test_pill_registry_resolves(self):
        """shape_from_type('pill') returns a PillShape."""
        assert isinstance(shape_from_type("pill"), PillShape)

    def test_pill_room_save_roundtrip(self, tmp_path):
        """PillShape survives save/load via type_name."""
        from nhc.dungeon.model import Room

        room = Room(id="r1", rect=Rect(0, 0, 9, 5), shape=PillShape())
        assert room.shape.type_name == "pill"
        resolved = shape_from_type(room.shape.type_name)
        assert isinstance(resolved, PillShape)


class TestTempleShape:
    def test_type_name_includes_flat_side(self):
        assert TempleShape(flat_side="south").type_name == "temple_s"
        assert TempleShape(flat_side="north").type_name == "temple_n"
        assert TempleShape(flat_side="east").type_name == "temple_e"
        assert TempleShape(flat_side="west").type_name == "temple_w"

    def test_invalid_flat_side_defaults(self):
        assert TempleShape(flat_side="bogus").flat_side == "south"

    def test_temple_9x9_south_flat(self):
        """9x9 temple with flat south arm: 3 capped + 1 rectangular."""
        rect = Rect(0, 0, 9, 9)
        shape = TempleShape(flat_side="south")
        tiles = shape.floor_tiles(rect)

        # Centre intersection is floor
        assert (4, 4) in tiles

        # South arm (flat): full 3x3 rectangle at the bottom
        for y in (6, 7, 8):
            for x in (3, 4, 5):
                assert (x, y) in tiles, f"south arm ({x},{y}) missing"

        # North arm tip row has only the centre column (corners clipped)
        assert (4, 0) in tiles
        assert (3, 0) not in tiles
        assert (5, 0) not in tiles

        # East arm tip column has only the centre row
        assert (8, 4) in tiles
        assert (8, 3) not in tiles
        assert (8, 5) not in tiles

        # West arm tip column has only the centre row
        assert (0, 4) in tiles
        assert (0, 3) not in tiles
        assert (0, 5) not in tiles

        # Row just inside the cap: north arm at y=1 is fully 3 wide
        for x in (3, 4, 5):
            assert (x, 1) in tiles

        # Bounding-rect corners are never floor
        assert (0, 0) not in tiles
        assert (8, 0) not in tiles
        assert (0, 8) not in tiles
        assert (8, 8) not in tiles

    def test_temple_north_flat_has_rectangular_north_arm(self):
        rect = Rect(0, 0, 9, 9)
        tiles = TempleShape(flat_side="north").floor_tiles(rect)
        # North arm is the flat one: full 3x3 at top
        for y in (0, 1, 2):
            for x in (3, 4, 5):
                assert (x, y) in tiles
        # South arm tip now capped: only (4, 8)
        assert (4, 8) in tiles
        assert (3, 8) not in tiles
        assert (5, 8) not in tiles

    def test_temple_is_superset_of_cross_with_capped_corners_removed(self):
        """Temple tiles ⊆ cross tiles (capping only removes tiles)."""
        rect = Rect(0, 0, 9, 9)
        temple = TempleShape(flat_side="south").floor_tiles(rect)
        cross = CrossShape().floor_tiles(rect)
        assert temple <= cross
        # Exactly 6 tiles removed (2 corners × 3 capped arms, bar_w=3)
        assert len(cross) - len(temple) == 6

    def test_temple_flat_side_symmetry(self):
        """Mirror symmetry across the axis containing the flat arm."""
        rect = Rect(0, 0, 9, 9)
        tiles = TempleShape(flat_side="south").floor_tiles(rect)
        cx = 4
        # Horizontal mirror (across the vertical centreline x=cx)
        for x, y in tiles:
            assert (2 * cx - x, y) in tiles, f"mirror of ({x},{y}) missing"

    def test_temple_subset_of_rect(self):
        rect = Rect(5, 3, 9, 9)
        assert (TempleShape().floor_tiles(rect)
                <= RectShape().floor_tiles(rect))

    def test_temple_origin_offset(self):
        rect = Rect(10, 20, 9, 9)
        tiles = TempleShape(flat_side="south").floor_tiles(rect)
        for x, y in tiles:
            assert 10 <= x < 19
            assert 20 <= y < 29
        # Center of temple
        assert (14, 24) in tiles
        # South flat arm tip
        assert (14, 28) in tiles
        assert (13, 28) in tiles
        assert (15, 28) in tiles

    def test_temple_perimeter(self):
        rect = Rect(0, 0, 9, 9)
        shape = TempleShape(flat_side="south")
        floor = shape.floor_tiles(rect)
        perim = shape.perimeter_tiles(rect)
        interior = floor - perim
        assert len(perim) > 0
        assert len(interior) > 0
        assert perim <= floor

    def test_temple_cardinal_walls_skips_flat_side(self):
        """cardinal_walls returns only the 3 capped arm tip wall positions."""
        rect = Rect(0, 0, 9, 9)
        walls = TempleShape(flat_side="south").cardinal_walls(rect)
        assert len(walls) == 3
        walls_set = set(walls)
        # North, east, west cardinals (just outside rect)
        assert (4, -1) in walls_set     # north
        assert (9, 4) in walls_set      # east
        assert (-1, 4) in walls_set     # west
        # South is the flat side — not injected
        assert (4, 9) not in walls_set

    def test_temple_cardinal_walls_north_flat(self):
        rect = Rect(0, 0, 9, 9)
        walls = set(TempleShape(flat_side="north").cardinal_walls(rect))
        assert (4, 9) in walls
        assert (9, 4) in walls
        assert (-1, 4) in walls
        assert (4, -1) not in walls

    def test_temple_registry_roundtrip(self):
        """shape_from_type restores the same variant."""
        for side_char, full in [
            ("n", "north"), ("s", "south"),
            ("e", "east"), ("w", "west"),
        ]:
            resolved = shape_from_type(f"temple_{side_char}")
            assert isinstance(resolved, TempleShape)
            assert resolved.flat_side == full

    def test_temple_7x7_minimum_size(self):
        """Smallest temple (7x7) still produces valid geometry."""
        rect = Rect(0, 0, 7, 7)
        tiles = TempleShape(flat_side="south").floor_tiles(rect)
        # Center and flat-side arm must be present
        assert (3, 3) in tiles
        assert (3, 6) in tiles
        # Capped tips present
        assert (3, 0) in tiles
        assert (0, 3) in tiles
        assert (6, 3) in tiles


class TestCrossShape:
    def test_type_name(self):
        assert CrossShape.type_name == "cross"

    def test_7x7_cross(self):
        rect = Rect(0, 0, 7, 7)
        tiles = CrossShape().floor_tiles(rect)
        # Center must be floor
        assert (3, 3) in tiles
        # All 4 corners should be void (not in the + shape)
        assert (0, 0) not in tiles
        assert (6, 0) not in tiles
        assert (0, 6) not in tiles
        assert (6, 6) not in tiles
        # Arms extend to edges
        assert (3, 0) in tiles   # top arm
        assert (3, 6) in tiles   # bottom arm
        assert (0, 3) in tiles   # left arm
        assert (6, 3) in tiles   # right arm

    def test_cross_symmetry(self):
        rect = Rect(0, 0, 9, 9)
        tiles = CrossShape().floor_tiles(rect)
        cx, cy = 4, 4
        for x, y in tiles:
            assert (2 * cx - x, y) in tiles, f"H-mirror of ({x},{y})"
            assert (x, 2 * cy - y) in tiles, f"V-mirror of ({x},{y})"

    def test_cross_fewer_tiles_than_rect(self):
        rect = Rect(0, 0, 7, 7)
        assert len(CrossShape().floor_tiles(rect)) < len(
            RectShape().floor_tiles(rect)
        )

    def test_cross_subset_of_rect(self):
        rect = Rect(2, 3, 8, 6)
        assert CrossShape().floor_tiles(rect) <= RectShape().floor_tiles(rect)

    def test_cross_perimeter(self):
        rect = Rect(0, 0, 7, 7)
        shape = CrossShape()
        floor = shape.floor_tiles(rect)
        perimeter = shape.perimeter_tiles(rect)
        assert len(perimeter) > 0
        assert perimeter <= floor

    def test_cross_has_four_arms(self):
        """Cross should have tiles at all 4 edges of the rect."""
        rect = Rect(0, 0, 9, 9)
        tiles = CrossShape().floor_tiles(rect)
        top = any(y == 0 for _, y in tiles)
        bottom = any(y == 8 for _, y in tiles)
        left = any(x == 0 for x, _ in tiles)
        right = any(x == 8 for x, _ in tiles)
        assert top and bottom and left and right


class TestHybridShape:
    def test_vertical_split_circle_rect(self):
        """Left half circle, right half rect."""
        rect = Rect(0, 0, 10, 7)
        shape = HybridShape(CircleShape(), RectShape(), "vertical")
        tiles = shape.floor_tiles(rect)
        # Center of both halves should be floor
        assert (2, 3) in tiles   # left half center
        assert (7, 3) in tiles   # right half center
        # All tiles within bounding rect
        for x, y in tiles:
            assert 0 <= x < 10 and 0 <= y < 7

    def test_horizontal_split(self):
        rect = Rect(0, 0, 7, 10)
        shape = HybridShape(CircleShape(), RectShape(), "horizontal")
        tiles = shape.floor_tiles(rect)
        assert len(tiles) > 0
        for x, y in tiles:
            assert 0 <= x < 7 and 0 <= y < 10

    def test_hybrid_subset_of_rect(self):
        rect = Rect(2, 3, 10, 8)
        shape = HybridShape(CircleShape(), RectShape(), "vertical")
        assert shape.floor_tiles(rect) <= RectShape().floor_tiles(rect)

    def test_hybrid_type_name(self):
        shape = HybridShape(CircleShape(), RectShape(), "vertical")
        assert shape.type_name == "hybrid_circle_rect_v"
        shape2 = HybridShape(OctagonShape(), RectShape(), "horizontal")
        assert shape2.type_name == "hybrid_octagon_rect_h"

    def test_hybrid_perimeter(self):
        rect = Rect(0, 0, 10, 7)
        shape = HybridShape(CircleShape(), RectShape(), "vertical")
        floor = shape.floor_tiles(rect)
        perimeter = shape.perimeter_tiles(rect)
        assert len(perimeter) > 0
        assert perimeter <= floor

    def test_hybrid_save_load_roundtrip(self, tmp_path):
        """Hybrid shapes survive save→load."""
        shape = HybridShape(CircleShape(), RectShape(), "vertical")
        loaded = shape_from_type(shape.type_name)
        assert isinstance(loaded, HybridShape)
        assert loaded.type_name == shape.type_name
        # Floor tiles should match
        rect = Rect(0, 0, 10, 7)
        assert loaded.floor_tiles(rect) == shape.floor_tiles(rect)


class TestShapeRegistry:
    def test_resolve_rect(self):
        shape = shape_from_type("rect")
        assert isinstance(shape, RectShape)

    def test_resolve_circle(self):
        shape = shape_from_type("circle")
        assert isinstance(shape, CircleShape)

    def test_resolve_octagon(self):
        shape = shape_from_type("octagon")
        assert isinstance(shape, OctagonShape)

    def test_resolve_cross(self):
        shape = shape_from_type("cross")
        assert isinstance(shape, CrossShape)

    def test_resolve_unknown_defaults_to_rect(self):
        shape = shape_from_type("unknown_future_shape")
        assert isinstance(shape, RectShape)

    def test_resolve_none_defaults_to_rect(self):
        shape = shape_from_type(None)
        assert isinstance(shape, RectShape)


class TestShapeSaveLoad:
    def test_room_shape_survives_save_load(self, tmp_path):
        """Shape type is preserved through JSON save/load."""
        tiles = [
            [Tile(terrain=Terrain.FLOOR) for _ in range(10)]
            for _ in range(10)
        ]
        level = Level(
            id="test", name="Test", depth=1,
            width=10, height=10, tiles=tiles,
            rooms=[Room(id="room_1", rect=Rect(1, 1, 5, 5))],
        )

        world = World()
        pid = world.create_entity({
            "Position": Position(x=3, y=3, level_id="test"),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=8, maximum=8),
            "Player": Player(),
            "Renderable": Renderable(glyph="@", color="white"),
        })

        path = tmp_path / "save.json"
        save_game(world, level, pid, 1, [], save_path=path)
        _, loaded_level, _, _, _ = load_game(save_path=path)

        assert len(loaded_level.rooms) == 1
        room = loaded_level.rooms[0]
        assert isinstance(room.shape, RectShape)
        assert room.shape.type_name == "rect"

    def test_circle_shape_survives_save_load(self, tmp_path):
        """Circle shape type is preserved through JSON save/load."""
        tiles = [
            [Tile(terrain=Terrain.FLOOR) for _ in range(10)]
            for _ in range(10)
        ]
        level = Level(
            id="test", name="Test", depth=1,
            width=10, height=10, tiles=tiles,
            rooms=[Room(
                id="room_1", rect=Rect(1, 1, 7, 7),
                shape=CircleShape(),
            )],
        )

        world = World()
        pid = world.create_entity({
            "Position": Position(x=3, y=3, level_id="test"),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=8, maximum=8),
            "Player": Player(),
            "Renderable": Renderable(glyph="@", color="white"),
        })

        path = tmp_path / "save.json"
        save_game(world, level, pid, 1, [], save_path=path)
        _, loaded_level, _, _, _ = load_game(save_path=path)

        room = loaded_level.rooms[0]
        assert isinstance(room.shape, CircleShape)
        assert room.shape.type_name == "circle"

class TestCircleRoomGeneration:
    """Integration tests: generate dungeons with circular rooms."""

    def _generate_with_circles(self, seed=42):
        set_seed(seed)
        gen = BSPGenerator()
        params = GenerationParams(
            width=60, height=40, shape_variety=1.0,
        )
        return gen.generate(params)

    def test_generates_with_circles(self):
        level = self._generate_with_circles()
        assert level is not None
        assert len(level.rooms) >= 3

    def test_has_non_rect_rooms(self):
        level = self._generate_with_circles()
        non_rect = [
            r for r in level.rooms
            if not isinstance(r.shape, RectShape)
        ]
        assert len(non_rect) >= 1

    def test_all_rooms_reachable(self):
        """Every room center must be reachable via flood fill."""
        level = self._generate_with_circles()
        # Find stairs_up as starting point
        start = None
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature == "stairs_up":
                    start = (x, y)
                    break
            if start:
                break
        assert start is not None

        # Flood fill
        visited = set()
        stack = [start]
        while stack:
            fx, fy = stack.pop()
            if (fx, fy) in visited:
                continue
            t = level.tile_at(fx, fy)
            if not t or t.terrain != Terrain.FLOOR:
                continue
            visited.add((fx, fy))
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                stack.append((fx + dx, fy + dy))

        # Every room center must be reachable
        for room in level.rooms:
            cx, cy = room.rect.center
            assert (cx, cy) in visited, (
                f"{room.id} center ({cx},{cy}) not reachable"
            )

    def test_has_doors(self):
        level = self._generate_with_circles()
        door_count = sum(
            1 for row in level.tiles for t in row
            if t.feature and "door" in t.feature
        )
        assert door_count >= 2

    def test_has_stairs(self):
        level = self._generate_with_circles()
        features = {
            t.feature for row in level.tiles for t in row if t.feature
        }
        assert "stairs_up" in features
        assert "stairs_down" in features

    def test_walls_surround_circle_rooms(self):
        """Circle rooms must have WALL tiles around their perimeter."""
        level = self._generate_with_circles()
        for room in level.rooms:
            if not isinstance(room.shape, CircleShape):
                continue
            floor = room.floor_tiles()
            for fx, fy in floor:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = fx + dx, fy + dy
                    if (nx, ny) not in floor:
                        t = level.tile_at(nx, ny)
                        if t:
                            # Should be wall, door, or corridor
                            assert t.terrain in (
                                Terrain.WALL, Terrain.FLOOR,
                            ), (
                                f"Tile ({nx},{ny}) adjacent to "
                                f"{room.id} circle floor is "
                                f"{t.terrain}, expected WALL/FLOOR"
                            )

    def test_multiple_seeds_with_circles(self):
        """Generation with circles works across different seeds."""
        for seed in [1, 42, 99, 12345, 99999]:
            level = self._generate_with_circles(seed=seed)
            assert len(level.rooms) >= 3, f"seed={seed}"

    def test_circle_save_load_roundtrip(self, tmp_path):
        """Circles survive save→load with correct shape type."""
        level = self._generate_with_circles()
        world = World()
        cx, cy = level.rooms[0].rect.center
        pid = world.create_entity({
            "Position": Position(x=cx, y=cy, level_id=level.id),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=8, maximum=8),
            "Player": Player(),
            "Renderable": Renderable(glyph="@", color="white"),
        })

        path = tmp_path / "save.json"
        save_game(world, level, pid, 1, [], save_path=path)
        _, loaded, _, _, _ = load_game(save_path=path)

        for orig, load in zip(level.rooms, loaded.rooms):
            assert orig.shape.type_name == load.shape.type_name, (
                f"{orig.id}: shape {orig.shape.type_name} "
                f"!= loaded {load.shape.type_name}"
            )


class TestRoundedWallGlyphs:
    """Tests for rounded corner wall glyph rendering."""

    def test_wall_glyph_rounded_corners(self):
        set_theme("modern")
        # ┌ (south+east) becomes ╭ when rounded
        assert wall_glyph(False, True, True, False, rounded=False) == "┌"
        assert wall_glyph(False, True, True, False, rounded=True) == "╭"
        # ┐ (south+west) becomes ╮
        assert wall_glyph(False, True, False, True, rounded=False) == "┐"
        assert wall_glyph(False, True, False, True, rounded=True) == "╮"
        # └ (north+east) becomes ╰
        assert wall_glyph(True, False, True, False, rounded=False) == "└"
        assert wall_glyph(True, False, True, False, rounded=True) == "╰"
        # ┘ (north+west) becomes ╯
        assert wall_glyph(True, False, False, True, rounded=False) == "┘"
        assert wall_glyph(True, False, False, True, rounded=True) == "╯"

    def test_wall_glyph_rounded_non_corner_unchanged(self):
        set_theme("modern")
        # Straight lines should not change with rounded=True
        assert wall_glyph(False, False, True, True, rounded=True) == "─"
        assert wall_glyph(True, True, False, False, rounded=True) == "│"
        # T-junctions should not change
        assert wall_glyph(True, True, True, True, rounded=True) == "┼"

    def test_basic_theme_no_rounded(self):
        set_theme("basic")
        # Basic theme has no walls_rounded, so rounded=True still
        # returns the standard ASCII glyph
        assert wall_glyph(False, True, True, False, rounded=True) == "+"
        set_theme("modern")  # reset

    def test_wall_char_at_rounded_for_circle_room(self):
        """_wall_char_at uses rounded corners for circle room walls."""
        set_theme("modern")

        # Build a small level with a circle room
        level = Level.create_empty("t", "t", 1, 15, 15)
        rect = Rect(3, 3, 7, 7)
        shape = CircleShape()
        room = Room(id="r1", rect=rect, shape=shape)
        level.rooms = [room]

        # Carve floor
        for x, y in shape.floor_tiles(rect):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        # Build walls (8-neighbor)
        floor_set = shape.floor_tiles(rect)
        for fx, fy in floor_set:
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    nx, ny = fx + dx, fy + dy
                    if (nx, ny) not in floor_set and level.in_bounds(nx, ny):
                        if level.tiles[ny][nx].terrain == Terrain.VOID:
                            level.tiles[ny][nx] = Tile(terrain=Terrain.WALL)

        # Find a corner wall tile (L-shaped connection)
        # and verify it gets a rounded glyph
        corner_found = False
        for y in range(15):
            for x in range(15):
                if level.tiles[y][x].terrain != Terrain.WALL:
                    continue
                glyph_normal = TerminalRenderer._wall_char_at(
                    level, x, y, rounded=False,
                )
                glyph_rounded = TerminalRenderer._wall_char_at(
                    level, x, y, rounded=True,
                )
                if glyph_normal in ("┌", "┐", "└", "┘"):
                    assert glyph_rounded in ("╭", "╮", "╰", "╯"), (
                        f"Wall at ({x},{y}) with glyph {glyph_normal} "
                        f"should be rounded but got {glyph_rounded}"
                    )
                    corner_found = True

        assert corner_found, "No corner walls found in circle room"
        set_theme("modern")  # reset


class TestShapeSaveLoadBackcompat:
    """Backward compatibility for saves without shape field."""

    def test_old_save_without_shape_loads_rect(self, tmp_path):
        """Saves from before the shape field default to RectShape."""
        data = {
            "version": 1, "turn": 1, "player_id": 1, "next_id": 2,
            "entities": {
                "1": {
                    "Position": {"x": 3, "y": 3, "level_id": "test"},
                    "Player": True,
                }
            },
            "level": {
                "id": "test", "name": "Test", "depth": 1,
                "width": 5, "height": 5,
                "tiles": [
                    [{"terrain": "FLOOR"} for _ in range(5)]
                    for _ in range(5)
                ],
                "rooms": [{
                    "id": "room_1",
                    "rect": {"x": 0, "y": 0, "width": 5, "height": 5},
                    "tags": [], "description": "", "connections": [],
                    # No "shape" key — old format
                }],
                "corridors": [],
                "metadata": {},
            },
            "messages": [],
        }

        path = tmp_path / "old_save.json"
        path.write_text(json.dumps(data))

        _, loaded_level, _, _, _ = load_game(save_path=path)

        room = loaded_level.rooms[0]
        assert isinstance(room.shape, RectShape)
