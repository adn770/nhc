"""Tests for the Python port of the clearHatch polygon
algorithm in ``nhc.rendering.hatch_polygon``.

These tests pin the same behaviour as the JS implementation in
``nhc/web/static/js/map.js`` so the two stay in sync.
"""

from __future__ import annotations

from nhc.rendering.hatch_polygon import (
    WALL_E,
    WALL_N,
    WALL_S,
    WALL_W,
    build_tile_set_polygons,
    offset_loop,
)

CELL = 32
PAD = 32


class TestBuildTileSetPolygonsSingleTile:
    """A single tile produces one 4-edge square loop."""

    def test_single_tile_four_edges(self):
        walls = {(0, 0): WALL_N | WALL_E | WALL_S | WALL_W}
        loops = build_tile_set_polygons(walls, CELL, PAD)
        assert len(loops) == 1
        loop = loops[0]
        assert len(loop) == 4
        for e in loop:
            assert e.wall is True

    def test_single_tile_corners_are_pixel_coords(self):
        walls = {(0, 0): 0}
        loops = build_tile_set_polygons(walls, CELL, PAD)
        loop = loops[0]
        # First edge starts at (PAD, PAD) and walks clockwise.
        assert (loop[0].ax, loop[0].ay) == (PAD, PAD)
        assert (loop[0].bx, loop[0].by) == (PAD + CELL, PAD)
        # Second edge goes down the right side.
        assert (loop[1].ax, loop[1].ay) == (PAD + CELL, PAD)
        assert (loop[1].bx, loop[1].by) == (PAD + CELL, PAD + CELL)


class TestBuildTileSetPolygonsRect:
    """A 3x3 rect with all wall bits collapses to a 4-edge
    loop (colinear merging)."""

    def test_3x3_rect_collapses_to_four_edges(self):
        walls: dict[tuple[int, int], int] = {}
        for ty in range(3):
            for tx in range(3):
                mask = 0
                if ty == 0:
                    mask |= WALL_N
                if ty == 2:
                    mask |= WALL_S
                if tx == 0:
                    mask |= WALL_W
                if tx == 2:
                    mask |= WALL_E
                walls[(tx, ty)] = mask
        loops = build_tile_set_polygons(walls, CELL, PAD)
        assert len(loops) == 1
        # Outer rect has 4 merged edges.
        assert len(loops[0]) == 4
        # All outer edges are wall edges.
        assert all(e.wall for e in loops[0])

    def test_3x3_rect_pixel_bounds(self):
        walls: dict[tuple[int, int], int] = {}
        for ty in range(3):
            for tx in range(3):
                walls[(tx, ty)] = (
                    (WALL_N if ty == 0 else 0)
                    | (WALL_S if ty == 2 else 0)
                    | (WALL_W if tx == 0 else 0)
                    | (WALL_E if tx == 2 else 0)
                )
        loop = build_tile_set_polygons(walls, CELL, PAD)[0]
        xs = [e.ax for e in loop] + [e.bx for e in loop]
        ys = [e.ay for e in loop] + [e.by for e in loop]
        assert min(xs) == PAD
        assert max(xs) == PAD + 3 * CELL
        assert min(ys) == PAD
        assert max(ys) == PAD + 3 * CELL


class TestBuildTileSetPolygonsDisjoint:
    """Two disconnected tiles produce two loops."""

    def test_two_disjoint_components(self):
        walls = {
            (0, 0): WALL_N | WALL_E | WALL_S | WALL_W,
            (5, 5): WALL_N | WALL_E | WALL_S | WALL_W,
        }
        loops = build_tile_set_polygons(walls, CELL, PAD)
        assert len(loops) == 2


class TestBuildTileSetPolygonsFlagChange:
    """A horizontal run where some tiles have wall-N bit and
    some don't must NOT collapse across the flag boundary."""

    def test_colinear_flag_change_stays_split(self):
        # Three tiles in a row. Middle has no N wall; outer two
        # do. After merging, the top edge should be split into
        # three segments (wall, non-wall, wall).
        walls = {
            (0, 0): WALL_N | WALL_S | WALL_W,
            (1, 0): WALL_S,
            (2, 0): WALL_N | WALL_S | WALL_E,
        }
        loops = build_tile_set_polygons(walls, CELL, PAD)
        assert len(loops) == 1
        loop = loops[0]
        # Top row (y=PAD): walk rightward collecting wall flags.
        top_edges = [e for e in loop if e.ay == PAD and e.by == PAD]
        # The top should be broken into three segments by flag.
        assert len(top_edges) == 3
        # First and last are wall, middle is not.
        top_edges.sort(key=lambda e: min(e.ax, e.bx))
        assert top_edges[0].wall is True
        assert top_edges[1].wall is False
        assert top_edges[2].wall is True


class TestOffsetLoopSingleTile:
    """Wall-only square expands uniformly by dist."""

    def test_all_walls_expand_uniformly(self):
        walls = {(0, 0): WALL_N | WALL_E | WALL_S | WALL_W}
        loop = build_tile_set_polygons(walls, CELL, PAD)[0]
        pts = offset_loop(loop, 2)
        # Four vertices after offset, all pushed 2 px outward.
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        assert min(xs) == PAD - 2
        assert max(xs) == PAD + CELL + 2
        assert min(ys) == PAD - 2
        assert max(ys) == PAD + CELL + 2

    def test_no_wall_stays_flush(self):
        walls = {(0, 0): 0}
        loop = build_tile_set_polygons(walls, CELL, PAD)[0]
        pts = offset_loop(loop, 2)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        assert min(xs) == PAD
        assert max(xs) == PAD + CELL
        assert min(ys) == PAD
        assert max(ys) == PAD + CELL


class TestOffsetLoopSelective:
    """Mixed wall/non-wall edges push only the wall ones."""

    def test_only_north_wall_pushed(self):
        # Single tile, only the north edge marked as wall.
        walls = {(0, 0): WALL_N}
        loop = build_tile_set_polygons(walls, CELL, PAD)[0]
        pts = offset_loop(loop, 2)
        ys = [p[1] for p in pts]
        # Top should be pushed up by 2 px; bottom stays flush.
        assert min(ys) == PAD - 2
        assert max(ys) == PAD + CELL


class TestOffsetLoopParallelBridge:
    """A colinear wall↔non-wall transition produces parallel
    offset lines — the bridge branch emits two points."""

    def test_bridge_at_flag_change(self):
        # Three tiles in a row with a flag flip on the top edge:
        # |wall|no-wall|wall|. The two colinear transitions
        # each yield parallel offset lines and emit a
        # perpendicular bridge pair in the output.
        walls = {
            (0, 0): WALL_N | WALL_S | WALL_W,
            (1, 0): WALL_S,
            (2, 0): WALL_N | WALL_S | WALL_E,
        }
        loop = build_tile_set_polygons(walls, CELL, PAD)[0]
        pts = offset_loop(loop, 2)
        # The lifted wall portions sit at y = PAD - 2, the
        # flush centre portion at y = PAD. Both must appear in
        # the output, with matching x bridges at PAD + CELL and
        # PAD + 2 * CELL.
        ys = {round(p[1], 6) for p in pts}
        assert PAD - 2 in ys
        assert PAD in ys
        lifted_xs = sorted(
            round(p[0], 6) for p in pts if p[1] == PAD - 2
        )
        flush_xs = sorted(
            round(p[0], 6) for p in pts if p[1] == PAD
        )
        # Each bridge contributes one lifted point and one
        # flush point at the same x.
        assert PAD + CELL in lifted_xs and PAD + CELL in flush_xs
        assert (PAD + 2 * CELL in lifted_xs
                and PAD + 2 * CELL in flush_xs)
