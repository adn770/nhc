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

import math
import random
import re

from typing import Any, Callable

from shapely.geometry import (
    LineString, MultiPolygon, Point, Polygon as ShapelyPolygon,
)

from nhc.rendering import _perlin as _noise
from nhc.rendering._cave_geometry import _smooth_closed_path
from nhc.rendering._dungeon_polygon import (
    _build_sections, _pick_section_points,
)
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
    "walls_and_floors",
    "terrain_tints",
    "floor_grid",
    "floor_detail",
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
    "walls_and_floors": frozenset({Op.Op.WallsAndFloorsOp}),
    "terrain_tints": frozenset({Op.Op.TerrainTintOp}),
    "floor_grid": frozenset({Op.Op.FloorGridOp}),
    "floor_detail": frozenset({Op.Op.FloorDetailOp}),
    "terrain_detail": frozenset({Op.Op.TerrainDetailOp}),
    "stairs": frozenset({Op.Op.StairsOp}),
    "surface_features": frozenset({
        Op.Op.WellFeatureOp,
        Op.Op.FountainFeatureOp,
        Op.Op.TreeFeatureOp,
        Op.Op.BushFeatureOp,
        # Phase 1 transitional — _emit_surface_features_ir
        # produces a single GenericProceduralOp(name="surface_features")
        # that carries the layer's pre-rendered groups. The four
        # dedicated ops above stay schema-reserved for Phase 4's
        # structured port.
        Op.Op.GenericProceduralOp,
    }),
}


_BARE_SKIP_LAYERS: frozenset[str] = frozenset({
    "floor_detail",
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


def _root_or_raise(buf: bytes) -> FloorIR:
    if not FloorIR.FloorIRBufferHasIdentifier(buf, 0):
        raise ValueError(
            "Buffer does not carry the NIRF file_identifier — is "
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

    The schema's ``dx`` / ``dy`` / ``opacity`` defaults
    (3.0 / 3.0 / 0.08) match the legacy hard-coded constants — the
    handler ignores the FB fields and uses literals instead, both
    to dodge the float32 round-trip on 0.08 (which would surface as
    "0.07999999821186066") and to keep integer formatting where the
    legacy renderer's int arithmetic produced integers.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    kind = op.kind
    if kind == ShadowKind.ShadowKind.Corridor:
        out: list[str] = []
        for tile in op.tiles:
            px = tile.x * CELL + 3
            py = tile.y * CELL + 3
            out.append(
                f'<rect x="{px}" y="{py}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{INK}" opacity="0.08"/>'
            )
        return out
    if kind == ShadowKind.ShadowKind.Room:
        return [_draw_room_shadow(op, fir)]
    raise ValueError(f"unknown ShadowKind: {kind}")


def _draw_room_shadow(op: Any, fir: FloorIR) -> str:  # type: ignore[name-defined]
    """Reproduce ``_shadows._room_shadow_svg`` from the IR.

    Dispatches on the referenced region's ``shape_tag`` so the
    output matches the legacy element form for each supported
    shape: rect / octagon / cave (plus the cave→rect fallback that
    :func:`nhc.rendering.ir_emitter._room_region_data` collapses
    into ``shape_tag == "rect"``).
    """
    region = _find_region(fir, op.regionRef)
    if region is None:
        raise ValueError(
            f"ShadowOp(Room) references unknown region "
            f"{op.regionRef!r}; emit_regions must register one"
        )
    shape_tag = region.ShapeTag()
    coords = _polygon_paths_to_coords(region.Polygon())

    if shape_tag == b"rect":
        # Rect form bakes the +3 offset into x / y. Coords are
        # integer-valued (CELL × tile-int) so int() formats cleanly.
        xs = [int(x) for x, _ in coords]
        ys = [int(y) for _, y in coords]
        px, py = min(xs) + 3, min(ys) + 3
        pw = max(xs) - min(xs)
        ph = max(ys) - min(ys)
        return (
            f'<rect x="{px}" y="{py}" '
            f'width="{pw}" height="{ph}" '
            f'fill="{INK}" opacity="0.08"/>'
        )

    if shape_tag == b"octagon":
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        outline = f'<polygon points="{points}"/>'
        return _wrap_outline(outline)

    if shape_tag == b"cave":
        outline = _smooth_closed_path(coords)
        return _wrap_outline(outline)

    raise NotImplementedError(
        f"Room shadow handler for shape_tag {shape_tag!r} not "
        "implemented; the starter fixtures only exercise rect / "
        "octagon / cave"
    )


def _wrap_outline(outline: str) -> str:
    """Mirror ``_shadows._room_shadow_svg`` wrap: inject fill +
    opacity on the outline element, then translate by (3, 3)."""
    el = outline.replace("/>", f' fill="{INK}" opacity="0.08"/>')
    return f'<g transform="translate(3,3)">{el}</g>'


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


def _polygon_paths_to_coords(polygon: Any) -> list[tuple[float, float]]:
    """Flatten a single-ring FB Polygon into an (x, y) coord list.

    The single-ring assumption matches every region the room shadow
    handler resolves: ``_room_region_data`` builds rect / octagon /
    cave polygons via ``_coords_to_polygon`` which always emits one
    exterior ring with no holes. If a future commit registers
    multi-ring room regions, this helper will need a rings-aware
    counterpart.
    """
    return [
        (polygon.Paths(i).X(), polygon.Paths(i).Y())
        for i in range(polygon.PathsLength())
    ]


_OP_HANDLERS[Op.Op.ShadowOp] = _draw_shadow_from_ir


def _draw_hatch_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Reproduce ``_render_hatching`` / ``_render_corridor_hatching``.

    1.c.1 ships the Corridor branch — replays the per-tile RNG and
    Perlin sequence in ``design/ir_primitives.md`` §7.2 order, with
    the tile list pre-sorted by the emitter so
    ``random.Random(op.seed)`` walks each tile's stones, section
    partitioning, and stroke wobble in the legacy order. The Room
    branch lands in 1.c.2.
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
    """Per-tile fill / stones / Perlin-anchored hatch lines.

    Mirrors ``_render_corridor_hatching`` line-for-line but drives
    the iteration off ``op.tiles`` (pre-sorted by the emitter)
    instead of recomputing the tile set. The three output groups
    (fill, lines, stones) are returned as separate strings so the
    layer-level ``\\n`` join matches the legacy ``svg.append`` pattern.
    """
    rng = random.Random(op.seed)
    min_stroke = 1.0
    max_stroke = 1.8
    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for tile in op.tiles:
        gx, gy = tile.x, tile.y
        tile_fills.append(
            f'<rect x="{gx * CELL}" y="{gy * CELL}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{HATCH_UNDERLAY}"/>'
        )

        n_stones = rng.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
        for _ in range(n_stones):
            sx = (gx + rng.uniform(0.15, 0.85)) * CELL
            sy = (gy + rng.uniform(0.15, 0.85)) * CELL
            rx = rng.uniform(2, CELL * 0.25)
            ry = rng.uniform(2, CELL * 0.2)
            angle = rng.uniform(0, 180)
            sw = rng.uniform(1.2, 2.0)
            hatch_stones.append(
                f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                f'rx="{rx:.1f}" ry="{ry:.1f}" '
                f'transform="rotate({angle:.0f},'
                f'{sx:.1f},{sy:.1f})" '
                f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                f'stroke-width="{sw:.1f}"/>'
            )

        nr = CELL * 0.1
        adx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
        ady = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
        anchor = (
            (gx + 0.5) * CELL + adx,
            (gy + 0.5) * CELL + ady,
        )
        corners = [
            (gx * CELL, gy * CELL),
            ((gx + 1) * CELL, gy * CELL),
            ((gx + 1) * CELL, (gy + 1) * CELL),
            (gx * CELL, (gy + 1) * CELL),
        ]
        pts = _pick_section_points(corners, anchor, CELL, rng)
        sections = _build_sections(anchor, pts, corners)

        for i, section in enumerate(sections):
            if section.is_empty or section.area < 1:
                continue
            if i == 0:
                seg_angle = math.atan2(
                    pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]
                )
            else:
                seg_angle = rng.uniform(0, math.pi)

            bounds = section.bounds
            diag = math.hypot(
                bounds[2] - bounds[0], bounds[3] - bounds[1]
            )
            spacing = CELL * 0.20
            n_lines = max(3, int(diag / spacing))

            for j in range(n_lines):
                offset = (j - (n_lines - 1) / 2) * spacing
                scx = section.centroid.x
                scy = section.centroid.y
                perp_x = math.cos(seg_angle + math.pi / 2) * offset
                perp_y = math.sin(seg_angle + math.pi / 2) * offset
                line = LineString([
                    (
                        scx + perp_x - math.cos(seg_angle) * diag,
                        scy + perp_y - math.sin(seg_angle) * diag,
                    ),
                    (
                        scx + perp_x + math.cos(seg_angle) * diag,
                        scy + perp_y + math.sin(seg_angle) * diag,
                    ),
                ])
                clipped = section.intersection(line)
                if (
                    clipped.is_empty
                    or not isinstance(clipped, LineString)
                ):
                    continue
                p1, p2 = list(clipped.coords)
                wb = CELL * 0.03
                p1 = (
                    p1[0] + _noise.pnoise2(
                        p1[0] * 0.1, p1[1] * 0.1, base=10) * wb,
                    p1[1] + _noise.pnoise2(
                        p1[0] * 0.1, p1[1] * 0.1, base=11) * wb,
                )
                p2 = (
                    p2[0] + _noise.pnoise2(
                        p2[0] * 0.1, p2[1] * 0.1, base=12) * wb,
                    p2[1] + _noise.pnoise2(
                        p2[0] * 0.1, p2[1] * 0.1, base=13) * wb,
                )
                lsw = rng.uniform(min_stroke, max_stroke)
                hatch_lines.append(
                    f'<line x1="{p1[0]:.1f}" '
                    f'y1="{p1[1]:.1f}" '
                    f'x2="{p2[0]:.1f}" '
                    f'y2="{p2[1]:.1f}" '
                    f'stroke="{INK}" '
                    f'stroke-width="{lsw:.2f}" '
                    f'stroke-linecap="round"/>'
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
    """Reproduce ``_render_hatching`` (perimeter halo).

    The legacy iteration interleaves a 10% RNG-driven skip with
    rendering, so the rng stream can't be split between emit and
    handler — the entire walk lives here. The IR provides the
    floor-tile set (``op.tiles``), the dungeon polygon (region
    ``op.regionOut``), and ``op.extentTiles`` (= ``hatch_distance``).
    Cave mode is detected by the presence of a ``cave`` foundation
    region (``ctx.cave_wall_poly is not None`` in the legacy).
    """
    region = _find_region(fir, op.regionOut)
    if region is None:
        # Legacy short-circuits when dungeon_poly is empty — emitter
        # also skips the op then, so an unresolved region_out here
        # means the IR was hand-crafted; bail to match.
        return []

    dungeon_poly = _fb_polygon_to_shapely(region.Polygon())
    if dungeon_poly is None or dungeon_poly.is_empty:
        return []

    floor_set = {(t.x, t.y) for t in op.tiles}
    base_distance_limit = op.extentTiles * CELL
    cave_mode = _find_region(fir, b"cave") is not None
    width = fir.WidthTiles()
    height = fir.HeightTiles()

    rng = random.Random(op.seed)
    min_stroke = 1.0
    max_stroke = 1.8
    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    boundary = dungeon_poly.boundary

    for gy in range(-1, height + 1):
        for gx in range(-1, width + 1):
            if (gx, gy) in floor_set:
                continue

            # 5x5 floor neighborhood; fall back to polygon distance.
            min_dist = float("inf")
            for ddx in range(-2, 3):
                for ddy in range(-2, 3):
                    if (gx + ddx, gy + ddy) in floor_set:
                        d = math.hypot(ddx, ddy) * CELL
                        if d < min_dist:
                            min_dist = d
            if min_dist == float("inf"):
                center = Point(
                    (gx + 0.5) * CELL, (gy + 0.5) * CELL,
                )
                min_dist = boundary.distance(center)
            dist = min_dist

            # Caves use a fixed limit; dungeons modulate via Perlin.
            if not cave_mode:
                noise_var = (
                    _noise.pnoise2(gx * 0.3, gy * 0.3, base=50)
                    * CELL * 0.8
                )
                tile_limit = base_distance_limit + noise_var
            else:
                tile_limit = base_distance_limit
            if dist > tile_limit:
                continue

            # 10% RNG-driven discontinuity. The rng.random() call
            # only fires when the conditions match — keep this
            # branch identical to legacy so the stream advances in
            # lock-step.
            if (
                not cave_mode
                and dist > base_distance_limit * 0.5
                and rng.random() < 0.10
            ):
                continue

            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>'
            )

            n_stones = rng.choices(
                [0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15]
            )[0]
            for _ in range(n_stones):
                sx = (gx + rng.uniform(0.15, 0.85)) * CELL
                sy = (gy + rng.uniform(0.15, 0.85)) * CELL
                rx = rng.uniform(2, CELL * 0.25)
                ry = rng.uniform(2, CELL * 0.2)
                angle = rng.uniform(0, 180)
                sw = rng.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},'
                    f'{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                    f'stroke-width="{sw:.1f}"/>'
                )

            nr = CELL * 0.1
            adx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
            ady = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
            anchor = (
                (gx + 0.5) * CELL + adx,
                (gy + 0.5) * CELL + ady,
            )
            corners = [
                (gx * CELL, gy * CELL),
                ((gx + 1) * CELL, gy * CELL),
                ((gx + 1) * CELL, (gy + 1) * CELL),
                (gx * CELL, (gy + 1) * CELL),
            ]
            pts = _pick_section_points(corners, anchor, CELL, rng)
            sections = _build_sections(anchor, pts, corners)

            for i, section in enumerate(sections):
                if section.is_empty or section.area < 1:
                    continue
                if i == 0:
                    seg_angle = math.atan2(
                        pts[1][1] - pts[0][1],
                        pts[1][0] - pts[0][0],
                    )
                else:
                    seg_angle = rng.uniform(0, math.pi)

                bounds = section.bounds
                diag = math.hypot(
                    bounds[2] - bounds[0], bounds[3] - bounds[1]
                )
                spacing = CELL * 0.20
                n_lines = max(3, int(diag / spacing))

                for j in range(n_lines):
                    offset = (j - (n_lines - 1) / 2) * spacing
                    cx = section.centroid.x
                    cy = section.centroid.y
                    perp_x = math.cos(seg_angle + math.pi / 2) * offset
                    perp_y = math.sin(seg_angle + math.pi / 2) * offset
                    line = LineString([
                        (
                            cx + perp_x - math.cos(seg_angle) * diag,
                            cy + perp_y - math.sin(seg_angle) * diag,
                        ),
                        (
                            cx + perp_x + math.cos(seg_angle) * diag,
                            cy + perp_y + math.sin(seg_angle) * diag,
                        ),
                    ])
                    clipped = section.intersection(line)
                    if (
                        clipped.is_empty
                        or not isinstance(clipped, LineString)
                    ):
                        continue
                    p1, p2 = list(clipped.coords)
                    wb = CELL * 0.03
                    p1 = (
                        p1[0] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=10) * wb,
                        p1[1] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=11) * wb,
                    )
                    p2 = (
                        p2[0] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=12) * wb,
                        p2[1] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=13) * wb,
                    )
                    sw = rng.uniform(min_stroke, max_stroke)
                    hatch_lines.append(
                        f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" '
                        f'x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
                        f'stroke="{INK}" stroke-width="{sw:.2f}" '
                        f'stroke-linecap="round"/>'
                    )

    if not (tile_fills or hatch_lines or hatch_stones):
        return []

    # Outer rect + dungeon polygon path produces an evenodd clip
    # that hatches everything outside the dungeon floor — see the
    # rationale comment in `_render_hatching`. Holes inside cave
    # walls flip back to "hatch" by re-including the hole rings.
    map_w = width * CELL
    map_h = height * CELL
    margin = CELL * 2
    clip_d = (
        f"M{-margin},{-margin} "
        f"H{map_w + margin} V{map_h + margin} "
        f"H{-margin} Z "
    )
    poly = region.Polygon()
    for i in range(poly.RingsLength()):
        ring = poly.Rings(i)
        start = ring.Start()
        count = ring.Count()
        coords = [
            (poly.Paths(start + j).X(), poly.Paths(start + j).Y())
            for j in range(count)
        ]
        clip_d += f"M{coords[0][0]:.0f},{coords[0][1]:.0f} "
        clip_d += " ".join(
            f"L{x:.0f},{y:.0f}" for x, y in coords[1:]
        )
        clip_d += " Z "

    out: list[str] = [
        f'<defs><clipPath id="hatch-clip">'
        f'<path d="{clip_d}" clip-rule="evenodd"/>'
        f'</clipPath></defs>',
        '<g clip-path="url(#hatch-clip)">',
    ]
    if tile_fills:
        out.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        out.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        out.append(f'<g>{"".join(hatch_stones)}</g>')
    out.append("</g>")
    return out


def _fb_polygon_to_shapely(
    poly: Any,
) -> "ShapelyPolygon | MultiPolygon | None":
    """Rebuild a Shapely polygon from an FB Polygon's rings.

    Used by the Room hatch handler for the boundary-distance
    fallback when no floor tile sits in the 5×5 neighbourhood. The
    emitter's :func:`_shapely_to_polygon` stores multi-components as
    interleaved (exterior, hole, hole, exterior, hole, ...) rings;
    every non-hole ring opens a new component. Reconstruct as a
    :class:`ShapelyPolygon` for one component or a
    :class:`MultiPolygon` for two or more so
    ``boundary.distance(...)`` matches the legacy across the rect
    dungeon (multi-component) and cave (single-component) fixtures.
    """
    if poly is None or poly.PathsLength() == 0:
        return None
    components: list[tuple[list[tuple[float, float]], list]] = []
    for i in range(poly.RingsLength()):
        ring = poly.Rings(i)
        start = ring.Start()
        count = ring.Count()
        coords = [
            (poly.Paths(start + j).X(), poly.Paths(start + j).Y())
            for j in range(count)
        ]
        if ring.IsHole():
            if not components:
                continue  # hole without preceding exterior — skip
            components[-1][1].append(coords)
        else:
            components.append((coords, []))
    if not components:
        return None
    if len(components) == 1:
        exterior, holes = components[0]
        return ShapelyPolygon(exterior, holes)
    return MultiPolygon(
        [ShapelyPolygon(exterior, holes) for exterior, holes in components]
    )


_OP_HANDLERS[Op.Op.HatchOp] = _draw_hatch_from_ir


def _draw_walls_and_floors_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_walls_and_floors``.

    Walks the IR's structured + pre-rendered fields in legacy
    output order: per-tile corridor / door rects → rect-room rects
    → smooth fills → cave region (fill + wall) → smooth walls →
    wall extensions → tile-edge walls. Schema fields for colors and
    wall_width are reserved for theme variation and ignored here in
    favour of the legacy constants — keeping the byte-equal contract
    in one obvious place.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []
    stroke_style = (
        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )

    for tile in (op.corridorTiles or []):
        out.append(
            f'<rect x="{tile.x * CELL}" y="{tile.y * CELL}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{FLOOR_COLOR}" stroke="none"/>'
        )

    for rr in (op.rectRooms or []):
        out.append(
            f'<rect x="{rr.x * CELL}" y="{rr.y * CELL}" '
            f'width="{rr.w * CELL}" height="{rr.h * CELL}" '
            f'fill="{FLOOR_COLOR}" stroke="none"/>'
        )

    for fill in (op.smoothFillSvg or []):
        out.append(_to_str(fill))

    cave_path = _to_str(op.caveRegion)
    if cave_path:
        out.append(cave_path.replace(
            "/>",
            f' fill="{CAVE_FLOOR_COLOR}" stroke="none" '
            f'fill-rule="evenodd"/>',
        ))
        out.append(cave_path.replace(
            "/>", f' fill="none" {stroke_style}/>',
        ))

    for wall in (op.smoothWallSvg or []):
        out.append(_to_str(wall))

    ext_d = _to_str(op.wallExtensionsD)
    if ext_d:
        out.append(
            f'<path d="{ext_d}" fill="none" {stroke_style}/>'
        )

    if op.wallSegments:
        segs = [_to_str(s) for s in op.wallSegments]
        out.append(
            f'<path d="{" ".join(segs)}" fill="none" '
            f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    return out


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

    clip_id = _to_str(op.clipRegion)
    if tint_rects:
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "terrain-clip"))
                out.append('<g clip-path="url(#terrain-clip)">')
                out.extend(tint_rects)
                out.append("</g>")
            else:
                out.extend(tint_rects)
        else:
            out.extend(tint_rects)

    out.extend(wash_rects)
    return out


def _dungeon_clip_defs(poly: Any, clip_id: str) -> str:
    """Build the legacy ``_dungeon_interior_clip`` defs element.

    Walks every ring (exterior + holes) once, M / L / Z encoded
    with ``:.0f`` formatting, ``fill-rule="evenodd"`` so the holes
    cut the clipped region. Reused by terrain tints (1.e) and any
    later layer that needs a dungeon-interior clip.
    """
    clip_d = ""
    for i in range(poly.RingsLength()):
        ring = poly.Rings(i)
        start = ring.Start()
        count = ring.Count()
        coords = [
            (poly.Paths(start + j).X(), poly.Paths(start + j).Y())
            for j in range(count)
        ]
        clip_d += f"M{coords[0][0]:.0f},{coords[0][1]:.0f} "
        clip_d += " ".join(
            f"L{x:.0f},{y:.0f}" for x, y in coords[1:]
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
        clip_id = _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "grid-clip"))
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


def _draw_floor_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_floor_detail``.

    Three modes:

    - ``wood_floor_groups`` non-empty → emit them verbatim and
      return. The legacy wood-floor short-circuit owns its own
      clipPath envelope; the IR carries the fragments end-to-end.
    - Otherwise: room_groups in the dungeon-interior clipPath
      envelope, then corridor_groups, then decorator_groups
      (all unclipped). Decorator groups land after corridor
      groups to mirror the legacy ``_render_floor_detail`` order
      where ``walk_and_paint(...)`` runs at the bottom.
    """
    op = OpCreator(entry.OpType(), entry.Op())

    wood_floor = [_to_str(g) for g in (op.woodFloorGroups or [])]
    if wood_floor:
        return wood_floor

    out: list[str] = []
    room_groups = [_to_str(g) for g in (op.roomGroups or [])]
    corridor_groups = [_to_str(g) for g in (op.corridorGroups or [])]
    decorator_groups = [_to_str(g) for g in (op.decoratorGroups or [])]

    if room_groups:
        clip_id = _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "detail-clip"))
                out.append('<g clip-path="url(#detail-clip)">')
                out.extend(room_groups)
                out.append("</g>")
            else:
                out.extend(room_groups)
        else:
            out.extend(room_groups)

    out.extend(corridor_groups)
    out.extend(decorator_groups)
    return out


_OP_HANDLERS[Op.Op.FloorDetailOp] = _draw_floor_detail_from_ir


def _draw_terrain_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_terrain_detail``.

    Wraps room_groups in the ``terrain-detail-clip`` envelope, then
    appends corridor_groups unclipped. Same shape as 1.g's
    floor-detail handler — the unified ``walk_and_paint`` pipeline
    means both layers share the bucketed clipPath structure.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []

    room_groups = [_to_str(g) for g in (op.roomGroups or [])]
    corridor_groups = [_to_str(g) for g in (op.corridorGroups or [])]

    if room_groups:
        clip_id = _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "terrain-detail-clip"))
                out.append('<g clip-path="url(#terrain-detail-clip)">')
                out.extend(room_groups)
                out.append("</g>")
            else:
                out.extend(room_groups)
        else:
            out.extend(room_groups)

    out.extend(corridor_groups)
    return out


_OP_HANDLERS[Op.Op.TerrainDetailOp] = _draw_terrain_detail_from_ir


def _draw_stairs_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_stairs``.

    Per-stair tapering wedge with parallel step lines, plus a
    bright fill polygon when the floor's theme is "cave". The
    legacy renderer iterates ``stairs_up`` and ``stairs_down``
    tiles in y-major order and emits the same element sequence
    per stair: cave fill (if cave theme) → top rail → bottom rail
    → 6 step lines.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []
    theme = _to_str(op.theme)
    fill_color = _to_str(op.fillColor)

    rail_sw = 1.5
    step_sw = 1.0
    n_steps = 5
    wide_h = CELL * 0.4
    narrow_h = CELL * 0.1

    for stair in (op.stairs or []):
        x, y = stair.x, stair.y
        down = stair.direction == StairDirection.StairDirection.Down
        px, py = x * CELL, y * CELL
        m = CELL * 0.1
        cy = py + CELL / 2
        left_x = px + m
        right_x = px + CELL - m

        if theme == "cave":
            if down:
                pts = (
                    f'{left_x:.1f},{cy - wide_h:.1f} '
                    f'{right_x:.1f},{cy - narrow_h:.1f} '
                    f'{right_x:.1f},{cy + narrow_h:.1f} '
                    f'{left_x:.1f},{cy + wide_h:.1f}'
                )
            else:
                pts = (
                    f'{left_x:.1f},{cy - narrow_h:.1f} '
                    f'{right_x:.1f},{cy - wide_h:.1f} '
                    f'{right_x:.1f},{cy + wide_h:.1f} '
                    f'{left_x:.1f},{cy + narrow_h:.1f}'
                )
            out.append(
                f'<polygon points="{pts}" '
                f'fill="{fill_color}" stroke="none"/>'
            )

        if down:
            top_y0, top_y1 = cy - wide_h, cy - narrow_h
            bot_y0, bot_y1 = cy + wide_h, cy + narrow_h
            wide_start, narrow_end = wide_h, narrow_h
        else:
            top_y0, top_y1 = cy - narrow_h, cy - wide_h
            bot_y0, bot_y1 = cy + narrow_h, cy + wide_h
            wide_start, narrow_end = narrow_h, wide_h

        out.append(
            f'<line x1="{left_x:.1f}" y1="{top_y0:.1f}" '
            f'x2="{right_x:.1f}" y2="{top_y1:.1f}" '
            f'stroke="{INK}" stroke-width="{rail_sw}" '
            f'stroke-linecap="round"/>'
        )
        out.append(
            f'<line x1="{left_x:.1f}" y1="{bot_y0:.1f}" '
            f'x2="{right_x:.1f}" y2="{bot_y1:.1f}" '
            f'stroke="{INK}" stroke-width="{rail_sw}" '
            f'stroke-linecap="round"/>'
        )

        span = right_x - left_x
        for i in range(n_steps + 1):
            t = i / n_steps
            sx = left_x + span * t
            half = wide_start + (narrow_end - wide_start) * t
            out.append(
                f'<line x1="{sx:.1f}" y1="{cy - half:.1f}" '
                f'x2="{sx:.1f}" y2="{cy + half:.1f}" '
                f'stroke="{INK}" stroke-width="{step_sw}" '
                f'stroke-linecap="round"/>'
            )

    return out


_OP_HANDLERS[Op.Op.StairsOp] = _draw_stairs_from_ir


def _draw_generic_procedural_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 1 escape hatch — emit ``op.groups`` verbatim.

    Used by 1.m's surface_features passthrough (and any future
    layer-level passthrough that doesn't yet have a structured
    op). The handler is intentionally trivial: it just decodes
    the FB string list and returns it. ``op.name`` selects which
    layer slot the groups land in via ``_LAYER_OPS`` membership;
    this handler stays neutral on the dispatch since the slot
    decision is the dispatcher's job.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    return [_to_str(g) for g in (op.groups or [])]


_OP_HANDLERS[Op.Op.GenericProceduralOp] = _draw_generic_procedural_from_ir
