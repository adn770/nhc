"""Phase 1.22 — Region.outline parallel emission (schema 3.2).

Pins the contract of the v4e migration's first sub-phase:

* The IR schema bumps to ``minor == 2``.
* Every emitted Region carries an ``outline: Outline`` parallel to
  the legacy ``polygon: Polygon`` field.
* For polygon-kind regions (Dungeon / Cave / Room / Building / Site)
  the outline mirrors the source polygon: ``outline.vertices`` carries
  the same point list as ``polygon.paths``, and ``outline.rings``
  carries the multi-ring partitioning when (and only when) the
  polygon has more than one ring (single-ring outlines leave
  ``rings`` empty per ``design/map_ir_v4e.md`` §4).
* The Circle and Pill descriptor variants of ``Outline`` round-trip
  through FlatBuffers cleanly so the future per-shape Region
  emission for circle / pill rooms (1.23+) has a stable schema to
  ship.
* For fixtures with a multi-ring dungeon polygon (cave-wall holes
  or per-room subtractions), the ``Outline`` faithfully carries
  every ring with the matching ``is_hole`` flag.

No consumer behaviour change at 1.22 — every consumer continues
reading ``Region.polygon`` (parallel emission). 1.23 onwards starts
switching consumers to read ``region_ref`` and resolve through
``Region.outline``.
"""

from __future__ import annotations

import flatbuffers
import pytest

from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.PathRange import PathRangeT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.RegionKind import RegionKind
from nhc.rendering.ir._fb.Vec2 import Vec2T

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


# ── Helpers ────────────────────────────────────────────────────


@pytest.fixture(scope="module", params=all_descriptors())
def emitted(request):
    """Build each starter-fixture level once per module."""
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(request.param)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    return inputs, buf, fir


def _vec2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def _pack_floor_ir_with_region(region: RegionT) -> bytes:
    """Pack a minimal FloorIR carrying ``region`` for round-trip tests."""
    fir = FloorIRT()
    fir.major = 3
    fir.minor = 2
    fir.widthTiles = 16
    fir.heightTiles = 16
    fir.cell = 32
    fir.padding = 32
    fir.floorKind = 0
    fir.theme = "dungeon"
    fir.baseSeed = 0
    fir.regions = [region]
    fir.ops = []

    builder = flatbuffers.Builder(256)
    builder.Finish(fir.Pack(builder), b"NIR3")
    return bytes(builder.Output())


# ── Schema bump ────────────────────────────────────────────────


def test_schema_minor_is_2(emitted) -> None:
    """1.22: SCHEMA_MINOR bumps from 1 to 2 for the Region.outline addition."""
    _, _, fir = emitted
    assert fir.major == 3
    assert fir.minor == 2, (
        f"expected schema minor 2 (Phase 1.22), got {fir.minor}; "
        "the v4e migration's first sub-phase bumps SCHEMA_MINOR "
        "to mark the Region.outline addition. file_identifier "
        "stays NIR3 — the atomic NIR3 → NIR4 cut happens at 1.27."
    )


# ── Outline parallel population ────────────────────────────────


def test_every_region_has_an_outline(emitted) -> None:
    """1.22: every Region carries a populated outline parallel to polygon."""
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        assert region.outline is not None, (
            f"region {rid!r} is missing the new outline field. "
            "Phase 1.22 emits Region.outline parallel to "
            "Region.polygon for every region kind."
        )


def test_outline_vertices_mirror_polygon_paths(emitted) -> None:
    """Polygonal kinds: outline.vertices ≡ polygon.paths point-for-point."""
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        if region.outline.descriptorKind != OutlineKind.Polygon:
            continue
        if region.polygon is None or not region.polygon.paths:
            continue
        legacy = [(v.x, v.y) for v in region.polygon.paths]
        new = [(v.x, v.y) for v in (region.outline.vertices or [])]
        assert new == legacy, (
            f"region {rid!r}: outline.vertices ({len(new)} pts) does "
            f"not match polygon.paths ({len(legacy)} pts). The "
            "outline must mirror the polygon point-for-point."
        )


def test_outline_rings_match_polygon_rings_for_multiring(emitted) -> None:
    """Multi-ring polygons: outline.rings mirrors polygon.rings.

    Single-ring polygons leave outline.rings empty per v4e §4
    ("rings: [PathRange]; multi-ring partitioning; empty == single
    ring"). The legacy Polygon table uses a redundant 1-entry
    ``rings`` for single rings; the v4e Outline collapses that to
    the empty default.
    """
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        if region.outline.descriptorKind != OutlineKind.Polygon:
            continue
        if region.polygon is None:
            continue
        legacy_rings = list(region.polygon.rings or [])
        new_rings = list(region.outline.rings or [])
        if len(legacy_rings) <= 1:
            assert len(new_rings) == 0, (
                f"region {rid!r}: single-ring polygon should leave "
                f"outline.rings empty (v4e §4); got {len(new_rings)} "
                "ring entries."
            )
        else:
            assert len(new_rings) == len(legacy_rings), (
                f"region {rid!r}: multi-ring outline must mirror "
                f"every ring (got {len(new_rings)} new vs "
                f"{len(legacy_rings)} legacy)."
            )
            for i, (lr, nr) in enumerate(zip(legacy_rings, new_rings)):
                assert (nr.start, nr.count, nr.isHole) == (
                    lr.start, lr.count, lr.isHole,
                ), (
                    f"region {rid!r} ring {i}: outline ring "
                    f"({nr.start},{nr.count},hole={nr.isHole}) does "
                    f"not match polygon ring "
                    f"({lr.start},{lr.count},hole={lr.isHole})."
                )


def test_outline_closed_flag_is_true(emitted) -> None:
    """Region outlines are always closed (no open polylines at the region table)."""
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        assert region.outline.closed is True, (
            f"region {rid!r}: outline.closed must be True "
            "(open polylines belong on InteriorWallOp, not Region)."
        )


# ── Multi-ring Dungeon (cave-wall holes) ───────────────────────


def test_dungeon_region_outline_multi_ring_in_cave_fixture() -> None:
    """seed99_cave: Dungeon region's outline carries multi-ring partitioning.

    ``_shapely_to_polygon`` packs the dungeon polygon as a multi-
    ring shape: the exterior dungeon perimeter plus one or more
    cave-wall hole rings (or per-room cookie-cutter subtractions).
    The Outline must carry the same partitioning so future
    consumers reading ``Region.outline`` can render the multi-ring
    fill via FillRule::EvenOdd without falling back to the legacy
    polygon.paths field.
    """
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs("seed99_cave_cave_cave")
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    dungeon = next(
        (r for r in fir.regions
         if (r.id.decode() if isinstance(r.id, bytes) else r.id) == "dungeon"),
        None,
    )
    assert dungeon is not None, "seed99_cave is missing the dungeon Region"
    assert dungeon.outline.descriptorKind == OutlineKind.Polygon
    assert len(dungeon.outline.rings) >= 2, (
        "dungeon region in seed99_cave must carry ≥ 2 rings on "
        f"outline (exterior + cave hole(s)); got "
        f"{len(dungeon.outline.rings)}."
    )
    # At least one ring must be flagged as a hole — the cave-wall
    # interior holes drive the EvenOdd fill discipline.
    hole_count = sum(
        1 for r in dungeon.outline.rings if r.isHole
    )
    assert hole_count >= 1, (
        "dungeon region must mark at least one ring as a hole "
        "(cave-wall holes / per-room subtractions are the source "
        "of multi-ringness for dungeon polygons)."
    )


# ── Descriptor round-trip (Circle / Pill) ──────────────────────


def test_circle_descriptor_outline_round_trips() -> None:
    """A synthetic Region with a Circle-descriptor Outline encodes + decodes."""
    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Circle
    outline.closed = True
    outline.vertices = []
    outline.rings = []
    outline.cuts = []
    outline.cx = 256.0
    outline.cy = 256.0
    outline.rx = 96.0
    outline.ry = 96.0

    region = RegionT()
    region.id = "synthetic.circle"
    region.kind = RegionKind.Room
    region.polygon = None
    region.shapeTag = "circle"
    region.outline = outline

    buf = _pack_floor_ir_with_region(region)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.regions[0]
    assert decoded.outline.descriptorKind == OutlineKind.Circle
    assert decoded.outline.cx == pytest.approx(256.0)
    assert decoded.outline.cy == pytest.approx(256.0)
    assert decoded.outline.rx == pytest.approx(96.0)
    assert decoded.outline.ry == pytest.approx(96.0)
    assert (decoded.outline.vertices or []) == []


def test_pill_descriptor_outline_round_trips() -> None:
    """A synthetic Region with a Pill-descriptor Outline encodes + decodes."""
    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Pill
    outline.closed = True
    outline.vertices = []
    outline.rings = []
    outline.cuts = []
    outline.cx = 320.0
    outline.cy = 192.0
    outline.rx = 128.0
    outline.ry = 64.0

    region = RegionT()
    region.id = "synthetic.pill"
    region.kind = RegionKind.Room
    region.polygon = None
    region.shapeTag = "pill"
    region.outline = outline

    buf = _pack_floor_ir_with_region(region)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.regions[0]
    assert decoded.outline.descriptorKind == OutlineKind.Pill
    assert decoded.outline.cx == pytest.approx(320.0)
    assert decoded.outline.cy == pytest.approx(192.0)
    assert decoded.outline.rx == pytest.approx(128.0)
    assert decoded.outline.ry == pytest.approx(64.0)


def test_polygon_outline_with_multiring_round_trips() -> None:
    """A synthetic multi-ring Polygon outline encodes + decodes preserving rings."""
    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Polygon
    outline.closed = True
    outline.cuts = []
    outline.vertices = [
        # ring 0 — outer square
        _vec2(0.0, 0.0), _vec2(64.0, 0.0),
        _vec2(64.0, 64.0), _vec2(0.0, 64.0),
        # ring 1 — inner hole
        _vec2(16.0, 16.0), _vec2(16.0, 48.0),
        _vec2(48.0, 48.0), _vec2(48.0, 16.0),
    ]
    r0 = PathRangeT()
    r0.start, r0.count, r0.isHole = 0, 4, False
    r1 = PathRangeT()
    r1.start, r1.count, r1.isHole = 4, 4, True
    outline.rings = [r0, r1]

    region = RegionT()
    region.id = "synthetic.donut"
    region.kind = RegionKind.Dungeon
    region.polygon = None
    region.shapeTag = "polygon"
    region.outline = outline

    buf = _pack_floor_ir_with_region(region)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.regions[0].outline
    assert decoded.descriptorKind == OutlineKind.Polygon
    assert len(decoded.vertices) == 8
    assert len(decoded.rings) == 2
    assert (decoded.rings[0].start, decoded.rings[0].count,
            decoded.rings[0].isHole) == (0, 4, False)
    assert (decoded.rings[1].start, decoded.rings[1].count,
            decoded.rings[1].isHole) == (4, 4, True)
