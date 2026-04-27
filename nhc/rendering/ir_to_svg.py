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
    BG, CAVE_FLOOR_COLOR, CELL, FLOOR_COLOR, HATCH_UNDERLAY, INK,
    WALL_WIDTH,
)
from nhc.rendering.ir._fb import HatchKind, Op, ShadowKind, TerrainKind
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.Op import OpCreator
from nhc.rendering.ir._fb.OpEntry import OpEntry
from nhc.rendering.ir._fb.Region import Region


# Maps Op union tag → handler. Layer commits 1.b–1.j each register
# one entry; an op surfacing without a handler is a contract
# violation, not an extensibility hook.
_OP_HANDLERS: dict[int, Callable[[OpEntry, FloorIR], list[str]]] = {}


# Maps layer name → set of Op union tags belonging to that layer.
# Source: design/map_ir.md §6 layer ordering. Each layer commit
# adds an entry as it lands its first op; the dict is the contract
# the per-layer parity tests dispatch against.
_LAYER_OPS: dict[str, frozenset[int]] = {
    "shadows": frozenset({Op.Op.ShadowOp}),
    "hatching": frozenset({Op.Op.HatchOp}),
    "walls_and_floors": frozenset({Op.Op.WallsAndFloorsOp}),
    "terrain_tints": frozenset({Op.Op.TerrainTintOp}),
}


def ir_to_svg(buf: bytes) -> str:
    """Render a ``FloorIR`` FlatBuffer to its legacy SVG output.

    The integration parity gate in
    :mod:`tests.unit.test_ir_to_svg` stays XFAIL until 1.k populates
    the ops vector and registers every handler.
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
    parts.extend(_dispatch_ops(fir, op_filter=None))
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

    Per-tile WATER / GRASS / LAVA / CHASM rects (with the palette
    tint + opacity for the floor's theme) wrapped in a dungeon-
    interior clipPath, then per-room hint washes appended after.
    The IR carries the resolved color + opacity inline on each
    ``RoomWash`` so the handler doesn't need the room-tag table.
    Terrain colors come from the palette keyed on ``fir.theme``.
    """
    from nhc.dungeon.model import Terrain
    from nhc.rendering.terrain_palette import get_palette

    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []

    theme = _to_str(fir.Theme())
    palette = get_palette(theme)
    style_by_kind = {
        TerrainKind.TerrainKind.Water: palette.water,
        TerrainKind.TerrainKind.Grass: palette.grass,
        TerrainKind.TerrainKind.Lava: palette.lava,
        TerrainKind.TerrainKind.Chasm: palette.chasm,
    }

    tint_rects: list[str] = []
    for tile in (op.tiles or []):
        style = style_by_kind.get(tile.kind)
        if style is None:
            continue
        tint_rects.append(
            f'<rect x="{tile.x * CELL}" y="{tile.y * CELL}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{style.tint}" opacity="{style.tint_opacity}"/>'
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

    for w in (op.roomWashes or []):
        color = _to_str(w.color)
        # ROOM_TYPE_TINTS values are 2-decimal (0.06 / 0.12 / 0.15
        # / 0.18); float32 storage would surface them as
        # "0.05999999865889549". `:.2f` keeps the byte-equal
        # contract with the legacy Python f-string. If a future
        # tint table introduces sub-percent precision, switch the
        # field to `double` in the schema.
        out.append(
            f'<rect x="{w.x * CELL}" y="{w.y * CELL}" '
            f'width="{w.w * CELL}" height="{w.h * CELL}" '
            f'fill="{color}" opacity="{w.opacity:.2f}"/>'
        )
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
