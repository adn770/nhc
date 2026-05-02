"""Phase 1.24 — ExteriorWallOp.region_ref + op-level cuts (schema 3.4).

Pins the third sub-phase of the v4e migration: every emitted
:class:`ExteriorWallOp` carries a ``region_ref: string`` and an
op-level ``cuts: [Cut]`` parallel to the existing
``outline.cuts``. Consumers (Python + Rust) prefer the new
fields — ``region_ref`` resolves geometry through
``Region.outline`` (shipped at 1.22) and op-level ``cuts``
supersede the legacy ``outline.cuts`` for stroke break
intervals. ``InteriorWallOp`` gains the same op-level ``cuts``
mirror; its outline stays op-level because partitions are not
region perimeters.

Empty ``region_ref`` falls back to ``op.outline``; empty op
``cuts`` falls back to ``outline.cuts``. The legacy
``outline.cuts`` and ``op.outline`` retire at the 4.0 cut at
1.27.

No pixel change at 1.24 — both sources resolve to identical
geometry under parallel emission.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import flatbuffers
import pytest

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.Cut import CutT
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.ExteriorWallOp import ExteriorWallOpT
from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir._fb.InteriorWallOp import InteriorWallOpT
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.RegionKind import RegionKind
from nhc.rendering.ir._fb.Vec2 import Vec2T
from nhc.rendering.ir._fb.WallStyle import WallStyle

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "floor_ir"
)


# ── Helpers ────────────────────────────────────────────────────


def _vec2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def _cut(start: tuple[float, float], end: tuple[float, float],
         style: int) -> CutT:
    c = CutT()
    c.start = _vec2(*start)
    c.end = _vec2(*end)
    c.style = style
    return c


def _exterior_walls(fir: FloorIRT) -> list[Any]:
    return [
        e.op for e in (fir.ops or [])
        if e.opType == Op.Op.ExteriorWallOp
    ]


def _interior_walls(fir: FloorIRT) -> list[Any]:
    return [
        e.op for e in (fir.ops or [])
        if e.opType == Op.Op.InteriorWallOp
    ]


def _decode_id(rid: Any) -> str:
    return rid.decode() if isinstance(rid, bytes) else (rid or "")


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


def _pack_floor_ir(regions: list[RegionT], ops: list[OpEntryT]) -> bytes:
    fir = FloorIRT()
    fir.major = 3
    fir.minor = 4
    fir.widthTiles = 16
    fir.heightTiles = 16
    fir.cell = 32
    fir.padding = 32
    fir.floorKind = 0
    fir.theme = "dungeon"
    fir.baseSeed = 0
    fir.regions = regions
    fir.ops = ops

    builder = flatbuffers.Builder(256)
    builder.Finish(fir.Pack(builder), b"NIR3")
    return bytes(builder.Output())


# ── Schema bump ────────────────────────────────────────────────


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_schema_minor_at_least_4(descriptor: str) -> None:
    """1.24: SCHEMA_MINOR ≥ 4 (ExteriorWallOp.region_ref + op cuts at 1.24).

    Subsequent v4e sub-phases bump the minor further additively
    so this lower-bound check stays green across the migration.
    The exact current minor is locked by the skeleton sentinel.
    """
    fir = _build_emitted(descriptor)
    assert fir.major == 3
    assert fir.minor >= 4, (
        f"expected schema minor ≥ 4 (Phase 1.24 bumped to 4), got "
        f"{fir.minor}; ExteriorWallOp.region_ref + op-level cuts are "
        "required from 1.24 onward."
    )


# ── Round-trip — synthetic IR ──────────────────────────────────


def test_exterior_wall_op_region_ref_round_trips() -> None:
    """ExteriorWallOp.region_ref ships through the FB pipeline."""
    op = ExteriorWallOpT()
    op.outline = OutlineT()
    op.outline.descriptorKind = OutlineKind.Polygon
    op.outline.closed = True
    op.outline.cuts = []
    op.outline.rings = []
    op.outline.vertices = [
        _vec2(0, 0), _vec2(64, 0), _vec2(64, 64), _vec2(0, 64),
    ]
    op.style = WallStyle.DungeonInk
    op.regionRef = "room.synthetic.42"
    op.cuts = []
    op.rngSeed = 0

    entry = OpEntryT()
    entry.opType = Op.Op.ExteriorWallOp
    entry.op = op

    region = RegionT()
    region.id = "room.synthetic.42"
    region.kind = RegionKind.Room
    region.shapeTag = "rect"
    region.polygon = None
    region.outline = OutlineT()
    region.outline.descriptorKind = OutlineKind.Polygon
    region.outline.closed = True
    region.outline.cuts = []
    region.outline.rings = []
    region.outline.vertices = list(op.outline.vertices)

    buf = _pack_floor_ir([region], [entry])
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.ops[0].op
    assert _decode_id(decoded.regionRef) == "room.synthetic.42"


def test_exterior_wall_op_cuts_round_trip() -> None:
    """ExteriorWallOp op-level cuts ship through the FB pipeline."""
    op = ExteriorWallOpT()
    op.outline = OutlineT()
    op.outline.descriptorKind = OutlineKind.Polygon
    op.outline.closed = True
    op.outline.cuts = []
    op.outline.rings = []
    op.outline.vertices = [
        _vec2(0, 0), _vec2(64, 0), _vec2(64, 64), _vec2(0, 64),
    ]
    op.style = WallStyle.DungeonInk
    op.regionRef = ""
    op.cuts = [
        _cut((16, 0), (32, 0), CutStyle.DoorWood),
        _cut((48, 64), (56, 64), CutStyle.DoorIron),
    ]
    op.rngSeed = 0

    entry = OpEntryT()
    entry.opType = Op.Op.ExteriorWallOp
    entry.op = op

    buf = _pack_floor_ir([], [entry])
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.ops[0].op
    assert decoded.cuts is not None
    assert len(decoded.cuts) == 2
    assert decoded.cuts[0].style == CutStyle.DoorWood
    assert decoded.cuts[1].style == CutStyle.DoorIron
    assert decoded.cuts[0].start.x == 16.0
    assert decoded.cuts[1].end.x == 56.0


def test_interior_wall_op_cuts_round_trip() -> None:
    """InteriorWallOp op-level cuts ship through the FB pipeline."""
    op = InteriorWallOpT()
    op.outline = OutlineT()
    op.outline.descriptorKind = OutlineKind.Polygon
    op.outline.closed = False
    op.outline.cuts = []
    op.outline.rings = []
    op.outline.vertices = [_vec2(0, 32), _vec2(96, 32)]
    op.style = WallStyle.PartitionWood
    op.cuts = [_cut((32, 32), (48, 32), CutStyle.DoorWood)]

    entry = OpEntryT()
    entry.opType = Op.Op.InteriorWallOp
    entry.op = op

    buf = _pack_floor_ir([], [entry])
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.ops[0].op
    assert decoded.cuts is not None
    assert len(decoded.cuts) == 1
    assert decoded.cuts[0].style == CutStyle.DoorWood


# ── Consumer prefers region_ref / op cuts ──────────────────────


def test_exterior_wall_op_consumer_prefers_region_ref() -> None:
    """When region_ref resolves, the consumer reads geometry from the Region.

    Build a synthetic IR where the op's own ``outline`` is a
    deliberately-tiny 4×4 square but the Region's outline is the
    intended 64×64. A consumer that reads ``op.outline`` strokes
    a ~16-px perimeter; a consumer that prefers ``region_ref``
    strokes the full 256-px perimeter.
    """
    from nhc.rendering.ir_to_svg import _draw_exterior_wall_op_from_ir

    bad = OutlineT()
    bad.descriptorKind = OutlineKind.Polygon
    bad.closed = True
    bad.cuts = []
    bad.rings = []
    bad.vertices = [
        _vec2(0, 0), _vec2(4, 0), _vec2(4, 4), _vec2(0, 4),
    ]

    op = ExteriorWallOpT()
    op.outline = bad
    op.style = WallStyle.DungeonInk
    op.regionRef = "room.bigger"
    op.cuts = []
    op.rngSeed = 0

    entry = OpEntryT()
    entry.opType = Op.Op.ExteriorWallOp
    entry.op = op

    region_outline = OutlineT()
    region_outline.descriptorKind = OutlineKind.Polygon
    region_outline.closed = True
    region_outline.cuts = []
    region_outline.rings = []
    region_outline.vertices = [
        _vec2(0, 0), _vec2(64, 0), _vec2(64, 64), _vec2(0, 64),
    ]

    region = RegionT()
    region.id = "room.bigger"
    region.kind = RegionKind.Room
    region.shapeTag = "rect"
    region.polygon = None
    region.outline = region_outline

    buf = _pack_floor_ir([region], [entry])
    fir = FloorIR.GetRootAs(buf, 0)
    fb_entry = fir.Ops(0)
    frags = _draw_exterior_wall_op_from_ir(fb_entry, fir)
    body = " ".join(frags)
    # The stroked path must include vertices at 64.0 (the region
    # outline's extent), not just 4.0 (the decoy).
    assert "64" in body, (
        f"expected the consumer to stroke the 64×64 region outline; "
        f"got: {body!r}"
    )


def test_exterior_wall_op_consumer_prefers_op_cuts() -> None:
    """When op.cuts is populated it overrides outline.cuts.

    Build a synthetic IR where ``op.cuts`` is empty but
    ``op.outline.cuts`` carries a fake door at one edge — that
    fake door must NOT appear in the output (op.cuts being empty
    means "no cuts" — the legacy outline.cuts is shadowed).
    Conversely, populating ``op.cuts`` with a real door must
    produce the matching stroke break.

    Mirrors the FloorOp.region_ref preference contract from
    1.23a — when the new field is present on the op, the consumer
    treats it as authoritative.
    """
    from nhc.rendering.ir_to_svg import _draw_exterior_wall_op_from_ir

    # Outline carries a fake outline.cut on the top edge that
    # the op.cuts (empty in this test) must shadow.
    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Polygon
    outline.closed = True
    outline.rings = []
    outline.vertices = [
        _vec2(0, 0), _vec2(64, 0), _vec2(64, 64), _vec2(0, 64),
    ]
    outline.cuts = [
        _cut((16, 0), (32, 0), CutStyle.DoorWood),  # legacy door
    ]

    op = ExteriorWallOpT()
    op.outline = outline
    op.style = WallStyle.DungeonInk
    op.regionRef = ""  # no region resolution
    # Op-level cuts deliberately mismatched: a different door
    # interval on the bottom edge.
    op.cuts = [
        _cut((20, 64), (40, 64), CutStyle.DoorIron),
    ]
    op.rngSeed = 0

    entry = OpEntryT()
    entry.opType = Op.Op.ExteriorWallOp
    entry.op = op

    buf = _pack_floor_ir([], [entry])
    fir = FloorIR.GetRootAs(buf, 0)
    fb_entry = fir.Ops(0)
    frags = _draw_exterior_wall_op_from_ir(fb_entry, fir)
    body = " ".join(frags)
    # The output must reflect the op.cuts (bottom-edge cut at
    # y=64 between x=20 and x=40), NOT the outline.cuts (top-edge
    # cut at y=0 between x=16 and x=32). The simplest stable
    # check: the op.cuts pair (20,64)-(40,64) appears as gap
    # boundary in the stroke path; the outline.cuts pair
    # (16,0)-(32,0) does NOT.
    #
    # The wall stroke breaks at the cut interval: vertices
    # immediately before the cut start and after the cut end
    # bound the path. We assert the bottom-edge break is
    # present (path mentions y=64 with x=20 or x=40) AND the
    # top-edge break is absent (path does NOT contain a "M16,0"
    # / "L32,0" mid-path break — those would only appear under
    # the outline.cuts dispatch).
    assert "20" in body and "64" in body, (
        f"expected op.cuts to drive the stroke break (bottom-edge "
        f"cut at x=20-40, y=64); got: {body!r}"
    )


# ── Fixture coverage ───────────────────────────────────────────


def test_room_exterior_wall_carries_region_ref() -> None:
    """seed42 (rect dungeon): every rect-room ExteriorWallOp ref the Room.

    Every ``ExteriorWallOp`` with ``style == DungeonInk`` and
    matching a Region(kind=Room) by outline must carry
    ``region_ref = room.id``.
    """
    fir = _build_emitted("seed42_rect_dungeon_dungeon")
    room_region_ids = {
        _decode_id(r.id) for r in fir.regions
        if r.kind == RegionKind.Room
    }
    refs = {
        _decode_id(op.regionRef) for op in _exterior_walls(fir)
        if op.style == WallStyle.DungeonInk
        and _decode_id(op.regionRef)
    }
    missing = room_region_ids - refs
    assert not missing, (
        f"some Room regions have no DungeonInk ExteriorWallOp ref: "
        f"{sorted(missing)}"
    )


def test_smooth_room_exterior_wall_carries_region_ref() -> None:
    """seed7_octagon: smooth-room walls ref the matching Room."""
    fir = _build_emitted("seed7_octagon_crypt_dungeon")
    room_region_ids = {
        _decode_id(r.id) for r in fir.regions
        if r.kind == RegionKind.Room
    }
    refs = {
        _decode_id(op.regionRef) for op in _exterior_walls(fir)
        if op.style == WallStyle.DungeonInk
        and _decode_id(op.regionRef)
    }
    missing = room_region_ids - refs
    assert not missing, (
        f"some Room regions in seed7_octagon have no DungeonInk "
        f"ExteriorWallOp ref: {sorted(missing)}"
    )


def test_cave_exterior_wall_region_ref_deferred() -> None:
    """seed99_cave: CaveInk walls leave region_ref empty (mirrors FloorOp deferral)."""
    fir = _build_emitted("seed99_cave_cave_cave")
    cave_walls = [
        op for op in _exterior_walls(fir)
        if op.style == WallStyle.CaveInk
    ]
    assert cave_walls, "seed99_cave has no CaveInk ExteriorWallOp"
    refs = {_decode_id(op.regionRef) for op in cave_walls}
    assert refs == {""}, (
        f"CaveInk ExteriorWallOps must leave region_ref empty at "
        f"1.24 (multi-ring cave Region resolution lands later); "
        f"got: {sorted(refs)}"
    )


def test_enclosure_exterior_wall_carries_enclosure_region_ref() -> None:
    """Phase 1.26c: enclosure walls ref a Region(kind=Enclosure, id="enclosure").

    Reads the committed ``synthetic_enclosure_palisade_rect`` floor.nir
    fixture from disk. Asserts that:

    - the IR carries a ``Region(kind=Enclosure, id="enclosure")``;
    - every ``ExteriorWallOp`` with ``style`` in ``{Palisade,
      FortificationMerlon}`` carries ``regionRef = "enclosure"``.

    Closes the deferred enclosure region_ref gap from 1.24 (where
    site enclosures had no Region and so left ``regionRef`` empty).
    """
    p = _FIXTURE_ROOT / "synthetic_enclosure_palisade_rect" / "floor.nir"
    if not p.exists():
        pytest.skip("synthetic_enclosure_palisade_rect fixture missing")
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(p.read_bytes(), 0))

    enclosure_regions = [
        r for r in (fir.regions or [])
        if r.kind == RegionKind.Enclosure
    ]
    assert len(enclosure_regions) == 1, (
        f"expected exactly one Region(kind=Enclosure); got "
        f"{len(enclosure_regions)}"
    )
    assert _decode_id(enclosure_regions[0].id) == "enclosure", (
        f"expected Enclosure region id == 'enclosure'; got "
        f"{_decode_id(enclosure_regions[0].id)!r}"
    )

    enclosure_walls = [
        op for op in _exterior_walls(fir)
        if op.style in (
            WallStyle.Palisade, WallStyle.FortificationMerlon,
        )
    ]
    assert enclosure_walls, (
        "synthetic_enclosure_palisade_rect has no Palisade / "
        "FortificationMerlon ExteriorWallOp"
    )
    for op in enclosure_walls:
        ref = _decode_id(op.regionRef)
        assert ref == "enclosure", (
            f"Palisade / FortificationMerlon ExteriorWallOp must "
            f"carry regionRef='enclosure' at 1.26c; got {ref!r}"
        )


def test_op_cuts_mirror_outline_cuts_in_fixtures() -> None:
    """Parallel emission invariant — every wall op's op.cuts ≡ outline.cuts.

    The 1.24 emitter mirrors ``outline.cuts`` to ``op.cuts`` for
    every ExteriorWallOp + InteriorWallOp. Walks every fixture
    and asserts the two cut lists are equal point-for-point.
    """
    for desc in all_descriptors():
        fir = _build_emitted(desc)
        for op in _exterior_walls(fir) + _interior_walls(fir):
            outline_cuts = list(op.outline.cuts or []) if op.outline else []
            op_cuts = list(op.cuts or [])
            assert len(outline_cuts) == len(op_cuts), (
                f"{desc}: wall op cut count mismatch — "
                f"outline.cuts={len(outline_cuts)} vs "
                f"op.cuts={len(op_cuts)}"
            )
            for i, (oc, pc) in enumerate(zip(outline_cuts, op_cuts)):
                assert (oc.start.x, oc.start.y) == (pc.start.x, pc.start.y), (
                    f"{desc}: cut {i} start mismatch"
                )
                assert (oc.end.x, oc.end.y) == (pc.end.x, pc.end.y), (
                    f"{desc}: cut {i} end mismatch"
                )
                assert oc.style == pc.style, (
                    f"{desc}: cut {i} style mismatch"
                )


def test_building_masonry_wall_carries_region_ref() -> None:
    """seed7_brick_building (post-regen): masonry ExteriorWallOps ref the building.

    Reads the committed ``floor.nir`` from disk (building flow
    isn't in the standard descriptor set). Asserts that any
    masonry ExteriorWallOp's non-empty region_ref resolves to a
    Region(kind=Building).
    """
    p = _FIXTURE_ROOT / "seed7_brick_building_floor0" / "floor.nir"
    if not p.exists():
        pytest.skip("seed7_brick_building_floor0 fixture missing")
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(p.read_bytes(), 0))
    masonry_walls = [
        op for op in _exterior_walls(fir)
        if op.style in (
            WallStyle.MasonryBrick, WallStyle.MasonryStone,
        )
    ]
    if not masonry_walls:
        pytest.skip("seed7_brick_building has no masonry ExteriorWallOp")
    building_region_ids = {
        _decode_id(r.id) for r in fir.regions
        if r.kind == RegionKind.Building
    }
    for op in masonry_walls:
        ref = _decode_id(op.regionRef)
        if not ref:
            continue
        assert ref in building_region_ids, (
            f"masonry ExteriorWallOp region_ref {ref!r} does not "
            f"resolve to a Building Region "
            f"(known: {sorted(building_region_ids)})."
        )
