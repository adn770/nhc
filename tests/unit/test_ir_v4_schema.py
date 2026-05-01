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

    expected = {"DungeonFloor": 0, "CaveFloor": 1}
    for name, value in expected.items():
        assert getattr(FloorStyle, name) == value


def test_outline_kind_values_declared() -> None:
    """OutlineKind has the three declared variants at stable tags."""
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    assert OutlineKind.Polygon == 0
    assert OutlineKind.Circle == 1
    assert OutlineKind.Pill == 2
