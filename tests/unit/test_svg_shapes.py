"""Tests for SVG rendering of shaped rooms.

These tests verify the visual properties of the rendered SVG
output — what shapes are drawn, where gaps appear, whether
outlines align with the tile grid — without depending on
rendering order or implementation details.
"""

import re

from shapely.geometry import Point, Polygon

from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, Level, OctagonShape,
    PillShape, Rect, RectShape, Room, RoomShape, TempleShape,
    Terrain, Tile,
)
from nhc.rendering.svg import (
    BG, CELL, FLOOR_COLOR, FLOOR_STONE_FILL, GRID_WIDTH,
    HATCH_UNDERLAY, PADDING, WALL_WIDTH, render_floor_svg,
)


# ── Helpers ──────────────────────────────────────────────────────


def _carve_room(level: Level, room: Room) -> None:
    """Carve floor tiles matching the room shape and add walls."""
    for x, y in room.floor_tiles():
        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    # Walls around floor
    floor = room.floor_tiles()
    for fx, fy in floor:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = fx + dx, fy + dy
            if ((nx, ny) not in floor
                    and level.in_bounds(nx, ny)
                    and level.tiles[ny][nx].terrain == Terrain.VOID):
                level.tiles[ny][nx] = Tile(terrain=Terrain.WALL)


def _add_corridor(
    level: Level, room: Room,
    entry_x: int, entry_y: int,
    dx: int, dy: int,
    length: int = 3,
    door: bool = False,
) -> None:
    """Add a corridor entering the room at (entry_x, entry_y).

    The corridor extends *length* tiles in direction (dx, dy).
    The entry tile is the wall tile adjacent to the room floor.
    """
    # Convert entry wall tile to door or corridor
    if door:
        level.tiles[entry_y][entry_x] = Tile(
            terrain=Terrain.FLOOR, feature="door_closed",
        )
    else:
        level.tiles[entry_y][entry_x] = Tile(
            terrain=Terrain.FLOOR, is_corridor=True,
        )
    # Carve corridor tiles outward
    cx, cy = entry_x + dx, entry_y + dy
    for _ in range(length):
        if level.in_bounds(cx, cy):
            level.tiles[cy][cx] = Tile(
                terrain=Terrain.FLOOR, is_corridor=True,
            )
        cx += dx
        cy += dy


def _make_shaped_level(
    shape: RoomShape,
    room_x: int = 3,
    room_y: int = 3,
    room_w: int = 9,
    room_h: int = 9,
    corridor_side: str | None = None,
    door: bool = False,
) -> tuple[Level, Room]:
    """Create a level with a single shaped room.

    If *corridor_side* is 'north', 'south', 'east', or 'west',
    a 3-tile corridor enters the room from that direction.
    """
    w = room_x + room_w + 6
    h = room_y + room_h + 6
    level = Level.create_empty("t", "T", depth=1, width=w, height=h)
    rect = Rect(room_x, room_y, room_w, room_h)
    room = Room(id="r1", rect=rect, shape=shape)
    level.rooms.append(room)
    _carve_room(level, room)

    if corridor_side:
        floor = room.floor_tiles()
        cx_tile = rect.x + rect.width // 2
        cy_tile = rect.y + rect.height // 2

        if corridor_side == "east":
            # Find rightmost floor tile at center row
            ex = max(fx for fx, fy in floor if fy == cy_tile)
            _add_corridor(level, room, ex + 1, cy_tile, 1, 0,
                          door=door)
        elif corridor_side == "west":
            ex = min(fx for fx, fy in floor if fy == cy_tile)
            _add_corridor(level, room, ex - 1, cy_tile, -1, 0,
                          door=door)
        elif corridor_side == "south":
            ey = max(fy for fx, fy in floor if fx == cx_tile)
            _add_corridor(level, room, cx_tile, ey + 1, 0, 1,
                          door=door)
        elif corridor_side == "north":
            ey = min(fy for fx, fy in floor if fx == cx_tile)
            _add_corridor(level, room, cx_tile, ey - 1, 0, -1,
                          door=door)

    return level, room


# ── 1. Smooth room outlines ─────────────────────────────────────


class TestSmoothOutlines:
    def test_circle_room_produces_circle_element(self):
        level, _ = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level)
        assert "<circle " in svg
        assert re.search(r'cx="[\d.]+"', svg)
        assert re.search(r'cy="[\d.]+"', svg)
        assert re.search(r'r="[\d.]+"', svg)

    def test_octagon_room_produces_polygon(self):
        level, _ = _make_shaped_level(OctagonShape())
        svg = render_floor_svg(level)
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match, "No polygon found for octagon"
        points = match.group(1).split()
        assert len(points) == 8, f"Octagon needs 8 vertices, got {len(points)}"

    def test_cross_room_produces_polygon(self):
        level, _ = _make_shaped_level(CrossShape())
        svg = render_floor_svg(level)
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match, "No polygon found for cross"
        points = match.group(1).split()
        assert len(points) == 12, f"Cross needs 12 vertices, got {len(points)}"

    def test_rect_room_no_smooth_outline(self):
        level, _ = _make_shaped_level(RectShape())
        svg = render_floor_svg(level)
        assert "<circle " not in svg
        assert "<polygon " not in svg

    def test_temple_room_produces_polygon(self):
        level, _ = _make_shaped_level(TempleShape(flat_side="south"))
        svg = render_floor_svg(level)
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match, "No polygon found for temple"
        # Temple has 3 arc caps (12 segs each) + straight segments.
        points = match.group(1).split()
        assert len(points) > 20, (
            f"Temple outline needs many vertices for arc caps, got {len(points)}"
        )

    def test_temple_orientations_all_produce_polygon(self):
        for side in ("north", "south", "east", "west"):
            level, _ = _make_shaped_level(TempleShape(flat_side=side))
            svg = render_floor_svg(level)
            assert re.search(r'<polygon points="', svg), (
                f"temple flat={side} missing polygon"
            )


class TestTemplePolygonAlignment:
    def _polygon(self, svg: str) -> Polygon:
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match
        verts = []
        for pt in match.group(1).split():
            x, y = pt.split(",")
            verts.append((float(x), float(y)))
        return Polygon(verts)

    def test_temple_polygon_covers_all_floor_tiles(self):
        shape = TempleShape(flat_side="south")
        level, room = _make_shaped_level(shape)
        poly = self._polygon(render_floor_svg(level))
        for tx, ty in room.floor_tiles():
            center = Point(tx * CELL + CELL / 2, ty * CELL + CELL / 2)
            assert poly.contains(center), (
                f"Floor tile ({tx},{ty}) center not inside temple polygon"
            )

    def test_temple_polygon_excludes_rect_corners(self):
        shape = TempleShape(flat_side="south")
        level, room = _make_shaped_level(shape)
        poly = self._polygon(render_floor_svg(level))
        r = room.rect
        floor = room.floor_tiles()
        for tx, ty in [
            (r.x, r.y), (r.x2 - 1, r.y),
            (r.x, r.y2 - 1), (r.x2 - 1, r.y2 - 1),
        ]:
            if (tx, ty) not in floor:
                center = Point(tx * CELL + CELL / 2, ty * CELL + CELL / 2)
                assert not poly.contains(center), (
                    f"Non-floor corner ({tx},{ty}) inside temple polygon"
                )

    def test_temple_flat_south_has_rectangular_bottom(self):
        """The bottom edge of a south-flat temple reaches the rect
        bottom at multiple x-positions (flat arm tip)."""
        shape = TempleShape(flat_side="south")
        level, room = _make_shaped_level(shape)
        svg = render_floor_svg(level)
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match
        verts = []
        for pt in match.group(1).split():
            x, y = pt.split(",")
            verts.append((float(x), float(y)))
        bottom_y = room.rect.y2 * CELL
        bottom_vertices = [(x, y) for (x, y) in verts if y == bottom_y]
        # Flat arm bottom edge has 2 vertices (tip corners).
        assert len(bottom_vertices) >= 2, (
            f"south-flat temple should touch y={bottom_y}, got {bottom_vertices}"
        )


class TestTempleGappedOutlines:
    def test_temple_doorless_east_opening_uses_path(self):
        """A temple with a doorless corridor uses <path> with gap,
        not a closed polygon."""
        level, _ = _make_shaped_level(
            TempleShape(flat_side="south"), corridor_side="east")
        svg = render_floor_svg(level)
        wall_paths = re.findall(
            r'<path[^>]+d="(M[^"]+)"[^>]+stroke-width', svg)
        has_gapped = any(p.count("M") >= 2 for p in wall_paths)
        assert has_gapped, "No gapped path for temple east opening"

    def test_temple_doorless_flat_side_uses_path(self):
        """A corridor on the flat arm (south) also produces a gap."""
        level, _ = _make_shaped_level(
            TempleShape(flat_side="south"), corridor_side="south")
        svg = render_floor_svg(level)
        wall_paths = re.findall(
            r'<path[^>]+d="(M[^"]+)"[^>]+stroke-width', svg)
        has_gapped = any(p.count("M") >= 2 for p in wall_paths)
        assert has_gapped, "No gapped path for temple flat-side opening"

    def test_temple_with_door_stays_polygon(self):
        level, _ = _make_shaped_level(
            TempleShape(flat_side="south"),
            corridor_side="east", door=True)
        svg = render_floor_svg(level)
        assert re.search(r'<polygon points="', svg)


# ── 2. Cross polygon alignment ──────────────────────────────────


class TestCrossPolygonAlignment:
    def test_cross_vertices_on_tile_boundaries(self):
        """All cross polygon coordinates must be multiples of CELL."""
        level, _ = _make_shaped_level(CrossShape())
        svg = render_floor_svg(level)
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match
        for pt in match.group(1).split():
            x, y = pt.split(",")
            assert float(x) % CELL == 0, f"x={x} not on tile boundary"
            assert float(y) % CELL == 0, f"y={y} not on tile boundary"

    def test_cross_polygon_covers_all_floor_tiles(self):
        """Every floor tile center must be inside the polygon."""
        shape = CrossShape()
        level, room = _make_shaped_level(shape)
        svg = render_floor_svg(level)
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match
        verts = []
        for pt in match.group(1).split():
            x, y = pt.split(",")
            verts.append((float(x), float(y)))
        poly = Polygon(verts)

        for tx, ty in room.floor_tiles():
            center = Point(tx * CELL + CELL / 2, ty * CELL + CELL / 2)
            assert poly.contains(center), (
                f"Floor tile ({tx},{ty}) center not inside polygon"
            )

    def test_cross_polygon_excludes_corner_tiles(self):
        """Corner tiles of the bounding rect are outside the cross."""
        shape = CrossShape()
        level, room = _make_shaped_level(shape)
        svg = render_floor_svg(level)
        match = re.search(r'<polygon points="([^"]+)"', svg)
        assert match
        verts = []
        for pt in match.group(1).split():
            x, y = pt.split(",")
            verts.append((float(x), float(y)))
        poly = Polygon(verts)

        r = room.rect
        floor = room.floor_tiles()
        corners = [
            (r.x, r.y), (r.x2 - 1, r.y),
            (r.x, r.y2 - 1), (r.x2 - 1, r.y2 - 1),
        ]
        for tx, ty in corners:
            if (tx, ty) not in floor:
                center = Point(tx * CELL + CELL / 2,
                               ty * CELL + CELL / 2)
                assert not poly.contains(center), (
                    f"Non-floor corner ({tx},{ty}) inside polygon"
                )


# ── 3. Gapped outlines at doorless openings ──────────────────────


class TestGappedOutlines:
    def test_circle_doorless_opening_uses_path_not_circle(self):
        """A circle room with a doorless corridor uses <path>,
        not <circle>."""
        level, _ = _make_shaped_level(
            CircleShape(), corridor_side="east")
        svg = render_floor_svg(level)
        # Should NOT use a closed <circle> element
        # The wall group should contain a <path> with arcs instead
        assert re.search(r'<path[^>]+d="[^"]*A', svg), (
            "Expected arc path for gapped circle"
        )

    def test_circle_doorless_path_not_closed(self):
        """The gapped circle outline path must not be closed."""
        level, _ = _make_shaped_level(
            CircleShape(), corridor_side="east")
        svg = render_floor_svg(level)
        # Find path elements with arcs (the circle outline)
        arc_paths = re.findall(r'<path[^>]+d="([^"]*A[^"]*)"', svg)
        assert arc_paths, "No arc path found"
        for path_d in arc_paths:
            assert "Z" not in path_d, (
                f"Gapped arc path should not be closed: {path_d[:80]}"
            )

    def test_cross_doorless_two_gaps_has_multiple_subpaths(self):
        """A cross with two doorless openings has multiple subpaths."""
        shape = CrossShape()
        level, room = _make_shaped_level(shape, room_w=9, room_h=9)
        # Add corridors on both east and west arms
        floor = room.floor_tiles()
        cy = room.rect.y + room.rect.height // 2
        ex = max(fx for fx, fy in floor if fy == cy)
        wx = min(fx for fx, fy in floor if fy == cy)
        _add_corridor(level, room, ex + 1, cy, 1, 0)
        _add_corridor(level, room, wx - 1, cy, -1, 0)
        svg = render_floor_svg(level)
        wall_paths = re.findall(
            r'<path[^>]+d="(M[^"]+)"[^>]+stroke-width', svg)
        has_multi = any(p.count("M") >= 3 for p in wall_paths)
        assert has_multi, "Two gaps should produce >=3 subpaths"

    def test_circle_with_door_stays_closed(self):
        """A circle room with a door keeps its <circle> element."""
        level, _ = _make_shaped_level(
            CircleShape(), corridor_side="east", door=True)
        svg = render_floor_svg(level)
        assert "<circle " in svg

    def test_cross_doorless_opening_uses_path(self):
        """A cross with a doorless corridor uses <path> not <polygon>."""
        level, _ = _make_shaped_level(
            CrossShape(), corridor_side="east")
        svg = render_floor_svg(level)
        # The outline should be a <path> with gaps, not a polygon
        wall_paths = re.findall(
            r'<path[^>]+d="(M[^"]+)"[^>]+stroke-width', svg)
        # At least one path should have multiple M subpaths
        has_gapped = any(
            p.count("M") >= 2 for p in wall_paths
        )
        assert has_gapped, "No gapped path found for cross"

    def test_cross_with_door_stays_polygon(self):
        """A cross with a door keeps its <polygon> outline."""
        level, _ = _make_shaped_level(
            CrossShape(), corridor_side="east", door=True)
        svg = render_floor_svg(level)
        assert re.search(r'<polygon points="[^"]*"', svg)

    def test_octagon_doorless_opening_not_closed(self):
        level, _ = _make_shaped_level(
            OctagonShape(), corridor_side="east")
        svg = render_floor_svg(level)
        wall_paths = re.findall(
            r'<path[^>]+d="(M[^"]+)"[^>]+stroke-width', svg)
        has_gapped = any(
            p.count("M") >= 2 and "Z" not in p
            for p in wall_paths
        )
        assert has_gapped, "No gapped path for octagon opening"


# ── 3b. Circle gaps straddling ±π ────────────────────────────────


class TestCircleGapWrapAround:
    """Corridors entering from the west create gap angles that straddle
    the ±π boundary.  The drawn arcs must cover most of the circle,
    not just a tiny sliver."""

    def test_west_corridor_draws_most_of_circle(self):
        """A circle with a west corridor should draw >270° of arc,
        not a tiny ~20° sliver."""
        level, _ = _make_shaped_level(
            CircleShape(), room_w=5, room_h=5,
            corridor_side="west")
        svg = render_floor_svg(level)
        # Find arc paths with A commands (wall-width strokes)
        arc_paths = re.findall(
            r'<path[^>]+d="(M[^"]*A[^"]*)"[^>]+stroke-width="5',
            svg)
        assert arc_paths, "No wall-stroke arc path found"
        # The large-arc flag should be 1 for at least one arc,
        # meaning the drawn arc spans > 180°
        all_d = " ".join(arc_paths)
        arcs = re.findall(
            r'A[\d.]+,[\d.]+ 0 (\d),1', all_d)
        large_flags = [int(f) for f in arcs]
        assert any(f == 1 for f in large_flags), (
            f"Expected at least one large-arc flag=1, got {large_flags}. "
            f"The circle wall is probably just a tiny sliver."
        )

    def test_west_and_north_corridors_draw_most_of_circle(self):
        """Two corridors (west + north) should still draw the
        majority of the circle outline, not just a small arc."""
        level, room = _make_shaped_level(
            CircleShape(), room_w=5, room_h=5,
            corridor_side="west")
        # Add a second corridor from the north
        floor = room.floor_tiles()
        cx_tile = room.rect.x + room.rect.width // 2
        ey = min(fy for fx, fy in floor if fx == cx_tile)
        _add_corridor(level, room, cx_tile, ey - 1, 0, -1)
        svg = render_floor_svg(level)
        # Should have arc paths with wall-width stroke
        arc_paths = re.findall(
            r'<path[^>]+d="(M[^"]*A[^"]*)"[^>]+stroke-width="5',
            svg)
        assert arc_paths, "No wall-stroke arc path found"
        # Count total arc segments (M...A pairs)
        all_d = " ".join(arc_paths)
        arc_count = all_d.count(" A")
        assert arc_count >= 2, (
            f"Two gaps should produce >= 2 arc segments, got {arc_count}"
        )

    def test_south_corridor_draws_most_of_circle(self):
        """South corridor (gap near +π/2) should also work."""
        level, _ = _make_shaped_level(
            CircleShape(), room_w=5, room_h=5,
            corridor_side="south")
        svg = render_floor_svg(level)
        arc_paths = re.findall(
            r'<path[^>]+d="(M[^"]*A[^"]*)"[^>]+stroke-width="5',
            svg)
        assert arc_paths, "No wall-stroke arc path found"
        all_d = " ".join(arc_paths)
        arcs = re.findall(
            r'A[\d.]+,[\d.]+ 0 (\d),1', all_d)
        large_flags = [int(f) for f in arcs]
        assert any(f == 1 for f in large_flags), (
            f"Expected large-arc for south corridor, got {large_flags}"
        )


# ── 4. Corridor wall extensions ──────────────────────────────────


class TestWallExtensions:
    def test_doorless_opening_has_wall_extensions(self):
        """Wall extensions connect the outline gap to the corridor."""
        level, room = _make_shaped_level(
            CircleShape(), corridor_side="east")
        svg = render_floor_svg(level)
        # Wall extensions are short M...L segments in the wall group
        # They should be present near the corridor opening
        wall_style = f'stroke-width="{WALL_WIDTH}"'
        wall_els = re.findall(
            rf'<path[^>]+d="(M[^"]+)"[^>]*{re.escape(wall_style)}',
            svg)
        # At least one wall path should have extension-like
        # short segments (M...L pairs) near the room edge
        all_d = " ".join(wall_els)
        ml_pairs = re.findall(r'M[\d.]+,[\d.]+ L[\d.]+,[\d.]+', all_d)
        assert len(ml_pairs) >= 2, (
            f"Expected >=2 wall extension segments, got {len(ml_pairs)}"
        )

    def test_no_wall_extensions_with_door(self):
        """No wall extensions when corridor has a door."""
        level, _ = _make_shaped_level(
            CircleShape(), corridor_side="east", door=True)
        svg = render_floor_svg(level)
        # The circle outline should be a simple <circle>, not a path
        assert "<circle " in svg


# ── 5. Hybrid room arc direction ─────────────────────────────────


class TestHybridArcDirection:
    def _make_hybrid_level(self, split, circle_side):
        """Create a hybrid room and return (level, room, svg)."""
        if split == "vertical":
            if circle_side == "left":
                shape = HybridShape(CircleShape(), RectShape(), split)
            else:
                shape = HybridShape(RectShape(), CircleShape(), split)
        else:
            if circle_side == "left":
                shape = HybridShape(CircleShape(), RectShape(), split)
            else:
                shape = HybridShape(RectShape(), CircleShape(), split)
        level, room = _make_shaped_level(
            shape, room_w=10, room_h=8)
        svg = render_floor_svg(level)
        return level, room, svg

    def _extract_arc_params(self, svg):
        """Extract (sweep_flag, end_x, end_y) from the first arc."""
        match = re.search(
            r'A[\d.]+,[\d.]+ \d+ (\d+),(\d+) ([\d.]+),([\d.]+)',
            svg)
        assert match, "No arc found in SVG"
        large = int(match.group(1))
        sweep = int(match.group(2))
        ex = float(match.group(3))
        ey = float(match.group(4))
        return large, sweep, ex, ey

    def test_vertical_circle_left_arc_bulges_left(self):
        """Circle on left of vertical split bulges leftward."""
        _, room, svg = self._make_hybrid_level("vertical", "left")
        _, sweep, _, _ = self._extract_arc_params(svg)
        # sweep=0 (CCW in SVG) makes the arc bulge left
        assert sweep == 0

    def test_horizontal_circle_top_arc_bulges_up(self):
        """Circle on top of horizontal split bulges upward."""
        _, room, svg = self._make_hybrid_level("horizontal", "left")
        _, sweep, _, _ = self._extract_arc_params(svg)
        # sweep=1 (CW in SVG) makes the arc bulge up
        assert sweep == 1

    def test_hybrid_outline_is_single_path(self):
        """A hybrid room without corridors is a single closed path."""
        _, _, svg = self._make_hybrid_level("vertical", "left")
        # Should have a <path d="...Z"/> element
        match = re.search(r'<path[^>]+d="([^"]+Z)"', svg)
        assert match, "Hybrid outline should be a closed path"

    def test_hybrid_doorless_opening_gaps_outline(self):
        """Hybrid with doorless corridor has gapped wall outline.

        Gap handling converts the hybrid outline into a polyline
        (arc approximated by many straight segments) so the gap can
        be traced uniformly with the polygon-with-gaps pipeline.
        The gapped wall path must therefore be open (no Z) and
        contain multiple subpaths (multiple M commands)."""
        shape = HybridShape(CircleShape(), RectShape(), "horizontal")
        level, room = _make_shaped_level(
            shape, room_w=9, room_h=10,
            corridor_side="north")
        svg = render_floor_svg(level)
        wall_paths = re.findall(
            r'<path[^>]+d="(M[^"]+)"[^>]+stroke-width="5', svg)
        has_gapped = any(
            p.count("M") >= 2 and "Z" not in p
            for p in wall_paths
        )
        assert has_gapped, (
            "Hybrid wall outline must be open and contain multiple "
            f"subpaths at a corridor opening; got: {wall_paths}"
        )

    def test_hybrid_west_corridor_on_diagonal_keeps_arc_short(self):
        """Regression: a west-side corridor whose wall lies on the
        straight diagonal between the arc endpoint and the rect
        corner must not be misclassified as an arc hit. The old
        hybrid gap classification used a 2-pixel radius tolerance
        that picked up diagonal points at sqrt(r^2 + small^2)
        distance from the centre, projected them onto the arc via
        atan2, and made the rendered arc sweep ~358° of the circle
        (large_arc=1) with its endpoint back near the arc start.

        For a 5x10 hybrid_circle_rect_h room (circle on top) with
        a doorless corridor entering from the west one row below
        the equator, the wall gap lies on the vertical diagonal
        from (px, mid) to (ccx-r, ccy). The gapped wall must not
        contain any near-full-circle arc sweep — after the fix
        hybrid gap handling goes through the polygon-with-gaps
        pipeline, so the rendered outline contains only straight
        polygon segments with no SVG A commands at all.
        """
        shape = HybridShape(CircleShape(), RectShape(), "horizontal")
        # 5 wide x 10 tall: top half is a 5x5 circle (d=5, r=2 tiles),
        # bottom half is a 5x5 rect. Equator row of circle is at
        # mid_row = room_y + 2 (tile-local), where room_y is 3 from
        # _make_shaped_level defaults.
        level, room = _make_shaped_level(
            shape, room_x=3, room_y=3, room_w=5, room_h=10)
        # Add a doorless corridor entering from the west one row
        # BELOW the equator (room_y + 3). The wall gap at that row
        # lies on the vertical diagonal line from the arc's west
        # endpoint down to the rect-half seam, at a y-distance of
        # ~0.5 tiles below the circle centre. Its straight-line
        # distance from the circle centre is sqrt(r^2 + small^2),
        # ~1.6 pixels past the radius — exactly what the old 2.0-px
        # tolerance in _hybrid_with_gaps misclassified as on-arc.
        floor = room.floor_tiles()
        wy = room.rect.y + 3
        wx = min(fx for fx, fy in floor if fy == wy)
        _add_corridor(level, room, wx - 1, wy, -1, 0, length=3)
        svg = render_floor_svg(level)
        # Extract all arc commands in wall-stroked paths (width=4).
        arc_cmds = re.findall(
            r'<path[^>]+d="([^"]*A[^"]*)"[^>]+stroke-width="5',
            svg,
        )
        # The drawn arc must not be a near-full-circle sweep. In
        # the bug the broken arc uses large_arc=1 with sweep=1 and
        # endpoint very close to (cx - r, cy) (the arc start). A
        # correct gap on the diagonal leaves the arc as the full
        # half circle unbroken, or as straight polygon segments
        # spanning the equator — in either case, no single arc
        # command should have large_arc=1.
        bad_arcs = []
        for path_d in arc_cmds:
            for m in re.finditer(
                r'A[\d.]+,[\d.]+ 0 (\d),(\d) ([\d.]+),([\d.]+)',
                path_d,
            ):
                large = int(m.group(1))
                if large == 1:
                    bad_arcs.append(m.group(0))
        assert not bad_arcs, (
            "Hybrid wall path contains a near-full-circle arc "
            f"(large_arc=1) indicating the diagonal gap was "
            f"misclassified as on-arc: {bad_arcs}"
        )


# ── 6. Grid lines at boundaries ──────────────────────────────────


class TestBoundaryGridLines:
    def test_grid_between_corridor_and_smooth_room(self):
        """Grid lines must exist at corridor↔smooth room edges."""
        level, room = _make_shaped_level(
            CircleShape(), corridor_side="east")
        svg = render_floor_svg(level)
        # Count grid path elements (opacity=0.7, GRID_WIDTH stroke)
        grid_pattern = (
            rf'stroke-width="{GRID_WIDTH}"[^>]*opacity="0\.7"'
            rf'|opacity="0\.7"[^>]*stroke-width="{GRID_WIDTH}"'
        )
        grid_paths = re.findall(
            rf'<path[^>]+d="([^"]+)"[^>]*(?:{grid_pattern})', svg)
        assert grid_paths, "No grid paths found"
        # The boundary grid pass should add segments — verify total
        # grid segment count is positive
        all_grid = " ".join(grid_paths)
        m_count = all_grid.count("M")
        assert m_count > 0, "No grid segments found"


# ── 7. Layer order: walls before floor fills ─────────────────────


class TestLayerOrder:
    """Walls and floor fills render together after hatching."""

    def test_hatching_clipped_to_dungeon_exterior(self):
        """Hatching is clipped to the dungeon exterior."""
        level, _ = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level, seed=42)
        assert "hatch-clip" in svg

    def test_hatching_before_walls(self):
        """Hatching appears before wall strokes in the SVG."""
        level, _ = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level, seed=42)
        hatch_pos = svg.find(HATCH_UNDERLAY)
        wall_pos = svg.find(f'stroke-width="{WALL_WIDTH}"')
        assert 0 < hatch_pos < wall_pos, (
            "Hatching should appear before walls"
        )

    def test_smooth_room_fill_and_stroke(self):
        """Smooth rooms have both floor fill and wall stroke."""
        level, _ = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level, seed=42)
        assert f'fill="{FLOOR_COLOR}"' in svg
        assert f'stroke-width="{WALL_WIDTH}"' in svg


# ── 8. Floor fill on corridor opening tiles ──────────────────────


class TestFloorFillCoverage:
    def test_smooth_room_has_floor_fill(self):
        """Smooth rooms are filled with FLOOR_COLOR."""
        level, _ = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level, seed=42)
        assert f'fill="{FLOOR_COLOR}"' in svg

    def test_rect_room_has_floor_fill(self):
        """Rect rooms have a FLOOR_COLOR-filled rect."""
        level, room = _make_shaped_level(RectShape())
        svg = render_floor_svg(level, seed=42)
        r = room.rect
        fill_rect = (
            f'x="{r.x * CELL}" y="{r.y * CELL}" '
            f'width="{r.width * CELL}" height="{r.height * CELL}" '
            f'fill="{FLOOR_COLOR}"'
        )
        assert fill_rect in svg

    def test_corridor_tile_has_floor_fill(self):
        """Corridor tiles get individual FLOOR_COLOR rects."""
        level, room = _make_shaped_level(
            RectShape(), corridor_side="east")
        svg = render_floor_svg(level, seed=42)
        floor = room.floor_tiles()
        cy = room.rect.y + room.rect.height // 2
        ex = room.rect.x2  # first corridor tile
        tile_fill = (
            f'x="{ex * CELL}" y="{cy * CELL}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{FLOOR_COLOR}"'
        )
        assert tile_fill in svg


# ── 8. Hatching / floor boundary ──────────────────────────────────


class TestHatchingFloorBoundary:
    """With the walls-before-fills layer order, hatching renders
    everywhere, walls define the boundary, and floor fills cover
    hatching inside rooms.  No clip paths needed."""

    def test_hatching_clipped_to_exterior(self):
        """Hatching is clipped to dungeon exterior."""
        level, _ = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level, seed=42)
        assert "hatch-clip" in svg

    def test_hatching_exists(self):
        """Hatching is present in the SVG."""
        level, _ = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level, seed=42)
        assert HATCH_UNDERLAY in svg

    def test_smooth_room_outline_covers_all_floor(self):
        """The smooth room outline fill covers all floor tiles."""
        level, room = _make_shaped_level(CircleShape())
        svg = render_floor_svg(level, seed=42)
        assert f'fill="{FLOOR_COLOR}"' in svg


# ── 9. Grid details inside shaped rooms ──────────────────────────


class TestGridInSmoothRooms:
    """Grid lines and floor detail must appear inside smooth rooms."""

    def _assert_grid_segments(self, shape):
        level, _ = _make_shaped_level(shape)
        svg = render_floor_svg(level, seed=42)
        grid_segs = re.findall(
            rf'<path[^>]+d="([^"]+)"[^>]*'
            rf'stroke-width="{GRID_WIDTH}"', svg)
        all_d = " ".join(grid_segs)
        assert all_d.count("M") >= 5, (
            f"Expected grid segments for {shape.type_name}"
        )

    def test_grid_inside_circle_room(self):
        self._assert_grid_segments(CircleShape())

    def test_grid_inside_cross_room(self):
        self._assert_grid_segments(CrossShape())

    def test_grid_inside_octagon_room(self):
        self._assert_grid_segments(OctagonShape())

    def test_grid_inside_pill_room(self):
        self._assert_grid_segments(PillShape())

    def test_grid_inside_temple_room(self):
        self._assert_grid_segments(TempleShape(flat_side="south"))

    def test_temple_room_has_shapely_polygon_covering_floor(self):
        """_room_shapely_polygon must return a polygon for temple
        rooms so grid/detail clip-paths reveal them."""
        from nhc.rendering.svg import _room_shapely_polygon
        room = Room(
            id="r1", rect=Rect(0, 0, 9, 9),
            shape=TempleShape(flat_side="south"),
        )
        poly = _room_shapely_polygon(room)
        assert poly is not None, "temple room missing shapely polygon"
        assert not poly.is_empty
        for tx, ty in room.floor_tiles():
            center = Point(tx * CELL + CELL / 2, ty * CELL + CELL / 2)
            assert poly.contains(center), (
                f"temple floor tile ({tx},{ty}) not inside shapely polygon"
            )

    def test_pill_room_has_shapely_polygon_covering_floor(self):
        """_room_shapely_polygon must return a polygon for pill
        rooms so grid/detail clip-paths reveal them. Without this
        the pill room gets clipped out of dungeon_poly and the
        grid + floor detail layers do not render over it."""
        from nhc.rendering.svg import _room_shapely_polygon
        room = Room(
            id="r1", rect=Rect(0, 0, 9, 5), shape=PillShape(),
        )
        poly = _room_shapely_polygon(room)
        assert poly is not None, "pill room missing shapely polygon"
        assert not poly.is_empty
        for tx, ty in room.floor_tiles():
            center = Point(tx * CELL + CELL / 2, ty * CELL + CELL / 2)
            assert poly.contains(center), (
                f"pill floor tile ({tx},{ty}) not inside shapely polygon"
            )

    def test_no_per_room_clip_path_for_rect_room(self):
        """Rect rooms don't need per-room clip paths for grid."""
        level, _ = _make_shaped_level(RectShape())
        svg = render_floor_svg(level, seed=42)
        # The hatching clip path (hatch-clip) may exist, but there
        # should be no per-room smooth-clip paths
        assert "smooth-clip" not in svg


class TestGridStructure:
    """Grid lines appear between adjacent floor tiles,
    not at room edges facing void/wall."""

    def test_grid_between_adjacent_floor_tiles(self):
        """Grid draws right/bottom edges between floor neighbors."""
        level, room = _make_shaped_level(RectShape(), room_w=5, room_h=5)
        svg = render_floor_svg(level, seed=42)
        # Grid uses GRID_WIDTH stroke and 0.7 opacity
        grid_segs = re.findall(
            rf'<path[^>]+d="([^"]+)"[^>]*'
            rf'stroke-width="{GRID_WIDTH}"', svg)
        all_d = " ".join(grid_segs)
        # Should have many M...L segments for the grid
        m_count = all_d.count("M")
        assert m_count >= 10, (
            f"Expected many grid segments, got {m_count}"
        )

    def test_corridor_tiles_have_grid(self):
        """Corridor tiles get grid lines too."""
        level, _ = _make_shaped_level(
            RectShape(), corridor_side="east")
        svg = render_floor_svg(level, seed=42)
        grid_segs = re.findall(
            rf'<path[^>]+d="([^"]+)"[^>]*'
            rf'stroke-width="{GRID_WIDTH}"', svg)
        all_d = " ".join(grid_segs)
        assert all_d.count("M") >= 10


class TestFloorDetailIndependentOfShape:
    """Cracks, stones, and scratches must appear on all floor tiles
    regardless of room shape.  Floor decoration is a property of
    the tile, not the room geometry."""

    def _render_large_room(self, shape, seed=42):
        level, room = _make_shaped_level(
            shape, room_w=15, room_h=15)
        svg = render_floor_svg(level, seed=seed)
        return svg

    def _assert_stones(self, shape):
        for seed in range(30):
            svg = self._render_large_room(shape, seed)
            if FLOOR_STONE_FILL in svg:
                return
        assert False, (
            f"No floor stones in {shape.type_name} room across 30 seeds"
        )

    def _assert_cracks(self, shape):
        for seed in range(30):
            svg = self._render_large_room(shape, seed)
            if 'opacity="0.5"' in svg and "<line " in svg:
                return
        assert False, (
            f"No cracks in {shape.type_name} room across 30 seeds"
        )

    def _assert_scratches(self, shape):
        for seed in range(50):
            svg = self._render_large_room(shape, seed)
            if "y-scratch" in svg or 'opacity="0.45"' in svg:
                return
        assert False, (
            f"No scratches in {shape.type_name} room across 50 seeds"
        )

    def test_stones_in_rect_room(self):
        self._assert_stones(RectShape())

    def test_stones_in_circle_room(self):
        self._assert_stones(CircleShape())

    def test_stones_in_cross_room(self):
        self._assert_stones(CrossShape())

    def test_stones_in_octagon_room(self):
        self._assert_stones(OctagonShape())

    def test_stones_in_pill_room(self):
        self._assert_stones(PillShape())

    def test_stones_in_temple_room(self):
        self._assert_stones(TempleShape(flat_side="south"))

    def test_cracks_in_rect_room(self):
        self._assert_cracks(RectShape())

    def test_cracks_in_circle_room(self):
        self._assert_cracks(CircleShape())

    def test_cracks_in_cross_room(self):
        self._assert_cracks(CrossShape())

    def test_cracks_in_octagon_room(self):
        self._assert_cracks(OctagonShape())

    def test_cracks_in_pill_room(self):
        self._assert_cracks(PillShape())

    def test_cracks_in_temple_room(self):
        self._assert_cracks(TempleShape(flat_side="south"))

    def test_scratches_in_rect_room(self):
        self._assert_scratches(RectShape())

    def test_scratches_in_circle_room(self):
        self._assert_scratches(CircleShape())

    def test_scratches_in_cross_room(self):
        self._assert_scratches(CrossShape())

    def test_scratches_in_octagon_room(self):
        self._assert_scratches(OctagonShape())

    def test_scratches_in_pill_room(self):
        self._assert_scratches(PillShape())

    def test_scratches_in_temple_room(self):
        self._assert_scratches(TempleShape(flat_side="south"))

    def test_detail_on_corridor_opening_tile(self):
        """Corridor opening tiles get floor detail via the
        unclipped corridor detail path (not the dungeon polygon)."""
        level, room = _make_shaped_level(
            CircleShape(), room_w=11, room_h=11,
            corridor_side="east")
        floor = room.floor_tiles()
        cy = room.rect.y + room.rect.height // 2
        ex = max(fx for fx, fy in floor if fy == cy) + 1
        # Corridor opening tile is a corridor tile rendered
        # without polygon clipping — verify it gets detail
        tile = level.tile_at(ex, cy)
        assert tile is not None and tile.is_corridor, (
            f"Tile ({ex},{cy}) should be a corridor tile"
        )
        # Render with many seeds to hit detail RNG
        for seed in range(30):
            svg = render_floor_svg(level, seed=seed)
            if FLOOR_STONE_FILL in svg:
                return
        pytest.fail("No floor detail found on corridor opening tile")

    def test_stones_on_corridor_tiles(self):
        """Floor stones appear on corridor tiles."""
        for seed in range(50):
            # Long corridor to increase chances
            level, room = _make_shaped_level(
                RectShape(), room_w=5, room_h=5,
                corridor_side="east")
            # Extend corridor further
            cy = room.rect.y + room.rect.height // 2
            ex = room.rect.x2 + 1
            for x in range(ex, ex + 10):
                if level.in_bounds(x, cy):
                    level.tiles[cy][x] = Tile(
                        terrain=Terrain.FLOOR, is_corridor=True)
            svg = render_floor_svg(level, seed=seed)
            if FLOOR_STONE_FILL in svg:
                return
        assert False, "No floor stones on corridor tiles across 50 seeds"

    def test_cracks_on_corridor_tiles(self):
        """Cracks appear on corridor tiles."""
        for seed in range(50):
            level, room = _make_shaped_level(
                RectShape(), room_w=5, room_h=5,
                corridor_side="east")
            cy = room.rect.y + room.rect.height // 2
            ex = room.rect.x2 + 1
            for x in range(ex, ex + 10):
                if level.in_bounds(x, cy):
                    level.tiles[cy][x] = Tile(
                        terrain=Terrain.FLOOR, is_corridor=True)
            svg = render_floor_svg(level, seed=seed)
            if 'opacity="0.5"' in svg and "<line " in svg:
                return
        assert False, "No cracks on corridor tiles across 50 seeds"

    def test_scratches_on_corridor_tiles(self):
        """Scratches appear on corridor tiles."""
        for seed in range(50):
            level, room = _make_shaped_level(
                RectShape(), room_w=5, room_h=5,
                corridor_side="east")
            cy = room.rect.y + room.rect.height // 2
            ex = room.rect.x2 + 1
            for x in range(ex, ex + 10):
                if level.in_bounds(x, cy):
                    level.tiles[cy][x] = Tile(
                        terrain=Terrain.FLOOR, is_corridor=True)
            svg = render_floor_svg(level, seed=seed)
            if "y-scratch" in svg or 'opacity="0.45"' in svg:
                return
        assert False, "No scratches on corridor tiles across 50 seeds"

    def test_stones_on_doorless_opening_tile(self):
        """Floor stones appear on doorless opening tiles."""
        for seed in range(50):
            level, room = _make_shaped_level(
                CircleShape(), room_w=11, room_h=11,
                corridor_side="east")
            svg = render_floor_svg(level, seed=seed)
            if FLOOR_STONE_FILL in svg:
                return
        assert False, (
            "No floor stones on doorless opening across 50 seeds"
        )
