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
    fir.major = 4
    fir.minor = 0
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
    builder.Finish(fir.Pack(builder), b"NIR4")
    return bytes(builder.Output())


# ── Schema bump ────────────────────────────────────────────────


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_schema_major_is_4(descriptor: str) -> None:
    """NIR4: SCHEMA_MAJOR = 4. Replaces the pre-cut minor-≥-4 sentinel."""
    fir = _build_emitted(descriptor)
    assert fir.major == 4, f"expected major=4, got {fir.major}"


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


# NIR4: test_exterior_wall_op_consumer_prefers_op_cuts deleted —
# Outline.cuts retired from the schema; op.cuts is the only
# canonical source for stroke break intervals (no parallel emission
# to test "preference" between).


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


def test_cave_exterior_wall_carries_cave_region_ref() -> None:
    """seed99_cave: CaveInk walls ref a per-system Region(kind=Cave).

    Phase 1.26b mirror of the cave FloorOp realignment. Each cave
    ExteriorWallOp (``style=CaveInk``) emits with
    ``regionRef = "cave.<i>"`` for the i-th disjoint cave system.
    The matching Region carries an outline whose vertices mirror
    the ExteriorWallOp's outline vertex-for-vertex (both come from
    ``_cave_raw_exterior_coords(tile_group)``).
    """
    fir = _build_emitted("seed99_cave_cave_cave")
    cave_walls = [
        op for op in _exterior_walls(fir)
        if op.style == WallStyle.CaveInk
    ]
    assert cave_walls, "seed99_cave has no CaveInk ExteriorWallOp"

    cave_regions = {
        _decode_id(r.id): r for r in (fir.regions or [])
        if r.kind == RegionKind.Cave
    }
    assert cave_regions, "seed99_cave has no Region(kind=Cave)"

    for op in cave_walls:
        ref = _decode_id(op.regionRef)
        assert ref.startswith("cave."), (
            f"CaveInk ExteriorWallOp.regionRef must follow "
            f"'cave.<i>' format; got {ref!r}"
        )
        region = cave_regions.get(ref)
        assert region is not None, (
            f"CaveInk ExteriorWallOp.regionRef={ref!r} does not "
            f"resolve; known cave regions: {sorted(cave_regions)}"
        )
        # NIR4: ExteriorWallOp.outline retired structurally.
        assert region.outline is not None
        region_vs = [(v.x, v.y) for v in (region.outline.vertices or [])]
        assert region_vs and len(region_vs) >= 4, (
            f"Region(kind=Cave).outline must carry the cave system "
            f"boundary; got {len(region_vs)} vertices."
        )


@pytest.mark.skip(
    reason="NIR4: committed fixture .nir files still carry the NIR3 "
    "file_identifier; fixture regeneration is task #10."
)
def test_enclosure_exterior_wall_carries_enclosure_region_ref() -> None:
    """Phase 1.26c: enclosure walls ref a Region(kind=Enclosure, id="enclosure").
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


def test_op_cuts_canonical_when_outline_retired() -> None:
    """NIR4: ExteriorWallOp ships ``cuts`` only via op-level ``op.cuts``
    (outline.cuts retired with the schema cut). InteriorWallOp keeps
    its op-level outline + cuts.
    """
    for desc in all_descriptors():
        fir = _build_emitted(desc)
        for op in _exterior_walls(fir):
            assert not hasattr(op, "outline") or op.outline is None, (
                f"{desc}: ExteriorWallOp.outline must not be set "
                "(retired in NIR4 schema)."
            )
        for op in _interior_walls(fir):
            # InteriorWallOp keeps op.outline; cuts live op-level.
            assert op.outline is not None
            assert not hasattr(op.outline, "cuts") or (
                op.outline.cuts is None or list(op.outline.cuts) == []
            ), f"{desc}: InteriorWallOp.outline.cuts retired in NIR4"


@pytest.mark.skip(
    reason="NIR4: committed fixture .nir files still carry the NIR3 "
    "file_identifier; fixture regeneration is task #10."
)
def test_building_masonry_wall_carries_region_ref() -> None:
    """seed7_brick_building (post-regen): masonry ExteriorWallOps ref the building.
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


# ── Phase 1.26e-1 — _smooth_corridor_stubs bypass-reader tests ──


def test_smooth_corridor_stubs_prefers_region_ref_over_op_outline() -> None:
    """_smooth_corridor_stubs must dispatch through region_ref + op.cuts.

    Phase 1.26e-1: this helper derives wall-extension fragments
    from None_ cuts on smooth DungeonInk ExteriorWallOps. Pre-
    1.26e-1 it bypassed region_ref (read ``op.outline``) and
    op.cuts (read ``outline.cuts``) — that bypass had to disappear
    before 1.26e-2 could drop ``ExteriorWallOp.outline`` populating
    for ops with region_ref.

    Test: the op carries a 4×4 decoy outline + a wrong outline.cuts
    entry, while the Region carries the real 8-vertex octagon outline
    and op.cuts carries the real None_ corridor opening. A bypass
    reader returns an empty extension list (4×4 decoy has no smooth
    edges); a region_ref + op.cuts reader returns 2 stubs (one per
    cut endpoint).
    """
    from nhc.rendering.ir._fb.FloorIR import FloorIR
    from nhc.rendering.ir_to_svg import _smooth_corridor_stubs

    # Decoy outline on the op: 4×4 box (degenerate for stub derivation —
    # too small for a "smooth" classification, no octagon edges).
    bad_outline = OutlineT()
    bad_outline.descriptorKind = OutlineKind.Polygon
    bad_outline.closed = True
    bad_outline.rings = []
    bad_outline.vertices = [
        _vec2(0, 0), _vec2(4, 0), _vec2(4, 4), _vec2(0, 4),
    ]
    # Decoy outline cut on the wrong location. A bypass-reader would
    # mistake this for a corridor opening.
    bad_outline.cuts = [
        _cut((0, 0), (4, 0), CutStyle.None_),  # decoy on top edge
    ]

    op = ExteriorWallOpT()
    op.outline = bad_outline
    op.style = WallStyle.DungeonInk
    op.regionRef = "room.octagon"
    # Real op.cuts: corridor opening on the octagon's right edge.
    op.cuts = [
        _cut((1216, 192), (1216, 224), CutStyle.None_),
    ]
    op.rngSeed = 0

    entry = OpEntryT()
    entry.opType = Op.Op.ExteriorWallOp
    entry.op = op

    # Real outline on the Region: octagon from seed7 ExtWallOp[14].
    region_outline = OutlineT()
    region_outline.descriptorKind = OutlineKind.Polygon
    region_outline.closed = True
    region_outline.cuts = []
    region_outline.rings = []
    region_outline.vertices = [
        _vec2(1088, 96), _vec2(1152, 96), _vec2(1216, 160),
        _vec2(1216, 224), _vec2(1152, 288), _vec2(1088, 288),
        _vec2(1024, 224), _vec2(1024, 160),
    ]

    region = RegionT()
    region.id = "room.octagon"
    region.kind = RegionKind.Room
    region.shapeTag = "octagon"
    region.polygon = None
    region.outline = region_outline

    buf = _pack_floor_ir([region], [entry])
    fir = FloorIR.GetRootAs(buf, 0)
    stubs = _smooth_corridor_stubs(fir)

    # The op.cuts cut at right edge (1216,192)–(1216,224) projects
    # outward (perpendicular into the corridor) producing two
    # extension stubs at the cut endpoints. Bypass reader yields
    # zero stubs (decoy 4×4 outline has no matching None_ cut on
    # the right edge).
    assert len(stubs) == 2, (
        f"expected 2 stubs from the op.cuts None_ cut on the "
        f"region's right edge; got {len(stubs)} stubs: {stubs}. "
        "_smooth_corridor_stubs must read the Region's outline + "
        "op.cuts, not the op's decoy outline.cuts."
    )
    # Stubs extend perpendicular outward from the cut endpoints.
    expected = {
        "M1216.0,192.0 L1248.0,192.0",
        "M1216.0,224.0 L1248.0,224.0",
    }
    assert set(stubs) == expected, (
        f"stub coords mismatch — expected the right-edge "
        f"perpendicular extensions {expected}; got {set(stubs)}."
    )


# ── Phase 1.26e-2b — ExteriorWallOp.outline retired when region_ref set ──


# NIR4: tests pinning "ExteriorWallOp.outline dropped when region_ref
# set" deleted — the schema cut removed `outline` from ExteriorWallOp
# entirely (the OpT class has no outline attribute), so structural
# enforcement replaces these regression tests.


# NIR4: tests pinning "ExteriorWallOp.outline dropped when region_ref
# set" deleted — the schema cut removed `outline` from ExteriorWallOp
# entirely, so structural enforcement replaces these regression tests.
# (Tests for enclosure / building / brick_with_interior fixtures also
# loaded NIR3 .nir files which need regeneration — task #10.)
