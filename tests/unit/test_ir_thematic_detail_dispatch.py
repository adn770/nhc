"""Sentinel: dispatcher knows about ``ThematicDetailOp``.

Per §8 step 2 of ``plans/nhc_ir_migration_plan.md``, the
``ThematicDetailOp`` table (already in the schema since the
Phase 0.2 setup commit) is wired to a no-op dispatcher arm so
that future emits of the op type don't raise the
``NotImplementedError`` ``_dispatch_ops`` throws for unknown op
tags. The actual port lands at step 4
(``thematic_detail`` Rust port); until then the thematic detail
keeps flowing through the legacy ``FloorDetailOp`` passthrough.

This test asserts the plumbing exists and behaves as a no-op.
It also pins ``thematic_detail`` into the layer-name registry so
``layer_to_svg(buf, layer="thematic_detail")`` resolves to the
ThematicDetailOp set instead of raising ``KeyError``.
"""

from __future__ import annotations

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir_to_svg import _LAYER_OPS, _OP_HANDLERS


def test_thematic_detail_handler_registered() -> None:
    handler = _OP_HANDLERS.get(Op.Op.ThematicDetailOp)
    assert handler is not None, (
        "no IR→SVG handler registered for ThematicDetailOp; "
        "step 2 of plan §8 ships an empty-arm stub"
    )


def test_thematic_detail_handler_returns_empty() -> None:
    """Step 2 ships an empty-arm stub. The actual painting lands
    at step 4; until then the handler must produce no fragments
    so the ``passthrough fallback wins`` invariant from the plan
    holds."""
    handler = _OP_HANDLERS[Op.Op.ThematicDetailOp]
    # The handler signature is ``(entry: OpEntry, fir: FloorIR)``;
    # for the empty-arm stub neither argument is dereferenced. We
    # pass ``None`` for both — if the stub does anything beyond
    # returning ``[]`` this will raise.
    assert handler(None, None) == []


def test_thematic_detail_layer_registered() -> None:
    assert "thematic_detail" in _LAYER_OPS, (
        "thematic_detail layer not registered in _LAYER_OPS; "
        "step 2 of plan §8 adds it alongside the dispatcher arm"
    )
    assert _LAYER_OPS["thematic_detail"] == frozenset({
        Op.Op.ThematicDetailOp,
    })
