"""Enclosure gate cuts center on the gate's tile span.

A real-site gate ``(gx, gy, length)`` spans ``length`` tiles in +y
from ``(gx, gy)`` (see ``_gate_apron_tiles``). The rendered wall cut
must cover exactly those rows so the gate opening lines up with the
street that routes to it. Pre-fix the projection used the gate's
top-left corner as the cut centre, so the symmetric cut landed half a
gate (one tile) too far north — the gate looked "one tile off" from
the street.
"""

from __future__ import annotations

from nhc.rendering._ir_helpers import CELL, PADDING
from nhc.rendering._outline_helpers import (
    cuts_for_enclosure_gates,
    project_site_gate_cut,
)
from nhc.rendering.ir._fb.CutStyle import CutStyle


def _rect_poly_px(min_x, min_y, max_x, max_y):
    return [
        (PADDING + min_x * CELL, PADDING + min_y * CELL),
        (PADDING + max_x * CELL, PADDING + min_y * CELL),
        (PADDING + max_x * CELL, PADDING + max_y * CELL),
        (PADDING + min_x * CELL, PADDING + max_y * CELL),
    ]


def _gate_cut(gate, poly):
    triple = project_site_gate_cut(gate, poly)
    cuts = cuts_for_enclosure_gates(poly, [triple], CutStyle.WoodGate)
    assert len(cuts) == 1
    return cuts[0]


def test_east_gate_cut_spans_exact_gate_rows():
    poly = _rect_poly_px(2, 2, 12, 12)
    gate = (12, 5, 2)  # east wall (gx == max_x), rows 5..6
    cut = _gate_cut(gate, poly)
    ys = sorted((cut.start.y, cut.end.y))
    # The opening must cover the gate's tile edges: top of row 5 to
    # the bottom of row 6.
    assert ys[0] == PADDING + 5 * CELL          # 192
    assert ys[1] == PADDING + (5 + 2) * CELL     # 256
    # And the x sits on the east wall.
    assert cut.start.x == cut.end.x == PADDING + 12 * CELL


def test_west_gate_cut_spans_exact_gate_rows():
    poly = _rect_poly_px(2, 2, 12, 12)
    gate = (2, 4, 2)  # west wall (gx == min_x), rows 4..5
    cut = _gate_cut(gate, poly)
    ys = sorted((cut.start.y, cut.end.y))
    assert ys[0] == PADDING + 4 * CELL
    assert ys[1] == PADDING + (4 + 2) * CELL
    assert cut.start.x == cut.end.x == PADDING + 2 * CELL


def test_three_tile_gate_centers_on_its_span():
    poly = _rect_poly_px(0, 0, 20, 20)
    gate = (20, 8, 3)  # keep-style length-3 gate, rows 8..10
    cut = _gate_cut(gate, poly)
    ys = sorted((cut.start.y, cut.end.y))
    assert ys[0] == PADDING + 8 * CELL
    assert ys[1] == PADDING + (8 + 3) * CELL
