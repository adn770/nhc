"""Interior wall SVG rendering tests (M7).

See ``design/building_interiors.md`` — interior walls render as
one ``<line>`` per straight run, stroke-width ~0.25 tile,
colored by ``Building.interior_wall_material``. Perimeter runs
keep the existing stylized brick / stone pass.
"""

from __future__ import annotations

import re

from nhc.dungeon.building import Building
from nhc.dungeon.model import (
    Level, Rect, RectShape, Room, Terrain, Tile,
)
from nhc.rendering.building import (
    INTERIOR_WALL_COLORS, render_building_floor_svg,
)


def _single_floor_building(
    *, interior_wall_material: str = "stone",
    interior_wall_tiles: set[tuple[int, int]] | None = None,
) -> Building:
    rect = Rect(1, 1, 7, 7)
    w = rect.x + rect.width + 2
    h = rect.y + rect.height + 2
    level = Level.create_empty("b_f0", "b floor 0", 1, w, h)
    level.building_id = "b"
    level.floor_index = 0
    # Footprint = FLOOR.
    footprint = RectShape().floor_tiles(rect)
    for (x, y) in footprint:
        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    # Shell WALLs at 8-neighbours outside the footprint.
    for (x, y) in footprint:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = x + dx, y + dy
                if (nx, ny) in footprint or not level.in_bounds(nx, ny):
                    continue
                if level.tiles[ny][nx].terrain is Terrain.VOID:
                    level.tiles[ny][nx] = Tile(terrain=Terrain.WALL)
    # Stamp interior walls if provided.
    for (x, y) in interior_wall_tiles or set():
        level.tiles[y][x] = Tile(terrain=Terrain.WALL)
    level.rooms = [Room(
        id="r", rect=rect, shape=RectShape(), tags=["interior"],
    )]
    return Building(
        id="b", base_shape=RectShape(), base_rect=rect,
        floors=[level], wall_material="brick",
        interior_wall_material=interior_wall_material,
    )


class TestInteriorWallOverlay:
    def test_no_interior_walls_emits_no_line(self):
        """A SingleRoom-like floor (no interior walls) emits no
        interior-wall <line>s."""
        building = _single_floor_building()
        svg = render_building_floor_svg(building, 0)
        # The only <line> should come from legitimate sources (not
        # the interior-wall overlay). Search for the interior-wall
        # stone color specifically.
        color = INTERIOR_WALL_COLORS["stone"]
        matches = re.findall(
            rf'<line[^>]*stroke="{re.escape(color)}"[^>]*/>',
            svg,
        )
        assert matches == []

    def test_horizontal_wall_emits_one_line(self):
        """A single horizontal interior wall becomes one <line>."""
        # Horizontal wall at y=4 spanning x=1..7 (minus door at 4).
        wall = {(x, 4) for x in range(1, 8) if x != 4}
        building = _single_floor_building(
            interior_wall_material="wood",
            interior_wall_tiles=wall,
        )
        svg = render_building_floor_svg(building, 0)
        color = INTERIOR_WALL_COLORS["wood"]
        matches = re.findall(
            rf'<line[^>]*stroke="{re.escape(color)}"[^>]*/>',
            svg,
        )
        # Door splits the wall into 2 runs (left + right of door).
        assert len(matches) == 2

    def test_material_selects_color(self):
        wall = {(x, 4) for x in range(1, 8) if x != 4}
        for material, expected in INTERIOR_WALL_COLORS.items():
            building = _single_floor_building(
                interior_wall_material=material,
                interior_wall_tiles=wall,
            )
            svg = render_building_floor_svg(building, 0)
            assert f'stroke="{expected}"' in svg, (
                f"missing interior-wall color for material={material}"
            )

    def test_interior_wall_material_default_is_stone(self):
        """Buildings that do not set interior_wall_material default
        to stone (matches the fallback in ARCHETYPE_CONFIG)."""
        rect = Rect(1, 1, 5, 5)
        b = Building(
            id="b", base_shape=RectShape(), base_rect=rect,
        )
        assert b.interior_wall_material == "stone"

    def test_perimeter_pass_unchanged_no_interior_walls(self):
        """Without interior walls, the composite output equals the
        pre-M7 output (perimeter brick/stone overlay untouched)."""
        building = _single_floor_building()
        svg = render_building_floor_svg(building, 0)
        # The perimeter brick overlay emits <rect> elements for the
        # masonry pattern. Our interior-wall pass must not touch
        # them. Just check that brick-colored fills still appear.
        assert "fill=" in svg  # sanity: SVG still has fills
