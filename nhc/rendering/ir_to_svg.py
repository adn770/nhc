"""IR → SVG transformer — Phase 1.a skeleton.

Cold-path transformer: consumes a ``FloorIR`` FlatBuffer and emits
the SVG string ``render_floor_svg`` used to produce. The byte-equal
gate in :mod:`tests.unit.test_ir_to_svg` is the contract that
protects every Phase 1–7 transition.

Phase 1.a wires the envelope (``<svg>`` header, background rect,
``<g transform>`` translate) and the dispatch loop. The
:data:`_OP_HANDLERS` registry is empty; per-layer commits
1.b–1.j register one handler per op kind. Phase 1.k populates the
fixture ``.nir`` files and the parity gate flips green.

Op-handler signature::

    handler(op_entry: OpEntry, fir: FloorIR) -> list[str]

Each handler returns a list of SVG element-line strings that are
``\\n``-joined with the rest of the output, matching the legacy
``render_layers`` joining behaviour.
"""

from __future__ import annotations

from typing import Callable

from nhc.rendering._svg_helpers import BG
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.OpEntry import OpEntry


# Maps Op union tag → handler. Layer commits 1.b–1.j each register
# one entry; 1.a leaves the table empty so the dispatch loop short-
# circuits on op-empty IRs (and raises on any op surfaced before its
# handler lands, surfacing the contract violation immediately).
_OP_HANDLERS: dict[int, Callable[[OpEntry, FloorIR], list[str]]] = {}


def ir_to_svg(buf: bytes) -> str:
    """Render a ``FloorIR`` FlatBuffer to its legacy SVG output.

    Phase 1.a returns an envelope-wrapped empty SVG for an op-empty
    IR. The integration parity gate in
    :mod:`tests.unit.test_ir_to_svg` stays XFAIL until 1.k populates
    the ops vector and registers every handler.
    """
    if not FloorIR.FloorIRBufferHasIdentifier(buf, 0):
        raise ValueError(
            "Buffer does not carry the NIRF file_identifier — is "
            "this a FloorIR buffer at the current schema major?"
        )
    fir = FloorIR.GetRootAs(buf, 0)
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
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        op_type = entry.OpType()
        handler = _OP_HANDLERS.get(op_type)
        if handler is None:
            # Each layer commit registers its handler in the same PR
            # that emits the op, so a missing handler here is a
            # contract violation, not an extensibility hook.
            raise NotImplementedError(
                f"no IR→SVG handler registered for Op tag {op_type}; "
                "the matching Phase 1 layer commit must register one"
            )
        parts.extend(handler(entry, fir))
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)
