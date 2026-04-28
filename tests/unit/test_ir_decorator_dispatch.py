"""Sentinel: dispatcher knows about ``DecoratorOp``.

Per §8 step 5 of ``plans/nhc_ir_migration_plan.md`` (Q2 schema
bump B, locked 2026-04-28), the decorator pipeline gains a
structured ``DecoratorOp`` carrying seven per-decorator vector
fields (cobblestone / brick / flagstone / opus_romano /
field_stone / cart_tracks / ore_deposit). Each variant ports
to Rust at sub-steps 6–12; until then this commit ships an
empty-arm dispatcher stub plus the layer-registry membership
that future emits rely on.

This test asserts the plumbing exists and behaves as a no-op
(legacy decorator passthrough at
``FloorDetailOp.decorator_groups`` still serves rendering).
"""
from __future__ import annotations

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir_to_svg import _LAYER_OPS, _OP_HANDLERS


def test_decorator_handler_registered() -> None:
    handler = _OP_HANDLERS.get(Op.Op.DecoratorOp)
    assert handler is not None, (
        "no IR→SVG handler registered for DecoratorOp; step 5 "
        "of plan §8 ships an empty-arm stub"
    )


def test_decorator_handler_returns_empty() -> None:
    """Step 5 ships an empty-arm stub. Per-variant Rust ports
    land at sub-steps 6–12; until then the handler must produce
    no fragments so the ``passthrough fallback wins`` invariant
    holds. The stub doesn't dereference its arguments — pass
    ``None`` for both."""
    handler = _OP_HANDLERS[Op.Op.DecoratorOp]
    assert handler(None, None) == []


def test_decorator_in_floor_detail_layer() -> None:
    """The decorator pipeline rides in the floor_detail layer
    slot (legacy ``walk_and_paint`` runs alongside the floor-
    detail-proper output as a post-pass)."""
    assert Op.Op.DecoratorOp in _LAYER_OPS["floor_detail"], (
        "DecoratorOp not registered in the floor_detail layer; "
        "step 5 of plan §8 adds it alongside FloorDetailOp"
    )
