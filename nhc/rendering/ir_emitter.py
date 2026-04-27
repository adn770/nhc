"""Floor IR emitter — Phase 1.a skeleton + emit_regions foundation.

Walks a ``Level`` + :class:`RenderContext` through the
:data:`IR_STAGES` pipeline and emits a ``FloorIR`` FlatBuffer. The
stage list mirrors :data:`nhc.rendering._floor_layers.FLOOR_LAYERS`
in §6 layer order, with an additional foundation stage
(:func:`emit_regions`) that registers the polygon regions
subsequent ops reference by id.

Public surface:

- :func:`build_floor_ir` — the cold-path entry point that
  ``render_floor_svg`` will route through once 1.k rewires it.
- :data:`IR_STAGES` — ordered tuple of stage callables; each takes
  the :class:`FloorIRBuilder` and writes regions / ops.

Phase 1.a fills :func:`emit_regions` (registers the dungeon
polygon and, when present, the cave polygon). The other nine
stages are no-op stubs; Phase 1.b–1.j land their op-emit logic
one layer at a time.
"""

from __future__ import annotations

from typing import Any, Callable

import flatbuffers

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import OctagonShape, RectShape
from nhc.rendering._cave_geometry import (
    _build_cave_wall_geometry, _trace_cave_boundary_coords,
)
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._render_context import (
    RenderContext, build_render_context,
)
from nhc.rendering._room_outlines import _polygon_vertices
from nhc.rendering._svg_helpers import CELL, PADDING
from nhc.rendering.ir._fb import FloorKind, RegionKind
from nhc.rendering.ir._fb.FeatureFlags import FeatureFlagsT
from nhc.rendering.ir._fb.FloorIR import FloorIRT
from nhc.rendering.ir._fb.PathRange import PathRangeT
from nhc.rendering.ir._fb.Polygon import PolygonT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.Vec2 import Vec2T


# Schema version stamped on every emitted buffer. Bumped per the
# §"Schema-evolution discipline" checklist in the migration plan
# whenever floor_ir.fbs changes (additive → minor, breaking → major).
_SCHEMA_MAJOR = 1
_SCHEMA_MINOR = 1

_FILE_IDENTIFIER = b"NIRF"


_FLOOR_KIND_MAP: dict[str, int] = {
    "dungeon": FloorKind.FloorKind.Dungeon,
    "cave": FloorKind.FloorKind.Cave,
    "building": FloorKind.FloorKind.Building,
    "surface": FloorKind.FloorKind.Surface,
}


class FloorIRBuilder:
    """Object-API wrapper that accumulates regions + ops, then packs.

    Stages call :meth:`add_region` / :meth:`add_op`; :meth:`finish`
    serialises the buffer with the ``NIRF`` file_identifier.

    Splitting region registration from op emission lets ops reference
    regions by id without ordering constraints inside individual
    stages — the emitter walks every stage before any op is laid
    down on the wire.
    """

    def __init__(self, ctx: RenderContext) -> None:
        self.ctx = ctx
        self.regions: list[RegionT] = []
        self.ops: list[Any] = []  # OpEntryT once 1.b+ start emitting

    def add_region(
        self,
        *,
        id: str,
        kind: int,
        polygon: PolygonT,
        shape_tag: str = "",
    ) -> None:
        region = RegionT()
        region.id = id
        region.kind = kind
        region.polygon = polygon
        region.shapeTag = shape_tag
        self.regions.append(region)

    def add_op(self, op_entry: Any) -> None:
        self.ops.append(op_entry)

    def finish(self) -> bytes:
        ctx = self.ctx
        fir = FloorIRT()
        fir.major = _SCHEMA_MAJOR
        fir.minor = _SCHEMA_MINOR
        fir.widthTiles = ctx.level.width
        fir.heightTiles = ctx.level.height
        fir.cell = CELL
        fir.padding = PADDING
        fir.floorKind = _FLOOR_KIND_MAP[ctx.floor_kind]
        fir.theme = ctx.theme
        fir.baseSeed = ctx.seed
        fir.flags = _build_flags(ctx)
        fir.regions = list(self.regions)
        fir.ops = list(self.ops)

        builder = flatbuffers.Builder(1024)
        builder.Finish(fir.Pack(builder), _FILE_IDENTIFIER)
        return bytes(builder.Output())


def _build_flags(ctx: RenderContext) -> FeatureFlagsT:
    flags = FeatureFlagsT()
    flags.shadowsEnabled = ctx.shadows_enabled
    flags.hatchingEnabled = ctx.hatching_enabled
    flags.atmosphericsEnabled = ctx.atmospherics_enabled
    flags.macabreDetail = ctx.macabre_detail
    flags.vegetationEnabled = ctx.vegetation_enabled
    flags.interiorFinish = ctx.interior_finish
    return flags


def _shapely_to_polygon(geom: Any) -> PolygonT:
    """Pack a Shapely Polygon / MultiPolygon into the FB Polygon table.

    Each Shapely ring contributes one entry to ``rings`` slicing
    into the shared ``paths`` flat point list. Holes (interior rings)
    set ``is_hole`` so even-odd renderers reconstruct fills correctly.
    The trailing duplicate point Shapely returns from ``coords`` is
    preserved — downstream renderers expect closed rings.
    """
    polys = list(getattr(geom, "geoms", (geom,)))
    poly = PolygonT()
    poly.paths = []
    poly.rings = []
    for p in polys:
        _append_ring(poly, p.exterior.coords, is_hole=False)
        for hole in p.interiors:
            _append_ring(poly, hole.coords, is_hole=True)
    return poly


def _append_ring(poly: PolygonT, coords: Any, *, is_hole: bool) -> None:
    pts = list(coords)
    start = len(poly.paths)
    for x, y in pts:
        v = Vec2T()
        v.x = float(x)
        v.y = float(y)
        poly.paths.append(v)
    ring = PathRangeT()
    ring.start = start
    ring.count = len(pts)
    ring.isHole = is_hole
    poly.rings.append(ring)


def _coords_to_polygon(
    coords: list[tuple[float, float]],
) -> PolygonT:
    """Pack an explicit coord list into a single-ring FB Polygon.

    Used for room regions whose polygons come from non-Shapely
    helpers (rect bbox, ``_polygon_vertices`` for octagons,
    ``_trace_cave_boundary_coords`` for caves). The coord list must
    not contain a closing duplicate — the cave-room handler in
    ``ir_to_svg.py`` calls ``_smooth_closed_path`` directly on
    ``polygon.paths`` and that helper modulo-indexes around the
    ring; a duplicate first/last point would produce a phantom
    Bézier segment with zero arc length.
    """
    poly = PolygonT()
    poly.paths = []
    poly.rings = []
    _append_ring(poly, coords, is_hole=False)
    return poly


def _room_region_data(
    room: Any,
) -> tuple[list[tuple[float, float]], str] | None:
    """Compute polygon coords + shape_tag for one room's region.

    Mirrors the shape dispatch in
    ``_room_outlines._room_svg_outline`` /
    ``_shadows._room_shadow_svg`` so the IR-driven shadow handler
    reproduces the legacy element form byte-for-byte:

    - Rect rooms (and unsupported-shape fallbacks): polygon is the
      4-vertex pixel-space bbox, shape_tag is ``"rect"``. The
      shadow handler emits the simple ``<rect>`` form using the
      bbox.
    - Octagon rooms: polygon is the 8 vertices from
      ``_polygon_vertices``, shape_tag is ``"octagon"``.
    - Cave rooms with a valid boundary (≥ 4 traced coords):
      polygon is the pre-smoothing tile-corner coords, shape_tag
      is ``"cave"``. The handler runs ``_smooth_closed_path``.
      Caves with degenerate boundaries fall back to ``"rect"`` so
      the legacy ``_room_shadow_svg`` rect-fallback path matches.

    Returns ``None`` only when the shape isn't yet supported by
    1.b.2 — Pill / Temple / LShape / Cross / Hybrid / Circle. The
    starter fixtures don't exercise those, so no parity test
    triggers this branch; later commits add them when fixtures land.
    """
    rect = room.rect
    px = rect.x * CELL
    py = rect.y * CELL
    pw = rect.width * CELL
    ph = rect.height * CELL
    bbox = [
        (float(px), float(py)),
        (float(px + pw), float(py)),
        (float(px + pw), float(py + ph)),
        (float(px), float(py + ph)),
    ]

    shape = room.shape
    if isinstance(shape, CaveShape):
        coords = _trace_cave_boundary_coords(room.floor_tiles())
        if coords and len(coords) >= 4:
            return [(float(x), float(y)) for x, y in coords], "cave"
        # legacy falls back to room.rect — match that
        return bbox, "rect"

    if isinstance(shape, OctagonShape):
        verts = _polygon_vertices(shape, rect)
        return [(float(x), float(y)) for x, y in verts], "octagon"

    if isinstance(shape, RectShape):
        return bbox, "rect"

    # Pill / Temple / LShape / Cross / Hybrid / Circle — unsupported
    # in 1.b.2; the starter fixtures don't include them.
    return None


# ── Stages ──────────────────────────────────────────────────────


def emit_regions(builder: FloorIRBuilder) -> None:
    """Register polygon regions ops reference by id.

    1.a registered the foundation ``dungeon`` and ``cave`` regions.
    1.b.2 extends this to one Region per room (id matches
    ``room.id``) so the Room branch of ``_draw_shadow_from_ir`` can
    resolve geometry by reference. Hole / corridor regions land in
    1.c when ``HatchOp.region_in`` / ``region_out`` first need them.
    """
    ctx = builder.ctx
    if ctx.dungeon_poly is not None:
        builder.add_region(
            id="dungeon",
            kind=RegionKind.RegionKind.Dungeon,
            polygon=_shapely_to_polygon(ctx.dungeon_poly),
            shape_tag="dungeon",
        )
    if ctx.cave_wall_poly is not None:
        builder.add_region(
            id="cave",
            kind=RegionKind.RegionKind.Cave,
            polygon=_shapely_to_polygon(ctx.cave_wall_poly),
            shape_tag="cave",
        )
    for room in ctx.level.rooms:
        data = _room_region_data(room)
        if data is None:
            continue
        coords, shape_tag = data
        builder.add_region(
            id=room.id,
            kind=RegionKind.RegionKind.Room,
            polygon=_coords_to_polygon(coords),
            shape_tag=shape_tag,
        )


def emit_shadows(builder: FloorIRBuilder) -> None:
    """Phase 1.b.1: emit ShadowOp(Corridor); 1.b.2 adds Room kind."""
    from nhc.rendering._floor_layers import _emit_shadows_ir
    _emit_shadows_ir(builder)


def emit_hatch(builder: FloorIRBuilder) -> None:
    """Phase 1.c.1: emit HatchOp(Corridor); 1.c.2 adds Room kind."""
    from nhc.rendering._floor_layers import _emit_hatch_ir
    _emit_hatch_ir(builder)


def emit_walls_and_floors(builder: FloorIRBuilder) -> None:
    """Phase 1.d: emit WallsAndFloorsOp with pre-rendered smooth-room
    fragments, structured rect rooms / corridor tiles, and combined
    wall-segment / wall-extension strings."""
    from nhc.rendering._floor_layers import _emit_walls_and_floors_ir
    _emit_walls_and_floors_ir(builder)


def emit_terrain_tints(builder: FloorIRBuilder) -> None:
    """Phase 1.e: emit TerrainTintOp (per-tile WATER/GRASS/LAVA/CHASM
    tints + per-room hint washes, clipped to the dungeon interior)."""
    from nhc.rendering._floor_layers import _emit_terrain_tints_ir
    _emit_terrain_tints_ir(builder)


def emit_floor_grid(builder: FloorIRBuilder) -> None:
    """Stub — Phase 1.f lands FloorGridOp emit + handler."""


def emit_floor_detail(builder: FloorIRBuilder) -> None:
    """Stub — Phase 1.g lands the eight floor-detail ops."""


def emit_terrain_detail(builder: FloorIRBuilder) -> None:
    """Stub — Phase 1.h lands TerrainDetailOp emit + handler."""


def emit_stairs(builder: FloorIRBuilder) -> None:
    """Stub — Phase 1.i lands StairsOp emit + handler."""


def emit_surface_features(builder: FloorIRBuilder) -> None:
    """Stub — Phase 1.j lands the four surface-feature ops."""


# Pipeline order mirrors design/map_ir.md §18 (and §6 layer order).
# `emit_regions` is a foundation stage; the remaining nine each
# correspond to one entry in `_floor_layers.FLOOR_LAYERS`.
IR_STAGES: tuple[Callable[[FloorIRBuilder], None], ...] = (
    emit_regions,
    emit_shadows,
    emit_hatch,
    emit_walls_and_floors,
    emit_terrain_tints,
    emit_floor_grid,
    emit_floor_detail,
    emit_terrain_detail,
    emit_stairs,
    emit_surface_features,
)


# ── Public entry ────────────────────────────────────────────────


def build_floor_ir(
    level: Any,
    *,
    seed: int = 0,
    hatch_distance: float = 2.0,
    building_footprint: set[tuple[int, int]] | None = None,
    building_polygon: list[tuple[float, float]] | None = None,
    vegetation: bool = True,
) -> bytes:
    """Build a ``FloorIR`` FlatBuffer for ``level``.

    Mirrors :func:`nhc.rendering.svg.render_floor_svg` parameter for
    parameter so 1.k can call ``ir_to_svg(build_floor_ir(...))`` as a
    drop-in replacement for the legacy renderer.
    """
    ctx = build_render_context(
        level,
        seed=seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        building_footprint=building_footprint,
        building_polygon=building_polygon,
        hatch_distance=hatch_distance,
        vegetation=vegetation,
    )
    builder = FloorIRBuilder(ctx)
    for stage in IR_STAGES:
        stage(builder)
    return builder.finish()
