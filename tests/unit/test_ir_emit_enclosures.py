"""Phase 1.14 — enclosure ExteriorWallOp + cuts_for_enclosure_gates.

Tests for the parallel ExteriorWallOp emission alongside the legacy
EnclosureOp for palisade / fortification enclosures, and for the
cuts_for_enclosure_gates helper that resolves (edge_idx, t_center,
half_px) gate triples to pixel-space (start, end) Cut pairs.

All tests follow the TDD cadence in plans/nhc_pure_ir_plan.md §1.14:
tests were written before the implementation was added, ran red, then
the implementation was added to make them pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.EnclosureStyle import EnclosureStyle
from nhc.rendering.ir._fb.GateStyle import GateStyle
from nhc.rendering.ir._fb.WallStyle import WallStyle
from nhc.rendering.ir_emitter import (
    FloorIRBuilder,
    emit_site_enclosure,
    emit_site_region,
)


@dataclass
class _StubLevel:
    width: int = 32
    height: int = 32


@dataclass
class _StubCtx:
    level: _StubLevel | None = None
    seed: int = 0
    theme: str = "dungeon"
    floor_kind: str = "surface"
    shadows_enabled: bool = True
    hatching_enabled: bool = True
    atmospherics_enabled: bool = True
    macabre_detail: bool = False
    vegetation_enabled: bool = True
    interior_finish: str = ""


# ── cuts_for_enclosure_gates helper ───────────────────────────────


def test_cuts_for_enclosure_gates_resolves_pixel_coords() -> None:
    """A gate at edge 0 (t=0.5, half_px=32) on a 4-vertex rect polygon
    resolves to (start, end) at the midpoint of the first edge, each
    shifted ±32px along the edge direction.

    Polygon: (64, 64) → (640, 64) → (640, 448) → (64, 448)
    Edge 0: from (64, 64) to (640, 64), horizontal, length 576px.
    Gate center at t=0.5: (352, 64). Half_px=32: start=(320,64),
    end=(384,64).
    """
    from nhc.rendering._outline_helpers import cuts_for_enclosure_gates

    polygon_px = [
        (64.0, 64.0),
        (640.0, 64.0),
        (640.0, 448.0),
        (64.0, 448.0),
    ]
    gates = [(0, 0.5, 32.0)]
    cuts = cuts_for_enclosure_gates(polygon_px, gates, GateStyle.Wood)

    assert len(cuts) == 1
    cut = cuts[0]
    assert cut.style == CutStyle.WoodGate
    # Edge 0 is horizontal (y==64); start is at x=320, end at x=384.
    assert math.isclose(cut.start.x, 320.0)
    assert math.isclose(cut.start.y, 64.0)
    assert math.isclose(cut.end.x, 384.0)
    assert math.isclose(cut.end.y, 64.0)


def test_cuts_for_enclosure_gates_portcullis_maps_to_portculligate() -> None:
    """GateStyle.Portcullis resolves to CutStyle.PortcullisGate."""
    from nhc.rendering._outline_helpers import cuts_for_enclosure_gates

    polygon_px = [
        (0.0, 0.0),
        (256.0, 0.0),
        (256.0, 256.0),
        (0.0, 256.0),
    ]
    gates = [(0, 0.5, 16.0)]
    cuts = cuts_for_enclosure_gates(polygon_px, gates, GateStyle.Portcullis)

    assert len(cuts) == 1
    assert cuts[0].style == CutStyle.PortcullisGate


def test_cuts_for_enclosure_gates_vertical_edge() -> None:
    """A gate on a vertical edge (edge 1) resolves to vertical cut
    coords at the correct x offset.

    Polygon: (0,0) → (256,0) → (256,256) → (0,256)
    Edge 1: from (256,0) to (256,256), vertical, length 256px.
    Gate center at t=0.5: (256, 128). Half_px=16: start=(256,112),
    end=(256,144).
    """
    from nhc.rendering._outline_helpers import cuts_for_enclosure_gates

    polygon_px = [
        (0.0, 0.0),
        (256.0, 0.0),
        (256.0, 256.0),
        (0.0, 256.0),
    ]
    gates = [(1, 0.5, 16.0)]
    cuts = cuts_for_enclosure_gates(polygon_px, gates, GateStyle.Wood)

    assert len(cuts) == 1
    cut = cuts[0]
    assert math.isclose(cut.start.x, 256.0)
    assert math.isclose(cut.start.y, 112.0)
    assert math.isclose(cut.end.x, 256.0)
    assert math.isclose(cut.end.y, 144.0)


def test_cuts_for_enclosure_gates_multiple_gates() -> None:
    """Multiple gates on different edges each emit a separate Cut."""
    from nhc.rendering._outline_helpers import cuts_for_enclosure_gates

    polygon_px = [
        (0.0, 0.0),
        (320.0, 0.0),
        (320.0, 320.0),
        (0.0, 320.0),
    ]
    gates = [(0, 0.5, 16.0), (2, 0.5, 16.0)]
    cuts = cuts_for_enclosure_gates(polygon_px, gates, GateStyle.Wood)

    assert len(cuts) == 2
    assert all(c.style == CutStyle.WoodGate for c in cuts)


def test_cuts_for_enclosure_gates_empty_gates() -> None:
    """No gates → empty cut list."""
    from nhc.rendering._outline_helpers import cuts_for_enclosure_gates

    polygon_px = [(0.0, 0.0), (128.0, 0.0), (128.0, 128.0), (0.0, 128.0)]
    cuts = cuts_for_enclosure_gates(polygon_px, [], GateStyle.Wood)
    assert cuts == []


# ── emit_site_enclosure ExteriorWallOp parallel emission ──────────


def _make_builder() -> FloorIRBuilder:
    return FloorIRBuilder(
        _StubCtx(level=_StubLevel())  # type: ignore[arg-type]
    )


def _ext_wall_ops(builder: FloorIRBuilder) -> list:
    from nhc.rendering.ir._fb import Op
    return [e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp]


def test_palisade_emits_exterior_wall_op_alongside_enclosure_op() -> None:
    """Palisade enclosure produces one EnclosureOp AND one ExteriorWallOp."""
    from nhc.rendering.ir._fb import Op

    builder = _make_builder()
    emit_site_enclosure(
        builder,
        polygon_tiles=[(2, 2), (20, 2), (20, 14), (2, 14)],
        style=EnclosureStyle.Palisade,
        gates=None,
        base_seed=7,
    )

    enclosure_ops = [
        e for e in builder.ops if e.opType == Op.Op.EnclosureOp
    ]
    ext_ops = _ext_wall_ops(builder)
    assert len(enclosure_ops) == 1, "legacy EnclosureOp must still emit"
    assert len(ext_ops) == 1, "new ExteriorWallOp must emit alongside"


def test_fortification_emits_exterior_wall_op_with_fortmerlon_style() -> None:
    """Fortification enclosure ExteriorWallOp carries WallStyle.FortificationMerlon."""
    builder = _make_builder()
    emit_site_enclosure(
        builder,
        polygon_tiles=[(2, 2), (20, 2), (20, 14), (2, 14)],
        style=EnclosureStyle.Fortification,
        gates=None,
        base_seed=7,
        corner_style=CornerStyle.Merlon,
    )

    ext_ops = _ext_wall_ops(builder)
    assert len(ext_ops) == 1
    assert ext_ops[0].op.style == WallStyle.FortificationMerlon


def test_palisade_exterior_wall_op_has_palisade_style() -> None:
    """Palisade enclosure ExteriorWallOp carries WallStyle.Palisade."""
    builder = _make_builder()
    emit_site_enclosure(
        builder,
        polygon_tiles=[(0, 0), (8, 0), (8, 8), (0, 8)],
        style=EnclosureStyle.Palisade,
        gates=None,
        base_seed=0,
    )

    ext_ops = _ext_wall_ops(builder)
    assert len(ext_ops) == 1
    assert ext_ops[0].op.style == WallStyle.Palisade


def test_enclosure_corner_style_preserved_on_exterior_wall_op() -> None:
    """CornerStyle from the source enclosure passes through to ExteriorWallOp."""
    for cs in (CornerStyle.Merlon, CornerStyle.Diamond, CornerStyle.Tower):
        builder = _make_builder()
        emit_site_enclosure(
            builder,
            polygon_tiles=[(2, 2), (20, 2), (20, 14), (2, 14)],
            style=EnclosureStyle.Fortification,
            gates=None,
            base_seed=7,
            corner_style=cs,
        )
        ext_ops = _ext_wall_ops(builder)
        assert len(ext_ops) == 1
        assert ext_ops[0].op.cornerStyle == cs, (
            f"cornerStyle {cs} not preserved on ExteriorWallOp"
        )


def test_wood_gate_resolves_to_woodgate_cut_at_edge_midpoint() -> None:
    """Wood gate on edge 0 → ExteriorWallOp outline has one WoodGate Cut
    at the midpoint of the first polygon edge in pixel space."""
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    builder = _make_builder()
    # polygon_tiles: (2,2) → (20,2) → (20,14) → (2,14)
    # Edge 0 in pixel space: (64,64) → (640,64), horizontal 576px.
    # Gate (edge_idx=0, t=0.5, half_px=32.0):
    #   center=(352,64), start=(320,64), end=(384,64).
    emit_site_enclosure(
        builder,
        polygon_tiles=[(2, 2), (20, 2), (20, 14), (2, 14)],
        style=EnclosureStyle.Palisade,
        gates=[(0, 0.5, 32.0)],
        base_seed=7,
    )

    ext_ops = _ext_wall_ops(builder)
    assert len(ext_ops) == 1
    outline = ext_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Polygon
    assert outline.closed is True
    cuts = outline.cuts
    assert len(cuts) == 1
    cut = cuts[0]
    assert cut.style == CutStyle.WoodGate
    # Edge 0: (2*32, 2*32) → (20*32, 2*32) = (64, 64) → (640, 64)
    # t=0.5 → center=(352, 64), half_px=32 → start=(320,64), end=(384,64)
    assert math.isclose(cut.start.x, 320.0)
    assert math.isclose(cut.start.y, 64.0)
    assert math.isclose(cut.end.x, 384.0)
    assert math.isclose(cut.end.y, 64.0)


def test_portcullis_gate_resolves_to_portcullisgate_cut() -> None:
    """Portcullis gate_style → ExteriorWallOp outline cut has PortcullisGate style."""
    builder = _make_builder()
    emit_site_enclosure(
        builder,
        polygon_tiles=[(0, 0), (8, 0), (8, 8), (0, 8)],
        style=EnclosureStyle.Fortification,
        gates=[(0, 0.5, 16.0)],
        base_seed=0,
        gate_style=GateStyle.Portcullis,
    )

    ext_ops = _ext_wall_ops(builder)
    assert len(ext_ops) == 1
    cuts = ext_ops[0].op.outline.cuts
    assert len(cuts) == 1
    assert cuts[0].style == CutStyle.PortcullisGate


def test_exterior_wall_op_count_matches_enclosure_op_count() -> None:
    """One ExteriorWallOp emitted per EnclosureOp (1:1 parallel emission)."""
    from nhc.rendering.ir._fb import Op

    builder = _make_builder()
    emit_site_enclosure(
        builder,
        polygon_tiles=[(2, 2), (20, 2), (20, 14), (2, 14)],
        style=EnclosureStyle.Palisade,
        gates=None,
        base_seed=7,
    )

    enc_count = sum(
        1 for e in builder.ops if e.opType == Op.Op.EnclosureOp
    )
    ext_count = sum(
        1 for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
    )
    assert ext_count == enc_count


def test_too_few_vertices_emits_no_exterior_wall_op() -> None:
    """Degenerate polygon (< 3 vertices) skips both ops including the new one."""
    builder = _make_builder()
    emit_site_enclosure(
        builder,
        polygon_tiles=[(0, 0), (1, 0)],  # degenerate
        style=EnclosureStyle.Palisade,
        base_seed=0,
    )
    assert builder.ops == []


def test_exterior_wall_op_outline_vertices_match_polygon_px() -> None:
    """ExteriorWallOp.outline.vertices are the enclosure polygon in bare
    tile-pixel coords (tile * CELL, no PADDING baked in)."""
    from nhc.rendering._svg_helpers import CELL

    builder = _make_builder()
    polygon_tiles = [(2, 2), (20, 2), (20, 14), (2, 14)]
    emit_site_enclosure(
        builder,
        polygon_tiles=polygon_tiles,
        style=EnclosureStyle.Palisade,
        gates=None,
        base_seed=7,
    )

    ext_ops = _ext_wall_ops(builder)
    assert len(ext_ops) == 1
    verts = ext_ops[0].op.outline.vertices
    assert len(verts) == 4
    for v, (tx, ty) in zip(verts, polygon_tiles):
        assert math.isclose(v.x, tx * CELL)
        assert math.isclose(v.y, ty * CELL)


def test_exterior_wall_op_emitted_after_enclosure_op() -> None:
    """ExteriorWallOp appears AFTER EnclosureOp in ops[] to preserve
    the 1.16+ consumer-switch invariant (new op lands after legacy op)."""
    from nhc.rendering.ir._fb import Op

    builder = _make_builder()
    emit_site_enclosure(
        builder,
        polygon_tiles=[(2, 2), (20, 2), (20, 14), (2, 14)],
        style=EnclosureStyle.Palisade,
        gates=None,
        base_seed=7,
    )

    enc_idx = next(
        i for i, e in enumerate(builder.ops)
        if e.opType == Op.Op.EnclosureOp
    )
    ext_idx = next(
        i for i, e in enumerate(builder.ops)
        if e.opType == Op.Op.ExteriorWallOp
    )
    assert ext_idx > enc_idx, (
        "ExteriorWallOp must follow EnclosureOp in ops[]"
    )
