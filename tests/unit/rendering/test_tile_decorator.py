"""Tests for the TileDecorator + walk_and_paint primitives.

Phase 2 of the rendering refactor. Covers:
* TileDecorator predicate gating (only matching tiles paint)
* requires / forbids flag gating against RenderContext
* group_open / group_close lifecycle (groups only emit when there
  are fragments)
* multi-decorator ordering (z_order)
* portability (synthetic level with one matching tile in any
  floor_kind paints the matching decorator)
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.rendering._decorators import (
    PaintArgs,
    TileDecorator,
    walk_and_paint,
)
from nhc.rendering._render_context import build_render_context


def _grid(width: int, height: int) -> Level:
    level = Level.create_empty("L", "L", 0, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    return level


def _stamp(level: Level, x: int, y: int, **kwargs) -> None:
    """Mutate a single tile on the test grid."""
    base = level.tiles[y][x]
    fields = {
        "terrain": base.terrain,
        "surface_type": base.surface_type,
        "feature": base.feature,
    }
    fields.update(kwargs)
    level.tiles[y][x] = Tile(**fields)


class TestPredicateGating:
    def test_only_matching_tiles_paint(self) -> None:
        level = _grid(3, 1)
        _stamp(level, 1, 0, surface_type=SurfaceType.STREET)
        ctx = build_render_context(level, seed=0)

        calls: list[tuple[int, int]] = []

        def paint(args: PaintArgs):
            calls.append((args.x, args.y))
            return [f'<rect x="{args.x}"/>']

        dec = TileDecorator(
            name="streetonly",
            layer="floor_detail",
            predicate=lambda lvl, x, y: (
                lvl.tiles[y][x].surface_type is SurfaceType.STREET
            ),
            paint=paint,
        )
        out = walk_and_paint(ctx, [dec])
        assert calls == [(1, 0)]
        assert out == ['<rect x="1"/>']

    def test_no_matches_emits_nothing_no_group(self) -> None:
        level = _grid(2, 1)
        ctx = build_render_context(level, seed=0)

        dec = TileDecorator(
            name="never",
            layer="floor_detail",
            predicate=lambda lvl, x, y: False,
            paint=lambda args: ["<x/>"],
            group_open='<g class="never">',
        )
        # No fragments -> no group_open, no group_close.
        assert walk_and_paint(ctx, [dec]) == []


class TestFlagRequiresForbids:
    def test_requires_blocks_when_flag_false(self) -> None:
        level = _grid(1, 1)
        _stamp(level, 0, 0, surface_type=SurfaceType.STREET)
        # Building flips macabre_detail -> False.
        level.building_id = "b1"
        ctx = build_render_context(level, seed=0)

        dec = TileDecorator(
            name="bones",
            layer="floor_detail",
            predicate=lambda lvl, x, y: True,
            paint=lambda args: ["<bone/>"],
            requires=frozenset({"macabre_detail"}),
        )
        assert walk_and_paint(ctx, [dec]) == []

    def test_requires_allows_when_flag_true(self) -> None:
        level = _grid(1, 1)
        ctx = build_render_context(level, seed=0)

        dec = TileDecorator(
            name="bones",
            layer="floor_detail",
            predicate=lambda lvl, x, y: True,
            paint=lambda args: ["<bone/>"],
            requires=frozenset({"macabre_detail"}),
        )
        assert walk_and_paint(ctx, [dec]) == ["<bone/>"]

    def test_forbids_blocks_when_flag_true(self) -> None:
        level = _grid(1, 1)
        ctx = build_render_context(level, seed=0)
        # macabre_detail is True for default dungeon -- "forbids"
        # of that flag should suppress.

        dec = TileDecorator(
            name="never_in_dungeon",
            layer="floor_detail",
            predicate=lambda lvl, x, y: True,
            paint=lambda args: ["<x/>"],
            forbids=frozenset({"macabre_detail"}),
        )
        assert walk_and_paint(ctx, [dec]) == []


class TestGroupLifecycle:
    def test_group_open_close_wrap_fragments(self) -> None:
        level = _grid(2, 1)
        _stamp(level, 0, 0, surface_type=SurfaceType.STREET)
        ctx = build_render_context(level, seed=0)

        dec = TileDecorator(
            name="streets",
            layer="floor_detail",
            predicate=lambda lvl, x, y: (
                lvl.tiles[y][x].surface_type is SurfaceType.STREET
            ),
            paint=lambda args: ["<rect/>"],
            group_open='<g class="streets">',
        )
        out = walk_and_paint(ctx, [dec])
        assert out == ['<g class="streets">', "<rect/>", "</g>"]

    def test_group_close_default_is_g_close(self) -> None:
        dec = TileDecorator(
            name="x",
            layer="l",
            predicate=lambda lvl, x, y: True,
            paint=lambda args: [],
        )
        assert dec.group_close == "</g>"


class TestMultiDecorator:
    def test_independent_decorators_fire_per_tile(self) -> None:
        # COBBLESTONE and COBBLE_STONE share a predicate but have
        # different group wrappers; each tile produces fragments
        # in both.
        level = _grid(2, 1)
        for x in (0, 1):
            _stamp(level, x, 0, surface_type=SurfaceType.STREET)
        ctx = build_render_context(level, seed=0)

        a = TileDecorator(
            name="a",
            layer="l",
            predicate=lambda lvl, x, y: True,
            paint=lambda args: ["<a/>"],
            group_open='<g id="a">',
        )
        b = TileDecorator(
            name="b",
            layer="l",
            predicate=lambda lvl, x, y: True,
            paint=lambda args: ["<b/>"],
            group_open='<g id="b">',
        )
        out = walk_and_paint(ctx, [a, b])
        # Decorator a's group then decorator b's group.
        assert out == [
            '<g id="a">', "<a/>", "<a/>", "</g>",
            '<g id="b">', "<b/>", "<b/>", "</g>",
        ]


class TestPaintArgs:
    def test_paint_receives_pixel_coords_and_tile(self) -> None:
        from nhc.rendering._svg_helpers import CELL

        level = _grid(3, 2)
        _stamp(level, 2, 1, surface_type=SurfaceType.STREET)
        ctx = build_render_context(level, seed=0)

        captured: dict = {}

        def paint(args: PaintArgs):
            captured["x"] = args.x
            captured["y"] = args.y
            captured["px"] = args.px
            captured["py"] = args.py
            captured["tile"] = args.tile
            captured["ctx"] = args.ctx
            assert isinstance(args.rng, random.Random)
            return ["<x/>"]

        dec = TileDecorator(
            name="d",
            layer="l",
            predicate=lambda lvl, x, y: (
                lvl.tiles[y][x].surface_type is SurfaceType.STREET
            ),
            paint=paint,
        )
        walk_and_paint(ctx, [dec])
        assert captured["x"] == 2
        assert captured["y"] == 1
        assert captured["px"] == 2 * CELL
        assert captured["py"] == 1 * CELL
        assert captured["tile"].surface_type is SurfaceType.STREET
        assert captured["ctx"] is ctx


class TestDeterminism:
    def test_same_seed_same_output(self) -> None:
        level = _grid(4, 4)
        for x in range(4):
            for y in range(4):
                _stamp(level, x, y, surface_type=SurfaceType.STREET)
        ctx = build_render_context(level, seed=42)

        def paint(args: PaintArgs):
            return [f"<r v={args.rng.random():.4f}/>"]

        dec = TileDecorator(
            name="d",
            layer="l",
            predicate=lambda lvl, x, y: True,
            paint=paint,
        )
        first = walk_and_paint(ctx, [dec])
        second = walk_and_paint(ctx, [dec])
        assert first == second
