"""Phase 1.25 — per-tile ops gain region_ref (schema 3.5).

Pins the fourth sub-phase of the v4e migration: every per-tile op
(``TerrainTintOp`` / ``FloorGridOp`` / ``FloorDetailOp`` /
``ThematicDetailOp`` / ``TerrainDetailOp`` / ``DecoratorOp``)
carries a ``region_ref: string`` parallel to the existing
``clip_region: string``. Consumers (Python + Rust) prefer
``region_ref``; empty falls back to ``clip_region`` for 3.x
cached buffers. The legacy ``clip_region`` retires at the 1.27
atomic cut.

No pixel change at 1.25 — both fields resolve to identical clip
regions under parallel emission.
"""

from __future__ import annotations

from typing import Any

import pytest

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


_PER_TILE_OP_TYPES: tuple[int, ...] = (
    Op.Op.TerrainTintOp,
    Op.Op.FloorGridOp,
    Op.Op.FloorDetailOp,
    Op.Op.ThematicDetailOp,
    Op.Op.TerrainDetailOp,
    Op.Op.DecoratorOp,
)


def _decode(s: Any) -> str:
    return s.decode() if isinstance(s, bytes) else (s or "")


def _build_emitted(descriptor: str) -> FloorIRT:
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(descriptor)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    return FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))


# ── Schema bump ────────────────────────────────────────────────


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_schema_major_is_4(descriptor: str) -> None:
    """NIR4: SCHEMA_MAJOR = 4."""
    fir = _build_emitted(descriptor)
    assert fir.major == 4, f"expected major=4, got {fir.major}"


# ── Parallel emission invariant ────────────────────────────────


# NIR4: test_per_tile_op_clip_region_empty_post_1_26a deleted —
# clipRegion field is gone from the schema; region_ref is the only
# canonical source.


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_per_tile_op_region_ref_carries_clip_target(descriptor: str) -> None:
    """region_ref carries the clip target ("dungeon" or "")."""
    fir = _build_emitted(descriptor)
    for entry in fir.ops or []:
        if entry.opType not in _PER_TILE_OP_TYPES:
            continue
        op = entry.op
        region_ref = _decode(op.regionRef)
        assert region_ref in ("", "dungeon"), (
            f"{descriptor}: per-tile op {op.__class__.__name__} "
            f"region_ref must be '' or 'dungeon'; got "
            f"{region_ref!r}"
        )


# ── Consumer preference (synthetic IR) ─────────────────────────


# NIR4: test_consumer_prefers_region_ref_over_clip_region deleted —
# clipRegion is gone from the schema; only region_ref remains, so
# there's no parallel field to test "preference" between.
