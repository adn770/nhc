"""IR → SVG transformer.

Cold-path transformer: consumes a ``FloorIR`` FlatBuffer and emits
the SVG string ``render_floor_svg`` used to produce. The byte-equal
gate in :mod:`tests.unit.test_ir_to_svg` is the contract that
protects every Phase 1–7 transition.

Phase 1.a wired the envelope (``<svg>`` header, background rect,
``<g transform>`` translate) and the dispatch loop. Phase 1.b.1
adds the ``ShadowOp(Corridor)`` handler and the
:func:`layer_to_svg` helper that grounds every per-layer parity
test in the rest of Phase 1. Subsequent layer commits (1.b.2 +
1.c–1.j) register one handler per op kind; Phase 1.k populates the
fixture ``.nir`` files and the integration parity gate flips green.

Op-handler signature::

    handler(op_entry: OpEntry, fir: FloorIR) -> list[str]

Each handler returns a list of SVG element-line strings that are
``\\n``-joined with the rest of the output, matching the legacy
``render_layers`` joining behaviour.
"""

from __future__ import annotations

import random
import re

from typing import Any, Callable

from nhc.rendering._svg_helpers import (
    BG, CAVE_FLOOR_COLOR, CELL, FLOOR_COLOR, GRID_WIDTH,
    HATCH_UNDERLAY, INK, WALL_WIDTH, _wobbly_grid_seg,
)
from nhc.rendering.ir._fb import (
    HatchKind, Op, ShadowKind, StairDirection, TerrainKind,
)
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.Op import OpCreator
from nhc.rendering.ir._fb.OpEntry import OpEntry
from nhc.rendering.ir._fb.Region import Region


# Maps Op union tag → handler. Layer commits 1.b–1.j each register
# one entry; an op surfacing without a handler is a contract
# violation, not an extensibility hook.
_OP_HANDLERS: dict[int, Callable[[OpEntry, FloorIR], list[str]]] = {}


# Layer render order. Mirrors `nhc/rendering/_floor_layers.py:FLOOR_LAYERS`
# (sorted by `Layer.order`) so `ir_to_svg` emits the per-layer comment
# stats and op output in the same sequence as the legacy
# `render_layers`. Source of truth: design/map_ir.md §6.
_LAYER_ORDER: tuple[str, ...] = (
    "shadows",
    "hatching",
    "structural",
    "terrain_tints",
    "floor_grid",
    "floor_detail",
    "thematic_detail",
    "terrain_detail",
    "stairs",
    "surface_features",
)


# Element-tag counter mirroring `_pipeline._OPEN_TAG` so the IR-
# driven renderer reports the same per-layer element count in its
# `<!-- layer.NAME: N elements, M bytes -->` comment.
_OPEN_TAG = re.compile(r"<[a-zA-Z]")


# Maps layer name → set of Op union tags belonging to that layer.
# Source: design/map_ir.md §6 layer ordering. Each layer commit
# adds an entry as it lands its first op; the dict is the contract
# the per-layer parity tests dispatch against.
_LAYER_OPS: dict[str, frozenset[int]] = {
    "shadows": frozenset({Op.Op.ShadowOp}),
    "hatching": frozenset({Op.Op.HatchOp}),
    "structural": frozenset({
        # Phase 1.26f — fresh IR ships only the new ops here. The
        # legacy ops (WallsAndFloorsOp / EnclosureOp /
        # BuildingExteriorWallOp / BuildingInteriorWallOp) stay in
        # the filter so 3.x cached buffers continue rendering via
        # their back-compat handlers.
        Op.Op.WallsAndFloorsOp,
        # Phase 1.26f — FloorOp dispatches as a standalone op handler
        # (was previously consumed inside the WallsAndFloorsOp
        # handler). Each FloorOp emits its fill fragment(s) in IR
        # op-order so the floors-under-walls paint sequence holds.
        Op.Op.FloorOp,
        # Phase 8.1: per-building roof primitives. Site IRs emit
        # RoofOps after the floor + wall ops so the roof paints
        # over them — see design/map_ir.md §6.1.
        Op.Op.RoofOp,
        Op.Op.EnclosureOp,
        Op.Op.BuildingExteriorWallOp,
        Op.Op.BuildingInteriorWallOp,
        # Phase 1.16: new 4.0 wall ops. InteriorWallOp (partition
        # lines, slot 3) and ExteriorWallOp (perimeter walls, slot 5)
        # are dispatched here.
        # Phase 1.16b-3: CorridorWallOp added for DungeonInk corridor
        # walls; ExteriorWallOp DungeonInk now active.
        Op.Op.ExteriorWallOp,
        Op.Op.InteriorWallOp,
        Op.Op.CorridorWallOp,
    }),
    "terrain_tints": frozenset({Op.Op.TerrainTintOp}),
    "floor_grid": frozenset({Op.Op.FloorGridOp}),
    "floor_detail": frozenset({
        Op.Op.FloorDetailOp,
        # The structured decorator pipeline (cobblestone / brick /
        # flagstone / opus_romano / field_stone / cart_tracks /
        # ore_deposit) rides in the floor_detail layer slot via
        # DecoratorOp's per-variant vector tables.
        Op.Op.DecoratorOp,
    }),
    "thematic_detail": frozenset({Op.Op.ThematicDetailOp}),
    "terrain_detail": frozenset({Op.Op.TerrainDetailOp}),
    "stairs": frozenset({Op.Op.StairsOp}),
    "surface_features": frozenset({
        Op.Op.WellFeatureOp,
        Op.Op.FountainFeatureOp,
        Op.Op.TreeFeatureOp,
        Op.Op.BushFeatureOp,
    }),
}


_BARE_SKIP_LAYERS: frozenset[str] = frozenset({
    "floor_detail",
    "thematic_detail",
    "terrain_detail",
    "surface_features",
})


def ir_to_svg(buf: bytes, *, bare: bool = False) -> str:
    """Render a ``FloorIR`` FlatBuffer to its legacy SVG output.

    Layers stream in :data:`_LAYER_ORDER` sequence, each prefixed
    by a ``<!-- layer.NAME: N elements, M bytes -->`` comment that
    matches the legacy ``_pipeline.render_layers`` shape — the
    self-describing stats the byte-equal parity gate locks in.

    ``bare=True`` (Phase 2.5 of plans/nhc_ir_migration_plan.md)
    elides the decoration layers (``floor_detail``,
    ``terrain_detail``, ``surface_features``) entirely — same
    "skip layer, skip comment" shape that the inactive-flag path
    uses for shadows / hatching. Used by the ``?bare=1`` query
    parameter on the .svg route for /admin debug visualisation,
    where seeing the underlying geometry matters more than seeing
    the cobblestone overlay.
    """
    fir = _root_or_raise(buf)
    cell = fir.Cell()
    padding = fir.Padding()
    w = fir.WidthTiles() * cell + 2 * padding
    h = fir.HeightTiles() * cell + 2 * padding

    parts: list[str] = [
        (
            f'<svg width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" '
            'xmlns="http://www.w3.org/2000/svg">'
        ),
        f'<rect width="100%" height="100%" fill="{BG}"/>',
        f'<g transform="translate({padding},{padding})">',
    ]
    flags = fir.Flags()
    inactive: set[str] = set()
    if flags is not None:
        # Shadows + hatching are gated on RenderContext flags in
        # the legacy `FLOOR_LAYERS`. When inactive, `render_layers`
        # skips the layer entirely (no comment, no fragments) — the
        # IR matches by suppressing the comment header here. The
        # other seven layers default to active.
        if not flags.ShadowsEnabled():
            inactive.add("shadows")
        if not flags.HatchingEnabled():
            inactive.add("hatching")
    if bare:
        inactive |= _BARE_SKIP_LAYERS
    for layer_name in _LAYER_ORDER:
        if layer_name in inactive:
            continue
        layer_frags = _dispatch_ops(
            fir, op_filter=_LAYER_OPS[layer_name],
        )
        joined = "".join(layer_frags)
        n_elements = len(_OPEN_TAG.findall(joined))
        n_bytes = len(joined)
        parts.append(
            f"<!-- layer.{layer_name}: {n_elements} elements, "
            f"{n_bytes} bytes -->"
        )
        parts.extend(layer_frags)
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


def layer_to_svg(buf: bytes, *, layer: str) -> str:
    """Render only the ops belonging to ``layer``.

    Returns the joined SVG fragment for the layer, no envelope.
    Per-layer parity tests in 1.b–1.j use this to compare the
    IR-rendered slice against the legacy paint-helper output for
    one layer in isolation, so a regression bisects to a single
    layer commit instead of "something broke between 1.b and 1.j".
    """
    if layer not in _LAYER_OPS:
        raise KeyError(
            f"unknown layer: {layer!r}; known layers: "
            f"{sorted(_LAYER_OPS)}"
        )
    fir = _root_or_raise(buf)
    return "\n".join(_dispatch_ops(fir, op_filter=_LAYER_OPS[layer]))


def layer_to_svg_full(buf: bytes, *, layer: str) -> str:
    """Render ``layer`` wrapped in the standard SVG envelope.

    The envelope is the same one ``ir_to_svg`` writes:
    ``<svg viewBox=...>``, the ``BG`` background rect, and a
    ``<g transform="translate(padding,padding)">`` group around
    the per-layer fragments. Used by the Phase 5 PNG parity
    harness — feeding the result into ``resvg-py`` produces the
    baseline that ``nhc_render.ir_to_png(buf, layer=...)`` is
    measured against.
    """
    if layer not in _LAYER_OPS:
        raise KeyError(
            f"unknown layer: {layer!r}; known layers: "
            f"{sorted(_LAYER_OPS)}"
        )
    fir = _root_or_raise(buf)
    cell = fir.Cell()
    padding = fir.Padding()
    w = fir.WidthTiles() * cell + 2 * padding
    h = fir.HeightTiles() * cell + 2 * padding
    body = "\n".join(_dispatch_ops(fir, op_filter=_LAYER_OPS[layer]))
    return (
        f'<svg width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="100%" height="100%" fill="{BG}"/>'
        f'<g transform="translate({padding},{padding})">'
        f'{body}'
        '</g></svg>'
    )


def _root_or_raise(buf: bytes) -> FloorIR:
    if not FloorIR.FloorIRBufferHasIdentifier(buf, 0):
        raise ValueError(
            "Buffer does not carry the NIR3 file_identifier — is "
            "this a FloorIR buffer at the current schema major?"
        )
    return FloorIR.GetRootAs(buf, 0)


def _dispatch_ops(
    fir: FloorIR,
    *,
    op_filter: frozenset[int] | None,
) -> list[str]:
    parts: list[str] = []
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        op_type = entry.OpType()
        if op_filter is not None and op_type not in op_filter:
            continue
        handler = _OP_HANDLERS.get(op_type)
        if handler is None:
            raise NotImplementedError(
                f"no IR→SVG handler registered for Op tag {op_type}; "
                "the matching Phase 1 layer commit must register one"
            )
        parts.extend(handler(entry, fir))
    return parts


# ── Op handlers ─────────────────────────────────────────────────


def _draw_shadow_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Reproduce ``_render_room_shadows`` / ``_render_corridor_shadows``.

    Phase 4.2 — the per-tile corridor rects and the per-shape
    room shadows live in
    ``crates/nhc-render/src/primitives/shadow.rs`` and are reached
    via the four ``nhc_render.draw_*_shadow*`` functions. The Python
    side resolves the room region's shape_tag from the IR and
    dispatches; the legacy 0.08-opacity / +3-offset / #000000-ink
    constants are baked into the Rust side.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    kind = op.kind
    if kind == ShadowKind.ShadowKind.Corridor:
        tiles = [(t.x, t.y) for t in op.tiles]
        return nhc_render.draw_corridor_shadows(tiles)
    if kind == ShadowKind.ShadowKind.Room:
        return [_draw_room_shadow(op, fir)]
    raise ValueError(f"unknown ShadowKind: {kind}")


def _draw_room_shadow(op: Any, fir: FloorIR) -> str:  # type: ignore[name-defined]
    """Reproduce ``_shadows._room_shadow_svg`` from the IR.

    Dispatches on the referenced region's ``shape_tag`` and routes
    to the matching Rust primitive (rect / octagon / cave). The
    cave→rect fallback that
    :func:`nhc.rendering.ir_emitter._room_region_data` collapses
    into ``shape_tag == "rect"`` is handled by the rect branch.
    """
    import nhc_render

    region = _find_region(fir, op.regionRef)
    if region is None:
        raise ValueError(
            f"ShadowOp(Room) references unknown region "
            f"{op.regionRef!r}; emit_regions must register one"
        )
    shape_tag = region.ShapeTag()
    coords = _outline_vertices_to_coords(region.Outline())

    if shape_tag == b"rect":
        return nhc_render.draw_room_shadow_rect(coords)
    if shape_tag == b"octagon":
        return nhc_render.draw_room_shadow_octagon(coords)
    if shape_tag == b"cave":
        return nhc_render.draw_room_shadow_cave(coords)
    # Phase 1.23b — HybridShape Region carries a tessellated
    # polygon (the same dense polyline ``outline_from_hybrid``
    # produces). Routes to the polygon-shadow primitive used by
    # octagons; the legacy ``_shadows._room_shadow_svg`` path
    # emits the same `<g><polygon points=…/></g>` structure for
    # any polygon-shaped room.
    if shape_tag == b"hybrid":
        return nhc_render.draw_room_shadow_octagon(coords)
    # Phase 1.26d-1 — L / Temple / Cross / Circle / Pill rooms
    # all route through the polygon-shadow primitive. The Circle
    # and Pill descriptor outlines can't be passed to a polygon
    # primitive, so the shadow handler reads the polygonised
    # ``Region.polygon`` (24-sample circle / bbox quad) — produced
    # by ``_room_region_data`` alongside the canonical descriptor
    # outline.
    if shape_tag in (
        b"l_shape", b"temple", b"cross", b"circle", b"pill",
    ):
        return nhc_render.draw_room_shadow_octagon(coords)

    raise NotImplementedError(
        f"Room shadow handler for shape_tag {shape_tag!r} not "
        "implemented; the starter fixtures only exercise rect / "
        "octagon / cave / hybrid / l_shape / temple / cross / "
        "circle / pill"
    )


def _find_region(fir: FloorIR, region_ref: bytes) -> Region | None:
    """Linear scan of regions[] by id.

    Cheap for the starter fixtures (~20 regions × ~20 room ops per
    parity test). Revisit with a regions-by-id dict if a fixture
    grows past a couple hundred regions and the lookup shows up in
    the fast-suite timing budget.
    """
    for j in range(fir.RegionsLength()):
        region = fir.Regions(j)
        if region.Id() == region_ref:
            return region
    return None


def _outline_vertices_to_coords(outline: Any) -> list[tuple[float, float]]:
    """Flatten an FB Outline's vertices into an (x, y) coord list.

    Phase 1.26g — replaces the legacy ``_polygon_paths_to_coords``
    that read ``Region.polygon.paths``. Outline.vertices carries
    the same vertex list as the source polygon (point-for-point
    mirror, including the polygonised approximation embedded in
    Circle / Pill descriptors per the 1.26g emitter change).
    Multi-ring outlines are flattened in vertex order; callers
    that care about ring boundaries should walk ``outline.rings``
    explicitly (see ``_dungeon_clip_defs``).
    """
    return [
        (outline.Vertices(i).X(), outline.Vertices(i).Y())
        for i in range(outline.VerticesLength())
    ]


_OP_HANDLERS[Op.Op.ShadowOp] = _draw_shadow_from_ir


def _draw_hatch_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Dispatch to the corridor / room / hole hatch handler.

    Sub-step 1.e (plan §8) routes Corridor + Room through the Rust
    `nhc_render.draw_hatch_*` entry points; the relaxed parity gate
    (1.a invariants + 1.f snapshot lock) replaces the legacy
    byte-equal contract for these branches. Hole stays schema-
    reserved — the emitter never produces it under the Phase 1
    contract.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    if op.kind == HatchKind.HatchKind.Corridor:
        return _draw_hatch_corridor(op)
    if op.kind == HatchKind.HatchKind.Room:
        return _draw_hatch_room(op, fir)
    if op.kind == HatchKind.HatchKind.Hole:
        # Schema-reserved; the legacy `_render_hole_hatching` is
        # never wired into `_hatching_paint` in Phase 1, so a Hole
        # op surfacing here is a contract violation.
        raise NotImplementedError(
            "Hole hatching is schema-reserved but unused in Phase "
            "1; the emitter must not produce HatchOp(kind=Hole)"
        )
    raise ValueError(f"unknown HatchKind: {op.kind}")


def _draw_hatch_corridor(op: Any) -> list[str]:
    """Corridor halo — Phase 4 sub-step 1.e: delegate to Rust.

    The Rust impl
    (``crates/nhc-render/src/primitives/hatch.rs::draw_hatch_corridor``)
    owns the per-tile painting (stone scatter, section
    partitioning, Perlin-wobbled strokes); this handler wraps the
    three returned fragment buckets in the legacy
    ``<g opacity="...">`` envelopes. The relaxed parity gate
    (sub-step 1.a invariants + 1.f snapshot lock) is the contract
    going forward — byte-equal-with-legacy is dropped.
    """
    import nhc_render

    tiles = [(t.x, t.y) for t in op.tiles]
    if not tiles:
        return []
    tile_fills, hatch_lines, hatch_stones = (
        nhc_render.draw_hatch_corridor(tiles, op.seed)
    )
    out: list[str] = []
    if tile_fills:
        out.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        out.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        out.append(f'<g>{"".join(hatch_stones)}</g>')
    return out


def _draw_hatch_room(op: Any, fir: FloorIR) -> list[str]:
    """Room halo — Phase 4 sub-step 1.e: delegate to Rust.

    Sub-step 1.b shifted the candidate walk + Perlin distance
    filter to the emitter; sub-step 1.d ported the painting
    passes to Rust
    (``crates/nhc-render/src/primitives/hatch.rs::draw_hatch_room``).
    This handler calls into Rust for the three SVG fragment
    buckets and wraps each in its opacity envelope. The Hole kind
    is unreachable at the dispatcher level; this branch only
    handles Room.

    Phase 1.21a: the legacy ``<g clip-path="url(#hatch-clip)">``
    wrapper around the buckets is dropped — the stamp model
    relies on paint order to cover any tile-bbox bleed at smooth-
    room corners. ``HatchOp`` paints early in IR_STAGES (before
    ``emit_walls_and_floors``) so floor / wall ops render OVER
    the hatch and naturally clip its bleed inside the dungeon
    polygon.
    """
    import nhc_render

    tiles = [(t.x, t.y) for t in op.tiles]
    if not tiles:
        return []

    is_outer_raw = op.isOuter
    if is_outer_raw is None:
        is_outer = [False] * len(tiles)
    else:
        # ``isOuter`` may surface as a numpy array; normalise to a
        # list[bool] for the PyO3 boundary.
        is_outer = [bool(b) for b in is_outer_raw]

    tile_fills, hatch_lines, hatch_stones = (
        nhc_render.draw_hatch_room(tiles, is_outer, op.seed)
    )
    if not (tile_fills or hatch_lines or hatch_stones):
        return []

    out: list[str] = []
    if tile_fills:
        out.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        out.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        out.append(f'<g>{"".join(hatch_stones)}</g>')
    return out


_OP_HANDLERS[Op.Op.HatchOp] = _draw_hatch_from_ir


def _collect_consumed_floor_ops(fir: FloorIR) -> list[Any]:
    """Collect all consumed FloorOp entries from ``fir.ops[]``.

    Returns a list of ``OpEntry`` objects whose type is ``FloorOp``
    and whose style is in {``FloorStyle.DungeonFloor``,
    ``FloorStyle.CaveFloor``}. Phase 1.15b extends the original
    DungeonFloor-only filter to include CaveFloor now that the
    cave-emitter corrigendum (commit 41a04da) emits one merged
    FloorOp whose vertex list matches the single ``cave_region``
    path that the legacy consumer produces.

    Linear scan — cheap for the fixture sizes (< 300 ops).
    """
    from nhc.rendering.ir._fb import FloorStyle as FloorStyleMod

    FS = FloorStyleMod.FloorStyle
    _CONSUMED_FLOOR_STYLES = frozenset({
        FS.DungeonFloor, FS.CaveFloor, FS.WoodFloor,
    })

    result = []
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.FloorOp:
            continue
        op = OpCreator(entry.OpType(), entry.Op())
        if op.style in _CONSUMED_FLOOR_STYLES:
            result.append(entry)
    return result


def _draw_floor_op_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Emit SVG for a single ``FloorOp`` stamp.

    Phase 1.15 — first commit where pixels flow through the new 4.0
    ops. Reads ``op.outline`` (Outline) and ``op.style``
    (FloorStyle), dispatches on ``outline.descriptor_kind``:

    * ``Polygon`` + ``DungeonFloor``: ``<polygon points="…">`` with
      ``fill="#FFFFFF" stroke="none"``. Used for rect rooms,
      corridor tiles, octagon/L-shape/temple smooth rooms.
    * ``Polygon`` + ``CaveFloor``: reconstruct the centripetal
      Catmull-Rom bezier path from the vertex list (same
      ``_smooth_closed_path`` the legacy cave emitter uses) and
      inject ``fill="#F5EBD8" stroke="none" fill-rule="evenodd"``.
      Produces a byte-identical SVG path to the legacy path.
    * ``Circle``: ``<circle cx="…" cy="…" r="…" fill="…"
      stroke="none"/>``.
    * ``Pill``: ``<rect x="…" y="…" width="…" height="…" rx="…"
      ry="…" fill="…" stroke="none"/>``.

    Phase 1.23a — region-keyed dispatch: when ``op.region_ref`` is
    non-empty AND resolves to a Region with a populated outline,
    the geometry comes from ``region.outline`` instead of
    ``op.outline``. This is the v4e canonical path; the
    ``op.outline`` fallback covers per-tile corridor FloorOps
    (no per-tile Region) and 3.x cached buffers that pre-date the
    field.

    Returns a single-element ``list[str]`` per the handler
    convention. Returns ``[]`` when the outline is absent or
    degenerate (< 2 vertices for polygon; zero radius for circle).
    """
    from nhc.rendering._floor_detail import WOOD_FLOOR_FILL
    from nhc.rendering.ir._fb import FloorStyle as FloorStyleMod, OutlineKind as OutlineKindMod
    from nhc.rendering.ir._fb.Outline import OutlineT

    op = OpCreator(entry.OpType(), entry.Op())
    outline = op.outline
    region_ref = op.regionRef or b""
    if region_ref:
        region = _find_region(fir, region_ref)
        if region is not None:
            region_outline_fb = region.Outline()
            if region_outline_fb is not None:
                outline = OutlineT.InitFromObj(region_outline_fb)
    if outline is None:
        return []

    style = op.style
    if style == FloorStyleMod.FloorStyle.CaveFloor:
        color = CAVE_FLOOR_COLOR
    elif style == FloorStyleMod.FloorStyle.WoodFloor:
        color = WOOD_FLOOR_FILL
    else:
        color = FLOOR_COLOR

    kind = outline.descriptorKind

    if kind == OutlineKindMod.OutlineKind.Circle:
        cx = outline.cx
        cy = outline.cy
        r = outline.rx
        if r <= 0:
            return []
        return [
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{color}" stroke="none"/>'
        ]

    if kind == OutlineKindMod.OutlineKind.Pill:
        cx = outline.cx
        cy = outline.cy
        rx = outline.rx
        ry = outline.ry
        if rx <= 0 or ry <= 0:
            return []
        x = cx - rx
        y = cy - ry
        w = rx * 2
        h = ry * 2
        radius = min(rx, ry)
        return [
            f'<rect x="{x:.1f}" y="{y:.1f}" '
            f'width="{w:.1f}" height="{h:.1f}" '
            f'rx="{radius:.1f}" ry="{radius:.1f}" '
            f'fill="{color}" stroke="none"/>'
        ]

    # Polygon descriptor (the default)
    verts = outline.vertices
    if not verts or len(verts) < 2:
        return []

    coords = [(v.x, v.y) for v in verts]

    if style == FloorStyleMod.FloorStyle.CaveFloor:
        # Run the buffer+jitter+smooth pipeline on the raw exterior ring
        # stored in FloorOp.outline.vertices.  The pipeline is seeded
        # from fir.BaseSeed() + 0x5A17E5 — the same offset
        # _render_context.py:117 uses — so the output is byte-identical
        # to the legacy _build_cave_wall_geometry path.
        path_el = _cave_path_from_outline(coords, fir.BaseSeed())
        return [
            path_el.replace(
                "/>",
                f' fill="{CAVE_FLOOR_COLOR}" stroke="none" '
                f'fill-rule="evenodd"/>',
            )
        ]

    # DungeonFloor polygon. Phase 1.26d-3 — multi-ring outlines (the
    # merged corridor FloorOp's disjoint connected components, plus
    # interior holes for annular corridors that wrap a room) build a
    # single ``<path>`` with one ``M…L…Z`` subpath per ring and
    # ``fill-rule="evenodd"`` so interior holes punch out correctly.
    # Single-ring outlines (rect rooms, smooth polygon rooms,
    # single-component corridors via the v4e shorthand) keep emitting
    # one ``<polygon>`` (no fill-rule needed for a simple convex /
    # non-self-intersecting fill).
    rings = outline.rings or []
    if rings:
        subpaths: list[str] = []
        for ring in rings:
            start = int(ring.start)
            count = int(ring.count)
            if count < 2:
                continue
            ring_coords = coords[start:start + count]
            d_parts = [f"M{ring_coords[0][0]:.1f},{ring_coords[0][1]:.1f}"]
            for x, y in ring_coords[1:]:
                d_parts.append(f"L{x:.1f},{y:.1f}")
            d_parts.append("Z")
            subpaths.append(" ".join(d_parts))
        if not subpaths:
            return []
        d = " ".join(subpaths)
        return [
            f'<path d="{d}" fill="{color}" stroke="none" '
            f'fill-rule="evenodd"/>'
        ]

    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    return [
        f'<polygon points="{points}" '
        f'fill="{color}" stroke="none"/>'
    ]


_OP_HANDLERS[Op.Op.FloorOp] = _draw_floor_op_from_ir


def _cave_path_from_outline(
    vertices: list[tuple[float, float]],
    base_seed: int,
) -> str:
    """Reconstruct the cave SVG path from raw tile-boundary coords.

    Applies the same buffer(0.3*CELL) + _densify_ring + _jitter_ring_outward
    + _smooth_closed_path pipeline that :func:`_build_cave_wall_geometry`
    uses.  ``vertices`` must be the raw (un-simplified) exterior ring
    produced by :func:`_cave_raw_exterior_coords` and stored in
    ``FloorOp.outline.vertices`` / ``ExteriorWallOp.outline.vertices``.

    The RNG is seeded with ``base_seed + 0x5A17E5`` — the same offset
    ``nhc/rendering/_render_context.py:117`` uses — so the jitter
    sequence is deterministic and byte-identical to the legacy output.

    Returns a ``<path d="…"/>`` string (no fill/stroke attrs); callers
    inject the appropriate presentation attributes.

    Both the CaveFloor FloorOp fill branch and the CaveInk ExteriorWallOp
    stroke branch call this helper so fill and stroke share identical
    geometry.
    """
    from shapely.geometry import Polygon as _ShPoly
    from shapely.geometry.polygon import orient as _shapely_orient

    from nhc.rendering._cave_geometry import (
        _densify_ring,
        _jitter_ring_outward,
        _ring_to_subpath,
    )

    if len(vertices) < 4:
        return '<path d=""/>'

    poly = _ShPoly(vertices)
    if not poly.is_valid or poly.is_empty:
        return '<path d=""/>'

    buffer_r = CELL * 0.3
    simplify_tol = CELL * 0.15
    step = CELL * 0.8

    inflated = poly.buffer(buffer_r, join_style='round', quad_segs=8)
    if inflated.is_empty:
        return '<path d=""/>'
    if hasattr(inflated, 'geoms'):
        inflated = max(inflated.geoms, key=lambda g: g.area)

    simp = inflated.simplify(simplify_tol, preserve_topology=True)
    simp = _shapely_orient(simp, sign=1.0)
    if simp.is_empty or not hasattr(simp, 'exterior'):
        return '<path d=""/>'

    rng = random.Random(base_seed + 0x5A17E5)

    # Exterior ring (CCW after orient sign=1.0)
    ext = list(simp.exterior.coords)
    if ext and ext[0] == ext[-1]:
        ext = ext[:-1]
    ext_d = _densify_ring(ext, step)
    ext_j = _jitter_ring_outward(
        ext_d, poly, rng, is_hole=False,
        direction_poly=simp,
    )
    subpaths = []
    s = _ring_to_subpath(ext_j)
    if s:
        subpaths.append(s)

    # Holes (for cave regions with interior voids)
    jittered_holes: list[list[tuple[float, float]]] = []
    for hole in simp.interiors:
        h = list(hole.coords)
        if h and h[0] == h[-1]:
            h = h[:-1]
        h_d = _densify_ring(h, step)
        h_j = _jitter_ring_outward(
            h_d, poly, rng, is_hole=True,
            direction_poly=simp,
        )
        s = _ring_to_subpath(h_j)
        if s:
            subpaths.append(s)
            jittered_holes.append(h_j)

    if not subpaths:
        return '<path d=""/>'
    return f'<path d="{" ".join(subpaths)}"/>'


def _draw_walls_and_floors_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_walls_and_floors`` with Phase 1.15 floor switch.

    Phase 1.15 — partial scope (rect rooms + corridors + smooth
    DungeonFloor shapes). Extended in Phase 1.15b to include CaveFloor;
    the real-consumer follow-up (Phase 1.15b→) replaces the provisional
    cave_region shortcut with the genuine buffer+jitter+smooth pipeline.

    When consumed FloorOps (DungeonFloor or CaveFloor) are present:

    1. Collect all consumed FloorOp entries and emit their floor SVG
       **first** (floors-under-walls paint order keeps walls on top).
       CaveFloor FloorOps are dispatched through ``_draw_floor_op_from_ir``
       which calls ``_cave_path_from_outline`` for the full pipeline.
    2. Pass empty ``rect_rooms`` and ``corridor_tiles`` to Rust (the
       FloorOps cover these).
    3. ``smooth_fills`` passes through unchanged — it may contain
       non-FloorOp content (wood-floor tile rects in building floors)
       that has no FloorOp equivalent.
    4. Pass empty ``cave_region`` to Rust so it does not also emit cave
       fill/stroke — the CaveFloor FloorOp consumer owns that output.
       CaveInk stroke is emitted by the ``ExteriorWallOp`` CaveInk
       handler (``_draw_exterior_wall_op_from_ir``) via the same
       ``_cave_path_from_outline`` pipeline.

    ``FloorOp`` is NOT a standalone dispatch handler — it is consumed
    here so that the combined floor+wall emit sequence mirrors the
    legacy floor-before-wall ordering.

    When no consumed FloorOp is present (3.x cached buffers), all
    inputs pass through unchanged for full back-compat.

    Phase 4.4 — partial port. Structural geometry (smooth-room
    outlines, cave region path, wall extension data) is computed
    Python-side during emission and travels into Rust as
    pre-rendered SVG fragment strings; only the stroke-emission
    envelope (rect emission for corridor tiles + rect rooms, and
    the two ``/>``-replacement wraps around the cave region) lives
    in ``crates/nhc-render/src/primitives/walls_and_floors.rs``.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    wall_segments = [_to_str(s) for s in (op.wallSegments or [])]
    smooth_walls = [_to_str(s) for s in (op.smoothWallSvg or [])]
    smooth_fills = [_to_str(s) for s in (op.smoothFillSvg or [])]
    cave_region = _to_str(op.caveRegion)
    wall_extensions_d = _to_str(op.wallExtensionsD)

    consumed_floor_ops = _collect_consumed_floor_ops(fir)
    if consumed_floor_ops:
        # Phase 1.26f — FloorOp / ExteriorWallOp / InteriorWallOp /
        # CorridorWallOp dispatch as standalone handlers; this branch
        # only runs for 3.x cached buffers that ship a parallel-
        # emission WAF alongside the new ops. Skip the floor /
        # stub emission (the standalone handlers own them) and let
        # the WAF emit only what its still-populated legacy fields
        # carry — typically nothing for fresh-but-cached buffers.
        from nhc.rendering.ir._fb import FloorStyle as FloorStyleMod
        FS = FloorStyleMod.FloorStyle
        has_cave_floor_op = any(
            OpCreator(e.OpType(), e.Op()).style == FS.CaveFloor
            for e in consumed_floor_ops
        )

        rect_rooms = [
            (rr.x, rr.y, rr.w, rr.h) for rr in (op.rectRooms or [])
        ]
        floors_covered = (
            len(consumed_floor_ops)
            >= len(rect_rooms)
            + len(op.corridorTiles or [])
            + len(smooth_fills)
        )
        has_consumed_dungeon = _has_consumed_dungeon_exterior_wall_ops(fir)

        return nhc_render.draw_walls_and_floors(
            [],
            [],
            [] if floors_covered else smooth_fills,
            "" if has_cave_floor_op else cave_region,
            [] if has_consumed_dungeon else smooth_walls,
            "" if has_consumed_dungeon else wall_extensions_d,
            [] if has_consumed_dungeon else wall_segments,
        )

    # Legacy fallback — 3.x cached buffers without FloorOp.
    corridor_tiles = [
        (t.x, t.y) for t in (op.corridorTiles or [])
    ]
    rect_rooms = [
        (rr.x, rr.y, rr.w, rr.h) for rr in (op.rectRooms or [])
    ]
    return nhc_render.draw_walls_and_floors(
        corridor_tiles,
        rect_rooms,
        smooth_fills,
        cave_region,
        smooth_walls,
        wall_extensions_d,
        wall_segments,
    )


def _to_str(value: Any) -> str:
    """FB strings surface as bytes; decode to str at the boundary."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8")
    return value


_OP_HANDLERS[Op.Op.WallsAndFloorsOp] = _draw_walls_and_floors_from_ir


def _draw_terrain_tint_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_terrain_tints``.

    Phase 4.1 — the per-tile tint rect emission and the per-room
    wash emission live in
    ``crates/nhc-render/src/primitives/terrain_tints.rs`` and are
    reached via ``nhc_render.draw_terrain_tints``. The Python
    side resolves the palette from ``fir.theme`` (display data,
    stays Python-side) and owns the dungeon-interior clip
    envelope (the IR's region polygon stays Python-side too —
    only the layer's RNG-free string emission moved to Rust).
    """
    import nhc_render
    from nhc.rendering.terrain_palette import get_palette

    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []

    theme = _to_str(fir.Theme())
    palette = get_palette(theme)
    # Discriminant-keyed palette (matches `TerrainKind` in
    # `floor_ir.fbs`: Water=1, Lava=2, Chasm=3, Grass=4; None=0
    # is the schema sentinel and never appears in emitted tiles).
    palette_map = {
        TerrainKind.TerrainKind.Water: (
            palette.water.tint, palette.water.tint_opacity),
        TerrainKind.TerrainKind.Lava: (
            palette.lava.tint, palette.lava.tint_opacity),
        TerrainKind.TerrainKind.Chasm: (
            palette.chasm.tint, palette.chasm.tint_opacity),
        TerrainKind.TerrainKind.Grass: (
            palette.grass.tint, palette.grass.tint_opacity),
    }
    tiles = [
        (tile.x, tile.y, int(tile.kind))
        for tile in (op.tiles or [])
    ]
    washes = [
        (w.x, w.y, w.w, w.h, _to_str(w.color), float(w.opacity))
        for w in (op.roomWashes or [])
    ]
    tint_rects, wash_rects = nhc_render.draw_terrain_tints(
        tiles, palette_map, washes,
    )

    # Phase 1.25 — prefer op.regionRef (canonical 4.0 name);
    # fall back to op.clipRegion for 3.x cached buffers.
    clip_id = _to_str(op.regionRef) or _to_str(op.clipRegion)
    if tint_rects:
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Outline(), "terrain-clip"))
                out.append('<g clip-path="url(#terrain-clip)">')
                out.extend(tint_rects)
                out.append("</g>")
            else:
                out.extend(tint_rects)
        else:
            out.extend(tint_rects)

    out.extend(wash_rects)
    return out


def _dungeon_clip_defs(outline: Any, clip_id: str) -> str:
    """Build the legacy ``_dungeon_interior_clip`` defs element.

    Phase 1.26g — reads from ``Region.outline`` (rings + vertices)
    instead of ``Region.polygon`` (rings + paths). The two carry
    identical geometry post-1.22; this commit migrates the
    consumer to drop the ``Region.polygon`` bypass-read in
    preparation for the 4.0 cut at 1.27.

    Multi-ring outlines (e.g. dungeon polygons with cave-wall
    holes) walk every ring once. Single-ring outlines take the v4e
    shorthand (``rings = []``, vertices IS the single ring) and
    walk the full vertex list as one M / L / Z subpath.
    ``fill-rule="evenodd"`` so the holes cut the clipped region.
    """
    verts = outline.Vertices
    rings_count = outline.RingsLength()
    if rings_count == 0:
        # v4e shorthand: vertices IS the single ring.
        n = outline.VerticesLength()
        if n < 2:
            clip_d = ""
        else:
            v0 = verts(0)
            clip_d = f"M{v0.X():.0f},{v0.Y():.0f} "
            clip_d += " ".join(
                f"L{verts(j).X():.0f},{verts(j).Y():.0f}"
                for j in range(1, n)
            )
            clip_d += " Z "
    else:
        clip_d = ""
        for i in range(rings_count):
            ring = outline.Rings(i)
            start = ring.Start()
            count = ring.Count()
            if count < 2:
                continue
            v0 = verts(start)
            clip_d += f"M{v0.X():.0f},{v0.Y():.0f} "
            clip_d += " ".join(
                f"L{verts(start + j).X():.0f},{verts(start + j).Y():.0f}"
                for j in range(1, count)
            )
            clip_d += " Z "
    return (
        f'<defs><clipPath id="{clip_id}">'
        f'<path d="{clip_d}" fill-rule="evenodd"/>'
        f'</clipPath></defs>'
    )


_OP_HANDLERS[Op.Op.TerrainTintOp] = _draw_terrain_tint_from_ir


def _draw_floor_grid_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_floor_grid``.

    Phase 3 canary — the per-edge wobbly-grid segment generator
    lives in ``crates/nhc-render/src/primitives/floor_grid.rs`` and
    is reached via ``nhc_render.draw_floor_grid``. The byte-equal
    parity gate is ``tests/unit/test_emit_floor_grid_parity.py``.
    Python keeps ownership of the SVG envelope (clip-path defs,
    ``<path>`` wrapping) because those bits are not RNG-sensitive
    and the IR's region polygon stays Python-side.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    width = fir.WidthTiles()
    height = fir.HeightTiles()
    tiles = [
        (tile.x, tile.y, bool(tile.isCorridor))
        for tile in (op.tiles or [])
    ]
    room_d, corridor_d = nhc_render.draw_floor_grid(
        width, height, tiles, op.seed,
    )

    style = (
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{GRID_WIDTH}" '
        f'opacity="0.7" stroke-linecap="round"'
    )

    out: list[str] = []
    if room_d:
        # Phase 1.25 — prefer op.regionRef (canonical 4.0 name);
        # fall back to op.clipRegion for 3.x cached buffers.
        clip_id = _to_str(op.regionRef) or _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Outline(), "grid-clip"))
                out.append(
                    f'<path d="{room_d}" '
                    f'{style} clip-path="url(#grid-clip)"/>'
                )
            else:
                out.append(f'<path d="{room_d}" {style}/>')
        else:
            out.append(f'<path d="{room_d}" {style}/>')

    if corridor_d:
        out.append(f'<path d="{corridor_d}" {style}/>')

    return out


_OP_HANDLERS[Op.Op.FloorGridOp] = _draw_floor_grid_from_ir


def _draw_wood_floor_from_ir(op, fir: FloorIR) -> list[str]:
    """Reproduce ``_render_wood_floor`` from structured fields.

    Phase 9.2b: drives the wood-floor SVG output from
    ``op.woodTiles`` (per-tile rect fill), ``op.woodBuildingPolygon``
    (chamfer / curved-wall outline for octagon and circle floors)
    and ``op.woodRooms`` (per-room rects for the parquet plank +
    grain generators). Output stays byte-equal to the legacy
    ``_render_wood_floor`` walk by replaying the same row-major
    iteration and the ``random.Random(seed)`` draw order on
    grain (per-strip jittered offsets) followed by seams (per-
    plank lengths).
    """
    from nhc.rendering._floor_detail import (
        WOOD_GRAIN_LINES_PER_STRIP, WOOD_GRAIN_OPACITY,
        WOOD_GRAIN_STROKE_WIDTH, WOOD_PLANK_LENGTH_MAX,
        WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_WIDTH_PX,
        WOOD_SEAM_WIDTH, _wood_palette_for_room,
    )

    out: list[str] = []
    rng = random.Random(int(op.seed))

    # Phase 1.25 — prefer op.regionRef (canonical 4.0 name);
    # fall back to op.clipRegion for 3.x cached buffers.
    clip_id = _to_str(op.regionRef) or _to_str(op.clipRegion)
    region = (
        _find_region(fir, clip_id.encode()) if clip_id else None
    )
    has_dungeon_clip = region is not None

    # Wood base fill is emitted by WallsAndFloorsOp (structural
    # layer) per design/map_ir.md §6.1; this handler only paints
    # the per-room grain + plank seams (floor_detail layer).
    #
    # SVG only allows one ``clip-path`` per element — pick exactly
    # one. The dungeon Region's outline tracks the building
    # polygon for building floors (per the
    # ``build_render_context`` override that made ``dungeon_poly =
    # building_polygon`` when the building is set), so the
    # wood-interior-clip is sufficient. Fall back to
    # ``op.woodBuildingPolygon`` only when there's no dungeon
    # Region (3.x cached building IRs from before the override
    # landed).
    if has_dungeon_clip:
        out.append(_dungeon_clip_defs(
            region.Outline(), "wood-interior-clip",
        ))
        clip_attr = ' clip-path="url(#wood-interior-clip)"'
    else:
        polygon = list(op.woodBuildingPolygon or [])
        if polygon:
            poly_points = " ".join(
                f"{p.x:.1f},{p.y:.1f}" for p in polygon
            )
            out.append(
                '<defs><clipPath id="wood-bldg-clip">'
                f'<polygon points="{poly_points}"/>'
                '</clipPath></defs>'
            )
            clip_attr = ' clip-path="url(#wood-bldg-clip)"'
        else:
            clip_attr = ""

    rooms = list(op.woodRooms or [])
    if not rooms:
        return out

    # Resolve each room's palette ONCE — the same palette feeds
    # the per-room overlay rect, the grain stroke colours, and
    # the seam stroke colour. Palette derives from the building's
    # ``op.seed`` (species pick) plus the room's ``regionRef``
    # (tone variant within the species).
    seed_int = int(op.seed)
    room_palettes: list[tuple[str, str, str, str]] = [
        _wood_palette_for_room(seed_int, _to_str(room.regionRef))
        for room in rooms
    ]

    # Per-room base overlay rects — paint the species' tone over
    # the building-wide ``WoodFloor`` FloorOp base. Room rects
    # never extend past the building polygon thanks to the clip
    # group around them. Emitted as one ``<g>`` so the clip-path
    # binds once.
    out.append(f'<g{clip_attr}>')
    for room, palette in zip(rooms, room_palettes):
        fill = palette[0]
        out.append(
            f'<rect x="{room.x * CELL:.1f}" y="{room.y * CELL:.1f}" '
            f'width="{room.w * CELL:.1f}" '
            f'height="{room.h * CELL:.1f}" '
            f'fill="{fill}" stroke="none"/>'
        )
    out.append('</g>')

    # Grain lines — bucket per (light-colour, dark-colour) pair so
    # rooms sharing a tone share groups (compact SVG output). RNG
    # draw order matches the legacy walk: rooms outer, plank
    # strips inner, two grain lines per strip.
    grain_buckets: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for room, palette in zip(rooms, room_palettes):
        _, grain_light, grain_dark, _ = palette
        light_lines, dark_lines = grain_buckets.setdefault(
            (grain_light, grain_dark), ([], []),
        )
        x0 = room.x * CELL
        y0 = room.y * CELL
        x1 = (room.x + room.w) * CELL
        y1 = (room.y + room.h) * CELL
        horizontal = room.w >= room.h
        width = WOOD_PLANK_WIDTH_PX

        if horizontal:
            y = y0
            while y < y1:
                strip_bot = min(y + width, y1)
                span = strip_bot - y
                if span <= 0.5:
                    y += width
                    continue
                for i in range(WOOD_GRAIN_LINES_PER_STRIP):
                    gy = rng.uniform(
                        y + span * 0.15, strip_bot - span * 0.15,
                    )
                    dest = light_lines if i % 2 == 0 else dark_lines
                    dest.append(
                        f'<line x1="{x0:.1f}" y1="{gy:.1f}" '
                        f'x2="{x1:.1f}" y2="{gy:.1f}"/>'
                    )
                y += width
        else:
            x = x0
            while x < x1:
                strip_right = min(x + width, x1)
                span = strip_right - x
                if span <= 0.5:
                    x += width
                    continue
                for i in range(WOOD_GRAIN_LINES_PER_STRIP):
                    gx = rng.uniform(
                        x + span * 0.15, strip_right - span * 0.15,
                    )
                    dest = light_lines if i % 2 == 0 else dark_lines
                    dest.append(
                        f'<line x1="{gx:.1f}" y1="{y0:.1f}" '
                        f'x2="{gx:.1f}" y2="{y1:.1f}"/>'
                    )
                x += width

    # Emit per-tone grain groups — light then dark, matching the
    # legacy two-group emission shape. Insertion-ordered iteration
    # keeps SVG output stable across runs.
    for (light_colour, dark_colour), (light_lines, dark_lines) in (
        grain_buckets.items()
    ):
        if light_lines:
            out.append(
                f'<g fill="none" stroke="{light_colour}" '
                f'stroke-width="{WOOD_GRAIN_STROKE_WIDTH}" '
                f'opacity="{WOOD_GRAIN_OPACITY}"{clip_attr}>'
            )
            out.append("".join(light_lines))
            out.append("</g>")
        if dark_lines:
            out.append(
                f'<g fill="none" stroke="{dark_colour}" '
                f'stroke-width="{WOOD_GRAIN_STROKE_WIDTH}" '
                f'opacity="{WOOD_GRAIN_OPACITY}"{clip_attr}>'
            )
            out.append("".join(dark_lines))
            out.append("</g>")

    # Plank seams — bucket per seam colour, mirroring the grain
    # bucket pattern.
    seam_buckets: dict[str, list[str]] = {}
    for room, palette in zip(rooms, room_palettes):
        seam_colour = palette[3]
        seam_bucket = seam_buckets.setdefault(seam_colour, [])
        seam_bucket.extend(_parquet_seams_from_room_ir(
            room, rng,
            WOOD_PLANK_WIDTH_PX,
            WOOD_PLANK_LENGTH_MIN,
            WOOD_PLANK_LENGTH_MAX,
        ))
    for seam_colour, seam_lines in seam_buckets.items():
        if not seam_lines:
            continue
        out.append(
            f'<g fill="none" stroke="{seam_colour}" '
            f'stroke-width="{WOOD_SEAM_WIDTH}"{clip_attr}>'
        )
        out.append("".join(seam_lines))
        out.append("</g>")
    return out


def _parquet_seams_from_room_ir(
    room, rng, width: float, length_min: float, length_max: float,
) -> list[str]:
    x0 = room.x * CELL
    y0 = room.y * CELL
    x1 = (room.x + room.w) * CELL
    y1 = (room.y + room.h) * CELL
    horizontal = room.w >= room.h
    seams: list[str] = []
    if horizontal:
        y = y0
        while y < y1:
            strip_bot = min(y + width, y1)
            x_end = x0 + rng.uniform(length_min, length_max)
            while x_end < x1:
                seams.append(
                    f'<line x1="{x_end:.1f}" y1="{y:.1f}" '
                    f'x2="{x_end:.1f}" y2="{strip_bot:.1f}"/>'
                )
                x_end += rng.uniform(length_min, length_max)
            y += width
            if y < y1:
                seams.append(
                    f'<line x1="{x0:.1f}" y1="{y:.1f}" '
                    f'x2="{x1:.1f}" y2="{y:.1f}"/>'
                )
    else:
        x = x0
        while x < x1:
            strip_right = min(x + width, x1)
            y_end = y0 + rng.uniform(length_min, length_max)
            while y_end < y1:
                seams.append(
                    f'<line x1="{x:.1f}" y1="{y_end:.1f}" '
                    f'x2="{strip_right:.1f}" y2="{y_end:.1f}"/>'
                )
                y_end += rng.uniform(length_min, length_max)
            x += width
            if x < x1:
                seams.append(
                    f'<line x1="{x:.1f}" y1="{y0:.1f}" '
                    f'x2="{x:.1f}" y2="{y1:.1f}"/>'
                )
    return seams


def _draw_floor_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_floor_detail``.

    Two modes:

    - Wood-floor short-circuit (``wood_tiles`` / ``wood_rooms`` /
      ``wood_building_polygon`` populated) → drive
      ``_draw_wood_floor_from_ir`` from the structured fields.
    - Otherwise: floor-detail-proper from Rust
      (``nhc_render.draw_floor_detail``) under the dungeon-
      interior clipPath envelope on the room side, with the
      corridor side appended unclipped.

    Schema 3.1 (Phase 0.1 of plans/nhc_pure_ir_plan.md) drops the
    legacy thematic passthrough reads on ``room_groups`` /
    ``corridor_groups``: those vectors haven't been populated
    since schema 3.0 (ThematicDetailOp owns thematic detail), so
    the defensive concat is dead code. The schema fields stay
    declared until the 4.0 cut.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())

    if op.woodTiles or op.woodBuildingPolygon or op.woodRooms:
        return _draw_wood_floor_from_ir(op, fir)

    out: list[str] = []

    rust_room: list[str] = []
    rust_corridor: list[str] = []
    op_tiles = op.tiles if op.tiles is not None else []
    op_is_corridor = (
        op.isCorridor if op.isCorridor is not None else []
    )
    if len(op_tiles) > 0:
        tiles = [
            (t.x, t.y, bool(op_is_corridor[i]))
            for i, t in enumerate(op_tiles)
        ]
        flags = fir.Flags()
        macabre = (
            bool(flags.MacabreDetail()) if flags is not None else True
        )
        rust_room, rust_corridor = nhc_render.draw_floor_detail(
            tiles, int(op.seed), _to_str(op.theme), macabre,
        )

    room_groups = rust_room
    corridor_groups = rust_corridor

    if room_groups:
        # Phase 1.25 — prefer op.regionRef (canonical 4.0 name);
        # fall back to op.clipRegion for 3.x cached buffers.
        clip_id = _to_str(op.regionRef) or _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Outline(), "detail-clip"))
                out.append('<g clip-path="url(#detail-clip)">')
                out.extend(room_groups)
                out.append("</g>")
            else:
                out.extend(room_groups)
        else:
            out.extend(room_groups)

    out.extend(corridor_groups)
    return out


_OP_HANDLERS[Op.Op.FloorDetailOp] = _draw_floor_detail_from_ir


def _draw_thematic_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce the thematic-detail layer (webs / bones / skulls).

    Sub-step 4.e wires the Rust port at
    ``nhc_render.draw_thematic_detail``. Walks ``op.tiles[]``
    plus the parallel ``isCorridor[]`` / ``wallCorners[]``
    arrays through the FFI boundary; the painter handles the
    per-theme probability table, the legacy
    ``random.choice``-style web-corner pick, and the macabre
    gate. Output rides under the dungeon-interior clipPath
    envelope on the room side, with the corridor side appended
    unclipped.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) == 0:
        return []

    op_is_corridor = (
        op.isCorridor if op.isCorridor is not None else []
    )
    op_wall_corners = (
        op.wallCorners if op.wallCorners is not None else []
    )
    theme = _to_str(op.theme)
    flags = fir.Flags()
    macabre = (
        bool(flags.MacabreDetail()) if flags is not None else True
    )

    tiles = [
        (
            t.x,
            t.y,
            bool(op_is_corridor[i]),
            int(op_wall_corners[i]) if i < len(op_wall_corners) else 0,
        )
        for i, t in enumerate(op_tiles)
    ]
    room_groups, corridor_groups = nhc_render.draw_thematic_detail(
        tiles, int(op.seed), theme, macabre,
    )

    out: list[str] = []
    if room_groups:
        # Phase 1.25 — prefer op.regionRef (canonical 4.0 name);
        # fall back to op.clipRegion for 3.x cached buffers.
        clip_id = _to_str(op.regionRef) or _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(
                    _dungeon_clip_defs(region.Outline(), "thematic-clip")
                )
                out.append('<g clip-path="url(#thematic-clip)">')
                out.extend(room_groups)
                out.append("</g>")
            else:
                out.extend(room_groups)
        else:
            out.extend(room_groups)

    out.extend(corridor_groups)
    return out


_OP_HANDLERS[Op.Op.ThematicDetailOp] = _draw_thematic_detail_from_ir


def _terrain_detail_seeded_rng(seed: int, name: str):
    """Per-decorator deterministic RNG used by the terrain-detail
    handler.

    Mirrors the legacy ``_decorators._seeded_rng`` formula
    (Mersenne Twister keyed by ``(ctx.seed, decorator_name)``) so
    SVG output stays byte-equal to the historical fixture
    snapshots in ``tests/fixtures/floor_ir/<descriptor>/floor.svg``.
    """
    name_seed = sum(
        (ord(c) * 31 ** i) for i, c in enumerate(name)
    ) & 0xFFFF_FFFF
    return random.Random((seed * 1_000_003) ^ name_seed)


# Per-terrain-kind metadata for the from-IR painter. Mirrors the
# (name, z_order, palette) tuple the legacy `_terrain_detail.py`
# `TileDecorator` instances carried; keeping it inline here lets
# `ir_to_svg` consume the painters without depending on the
# legacy decorator infrastructure.
_TERRAIN_DETAIL_DISPATCH: tuple[tuple[int, str, int, str], ...] = (
    # (TerrainKind value, decorator name, z_order, css class)
    (1, "terrain_water", 10, "terrain-water"),
    (2, "terrain_lava", 30, "terrain-lava"),
    (3, "terrain_chasm", 40, "terrain-chasm"),
)


def _draw_terrain_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_terrain_detail`` from ``tiles[]``.

    Drives the per-tile water / lava / chasm painters directly
    from the structured tile list, mirroring the (now-retired)
    ``walk_and_paint`` row-major dispatch + room/corridor
    bucketing + dungeon-poly clip envelope. Per-decorator
    ``random.Random`` keying matches the
    ``_terrain_detail_seeded_rng`` formula above so output stays
    byte-equal to the snapshot fixtures.
    """
    from nhc.rendering._terrain_detail import (
        _chasm_detail, _lava_detail, _water_detail,
    )
    from nhc.rendering.terrain_palette import get_palette

    op = OpCreator(entry.OpType(), entry.Op())
    if not op.tiles:
        return []

    theme_str = _to_str(op.theme) or "dungeon"
    palette = get_palette(theme_str)
    dungeon_palette = get_palette("dungeon")

    painter_by_kind = {
        1: (_water_detail, palette.water, dungeon_palette.water),
        2: (_lava_detail, palette.lava, dungeon_palette.lava),
        3: (_chasm_detail, palette.chasm, dungeon_palette.chasm),
    }

    ctx_seed = int(op.seed) - 200
    rngs = {
        kind: _terrain_detail_seeded_rng(ctx_seed, name)
        for kind, name, _, _ in _TERRAIN_DETAIL_DISPATCH
    }
    buckets: dict[int, dict[str, list[str]]] = {
        kind: {"room": [], "corridor": []}
        for kind, _, _, _ in _TERRAIN_DETAIL_DISPATCH
    }

    for tile in op.tiles:
        info = painter_by_kind.get(int(tile.kind))
        if info is None:
            continue
        painter, style, _ = info
        produced = painter(
            rngs[int(tile.kind)],
            tile.x * CELL, tile.y * CELL,
            style.detail_ink, style.detail_opacity,
        )
        bucket = "corridor" if tile.isCorridor else "room"
        buckets[int(tile.kind)][bucket].extend(produced)

    # Emit in z_order ascending. Group-open uses the dungeon-theme
    # palette to match the legacy `_terrain_group_open`, which
    # hard-codes the "dungeon" palette regardless of running theme.
    active_in_z = sorted(
        _TERRAIN_DETAIL_DISPATCH, key=lambda row: row[2],
    )

    def _group_open(kind: int, css_class: str) -> str:
        d_style = painter_by_kind[kind][2]
        return (
            f'<g class="{css_class}" '
            f'opacity="{d_style.detail_opacity}" '
            f'stroke="{d_style.detail_ink}" '
            f'stroke-linecap="round">'
        )

    def _emit_group(
        target: list[str], kind: int, css_class: str,
        frags: list[str],
    ) -> None:
        if not frags:
            return
        target.append(_group_open(kind, css_class))
        target.extend(frags)
        target.append("</g>")

    out: list[str] = []
    has_any_room = any(
        buckets[kind]["room"] for kind, _, _, _ in active_in_z
    )
    # Phase 1.25 — prefer op.regionRef; fall back to clipRegion.
    clip_id_str = _to_str(op.regionRef) or _to_str(op.clipRegion)
    region = (
        _find_region(fir, clip_id_str.encode())
        if (has_any_room and clip_id_str)
        else None
    )
    use_clip = region is not None

    if use_clip:
        out.append(_dungeon_clip_defs(
            region.Outline(), "terrain-detail-clip",
        ))
        out.append('<g clip-path="url(#terrain-detail-clip)">')
    for kind, _, _, css_class in active_in_z:
        _emit_group(out, kind, css_class, buckets[kind]["room"])
    if use_clip:
        out.append("</g>")
    for kind, _, _, css_class in active_in_z:
        _emit_group(out, kind, css_class, buckets[kind]["corridor"])
    return out


_OP_HANDLERS[Op.Op.TerrainDetailOp] = _draw_terrain_detail_from_ir


def _draw_decorator_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Render the structured decorator pipeline (``DecoratorOp``).

    Sub-step 6 promotes the empty-arm stub from step 5 into a
    real handler that walks the per-variant vectors and routes
    each to its Rust port. Cobblestone is wired here; the
    remaining six variants land at sub-steps 7–12 (each port
    plugs in additional per-vector dispatch). Until then the
    other variants' fragments still ride through
    ``FloorDetailOp.decorator_groups`` (the passthrough) and
    the dispatcher must not double-draw them.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []
    seed = int(op.seed)

    cobble_variants = op.cobblestone if op.cobblestone is not None else []
    for variant in cobble_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_cobblestone(tiles, seed))

    brick_variants = op.brick if op.brick is not None else []
    for variant in brick_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_brick(tiles, seed))

    flagstone_variants = (
        op.flagstone if op.flagstone is not None else []
    )
    for variant in flagstone_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_flagstone(tiles, seed))

    opus_variants = (
        op.opusRomano if op.opusRomano is not None else []
    )
    for variant in opus_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_opus_romano(tiles, seed))

    field_variants = (
        op.fieldStone if op.fieldStone is not None else []
    )
    for variant in field_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_field_stone(tiles, seed))

    cart_variants = (
        op.cartTracks if op.cartTracks is not None else []
    )
    for variant in cart_variants:
        v_tiles = variant.tiles or []
        v_horiz = (
            variant.isHorizontal
            if variant.isHorizontal is not None
            else []
        )
        if not v_tiles:
            continue
        tiles = [
            (t.x, t.y, bool(v_horiz[i]))
            for i, t in enumerate(v_tiles)
        ]
        out.extend(nhc_render.draw_cart_tracks(tiles, seed))

    ore_variants = (
        op.oreDeposit if op.oreDeposit is not None else []
    )
    for variant in ore_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_ore_deposit(tiles, seed))

    return out


_OP_HANDLERS[Op.Op.DecoratorOp] = _draw_decorator_from_ir


def _draw_stairs_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_stairs``.

    Phase 4.3 — per-stair geometry lives in
    ``crates/nhc-render/src/primitives/stairs.rs`` and is reached
    via ``nhc_render.draw_stairs``. The Python side just unpacks
    the IR's stair list and forwards theme + fill_color; everything
    else (tapering wedge math, cave fill polygon, parallel step
    lines) is in Rust.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    theme = _to_str(op.theme)
    fill_color = _to_str(op.fillColor)
    stairs = [
        (s.x, s.y, int(s.direction)) for s in (op.stairs or [])
    ]
    return nhc_render.draw_stairs(stairs, theme, fill_color)


_OP_HANDLERS[Op.Op.StairsOp] = _draw_stairs_from_ir


def _draw_feature_groups(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Generic groups-passthrough handler used by surface-feature
    ops that haven't ported their per-tile painter to Rust yet
    (fountain / tree / bush — sub-steps 14-16).

    The op carries pre-rendered ``<g>`` strings in ``op.groups``;
    the handler emits them verbatim. Each feature's Rust port
    swaps this for a structured-tile dispatch arm.
    """
    del fir
    op = OpCreator(entry.OpType(), entry.Op())
    return [_to_str(g) for g in (op.groups or [])]


def _draw_well_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Well surface feature — Phase 4 sub-step 13.

    Reads ``op.tiles[]`` + ``op.shape`` and dispatches to the
    Rust port at ``nhc_render.draw_well``. Falls back to the
    transitional ``op.groups`` passthrough when the structured
    fields are empty (e.g. for fixtures emitted before the port
    landed).
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) > 0:
        tiles = [(t.x, t.y) for t in op_tiles]
        return nhc_render.draw_well(tiles, int(op.shape))
    return [_to_str(g) for g in (op.groups or [])]


def _draw_fountain_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Fountain surface feature — Phase 4 sub-step 14.

    Reads ``op.tiles[]`` + ``op.shape`` and dispatches to the
    Rust port. Falls back to ``op.groups`` for legacy IR buffers.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) > 0:
        tiles = [(t.x, t.y) for t in op_tiles]
        return nhc_render.draw_fountain(tiles, int(op.shape))
    return [_to_str(g) for g in (op.groups or [])]


def _draw_bush_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Bush surface feature — Phase 4 sub-step 16.

    Reads ``op.tiles[]`` and dispatches to the Rust port at
    ``nhc_render.draw_bush``. Falls back to ``op.groups`` for
    legacy IR buffers.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) > 0:
        tiles = [(t.x, t.y) for t in op_tiles]
        return nhc_render.draw_bush(tiles)
    return [_to_str(g) for g in (op.groups or [])]


def _draw_tree_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Tree surface feature — Phase 4 sub-step 15.

    Reads ``op.tiles[]`` (free trees) plus
    ``op.groveTiles[]`` + ``op.groveSizes[]`` (groves of size
    ≥ 3 partitioned across the flat list) and dispatches to
    ``nhc_render.draw_tree``. Falls back to ``op.groups`` for
    legacy IR buffers.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    op_grove_tiles = (
        op.groveTiles if op.groveTiles is not None else []
    )
    op_grove_sizes = (
        op.groveSizes if op.groveSizes is not None else []
    )
    if len(op_tiles) > 0 or len(op_grove_tiles) > 0:
        free_trees = [(t.x, t.y) for t in op_tiles]
        flat = [(t.x, t.y) for t in op_grove_tiles]
        groves: list[list[tuple[int, int]]] = []
        cursor = 0
        for size in op_grove_sizes:
            n = int(size)
            groves.append(flat[cursor : cursor + n])
            cursor += n
        return nhc_render.draw_tree(free_trees, groves)
    return [_to_str(g) for g in (op.groups or [])]


_OP_HANDLERS[Op.Op.WellFeatureOp] = _draw_well_from_ir
_OP_HANDLERS[Op.Op.FountainFeatureOp] = _draw_fountain_from_ir
_OP_HANDLERS[Op.Op.TreeFeatureOp] = _draw_tree_from_ir
_OP_HANDLERS[Op.Op.BushFeatureOp] = _draw_bush_from_ir


# ── RoofOp (Phase 8.1c.1) ───────────────────────────────────────
#
# Per-building shingle roof. The handler resolves region_ref to the
# matching Region(kind=Building), reads its polygon (pixel coords),
# picks gable / pyramid mode from shape_tag + bbox aspect, and
# emits a clip-path-bounded shingle running-bond plus ridge lines.
#
# Both rasterisers (this Python SVG path and the future tiny-skia
# port at crates/nhc-render/src/transform/png/roof.rs in 8.1c.2)
# walk the same splitmix64 stream seeded with RoofOp.rng_seed so
# their shingle layouts agree at PSNR > 40 dB. The Phase 8.1c.1
# Python implementation is the *reference* — the Rust port mirrors
# it constant-for-constant.


_ROOF_GOLDEN_GAMMA: int = 0x9E3779B97F4A7C15
_ROOF_MIX_C1: int = 0xBF58476D1CE4E5B9
_ROOF_MIX_C2: int = 0x94D049BB133111EB
_U64_MASK: int = 0xFFFFFFFFFFFFFFFF


_ROOF_SHADOW_FACTOR: float = 0.5
_ROOF_SHINGLE_WIDTH: float = 14.0
_ROOF_SHINGLE_HEIGHT: float = 5.0
_ROOF_SHINGLE_JITTER: float = 2.0
_ROOF_RIDGE_STROKE: str = "#000000"
_ROOF_RIDGE_WIDTH: float = 1.5
_ROOF_SHINGLE_STROKE: str = "#000000"
_ROOF_SHINGLE_STROKE_OPACITY: float = 0.2
_ROOF_SHINGLE_STROKE_WIDTH: float = 0.3


class _SplitMix64:
    """Stateful splitmix64 — mirrors crates/nhc-render/src/rng.rs.

    The Rust port at 8.1c.2 will pull from a parallel stream
    seeded with the same ``RoofOp.rng_seed``. Both sides advance
    state by ``GOLDEN_GAMMA`` each call before the 3-step mix, so
    ``next_u64`` outputs match value-for-value.
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _U64_MASK

    def next_u64(self) -> int:
        self._state = (self._state + _ROOF_GOLDEN_GAMMA) & _U64_MASK
        z = self._state
        z = ((z ^ (z >> 30)) * _ROOF_MIX_C1) & _U64_MASK
        z = ((z ^ (z >> 27)) * _ROOF_MIX_C2) & _U64_MASK
        return z ^ (z >> 31)

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * (self.next_u64() / 2 ** 64)

    def choice(self, seq: list) -> Any:
        return seq[self.next_u64() % len(seq)]


def _roof_scale_hex(hx: str, factor: float) -> str:
    r = min(255, max(0, int(int(hx[1:3], 16) * factor)))
    g = min(255, max(0, int(int(hx[3:5], 16) * factor)))
    b = min(255, max(0, int(int(hx[5:7], 16) * factor)))
    return f"#{r:02X}{g:02X}{b:02X}"


def _roof_shade_palette(tint: str, *, sunlit: bool) -> list[str]:
    if sunlit:
        factors = (1.15, 1.00, 0.88)
    else:
        c = _ROOF_SHADOW_FACTOR
        factors = (c * 1.15, c, c * 0.88)
    return [_roof_scale_hex(tint, f) for f in factors]


def _roof_shingle_region(
    x: float, y: float, w: float, h: float,
    shades: list[str], rng: _SplitMix64,
    *, vertical_courses: bool = False,
) -> list[str]:
    """Running-bond rows of shingle rects filling a bounding box.

    Each shingle's drawn rect is clamped to ``[x, x + w] × [y, y +
    h]`` so it never bleeds past the region's edges. Without the
    clamp, gable roofs show shadow shingles crossing the ridge into
    the sunlit side (and vice versa).

    By default shingles lay in *horizontal* courses (rows running
    left-right, long axis horizontal) — correct when the ridge is
    vertical (shingles run perpendicular to the ridge, parallel to
    the eaves on the left + right).

    When ``vertical_courses=True``, the layout transposes: columns
    run top-down with the running-bond offset on alternate columns
    (``y`` instead of ``x``), and each shingle's drawn rect is
    ``sh × sw_j`` (long axis vertical). Used for horizontal-ridge
    gables so the courses run perpendicular to the ridge.
    """
    sw = _ROOF_SHINGLE_WIDTH
    sh = _ROOF_SHINGLE_HEIGHT
    jitter = _ROOF_SHINGLE_JITTER
    frags: list[str] = []
    if vertical_courses:
        col = 0
        cx = x
        while cx < x + w:
            sy = y - (sw / 2 if col % 2 else 0)
            while sy < y + h:
                sw_j = sw + rng.uniform(-jitter, jitter)
                shade = rng.choice(shades)
                vy = max(sy, y)
                vb = min(sy + sw_j, y + h)
                vh = vb - vy
                if vh > 0:
                    frags.append(
                        f'<rect x="{cx:.1f}" y="{vy:.1f}" '
                        f'width="{sh:.1f}" height="{vh:.1f}" '
                        f'fill="{shade}" '
                        f'stroke="{_ROOF_SHINGLE_STROKE}" '
                        f'stroke-opacity="{_ROOF_SHINGLE_STROKE_OPACITY}" '
                        f'stroke-width="{_ROOF_SHINGLE_STROKE_WIDTH}"/>'
                    )
                sy += sw_j
            cx += sh
            col += 1
        return frags
    row = 0
    cy = y
    while cy < y + h:
        sx = x - (sw / 2 if row % 2 else 0)
        while sx < x + w:
            sw_j = sw + rng.uniform(-jitter, jitter)
            shade = rng.choice(shades)
            vx = max(sx, x)
            vr = min(sx + sw_j, x + w)
            vw = vr - vx
            if vw > 0:
                frags.append(
                    f'<rect x="{vx:.1f}" y="{cy:.1f}" '
                    f'width="{vw:.1f}" height="{sh:.1f}" '
                    f'fill="{shade}" '
                    f'stroke="{_ROOF_SHINGLE_STROKE}" '
                    f'stroke-opacity="{_ROOF_SHINGLE_STROKE_OPACITY}" '
                    f'stroke-width="{_ROOF_SHINGLE_STROKE_WIDTH}"/>'
                )
            sx += sw_j
        cy += sh
        row += 1
    return frags


def _roof_gable_sides(
    px: float, py: float, pw: float, ph: float,
    horizontal: bool,
    sunlit_shades: list[str], shadow_shades: list[str],
    rng: _SplitMix64,
) -> list[str]:
    frags: list[str] = []
    if horizontal:
        # Horizontal ridge — shingles laid in vertical courses so
        # their long axis runs perpendicular to the ridge (i.e.
        # parallel to the rake / down-slope direction).
        frags.extend(_roof_shingle_region(
            px, py, pw, ph / 2, shadow_shades, rng,
            vertical_courses=True,
        ))
        frags.extend(_roof_shingle_region(
            px, py + ph / 2, pw, ph / 2, sunlit_shades, rng,
            vertical_courses=True,
        ))
        frags.append(
            f'<line x1="{px:.1f}" y1="{py + ph / 2:.1f}" '
            f'x2="{px + pw:.1f}" y2="{py + ph / 2:.1f}" '
            f'stroke="{_ROOF_RIDGE_STROKE}" '
            f'stroke-width="{_ROOF_RIDGE_WIDTH}"/>'
        )
    else:
        # Vertical ridge — shingles laid in horizontal courses
        # (default) so their long axis runs perpendicular to the
        # ridge.
        frags.extend(_roof_shingle_region(
            px, py, pw / 2, ph, shadow_shades, rng,
        ))
        frags.extend(_roof_shingle_region(
            px + pw / 2, py, pw / 2, ph, sunlit_shades, rng,
        ))
        frags.append(
            f'<line x1="{px + pw / 2:.1f}" y1="{py:.1f}" '
            f'x2="{px + pw / 2:.1f}" y2="{py + ph:.1f}" '
            f'stroke="{_ROOF_RIDGE_STROKE}" '
            f'stroke-width="{_ROOF_RIDGE_WIDTH}"/>'
        )
    return frags


def _roof_pyramid_sides(
    polygon: list[tuple[float, float]],
    sunlit_shades: list[str], shadow_shades: list[str],
    rng: _SplitMix64,
) -> list[str]:
    """N triangles from polygon centre, shaded by edge midpoint
    direction (north / west = shadow, south / east = sunlit), plus
    ridges from centre to each polygon vertex."""
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    frags: list[str] = []
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        mx = (a[0] + b[0]) / 2
        my = (a[1] + b[1]) / 2
        is_shadow = my < cy - 1e-3 or (
            mx < cx - 1e-3 and my < cy + 1e-3
        )
        shades = shadow_shades if is_shadow else sunlit_shades
        fill = rng.choice(shades)
        pts = (
            f"{a[0]:.1f},{a[1]:.1f} "
            f"{b[0]:.1f},{b[1]:.1f} "
            f"{cx:.1f},{cy:.1f}"
        )
        frags.append(
            f'<polygon points="{pts}" fill="{fill}" '
            f'stroke="{_ROOF_SHINGLE_STROKE}" '
            f'stroke-opacity="{_ROOF_SHINGLE_STROKE_OPACITY}" '
            f'stroke-width="{_ROOF_SHINGLE_STROKE_WIDTH}"/>'
        )
    for (vx, vy) in polygon:
        frags.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" '
            f'x2="{vx:.1f}" y2="{vy:.1f}" '
            f'stroke="{_ROOF_RIDGE_STROKE}" '
            f'stroke-width="{_ROOF_RIDGE_WIDTH}"/>'
        )
    return frags


def _roof_geometry_mode(shape_tag: str, polygon: list[tuple[float, float]]) -> str:
    """Pick "gable" or "pyramid" from shape_tag + footprint bbox.

    Mirrors design/map_ir.md §7.14:
    - rect non-square / l_shape_*  → gable
    - rect square / octagon / circle / fallback → pyramid
    """
    if shape_tag.startswith("l_shape"):
        return "gable"
    if shape_tag == "rect":
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        return "pyramid" if abs(w - h) < 1e-6 else "gable"
    return "pyramid"  # octagon / circle / unknown


def _draw_roof_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Phase 8.1c.1: per-building shingle roof.

    Reads the referenced ``Region(kind=Building)``, picks geometry
    from its ``shape_tag`` + polygon bbox, and emits a clip-path-
    bounded roof body. The Python implementation is the reference;
    the Rust tiny-skia port at 8.1c.2 mirrors the same RNG +
    constants so PSNR > 40 dB across both rasterisers.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    region_ref = _to_str(op.regionRef)
    region = _find_region(fir, op.regionRef)
    if region is None:
        raise ValueError(
            f"RoofOp references unknown region {region_ref!r}; "
            "emit_regions / emit_building_regions must register it"
        )
    shape_tag = _to_str(region.ShapeTag())
    # Phase 1.26g — read footprint from Region.outline (the canonical
    # post-1.27 source) instead of Region.polygon.
    outline_fb = region.Outline()
    if outline_fb is None or outline_fb.VerticesLength() < 3:
        raise ValueError(
            f"RoofOp region {region_ref!r} outline is empty or "
            "degenerate; cannot emit roof"
        )
    polygon: list[tuple[float, float]] = []
    for i in range(outline_fb.VerticesLength()):
        v = outline_fb.Vertices(i)
        polygon.append((v.X(), v.Y()))

    tint = _to_str(op.tint) or "#8A7A5A"
    rng = _SplitMix64(int(op.rngSeed))
    sunlit_shades = _roof_shade_palette(tint, sunlit=True)
    shadow_shades = _roof_shade_palette(tint, sunlit=False)

    mode = _roof_geometry_mode(shape_tag, polygon)
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    px, py = min(xs), min(ys)
    pw, ph = max(xs) - px, max(ys) - py

    body: list[str]
    if mode == "gable":
        body = _roof_gable_sides(
            px, py, pw, ph, pw >= ph,
            sunlit_shades, shadow_shades, rng,
        )
    else:
        body = _roof_pyramid_sides(
            polygon, sunlit_shades, shadow_shades, rng,
        )

    # Clip-path id derives from region_ref so the same Building
    # always yields the same clipPath id — stable across re-emits.
    clip_id = f"roof_{region_ref.replace('.', '_')}"
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in polygon)
    return [
        (
            f'<defs><clipPath id="{clip_id}">'
            f'<polygon points="{pts}"/>'
            f'</clipPath></defs>'
        ),
        f'<g clip-path="url(#{clip_id})">{"".join(body)}</g>',
    ]


_OP_HANDLERS[Op.Op.RoofOp] = _draw_roof_from_ir


# ── EnclosureOp (Phase 8.2) ─────────────────────────────────────
#
# Site-level palisade ring or fortification battlement. Reads the
# closed polygon, walks its edges (cut by per-edge gate spans into
# open sub-polylines), and dispatches each sub-segment on
# EnclosureStyle. Per-edge palisade RNG seeds derive from
# `rng_seed + edge_idx` so adding / removing a gate on edge X
# doesn't shift state on other edges. Both rasterisers walk the
# same splitmix64 stream — the Rust port at
# crates/nhc-render/src/transform/png/enclosure.rs lands at 8.2c.
#
# Constants mirror nhc/rendering/_enclosures.py value-for-value
# (palette + dimensions). The legacy module stays alive until the
# site-surface IR wiring at Phase 8.4 obsoletes it.


# Fortification (battlement) constants.
_ENC_FORTIF_STROKE = "#1A1A1A"
_ENC_FORTIF_STROKE_WIDTH = 0.8
_ENC_FORTIF_MERLON_FILL = "#D8D8D8"
_ENC_FORTIF_CRENEL_FILL = "#000000"
_ENC_FORTIF_CORNER_FILL = "#000000"
_ENC_FORTIF_SIZE = 8.0
_ENC_FORTIF_RATIO = 1.4142135623730951  # sqrt(2) — DIN A
_ENC_FORTIF_CORNER_SCALE = 3.0


# Palisade constants.
_ENC_PALI_FILL = "#8A5A2A"
_ENC_PALI_STROKE = "#4A2E1A"
_ENC_PALI_STROKE_WIDTH = 1.5
_ENC_PALI_RADIUS_MIN = 3.0
_ENC_PALI_RADIUS_MAX = 4.0
_ENC_PALI_RADIUS_JITTER = 0.3
_ENC_PALI_CIRCLE_STEP = 9.0
_ENC_PALI_DOOR_LENGTH_PX = 64.0


def _enc_corner_inset() -> float:
    return _ENC_FORTIF_SIZE / 2.0


def _enc_merge_cuts(
    cuts: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not cuts:
        return []
    cuts = sorted(cuts)
    merged = [cuts[0]]
    for lo, hi in cuts[1:]:
        plo, phi = merged[-1]
        if lo <= phi:
            merged[-1] = (plo, max(phi, hi))
        else:
            merged.append((lo, hi))
    return merged


def _enc_subsegments(
    a: tuple[float, float], b: tuple[float, float],
    cuts: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    ax, ay = a
    bx, by = b

    def _at(t: float) -> tuple[float, float]:
        return (ax + (bx - ax) * t, ay + (by - ay) * t)

    if not cuts:
        return [(a, b)]
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    prev = 0.0
    for lo, hi in cuts:
        if lo > prev:
            out.append((_at(prev), _at(lo)))
        prev = hi
    if prev < 1.0:
        out.append((_at(prev), _at(1.0)))
    return out


def _enc_fortification_rect(
    cx: float, cy: float, w: float, h: float, fill: str,
) -> str:
    return (
        f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'fill="{fill}" '
        f'stroke="{_ENC_FORTIF_STROKE}" '
        f'stroke-width="{_ENC_FORTIF_STROKE_WIDTH}"/>'
    )


def _enc_centered_fortification_chain(
    a: tuple[float, float], b: tuple[float, float],
) -> list[str]:
    """``C M C M ... C`` chain inside a horizontal / vertical sub-segment."""
    import math
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-6:
        return []
    horizontal = abs(dy) < 1e-6 and abs(dx) > 1e-6
    vertical = abs(dx) < 1e-6 and abs(dy) > 1e-6
    if not (horizontal or vertical):
        return []
    size = _ENC_FORTIF_SIZE
    rect_len = size * _ENC_FORTIF_RATIO
    k = int((seg_len + size) / (rect_len + size))
    if k < 1:
        return []
    used = k * rect_len + (k - 1) * size
    offset = (seg_len - used) / 2.0
    ux = dx / seg_len
    uy = dy / seg_len
    out: list[str] = []
    pos = offset
    alternate = 1  # start with crenel
    for _ in range(2 * k - 1):
        length = size if alternate == 0 else rect_len
        cx = ax + ux * (pos + length / 2.0)
        cy = ay + uy * (pos + length / 2.0)
        if horizontal:
            shape_w, shape_h = length, size
        else:
            shape_w, shape_h = size, length
        fill = (
            _ENC_FORTIF_MERLON_FILL if alternate == 0
            else _ENC_FORTIF_CRENEL_FILL
        )
        out.append(_enc_fortification_rect(cx, cy, shape_w, shape_h, fill))
        pos += length
        alternate = 1 - alternate
    return out


def _enc_corner_shape(
    x: float, y: float, corner_style: int,
) -> str:
    """Per-vertex corner block. corner_style is the raw FB enum int."""
    from nhc.rendering.ir._fb.CornerStyle import CornerStyle
    size = _ENC_FORTIF_SIZE * _ENC_FORTIF_CORNER_SCALE
    half = size / 2.0
    if corner_style == CornerStyle.Diamond:
        return (
            f'<rect x="{x - half:.1f}" y="{y - half:.1f}" '
            f'width="{size:.1f}" height="{size:.1f}" '
            f'fill="{_ENC_FORTIF_CORNER_FILL}" '
            f'stroke="{_ENC_FORTIF_STROKE}" '
            f'stroke-width="{_ENC_FORTIF_STROKE_WIDTH}" '
            f'transform="rotate(45 {x:.1f} {y:.1f})"/>'
        )
    # Merlon (and Tower fallback): axis-aligned black square.
    return _enc_fortification_rect(
        x, y, size, size, _ENC_FORTIF_CORNER_FILL,
    )


def _enc_palisade_circles(
    points: list[tuple[float, float]], rng: _SplitMix64,
) -> list[str]:
    import math
    if len(points) < 2:
        return []
    out: list[str] = []
    carry = 0.0
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        dx, dy = bx - ax, by - ay
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-6:
            continue
        ux, uy = dx / seg_len, dy / seg_len
        t = carry
        while t < seg_len:
            cx = ax + ux * t
            cy = ay + uy * t
            base_r = rng.uniform(_ENC_PALI_RADIUS_MIN, _ENC_PALI_RADIUS_MAX)
            jitter = rng.uniform(
                -_ENC_PALI_RADIUS_JITTER, _ENC_PALI_RADIUS_JITTER,
            )
            r = max(0.1, base_r + jitter)
            out.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                f'r="{r:.1f}" '
                f'fill="{_ENC_PALI_FILL}" '
                f'stroke="{_ENC_PALI_STROKE}" '
                f'stroke-width="{_ENC_PALI_STROKE_WIDTH}"/>'
            )
            t += _ENC_PALI_CIRCLE_STEP
        carry = max(0.0, t - seg_len)
    return out


def _enc_palisade_door_rect(
    a: tuple[float, float], b: tuple[float, float], t_center: float,
) -> str:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    cx = ax + dx * t_center
    cy = ay + dy * t_center
    horizontal = abs(dy) < 1e-6
    thickness = 2.0 * _ENC_PALI_RADIUS_MAX
    if horizontal:
        x = cx - _ENC_PALI_DOOR_LENGTH_PX / 2
        y = cy - thickness / 2
        w, h = _ENC_PALI_DOOR_LENGTH_PX, thickness
    else:
        x = cx - thickness / 2
        y = cy - _ENC_PALI_DOOR_LENGTH_PX / 2
        w, h = thickness, _ENC_PALI_DOOR_LENGTH_PX
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'fill="{_ENC_PALI_FILL}" '
        f'stroke="{_ENC_PALI_STROKE}" '
        f'stroke-width="{_ENC_PALI_STROKE_WIDTH}"/>'
    )


def _draw_enclosure_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Phase 8.2: site palisade or fortification ring.

    Walks the closed polygon, applies per-edge gate cuts, and
    dispatches each open sub-segment on EnclosureStyle. Per-edge
    palisade RNG state is `splitmix64(rng_seed + edge_idx)` so a
    gate edit on edge X leaves other edges' circle layouts pinned.

    Phase 1.16: suppressed when in-scope ExteriorWallOp entries are
    present in the IR (the new handler renders the same pixels).
    """
    if _has_consumed_exterior_wall_ops(fir):
        return []
    import math
    from nhc.rendering.ir._fb.EnclosureStyle import EnclosureStyle

    op = OpCreator(entry.OpType(), entry.Op())
    poly = op.polygon
    if poly is None or not poly.paths:
        return []
    polygon: list[tuple[float, float]] = [
        (v.x, v.y) for v in poly.paths
    ]
    n = len(polygon)
    if n < 3:
        return []

    # Group gates by edge.
    by_edge: dict[int, list[tuple[float, float]]] = {}
    midpoints: dict[int, list[tuple[float, float]]] = {}
    for g in (op.gates or []):
        edge_idx = int(g.edgeIdx)
        if not 0 <= edge_idx < n:
            continue
        a = polygon[edge_idx]
        b = polygon[(edge_idx + 1) % n]
        edge_len = math.hypot(b[0] - a[0], b[1] - a[1])
        if edge_len < 1e-6:
            continue
        half_t = float(g.halfPx) / edge_len
        lo = max(0.0, float(g.tCenter) - half_t)
        hi = min(1.0, float(g.tCenter) + half_t)
        if hi > lo:
            by_edge.setdefault(edge_idx, []).append((lo, hi))
            midpoints.setdefault(edge_idx, []).append(
                (float(g.tCenter), float(g.halfPx)),
            )

    style = int(op.style)
    rng_seed = int(op.rngSeed)
    out: list[str] = []

    if style == EnclosureStyle.Palisade:
        for i in range(n):
            a = polygon[i]
            b = polygon[(i + 1) % n]
            cuts = _enc_merge_cuts(by_edge.get(i, []))
            subs = _enc_subsegments(a, b, cuts)
            edge_rng = _SplitMix64(rng_seed + i)
            for (sa, sb) in subs:
                out.extend(_enc_palisade_circles(
                    [sa, sb], edge_rng,
                ))
            for t_center, _ in midpoints.get(i, []):
                out.append(_enc_palisade_door_rect(a, b, t_center))
        return out

    # Fortification: edges inset, centered chains, corner blocks
    # last so they sit on top.
    inset = _enc_corner_inset()
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        edge_len = math.hypot(b[0] - a[0], b[1] - a[1])
        if edge_len <= 2 * inset + 1e-6:
            continue
        ux = (b[0] - a[0]) / edge_len
        uy = (b[1] - a[1]) / edge_len
        a_in = (a[0] + ux * inset, a[1] + uy * inset)
        b_in = (b[0] - ux * inset, b[1] - uy * inset)
        cuts = _enc_merge_cuts(by_edge.get(i, []))
        t_inset = inset / edge_len
        denom = 1.0 - 2.0 * t_inset
        inset_cuts: list[tuple[float, float]] = []
        if denom > 1e-9:
            for lo, hi in cuts:
                new_lo = max(0.0, (lo - t_inset) / denom)
                new_hi = min(1.0, (hi - t_inset) / denom)
                if new_hi > new_lo:
                    inset_cuts.append((new_lo, new_hi))
        subs = _enc_subsegments(a_in, b_in, inset_cuts)
        for (sa, sb) in subs:
            out.extend(_enc_centered_fortification_chain(sa, sb))

    # Wood gate visuals (legacy fortification drew nothing here;
    # design/map_ir.md §7.15 makes gates a first-class concept and
    # always paints their rect).
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        for t_center, _ in midpoints.get(i, []):
            out.append(_enc_palisade_door_rect(a, b, t_center))

    corner_style = int(op.cornerStyle)
    for (x, y) in polygon:
        out.append(_enc_corner_shape(x, y, corner_style))
    return out


_OP_HANDLERS[Op.Op.EnclosureOp] = _draw_enclosure_from_ir


# ── BuildingExteriorWallOp + BuildingInteriorWallOp (Phase 8.3) ─
#
# Constants mirror nhc/rendering/_building_walls.py + building.py
# value-for-value (palette, dimensions, edge-extension trick).
# Both rasterisers walk the same splitmix64 stream — the Rust
# port at crates/nhc-render/src/transform/png/building_*.rs
# lands at 8.3c.


_MASONRY_STRIP_COUNT = 2
_MASONRY_MEAN_WIDTH = 12.0
_MASONRY_WIDTH_LOW = 0.9
_MASONRY_WIDTH_HIGH = 1.1
_MASONRY_CORNER_RADIUS = 1.2
_MASONRY_STROKE_WIDTH = 1.0
_MASONRY_WALL_THICKNESS = 8.0
_MASONRY_STRIP_OFFSETS = (0.0, _MASONRY_MEAN_WIDTH / 2)

_BRICK_FILL = "#B4695A"
_BRICK_SEAM = "#6A3A2A"
_STONE_FILL = "#9A8E80"
_STONE_SEAM = "#4A3E35"

_INTERIOR_WALL_COLORS: dict[int, str] = {
    # InteriorWallMaterial: Stone=0, Brick=1, Wood=2.
    0: "#707070",
    1: "#c4651d",
    2: "#7a4e2c",
}
_INTERIOR_WALL_STROKE_WIDTH = CELL * 0.25


def _masonry_palette(material: int) -> tuple[str, str]:
    """``WallMaterial`` int -> (fill, seam) hex strings."""
    from nhc.rendering.ir._fb.WallMaterial import WallMaterial
    if material == WallMaterial.Brick:
        return (_BRICK_FILL, _BRICK_SEAM)
    return (_STONE_FILL, _STONE_SEAM)


def _masonry_ortho_rect(
    horizontal: bool, run_start: float, perp: float,
    pos: float, width: float, strip_thick: float,
    fill: str, stroke: str,
) -> str:
    if horizontal:
        x = run_start + pos
        y = perp
        w = width
        h = strip_thick
    else:
        x = perp
        y = run_start + pos
        w = strip_thick
        h = width
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'rx="{_MASONRY_CORNER_RADIUS}" '
        f'ry="{_MASONRY_CORNER_RADIUS}" '
        f'fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{_MASONRY_STROKE_WIDTH}"/>'
    )


def _masonry_diagonal_rect(
    pos: float, perp: float, width: float, strip_thick: float,
    x0: float, y0: float, angle_deg: float,
    fill: str, stroke: str,
) -> str:
    return (
        f'<rect x="{pos:.1f}" y="{perp:.1f}" '
        f'width="{width:.1f}" height="{strip_thick:.1f}" '
        f'rx="{_MASONRY_CORNER_RADIUS}" '
        f'ry="{_MASONRY_CORNER_RADIUS}" '
        f'fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{_MASONRY_STROKE_WIDTH}" '
        f'transform="translate({x0:.1f} {y0:.1f}) '
        f'rotate({angle_deg:.2f})"/>'
    )


def _render_masonry_wall_run(
    x0: float, y0: float, x1: float, y1: float,
    *, rng: _SplitMix64, fill: str, stroke: str,
) -> list[str]:
    """Two-strip running-bond chain along a wall centerline.

    Mirrors nhc/rendering/_building_walls._render_masonry_wall_run
    but uses splitmix64 instead of random.Random.
    """
    import math
    if x0 == x1 and y0 == y1:
        return []
    horizontal = y0 == y1
    vertical = x0 == x1
    strip_thick = _MASONRY_WALL_THICKNESS / _MASONRY_STRIP_COUNT
    out: list[str] = []
    if horizontal or vertical:
        run_len = abs(x1 - x0) if horizontal else abs(y1 - y0)
        run_start = min(x0, x1) if horizontal else min(y0, y1)
        perp_start = (y0 if horizontal else x0) - _MASONRY_WALL_THICKNESS / 2
        for idx in range(_MASONRY_STRIP_COUNT):
            perp = perp_start + idx * strip_thick
            pos = max(0.0, _MASONRY_STRIP_OFFSETS[idx])
            while pos < run_len:
                width = _MASONRY_MEAN_WIDTH * rng.uniform(
                    _MASONRY_WIDTH_LOW, _MASONRY_WIDTH_HIGH,
                )
                width = min(width, run_len - pos)
                out.append(_masonry_ortho_rect(
                    horizontal, run_start, perp,
                    pos, width, strip_thick, fill, stroke,
                ))
                pos += width
        return out
    # Diagonal run.
    dx = x1 - x0
    dy = y1 - y0
    run_len = math.hypot(dx, dy)
    angle_deg = math.degrees(math.atan2(dy, dx))
    for idx in range(_MASONRY_STRIP_COUNT):
        perp = -_MASONRY_WALL_THICKNESS / 2 + idx * strip_thick
        pos = max(0.0, _MASONRY_STRIP_OFFSETS[idx])
        while pos < run_len:
            width = _MASONRY_MEAN_WIDTH * rng.uniform(
                _MASONRY_WIDTH_LOW, _MASONRY_WIDTH_HIGH,
            )
            width = min(width, run_len - pos)
            out.append(_masonry_diagonal_rect(
                pos, perp, width, strip_thick,
                x0, y0, angle_deg, fill, stroke,
            ))
            pos += width
    return out


def _draw_building_exterior_wall_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 8.3: per-building masonry perimeter pass.

    Resolves region_ref, walks polygon edges, and emits a 2-strip
    running-bond chain along each. Adjacent edges overlap by half
    the wall thickness at every vertex so the corner square paints
    fully (mirrors building.py:113-130).

    Phase 1.16: suppressed when in-scope ExteriorWallOp entries are
    present in the IR (the new handler renders the same pixels).
    """
    if _has_consumed_exterior_wall_ops(fir):
        return []
    import math
    op = OpCreator(entry.OpType(), entry.Op())
    region_ref = _to_str(op.regionRef)
    region = _find_region(fir, op.regionRef)
    if region is None:
        raise ValueError(
            f"BuildingExteriorWallOp references unknown region "
            f"{region_ref!r}"
        )
    # Phase 1.26g — read footprint from Region.outline.
    outline_fb = region.Outline()
    if outline_fb is None or outline_fb.VerticesLength() < 3:
        return []
    polygon: list[tuple[float, float]] = [
        (outline_fb.Vertices(i).X(), outline_fb.Vertices(i).Y())
        for i in range(outline_fb.VerticesLength())
    ]
    fill, stroke = _masonry_palette(int(op.material))
    rng_seed = int(op.rngSeed)
    ext = _MASONRY_WALL_THICKNESS / 2
    out: list[str] = []
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        dx = bx - ax
        dy = by - ay
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        ux = dx / length
        uy = dy / length
        ax_ext = ax - ux * ext
        ay_ext = ay - uy * ext
        bx_ext = bx + ux * ext
        by_ext = by + uy * ext
        edge_rng = _SplitMix64(rng_seed + i)
        out.extend(_render_masonry_wall_run(
            ax_ext, ay_ext, bx_ext, by_ext,
            rng=edge_rng, fill=fill, stroke=stroke,
        ))
    return out


_OP_HANDLERS[Op.Op.BuildingExteriorWallOp] = (
    _draw_building_exterior_wall_from_ir
)


def _tile_corner_delta(corner: int) -> tuple[int, int]:
    """``TileCorner`` int -> (Δx, Δy)."""
    from nhc.rendering.ir._fb.TileCorner import TileCorner
    if corner == TileCorner.NW:
        return (0, 0)
    if corner == TileCorner.NE:
        return (1, 0)
    if corner == TileCorner.SE:
        return (1, 1)
    return (0, 1)  # SW


def _draw_building_interior_wall_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 8.3: per-building partition lines.

    InteriorEdge endpoints are corner-grid vertices `(tile + Δ)`.
    The op carries the pre-coalesced + door-suppression-filtered
    edge list — the rasteriser is a thin per-edge stroke pass.

    Phase 1.16: suppressed when in-scope InteriorWallOp entries are
    present in the IR (the new handler renders the same pixels).
    """
    if _has_consumed_interior_wall_ops(fir):
        return []
    op = OpCreator(entry.OpType(), entry.Op())
    edges = op.edges or []
    if not edges:
        return []
    color = _INTERIOR_WALL_COLORS.get(int(op.material), _INTERIOR_WALL_COLORS[0])
    out: list[str] = []
    for edge in edges:
        adx, ady = _tile_corner_delta(int(edge.aCorner))
        bdx, bdy = _tile_corner_delta(int(edge.bCorner))
        px0 = (edge.ax + adx) * CELL
        py0 = (edge.ay + ady) * CELL
        px1 = (edge.bx + bdx) * CELL
        py1 = (edge.by + bdy) * CELL
        out.append(
            f'<line x1="{px0}" y1="{py0}" '
            f'x2="{px1}" y2="{py1}" '
            f'stroke="{color}" '
            f'stroke-width="{_INTERIOR_WALL_STROKE_WIDTH}" '
            f'stroke-linecap="round"/>'
        )
    return out


_OP_HANDLERS[Op.Op.BuildingInteriorWallOp] = (
    _draw_building_interior_wall_from_ir
)


# ── ExteriorWallOp + InteriorWallOp (Phase 1.16) ────────────────
#
# New 4.0 wall ops: each carries an ``Outline`` (polygon vertices or
# Circle/Pill descriptor) plus a ``WallStyle`` enum. The consumer
# reproduces the same SVG as the legacy handlers it shadows.
#
# In-scope styles for Phase 1.16:
#   ExteriorWallOp: MasonryBrick, MasonryStone (buildings),
#                   Palisade, FortificationMerlon (enclosures)
#   InteriorWallOp: PartitionStone, PartitionBrick, PartitionWood
#
# Added in Phase 1.15b:
#   ExteriorWallOp: CaveInk (cave perimeter stroke; paired with
#     CaveFloor FloorOp from Phase 1.15b consumer switch).
#
# Deferred to Phase 1.16b (the only remaining deferred category):
#   ExteriorWallOp: DungeonInk (dungeon rect/smooth wall segments —
#     still emitted via WallsAndFloorsOp wall_segments / smooth_walls).
#
# Suppression: when ExteriorWallOp entries are present in the IR, their
# legacy counterparts (EnclosureOp for Palisade/FortificationMerlon,
# BuildingExteriorWallOp for Masonry) are suppressed. Similarly,
# BuildingInteriorWallOp is suppressed when InteriorWallOp is present.
# The detection is done via a pre-scan helper (_collect_consumed_wall_ops)
# that is called from each legacy handler's entry point.
#
# Phase 1.16b-3: DungeonInk ExteriorWallOp is NOW in scope. The emitter
# still populates wall_segments / smooth_walls / wall_extensions_d in
# WallsAndFloorsOp for legacy fallback; _draw_walls_and_floors_from_ir
# suppresses them when CorridorWallOp + DungeonInk ExteriorWallOps are
# both present. Phase 1.19 will stop populating those fields.

_EXTERIOR_WALL_IN_SCOPE = frozenset({
    # Phase 1.16 in-scope ExteriorWallOp styles. DungeonInk (0) added
    # in Phase 1.16b-3 (consumer switch). CaveInk (1) added in 1.15b.
    0,  # DungeonInk (Phase 1.16b-3)
    1,  # CaveInk (Phase 1.15b)
    2,  # MasonryBrick
    3,  # MasonryStone
    7,  # Palisade
    8,  # FortificationMerlon
})

_INTERIOR_WALL_IN_SCOPE = frozenset({
    # All Partition styles are in scope for Phase 1.16.
    4,  # PartitionStone
    5,  # PartitionBrick
    6,  # PartitionWood
    0,  # DungeonInk interior walls (future; safe to include now)
})


def _collect_consumed_wall_ops(
    fir: FloorIR,
) -> tuple[list[Any], list[Any]]:
    """Return (exterior_wall_ops, interior_wall_ops) from ``fir.ops[]``.

    Scans the full op list and returns two lists:
    - ``exterior_wall_ops``: ``OpEntry`` objects whose type is
      ``ExteriorWallOp`` and whose style is in ``_EXTERIOR_WALL_IN_SCOPE``.
      DungeonInk (0) included (Phase 1.16b-3).
      CaveInk (1) included (Phase 1.15b).
    - ``interior_wall_ops``: ``OpEntry`` objects whose type is
      ``InteriorWallOp`` and whose style is in ``_INTERIOR_WALL_IN_SCOPE``.

    Used both to drive the new handlers and as the legacy-suppression
    discriminant: if ``exterior_wall_ops`` is non-empty, the matching
    legacy handlers (EnclosureOp / BuildingExteriorWallOp) no-op.
    """
    ext_ops: list[Any] = []
    int_ops: list[Any] = []
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        op_type = entry.OpType()
        if op_type == Op.Op.ExteriorWallOp:
            op = OpCreator(op_type, entry.Op())
            if op is not None and int(op.style) in _EXTERIOR_WALL_IN_SCOPE:
                ext_ops.append(entry)
        elif op_type == Op.Op.InteriorWallOp:
            op = OpCreator(op_type, entry.Op())
            if op is not None and int(op.style) in _INTERIOR_WALL_IN_SCOPE:
                int_ops.append(entry)
    return ext_ops, int_ops


def _build_legacy_seed_index(fir: FloorIR) -> dict[int, int]:
    """Build a mapping: in-scope ExteriorWallOp position → RNG seed.

    The emitter pairs each in-scope ExteriorWallOp with a legacy op
    that carries the RNG seed (BuildingExteriorWallOp for masonry,
    EnclosureOp for palisade/fortification). This helper walks the
    ops list once, collecting legacy seeds in emission order, then
    pairs them by index to the ExteriorWallOps of matching style
    groups.

    Masonry (MasonryBrick=2, MasonryStone=3): paired with
      BuildingExteriorWallOp (one-to-one in emission order).
    Enclosure (Palisade=7, FortificationMerlon=8): paired with
      EnclosureOp (one-to-one in emission order).

    Returns a dict mapping the ordinal index of each in-scope
    ExteriorWallOp entry (counting from 0 across ALL in-scope
    styles) to its rng_seed. Ops with no paired legacy seed map
    to 0 (produces a plausible but non-matching pattern; only
    reached for IRs generated without the parallel-emission rule).
    """
    masonry_seeds: list[int] = []
    enclosure_seeds: list[int] = []

    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        op_type = entry.OpType()
        if op_type == Op.Op.BuildingExteriorWallOp:
            op = OpCreator(op_type, entry.Op())
            if op is not None:
                masonry_seeds.append(int(op.rngSeed))
        elif op_type == Op.Op.EnclosureOp:
            op = OpCreator(op_type, entry.Op())
            if op is not None:
                enclosure_seeds.append(int(op.rngSeed))

    # Walk the ExteriorWallOps in order and assign seeds.
    masonry_idx = 0
    enclosure_idx = 0
    result: dict[int, int] = {}
    slot = 0
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.ExteriorWallOp:
            continue
        op = OpCreator(Op.Op.ExteriorWallOp, entry.Op())
        if op is None:
            slot += 1
            continue
        style = int(op.style)
        if style not in _EXTERIOR_WALL_IN_SCOPE:
            continue
        if style in (2, 3):  # MasonryBrick, MasonryStone
            seed = (
                masonry_seeds[masonry_idx]
                if masonry_idx < len(masonry_seeds) else 0
            )
            masonry_idx += 1
        elif style in (7, 8):  # Palisade, FortificationMerlon
            seed = (
                enclosure_seeds[enclosure_idx]
                if enclosure_idx < len(enclosure_seeds) else 0
            )
            enclosure_idx += 1
        else:
            seed = 0
        result[slot] = seed
        slot += 1
    return result


def _get_legacy_seed(fir: FloorIR, ext_wall_slot: int) -> int:
    """Return the legacy RNG seed for the N-th in-scope ExteriorWallOp.

    Builds the seed index on each call (no caching — the IR scan is
    O(ops) which is cheap, and caching by id(fir) is unsafe due to
    Python memory-address reuse for short-lived objects).

    Phase 1.20 fallback: this function is only called when the new
    ExteriorWallOp's ``rng_seed`` field is 0 (3.x cached buffers).
    Fresh IRs carry the seed on the new op directly — see the
    ``op.rngSeed`` short-circuit in ``_draw_exterior_wall_op_from_ir``.
    """
    return _build_legacy_seed_index(fir).get(ext_wall_slot, 0)


def _cuts_for_edge(
    ax: float, ay: float, bx: float, by: float,
    cuts: list[Any],
) -> list[tuple[float, float]]:
    """Return parametric ``(lo_t, hi_t)`` cut intervals on edge (a→b).

    Each ``Cut`` carries pixel-space ``start``/``end`` coords. This
    helper projects those coords onto the edge's unit vector to compute
    parametric t values (0.0 = vertex a, 1.0 = vertex b). Cuts that
    don't land on this edge are rejected by two criteria:
    1. Parametric t outside [0, 1] (± tolerance) — the cut is beyond
       the edge endpoints.
    2. Perpendicular distance from the cut's midpoint to the edge's
       infinite line exceeds a pixel threshold — the cut belongs to a
       parallel but offset edge, not this one.
    """
    import math
    dx = bx - ax
    dy = by - ay
    edge_len = math.hypot(dx, dy)
    if edge_len < 1e-6:
        return []
    ux = dx / edge_len
    uy = dy / edge_len
    # Perpendicular unit vector (rotated 90°).
    px = -uy
    py = ux
    result: list[tuple[float, float]] = []
    for cut in cuts:
        if cut is None or cut.start is None or cut.end is None:
            continue
        sx, sy = float(cut.start.x), float(cut.start.y)
        ex, ey = float(cut.end.x), float(cut.end.y)
        # Midpoint of the cut.
        mx = (sx + ex) / 2.0
        my = (sy + ey) / 2.0
        # Perpendicular distance from midpoint to the edge's infinite line.
        perp_dist = abs((mx - ax) * px + (my - ay) * py)
        # Accept only cuts within 2 pixels of the edge (pixel-space coords
        # are integers × CELL so ≥ 16 px perp distance means a different
        # edge). Use a generous 4 px threshold to handle float rounding.
        if perp_dist > 4.0:
            continue
        # Project start/end onto the edge.
        ts = ((sx - ax) * ux + (sy - ay) * uy) / edge_len
        te = ((ex - ax) * ux + (ey - ay) * uy) / edge_len
        lo_t = min(ts, te)
        hi_t = max(ts, te)
        # Accept only cuts that overlap [0, 1] (with a small tolerance).
        _TOL = 0.05
        if hi_t < -_TOL or lo_t > 1.0 + _TOL:
            continue
        lo_t = max(0.0, lo_t)
        hi_t = min(1.0, hi_t)
        if hi_t > lo_t:
            result.append((lo_t, hi_t))
    return result


def _palisade_door_center(
    ax: float, ay: float, bx: float, by: float,
    cuts: list[Any],
) -> list[tuple[float, float, float]]:
    """Return gate centre (t_center, half_px) for palisade door rects.

    Converts pixel-coord Cut entries on this edge to (t_center,
    half_px) tuples for ``_enc_palisade_door_rect``. Only cuts whose
    style is NOT ``CutStyle.None_`` and NOT ``CutStyle.DoorSecret``
    are included (bare gaps / secret doors have no visible visual).
    Cuts that don't lie on this edge (perpendicular distance > 4 px)
    are silently skipped.
    """
    import math
    from nhc.rendering.ir._fb.CutStyle import CutStyle as CS
    dx = bx - ax
    dy = by - ay
    edge_len = math.hypot(dx, dy)
    if edge_len < 1e-6:
        return []
    ux = dx / edge_len
    uy = dy / edge_len
    # Perpendicular unit vector.
    px = -uy
    py = ux
    result: list[tuple[float, float, float]] = []
    for cut in cuts:
        if cut is None or cut.start is None or cut.end is None:
            continue
        style = int(cut.style)
        if style == CS.None_ or style == CS.DoorSecret:
            continue
        sx, sy = float(cut.start.x), float(cut.start.y)
        ex, ey = float(cut.end.x), float(cut.end.y)
        # Perpendicular distance from cut midpoint to this edge's line.
        mx = (sx + ex) / 2.0
        my = (sy + ey) / 2.0
        perp_dist = abs((mx - ax) * px + (my - ay) * py)
        if perp_dist > 4.0:
            continue
        # Centre of the cut in edge-parametric t.
        ts = ((sx - ax) * ux + (sy - ay) * uy) / edge_len
        te = ((ex - ax) * ux + (ey - ay) * uy) / edge_len
        t_center = (ts + te) / 2.0
        half_px = abs(te - ts) * edge_len / 2.0
        result.append((t_center, half_px, style))
    return result


def _ext_wall_op_slot(entry: OpEntry, fir: FloorIR) -> int:
    """Return the ordinal index (0-based) of ``entry`` among in-scope
    ExteriorWallOp entries in ``fir.ops[]``. Returns -1 if not found.

    Used to look up the paired legacy RNG seed via
    ``_get_legacy_seed(fir, slot)``. Identity is determined by
    comparing the FlatBuffers table byte-offset (``entry._tab.Pos``).
    """
    target_pos = entry._tab.Pos  # type: ignore[attr-defined]
    slot = 0
    for i in range(fir.OpsLength()):
        e = fir.Ops(i)
        if e.OpType() != Op.Op.ExteriorWallOp:
            continue
        op = OpCreator(Op.Op.ExteriorWallOp, e.Op())
        if op is None:
            continue
        if int(op.style) not in _EXTERIOR_WALL_IN_SCOPE:
            continue
        if e._tab.Pos == target_pos:  # type: ignore[attr-defined]
            return slot
        slot += 1
    return -1


def _draw_exterior_wall_op_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 1.16: dispatch ExteriorWallOp on WallStyle.

    In-scope styles:
    - ``MasonryBrick`` / ``MasonryStone``: reproduce the 2-strip
      running-bond chain from ``_draw_building_exterior_wall_from_ir``,
      reading vertices from ``outline.vertices`` instead of the legacy
      region polygon lookup.
    - ``Palisade``: reproduce palisade circle chain from
      ``_draw_enclosure_from_ir``, converting pixel-coord cuts to
      per-edge parametric intervals.
    - ``FortificationMerlon``: reproduce centered fortification chain +
      corner shapes from ``_draw_enclosure_from_ir``.
    - ``CaveInk`` (1): buffer+jitter+smooth pipeline from
      ``outline.vertices`` (raw tile-boundary ring stored by the emitter
      via ``_cave_raw_exterior_coords``). RNG seeded from
      ``fir.BaseSeed() + 0x5A17E5`` — same offset as
      ``_render_context.py:117``. Shares geometry with the paired
      CaveFloor FloorOp fill via ``_cave_path_from_outline``.

    RNG seed: ExteriorWallOpT carries no rngSeed field. Each new op
    is parallel-emitted alongside a legacy op (BuildingExteriorWallOp
    or EnclosureOp) that does carry the seed. The handler reads the
    paired seed via ``_get_legacy_seed`` so the masonry / palisade
    layout is byte-identical to the legacy output.

    Phase 1.16b-3 (now active):
    - ``DungeonInk`` (0): walks polygon outline with cuts via
      ``_walk_polygon_with_cuts``, emits ``<path>`` with DungeonInk
      stroke. Handles both rect (4-vertex) and smooth (8+ vertex)
      room outlines. Suppression of legacy fields is coordinated
      by ``_draw_walls_and_floors_from_ir`` via
      ``_has_consumed_dungeon_exterior_wall_ops``.
    """
    import math
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.WallStyle import WallStyle as WS

    op = OpCreator(entry.OpType(), entry.Op())
    if op is None:
        return []
    outline = op.outline
    # Phase 1.24 — region-keyed dispatch + op-level cuts. When
    # ``op.region_ref`` is non-empty AND resolves to a Region with a
    # populated outline, the geometry comes from
    # ``region.outline()``. When ``op.cuts`` is populated, it
    # supersedes the legacy ``outline.cuts`` for stroke break
    # intervals. Both fields default empty; empty refs / cuts fall
    # through to the legacy path. Mirrors the FloorOp.region_ref
    # dispatch from 1.23a. Mutating ``outline.cuts`` keeps the
    # rest of the function's ``outline.cuts`` reads transparently
    # working off the resolved cuts list.
    region_ref = op.regionRef or b""
    if region_ref:
        region = _find_region(fir, region_ref)
        if region is not None:
            region_outline_fb = region.Outline()
            if region_outline_fb is not None:
                outline = OutlineT.InitFromObj(region_outline_fb)
    if outline is None:
        return []
    op_cuts = list(op.cuts or [])
    if op_cuts:
        outline.cuts = op_cuts

    style = int(op.style)

    if style == WS.DungeonInk:
        # Phase 1.16b-3: emit polygon / circle / pill outline with cuts.
        # Matches legacy smooth_wall_svg output per descriptor kind.
        #
        # Legacy rules (from _floor_layers.py / _room_outlines.py):
        #   • Polygon rooms without corridor openings → <polygon points>
        #   • Polygon rooms with corridor openings   → <path d="…"> with
        #     gaps at None_ cut positions (doors are NOT gapped — they are
        #     rendered as separate overlays, so the wall stroke is
        #     unbroken at door positions).
        #   • Circle rooms without corridor openings → <circle cx cy r/>
        #   • Circle rooms with corridor openings   → <path d="…A…"> with
        #     arc gaps at None_ cut positions.
        #   • Pill rooms: treated as <rect rx ry/> (no gaps; pill rooms
        #     do not currently generate None_ corridor-opening cuts).
        #   • Rect rooms (4-vertex polygon): apply all cuts (the legacy
        #     wall_segments algorithm also skips door-tile edges).
        from nhc.rendering.ir._fb.CutStyle import CutStyle as _CS
        from nhc.rendering.ir._fb import OutlineKind as _OKMod

        _OK = _OKMod.OutlineKind
        _stroke = (
            f'fill="none" stroke="{INK}" '
            f'stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"'
        )

        kind_di = outline.descriptorKind
        cuts_di: list[Any] = list(outline.cuts or [])

        if kind_di == _OK.Circle:
            # Circle descriptor: cx / cy / rx == radius.
            ccx_di = float(outline.cx)
            ccy_di = float(outline.cy)
            r_di = float(outline.rx)
            if r_di <= 0:
                return []
            # Only None_ cuts matter (corridor openings; doors not gapped).
            none_cuts_ci = [c for c in cuts_di if int(c.style) == _CS.None_]
            if not none_cuts_ci:
                # Closed circle: emit <circle> matching legacy format.
                return [
                    f'<circle cx="{ccx_di:.1f}" cy="{ccy_di:.1f}" '
                    f'r="{r_di:.1f}" {_stroke}/>'
                ]
            # Gapped circle: arc path segments, mirroring _circle_with_gaps.
            TWO_PI = 2.0 * math.pi
            gap_intervals: list[tuple[float, float]] = []
            for c in none_cuts_ci:
                ax_c = float(c.start.x)
                ay_c = float(c.start.y)
                bx_c = float(c.end.x)
                by_c = float(c.end.y)
                a1_c = math.atan2(ay_c - ccy_di, ax_c - ccx_di) % TWO_PI
                a2_c = math.atan2(by_c - ccy_di, bx_c - ccx_di) % TWO_PI
                if a1_c > a2_c:
                    a1_c, a2_c = a2_c, a1_c
                span_c = a2_c - a1_c
                if span_c > math.pi:
                    gap_intervals.append((a2_c, a1_c + TWO_PI))
                else:
                    gap_intervals.append((a1_c, a2_c))
            gap_intervals.sort()
            n_gi = len(gap_intervals)
            arc_parts: list[str] = []
            for gi_idx in range(n_gi):
                gap_end_a = gap_intervals[gi_idx][1]
                next_start_a = gap_intervals[(gi_idx + 1) % n_gi][0]
                if gi_idx == n_gi - 1:
                    next_start_a += TWO_PI
                if next_start_a <= gap_end_a:
                    continue
                sx_c = ccx_di + r_di * math.cos(gap_end_a)
                sy_c = ccy_di + r_di * math.sin(gap_end_a)
                ex_c = ccx_di + r_di * math.cos(next_start_a)
                ey_c = ccy_di + r_di * math.sin(next_start_a)
                sweep_c = (next_start_a - gap_end_a) % TWO_PI
                large_c = 1 if sweep_c > math.pi else 0
                arc_parts.append(
                    f'M{sx_c:.1f},{sy_c:.1f} '
                    f'A{r_di:.1f},{r_di:.1f} 0 {large_c},1 '
                    f'{ex_c:.1f},{ey_c:.1f}'
                )
            if not arc_parts:
                return []
            d_ci = " ".join(arc_parts)
            return [f'<path d="{d_ci}" {_stroke}/>']

        if kind_di == _OK.Pill:
            # Pill descriptor: emit <rect rx ry> matching legacy format.
            # Pill rooms do not produce None_ corridor-opening cuts in
            # current dungeons, so no gap handling is needed.
            cx_p = float(outline.cx)
            cy_p = float(outline.cy)
            rx_p = float(outline.rx)
            ry_p = float(outline.ry)
            if rx_p <= 0 or ry_p <= 0:
                return []
            radius_p = min(rx_p, ry_p)
            return [
                f'<rect x="{cx_p - rx_p:.1f}" y="{cy_p - ry_p:.1f}" '
                f'width="{2 * rx_p:.1f}" height="{2 * ry_p:.1f}" '
                f'rx="{radius_p:.1f}" ry="{radius_p:.1f}" {_stroke}/>'
            ]

        # Polygon descriptor (default).
        verts_di = outline.vertices
        if not verts_di or len(verts_di) < 2:
            return []
        polygon_di: list[tuple[float, float]] = [
            (float(v.x), float(v.y)) for v in verts_di
        ]
        n_verts_di = len(polygon_di)
        if n_verts_di > 4:
            # Smooth polygon: only apply corridor-opening cuts (None_).
            none_cuts_di = [c for c in cuts_di if int(c.style) == _CS.None_]
            if not none_cuts_di:
                # No corridor openings: closed polygon matches legacy
                # <polygon points="..."> format from smooth_wall_svg.
                pts_di = " ".join(
                    f"{x:.1f},{y:.1f}" for x, y in polygon_di
                )
                return [f'<polygon points="{pts_di}" {_stroke}/>']
            d = _walk_polygon_with_cuts(polygon_di, none_cuts_di)
            if not d:
                return []
            return [f'<path d="{d}" {_stroke}/>']
        # Rect polygon (4 vertices): apply all cuts.
        d = _walk_polygon_with_cuts(polygon_di, cuts_di)
        if not d:
            return []
        return [f'<path d="{d}" {_stroke}/>']

    if style == WS.CaveInk:
        # Real consumer: run the buffer+jitter+smooth pipeline on
        # ExteriorWallOp.outline.vertices (the raw tile-boundary ring
        # from _cave_raw_exterior_coords) to produce byte-identical
        # cave stroke to the legacy _build_cave_wall_geometry path.
        # Seeded from fir.BaseSeed() + 0x5A17E5 (same offset as
        # _render_context.py:117).  Shares geometry with the CaveFloor
        # FloorOp fill via the same helper.
        cave_verts = outline.vertices
        if not cave_verts or len(cave_verts) < 4:
            return []
        cave_coords = [(float(v.x), float(v.y)) for v in cave_verts]
        path_el = _cave_path_from_outline(cave_coords, fir.BaseSeed())
        return [
            path_el.replace(
                "/>",
                f' fill="none" stroke="{INK}"'
                f' stroke-width="{WALL_WIDTH}"'
                f' stroke-linecap="round"'
                f' stroke-linejoin="round"/>',
            )
        ]

    verts = outline.vertices
    if not verts or len(verts) < 2:
        return []
    polygon: list[tuple[float, float]] = [
        (float(v.x), float(v.y)) for v in verts
    ]
    cuts: list[Any] = list(outline.cuts or [])

    # Resolve the RNG seed. Phase 1.20+: the new ExteriorWallOp
    # carries `rng_seed` directly, so prefer it. Fall back to the
    # paired-legacy-op lookup only when the new field is 0 (3.x
    # cached buffers without rng_seed populated).
    rng_seed = int(getattr(op, "rngSeed", 0) or 0)
    if rng_seed == 0:
        slot = _ext_wall_op_slot(entry, fir)
        rng_seed = _get_legacy_seed(fir, slot) if slot >= 0 else 0

    if style in (WS.MasonryBrick, WS.MasonryStone):
        # Mirror _draw_building_exterior_wall_from_ir: two-strip
        # running-bond chain along each polygon edge with ±ext overlap
        # at vertices.
        fill, stroke = _masonry_palette(style - 2)  # MasonryBrick=2→0, Stone=3→1
        ext = _MASONRY_WALL_THICKNESS / 2
        out: list[str] = []
        n = len(polygon)
        for i in range(n):
            ax, ay = polygon[i]
            bx, by = polygon[(i + 1) % n]
            dx = bx - ax
            dy = by - ay
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            ux = dx / length
            uy = dy / length
            ax_ext = ax - ux * ext
            ay_ext = ay - uy * ext
            bx_ext = bx + ux * ext
            by_ext = by + uy * ext
            edge_rng = _SplitMix64(rng_seed + i)
            out.extend(_render_masonry_wall_run(
                ax_ext, ay_ext, bx_ext, by_ext,
                rng=edge_rng, fill=fill, stroke=stroke,
            ))
        return out

    if style == WS.Palisade:
        # Mirror _draw_enclosure_from_ir Palisade branch.
        n = len(polygon)
        out_frags: list[str] = []
        for i in range(n):
            a = polygon[i]
            b = polygon[(i + 1) % n]
            ax2, ay2 = a
            bx2, by2 = b
            edge_cuts_t = _enc_merge_cuts(
                _cuts_for_edge(ax2, ay2, bx2, by2, cuts)
            )
            subs = _enc_subsegments(a, b, edge_cuts_t)
            edge_rng = _SplitMix64(rng_seed + i)
            for sa, sb in subs:
                out_frags.extend(_enc_palisade_circles([sa, sb], edge_rng))
            # Gate visuals (door rect at cut centre).
            for t_center, _half_px, _cs in _palisade_door_center(
                ax2, ay2, bx2, by2, cuts,
            ):
                out_frags.append(_enc_palisade_door_rect(a, b, t_center))
        return out_frags

    if style == WS.FortificationMerlon:
        # Mirror _draw_enclosure_from_ir Fortification branch.
        corner_style_int = int(op.cornerStyle)
        n = len(polygon)
        inset = _enc_corner_inset()
        out_fort: list[str] = []
        for i in range(n):
            a = polygon[i]
            b = polygon[(i + 1) % n]
            ax3, ay3 = a
            bx3, by3 = b
            edge_len = math.hypot(bx3 - ax3, by3 - ay3)
            if edge_len <= 2 * inset + 1e-6:
                continue
            ux2 = (bx3 - ax3) / edge_len
            uy2 = (by3 - ay3) / edge_len
            a_in = (ax3 + ux2 * inset, ay3 + uy2 * inset)
            b_in = (bx3 - ux2 * inset, by3 - uy2 * inset)
            edge_cuts_t = _enc_merge_cuts(
                _cuts_for_edge(ax3, ay3, bx3, by3, cuts)
            )
            t_inset = inset / edge_len
            denom = 1.0 - 2.0 * t_inset
            inset_cuts: list[tuple[float, float]] = []
            if denom > 1e-9:
                for lo, hi in edge_cuts_t:
                    new_lo = max(0.0, (lo - t_inset) / denom)
                    new_hi = min(1.0, (hi - t_inset) / denom)
                    if new_hi > new_lo:
                        inset_cuts.append((new_lo, new_hi))
            subs2 = _enc_subsegments(a_in, b_in, inset_cuts)
            for sa2, sb2 in subs2:
                out_fort.extend(_enc_centered_fortification_chain(sa2, sb2))

        # Wood gate visuals.
        for i in range(n):
            a = polygon[i]
            b = polygon[(i + 1) % n]
            ax4, ay4 = a
            bx4, by4 = b
            for t_center, _hp, _cs in _palisade_door_center(
                ax4, ay4, bx4, by4, cuts,
            ):
                out_fort.append(_enc_palisade_door_rect(a, b, t_center))

        # Corner blocks on top.
        for x, y in polygon:
            out_fort.append(_enc_corner_shape(x, y, corner_style_int))
        return out_fort

    # Any other deferred style: return empty.
    return []


def _draw_interior_wall_op_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 1.16: emit a <line> for each InteriorWallOp partition segment.

    An ``InteriorWallOp`` carries a 2-vertex open polyline (two corner-
    grid pixel coords) and a ``WallStyle`` (PartitionStone /
    PartitionBrick / PartitionWood). The rasteriser emits one
    ``<line>`` per op — the same stroke as the legacy
    ``_draw_building_interior_wall_from_ir`` per-edge line, but reading
    from the new op's ``outline.vertices`` rather than the edge table.
    """
    from nhc.rendering.ir._fb.WallStyle import WallStyle as WS

    op = OpCreator(entry.OpType(), entry.Op())
    if op is None:
        return []
    outline = op.outline
    if outline is None:
        return []
    verts = outline.vertices
    if not verts or len(verts) < 2:
        return []

    style = int(op.style)
    # Map WallStyle partition ints to the legacy color dict keys.
    # PartitionStone=4 → key 0 (stone), Brick=5 → key 1, Wood=6 → key 2.
    _STYLE_TO_MATERIAL: dict[int, int] = {
        WS.PartitionStone: 0,
        WS.PartitionBrick: 1,
        WS.PartitionWood: 2,
        WS.DungeonInk: 0,  # DungeonInk interior walls use stone colour
    }
    material_key = _STYLE_TO_MATERIAL.get(style, 0)
    color = _INTERIOR_WALL_COLORS.get(material_key, _INTERIOR_WALL_COLORS[0])

    out: list[str] = []
    # Walk pairs of consecutive vertices (for a 2-vertex open polyline
    # there is exactly one segment; for longer chains, all segments).
    pts = [(float(v.x), float(v.y)) for v in verts]
    for i in range(len(pts) - 1):
        px0, py0 = pts[i]
        px1, py1 = pts[i + 1]
        out.append(
            f'<line x1="{px0:.0f}" y1="{py0:.0f}" '
            f'x2="{px1:.0f}" y2="{py1:.0f}" '
            f'stroke="{color}" '
            f'stroke-width="{_INTERIOR_WALL_STROKE_WIDTH}" '
            f'stroke-linecap="round"/>'
        )
    return out


def _has_consumed_exterior_wall_ops(fir: FloorIR) -> bool:
    """Return True if the IR has any in-scope ExteriorWallOp entries.

    In-scope set is ``_EXTERIOR_WALL_IN_SCOPE`` (DungeonInk added in
    Phase 1.16b-3; CaveInk added in Phase 1.15b).
    Used by the legacy EnclosureOp and BuildingExteriorWallOp handlers
    to suppress themselves when the new handler is active.
    """
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() == Op.Op.ExteriorWallOp:
            op = OpCreator(Op.Op.ExteriorWallOp, entry.Op())
            if op is not None and int(op.style) in _EXTERIOR_WALL_IN_SCOPE:
                return True
    return False


def _has_consumed_interior_wall_ops(fir: FloorIR) -> bool:
    """Return True if the IR has any in-scope InteriorWallOp entries.

    Used by the legacy BuildingInteriorWallOp handler to suppress
    itself when the new handler is active.
    """
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() == Op.Op.InteriorWallOp:
            op = OpCreator(Op.Op.InteriorWallOp, entry.Op())
            if op is not None and int(op.style) in _INTERIOR_WALL_IN_SCOPE:
                return True
    return False


_OP_HANDLERS[Op.Op.ExteriorWallOp] = _draw_exterior_wall_op_from_ir
_OP_HANDLERS[Op.Op.InteriorWallOp] = _draw_interior_wall_op_from_ir


# ── DungeonInk consumer helpers (Phase 1.16b-3) ─────────────────
#
# Three helpers derive wall geometry from structured IR ops rather
# than the legacy WallsAndFloorsOp wall_segments / smooth_walls /
# wall_extensions_d fields.
#
# _walkable_tiles_from_ir(fir) — union of all FloorOp tile coords
# _building_footprint_tiles(fir) — Building region tiles (for
#     the _draw_wall_to filter on corridor tiles)
# _smooth_corridor_stubs(fir) — wall-extension paths from None_
#     cuts on smooth DungeonInk ExteriorWallOps (mirrors legacy
#     _outline_with_gaps extension geometry)
#
# Consumer:
# _draw_corridor_wall_op_from_ir — tile-edge walk for corridor walls
# _draw_exterior_wall_op_from_ir updated — DungeonInk now active
#
# Suppression:
# _has_consumed_dungeon_exterior_wall_ops(fir) — True when all
#     DungeonInk ExteriorWallOps are consumed (CorridorWallOp also
#     present). Used by _draw_walls_and_floors_from_ir to suppress
#     wall_segments / smooth_walls / wall_extensions_d.


def _walkable_tiles_from_ir(
    fir: FloorIR,
) -> set[tuple[int, int]]:
    """Return the set of walkable tile coords covered by FloorOps.

    Scans all FloorOp entries in ``fir.ops[]``, rasterizes each
    Polygon outline to integer tile coords, and returns their union.

    For each Polygon FloorOp:
    - 4-vertex axis-aligned bbox (rect room tile or corridor tile):
      enumerate all (x, y) from ``(x0/CELL, y0/CELL)`` to
      ``((x1/CELL)-1, (y1/CELL)-1)`` inclusive.
    - Other polygon (smooth / cave multi-vertex): Shapely
      point-in-polygon test against tile centres
      ``(x*CELL + CELL/2, y*CELL + CELL/2)``.

    Circle / Pill descriptors are handled via Shapely buffering.
    Tiles with x < 0 or y < 0 are excluded (out-of-bounds guard).

    Phase 1.26e-1 — region-keyed dispatch: when ``op.region_ref`` is
    non-empty AND resolves to a Region with a populated outline, the
    geometry comes from ``region.outline`` instead of ``op.outline``.
    Mirrors the FloorOp.region_ref dispatch from 1.23a. The
    ``op.outline`` fallback covers building wood-floor per-tile
    FloorOps (no per-tile Region) and 3.x cached buffers without
    region_ref.
    """
    from nhc.rendering.ir._fb import FloorStyle as FloorStyleMod
    from nhc.rendering.ir._fb import OutlineKind as OutlineKindMod
    from nhc.rendering.ir._fb.Outline import OutlineT

    FS = FloorStyleMod.FloorStyle
    OK = OutlineKindMod.OutlineKind

    width = fir.WidthTiles()
    height = fir.HeightTiles()
    result: set[tuple[int, int]] = set()

    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.FloorOp:
            continue
        op = OpCreator(entry.OpType(), entry.Op())
        if op is None:
            continue
        # Only DungeonFloor and CaveFloor are walkable for wall
        # derivation purposes.
        if op.style not in (FS.DungeonFloor, FS.CaveFloor):
            continue
        outline = op.outline
        region_ref = op.regionRef or b""
        if region_ref:
            region = _find_region(fir, region_ref)
            if region is not None:
                region_outline_fb = region.Outline()
                if region_outline_fb is not None:
                    outline = OutlineT.InitFromObj(region_outline_fb)
        if outline is None:
            continue

        kind = outline.descriptorKind

        if kind == OK.Polygon:
            verts = outline.vertices
            if not verts:
                continue
            coords = [(float(v.x), float(v.y)) for v in verts]
            # Phase 1.26d-3 — multi-ring outlines (merged corridor
            # FloorOp's disjoint connected components, plus interior
            # holes for annular components that wrap a room) require
            # ring-aware iteration. Group rings by exterior + holes:
            # consecutive ``is_hole=True`` rings belong to the most
            # recent exterior. Build one Shapely polygon per exterior
            # group (with its holes) so the containment test correctly
            # excludes hole regions. Single-ring outlines take the
            # v4e shorthand (rings = []) and walk the full vertex list
            # as one exterior with no holes.
            rings = outline.rings or []
            if rings:
                groups: list[
                    tuple[list[tuple[float, float]],
                          list[list[tuple[float, float]]]]
                ] = []
                for r in rings:
                    start = int(r.start)
                    count = int(r.count)
                    if count < 2:
                        continue
                    ring_coords = coords[start:start + count]
                    if not r.isHole:
                        groups.append((ring_coords, []))
                    elif groups:
                        groups[-1][1].append(ring_coords)
                    # Orphan hole (no preceding exterior): skip.
            else:
                groups = [(coords, [])]

            for ext_coords, hole_rings in groups:
                n = len(ext_coords)
                if n < 2:
                    continue

                if n == 4 and not hole_rings:
                    # Axis-aligned bbox with no holes: derive directly.
                    xs = [c[0] for c in ext_coords]
                    ys = [c[1] for c in ext_coords]
                    x0 = int(min(xs))
                    y0 = int(min(ys))
                    x1 = int(max(xs))
                    y1 = int(max(ys))
                    tx0 = x0 // CELL
                    ty0 = y0 // CELL
                    tx1 = x1 // CELL
                    ty1 = y1 // CELL
                    for ty in range(ty0, ty1):
                        for tx in range(tx0, tx1):
                            if 0 <= tx < width and 0 <= ty < height:
                                result.add((tx, ty))
                else:
                    # Non-rectangular or with holes: Shapely containment.
                    from shapely.geometry import Point, Polygon as ShPoly
                    poly_sh = ShPoly(ext_coords, holes=hole_rings)
                    if poly_sh.is_empty or not poly_sh.is_valid:
                        continue
                    bx0, by0, bx1, by1 = poly_sh.bounds
                    tx0 = max(0, int(bx0 // CELL))
                    ty0 = max(0, int(by0 // CELL))
                    tx1 = min(width, int(bx1 // CELL) + 1)
                    ty1 = min(height, int(by1 // CELL) + 1)
                    for ty in range(ty0, ty1):
                        for tx in range(tx0, tx1):
                            cx = tx * CELL + CELL / 2
                            cy = ty * CELL + CELL / 2
                            if poly_sh.contains(Point(cx, cy)):
                                result.add((tx, ty))

        elif kind == OK.Circle:
            from shapely.geometry import Point, Polygon as ShPoly
            px = outline.cx
            py_c = outline.cy
            r = outline.rx
            if r <= 0:
                continue
            circ = Point(px, py_c).buffer(r, resolution=32)
            bx0, by0, bx1, by1 = circ.bounds
            tx0 = max(0, int(bx0 // CELL))
            ty0 = max(0, int(by0 // CELL))
            tx1 = min(width, int(bx1 // CELL) + 1)
            ty1 = min(height, int(by1 // CELL) + 1)
            for ty in range(ty0, ty1):
                for tx in range(tx0, tx1):
                    cx_c = tx * CELL + CELL / 2
                    cy_c = ty * CELL + CELL / 2
                    if circ.contains(Point(cx_c, cy_c)):
                        result.add((tx, ty))

        elif kind == OK.Pill:
            from shapely.geometry import Point
            from shapely.geometry import box as ShBox
            rx = outline.rx
            ry = outline.ry
            if rx <= 0 or ry <= 0:
                continue
            # Pill is a rounded rect; Shapely approximation via buffer.
            from shapely.geometry import Polygon as ShPoly
            cx2 = outline.cx
            cy2 = outline.cy
            rounding = min(rx, ry)
            pill = ShBox(
                cx2 - rx, cy2 - ry, cx2 + rx, cy2 + ry,
            ).buffer(0).simplify(1)
            # Use exact containment on the bounding box.
            bx0, by0, bx1, by1 = cx2 - rx, cy2 - ry, cx2 + rx, cy2 + ry
            tx0 = max(0, int(bx0 // CELL))
            ty0 = max(0, int(by0 // CELL))
            tx1 = min(width, int(bx1 // CELL) + 1)
            ty1 = min(height, int(by1 // CELL) + 1)
            for ty in range(ty0, ty1):
                for tx in range(tx0, tx1):
                    cx_p = tx * CELL + CELL / 2
                    cy_p = ty * CELL + CELL / 2
                    if (cx2 - rx <= cx_p <= cx2 + rx and
                            cy2 - ry <= cy_p <= cy2 + ry):
                        result.add((tx, ty))

    return result


def _building_footprint_tiles(
    fir: FloorIR,
) -> set[tuple[int, int]] | None:
    """Return tile coords covered by Building regions, or None if none.

    Scans ``fir.regions[]`` for entries with ``kind == Building``.
    For each, runs a Shapely polygon-contains test against tile
    centres. Returns the union of all building tile sets, or ``None``
    when no Building regions are present (indicating that the
    ``_draw_wall_to`` filter should not apply).
    """
    from nhc.rendering.ir._fb import RegionKind as RegionKindMod

    RK = RegionKindMod.RegionKind
    width = fir.WidthTiles()
    height = fir.HeightTiles()
    found_any = False
    result: set[tuple[int, int]] = set()

    for j in range(fir.RegionsLength()):
        region = fir.Regions(j)
        if region.Kind() != RK.Building:
            continue
        found_any = True
        # Phase 1.26g — read footprint vertices from Region.outline.
        outline_fb = region.Outline()
        if outline_fb is None:
            continue
        coords = _outline_vertices_to_coords(outline_fb)
        if len(coords) < 3:
            continue
        from shapely.geometry import Point, Polygon as ShPoly
        poly_sh = ShPoly(coords)
        if poly_sh.is_empty or not poly_sh.is_valid:
            continue
        bx0, by0, bx1, by1 = poly_sh.bounds
        tx0 = max(0, int(bx0 // CELL))
        ty0 = max(0, int(by0 // CELL))
        tx1 = min(width, int(bx1 // CELL) + 1)
        ty1 = min(height, int(by1 // CELL) + 1)
        for ty in range(ty0, ty1):
            for tx in range(tx0, tx1):
                cx = tx * CELL + CELL / 2
                cy = ty * CELL + CELL / 2
                if poly_sh.contains(Point(cx, cy)):
                    result.add((tx, ty))

    return result if found_any else None


def _smooth_corridor_stubs(
    fir: FloorIR,
    corridor_tiles: set[tuple[int, int]] | None = None,
    walkable: set[tuple[int, int]] | None = None,
) -> list[str]:
    """Derive wall-extension stubs from None_ cuts on smooth ExteriorWallOps.

    For each DungeonInk ExteriorWallOp that has CutStyle.None_ cuts
    (doorless corridor openings on smooth rooms — octagon, circle, etc.),
    emit two wall-extension path fragments per cut. Each fragment
    extends from one cut endpoint perpendicular outward into the
    adjacent corridor tile by one CELL, mirroring the legacy
    ``_outline_with_gaps`` extension geometry stored in
    ``WallsAndFloorsOp.wallExtensionsD``.

    Cut endpoints are the hit_a / hit_b points where the corridor's
    two side walls intersect the room outline. The extension direction
    is determined by comparing the cut's midpoint to the polygon
    centroid:
    - Horizontal cut (N/S corridor): ``mid_y < centroid_y`` → North
      (far_y = cut_y - CELL); else South (far_y = cut_y + CELL).
    - Vertical cut (E/W corridor): ``mid_x < centroid_x`` → West
      (far_x = cut_x - CELL); else East (far_x = cut_x + CELL).

    Extension format: ``M{sx:.1f},{sy:.1f} L{tx:.1f},{ty:.1f}``
    matching the ``.1f`` precision of ``_intersect_outline``.

    Deduplication: a stub at (px, py)→(px±CELL, py) or (px, py)→(px,
    py±CELL) is skipped when the corresponding corridor tile's void-
    facing edge is already covered by ``_draw_corridor_wall_op_from_ir``.
    This prevents double-painting at the junction between the last
    corridor tile and the smooth room boundary.

    ``corridor_tiles`` and ``walkable`` are pre-computed sets passed by
    ``_draw_walls_and_floors_from_ir`` to avoid redundant traversal.
    When None, they are derived from ``fir`` internally.

    Returns an empty list for IRs with no smooth None_ cuts (e.g.
    rect-only dungeon floors like seed42).
    """
    import math as _math

    from nhc.rendering.ir._fb.CutStyle import CutStyle as CS
    from nhc.rendering.ir._fb.WallStyle import WallStyle as WS

    if corridor_tiles is None or walkable is None:
        # Derive corridor tiles from CorridorWallOp.
        corridor_tiles_local: set[tuple[int, int]] = set()
        for i in range(fir.OpsLength()):
            entry = fir.Ops(i)
            if entry.OpType() == Op.Op.CorridorWallOp:
                cwop = OpCreator(entry.OpType(), entry.Op())
                if cwop and cwop.tiles:
                    for t in cwop.tiles:
                        corridor_tiles_local.add((int(t.x), int(t.y)))
                break
        corridor_tiles = corridor_tiles_local
        walkable = _walkable_tiles_from_ir(fir)

    def _stub_covered_by_corridor(
        stub_x0: float, stub_y0: float, stub_x1: float, stub_y1: float,
    ) -> bool:
        """Return True if CorridorWallOp already emits this stub segment.

        The stub covers one tile-edge (horizontal or vertical, length
        CELL). It is covered when the adjacent corridor tile would emit
        the same edge facing into void.
        """
        # Horizontal stub: y0 == y1.
        if abs(stub_y0 - stub_y1) < 1e-3:
            y_edge = stub_y0
            x_lo = min(stub_x0, stub_x1)
            # The tile below this edge starts at (x_lo/CELL, y_edge/CELL).
            tx = round(x_lo / CELL)
            ty = round(y_edge / CELL)
            # This edge is the TOP of tile (tx, ty).
            # CorridorWallOp emits it when (tx, ty-1) not in walkable.
            return (tx, ty) in corridor_tiles and (tx, ty - 1) not in walkable
        # Vertical stub: x0 == x1.
        if abs(stub_x0 - stub_x1) < 1e-3:
            x_edge = stub_x0
            y_lo = min(stub_y0, stub_y1)
            # The tile to the right of this edge starts at (x_edge/CELL, y_lo/CELL).
            tx = round(x_edge / CELL)
            ty = round(y_lo / CELL)
            # This edge is the LEFT side of tile (tx, ty).
            # CorridorWallOp emits it when (tx-1, ty) not in walkable.
            return (tx, ty) in corridor_tiles and (tx - 1, ty) not in walkable
        return False

    result: list[str] = []

    from nhc.rendering.ir._fb.Outline import OutlineT

    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.ExteriorWallOp:
            continue
        op = OpCreator(Op.Op.ExteriorWallOp, entry.Op())
        if op is None:
            continue
        if int(op.style) != WS.DungeonInk:
            continue
        # Phase 1.26e-1 — region-keyed dispatch + op-level cuts. When
        # ``op.region_ref`` is non-empty AND resolves to a Region with
        # a populated outline, the geometry comes from
        # ``region.outline``. When ``op.cuts`` is populated, it
        # supersedes the legacy ``outline.cuts`` for stroke break
        # intervals. Mirrors the dispatch in
        # ``_draw_exterior_wall_op_from_ir``.
        outline = op.outline
        region_ref = op.regionRef or b""
        if region_ref:
            region = _find_region(fir, region_ref)
            if region is not None:
                region_outline_fb = region.Outline()
                if region_outline_fb is not None:
                    outline = OutlineT.InitFromObj(region_outline_fb)
        if outline is None:
            continue
        verts = outline.vertices
        if not verts or len(verts) < 3:
            continue
        op_cuts = list(op.cuts or [])
        cuts = op_cuts if op_cuts else list(outline.cuts or [])
        if not cuts:
            continue

        coords = [(float(v.x), float(v.y)) for v in verts]

        # Only emit extensions for None_ cuts (doorless openings).
        none_cuts = [c for c in cuts if int(c.style) == CS.None_]
        if not none_cuts:
            continue

        # Centroid of the polygon to determine corridor direction.
        centroid_x = sum(x for x, _ in coords) / len(coords)
        centroid_y = sum(y for _, y in coords) / len(coords)

        for cut in none_cuts:
            sx = float(cut.start.x)
            sy = float(cut.start.y)
            ex = float(cut.end.x)
            ey = float(cut.end.y)
            mid_x = (sx + ex) / 2.0
            mid_y = (sy + ey) / 2.0

            if abs(sx - ex) < 1e-3:
                # Vertical cut → E/W corridor.
                # Both endpoints share the same x; corridor is East/West.
                if mid_x < centroid_x:
                    far_x = sx - CELL   # West
                else:
                    far_x = sx + CELL   # East
                if not _stub_covered_by_corridor(sx, sy, far_x, sy):
                    result.append(
                        f'M{sx:.1f},{sy:.1f} L{far_x:.1f},{sy:.1f}'
                    )
                if not _stub_covered_by_corridor(ex, ey, far_x, ey):
                    result.append(
                        f'M{ex:.1f},{ey:.1f} L{far_x:.1f},{ey:.1f}'
                    )
            else:
                # Horizontal cut → N/S corridor.
                if mid_y < centroid_y:
                    far_y = sy - CELL   # North
                else:
                    far_y = sy + CELL   # South
                if not _stub_covered_by_corridor(sx, sy, sx, far_y):
                    result.append(
                        f'M{sx:.1f},{sy:.1f} L{sx:.1f},{far_y:.1f}'
                    )
                if not _stub_covered_by_corridor(ex, ey, ex, far_y):
                    result.append(
                        f'M{ex:.1f},{ey:.1f} L{ex:.1f},{far_y:.1f}'
                    )

    return result


def _walk_polygon_with_cuts(
    polygon: list[tuple[float, float]],
    cuts: list[Any],
) -> str:
    """Walk a closed polygon, breaking the stroke at cut intervals.

    Returns a ``d=`` string (M/L/M/L...) suitable for a ``<path>``
    element. Edges with cuts are split: the uncut sub-segments are
    emitted as ``M{x:.1f},{y:.1f} L{x:.1f},{y:.1f}`` moves; the cut
    intervals are silently skipped (creating the gap in the stroke).

    Coordinates use ``.1f`` precision to match the legacy smooth-wall
    format (``_intersect_outline`` returns floats).
    """
    import math as _math

    n = len(polygon)
    if n < 2:
        return ""

    d_parts: list[str] = []
    # Track whether we're in an active stroke run.
    in_stroke = False
    current_x = 0.0
    current_y = 0.0

    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        dx = bx - ax
        dy = by - ay
        edge_len = _math.hypot(dx, dy)
        if edge_len < 1e-6:
            continue

        edge_cuts = _cuts_for_edge(ax, ay, bx, by, cuts)
        # Sort by start t, merge overlapping intervals.
        edge_cuts.sort(key=lambda c: c[0])
        merged: list[tuple[float, float]] = []
        for lo, hi in edge_cuts:
            if merged and lo <= merged[-1][1] + 1e-6:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))

        # Walk from t=0 to t=1, skipping cut intervals.
        t = 0.0
        for lo_t, hi_t in merged:
            if lo_t > t + 1e-6:
                # Emit segment from t to lo_t.
                x0 = ax + t * dx
                y0 = ay + t * dy
                x1 = ax + lo_t * dx
                y1 = ay + lo_t * dy
                if (not in_stroke or
                        abs(x0 - current_x) > 1e-4 or
                        abs(y0 - current_y) > 1e-4):
                    d_parts.append(f'M{x0:.1f},{y0:.1f}')
                d_parts.append(f'L{x1:.1f},{y1:.1f}')
                current_x, current_y = x1, y1
                in_stroke = True
            # Skip from lo_t to hi_t.
            t = hi_t
            in_stroke = False

        # Emit remaining segment from t to 1.0.
        if t < 1.0 - 1e-6:
            x0 = ax + t * dx
            y0 = ay + t * dy
            x1 = bx
            y1 = by
            if (not in_stroke or
                    abs(x0 - current_x) > 1e-4 or
                    abs(y0 - current_y) > 1e-4):
                d_parts.append(f'M{x0:.1f},{y0:.1f}')
            d_parts.append(f'L{x1:.1f},{y1:.1f}')
            current_x, current_y = x1, y1
            in_stroke = True
        else:
            in_stroke = False

    return " ".join(d_parts)


def _draw_corridor_wall_op_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 1.16b-3: derive corridor wall edges from CorridorWallOp.

    For each corridor tile in ``op.tiles``, checks its 4 cardinal
    neighbours against the walkable tile set (``_walkable_tiles_from_ir``).
    Emits a wall stroke for each non-walkable neighbour — i.e. each
    tile edge that borders void space.

    Building-footprint filter (``_building_footprint_tiles``): when
    ``building_tiles`` is not None and the corridor tile is inside
    the building footprint, the wall edge to a non-walkable neighbour
    is only emitted when the neighbour is also inside the building
    footprint. This mirrors the legacy ``_draw_wall_to(neighbor)``
    predicate from ``_floor_layers.py``.

    All wall segments are collected into a single ``<path>`` element
    with the standard DungeonInk stroke style:
    ``fill="none" stroke="{INK}" stroke-width="{WALL_WIDTH}"
    stroke-linecap="round" stroke-linejoin="round"``.

    Guard: only emits when ``_has_consumed_dungeon_exterior_wall_ops``
    is True (i.e. the floor has CorridorWallOp + DungeonInk
    ExteriorWallOps). When the DungeonInk consumer is NOT active
    (e.g. a site IR whose only ExteriorWallOp is MasonryBrick),
    the legacy ``wall_segments`` in ``WallsAndFloorsOp`` still cover
    corridor walls and this handler must not double-paint them.
    """
    # Only emit when the DungeonInk consumer is fully active.
    if not _has_consumed_dungeon_exterior_wall_ops(fir):
        return []

    op = OpCreator(entry.OpType(), entry.Op())
    if op is None:
        return []
    tiles_list = op.tiles
    if not tiles_list:
        return []

    walkable = _walkable_tiles_from_ir(fir)
    building_tiles = _building_footprint_tiles(fir)

    segments: list[str] = []

    for tile in tiles_list:
        tx = int(tile.x)
        ty = int(tile.y)
        px = tx * CELL
        py = ty * CELL

        in_building = (
            building_tiles is not None
            and (tx, ty) in building_tiles
        )

        # (neighbor_x, neighbor_y, SVG segment string)
        neighbors: list[tuple[int, int, str]] = [
            (tx, ty - 1, f'M{px},{py} L{px + CELL},{py}'),
            (tx, ty + 1, f'M{px},{py + CELL} L{px + CELL},{py + CELL}'),
            (tx - 1, ty, f'M{px},{py} L{px},{py + CELL}'),
            (tx + 1, ty, f'M{px + CELL},{py} L{px + CELL},{py + CELL}'),
        ]

        for nx, ny, seg in neighbors:
            if (nx, ny) in walkable:
                # Walkable neighbour — no wall on this edge.
                continue
            # Apply building-footprint filter.
            if in_building:
                if building_tiles is not None and (nx, ny) not in building_tiles:
                    continue
            segments.append(seg)

    out: list[str] = []
    if segments:
        joined = " ".join(segments)
        out.append(
            f'<path d="{joined}" fill="none" stroke="{INK}" '
            f'stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    # Phase 1.26f — smooth-corridor stubs (extension fragments derived
    # from None_ cuts on smooth DungeonInk ExteriorWallOps) emit here
    # in CorridorWallOp's slot. Pre-1.26f, the WallsAndFloorsOp
    # dispatcher batched the stubs after its corridor-edge segments;
    # keeping that ordering here preserves the resvg paint sequence.
    stubs = _smooth_corridor_stubs(fir)
    if stubs:
        joined_stubs = " ".join(stubs)
        out.append(
            f'<path d="{joined_stubs}" fill="none" stroke="{INK}" '
            f'stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    return out


def _has_consumed_dungeon_exterior_wall_ops(fir: FloorIR) -> bool:
    """Return True if all DungeonInk ExteriorWallOps are consumed.

    Requires both a CorridorWallOp (to cover corridor tile edges) AND
    at least one DungeonInk ExteriorWallOp (to cover room perimeters).
    When both are present, the consumer owns all dungeon wall output
    and the legacy WallsAndFloorsOp fields should be suppressed.

    Returns False for IRs with no CorridorWallOp (3.x cached buffers).
    """
    has_corridor_wall_op = False
    has_dungeon_ink_ext_wall_op = False
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() == Op.Op.CorridorWallOp:
            has_corridor_wall_op = True
        elif entry.OpType() == Op.Op.ExteriorWallOp:
            op = OpCreator(Op.Op.ExteriorWallOp, entry.Op())
            if op is not None and int(op.style) == 0:  # DungeonInk = 0
                has_dungeon_ink_ext_wall_op = True
    return has_corridor_wall_op and has_dungeon_ink_ext_wall_op


_OP_HANDLERS[Op.Op.CorridorWallOp] = _draw_corridor_wall_op_from_ir
