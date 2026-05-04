"""Tests for the SVG floor renderer."""

import re

from shapely.geometry import Point, box

from nhc.dungeon.model import (
    Level, Rect, RectShape, Room, SurfaceType, Terrain, Tile,
)
from nhc.rendering._dungeon_polygon import _room_shapely_polygon
from nhc.rendering._floor_detail import _render_floor_grid
from nhc.rendering.svg import (
    CELL, FLOOR_STONE_FILL, PADDING,
    render_floor_svg,
)


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
        level.tiles[3][x] = Tile(
            terrain=Terrain.FLOOR, surface_type=SurfaceType.CORRIDOR,
        )

    # Add a closed door at (6,3)
    level.tiles[3][6].feature = "door_closed"

    # Add stairs down at (3,3)
    level.tiles[3][3].feature = "stairs_down"

    return level


class TestSVGOutput:
    def test_produces_valid_svg(self):
        """The SVG envelope is well-formed.

        The Rust SvgPainter prefixes an XML prolog
        (``<?xml ...?>``) before the ``<svg>`` element, so the
        check accepts either an XML or a bare-SVG header.
        """
        level = _make_level()
        svg = render_floor_svg(level)
        assert svg.startswith("<svg") or svg.startswith("<?xml")
        assert "<svg" in svg
        assert svg.rstrip().endswith("</svg>")

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

class TestRoomShapelyPolygon:
    """_room_shapely_polygon must return a polygon for every room type,
    covering the full wall-path area (bounding rect for rect rooms,
    geometric outline for shaped rooms)."""

    def test_rect_room_returns_polygon(self):
        """Rect rooms must produce a polygon, not None."""
        room = Room(id="r1", rect=Rect(3, 7, 8, 6),
                    shape=RectShape())
        poly = _room_shapely_polygon(room)
        assert poly is not None, (
            "_room_shapely_polygon returned None for RectShape")
        assert not poly.is_empty

    def test_rect_polygon_covers_bounding_rect(self):
        """Rect room polygon must cover the full bounding rect in
        pixel coords so the clip path sits at the wall stroke."""
        r = Rect(3, 7, 8, 6)
        room = Room(id="r1", rect=r, shape=RectShape())
        poly = _room_shapely_polygon(room)
        assert poly is not None

        # The polygon must contain the full pixel-space bounding rect
        px, py = r.x * CELL, r.y * CELL
        pw, ph = r.width * CELL, r.height * CELL
        expected = box(px, py, px + pw, py + ph)
        assert poly.contains(expected) or poly.equals(expected), (
            f"Rect room polygon does not cover bounding rect: "
            f"poly bounds={poly.bounds}, expected=({px},{py},"
            f"{px+pw},{py+ph})")

    def test_rect_polygon_wall_tile_inside(self):
        """A WALL tile at (3,10) adjacent to FLOOR at (4,10) must
        be inside the polygon — reproduces the grid clipping bug."""
        room = Room(id="r1", rect=Rect(3, 7, 8, 6),
                    shape=RectShape())
        poly = _room_shapely_polygon(room)
        assert poly is not None

        # Center of tile (3,10) in pixel coords
        tile_center = Point(3 * CELL + CELL / 2,
                            10 * CELL + CELL / 2)
        assert poly.contains(tile_center), (
            f"WALL tile (3,10) center not inside polygon — "
            f"grid/detail would be clipped")


class TestGridAndDetailOnWallTiles:
    """Grid and detail rendering must process all tiles (including
    WALL), relying on the dungeon polygon clip to hide exterior."""

    def _make_walled_level(self):
        """Level with WALL tiles surrounding FLOOR tiles,
        mimicking room #0 from seed99_shapes at tile (3,10)."""
        level = Level.create_empty("t", "T", depth=1,
                                   width=12, height=15)
        r = Rect(3, 7, 8, 6)
        room = Room(id="r1", rect=r, shape=RectShape())
        level.rooms.append(room)
        # Fill bounding rect: WALL border, FLOOR interior
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                on_edge = (x == r.x or x == r.x2 - 1
                           or y == r.y or y == r.y2 - 1)
                level.tiles[y][x] = Tile(
                    terrain=Terrain.WALL if on_edge
                    else Terrain.FLOOR)
        return level

    def test_grid_processes_all_tiles(self):
        """Grid must generate segments for every tile in the level,
        not filter by _is_floor/_is_door.  Verify by counting: a
        full room should produce edges for WALL tiles too."""
        level = self._make_walled_level()
        svg_parts: list[str] = []
        _render_floor_grid(svg_parts, level)
        joined = "".join(svg_parts)
        # Count M (move-to) = one per grid segment
        seg_count = joined.count("M")
        r = level.rooms[0].rect
        # All tiles in bounding rect: 8x6=48 tiles.
        # Each interior tile contributes right+bottom edges.
        # With all-tile processing, minimum edges =
        #   right edges: (w-1)*h = 7*6 = 42
        #   bottom edges: w*(h-1) = 8*5 = 40  -> total 82
        # within the room rect alone.
        # With floor-only filtering, WALL border tiles (20 tiles)
        # contribute far fewer edges.
        min_expected = (r.width - 1) * r.height + r.width * (r.height - 1)
        assert seg_count >= min_expected, (
            f"Grid produced {seg_count} segments, expected >= "
            f"{min_expected} (all tiles in room rect processed)")

class TestSecretDoorGridRouting:
    """Secret doors sit on the wall line between rooms, outside
    the dungeon polygon used by grid-clip. Their grid edges must
    therefore be routed into the unclipped (corridor) bucket —
    the same treatment visible doors get — otherwise the south
    edge of a secret door lands exactly on the clip boundary and
    the 0.3-px stroke is half-clipped to invisibility."""

    def _rect_room_with_secret_door(self):
        level = Level.create_empty("t", "T", depth=1,
                                   width=10, height=10)
        r = Rect(3, 4, 4, 4)
        room = Room(id="r1", rect=r, shape=RectShape())
        level.rooms.append(room)
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        # Secret door on the room's north edge at (4, 4).
        level.tiles[4][4] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_secret",
            door_side="north",
        )
        return level

    def test_secret_door_emits_unclipped_grid_bucket(self):
        level = self._rect_room_with_secret_door()
        dungeon_poly = _room_shapely_polygon(level.rooms[0])
        svg_parts: list[str] = []
        _render_floor_grid(svg_parts, level, dungeon_poly)
        joined = "".join(svg_parts)
        # Strip the clipPath definition — its inner <path> is
        # geometry for the clip, not a grid path.
        body = re.sub(r"<clipPath.*?</clipPath>", "", joined,
                      flags=re.DOTALL)
        path_count = body.count("<path ")
        clipped_count = body.count(
            'clip-path="url(#grid-clip)"')
        # The level has no corridors and no visible doors, so
        # the only source of an unclipped grid path is the
        # secret door bucket.
        assert path_count - clipped_count >= 1, (
            "secret-door grid segments must be emitted into an "
            "unclipped <path> so they render past the dungeon "
            f"clip boundary; saw {path_count} paths, "
            f"{clipped_count} clipped, body:\n{body}"
        )
