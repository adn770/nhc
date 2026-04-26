"""Phase 6 wood-floor decorator tests.

The ``WOOD_FLOOR_FILL_DECORATOR`` gates on
``ctx.interior_finish == "wood"`` via ``requires``. Stone-floored
levels must not emit any wood-fill rect; wood-floored levels must
emit one rect per FLOOR tile with the canonical
``WOOD_FLOOR_FILL`` colour.
"""

from __future__ import annotations

from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.rendering._decorators import walk_and_paint
from nhc.rendering._floor_detail import (
    WOOD_FLOOR_FILL,
    WOOD_FLOOR_FILL_DECORATOR,
)
from nhc.rendering._render_context import build_render_context


def _filled_level(w: int = 4, h: int = 3) -> Level:
    level = Level.create_empty("L", "L", 0, w, h)
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, w, h))]
    return level


class TestWoodFloorFillRequires:
    def test_stone_finish_emits_no_wood_fill(self) -> None:
        level = _filled_level()
        ctx = build_render_context(level, seed=0)
        # Default interior_finish is "stone".
        out = walk_and_paint(
            ctx, [WOOD_FLOOR_FILL_DECORATOR],
        )
        assert out == []

    def test_wood_finish_emits_one_rect_per_floor_tile(self) -> None:
        level = _filled_level(4, 3)
        level.interior_floor = "wood"
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(
            ctx, [WOOD_FLOOR_FILL_DECORATOR],
        )
        # 12 FLOOR tiles -> 12 wood-fill rects.
        rect_count = sum(
            1 for line in out if line.startswith("<rect")
        )
        assert rect_count == 12
        for line in out:
            if line.startswith("<rect"):
                assert WOOD_FLOOR_FILL in line

    def test_future_finish_is_inert(self) -> None:
        """The ``interior_finish`` field is a free string per the
        plan -- a value the wood decorator doesn't recognise must
        skip wood emission entirely."""
        level = _filled_level()
        level.interior_floor = "earth"
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(
            ctx, [WOOD_FLOOR_FILL_DECORATOR],
        )
        assert out == []
