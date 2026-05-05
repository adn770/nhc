"""Op-shape invariants for the canonical IR op stream.

For each parity fixture, asserts emit-side invariants that any
well-formed FloorIR has to satisfy regardless of how it was built:

- Region count matches between the v4 and v5 (post-cut: canonical)
  region arrays.
- Op-counter parity between v4 wall ops and V5StrokeOp, between
  v4 RoofOp and V5RoofOp, etc — caught here so emit-side drift
  surfaces before the parity gate runs.
- Every V5PaintOp's material references an in-range
  V5MaterialFamily.
- Every V5StrokeOp's wallMaterial references an in-range
  V5MaterialFamily and an in-range V5WallTreatment.
- Every V5PaintOp's region_ref resolves to a v5 region id (or is
  empty, which the dispatcher treats as op-level geometry).

Originally the v5-vs-v4 emit parity gate at Phase 1.5 of
``plans/nhc_pure_ir_v5_migration_plan.md``. Phase 4.2b promotes the
gate to "canonical op-shape invariants" — the same assertions hold
post-cut once the V5* prefix is renamed away at 4.3 and the v4
region/op arrays go away. The body changes by mechanical rename at
that point; the contract is the same.

Acceptance role: any emit-side regression that lands a malformed
op stream (missing region_ref, out-of-range enum, op-count drift)
surfaces here as a fixture-parametrised failure, ahead of the PNG
parity / pixel-PSNR gates whose failures are noisier to bisect.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5WallTreatment import V5WallTreatment


_FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "floor_ir"


def _all_fixture_buffers() -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for entry in sorted(_FIXTURE_ROOT.iterdir()):
        nir = entry / "floor.nir"
        if nir.is_file():
            out.append((entry.name, nir.read_bytes()))
    return out


def _fixture_ids() -> list[str]:
    return [name for name, _ in _all_fixture_buffers()]


@pytest.fixture(scope="module", params=_all_fixture_buffers(), ids=_fixture_ids())
def fixture(request) -> tuple[str, FloorIR]:
    name, buf = request.param
    fir = FloorIR.GetRootAs(buf, 0)
    return name, fir


def _count_v4_ops(fir: FloorIR) -> Counter:
    counts: Counter = Counter()
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        counts[entry.OpType()] += 1
    return counts


def _count_v5_ops(fir: FloorIR) -> Counter:
    counts: Counter = Counter()
    for i in range(fir.V5OpsLength()):
        entry = fir.V5Ops(i)
        counts[entry.OpType()] += 1
    return counts


# ── Canonical invariants (survive the 4.3 cut) ─────────────────


def test_every_region_carries_an_id(fixture):
    """Every region in the canonical (v5) array exposes a non-null
    id — region_ref resolution depends on it."""
    name, fir = fixture
    for i in range(fir.V5RegionsLength()):
        region = fir.V5Regions(i)
        assert region.Id() is not None, f"{name}: region {i} missing id"


# ── Pre-cut cross-checks against v4 legacy emit (deleted at 4.3) ──
#
# While both arrays ride the same FloorIR, op-count parity between
# the v4 (legacy) and v5 (canonical) streams is the sharpest
# emit-side regression detector. At Phase 4.3 the v4 arrays go
# away and these tests get deleted; the canonical invariants above
# carry forward unchanged.


def test_regions_count_matches_v4_legacy(fixture):
    name, fir = fixture
    assert fir.V5RegionsLength() == fir.RegionsLength(), (
        f"{name}: regions count diverges from v4 legacy"
    )


def test_paint_op_count_at_least_v4_floor_op_count(fixture):
    """Every v4 FloorOp lifts to one V5PaintOp; DecoratorOp stone
    variants lift to additional V5PaintOps. So canonical PaintOp
    count must be >= v4 FloorOp count."""
    name, fir = fixture
    v4_counts = _count_v4_ops(fir)
    v5_counts = _count_v5_ops(fir)
    floor_ops = v4_counts.get(Op.FloorOp, 0)
    paint_ops = v5_counts.get(V5Op.V5PaintOp, 0)
    assert paint_ops >= floor_ops, (
        f"{name}: PaintOps ({paint_ops}) < v4 FloorOps ({floor_ops})"
    )


def test_stroke_op_count_matches_v4_wall_op_count(fixture):
    """Every v4 wall op (Exterior, Interior, Corridor) lifts to
    one V5StrokeOp."""
    name, fir = fixture
    v4_counts = _count_v4_ops(fir)
    v5_counts = _count_v5_ops(fir)
    wall_ops = (
        v4_counts.get(Op.ExteriorWallOp, 0)
        + v4_counts.get(Op.InteriorWallOp, 0)
        + v4_counts.get(Op.CorridorWallOp, 0)
    )
    stroke_ops = v5_counts.get(V5Op.V5StrokeOp, 0)
    assert stroke_ops == wall_ops, (
        f"{name}: StrokeOps ({stroke_ops}) != v4 wall ops ({wall_ops})"
    )


def test_roof_op_count_matches_v4_legacy(fixture):
    name, fir = fixture
    v4_counts = _count_v4_ops(fir)
    v5_counts = _count_v5_ops(fir)
    assert v5_counts.get(V5Op.V5RoofOp, 0) == v4_counts.get(Op.RoofOp, 0), (
        f"{name}: V5RoofOp count diverges from v4 RoofOp count"
    )


# ── Material-family validity (canonical, survives the cut) ─────

_VALID_FAMILIES = {
    V5MaterialFamily.Plain,
    V5MaterialFamily.Cave,
    V5MaterialFamily.Wood,
    V5MaterialFamily.Stone,
    V5MaterialFamily.Earth,
    V5MaterialFamily.Liquid,
    V5MaterialFamily.Special,
}

_VALID_TREATMENTS = {
    V5WallTreatment.PlainStroke,
    V5WallTreatment.Masonry,
    V5WallTreatment.Partition,
    V5WallTreatment.Palisade,
    V5WallTreatment.Fortification,
}


def test_every_paint_op_carries_a_valid_material(fixture):
    name, fir = fixture
    for i in range(fir.V5OpsLength()):
        entry = fir.V5Ops(i)
        if entry.OpType() != V5Op.V5PaintOp:
            continue
        from nhc.rendering.ir._fb.V5PaintOp import V5PaintOp
        paint = V5PaintOp()
        paint.Init(entry.Op().Bytes, entry.Op().Pos)
        material = paint.Material()
        assert material is not None, f"{name}: PaintOp {i} missing material"
        assert material.Family() in _VALID_FAMILIES, (
            f"{name}: PaintOp {i} has out-of-range material family "
            f"{material.Family()}"
        )


def test_every_stroke_op_carries_a_valid_wall_material(fixture):
    name, fir = fixture
    for i in range(fir.V5OpsLength()):
        entry = fir.V5Ops(i)
        if entry.OpType() != V5Op.V5StrokeOp:
            continue
        from nhc.rendering.ir._fb.V5StrokeOp import V5StrokeOp
        stroke = V5StrokeOp()
        stroke.Init(entry.Op().Bytes, entry.Op().Pos)
        wm = stroke.WallMaterial()
        assert wm is not None, f"{name}: StrokeOp {i} missing wall material"
        assert wm.Family() in _VALID_FAMILIES, (
            f"{name}: StrokeOp {i} has out-of-range wall family"
        )
        assert wm.Treatment() in _VALID_TREATMENTS, (
            f"{name}: StrokeOp {i} has out-of-range wall treatment"
        )


# ── Geometry resolution: every paint op resolves a region ──────


def test_every_paint_op_resolves_a_region(fixture):
    name, fir = fixture
    region_ids: set[str] = set()
    for i in range(fir.V5RegionsLength()):
        rid = fir.V5Regions(i).Id()
        if rid is not None:
            region_ids.add(rid.decode("utf-8"))
    for i in range(fir.V5OpsLength()):
        entry = fir.V5Ops(i)
        if entry.OpType() != V5Op.V5PaintOp:
            continue
        from nhc.rendering.ir._fb.V5PaintOp import V5PaintOp
        paint = V5PaintOp()
        paint.Init(entry.Op().Bytes, entry.Op().Pos)
        rr = paint.RegionRef()
        if rr is None or len(rr) == 0:
            # Empty region_ref is allowed (paint defers to op-level
            # geometry; not produced by current emitter).
            continue
        rr = rr.decode("utf-8")
        assert rr in region_ids, (
            f"{name}: PaintOp {i} region_ref={rr!r} not in regions"
        )
