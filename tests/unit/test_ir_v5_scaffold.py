"""v5 schema scaffold — additive bindings round-trip.

Phase 1.1 of plans/nhc_pure_ir_v5_migration_plan.md adds v5
tables alongside v4 ones with a ``V5_`` prefix. The op union does
NOT yet include the v5 variants. Schema major stays at 4. The
test pins the contract:

- Generated bindings include V5* modules (Python).
- Each new table / struct round-trips through FlatBuffers
  ObjectAPI without losing fields.
- FloorIR.major remains 4 (no schema bump yet).

The atomic NIR4 → NIR5 cut at Phase 1.8 drops v4 ops, renames
V5* → canonical names, and bumps major to 5. Until then this
test guards the additive scaffold.
"""

from __future__ import annotations

import flatbuffers


# ── Module imports — generated bindings exist ──────────────────


def test_v5_material_family_enum_exposes_seven_families() -> None:
    from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily

    assert V5MaterialFamily.Plain == 0
    assert V5MaterialFamily.Cave == 1
    assert V5MaterialFamily.Wood == 2
    assert V5MaterialFamily.Stone == 3
    assert V5MaterialFamily.Earth == 4
    assert V5MaterialFamily.Liquid == 5
    assert V5MaterialFamily.Special == 6


def test_v5_wall_treatment_enum_exposes_five_treatments() -> None:
    from nhc.rendering.ir._fb.V5WallTreatment import V5WallTreatment

    assert V5WallTreatment.PlainStroke == 0
    assert V5WallTreatment.Masonry == 1
    assert V5WallTreatment.Partition == 2
    assert V5WallTreatment.Palisade == 3
    assert V5WallTreatment.Fortification == 4


def test_v5_path_style_enum_exposes_locked_two() -> None:
    from nhc.rendering.ir._fb.V5PathStyle import V5PathStyle

    assert V5PathStyle.CartTracks == 0
    assert V5PathStyle.OreVein == 1


def test_v5_fixture_kind_enum_exposes_locked_twelve() -> None:
    from nhc.rendering.ir._fb.V5FixtureKind import V5FixtureKind

    assert V5FixtureKind.Web == 0
    assert V5FixtureKind.Skull == 1
    assert V5FixtureKind.Bone == 2
    assert V5FixtureKind.LooseStone == 3
    assert V5FixtureKind.Tree == 4
    assert V5FixtureKind.Bush == 5
    assert V5FixtureKind.Well == 6
    assert V5FixtureKind.Fountain == 7
    assert V5FixtureKind.Stair == 8
    assert V5FixtureKind.Gravestone == 9
    assert V5FixtureKind.Sign == 10
    assert V5FixtureKind.Mushroom == 11


def test_v5_roof_style_enum_extends_v4_simple_dome_witchhat() -> None:
    from nhc.rendering.ir._fb.V5RoofStyle import V5RoofStyle

    assert V5RoofStyle.Simple == 0
    assert V5RoofStyle.Pyramid == 1
    assert V5RoofStyle.Gable == 2
    assert V5RoofStyle.Dome == 3
    assert V5RoofStyle.WitchHat == 4


# ── Material / WallMaterial round-trip ─────────────────────────


def test_v5_material_round_trip() -> None:
    from nhc.rendering.ir._fb.V5Material import V5Material, V5MaterialT
    from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily

    src = V5MaterialT()
    src.family = V5MaterialFamily.Wood
    src.style = 2
    src.subPattern = 3
    src.tone = 1
    src.seed = 0xDEADBEEF

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5Material.GetRootAs(builder.Output(), 0)
    out = V5MaterialT.InitFromObj(parsed)

    assert out.family == V5MaterialFamily.Wood
    assert out.style == 2
    assert out.subPattern == 3
    assert out.tone == 1
    assert out.seed == 0xDEADBEEF


def test_v5_wall_material_round_trip() -> None:
    from nhc.rendering.ir._fb.CornerStyle import CornerStyle
    from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily
    from nhc.rendering.ir._fb.V5WallMaterial import V5WallMaterial, V5WallMaterialT
    from nhc.rendering.ir._fb.V5WallTreatment import V5WallTreatment

    src = V5WallMaterialT()
    src.family = V5MaterialFamily.Stone
    src.style = 4
    src.treatment = V5WallTreatment.Fortification
    src.cornerStyle = CornerStyle.Diamond
    src.tone = 2
    src.seed = 0xC0FFEE

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5WallMaterial.GetRootAs(builder.Output(), 0)
    out = V5WallMaterialT.InitFromObj(parsed)

    assert out.family == V5MaterialFamily.Stone
    assert out.style == 4
    assert out.treatment == V5WallTreatment.Fortification
    assert out.cornerStyle == CornerStyle.Diamond
    assert out.tone == 2
    assert out.seed == 0xC0FFEE


# ── Region with parent_id + cuts (no Region.kind) ──────────────


def test_v5_region_carries_parent_id_and_cuts_no_kind() -> None:
    from nhc.rendering.ir._fb.Cut import CutT
    from nhc.rendering.ir._fb.CutStyle import CutStyle
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.V5Region import V5Region, V5RegionT
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    src = V5RegionT()
    src.id = "aisle.1"
    src.parentId = "temple.5"
    src.shapeTag = "rect"
    src.outline = OutlineT()
    src.outline.vertices = [Vec2T(), Vec2T(), Vec2T(), Vec2T()]
    cut = CutT()
    cut.start = Vec2T()
    cut.start.x = 1.0
    cut.start.y = 0.0
    cut.end = Vec2T()
    cut.end.x = 2.0
    cut.end.y = 0.0
    cut.style = CutStyle.DoorWood
    src.cuts = [cut]

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5Region.GetRootAs(builder.Output(), 0)
    out = V5RegionT.InitFromObj(parsed)

    assert out.id.decode() == "aisle.1"
    assert out.parentId.decode() == "temple.5"
    assert out.shapeTag.decode() == "rect"
    assert out.outline is not None
    assert len(out.cuts) == 1
    assert out.cuts[0].style == CutStyle.DoorWood
    # Region.kind eliminated in v5; the binding has no `kind` attr
    # on V5RegionT.
    assert not hasattr(out, "kind")


# ── Op tables — round-trip each new shape ──────────────────────


def test_v5_paint_op_round_trip() -> None:
    from nhc.rendering.ir._fb.V5Material import V5MaterialT
    from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily
    from nhc.rendering.ir._fb.V5PaintOp import V5PaintOp, V5PaintOpT

    src = V5PaintOpT()
    src.regionRef = "temple.5"
    src.subtractRegionRefs = ["altar.0", "plinth.1"]
    src.material = V5MaterialT()
    src.material.family = V5MaterialFamily.Stone
    src.material.style = 0  # Cobblestone
    src.material.subPattern = 0  # Herringbone
    src.material.tone = 1
    src.material.seed = 0x1234

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5PaintOp.GetRootAs(builder.Output(), 0)
    out = V5PaintOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "temple.5"
    assert [s.decode() for s in out.subtractRegionRefs] == ["altar.0", "plinth.1"]
    assert out.material.family == V5MaterialFamily.Stone
    assert out.material.seed == 0x1234


def test_v5_stamp_op_round_trip_decorator_mask_and_density() -> None:
    from nhc.rendering.ir._fb.V5StampOp import V5StampOp, V5StampOpT

    src = V5StampOpT()
    src.regionRef = "room.3"
    src.subtractRegionRefs = []
    # bits: 0=GridLines | 1=Cracks | 5=Moss
    src.decoratorMask = (1 << 0) | (1 << 1) | (1 << 5)
    src.density = 64
    src.seed = 0xABCD

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5StampOp.GetRootAs(builder.Output(), 0)
    out = V5StampOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "room.3"
    assert out.decoratorMask == (1 << 0) | (1 << 1) | (1 << 5)
    assert out.density == 64
    assert out.seed == 0xABCD


def test_v5_path_op_round_trip() -> None:
    from nhc.rendering.ir._fb.TileCoord import TileCoordT
    from nhc.rendering.ir._fb.V5PathOp import V5PathOp, V5PathOpT
    from nhc.rendering.ir._fb.V5PathStyle import V5PathStyle

    src = V5PathOpT()
    src.regionRef = "corridor.2"
    src.tiles = [TileCoordT(), TileCoordT()]
    src.tiles[0].x = 5
    src.tiles[0].y = 7
    src.tiles[1].x = 6
    src.tiles[1].y = 7
    src.style = V5PathStyle.CartTracks
    src.seed = 0xFACE

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5PathOp.GetRootAs(builder.Output(), 0)
    out = V5PathOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "corridor.2"
    assert len(out.tiles) == 2
    assert out.tiles[1].x == 6
    assert out.style == V5PathStyle.CartTracks


def test_v5_fixture_op_round_trip_with_anchors() -> None:
    from nhc.rendering.ir._fb.V5Anchor import V5AnchorT
    from nhc.rendering.ir._fb.V5FixtureKind import V5FixtureKind
    from nhc.rendering.ir._fb.V5FixtureOp import V5FixtureOp, V5FixtureOpT

    src = V5FixtureOpT()
    src.regionRef = "site.0"
    src.kind = V5FixtureKind.Tree
    a0 = V5AnchorT()
    a0.x = 10
    a0.y = 12
    a0.variant = 1
    a0.orientation = 0
    a0.scale = 1
    a0.groupId = 7
    src.anchors = [a0]
    src.seed = 0xBEEF

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5FixtureOp.GetRootAs(builder.Output(), 0)
    out = V5FixtureOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "site.0"
    assert out.kind == V5FixtureKind.Tree
    assert len(out.anchors) == 1
    assert out.anchors[0].x == 10
    assert out.anchors[0].y == 12
    assert out.anchors[0].variant == 1
    assert out.anchors[0].groupId == 7


def test_v5_stroke_op_round_trip() -> None:
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily
    from nhc.rendering.ir._fb.V5StrokeOp import V5StrokeOp, V5StrokeOpT
    from nhc.rendering.ir._fb.V5WallMaterial import V5WallMaterialT
    from nhc.rendering.ir._fb.V5WallTreatment import V5WallTreatment
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    src = V5StrokeOpT()
    src.regionRef = "room.7"
    src.outline = OutlineT()
    src.outline.vertices = [Vec2T(), Vec2T(), Vec2T()]
    src.wallMaterial = V5WallMaterialT()
    src.wallMaterial.family = V5MaterialFamily.Stone
    src.wallMaterial.style = 0
    src.wallMaterial.treatment = V5WallTreatment.Masonry
    src.wallMaterial.tone = 0
    src.wallMaterial.seed = 0x77

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5StrokeOp.GetRootAs(builder.Output(), 0)
    out = V5StrokeOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "room.7"
    assert out.wallMaterial.family == V5MaterialFamily.Stone
    assert out.wallMaterial.treatment == V5WallTreatment.Masonry


def test_v5_hatch_op_uses_subtract_region_refs() -> None:
    from nhc.rendering.ir._fb.HatchKind import HatchKind
    from nhc.rendering.ir._fb.V5HatchOp import V5HatchOp, V5HatchOpT

    src = V5HatchOpT()
    src.kind = HatchKind.Hole
    src.regionRef = "cave"
    src.subtractRegionRefs = ["dungeon"]
    src.tiles = []
    src.isOuter = []
    src.extentTiles = 2.0
    src.seed = 777
    src.hatchUnderlayColor = "#222222"

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5HatchOp.GetRootAs(builder.Output(), 0)
    out = V5HatchOpT.InitFromObj(parsed)

    assert out.kind == HatchKind.Hole
    assert out.regionRef.decode() == "cave"
    assert [s.decode() for s in out.subtractRegionRefs] == ["dungeon"]
    assert out.extentTiles == 2.0
    assert out.seed == 777


def test_v5_roof_op_carries_tone_seed_and_extended_styles() -> None:
    from nhc.rendering.ir._fb.V5RoofOp import V5RoofOp, V5RoofOpT
    from nhc.rendering.ir._fb.V5RoofStyle import V5RoofStyle

    src = V5RoofOpT()
    src.regionRef = "building.3"
    src.style = V5RoofStyle.Pyramid
    src.tone = 2
    src.tint = "#A07050"
    src.seed = 0xCAFE0003

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = V5RoofOp.GetRootAs(builder.Output(), 0)
    out = V5RoofOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "building.3"
    assert out.style == V5RoofStyle.Pyramid
    assert out.tone == 2
    assert out.tint.decode() == "#A07050"
    assert out.seed == 0xCAFE0003


# ── Op union remains v4 — schema stays at 4 ────────────────────


def test_v5_scaffold_does_not_extend_op_union() -> None:
    """The Op union is still the v4 set. v5 op variants will land
    in the union at the atomic cut (Phase 1.8)."""
    from nhc.rendering.ir._fb.Op import Op

    # Numeric values for v4 op variants — must remain stable.
    assert Op.NONE == 0
    assert Op.ShadowOp == 1
    assert Op.HatchOp == 2
    assert Op.FloorOp == 15
    # No V5* variants in the union yet.
    assert not hasattr(Op, "V5PaintOp")
    assert not hasattr(Op, "V5StampOp")


def test_floor_ir_major_remains_4() -> None:
    """Until the atomic cut, FloorIR.major stays at 4."""
    from nhc.rendering.ir_emitter import SCHEMA_MAJOR

    assert SCHEMA_MAJOR == 4
