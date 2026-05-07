"""Floor IR emitter — region-registration + canonical v5 op stream.

:func:`build_floor_ir` walks a ``Level`` + :class:`RenderContext`
through three region-registration passes (:func:`emit_regions`,
:func:`emit_site_overlays`, :func:`emit_building_overlays`) that
populate ``builder.regions`` with dungeon / cave / corridor / room /
site / building / enclosure outlines. :meth:`FloorIRBuilder.finish`
then drives the canonical v5 emit pipeline
(:mod:`nhc.rendering.emit`) which reads ``builder.regions`` and
``builder.site`` directly to produce the schema-5 op stream.
"""

from __future__ import annotations

from typing import Any

import flatbuffers

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, LShape, OctagonShape,
    PillShape, RectShape, TempleShape,
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
from nhc.rendering.ir._fb.FloorIR import FloorIRT
from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.PathRange import PathRangeT
from nhc.rendering.ir._fb.Polygon import PolygonT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.Vec2 import Vec2T


# Schema version stamped on every emitted buffer. Bumped per the
# §"Schema-evolution discipline" checklist in the migration plan
# whenever floor_ir.fbs changes (additive → minor, breaking → major).
SCHEMA_MAJOR = 5
SCHEMA_MINOR = 0
# Legacy aliases — kept for back-compat with the floor-artefact cache,
# which validates disk-loaded IR against the running build's schema.
_SCHEMA_MAJOR = SCHEMA_MAJOR
_SCHEMA_MINOR = SCHEMA_MINOR

_FILE_IDENTIFIER = b"NIR5"


# Tile-corner integer codes — kept here as a local helper now that
# the schema cut dropped the FB ``TileCorner`` enum (corners no
# longer ride on the wire; partition endpoints carry pixel coords).
class _TileCorner:
    NW = 0
    NE = 1
    SE = 2
    SW = 3


TileCorner = _TileCorner


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
    single enclosure ``ExteriorWallOp`` when the site has one.
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
        kind: int = 0,
        polygon: PolygonT,
        shape_tag: str = "",
        outline: OutlineT | None = None,
    ) -> None:
        region = RegionT()
        region.id = id
        region.parentId = ""
        region.cuts = []
        region.shapeTag = shape_tag
        # When the caller hasn't supplied an explicit outline (e.g. a
        # Circle / Pill descriptor variant), derive one from the
        # polygon: the vertex list mirrors ``polygon.paths`` and the
        # multi-ring partitioning mirrors ``polygon.rings`` only when
        # the polygon has more than one ring (single-ring outlines
        # leave ``rings`` empty per design/map_ir_v4e.md §4 — the v4e
        # shorthand: vertices IS the single ring).
        if outline is None:
            outline = _polygon_to_outline(polygon)
        else:
            # Circle / Pill descriptors arrive with ``vertices = []``
            # because they ship via the rasterisers' native primitives.
            # Mirror the polygonised approximation from
            # ``polygon.paths`` into ``outline.vertices`` so
            # polygon-vertex consumers (room shadow handler, future
            # consumers) can read everything from ``Region.outline``.
            # Multi-ring polygons mirror their rings too. The
            # descriptor stays canonical for rasterisers that dispatch
            # on ``descriptor_kind``; vertices is a convenience copy
            # the descriptor consumers ignore.
            if not (outline.vertices or []) and polygon is not None:
                outline.vertices = list(polygon.paths or [])
                if not (outline.rings or []) and polygon.rings:
                    legacy_rings = list(polygon.rings)
                    if len(legacy_rings) > 1:
                        outline.rings = legacy_rings
        region.outline = outline
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
        fir.baseSeed = ctx.seed

        # ``emit_all(builder)`` walks the builder's ctx / regions /
        # site directly to populate the canonical v5 op stream.
        from nhc.rendering.emit import emit_all

        regions, ops = emit_all(self)
        fir.regions = regions
        fir.ops = ops

        builder = flatbuffers.Builder(1024)
        builder.Finish(fir.Pack(builder), _FILE_IDENTIFIER)
        return bytes(builder.Output())


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


def _corridor_component_exterior_coords(
    tiles: set[tuple[int, int]],
) -> list[tuple[float, float]]:
    """Return the exterior ring of a corridor connected component.

    Phase 1.26d-2 — mirrors :func:`_cave_raw_exterior_coords` for
    corridor-tile groups. Builds a 32-pixel tile box per (tx, ty),
    unions them, and returns the exterior ring of the merged
    polygon as raw coords (no Douglas-Peucker simplification, no
    closing duplicate). Returns ``[]`` for empty / degenerate
    inputs.

    NOTE: Use :func:`_corridor_component_rings` to capture interior
    holes too. This helper is preserved for back-compat with callers
    that only need the exterior boundary.
    """
    rings = _corridor_component_rings(tiles)
    return rings[0][0] if rings else []


def _corridor_component_rings(
    tiles: set[tuple[int, int]],
) -> list[tuple[list[tuple[float, float]], bool]]:
    """Return every ring (exterior + interior holes) of a corridor component.

    Phase 1.26d-3 — extends :func:`_corridor_component_exterior_coords`
    to capture topological holes. A connected corridor component can
    wrap around a room and form an annulus; the exterior ring alone
    misrepresents that geometry. Returns one ``(coords, is_hole)``
    tuple per ring: the exterior comes first (``is_hole = False``),
    then any interior rings (``is_hole = True``). Both ring kinds drop
    the closing duplicate point.

    Returns ``[]`` for empty / degenerate inputs.
    """
    if not tiles:
        return []
    from shapely.geometry import Polygon as _ShPoly
    from shapely.ops import unary_union as _unary_union

    boxes = []
    for tx, ty in tiles:
        px, py = tx * CELL, ty * CELL
        boxes.append(_ShPoly([
            (px, py), (px + CELL, py),
            (px + CELL, py + CELL), (px, py + CELL),
        ]))
    merged = _unary_union(boxes)
    if merged.is_empty:
        return []
    if hasattr(merged, "geoms"):
        merged = max(merged.geoms, key=lambda g: g.area)

    def _ring_coords(seq: Any) -> list[tuple[float, float]]:
        coords = list(seq)
        if coords and coords[-1] == coords[0]:
            coords = coords[:-1]
        return [(float(x), float(y)) for x, y in coords]

    out: list[tuple[list[tuple[float, float]], bool]] = []
    out.append((_ring_coords(merged.exterior.coords), False))
    for interior in merged.interiors:
        ring = _ring_coords(interior.coords)
        if len(ring) >= 4:
            out.append((ring, True))
    return out


def _multiring_polygon(
    rings: list[tuple[list[tuple[float, float]], bool] | list[tuple[float, float]]],
) -> PolygonT:
    """Pack one PolygonT carrying every input ring.

    Phase 1.26d-2 helper, extended at 1.26d-3 to support interior
    holes. Each input is either ``(coords, is_hole)`` or a bare coord
    list (treated as exterior). Single-exterior inputs collapse to
    the v4e shorthand: one ``rings[0]`` entry covering the whole
    flat ``paths`` list.
    """
    poly = PolygonT()
    poly.paths = []
    poly.rings = []
    for entry in rings:
        if isinstance(entry, tuple):
            ring_coords, is_hole = entry
        else:
            ring_coords, is_hole = entry, False
        _append_ring(poly, ring_coords, is_hole=is_hole)
    return poly


def _multiring_outline(
    rings: list[tuple[list[tuple[float, float]], bool] | list[tuple[float, float]]],
) -> OutlineT:
    """Build a multi-ring OutlineT.

    Phase 1.26d-2 helper, extended at 1.26d-3 to support interior
    holes. Each input is either ``(coords, is_hole)`` or a bare coord
    list (treated as exterior). The flat ``vertices`` list contains
    every ring's points in iteration order so each ring is
    addressable by ``(start, count)`` with the matching ``is_hole``
    flag preserved on the ``PathRange``. Mirrors
    :func:`_polygon_to_outline`'s convention: single-exterior outlines
    leave ``rings = []`` per the v4e shorthand; outlines with multiple
    rings (or any hole ring) populate one ``PathRange`` per ring.
    """
    out = OutlineT()
    out.descriptorKind = OutlineKind.Polygon
    out.closed = True
    out.cuts = []
    out.vertices = []
    out.rings = []
    for entry in rings:
        if isinstance(entry, tuple):
            ring_coords, is_hole = entry
        else:
            ring_coords, is_hole = entry, False
        start = len(out.vertices)
        for x, y in ring_coords:
            v = Vec2T()
            v.x = float(x)
            v.y = float(y)
            out.vertices.append(v)
        rng = PathRangeT()
        rng.start = start
        rng.count = len(ring_coords)
        rng.isHole = is_hole
        out.rings.append(rng)
    # v4e single-ring shorthand: collapse rings to [] when there's
    # exactly one ring AND that ring is not a hole (per
    # design/map_ir_v4e.md §4 — a single hole-only outline is
    # nonsensical, so this is purely a no-hole single-exterior check).
    if len(out.rings) == 1 and not out.rings[0].isHole:
        out.rings = []
    return out


def _room_region_data(
    room: Any,
) -> tuple[
    list[tuple[float, float]], str, OutlineT | None,
] | None:
    """Compute polygon coords + shape_tag (+ optional outline) for a room.

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
    - Hybrid / LShape / TempleShape / CrossShape rooms: polygon is
      the tessellated vertex list from the matching
      ``outline_from_*`` helper, shape_tag is the shape name.
    - CircleShape / PillShape rooms: polygon is a polygonised
      approximation (24-sample circle / rounded-rect bbox) so the
      polygon-shadow primitive has vertices to draw, AND the
      explicit Circle / Pill descriptor outline is returned in the
      third tuple element so ``Region.outline`` carries the
      canonical descriptor (rasterisers use the native primitive).

    The third tuple element is the explicit outline override: when
    not ``None`` the caller passes it to ``add_region`` so the
    auto-derived polygon outline is bypassed for descriptor variants.

    Returns ``None`` only when the room shape is not in the
    supported set above (defensive — every room shape currently in
    use is covered by 1.26d-1).
    """
    from nhc.rendering._outline_helpers import (
        outline_from_circle, outline_from_cross, outline_from_l_shape,
        outline_from_pill, outline_from_temple,
    )

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
            return (
                [(float(x), float(y)) for x, y in coords],
                "cave",
                None,
            )
        # legacy falls back to room.rect — match that
        return bbox, "rect", None

    if isinstance(shape, OctagonShape):
        verts = _polygon_vertices(shape, rect)
        return (
            [(float(x), float(y)) for x, y in verts],
            "octagon",
            None,
        )

    if isinstance(shape, RectShape):
        return bbox, "rect", None

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
            return (
                [(float(x), float(y)) for x, y in verts],
                "hybrid",
                None,
            )
        return None

    # Phase 1.26d-1 — polygon-variant shapes (L / Temple / Cross)
    # tessellate via the existing outline helpers; the resulting
    # vertex list serves both ``Region.polygon`` and the
    # auto-derived Polygon outline (no explicit override needed).
    if isinstance(shape, LShape):
        outline = outline_from_l_shape(room)
        verts = [(float(v.x), float(v.y)) for v in outline.vertices]
        return verts, "l_shape", None

    if isinstance(shape, TempleShape):
        outline = outline_from_temple(room)
        verts = [(float(v.x), float(v.y)) for v in outline.vertices]
        return verts, "temple", None

    if isinstance(shape, CrossShape):
        outline = outline_from_cross(room)
        verts = [(float(v.x), float(v.y)) for v in outline.vertices]
        return verts, "cross", None

    # Phase 1.26d-1 — descriptor variants (Circle / Pill). The
    # canonical Region.outline carries the descriptor (cx/cy/rx/ry)
    # so rasterisers use their native circle / pill primitive; the
    # parallel Region.polygon carries a polygonised approximation
    # so the shadow handler (which reads region.Polygon()) has
    # vertices for the polygon-shadow primitive.
    if isinstance(shape, CircleShape):
        import math
        d = shape._diameter(rect)
        radius_px = (d / 2.0) * CELL
        cx_px = (rect.x + rect.width / 2.0) * CELL
        cy_px = (rect.y + rect.height / 2.0) * CELL
        n = _CIRCLE_FOOTPRINT_VERTICES
        verts = [
            (
                cx_px + radius_px * math.cos(2 * math.pi * i / n),
                cy_px + radius_px * math.sin(2 * math.pi * i / n),
            )
            for i in range(n)
        ]
        return verts, "circle", outline_from_circle(room)

    if isinstance(shape, PillShape):
        # Polygonised pill bbox — the rounded corners are not
        # tessellated here (the polygon is for the shadow primitive
        # only; the canonical descriptor outline rasterises the
        # rounded section natively). Using the bbox quad keeps the
        # polygonisation cheap; if a parity test ever shows the
        # shadow's rect bbox is too coarse, swap in a 24-sample
        # rounded-rect tessellation.
        return bbox, "pill", outline_from_pill(room)

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
        polygon=_coords_to_polygon(coords),
        shape_tag="rect",
    )


# ── Building wall edge helpers (live, used by emit/stroke.py) ──


_DOOR_SUPPRESSING_FEATURES = frozenset({
    "door_open", "door_closed", "door_locked",
})

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
        if region.outline is None:
            continue
        coords = [(v.x, v.y) for v in (region.outline.vertices or [])]
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
            polygon=_shapely_to_polygon(ctx.dungeon_poly),
            shape_tag="dungeon",
        )
    # Phase 1.26b — emit one ``Region(kind=Cave, id="cave.<i>")`` per
    # disjoint cave system, mirroring the per-system FloorOp +
    # ExteriorWallOp emission in :func:`_emit_walls_and_floors_ir`.
    # Both call :func:`_collect_cave_systems` so the iteration order
    # matches and each system's ``regionRef = f"cave.{i}"`` resolves
    # cleanly. The Region's polygon and outline both come from the
    # SAME ``_cave_raw_exterior_coords(tile_group)`` data the cave
    # FloorOp / WallOp consume — so consumer dispatch via
    # ``regionRef`` produces byte-identical geometry to the
    # ``op.outline`` fallback (closing the 1.23a / 1.24 deferral).
    cave_tiles = ctx.cave_tiles or set()
    if cave_tiles:
        from nhc.rendering._cave_geometry import _cave_raw_exterior_coords
        from nhc.rendering._floor_layers import _collect_cave_systems
        for i, tile_group in enumerate(_collect_cave_systems(cave_tiles)):
            coords = _cave_raw_exterior_coords(tile_group)
            if not coords or len(coords) < 4:
                continue
            builder.add_region(
                id=f"cave.{i}",
                polygon=_coords_to_polygon(coords),
                shape_tag="cave",
            )
    # Phase 1.26d-2 (scope-reduced) — register ONE merged
    # ``Region(kind=Corridor, id="corridor")`` per floor when corridor
    # tiles exist. The Region's outline is multi-ring with one ring
    # per disjoint corridor connected component (single-component
    # corridors take the v4e single-ring shorthand: ``rings = []``,
    # vertices IS the single exterior ring). All rings are exterior
    # (``is_hole = false``) — corridors are not topologically
    # annular.
    #
    # Per-tile corridor FloorOps still ship with ``region_ref = ""``
    # at this commit (consumer continues reading each op's own
    # bbox outline); the Region exists symbolically so the
    # structural "corridor system has no Region" gap from
    # 1.24/1.26 §"Deferred coverage gaps" closes here. A follow-up
    # sub-phase migrates the per-tile FloorOps to one merged
    # FloorOp once Python ir_to_svg + Rust floor_op gain multi-ring
    # outline rendering.
    from nhc.rendering._floor_layers import (
        _collect_corridor_components, _collect_corridor_tiles,
    )
    corridor_tiles = _collect_corridor_tiles(ctx.level, cave_tiles)
    if corridor_tiles:
        components = _collect_corridor_components(corridor_tiles)
        # Phase 1.26d-3 — capture interior holes (annular corridor
        # components form when a corridor wraps a room). Each entry
        # is (coords, is_hole); exterior comes first.
        rings_per_component: list[
            tuple[list[tuple[float, float]], bool]
        ] = []
        for comp in components:
            for ring_coords, is_hole in _corridor_component_rings(comp):
                if ring_coords and len(ring_coords) >= 4:
                    rings_per_component.append((ring_coords, is_hole))
        if rings_per_component:
            polygon = _multiring_polygon(rings_per_component)
            outline = _multiring_outline(rings_per_component)
            builder.add_region(
                id="corridor",
                polygon=polygon,
                shape_tag="corridor",
                outline=outline,
            )
    for room in ctx.level.rooms:
        data = _room_region_data(room)
        if data is None:
            continue
        coords, shape_tag, outline_override = data
        builder.add_region(
            id=room.id,
            polygon=_coords_to_polygon(coords),
            shape_tag=shape_tag,
            outline=outline_override,
        )
    # Terrain regions — one per disjoint cluster of WATER / LAVA /
    # CHASM / GRASS tiles. The v5 emit_paints pipeline references
    # these by id ("water.<i>", "lava.<i>", ...) when it produces
    # PaintOp(Liquid:Water) / PaintOp(Special:Chasm) / etc. Cave
    # tiles stay on the cave region so the exclusion list keeps the
    # tile-set partitioning disjoint.
    from nhc.dungeon.model import Terrain
    from nhc.rendering._floor_layers import (
        _collect_terrain_systems, _terrain_cluster_coords,
    )
    for terrain_kind, region_prefix in (
        (Terrain.WATER, "water"),
        (Terrain.LAVA, "lava"),
        (Terrain.CHASM, "chasm"),
        (Terrain.GRASS, "grass"),
    ):
        systems = _collect_terrain_systems(
            ctx.level, terrain_kind, exclude=cave_tiles,
        )
        for i, cluster in enumerate(systems):
            coords = _terrain_cluster_coords(cluster)
            if not coords or len(coords) < 4:
                continue
            builder.add_region(
                id=f"{region_prefix}.{i}",
                polygon=_coords_to_polygon(coords),
                shape_tag=region_prefix,
            )

    # Stone-decorator regions — one ``Region(id="<prefix>.<i>")`` per
    # disjoint cluster of pavement-style tiles, mirroring the terrain
    # regions above. The matching ``emit_paints`` stone-decorator
    # branch references each region directly so the Rust
    # ``paint_op::draw`` handler (which silently drops empty
    # ``region_ref`` PaintOps) gets a real outline to clip against.
    # Without this, the keep courtyard's FLOOR + STREET tiles
    # rendered as page-background cream because the cobble PaintOp
    # was dropped at the consumer.
    from nhc.rendering._floor_detail import (
        _is_brick_tile, _is_cobble_tile, _is_field_overlay_tile,
        _is_flagstone_tile, _is_opus_romano_tile,
    )
    from nhc.rendering._floor_layers import _collect_predicate_components
    for predicate, region_prefix in (
        (_is_cobble_tile, "paved"),
        (_is_brick_tile, "brick"),
        (_is_flagstone_tile, "flagstone"),
        (_is_opus_romano_tile, "opus_romano"),
        (_is_field_overlay_tile, "fieldstone"),
    ):
        components = _collect_predicate_components(
            ctx.level, predicate, exclude=cave_tiles,
        )
        for i, cluster in enumerate(components):
            coords = _terrain_cluster_coords(cluster)
            if not coords or len(coords) < 4:
                continue
            builder.add_region(
                id=f"{region_prefix}.{i}",
                polygon=_coords_to_polygon(coords),
                shape_tag=region_prefix,
            )


def emit_building_overlays(builder: FloorIRBuilder) -> None:
    """Building-floor composite overlays.

    Fires when the level is one of ``site.buildings[i].floors[j]``
    (resolved by ``level.building_id`` matching a building id). The
    stage registers the Building's polygon as a Region and emits
    ``InteriorWallOp`` partitions + the masonry ``ExteriorWallOp``
    via :func:`emit_building_walls`.

    Skips silently when there is no site context, when
    ``level.building_id`` is unset, or when the matching building
    is not present in ``site.buildings``.
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
    # "building.<i>" so wall ops' region_ref resolves cleanly when
    # there's a mismatch between the emit_building_regions
    # iteration index and the canonical building index in
    # site.buildings.
    builder.regions[-1].id = f"building.{building_index}"
    # Schema-5 cut: emit_building_walls produced v4 ExteriorWallOp /
    # InteriorWallOp tables that are gone from the schema. The v5
    # emit pipeline (nhc.rendering.emit.stroke) now derives the
    # equivalent V5StrokeOps directly from level + builder.site.


def emit_site_overlays(builder: FloorIRBuilder) -> None:
    """Phase 8.4 — site-surface composite overlays.

    Fires only when :class:`FloorIRBuilder.site` is set (i.e. the
    caller invoked ``build_floor_ir`` for a site surface and passed
    ``site=`` through). Emits, in order matching design/map_ir.md
    §6.1's structural-layer paint sequence:

    1. ``Region(kind=Site)`` covering the surface bounds.
    2. ``Region(kind=Building)`` per :attr:`Site.buildings` entry.
    3. ``RoofOp`` per building.
    4. Enclosure ``ExteriorWallOp`` when ``site.enclosure`` is set
       and the enclosure kind is one we cover (palisade /
       fortification).
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
    # Building regions.
    if site.buildings:
        emit_building_regions(builder, list(site.buildings))
    # Enclosure region — registered when the site has a palisade /
    # fortification enclosure, so the v5 ``emit_strokes`` enclosure
    # branch's ``region_ref="enclosure"`` resolves cleanly.
    enclosure = getattr(site, "enclosure", None)
    if (
        enclosure is not None
        and enclosure.kind in ("palisade", "fortification")
        and len(enclosure.polygon) >= 3
    ):
        coords_px = [
            (float(x * CELL), float(y * CELL))
            for x, y in enclosure.polygon
        ]
        builder.add_region(
            id="enclosure",
            polygon=_coords_to_polygon(coords_px),
            shape_tag="enclosure",
        )
    # Schema-5 cut: emit_building_roofs and emit_site_enclosure
    # produced v4 RoofOp / ExteriorWallOp tables that are gone from
    # the schema. The v5 emit pipeline (nhc.rendering.emit.roof,
    # nhc.rendering.emit.stroke) now derives the equivalent
    # RoofOp / StrokeOp directly from builder.regions and
    # builder.site.


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

    Three region-registration passes populate ``builder.regions``:

    - :func:`emit_regions` — dungeon / cave / corridor / room
      regions (always runs).
    - :func:`emit_site_overlays` — site / building / enclosure
      regions (fires when ``level is site.surface``).
    - :func:`emit_building_overlays` — per-building region (fires
      when ``level.building_id`` matches one of ``site.buildings``).

    :meth:`FloorIRBuilder.finish` then walks the v5 emit pipeline
    (:mod:`nhc.rendering.emit`) which reads ``builder.regions`` and
    ``builder.site`` directly to produce the canonical op stream.
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
    emit_regions(builder)
    if builder.site is not None:
        emit_site_overlays(builder)
        emit_building_overlays(builder)
    return builder.finish()
