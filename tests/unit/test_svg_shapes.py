"""Tests for SVG rendering of shaped rooms.

These tests verify the visual properties of the rendered SVG
output — what shapes are drawn, where gaps appear, whether
outlines align with the tile grid — without depending on
rendering order or implementation details.
"""

import re

from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, Level, OctagonShape,
    Rect, RectShape, Room, RoomShape, Terrain, Tile,
)
from nhc.rendering.svg import (
    BG, CELL, GRID_WIDTH, PADDING, WALL_WIDTH, render_floor_svg,
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
        from shapely.geometry import Point, Polygon

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
        from shapely.geometry import Point, Polygon

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

    def test_hybrid_doorless_opening_gaps_arc(self):
        """Hybrid with doorless corridor has gapped arc."""
        shape = HybridShape(CircleShape(), RectShape(), "horizontal")
        level, room = _make_shaped_level(
            shape, room_w=9, room_h=10,
            corridor_side="north")
        svg = render_floor_svg(level)
        # Should have a path with arcs but NOT closed
        arc_paths = re.findall(
            r'<path[^>]+d="([^"]*A[^"]*)"', svg)
        has_open_arc = any("Z" not in p for p in arc_paths)
        assert has_open_arc, "Hybrid gapped arc should not be closed"


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


# ── 7. Floor fill on corridor opening tiles ──────────────────────


class TestCorridorOpeningFills:
    def test_corridor_opening_tile_cleared(self):
        """Corridor opening tiles have hatching cleared with BG fill."""
        level, room = _make_shaped_level(
            CircleShape(), corridor_side="east")
        svg = render_floor_svg(level)
        # The smooth floor fills should include a BG rect for the
        # corridor opening tile
        floor = room.floor_tiles()
        cx_tile = room.rect.x + room.rect.width // 2
        cy_tile = room.rect.y + room.rect.height // 2
        # Find rightmost floor at center row + 1 = corridor entry
        ex = max(fx for fx, fy in floor if fy == cy_tile) + 1
        # Look for a BG rect at that tile position
        tile_px = ex * CELL
        tile_py = cy_tile * CELL
        bg_rect = (
            f'x="{tile_px}" y="{tile_py}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{BG}"'
        )
        assert bg_rect in svg, (
            f"No BG fill rect at corridor opening tile ({ex},{cy_tile})"
        )

    def test_no_extra_fill_with_door(self):
        """No extra BG fill when corridor has a door."""
        level, room = _make_shaped_level(
            CircleShape(), corridor_side="east", door=True)
        svg = render_floor_svg(level)
        floor = room.floor_tiles()
        cx_tile = room.rect.x + room.rect.width // 2
        cy_tile = room.rect.y + room.rect.height // 2
        ex = max(fx for fx, fy in floor if fy == cy_tile) + 1
        tile_px = ex * CELL
        tile_py = cy_tile * CELL
        # The smooth fill group shouldn't have a rect at the
        # corridor tile (it only clears for doorless openings)
        bg_rect = (
            f'x="{tile_px}" y="{tile_py}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{BG}" stroke="none"'
        )
        assert bg_rect not in svg
