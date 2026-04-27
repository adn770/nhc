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

from typing import Callable

from nhc.rendering._svg_helpers import BG, CELL, INK
from nhc.rendering.ir._fb import Op, ShadowKind
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.Op import OpCreator
from nhc.rendering.ir._fb.OpEntry import OpEntry


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

    1.b.1 lands the Corridor branch; 1.b.2 fills in the Room branch
    once ``emit_regions`` registers per-room polygons. The schema's
    ``dx`` / ``dy`` / ``opacity`` defaults (3.0 / 3.0 / 0.08) match
    the legacy hard-coded constants — the handler ignores the FB
    fields and uses literals instead, both to dodge the float32
    round-trip on 0.08 (which would surface as
    "0.07999999821186066") and to keep parity formatting integer
    where the legacy renderer's int arithmetic produced integers.
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
        raise NotImplementedError(
            "Room shadows ship in Phase 1.b.2 — extend "
            "_draw_shadow_from_ir's Room branch then"
        )
    raise ValueError(f"unknown ShadowKind: {kind}")


_OP_HANDLERS[Op.Op.ShadowOp] = _draw_shadow_from_ir
