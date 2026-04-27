"""Concrete layer registry for ``render_floor_svg``.

Wraps each existing pass as a :class:`Layer` and bundles them
into the ordered :data:`FLOOR_LAYERS` tuple. Phase 5 of the
rendering refactor.

IR emit-siblings (one per layer, named ``_emit_<name>_ir``) live
alongside the legacy ``_<name>_paint`` helpers. They are wired into
:data:`nhc.rendering.ir_emitter.IR_STAGES` and write FlatBuffer ops
that 1.k will route through ``ir_to_svg`` instead of the legacy
paint helpers. The paint helpers stay until Phase 4 deletes them
after the Rust ports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from nhc.dungeon.model import SurfaceType
from nhc.rendering._decorators import TileDecorator
from nhc.rendering._features_svg import (
    BUSH_FEATURE, FOUNTAIN_CROSS_FEATURE, FOUNTAIN_FEATURE,
    FOUNTAIN_LARGE_FEATURE, FOUNTAIN_LARGE_SQUARE_FEATURE,
    FOUNTAIN_SQUARE_FEATURE, TREE_FEATURE, WELL_FEATURE,
    WELL_SQUARE_FEATURE,
)
from nhc.rendering._pipeline import (
    Layer, TileWalkLayer, make_tile_walk_layer,
)
from nhc.rendering._render_context import RenderContext
from nhc.rendering._svg_helpers import _is_door

if TYPE_CHECKING:
    from nhc.rendering.ir_emitter import FloorIRBuilder


# ── Bespoke layer paint wrappers ─────────────────────────────


def _shadows_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._shadows import (
        _render_corridor_shadows, _render_room_shadows,
    )
    out: list[str] = []
    _render_room_shadows(out, ctx.level)
    _render_corridor_shadows(out, ctx.level)
    return out


def _emit_shadows_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the shadows layer.

    Phase 1.b.1: emits one aggregated ``ShadowOp(kind=Corridor)``
    carrying every CORRIDOR-surface tile and every door tile in
    layer order. The single-op form keeps the IR small and matches
    the legacy ``_render_corridor_shadows`` traversal order
    (row-major y, x). Room shadows ship in 1.b.2.
    """
    from nhc.rendering.ir._fb import Op, ShadowKind
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.ShadowOp import ShadowOpT
    from nhc.rendering.ir._fb.TileCoord import TileCoordT

    level = builder.ctx.level
    tiles: list[TileCoordT] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
            ):
                continue
            t = TileCoordT()
            t.x = x
            t.y = y
            tiles.append(t)
    if not tiles:
        return
    op = ShadowOpT()
    op.kind = ShadowKind.ShadowKind.Corridor
    op.tiles = tiles
    entry = OpEntryT()
    entry.opType = Op.Op.ShadowOp
    entry.op = op
    builder.add_op(entry)


def _hatching_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._hatching import (
        _render_corridor_hatching, _render_hatching,
    )
    out: list[str] = []
    _render_hatching(
        out, ctx.level, ctx.seed, ctx.dungeon_poly,
        hatch_distance=ctx.hatch_distance,
        cave_wall_poly=ctx.cave_wall_poly,
    )
    _render_corridor_hatching(out, ctx.level, ctx.seed)
    return out


def _walls_and_floors_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._walls_floors import _render_walls_and_floors
    out: list[str] = []
    footprint = (
        set(ctx.building_footprint)
        if ctx.building_footprint is not None
        else None
    )
    _render_walls_and_floors(
        out, ctx.level,
        cave_wall_path=ctx.cave_wall_path,
        cave_wall_poly=ctx.cave_wall_poly,
        cave_tiles=set(ctx.cave_tiles) if ctx.cave_tiles else set(),
        building_footprint=footprint,
    )
    return out


def _terrain_tints_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._terrain_detail import _render_terrain_tints
    out: list[str] = []
    _render_terrain_tints(out, ctx.level, ctx.dungeon_poly)
    return out


def _floor_grid_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._floor_detail import _render_floor_grid
    out: list[str] = []
    _render_floor_grid(out, ctx.level, ctx.dungeon_poly)
    return out


def _floor_detail_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._floor_detail import _render_floor_detail
    building_polygon = (
        list(ctx.building_polygon)
        if ctx.building_polygon is not None
        else None
    )
    out: list[str] = []
    _render_floor_detail(
        out, ctx.level, ctx.seed, ctx.dungeon_poly,
        building_polygon=building_polygon,
        ctx=ctx,
    )
    return out


def _terrain_detail_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._terrain_detail import _render_terrain_detail
    out: list[str] = []
    _render_terrain_detail(
        out, ctx.level, ctx.seed, ctx.dungeon_poly, ctx=ctx,
    )
    return out


def _stairs_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._stairs_svg import _render_stairs
    out: list[str] = []
    _render_stairs(out, ctx.level)
    return out


# ── Surface features layer (TileWalkLayer) ────────────────────

_SURFACE_FEATURE_DECORATORS: tuple[TileDecorator, ...] = (
    WELL_FEATURE,
    WELL_SQUARE_FEATURE,
    FOUNTAIN_FEATURE,
    FOUNTAIN_SQUARE_FEATURE,
    FOUNTAIN_LARGE_FEATURE,
    FOUNTAIN_LARGE_SQUARE_FEATURE,
    FOUNTAIN_CROSS_FEATURE,
    TREE_FEATURE,
    BUSH_FEATURE,
)


# ── Layer registry ────────────────────────────────────────────
#
# Order numbers preserve the legacy pass order: shadows=100,
# hatching=200, walls=300, terrain_tints=350, grid=400,
# floor_detail=500, terrain_detail=600, stairs=700,
# surface_features=800. Gaps of 100 leave room to slot future
# passes between existing ones.


FLOOR_LAYERS: tuple[Layer, ...] = (
    Layer(
        name="shadows",
        order=100,
        is_active=lambda ctx: ctx.shadows_enabled,
        paint=_shadows_paint,
    ),
    Layer(
        name="hatching",
        order=200,
        is_active=lambda ctx: ctx.hatching_enabled,
        paint=_hatching_paint,
    ),
    Layer(
        name="walls_and_floors",
        order=300,
        is_active=lambda ctx: True,
        paint=_walls_and_floors_paint,
    ),
    Layer(
        name="terrain_tints",
        order=350,
        is_active=lambda ctx: True,
        paint=_terrain_tints_paint,
    ),
    Layer(
        name="floor_grid",
        order=400,
        is_active=lambda ctx: True,
        paint=_floor_grid_paint,
    ),
    Layer(
        name="floor_detail",
        order=500,
        is_active=lambda ctx: True,
        paint=_floor_detail_paint,
    ),
    Layer(
        name="terrain_detail",
        order=600,
        is_active=lambda ctx: True,
        paint=_terrain_detail_paint,
    ),
    Layer(
        name="stairs",
        order=700,
        is_active=lambda ctx: True,
        paint=_stairs_paint,
    ),
    make_tile_walk_layer(
        name="surface_features",
        order=800,
        decorators=_SURFACE_FEATURE_DECORATORS,
    ),
)
