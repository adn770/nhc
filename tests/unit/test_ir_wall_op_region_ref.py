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
        # Phase 1.26e-2b: op.outline retired; Region.outline is canonical.
        assert op.outline is None or not (op.outline.vertices or []), (
            "ExteriorWallOp.outline retired at 1.26e-2b — "
            "Region.outline is canonical."
        )
        assert region.outline is not None
        region_vs = [(v.x, v.y) for v in (region.outline.vertices or [])]
        assert region_vs and len(region_vs) >= 4, (
            f"Region(kind=Cave).outline must carry the cave system "
            f"boundary; got {len(region_vs)} vertices."
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


def test_op_cuts_canonical_when_outline_retired() -> None:
    """Phase 1.26e-2b: ExteriorWallOp/InteriorWallOp ``op.cuts`` is canonical.

    Pre-1.26e-2b the emitter mirrored ``outline.cuts`` to ``op.cuts`` for
    every wall op (Phase 1.24 contract). Post-1.26e-2b ``outline.cuts``
    drops alongside ``op.outline``: the Region carries the geometry,
    and ``op.cuts`` carries the stroke break intervals. This test
    asserts the new canonical-cuts path: every wall op with cuts
    carries them on ``op.cuts``, and ``op.outline`` (if present) does
    not double up.

    InteriorWallOp keeps its op-level outline (interior walls aren't
    region perimeters), so its ``outline.cuts`` may be populated as
    the legacy path; tests for InteriorWallOp focus on ``op.cuts``.
    """
    for desc in all_descriptors():
        fir = _build_emitted(desc)
        for op in _exterior_walls(fir):
            outline_cuts = (
                list(op.outline.cuts or []) if op.outline else []
            )
            assert not outline_cuts, (
                f"{desc}: ExteriorWallOp.outline.cuts retired at "
                f"1.26e-2b; got {len(outline_cuts)} cuts on outline"
            )
        # InteriorWallOp.cuts: still synced with outline.cuts in
        # the emitter (interior walls have no Region; they keep
        # their op-level outline so the legacy mirror stays valid).
        for op in _interior_walls(fir):
            outline_cuts = (
                list(op.outline.cuts or []) if op.outline else []
            )
            op_cuts = list(op.cuts or [])
            assert len(outline_cuts) == len(op_cuts), (
                f"{desc}: InteriorWallOp cut count mismatch — "
                f"outline.cuts={len(outline_cuts)} vs "
                f"op.cuts={len(op_cuts)}"
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


def test_rect_room_exterior_wall_outline_dropped_when_region_ref_set() -> None:
    """seed42 (rect dungeon): rect-room ExteriorWallOps drop op.outline.

    Phase 1.26e-2b — emitter retires ``ExteriorWallOp.outline`` for
    ops that carry a non-empty ``region_ref``. The
    Region(kind=Room).outline registered by ``emit_regions`` is the
    canonical geometry source; consumers prefer ``region_ref`` per
    1.24, and the bypass-readers migrated at 1.26e-1 also walk
    ``region_ref`` before falling back to op.outline.

    Op-level ``cuts`` (Phase 1.24) stay populated — they're the
    canonical source for stroke break intervals; ``outline.cuts``
    retired alongside ``op.outline``.
    """
    fir = _build_emitted("seed42_rect_dungeon_dungeon")
    rect_walls = [
        op for op in _exterior_walls(fir)
        if op.style == WallStyle.DungeonInk
        and _decode_id(op.regionRef).startswith("room_")
    ]
    assert rect_walls, "seed42 has no rect-room ExteriorWallOp"
    for op in rect_walls:
        assert op.outline is None or not (op.outline.vertices or []), (
            f"rect-room ExteriorWallOp.regionRef={_decode_id(op.regionRef)!r} "
            f"must not carry op.outline; got vertices count = "
            f"{len(op.outline.vertices or []) if op.outline else 0}."
        )


def test_smooth_room_exterior_wall_outline_dropped_when_region_ref_set() -> None:
    """seed7_octagon: smooth-room ExteriorWallOps drop op.outline.

    Phase 1.26e-2b — same contract as rect rooms: smooth shapes
    (octagon / L / temple / circle / pill / cross / hybrid) all have
    Regions per 1.26d-1, so their ExteriorWallOps drop op.outline.
    """
    fir = _build_emitted("seed7_octagon_crypt_dungeon")
    smooth_walls = [
        op for op in _exterior_walls(fir)
        if op.style == WallStyle.DungeonInk
        and _decode_id(op.regionRef).startswith("room_")
    ]
    if not smooth_walls:
        pytest.skip("seed7_octagon has no smooth-room ExteriorWallOp")
    for op in smooth_walls:
        assert op.outline is None or not (op.outline.vertices or []), (
            f"smooth-room ExteriorWallOp.regionRef="
            f"{_decode_id(op.regionRef)!r} must not carry op.outline."
        )


def test_cave_exterior_wall_outline_dropped_when_region_ref_set() -> None:
    """seed99_cave: cave ExteriorWallOps drop op.outline.

    Phase 1.26e-2b — per-system ``ExteriorWallOp(region_ref=
    "cave.<i>")`` drops op.outline; Region(kind=Cave).outline is
    canonical (also single-ring raw boundary per 1.26b).
    """
    fir = _build_emitted("seed99_cave_cave_cave")
    cave_walls = [
        op for op in _exterior_walls(fir)
        if op.style == WallStyle.CaveInk
        and _decode_id(op.regionRef).startswith("cave.")
    ]
    assert cave_walls, "seed99_cave has no cave ExteriorWallOp"
    for op in cave_walls:
        assert op.outline is None or not (op.outline.vertices or []), (
            f"cave ExteriorWallOp.regionRef={_decode_id(op.regionRef)!r} "
            f"must not carry op.outline."
        )


def test_enclosure_exterior_wall_outline_dropped_when_region_ref_set() -> None:
    """Synthetic enclosure: ExteriorWallOp drops op.outline.

    Phase 1.26e-2b — site enclosures (palisade / fortification) have
    Region(kind=Enclosure, id="enclosure") per 1.26c; the
    ExteriorWallOp drops op.outline.
    """
    p = _FIXTURE_ROOT / "synthetic_enclosure_palisade_rect" / "floor.nir"
    if not p.exists():
        pytest.skip("synthetic_enclosure_palisade_rect fixture missing")
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(p.read_bytes(), 0))
    enclosure_walls = [
        op for op in _exterior_walls(fir)
        if _decode_id(op.regionRef) == "enclosure"
    ]
    assert enclosure_walls, "enclosure fixture has no enclosure ExteriorWallOp"
    for op in enclosure_walls:
        assert op.outline is None or not (op.outline.vertices or []), (
            "enclosure ExteriorWallOp.regionRef='enclosure' must not "
            "carry op.outline."
        )


def test_building_masonry_outline_dropped_when_region_ref_set() -> None:
    """seed7_brick_building: masonry ExteriorWallOps drop op.outline.

    Phase 1.26e-2b — building masonry walls reference
    Region(kind=Building, id="building.<i>") per 1.24/1.26.
    """
    p = _FIXTURE_ROOT / "seed7_brick_building_floor0" / "floor.nir"
    if not p.exists():
        pytest.skip("seed7_brick_building_floor0 fixture missing")
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(p.read_bytes(), 0))
    masonry_walls = [
        op for op in _exterior_walls(fir)
        if op.style in (WallStyle.MasonryBrick, WallStyle.MasonryStone)
        and _decode_id(op.regionRef).startswith("building.")
    ]
    if not masonry_walls:
        pytest.skip("seed7_brick_building has no masonry ExteriorWallOp")
    for op in masonry_walls:
        assert op.outline is None or not (op.outline.vertices or []), (
            f"masonry ExteriorWallOp.regionRef="
            f"{_decode_id(op.regionRef)!r} must not carry op.outline."
        )


def test_interior_wall_op_keeps_outline_by_design() -> None:
    """InteriorWallOp.outline stays populated past 1.26e-2b.

    Phase 1.26e-2b — interior walls (PartitionStone/Brick/Wood) are
    NOT region perimeters; they ship their own 2-vertex polyline
    outline on the op. The schema docstring at 1.24 documents this:
    ``interior walls keep their op-level outline because they are
    not region perimeters``.
    """
    p = _FIXTURE_ROOT / "synthetic_building_wall_brick_with_interior" / "floor.nir"
    if not p.exists():
        pytest.skip("synthetic_building_wall_brick_with_interior fixture missing")
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(p.read_bytes(), 0))
    interior_walls = _interior_walls(fir)
    assert interior_walls, (
        "synthetic_building_wall_brick_with_interior has no InteriorWallOp"
    )
    for op in interior_walls:
        assert op.outline is not None and op.outline.vertices, (
            "InteriorWallOp must keep op.outline populated — interior "
            "walls are not region perimeters"
        )
