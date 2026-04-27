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

from shapely.geometry import LineString

from nhc.rendering import _perlin as _noise
from nhc.rendering._cave_geometry import _smooth_closed_path
from nhc.rendering._dungeon_polygon import (
    _build_sections, _pick_section_points,
)
from nhc.rendering._svg_helpers import BG, CELL, HATCH_UNDERLAY, INK
from nhc.rendering.ir._fb import HatchKind, Op, ShadowKind
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
        raise NotImplementedError(
            "Room hatching ships in Phase 1.c.2 — extend "
            "_draw_hatch_from_ir's Room branch then"
        )
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


_OP_HANDLERS[Op.Op.HatchOp] = _draw_hatch_from_ir
