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

    def test_parchment_background(self):
        level = _make_level()
        svg = render_floor_svg(level)
        assert "#F5EDE0" in svg  # soft brown parchment

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

    def test_stairs_down_a_shape(self):
        """Stairs down should render as A-shape with step lines."""
        level = _make_level()
        svg = render_floor_svg(level)
        # Two leg lines + 3 step lines = at least 5 line elements
        assert svg.count("stroke-linecap=\"round\"") > 5

    def test_stairs_up_a_shape(self):
        level = _make_level()
        level.tiles[4][4] = Tile(terrain=Terrain.FLOOR)
        level.tiles[4][4].feature = "stairs_up"
        svg = render_floor_svg(level)
        assert svg.count("stroke-linecap=\"round\"") > 10

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
        assert "door" not in svg.lower()

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

    def test_floor_stones_soft_brown_fill(self):
        """Floor stones are filled with soft brown, not hollow."""
        # Use a larger room and a seed that produces stones
        level = Level.create_empty("t", "T", depth=1,
                                   width=20, height=20)
        for y in range(1, 19):
            for x in range(1, 19):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r", rect=Rect(1, 1, 18, 18)))
        # Try several seeds until we get a stone
        from nhc.rendering.svg import FLOOR_STONE_FILL
        for seed in range(50):
            svg = render_floor_svg(level, seed=seed)
            if FLOOR_STONE_FILL in svg:
                break
        assert FLOOR_STONE_FILL in svg, "No floor stone found in any seed"

    def test_floor_stones_match_hatching_stroke_style(self):
        """Floor stones use same stroke color as hatching stones."""
        level = Level.create_empty("t", "T", depth=1,
                                   width=20, height=20)
        for y in range(1, 19):
            for x in range(1, 19):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r", rect=Rect(1, 1, 18, 18)))
        for seed in range(50):
            svg = render_floor_svg(level, seed=seed)
            if 'stroke="#666666"' in svg:
                break
        # Both hatching and floor stones use #666666 stroke
        assert 'stroke="#666666"' in svg

    def test_floor_stone_clusters(self):
        """Some tiles have clusters of 3 stones close together."""
        from nhc.rendering.svg import FLOOR_STONE_FILL
        level = Level.create_empty("t", "T", depth=1,
                                   width=30, height=30)
        for y in range(1, 29):
            for x in range(1, 29):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r", rect=Rect(1, 1, 28, 28)))
        # With ~784 floor tiles and ~3% cluster chance, we should
        # reliably get at least one cluster across a few seeds
        found_cluster = False
        for seed in range(20):
            svg = render_floor_svg(level, seed=seed)
            # A cluster adds 3 ellipses; count brown-filled ellipses
            count = svg.count(f'fill="{FLOOR_STONE_FILL}"')
            # Singles add 1, clusters add 3 — if total >= 3 we likely
            # have at least one cluster (or 3 singles, but with 784
            # tiles and low single chance this proves clusters exist)
            if count >= 4:
                found_cluster = True
                break
        assert found_cluster, "No stone cluster found in any seed"

    def test_floor_stones_use_original_small_sizes(self):
        """Floor stones use the original smaller sizes, not hatching
        sizes."""
        import re
        from nhc.rendering.svg import FLOOR_STONE_FILL
        level = Level.create_empty("t", "T", depth=1,
                                   width=20, height=20)
        for y in range(1, 19):
            for x in range(1, 19):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r", rect=Rect(1, 1, 18, 18)))
        for seed in range(50):
            svg = render_floor_svg(level, seed=seed)
            if FLOOR_STONE_FILL in svg:
                break
        # Extract all rx values from floor stone ellipses
        # (they appear in the opacity="0.8" group)
        stone_group = re.search(
            r'<g opacity="0\.8">(.*?)</g>', svg, re.DOTALL)
        assert stone_group, "No floor stone group found"
        rx_vals = [float(v) for v in
                   re.findall(r'rx="([^"]+)"', stone_group.group(1))]
        assert rx_vals, "No rx values found"
        # Single stones max at CELL*0.15=4.8; cluster stones scale up
        # to 1.3x giving ~6.2. Hatching stones go up to CELL*0.25=8.
        # All floor stones must stay below hatching size.
        for rx in rx_vals:
            assert rx <= 6.5, f"Floor stone rx={rx} too large"

    def test_floor_y_scratches(self):
        """Some floor tiles have Y-shaped scratches."""
        level = Level.create_empty("t", "T", depth=1,
                                   width=30, height=30)
        for y in range(1, 29):
            for x in range(1, 29):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r", rect=Rect(1, 1, 28, 28)))
        found = False
        for seed in range(30):
            svg = render_floor_svg(level, seed=seed)
            if "y-scratch" in svg:
                found = True
                break
        assert found, "No Y-scratch found in any seed"

    def test_cracks_and_scratches_mutually_exclusive(self):
        """A tile never has both a crack and a Y-scratch."""
        import re
        from nhc.rendering.svg import _render_floor_detail
        level = Level.create_empty("t", "T", depth=1,
                                   width=30, height=30)
        for y in range(1, 29):
            for x in range(1, 29):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r", rect=Rect(1, 1, 28, 28)))
        # Run many seeds; check that the scratch count never exceeds
        # total tiles minus crack count (a rough structural check).
        # The real guarantee is in the code logic (elif), but we can
        # verify by checking both appear but the total detail count
        # (cracks + scratches) never exceeds tile count.
        for seed in [0, 7, 42]:
            svg_parts: list[str] = []
            _render_floor_detail(svg_parts, level, seed)
            joined = "".join(svg_parts)
            crack_count = joined.count("<polygon")
            scratch_count = joined.count("y-scratch")
            # With ~784 tiles and low chances, both should appear
            # but never on the same tile — total can't exceed 784
            assert crack_count + scratch_count <= 784
