"""Renderer draws interior edges as SVG lines (M11).

One ``<line>`` per coalesced edge run; door-suppressed edges are
skipped so the door glyph substitutes for the wall stroke.
"""

from __future__ import annotations

import re

from nhc.dungeon.building import Building
from nhc.dungeon.model import (
    Level, Rect, RectShape, Room, Terrain, canonicalize,
)
from nhc.rendering.building import render_building_floor_svg


def _make_level_with_edges(
    width: int, height: int,
    edges: list[tuple[int, int, str]],
) -> Level:
    lvl = Level.create_empty("test", "test", 0, width, height)
    for y in range(height):
        for x in range(width):
            lvl.tiles[y][x].terrain = Terrain.FLOOR
    for e in edges:
        lvl.interior_edges.add(canonicalize(*e))
    lvl.rooms = [
        Room(
            id="r0", rect=Rect(0, 0, width, height),
            shape=RectShape(), tags=[],
        ),
    ]
    return lvl


def _make_building(level: Level) -> Building:
    return Building(
        id="b1",
        base_shape=RectShape(),
        base_rect=Rect(0, 0, level.width, level.height),
        floors=[level],
        wall_material="stone",
        interior_floor="stone",
        interior_wall_material="stone",
    )


def _count_interior_wall_lines(svg: str) -> int:
    return len(re.findall(
        r'<line[^>]*stroke="#707070"', svg,
    ))


class TestInteriorEdgeSVG:
    def test_five_contiguous_edges_coalesce_to_one_line(self) -> None:
        """Five north edges at the same y become one SVG line."""
        edges = [(x, 3, "north") for x in range(1, 6)]
        lvl = _make_level_with_edges(8, 6, edges)
        b = _make_building(lvl)
        svg = render_building_floor_svg(b, floor_index=0)
        assert _count_interior_wall_lines(svg) == 1

    def test_five_separate_edges_emit_five_lines(self) -> None:
        """Non-contiguous edges don't coalesce."""
        edges = [(1, y, "west") for y in (1, 3, 5)] + [
            (x, 2, "north") for x in (1, 4)
        ]
        lvl = _make_level_with_edges(8, 8, edges)
        b = _make_building(lvl)
        svg = render_building_floor_svg(b, floor_index=0)
        # 3 west edges at x=1, at y=1, 3, 5 — non-consecutive, 3 lines.
        # 2 north edges at y=2, x=1 and x=4 — non-consecutive, 2 lines.
        assert _count_interior_wall_lines(svg) == 5

    def test_door_suppresses_wall_line_above_it(self) -> None:
        """A door_closed on tile (x, y) with door_side='north'
        suppresses the canonical edge (x, y, 'north')."""
        edges = [(x, 3, "north") for x in range(1, 6)]
        lvl = _make_level_with_edges(8, 6, edges)
        # Put a door at (3, 3) with door_side='north'.
        lvl.tiles[3][3].feature = "door_closed"
        lvl.tiles[3][3].door_side = "north"
        b = _make_building(lvl)
        svg = render_building_floor_svg(b, floor_index=0)
        # Remaining edges: y=3 north at x=1, 2 (coalesced) and x=4, 5
        # (coalesced). That's 2 lines.
        assert _count_interior_wall_lines(svg) == 2

    def test_secret_door_does_not_suppress_edge(self) -> None:
        """Secret doors render AS walls until discovered."""
        edges = [(x, 3, "north") for x in range(1, 4)]
        lvl = _make_level_with_edges(6, 6, edges)
        lvl.tiles[3][2].feature = "door_secret"
        lvl.tiles[3][2].door_side = "north"
        b = _make_building(lvl)
        svg = render_building_floor_svg(b, floor_index=0)
        # All 3 edges still rendered, coalesced into 1 line.
        assert _count_interior_wall_lines(svg) == 1
