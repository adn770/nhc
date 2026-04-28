"""Sentinel: dispatcher knows about ``DecoratorOp``.

Per §8 step 5 of ``plans/nhc_ir_migration_plan.md`` (Q2 schema
bump B, locked 2026-04-28), the decorator pipeline gains a
structured ``DecoratorOp`` carrying seven per-decorator vector
fields (cobblestone / brick / flagstone / opus_romano /
field_stone / cart_tracks / ore_deposit). Step 6 wired the
cobblestone variant to its Rust port; the remaining six
variants land at sub-steps 7–12.

This test asserts the dispatcher / layer plumbing is in place.
The cobblestone-port behaviour gate lives in
``test_emit_cobblestone_invariants.py``.
"""
from __future__ import annotations

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir_to_svg import _LAYER_OPS, _OP_HANDLERS


def test_decorator_handler_registered() -> None:
    handler = _OP_HANDLERS.get(Op.Op.DecoratorOp)
    assert handler is not None, (
        "no IR→SVG handler registered for DecoratorOp"
    )


def test_decorator_in_floor_detail_layer() -> None:
    """The decorator pipeline rides in the floor_detail layer
    slot (legacy ``walk_and_paint`` runs alongside the floor-
    detail-proper output as a post-pass)."""
    assert Op.Op.DecoratorOp in _LAYER_OPS["floor_detail"], (
        "DecoratorOp not registered in the floor_detail layer; "
        "step 5 of plan §8 adds it alongside FloorDetailOp"
    )
