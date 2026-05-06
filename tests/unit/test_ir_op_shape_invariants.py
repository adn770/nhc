"""Op-shape invariants for the canonical IR op stream (NIR5).

For each parity fixture, asserts emit-side invariants that any
well-formed FloorIR has to satisfy:

- Every ``PaintOp.material`` carries an in-range ``MaterialFamily``.
- Every ``StrokeOp.wall_material`` carries an in-range
  ``MaterialFamily`` and ``WallTreatment``.
- Every ``PaintOp.region_ref`` and ``StrokeOp.region_ref``
  resolves to a region id (or is empty, which the dispatcher
  treats as op-level geometry).
- Every fixture has at least one region.

Catches emit-side drift before the PNG / SVG parity gate runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.WallTreatment import WallTreatment


_FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "floor_ir"

_VALID_FAMILY_VALUES = {
    v for k, v in vars(MaterialFamily).items()
    if not k.startswith("_") and isinstance(v, int)
}
_VALID_TREATMENT_VALUES = {
    v for k, v in vars(WallTreatment).items()
    if not k.startswith("_") and isinstance(v, int)
}


def _all_fixture_buffers() -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for entry in sorted(_FIXTURE_ROOT.iterdir()):
        nir = entry / "floor.nir"
        if nir.is_file():
            out.append((entry.name, nir.read_bytes()))
    return out


def _fixture_ids() -> list[str]:
    return [name for name, _ in _all_fixture_buffers()]


@pytest.fixture(
    scope="module", params=_all_fixture_buffers(), ids=_fixture_ids(),
)
def fixture(request) -> tuple[str, FloorIR]:
    name, buf = request.param
    fir = FloorIR.GetRootAs(buf, 0)
    return name, fir


def _region_ids(fir: FloorIR) -> set[str]:
    out: set[str] = set()
    for i in range(fir.RegionsLength()):
        rid = fir.Regions(i).Id()
        if rid is not None:
            out.add(rid.decode("utf-8") if isinstance(rid, bytes) else rid)
    return out


def test_fixture_has_at_least_one_region(fixture) -> None:
    name, fir = fixture
    assert fir.RegionsLength() > 0, f"{name}: no regions"


def test_paint_op_material_family_in_range(fixture) -> None:
    name, fir = fixture
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.PaintOp:
            continue
        op = entry.Op()
        from nhc.rendering.ir._fb.PaintOp import PaintOp
        paint = PaintOp()
        paint.Init(op.Bytes, op.Pos)
        material = paint.Material()
        assert material is not None, f"{name} op {i}: missing material"
        assert material.Family() in _VALID_FAMILY_VALUES, (
            f"{name} op {i}: family {material.Family()} out of range"
        )


def test_stroke_op_wall_material_family_and_treatment_in_range(fixture) -> None:
    name, fir = fixture
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.StrokeOp:
            continue
        op = entry.Op()
        from nhc.rendering.ir._fb.StrokeOp import StrokeOp
        stroke = StrokeOp()
        stroke.Init(op.Bytes, op.Pos)
        wm = stroke.WallMaterial()
        assert wm is not None, f"{name} op {i}: missing wall_material"
        assert wm.Family() in _VALID_FAMILY_VALUES, (
            f"{name} op {i}: family {wm.Family()} out of range"
        )
        assert wm.Treatment() in _VALID_TREATMENT_VALUES, (
            f"{name} op {i}: treatment {wm.Treatment()} out of range"
        )


def test_paint_op_region_ref_resolves(fixture) -> None:
    name, fir = fixture
    region_ids = _region_ids(fir)
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.PaintOp:
            continue
        op = entry.Op()
        from nhc.rendering.ir._fb.PaintOp import PaintOp
        paint = PaintOp()
        paint.Init(op.Bytes, op.Pos)
        rr = paint.RegionRef()
        if rr is None or rr == b"" or rr == "":
            continue
        rr_str = rr.decode("utf-8") if isinstance(rr, bytes) else rr
        assert rr_str in region_ids, (
            f"{name} op {i}: PaintOp.region_ref={rr_str!r} not in regions"
        )


def test_stroke_op_region_ref_resolves_or_has_outline(fixture) -> None:
    """StrokeOp either references a region or carries an inline outline."""
    name, fir = fixture
    region_ids = _region_ids(fir)
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.StrokeOp:
            continue
        op = entry.Op()
        from nhc.rendering.ir._fb.StrokeOp import StrokeOp
        stroke = StrokeOp()
        stroke.Init(op.Bytes, op.Pos)
        rr = stroke.RegionRef()
        rr_str = (
            rr.decode("utf-8") if isinstance(rr, bytes)
            else (rr or "")
        )
        if rr_str:
            assert rr_str in region_ids, (
                f"{name} op {i}: StrokeOp.region_ref={rr_str!r} "
                "not in regions"
            )
        else:
            outline = stroke.Outline()
            assert outline is not None, (
                f"{name} op {i}: StrokeOp has no region_ref and no outline"
            )
