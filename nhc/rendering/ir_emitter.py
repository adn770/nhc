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
from nhc.dungeon.model import (
    CircleShape, HybridShape, LShape, OctagonShape, RectShape,
)
from nhc.rendering._cave_geometry import (
    _build_cave_wall_geometry, _trace_cave_boundary_coords,
)
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._render_context import (
    RenderContext, build_render_context,
)
from nhc.rendering._room_outlines import _hybrid_vertices, _polygon_vertices
from nhc.rendering._svg_helpers import CELL, PADDING
from nhc.rendering.ir._fb import FloorKind, RegionKind
from nhc.rendering.ir._fb.FeatureFlags import FeatureFlagsT
from nhc.rendering.ir._fb.FloorIR import FloorIRT
from nhc.rendering.ir._fb.BuildingExteriorWallOp import (
    BuildingExteriorWallOpT,
)
from nhc.rendering.ir._fb.BuildingInteriorWallOp import (
    BuildingInteriorWallOpT,
)
from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.EnclosureOp import EnclosureOpT
from nhc.rendering.ir._fb.EnclosureStyle import EnclosureStyle
from nhc.rendering.ir._fb.ExteriorWallOp import ExteriorWallOpT
from nhc.rendering.ir._fb.Gate import GateT
from nhc.rendering.ir._fb.GateStyle import GateStyle
from nhc.rendering.ir._fb.InteriorEdge import InteriorEdgeT
from nhc.rendering.ir._fb.InteriorWallMaterial import InteriorWallMaterial
from nhc.rendering.ir._fb.InteriorWallOp import InteriorWallOpT
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.PathRange import PathRangeT
from nhc.rendering.ir._fb.Polygon import PolygonT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.RoofOp import RoofOpT
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.TileCorner import TileCorner
from nhc.rendering.ir._fb.Vec2 import Vec2T
from nhc.rendering.ir._fb.WallMaterial import WallMaterial
from nhc.rendering.ir._fb.WallStyle import WallStyle


# Schema version stamped on every emitted buffer. Bumped per the
# §"Schema-evolution discipline" checklist in the migration plan
# whenever floor_ir.fbs changes (additive → minor, breaking → major).
SCHEMA_MAJOR = 3
SCHEMA_MINOR = 3
# Legacy aliases — Phase 2.3 promoted the constants to public names so
# the floor-artefact cache can validate disk-loaded IR against the
# running build's schema. Kept until the next IR refactor sweep.
_SCHEMA_MAJOR = SCHEMA_MAJOR
_SCHEMA_MINOR = SCHEMA_MINOR

_FILE_IDENTIFIER = b"NIR3"


_FLOOR_KIND_MAP: dict[str, int] = {
    "dungeon": FloorKind.FloorKind.Dungeon,
    "cave": FloorKind.FloorKind.Cave,
    "building": FloorKind.FloorKind.Building,
    "surface": FloorKind.FloorKind.Surface,
}


class FloorIRBuilder:
    """Object-API wrapper that accumulates regions + ops, then packs.

    Stages call :meth:`add_region` / :meth:`add_op`; :meth:`finish`
    serialises the buffer with the ``NIR3`` file_identifier.

    Splitting region registration from op emission lets ops reference
    regions by id without ordering constraints inside individual
    stages — the emitter walks every stage before any op is laid
    down on the wire.

    ``site`` is set when ``build_floor_ir`` is invoked for a site
    surface (Phase 8.4); the :func:`emit_site_overlays` stage then
    emits Site + Building regions, ``RoofOp`` per building, and a
    single ``EnclosureOp`` when the site has one.
    """

    def __init__(self, ctx: RenderContext) -> None:
        self.ctx = ctx
        self.regions: list[RegionT] = []
        self.ops: list[Any] = []  # OpEntryT once 1.b+ start emitting
        self.site: Any | None = None

    def add_region(
        self,
        *,
        id: str,
        kind: int,
        polygon: PolygonT,
        shape_tag: str = "",
        outline: OutlineT | None = None,
    ) -> None:
        region = RegionT()
        region.id = id
        region.kind = kind
        region.polygon = polygon
        region.shapeTag = shape_tag
        # Phase 1.22 of plans/nhc_pure_ir_plan.md — Region.outline
        # ships parallel to Region.polygon. When the caller hasn't
        # supplied an explicit outline (e.g. a Circle / Pill
        # descriptor variant), derive one from the polygon: the
        # vertex list mirrors ``polygon.paths`` and the multi-ring
        # partitioning mirrors ``polygon.rings`` only when the
        # polygon has more than one ring (single-ring outlines leave
        # ``rings`` empty per design/map_ir_v4e.md §4 — the v4e
        # shorthand: vertices IS the single ring).
        region.outline = outline or _polygon_to_outline(polygon)
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


def _polygon_to_outline(polygon: PolygonT | None) -> OutlineT:
    """Mirror a :class:`PolygonT` into an :class:`OutlineT`.

    Phase 1.22 — emitter-side helper for the Region.outline parallel
    population. Three contracts:

    - ``outline.vertices`` shares the same ``Vec2T`` list as
      ``polygon.paths`` (point-for-point; no closing duplicate
      added or removed — both fields preserve whatever the source
      coords carried).
    - ``outline.rings`` mirrors ``polygon.rings`` ONLY when the
      polygon has more than one ring (multi-ring dungeon polygon
      with cave-wall holes, or a multi-room cave system with inner
      cavities). Single-ring polygons collapse to the v4e
      shorthand: ``rings = []`` means "vertices IS the single
      ring" (see design/map_ir_v4e.md §4).
    - ``descriptor_kind = Polygon`` and ``closed = True`` — Region
      outlines are never open polylines (open partitions belong on
      ``InteriorWallOp``).

    Returns an :class:`OutlineT` with empty ``cuts`` (regions never
    carry cuts; cuts live on wall ops only). When ``polygon`` is
    ``None`` (defensive — no current call-site passes None), the
    returned Outline carries empty vertices / rings.
    """
    out = OutlineT()
    out.descriptorKind = OutlineKind.Polygon
    out.closed = True
    out.cuts = []
    if polygon is None:
        out.vertices = []
        out.rings = []
        return out
    out.vertices = list(polygon.paths or [])
    legacy_rings = list(polygon.rings or [])
    out.rings = list(legacy_rings) if len(legacy_rings) > 1 else []
    return out


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

    # Phase 1.23b — HybridShape Region carries the tessellated
    # polyline outline (matches what ``outline_from_hybrid`` ships
    # to the FloorOp / ExteriorWallOp). The legacy
    # ``smoothFillSvg`` arc-path FILL is retired by the same
    # commit; consumers reading region_ref now resolve the Hybrid
    # FILL through ``Region.outline.vertices`` polygon-rasteriser
    # instead of the SVG arc string.
    if isinstance(shape, HybridShape):
        verts = _hybrid_vertices(shape, rect)
        if verts:
            return [(float(x), float(y)) for x, y in verts], "hybrid"
        return None

    # Pill / Temple / LShape / Cross / Circle — still unsupported;
    # the starter fixtures do not include them.
    return None


# ── Phase 8.1: Site / Building region emit + footprint mask ────


# Sample count for the polygonised circle building footprint. 24 is
# coarse enough to stay cheap (24 polygon vertices, 24 mask scans
# per axis) and fine enough that the pyramid roof's RoofStyle.Simple
# render visually approximates a circle. Adjust if shingle running-
# bond on a 24-gon shows visible facets at fixture scale.
_CIRCLE_FOOTPRINT_VERTICES: int = 24


def _building_footprint_polygon_px(
    building: Any,
) -> list[tuple[float, float]]:
    """Outer footprint polygon for ``building`` in pixel coords.

    Mirrors :func:`nhc.rendering._roofs._footprint_polygon_px` for
    rect / octagon / L shapes. Phase 8.1 extends to circles
    (polygonised at :data:`_CIRCLE_FOOTPRINT_VERTICES` samples) so
    Circle buildings no longer skip — they paint a pyramid roof on
    the polygonised N-gon footprint per design/map_ir.md §7.14.

    Returns a list of ``(x, y)`` pixel-coord vertices, no closing
    duplicate.
    """
    shape = building.base_shape
    r = building.base_rect

    # Bare tile-pixel coords; the renderer's outer
    # ``translate(padding, padding)`` adds PADDING once. Baking it
    # in here would compound with the renderer's translate and
    # shift roofs / exterior walls by one tile (PADDING == CELL).
    def _tp(tx: float, ty: float) -> tuple[float, float]:
        return (tx * CELL, ty * CELL)

    if isinstance(shape, RectShape):
        return [
            _tp(r.x, r.y), _tp(r.x2, r.y),
            _tp(r.x2, r.y2), _tp(r.x, r.y2),
        ]
    if isinstance(shape, LShape):
        notch = shape._notch_rect(r)
        x0, y0, x1, y1 = r.x, r.y, r.x2, r.y2
        nx0, ny0, nx1, ny1 = (
            notch.x, notch.y, notch.x2, notch.y2,
        )
        if shape.corner == "nw":
            return [
                _tp(nx1, y0), _tp(x1, y0),
                _tp(x1, y1), _tp(x0, y1),
                _tp(x0, ny1), _tp(nx1, ny1),
            ]
        if shape.corner == "ne":
            return [
                _tp(x0, y0), _tp(nx0, y0),
                _tp(nx0, ny1), _tp(x1, ny1),
                _tp(x1, y1), _tp(x0, y1),
            ]
        if shape.corner == "sw":
            return [
                _tp(x0, y0), _tp(x1, y0),
                _tp(x1, y1), _tp(nx1, y1),
                _tp(nx1, ny0), _tp(x0, ny0),
            ]
        # "se"
        return [
            _tp(x0, y0), _tp(x1, y0),
            _tp(x1, ny0), _tp(nx0, ny0),
            _tp(nx0, y1), _tp(x0, y1),
        ]
    if isinstance(shape, OctagonShape):
        clip = max(1, min(r.width, r.height) // 3)
        return [
            _tp(r.x + clip, r.y),
            _tp(r.x2 - clip, r.y),
            _tp(r.x2, r.y + clip),
            _tp(r.x2, r.y2 - clip),
            _tp(r.x2 - clip, r.y2),
            _tp(r.x + clip, r.y2),
            _tp(r.x, r.y2 - clip),
            _tp(r.x, r.y + clip),
        ]
    if isinstance(shape, CircleShape):
        # Polygonise the inscribed circle at uniformly-spaced angles.
        # Centre is the rect centre in pixel coords; radius derives
        # from the same ``_diameter`` helper the tile rasteriser
        # uses, so the polygon visually wraps the actual floor tiles.
        import math
        d = shape._diameter(r)
        radius_px = (d / 2.0) * CELL
        cx_px = (r.x + r.width / 2.0) * CELL
        cy_px = (r.y + r.height / 2.0) * CELL
        n = _CIRCLE_FOOTPRINT_VERTICES
        return [
            (
                cx_px + radius_px * math.cos(2 * math.pi * i / n),
                cy_px + radius_px * math.sin(2 * math.pi * i / n),
            )
            for i in range(n)
        ]
    raise ValueError(
        f"unsupported Building base_shape for footprint polygon: "
        f"{type(shape).__name__}"
    )


def emit_site_region(
    builder: FloorIRBuilder, site_bounds_tiles: tuple[int, int, int, int],
) -> None:
    """Register the ``site`` Region for a surface IR.

    ``site_bounds_tiles`` is ``(x, y, w, h)`` in tile coords. The
    polygon is the pixel-space rect covering those tiles. id is the
    constant ``"site"``; ``RoofOp`` references buildings, not the
    site, so the Site region is purely informative — drives
    enclosure / fortification placement at later sub-phases.
    """
    x, y, w, h = site_bounds_tiles
    # Bare tile-pixel coords; the renderer's outer
    # ``translate(padding, padding)`` adds PADDING once.
    px = x * CELL
    py = y * CELL
    pw = w * CELL
    ph = h * CELL
    coords = [
        (float(px), float(py)),
        (float(px + pw), float(py)),
        (float(px + pw), float(py + ph)),
        (float(px), float(py + ph)),
    ]
    builder.add_region(
        id="site",
        kind=RegionKind.RegionKind.Site,
        polygon=_coords_to_polygon(coords),
        shape_tag="rect",
    )


# Roof tint palette — matches `nhc.rendering._roofs.ROOF_TINTS`.
# `emit_building_roofs` picks one entry per building from a
# splitmix64 stream seeded with `RoofOp.rng_seed`, so the SVG
# handler at `_draw_roof_from_ir` and the Rust PNG port pick the
# same shade.
_ROOF_TINTS: tuple[str, ...] = (
    "#8A8A8A",  # cool gray
    "#8A7A5A",  # warm tan
    "#8A5A3A",  # terracotta
    "#5A5048",  # charcoal
    "#7A5A3A",  # ochre
)


# splitmix64 constants — duplicated from ir_to_svg._SplitMix64 so
# the emit-side tint pick stays a single import-cycle-free helper.
# Both constants tables are unit-tested against the Rust crate's
# rng.rs in the Phase 0 / Phase 4 cross-language vectors.
_SM64_GOLDEN = 0x9E3779B97F4A7C15
_SM64_C1 = 0xBF58476D1CE4E5B9
_SM64_C2 = 0x94D049BB133111EB
_SM64_MASK = 0xFFFFFFFFFFFFFFFF


def _splitmix64_first(seed: int) -> int:
    """First u64 from a splitmix64 stream seeded with ``seed``."""
    state = (seed + _SM64_GOLDEN) & _SM64_MASK
    z = ((state ^ (state >> 30)) * _SM64_C1) & _SM64_MASK
    z = ((z ^ (z >> 27)) * _SM64_C2) & _SM64_MASK
    return z ^ (z >> 31)


def emit_building_roofs(
    builder: FloorIRBuilder, buildings: list[Any], base_seed: int,
) -> None:
    """Emit one ``RoofOp`` per entry in ``buildings``.

    Each RoofOp's ``rng_seed = base_seed + 0xCAFE + i`` matches the
    salt list in design/map_ir.md §10. ``tint`` is picked from
    :data:`_ROOF_TINTS` via a separate splitmix64 stream seeded
    with ``rng_seed ^ 0xC0FFEE`` so the rasteriser-side stream
    (seeded with ``rng_seed``) starts cleanly at the shingle-
    layout phase — no tint-slot offset for rasterisers to skip.

    ``style`` is :data:`RoofStyle.Simple` for every Phase 8.1
    building. Dome / WitchHat are forward-compat slots; the Rust
    handler falls back to Simple at render time.

    Pre-condition: corresponding ``Region(kind=Building, id=
    "building.<i>")`` entries must already be on ``builder.regions``
    (typically via :func:`emit_building_regions`).
    """
    for i, _ in enumerate(buildings):
        rng_seed = (base_seed + 0xCAFE + i) & _SM64_MASK
        tint_seed = (rng_seed ^ 0xC0FFEE) & _SM64_MASK
        tint = _ROOF_TINTS[
            _splitmix64_first(tint_seed) % len(_ROOF_TINTS)
        ]
        op = RoofOpT(
            regionRef=f"building.{i}",
            style=RoofStyle.Simple,
            tint=tint,
            rngSeed=rng_seed,
        )
        entry = OpEntryT()
        entry.opType = 16  # Op.RoofOp; explicit so this stays
                           # decoupled from a circular Op import.
        entry.op = op
        builder.add_op(entry)


def emit_site_enclosure(
    builder: FloorIRBuilder,
    polygon_tiles: list[tuple[float, float]],
    *,
    style: int,
    gates: list[tuple[int, float, float]] | None = None,
    base_seed: int,
    corner_style: int = CornerStyle.Merlon,
    gate_style: int = GateStyle.Wood,
) -> None:
    """Emit one ``EnclosureOp`` for a site's enclosure ring.

    ``polygon_tiles`` is the closed enclosure polygon in *tile*
    coords (no closing duplicate); the helper translates to bare
    tile-pixel space at emit time (``tile * CELL``). The renderer's
    outer ``translate(padding, padding)`` adds PADDING once at
    paint time.

    ``gates`` is a list of ``(edge_idx, t_center, half_px)`` triples
    matching the legacy ``site.enclosure.gates`` shape.
    ``base_seed`` is the floor's base RNG seed; per design/map_ir.md
    §10 the EnclosureOp salt is ``+ 0xE101`` (per-edge palisade
    streams seed at ``rng_seed + edge_idx``).

    No ``Region(kind=Site)`` registration is required for the
    enclosure to render — the polygon travels with the op — but
    callers typically call :func:`emit_site_region` first so other
    ops (roofs, gates) can reference the surface bounds.
    """
    if len(polygon_tiles) < 3:
        return
    coords_px = [
        (float(x * CELL), float(y * CELL))
        for x, y in polygon_tiles
    ]
    polygon = _coords_to_polygon(coords_px)
    # Phase 1.20 — legacy EnclosureOp no longer emitted; coverage
    # moved to ExteriorWallOp (WallStyle.Palisade /
    # FortificationMerlon, gates encoded as Cut entries) below.
    # Schema declaration stays until 1.22; back-compat reader in
    # transform/png/enclosure.rs keeps 3.x cached buffers rendering.

    # Phase 1.14 — parallel emission of ExteriorWallOp for enclosures.
    # Per EnclosureStyle.Palisade / EnclosureStyle.Fortification the
    # emitter ships one ExteriorWallOp { outline = closed polygon in
    # pixel coords, style = WallStyle.Palisade |
    # WallStyle.FortificationMerlon, corner_style = pass-through,
    # cuts = gates-as-cuts } alongside the legacy EnclosureOp. Gate
    # triples (edge_idx, t_center, half_px) are resolved to pixel-space
    # Cut pairs via cuts_for_enclosure_gates; GateStyle.Wood /
    # GateStyle.Portcullis map to CutStyle.WoodGate /
    # CutStyle.PortcullisGate.
    #
    # The new op lands AFTER the legacy EnclosureOp so the 1.16+
    # consumer switch can pick up the new path without reordering ops[];
    # mirrors Phase 1.12 (building ExteriorWallOp) and Phase 1.13
    # (InteriorWallOp).
    _ENCLOSURE_WALL_STYLE_MAP = {
        EnclosureStyle.Palisade: WallStyle.Palisade,
        EnclosureStyle.Fortification: WallStyle.FortificationMerlon,
    }
    if style in _ENCLOSURE_WALL_STYLE_MAP:
        from nhc.rendering._outline_helpers import (
            cuts_for_enclosure_gates, outline_from_polygon,
        )
        wall_op = ExteriorWallOpT()
        wall_op.outline = outline_from_polygon(coords_px)
        wall_op.outline.cuts = cuts_for_enclosure_gates(
            coords_px, list(gates or []), gate_style,
        )
        wall_op.style = _ENCLOSURE_WALL_STYLE_MAP[style]
        wall_op.cornerStyle = corner_style
        # Phase 1.20 — propagate the splitmix64 seed onto the new op
        # so the consumer can derive per-edge sub-seeds without
        # reading the paired EnclosureOp (which Phase 1.20 stops
        # emitting). The salt + mask match the legacy emission above.
        wall_op.rngSeed = (base_seed + 0xE101) & _SM64_MASK
        wall_entry = OpEntryT()
        wall_entry.opType = 22  # Op.ExteriorWallOp
        wall_entry.op = wall_op
        builder.add_op(wall_entry)


# ── Phase 8.3: Building wall ops ───────────────────────────────


_DOOR_SUPPRESSING_FEATURES = frozenset({
    "door_open", "door_closed", "door_locked",
})

_WALL_MATERIAL_MAP: dict[str, int] = {
    "brick": WallMaterial.Brick,
    "stone": WallMaterial.Stone,
}

_INTERIOR_WALL_MATERIAL_MAP: dict[str, int] = {
    "stone": InteriorWallMaterial.Stone,
    "brick": InteriorWallMaterial.Brick,
    "wood": InteriorWallMaterial.Wood,
}


def _coalesce_north_edges(
    norths: set[tuple[int, int]],
) -> list[tuple[int, int, int, int]]:
    """Merge consecutive north edges at the same y into one span.

    Mirrors building.py:_coalesce_north_edges. Output runs are
    ``(x0, y, end + 1, y)`` in tile-boundary coords.
    """
    runs: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for (x, y) in sorted(norths):
        if (x, y) in seen:
            continue
        end = x
        while (end + 1, y) in norths:
            end += 1
        for ix in range(x, end + 1):
            seen.add((ix, y))
        runs.append((x, y, end + 1, y))
    return runs


def _coalesce_west_edges(
    wests: set[tuple[int, int]],
) -> list[tuple[int, int, int, int]]:
    """Merge consecutive west edges at the same x into one span."""
    runs: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for (x, y) in sorted(wests):
        if (x, y) in seen:
            continue
        end = y
        while (x, end + 1) in wests:
            end += 1
        for iy in range(y, end + 1):
            seen.add((x, iy))
        runs.append((x, y, x, end + 1))
    return runs


def _edge_has_visible_door(
    level: Any, edge_x: int, edge_y: int, edge_side: str,
) -> bool:
    """Door-suppression filter mirroring building.py:_edge_has_visible_door."""
    from nhc.dungeon.model import canonicalize
    if edge_side == "north":
        candidates = [(edge_x, edge_y - 1), (edge_x, edge_y)]
    elif edge_side == "west":
        candidates = [(edge_x - 1, edge_y), (edge_x, edge_y)]
    else:
        return False
    for (tx, ty) in candidates:
        tile = level.tile_at(tx, ty)
        if tile is None:
            continue
        if tile.feature not in _DOOR_SUPPRESSING_FEATURES:
            continue
        if not tile.door_side:
            continue
        target = canonicalize(tx, ty, tile.door_side)
        if target == (edge_x, edge_y, edge_side):
            return True
    return False


def _tile_corner_delta(corner: int) -> tuple[int, int]:
    """``TileCorner`` int -> (Δx, Δy) for corner-grid pixel coords.

    Mirrors the rasteriser-side helper of the same name in
    ``nhc.rendering.ir_to_svg``; both consumers convert
    :type:`InteriorEdge` corner enums to integer offsets when
    materialising partition endpoints into pixel coords.
    """
    if corner == TileCorner.NW:
        return (0, 0)
    if corner == TileCorner.NE:
        return (1, 0)
    if corner == TileCorner.SE:
        return (1, 1)
    return (0, 1)  # SW


def _coalesced_interior_edges(
    level: Any,
) -> list[tuple[int, int, int, int, int, int]]:
    """Returns coalesced + door-filtered interior edges as
    ``(ax, ay, a_corner, bx, by, b_corner)`` int tuples.

    North edges run from the tile's NW corner to the next tile's
    NE corner; west edges from the tile's NW to SW. The
    a_corner / b_corner enum values are the FB ``TileCorner`` ints.
    """
    if not getattr(level, "interior_edges", None):
        return []
    norths: set[tuple[int, int]] = set()
    wests: set[tuple[int, int]] = set()
    for (x, y, side) in level.interior_edges:
        if _edge_has_visible_door(level, x, y, side):
            continue
        if side == "north":
            norths.add((x, y))
        elif side == "west":
            wests.add((x, y))
    out: list[tuple[int, int, int, int, int, int]] = []
    for (ax, ay, bx, by) in _coalesce_north_edges(norths):
        # NW -> NE: (ax + 0, ay + 0) to (bx - 1 + 1, ay + 0).
        out.append(
            (ax, ay, TileCorner.NW, bx - 1, ay, TileCorner.NE),
        )
    for (ax, ay, bx, by) in _coalesce_west_edges(wests):
        # NW -> SW: (ax + 0, ay + 0) to (ax + 0, by - 1 + 1).
        out.append(
            (ax, ay, TileCorner.NW, ax, by - 1, TileCorner.SW),
        )
    return out


def emit_building_walls(
    builder: FloorIRBuilder,
    building: Any,
    level: Any,
    *,
    base_seed: int,
    building_index: int = 0,
) -> None:
    """Emit BuildingExterior + BuildingInteriorWallOps for one Building floor.

    Skips ``BuildingExteriorWallOp`` when ``wall_material ==
    "dungeon"`` so the existing WallsAndFloorsOp dungeon-wall pass
    keeps painting them. Always emits ``BuildingInteriorWallOp``
    (possibly with empty edges so the rasteriser dispatch table
    still sees one op per building).

    Op-emit order is ``BuildingInteriorWallOp ->
    BuildingExteriorWallOp`` per design/map_ir.md §6.1. The curved
    or clipped exterior masonry overlays any partition extension
    into the rim zone, cleaning up T-junctions for circle /
    octagon buildings (mirrors ``building.py:97-104``).

    Pre-condition: a ``Region(kind=Building, id="building.<i>")``
    must already be on ``builder.regions`` (typically via
    :func:`emit_building_regions`).
    """
    region_id = f"building.{building_index}"
    # Interior partitions emit first so the exterior masonry
    # overlays them at the rim — see §6.1 paint order.
    interior_material = _INTERIOR_WALL_MATERIAL_MAP.get(
        getattr(building, "interior_wall_material", "stone"),
        InteriorWallMaterial.Stone,
    )
    edges = _coalesced_interior_edges(level)
    # Phase 1.20 — legacy BuildingInteriorWallOp no longer emitted;
    # coverage moved to InteriorWallOp (PartitionStone / Brick /
    # Wood) below. Schema declaration stays until 1.22; back-compat
    # reader in transform/png/building_interior_wall.rs keeps 3.x
    # cached buffers rendering.

    # Phase 1.13 — parallel emission of InteriorWallOp for partition
    # lines. Per coalesced + door-filtered interior partition edge in
    # ``edges`` the emitter ships one InteriorWallOp { outline:
    # open-polyline (closed=False) with the two corner-grid endpoints
    # in pixel coords, style: PartitionStone | PartitionBrick |
    # PartitionWood, cuts: [] } alongside the legacy
    # BuildingInteriorWallOp. Style maps 1:1 from the building's
    # ``interior_wall_material`` per design/map_ir_v4.md §3 / §7.
    #
    # Door cuts on partitions are pre-filtered upstream by
    # ``_edge_has_visible_door`` inside ``_coalesced_interior_edges``:
    # a partition edge that coincides with a visible door tile is
    # dropped from the coalesced list rather than emitted as a Cut
    # interval. The partition line is therefore split at the door's
    # tile edge — the gap is encoded as two separate InteriorWallOps
    # with no Cut between them — so cuts stay empty by contract.
    #
    # The new ops land BEFORE both the legacy and new exterior wall
    # ops to match the v4 paint order (slot 3 InteriorWallOp -> slot
    # 5 ExteriorWallOp, per design/map_ir_v4.md §4).
    _PARTITION_STYLE_MAP = {
        InteriorWallMaterial.Stone: WallStyle.PartitionStone,
        InteriorWallMaterial.Brick: WallStyle.PartitionBrick,
        InteriorWallMaterial.Wood: WallStyle.PartitionWood,
    }
    if edges:
        from nhc.rendering._outline_helpers import outline_from_polygon
        partition_style = _PARTITION_STYLE_MAP.get(
            interior_material, WallStyle.PartitionStone,
        )
        for (ax, ay, a_corner, bx, by, b_corner) in edges:
            adx, ady = _tile_corner_delta(a_corner)
            bdx, bdy = _tile_corner_delta(b_corner)
            point_a = ((ax + adx) * CELL, (ay + ady) * CELL)
            point_b = ((bx + bdx) * CELL, (by + bdy) * CELL)
            wall_op = InteriorWallOpT()
            wall_op.outline = outline_from_polygon(
                [point_a, point_b], closed=False,
            )
            wall_op.style = partition_style
            wall_entry = OpEntryT()
            wall_entry.opType = 21  # Op.InteriorWallOp
            wall_entry.op = wall_op
            builder.add_op(wall_entry)

    # Phase 1.20 — legacy BuildingExteriorWallOp no longer emitted;
    # coverage moved to ExteriorWallOp (MasonryBrick / MasonryStone)
    # below. Schema declaration stays until 1.22; back-compat reader
    # in transform/png/building_exterior_wall.rs keeps 3.x cached
    # buffers rendering. The "dungeon" wall_material short-circuit
    # still applies — for dungeon-walled buildings the new
    # ExteriorWallOp pass below also skips the exterior emit.
    wall_material = building.wall_material

    # Phase 1.12 — parallel emission of ExteriorWallOp for masonry
    # buildings. Per Region(kind=Building) with wall_material in
    # {"brick", "stone"} the emitter ships one ExteriorWallOp
    # { outline = building footprint polygon, style = MasonryBrick |
    # MasonryStone, corner_style = Merlon, cuts = [doors] } alongside
    # the legacy BuildingExteriorWallOp. The masonry wall styles map
    # 1:1 from the building's wall_material per design/map_ir_v4.md
    # §3 / §7. ``wall_material == "dungeon"`` skips both ops (the
    # dungeon perimeter walks the WallsAndFloorsOp pass instead);
    # non-masonry materials (``adobe`` / ``wood``) skip the new op
    # only — the v4 ``WallStyle`` enum reserves the masonry slots,
    # and adobe / wood will get dedicated styles in a future phase.
    #
    # Door cuts ride on the shape-agnostic
    # ``cuts_for_building_doors`` helper, which delegates to
    # ``cuts_for_room_doors`` after wrapping the building's
    # base_shape.floor_tiles(base_rect) in a Room-like adapter so the
    # door-side / pixel-edge logic stays in one place.
    #
    # The new op lands AFTER the legacy BuildingExteriorWallOp so the
    # 1.16+ consumer switch picks up the new path without reordering
    # ops[]; mirrors the Phase 1.10 cave ExteriorWallOp placement.
    _MASONRY_STYLE_MAP = {
        "brick": WallStyle.MasonryBrick,
        "stone": WallStyle.MasonryStone,
    }
    if wall_material in _MASONRY_STYLE_MAP:
        from nhc.rendering._outline_helpers import (
            cuts_for_building_doors, outline_from_polygon,
        )
        polygon = _building_footprint_polygon_px(building)
        coords = [(float(x), float(y)) for x, y in polygon]
        wall_op = ExteriorWallOpT()
        wall_op.outline = outline_from_polygon(coords)
        wall_op.outline.cuts = cuts_for_building_doors(building, level)
        wall_op.style = _MASONRY_STYLE_MAP[wall_material]
        wall_op.cornerStyle = CornerStyle.Merlon
        # Phase 1.20 — propagate the splitmix64 seed onto the new op
        # so the consumer can derive per-edge sub-seeds without
        # reading the paired BuildingExteriorWallOp (which Phase 1.20
        # stops emitting). Salt + mask match the legacy emission.
        wall_op.rngSeed = (
            base_seed + 0xBE71 + building_index
        ) & _SM64_MASK
        wall_entry = OpEntryT()
        wall_entry.opType = 22  # Op.ExteriorWallOp
        wall_entry.op = wall_op
        builder.add_op(wall_entry)


def emit_building_regions(
    builder: FloorIRBuilder, buildings: list[Any],
) -> None:
    """Register one ``Region(kind=Building)`` per entry in ``buildings``.

    ids are ``"building.<i>"`` so subsequent ``RoofOp`` /
    ``BuildingExteriorWallOp`` / ``BuildingInteriorWallOp`` entries
    reference the matching footprint by index. ``shape_tag`` is the
    base shape's ``type_name`` (``"rect"`` / ``"circle"`` /
    ``"octagon"`` / ``"l_shape_*"``); the rasteriser dispatches
    geometry from this string.
    """
    for i, b in enumerate(buildings):
        polygon = _building_footprint_polygon_px(b)
        coords = [(float(x), float(y)) for x, y in polygon]
        builder.add_region(
            id=f"building.{i}",
            kind=RegionKind.RegionKind.Building,
            polygon=_coords_to_polygon(coords),
            shape_tag=b.base_shape.type_name,
        )


def _point_in_polygon(
    px: float, py: float, polygon: list[tuple[float, float]],
) -> bool:
    """Even-odd ray casting. Cheap; allocation-free."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _collect_building_footprint_mask(
    regions: list[RegionT],
) -> set[tuple[int, int]]:
    """Tiles inside any ``Region(kind=Building)`` polygon.

    Used by floor-paint primitives (terrain_tints, floor_grid,
    floor_detail, terrain_detail, thematic_detail) to skip emit-time
    tile candidates whose centres fall inside a Building footprint.
    Roof + building-wall + building-floor ops own those tiles
    instead — see design/map_ir.md §6 for the layered ownership.

    Walks each Building region's bounding box in tile coords and
    point-in-polygon-tests each tile centre against the polygon.
    O(buildings × bbox_tiles); the starter site fixtures top out
    at ~40 buildings × ~25 tiles each = 1000 tests, well below
    perceptible.
    """
    mask: set[tuple[int, int]] = set()
    for region in regions:
        if region.kind != RegionKind.RegionKind.Building:
            continue
        if region.polygon is None:
            continue
        coords = [(v.x, v.y) for v in region.polygon.paths]
        if len(coords) < 3:
            continue
        # Tile bbox covering the polygon. Polygon coords are bare
        # tile-pixel space (``tile * CELL``); PADDING is applied by
        # the renderer's outer translate, not stored in the IR.
        min_x_px = min(c[0] for c in coords)
        max_x_px = max(c[0] for c in coords)
        min_y_px = min(c[1] for c in coords)
        max_y_px = max(c[1] for c in coords)
        x0 = int(min_x_px // CELL)
        x1 = int(max_x_px // CELL) + 1
        y0 = int(min_y_px // CELL)
        y1 = int(max_y_px // CELL) + 1
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                cx = (tx + 0.5) * CELL
                cy = (ty + 0.5) * CELL
                if _point_in_polygon(cx, cy, coords):
                    mask.add((tx, ty))
    return mask


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


def emit_building_overlays(builder: FloorIRBuilder) -> None:
    """Phase 8.5 — building-floor composite overlays.

    Fires when the level is one of ``site.buildings[i].floors[j]``
    (resolved by ``level.building_id`` matching a building id). The
    stage registers the Building's polygon as a Region and emits
    ``BuildingExteriorWallOp`` + ``BuildingInteriorWallOp`` per
    design/map_ir.md §6.1's Building paint order
    (``WallsAndFloorsOp -> BuildingInteriorWallOp ->
    BuildingExteriorWallOp``).

    Skips silently when there is no site context, when
    ``level.building_id`` is unset, or when the matching building
    is not present in ``site.buildings`` — those branches stay on
    the legacy ``render_building_floor_svg`` path until the rest of
    the migration retires it.
    """
    site = builder.site
    if site is None:
        return
    level = builder.ctx.level
    building_id = getattr(level, "building_id", None)
    if building_id is None:
        return
    match: tuple[int, Any] | None = None
    for i, b in enumerate(site.buildings):
        if b.id == building_id:
            match = (i, b)
            break
    if match is None:
        return
    building_index, building = match
    emit_building_regions(builder, [building])
    # Patch the freshly added region's id from "building.0" to
    # "building.<i>" so the BuildingExteriorWallOp's region_ref
    # (which uses building_index) resolves cleanly when there's a
    # mismatch between the emit_building_regions iteration index
    # and the canonical building index in site.buildings.
    builder.regions[-1].id = f"building.{building_index}"
    emit_building_walls(
        builder, building, level,
        base_seed=builder.ctx.seed,
        building_index=building_index,
    )


def emit_site_overlays(builder: FloorIRBuilder) -> None:
    """Phase 8.4 — site-surface composite overlays.

    Fires only when :class:`FloorIRBuilder.site` is set (i.e. the
    caller invoked ``build_floor_ir`` for a site surface and passed
    ``site=`` through). Emits, in order matching design/map_ir.md
    §6.1's structural-layer paint sequence:

    1. ``Region(kind=Site)`` covering the surface bounds.
    2. ``Region(kind=Building)`` per :attr:`Site.buildings` entry.
    3. ``RoofOp`` per building.
    4. ``EnclosureOp`` when ``site.enclosure`` is set and the
       enclosure kind is one we cover (palisade / fortification).

    Runs after ``emit_walls_and_floors`` so the structural-layer
    op order is `WallsAndFloorsOp → RoofOp → EnclosureOp`.
    """
    site = builder.site
    if site is None:
        return
    level = builder.ctx.level
    # Site overlays only fire on the surface itself; building-floor
    # IRs route through emit_building_overlays instead.
    if level is not getattr(site, "surface", None):
        return
    # Site region — pixel-rect bounds.
    emit_site_region(builder, (0, 0, level.width, level.height))
    # Building regions + roofs.
    if site.buildings:
        emit_building_regions(builder, list(site.buildings))
        emit_building_roofs(
            builder, list(site.buildings),
            base_seed=builder.ctx.seed,
        )
    # Optional enclosure.
    enclosure = getattr(site, "enclosure", None)
    if enclosure is None:
        return
    kind = enclosure.kind
    if kind == "palisade":
        style_int = EnclosureStyle.Palisade
    elif kind == "fortification":
        style_int = EnclosureStyle.Fortification
    else:
        # Forward-compat: unknown kind -> skip enclosure rather than
        # raise. Site SVG handles ruin / cottage / temple by skipping
        # the enclosure pass; mirror that here.
        return
    # Translate (gx, gy, length_tiles) -> (edge_idx, t_center, half_px)
    # by closest-edge projection — mirrors site_svg.py:_enclosure_fragments.
    poly_px = [
        (PADDING + x * CELL, PADDING + y * CELL)
        for (x, y) in enclosure.polygon
    ]
    n = len(poly_px)
    gates_param: list[tuple[int, float, float]] = []
    for (gx, gy, length_tiles) in enclosure.gates:
        gx_px = PADDING + gx * CELL
        gy_px = PADDING + gy * CELL
        best_idx = 0
        best_d = float("inf")
        best_t = 0.5
        for i in range(n):
            ax, ay = poly_px[i]
            bx, by = poly_px[(i + 1) % n]
            dx, dy = bx - ax, by - ay
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq == 0:
                continue
            t = max(0.0, min(1.0, (
                (gx_px - ax) * dx + (gy_px - ay) * dy
            ) / seg_len_sq))
            px = ax + dx * t
            py = ay + dy * t
            d = (px - gx_px) ** 2 + (py - gy_px) ** 2
            if d < best_d:
                best_d = d
                best_idx = i
                best_t = t
        gates_param.append(
            (best_idx, best_t, float(length_tiles) * CELL / 2.0),
        )
    emit_site_enclosure(
        builder,
        polygon_tiles=[
            (float(x), float(y)) for (x, y) in enclosure.polygon
        ],
        style=style_int,
        gates=gates_param,
        base_seed=builder.ctx.seed,
        corner_style=CornerStyle.Merlon,
    )


def emit_terrain_tints(builder: FloorIRBuilder) -> None:
    """Phase 1.e: emit TerrainTintOp (per-tile WATER/GRASS/LAVA/CHASM
    tints + per-room hint washes, clipped to the dungeon interior)."""
    from nhc.rendering._floor_layers import _emit_terrain_tints_ir
    _emit_terrain_tints_ir(builder)


def emit_floor_grid(builder: FloorIRBuilder) -> None:
    """Phase 1.f: emit FloorGridOp (Perlin-displaced wobbly grid
    overlay, fixed seed 41 per legacy)."""
    from nhc.rendering._floor_layers import _emit_floor_grid_ir
    _emit_floor_grid_ir(builder)


def emit_floor_detail(builder: FloorIRBuilder) -> None:
    """Phase 1.g: emit FloorDetailOp with pre-rendered room/corridor
    groups (Phase 1 transitional; Phase 4 refactors to per-tile
    structured ops when porting to Rust)."""
    from nhc.rendering._floor_layers import _emit_floor_detail_ir
    _emit_floor_detail_ir(builder)


def emit_thematic_detail(builder: FloorIRBuilder) -> None:
    """Phase 4 sub-step 4.b: emit ThematicDetailOp with the
    floor-tile candidate set + per-tile wall-corner bitmap. The
    dispatcher drives the painter from the IR (Python today,
    Rust at sub-step 4.e)."""
    from nhc.rendering._floor_layers import _emit_thematic_detail_ir
    _emit_thematic_detail_ir(builder)


def emit_terrain_detail(builder: FloorIRBuilder) -> None:
    """Phase 1.h: emit TerrainDetailOp with pre-rendered room/corridor
    groups (water / lava / chasm decorators)."""
    from nhc.rendering._floor_layers import _emit_terrain_detail_ir
    _emit_terrain_detail_ir(builder)


def emit_stairs(builder: FloorIRBuilder) -> None:
    """Phase 1.i: emit StairsOp (per-tile up/down stair markers)."""
    from nhc.rendering._floor_layers import _emit_stairs_ir
    _emit_stairs_ir(builder)


def emit_surface_features(builder: FloorIRBuilder) -> None:
    """Phase 1.j stub — starter fixtures produce no surface features.
    Future fixtures with wells / fountains / vegetation will need
    proper emit + handler."""
    from nhc.rendering._floor_layers import _emit_surface_features_ir
    _emit_surface_features_ir(builder)


# Pipeline order mirrors design/map_ir.md §18 (and §6 layer order).
# `emit_regions` is a foundation stage; the remaining nine each
# correspond to one entry in `_floor_layers.FLOOR_LAYERS`.
IR_STAGES: tuple[Callable[[FloorIRBuilder], None], ...] = (
    emit_regions,
    emit_shadows,
    emit_hatch,
    emit_walls_and_floors,
    # Phase 8.4: site-surface composite overlays. Inserts into the
    # `structural` layer dispatch *after* WallsAndFloorsOp so the
    # paint order is WallsAndFloorsOp -> RoofOp -> EnclosureOp on
    # site IRs (no-op for non-site IRs).
    emit_site_overlays,
    # Phase 8.5: building-floor composite overlays. Same shape as
    # 8.4 but for level == building.floors[j]; emits Building
    # region + interior + exterior wall ops.
    emit_building_overlays,
    emit_terrain_tints,
    emit_floor_grid,
    emit_floor_detail,
    emit_thematic_detail,
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
    site: Any | None = None,
) -> bytes:
    """Build a ``FloorIR`` FlatBuffer for ``level``.

    Mirrors :func:`nhc.rendering.svg.render_floor_svg` parameter for
    parameter so 1.k can call ``ir_to_svg(build_floor_ir(...))`` as a
    drop-in replacement for the legacy renderer.

    ``site`` (Phase 8.4) wires the site-surface composite overlay
    pass: when ``level is site.surface`` the emitter registers the
    Site + per-Building regions and emits the matching ``RoofOp`` /
    ``EnclosureOp`` ops. Passing a non-matching ``site`` (or
    ``None``) is a no-op — the gameplay dungeon / cave / building
    floors ride through unchanged.
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
    # Site context fires either of two emit-overlay stages:
    #   - emit_site_overlays  when level is site.surface (Phase 8.4)
    #   - emit_building_overlays when level is one of
    #     site.buildings[i].floors[j] (Phase 8.5)
    # Both stages are no-ops when builder.site stays None.
    if site is not None:
        is_surface = level is getattr(site, "surface", None)
        is_building_floor = (
            getattr(level, "building_id", None) is not None
            and any(
                b.id == level.building_id for b in site.buildings
            )
        )
        if is_surface or is_building_floor:
            builder.site = site
    for stage in IR_STAGES:
        stage(builder)
    return builder.finish()
