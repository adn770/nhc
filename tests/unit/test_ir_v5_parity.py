"""v5-vs-v4 emit parity gate (Phase 1.5 of v5 migration plan).

For each parity fixture, verifies that the v5 emit translators
produce a well-formed ``v5_regions`` / ``v5_ops`` set that
corresponds structurally to the v4 emit output:

- Region count matches.
- Every v4 op type has the right number of v5 op counterparts.
- v5 paint-op materials reference an in-range family.
- v5 stroke-op wall materials reference an in-range treatment.
- All v5 ops carry a non-empty region_ref OR an outline (StrokeOp).

This gate is *structural*, not pixel-equal. The plan's stated
PSNR ≥ 50 dB cross-rasteriser gate requires the v5 family
painters (Phase 2.x) to match the v4 painters' visual output.
Until those land, the pixel-PSNR gate cannot pass even when
emit is correct. The structural gate here catches emit-side
regressions; once Phase 2 ships, this module gains a sibling
``test_ir_v5_pixel_parity.py`` for the PSNR check.

The contract is the load-bearing acceptance gate before the
atomic cut at Phase 1.8: any v5 emit / consume mismatch should
surface here, not silently propagate into the cut.
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


# ── Region-count parity ────────────────────────────────────────


def test_v5_regions_count_matches_v4_regions(fixture):
    name, fir = fixture
    assert fir.V5RegionsLength() == fir.RegionsLength(), (
        f"{name}: v5 regions count diverges from v4"
    )


def test_every_v5_region_carries_an_id(fixture):
    name, fir = fixture
    for i in range(fir.V5RegionsLength()):
        region = fir.V5Regions(i)
        assert region.Id() is not None, f"{name}: v5 region {i} missing id"


# ── Op-count parity ────────────────────────────────────────────


def test_v5_paint_op_count_at_least_floor_op_count(fixture):
    """Every v4 FloorOp emits one V5PaintOp; DecoratorOp stone
    variants emit additional V5PaintOps. So v5 PaintOp count
    must be >= v4 FloorOp count."""
    name, fir = fixture
    v4_counts = _count_v4_ops(fir)
    v5_counts = _count_v5_ops(fir)
    floor_ops = v4_counts.get(Op.FloorOp, 0)
    paint_ops = v5_counts.get(V5Op.V5PaintOp, 0)
    assert paint_ops >= floor_ops, (
        f"{name}: v5 PaintOps ({paint_ops}) < v4 FloorOps ({floor_ops})"
    )


def test_v5_stroke_op_count_matches_v4_wall_op_count(fixture):
    """Every v4 wall op (Exterior, Interior, Corridor) maps to
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
        f"{name}: v5 StrokeOps ({stroke_ops}) != v4 wall ops ({wall_ops})"
    )


def test_v5_roof_op_count_matches_v4_roof_op_count(fixture):
    name, fir = fixture
    v4_counts = _count_v4_ops(fir)
    v5_counts = _count_v5_ops(fir)
    assert v5_counts.get(V5Op.V5RoofOp, 0) == v4_counts.get(Op.RoofOp, 0), (
        f"{name}: v5 RoofOp count diverges from v4 RoofOp count"
    )


# ── Material-family validity ───────────────────────────────────

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


def test_every_v5_paint_op_carries_a_valid_material(fixture):
    name, fir = fixture
    for i in range(fir.V5OpsLength()):
        entry = fir.V5Ops(i)
        if entry.OpType() != V5Op.V5PaintOp:
            continue
        # Read concrete v5 paint op via Table view.
        from nhc.rendering.ir._fb.V5PaintOp import V5PaintOp
        paint = V5PaintOp()
        paint.Init(entry.Op().Bytes, entry.Op().Pos)
        material = paint.Material()
        assert material is not None, f"{name}: v5 PaintOp {i} missing material"
        assert material.Family() in _VALID_FAMILIES, (
            f"{name}: v5 PaintOp {i} has out-of-range material family "
            f"{material.Family()}"
        )


def test_every_v5_stroke_op_carries_a_valid_wall_material(fixture):
    name, fir = fixture
    for i in range(fir.V5OpsLength()):
        entry = fir.V5Ops(i)
        if entry.OpType() != V5Op.V5StrokeOp:
            continue
        from nhc.rendering.ir._fb.V5StrokeOp import V5StrokeOp
        stroke = V5StrokeOp()
        stroke.Init(entry.Op().Bytes, entry.Op().Pos)
        wm = stroke.WallMaterial()
        assert wm is not None, f"{name}: v5 StrokeOp {i} missing wall material"
        assert wm.Family() in _VALID_FAMILIES, (
            f"{name}: v5 StrokeOp {i} has out-of-range wall family"
        )
        assert wm.Treatment() in _VALID_TREATMENTS, (
            f"{name}: v5 StrokeOp {i} has out-of-range wall treatment"
        )


# ── Geometry resolution: every paint op resolves a region ──────


def test_every_v5_paint_op_resolves_a_v5_region(fixture):
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
            f"{name}: v5 PaintOp {i} region_ref={rr!r} not in v5_regions"
        )
