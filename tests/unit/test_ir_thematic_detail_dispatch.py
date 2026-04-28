"""Sentinel: dispatcher knows about ``ThematicDetailOp``.

Per §8 step 2 of ``plans/nhc_ir_migration_plan.md``, the
``ThematicDetailOp`` table is wired to a dispatcher arm so the
``NotImplementedError`` ``_dispatch_ops`` throws for unknown op
tags doesn't fire when the op type appears. Step 2 shipped an
empty-arm stub; sub-step 4.b promoted the arm to drive the
Python painter from the IR. The Rust port lands at sub-step
4.e.

This test asserts the plumbing exists. It also pins
``thematic_detail`` into the layer-name registry so
``layer_to_svg(buf, layer="thematic_detail")`` resolves to the
ThematicDetailOp set instead of raising ``KeyError``.
"""

from __future__ import annotations

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir_to_svg import _LAYER_OPS, _OP_HANDLERS


def test_thematic_detail_handler_registered() -> None:
    handler = _OP_HANDLERS.get(Op.Op.ThematicDetailOp)
    assert handler is not None, (
        "no IR→SVG handler registered for ThematicDetailOp"
    )


def test_thematic_detail_layer_registered() -> None:
    assert "thematic_detail" in _LAYER_OPS, (
        "thematic_detail layer not registered in _LAYER_OPS; "
        "step 2 of plan §8 adds it alongside the dispatcher arm"
    )
    assert _LAYER_OPS["thematic_detail"] == frozenset({
        Op.Op.ThematicDetailOp,
    })
