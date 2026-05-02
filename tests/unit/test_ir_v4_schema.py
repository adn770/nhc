"""Round-trip tests for the v4-prep schema additions.

Phase 1 of plans/nhc_pure_ir_plan.md is the heavy lift to schema 4.0;
each step is pure-additive at first (new tables / enums / op-union
variants land alongside the existing ones, with no consumers reading
them yet) and only later does the cut commit drop the legacy entries.

This test module pins the contract of the additive prep commits:
1.1 (Outline + Cut + style enums) and 1.2 (FloorOp / InteriorWallOp /
ExteriorWallOp). The round-trip assertions guard the FlatBuffers
encoding of the new schema entities through the FB ObjectAPI; if a
later regen drops a field or perturbs an enum value the tests
catch it before any consumer ships.
"""

from __future__ import annotations

import flatbuffers


# ── 1.1 — Outline / Cut / style enums round-trip ─────────────────


def _roundtrip_outline(outline_t):
    """Serialise an OutlineT through a FlatBuffers builder and
    parse it back into a fresh OutlineT. Returns the parsed copy.
    """
    from nhc.rendering.ir._fb.Outline import Outline, OutlineT

    builder = flatbuffers.Builder(0)
    offset = outline_t.Pack(builder)
    builder.Finish(offset)
    buf = builder.Output()
    parsed = Outline.GetRootAs(buf, 0)
    return OutlineT.InitFromObj(parsed)


def test_outline_polygon_round_trip() -> None:
    """An Outline carrying explicit Polygon vertices round-trips."""
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    src = OutlineT()
    src.descriptorKind = OutlineKind.Polygon
    src.closed = True
    src.vertices = [
        Vec2T(),
        Vec2T(),
        Vec2T(),
        Vec2T(),
    ]
    src.vertices[0].x = 0.0
    src.vertices[0].y = 0.0
    src.vertices[1].x = 32.0
    src.vertices[1].y = 0.0
    src.vertices[2].x = 32.0
    src.vertices[2].y = 64.0
    src.vertices[3].x = 0.0
    src.vertices[3].y = 64.0
    src.cuts = []
    src.cx = 0.0
    src.cy = 0.0
    src.rx = 0.0
    src.ry = 0.0

    out = _roundtrip_outline(src)

    assert out.descriptorKind == OutlineKind.Polygon
    assert out.closed is True
    assert out.vertices is not None
    assert len(out.vertices) == 4
    assert out.vertices[2].x == 32.0
    assert out.vertices[2].y == 64.0
    assert out.cuts is None or len(out.cuts) == 0


def test_outline_circle_round_trip() -> None:
    """A Circle-descriptor Outline round-trips with cx / cy / rx /
    ry populated and an empty vertices list."""
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    src = OutlineT()
    src.descriptorKind = OutlineKind.Circle
    src.closed = True
    src.cx = 96.0
    src.cy = 96.0
    src.rx = 48.0
    src.ry = 48.0
    src.vertices = []
    src.cuts = []

    out = _roundtrip_outline(src)

    assert out.descriptorKind == OutlineKind.Circle
    assert out.cx == 96.0
    assert out.cy == 96.0
    assert out.rx == 48.0
    assert out.ry == 48.0


def test_outline_pill_round_trip() -> None:
    """A Pill-descriptor Outline round-trips with rx != ry."""
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    src = OutlineT()
    src.descriptorKind = OutlineKind.Pill
    src.closed = True
    src.cx = 100.0
    src.cy = 50.0
    src.rx = 60.0
    src.ry = 24.0
    src.vertices = []
    src.cuts = []

    out = _roundtrip_outline(src)

    assert out.descriptorKind == OutlineKind.Pill
    assert out.cx == 100.0
    assert out.cy == 50.0
    assert out.rx == 60.0
    assert out.ry == 24.0


def test_outline_with_cuts_round_trip() -> None:
    """An Outline with two Cuts round-trips: cut count, start /
    end coords, and styles all preserved."""
    from nhc.rendering.ir._fb.Cut import CutT
    from nhc.rendering.ir._fb.CutStyle import CutStyle
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    src = OutlineT()
    src.descriptorKind = OutlineKind.Polygon
    src.closed = True
    src.vertices = [Vec2T() for _ in range(4)]
    src.vertices[0].x, src.vertices[0].y = 0.0, 0.0
    src.vertices[1].x, src.vertices[1].y = 64.0, 0.0
    src.vertices[2].x, src.vertices[2].y = 64.0, 64.0
    src.vertices[3].x, src.vertices[3].y = 0.0, 64.0

    cut0 = CutT()
    cut0.start = Vec2T()
    cut0.start.x, cut0.start.y = 16.0, 0.0
    cut0.end = Vec2T()
    cut0.end.x, cut0.end.y = 32.0, 0.0
    cut0.style = CutStyle.DoorWood

    cut1 = CutT()
    cut1.start = Vec2T()
    cut1.start.x, cut1.start.y = 64.0, 16.0
    cut1.end = Vec2T()
    cut1.end.x, cut1.end.y = 64.0, 48.0
    cut1.style = CutStyle.DoorSecret

    src.cuts = [cut0, cut1]

    out = _roundtrip_outline(src)

    assert out.cuts is not None
    assert len(out.cuts) == 2
    assert out.cuts[0].start.x == 16.0
    assert out.cuts[0].end.x == 32.0
    assert out.cuts[0].style == CutStyle.DoorWood
    assert out.cuts[1].start.y == 16.0
    assert out.cuts[1].end.y == 48.0
    assert out.cuts[1].style == CutStyle.DoorSecret


def test_cut_style_values_round_trip() -> None:
    """Every declared CutStyle value encodes and decodes."""
    from nhc.rendering.ir._fb.Cut import CutT
    from nhc.rendering.ir._fb.CutStyle import CutStyle
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    expected = [
        CutStyle.None_,
        CutStyle.WoodGate,
        CutStyle.PortcullisGate,
        CutStyle.DoorWood,
        CutStyle.DoorStone,
        CutStyle.DoorIron,
        CutStyle.DoorSecret,
    ]
    cuts = []
    for style in expected:
        c = CutT()
        c.start = Vec2T()
        c.start.x, c.start.y = 0.0, 0.0
        c.end = Vec2T()
        c.end.x, c.end.y = 1.0, 0.0
        c.style = style
        cuts.append(c)

    src = OutlineT()
    src.vertices = [Vec2T() for _ in range(3)]
    src.vertices[0].x, src.vertices[0].y = 0.0, 0.0
    src.vertices[1].x, src.vertices[1].y = 1.0, 0.0
    src.vertices[2].x, src.vertices[2].y = 0.0, 1.0
    src.cuts = cuts
    src.closed = True

    out = _roundtrip_outline(src)

    assert out.cuts is not None
    assert len(out.cuts) == len(expected)
    for got, want in zip(out.cuts, expected):
        assert got.style == want


def test_wall_style_values_declared() -> None:
    """Every declared WallStyle enum value is reachable as a stable
    integer constant. The 4.0 wall ops (1.2) consume the enum; this
    test pins the value set so a later regen doesn't quietly perturb
    the tag mapping (which would shift cached buffers out of phase
    on the rasteriser side)."""
    from nhc.rendering.ir._fb.WallStyle import WallStyle

    expected = {
        "DungeonInk": 0,
        "CaveInk": 1,
        "MasonryBrick": 2,
        "MasonryStone": 3,
        "PartitionStone": 4,
        "PartitionBrick": 5,
        "PartitionWood": 6,
        "Palisade": 7,
        "FortificationMerlon": 8,
    }
    for name, value in expected.items():
        assert getattr(WallStyle, name) == value


def test_floor_style_values_declared() -> None:
    """Every declared FloorStyle enum value is reachable as a stable
    integer constant."""
    from nhc.rendering.ir._fb.FloorStyle import FloorStyle

    expected = {"DungeonFloor": 0, "CaveFloor": 1, "WoodFloor": 2}
    for name, value in expected.items():
        assert getattr(FloorStyle, name) == value


def test_floor_style_wood_floor_round_trips() -> None:
    """A FloorOp carrying ``FloorStyle.WoodFloor`` round-trips
    through the op union. Phase 1.20b: building wood-floor brown
    fill replaces the legacy ``WallsAndFloorsOp.smoothFillSvg``
    SVG-string path."""
    from nhc.rendering.ir._fb.FloorOp import FloorOpT
    from nhc.rendering.ir._fb.FloorStyle import FloorStyle
    from nhc.rendering.ir._fb.Op import Op

    src = FloorOpT()
    src.outline = _build_polygon_outline_t()
    src.style = FloorStyle.WoodFloor

    tag, op = _roundtrip_op_via_floor_ir(Op.FloorOp, src)
    assert tag == Op.FloorOp
    assert op.style == FloorStyle.WoodFloor
    assert op.outline is not None
    assert op.outline.vertices is not None
    assert len(op.outline.vertices) == 4


def test_outline_kind_values_declared() -> None:
    """OutlineKind has the three declared variants at stable tags."""
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    assert OutlineKind.Polygon == 0
    assert OutlineKind.Circle == 1
    assert OutlineKind.Pill == 2


# ── 1.2 — FloorOp / InteriorWallOp / ExteriorWallOp round-trip ──


def _build_polygon_outline_t() -> "OutlineT":
    """Helper: a 4-vertex closed polygon outline used by op tests."""
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Polygon
    outline.closed = True
    outline.vertices = [Vec2T() for _ in range(4)]
    outline.vertices[0].x, outline.vertices[0].y = 0.0, 0.0
    outline.vertices[1].x, outline.vertices[1].y = 64.0, 0.0
    outline.vertices[2].x, outline.vertices[2].y = 64.0, 96.0
    outline.vertices[3].x, outline.vertices[3].y = 0.0, 96.0
    outline.cuts = []
    return outline


def _roundtrip_op_via_floor_ir(op_value: int, op_t):
    """Wrap an op-table T value in a FloorIR root, serialise, parse
    back, return the (op_type_tag, parsed_op_T)."""
    from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
    from nhc.rendering.ir._fb.OpEntry import OpEntryT

    fir = FloorIRT()
    fir.major = 3
    fir.minor = 1
    fir.widthTiles = 4
    fir.heightTiles = 4
    fir.theme = "dungeon"
    fir.baseSeed = 1234

    entry = OpEntryT()
    entry.opType = op_value
    entry.op = op_t
    fir.ops = [entry]

    builder = flatbuffers.Builder(0)
    builder.Finish(fir.Pack(builder), b"NIR3")
    parsed = FloorIR.GetRootAs(builder.Output(), 0)
    parsed_t = FloorIRT.InitFromObj(parsed)
    assert parsed_t.ops is not None
    assert len(parsed_t.ops) == 1
    return parsed_t.ops[0].opType, parsed_t.ops[0].op


def test_floor_op_round_trip() -> None:
    """A FloorIR carrying a FloorOp inside the op union round-trips
    with outline + style preserved."""
    from nhc.rendering.ir._fb.FloorOp import FloorOpT
    from nhc.rendering.ir._fb.FloorStyle import FloorStyle
    from nhc.rendering.ir._fb.Op import Op

    src = FloorOpT()
    src.outline = _build_polygon_outline_t()
    src.style = FloorStyle.CaveFloor

    tag, op = _roundtrip_op_via_floor_ir(Op.FloorOp, src)
    assert tag == Op.FloorOp
    assert op.style == FloorStyle.CaveFloor
    assert op.outline is not None
    assert op.outline.vertices is not None
    assert len(op.outline.vertices) == 4
    assert op.outline.vertices[2].x == 64.0
    assert op.outline.vertices[2].y == 96.0


def test_interior_wall_op_round_trip() -> None:
    """An InteriorWallOp with an open polyline (closed=False) and a
    cut round-trips through the op union."""
    from nhc.rendering.ir._fb.Cut import CutT
    from nhc.rendering.ir._fb.CutStyle import CutStyle
    from nhc.rendering.ir._fb.InteriorWallOp import InteriorWallOpT
    from nhc.rendering.ir._fb.Op import Op
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind
    from nhc.rendering.ir._fb.Vec2 import Vec2T
    from nhc.rendering.ir._fb.WallStyle import WallStyle

    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Polygon
    outline.closed = False
    outline.vertices = [Vec2T() for _ in range(2)]
    outline.vertices[0].x, outline.vertices[0].y = 0.0, 32.0
    outline.vertices[1].x, outline.vertices[1].y = 128.0, 32.0
    cut = CutT()
    cut.start = Vec2T()
    cut.start.x, cut.start.y = 48.0, 32.0
    cut.end = Vec2T()
    cut.end.x, cut.end.y = 64.0, 32.0
    cut.style = CutStyle.DoorWood
    outline.cuts = [cut]

    src = InteriorWallOpT()
    src.outline = outline
    src.style = WallStyle.PartitionWood

    tag, op = _roundtrip_op_via_floor_ir(Op.InteriorWallOp, src)
    assert tag == Op.InteriorWallOp
    assert op.style == WallStyle.PartitionWood
    assert op.outline.closed is False
    assert len(op.outline.vertices) == 2
    assert len(op.outline.cuts) == 1
    assert op.outline.cuts[0].style == CutStyle.DoorWood


def test_exterior_wall_op_round_trip() -> None:
    """An ExteriorWallOp with corner_style, two cuts, and a closed
    polygon outline round-trips."""
    from nhc.rendering.ir._fb.CornerStyle import CornerStyle
    from nhc.rendering.ir._fb.Cut import CutT
    from nhc.rendering.ir._fb.CutStyle import CutStyle
    from nhc.rendering.ir._fb.ExteriorWallOp import ExteriorWallOpT
    from nhc.rendering.ir._fb.Op import Op
    from nhc.rendering.ir._fb.Vec2 import Vec2T
    from nhc.rendering.ir._fb.WallStyle import WallStyle

    outline = _build_polygon_outline_t()
    cut = CutT()
    cut.start = Vec2T()
    cut.start.x, cut.start.y = 16.0, 0.0
    cut.end = Vec2T()
    cut.end.x, cut.end.y = 48.0, 0.0
    cut.style = CutStyle.WoodGate
    outline.cuts = [cut]

    src = ExteriorWallOpT()
    src.outline = outline
    src.style = WallStyle.FortificationMerlon
    src.cornerStyle = CornerStyle.Diamond

    tag, op = _roundtrip_op_via_floor_ir(Op.ExteriorWallOp, src)
    assert tag == Op.ExteriorWallOp
    assert op.style == WallStyle.FortificationMerlon
    assert op.cornerStyle == CornerStyle.Diamond
    assert len(op.outline.cuts) == 1
    assert op.outline.cuts[0].style == CutStyle.WoodGate


def test_op_union_preserves_existing_variant_tags() -> None:
    """Adding FloorOp / InteriorWallOp / ExteriorWallOp at the end
    of the union must keep the pre-existing variant tags stable so
    older buffers continue to dispatch correctly. Pin every legacy
    tag value here as a regression guard."""
    from nhc.rendering.ir._fb.Op import Op

    # Pre-1.2 variants — these tags are part of the schema 3.x
    # contract and must NOT shift.
    assert Op.NONE == 0
    assert Op.ShadowOp == 1
    assert Op.HatchOp == 2
    assert Op.WallsAndFloorsOp == 3
    assert Op.TerrainTintOp == 4
    assert Op.FloorGridOp == 5
    assert Op.FloorDetailOp == 6
    assert Op.ThematicDetailOp == 7
    assert Op.TerrainDetailOp == 8
    assert Op.StairsOp == 9
    assert Op.TreeFeatureOp == 10
    assert Op.BushFeatureOp == 11
    assert Op.WellFeatureOp == 12
    assert Op.FountainFeatureOp == 13
    assert Op.GenericProceduralOp == 14
    assert Op.DecoratorOp == 15
    assert Op.RoofOp == 16
    assert Op.EnclosureOp == 17
    assert Op.BuildingExteriorWallOp == 18
    assert Op.BuildingInteriorWallOp == 19

    # New 1.2 variants — appended at the end so legacy tags stay put.
    assert Op.FloorOp == 20
    assert Op.InteriorWallOp == 21
    assert Op.ExteriorWallOp == 22
