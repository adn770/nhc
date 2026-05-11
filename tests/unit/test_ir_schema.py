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


def test_material_family_enum_exposes_seven_families() -> None:
    from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily

    assert MaterialFamily.Plain == 0
    assert MaterialFamily.Cave == 1
    assert MaterialFamily.Wood == 2
    assert MaterialFamily.Stone == 3
    assert MaterialFamily.Earth == 4
    assert MaterialFamily.Liquid == 5
    assert MaterialFamily.Special == 6


def test_wall_treatment_enum_exposes_five_treatments() -> None:
    from nhc.rendering.ir._fb.WallTreatment import WallTreatment

    assert WallTreatment.PlainStroke == 0
    assert WallTreatment.Masonry == 1
    assert WallTreatment.Partition == 2
    assert WallTreatment.Palisade == 3
    assert WallTreatment.Fortification == 4


def test_path_style_enum_exposes_locked_two() -> None:
    from nhc.rendering.ir._fb.PathStyle import PathStyle

    assert PathStyle.CartTracks == 0
    assert PathStyle.OreVein == 1


def test_fixture_kind_enum_exposes_locked_twelve() -> None:
    from nhc.rendering.ir._fb.FixtureKind import FixtureKind

    assert FixtureKind.Web == 0
    assert FixtureKind.Skull == 1
    assert FixtureKind.Bone == 2
    assert FixtureKind.LooseStone == 3
    assert FixtureKind.Tree == 4
    assert FixtureKind.Bush == 5
    assert FixtureKind.Well == 6
    assert FixtureKind.Fountain == 7
    assert FixtureKind.Stair == 8
    assert FixtureKind.Gravestone == 9
    assert FixtureKind.Sign == 10
    assert FixtureKind.Mushroom == 11


def test_roof_style_enum_extends_v4_simple_dome_witchhat() -> None:
    from nhc.rendering.ir._fb.RoofStyle import RoofStyle

    assert RoofStyle.Simple == 0
    assert RoofStyle.Pyramid == 1
    assert RoofStyle.Gable == 2
    assert RoofStyle.Dome == 3
    assert RoofStyle.WitchHat == 4


def test_roof_tile_pattern_enum_pins_canonical_values() -> None:
    from nhc.rendering.ir._fb.RoofTilePattern import RoofTilePattern

    assert RoofTilePattern.Plain == 0
    assert RoofTilePattern.Fishscale == 1
    assert RoofTilePattern.Thatch == 2
    assert RoofTilePattern.Pantile == 3
    assert RoofTilePattern.Slate == 4


# ── Material / WallMaterial round-trip ─────────────────────────


def test_material_round_trip() -> None:
    from nhc.rendering.ir._fb.Material import Material, MaterialT
    from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily

    src = MaterialT()
    src.family = MaterialFamily.Wood
    src.style = 2
    src.subPattern = 3
    src.tone = 1
    src.seed = 0xDEADBEEF

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = Material.GetRootAs(builder.Output(), 0)
    out = MaterialT.InitFromObj(parsed)

    assert out.family == MaterialFamily.Wood
    assert out.style == 2
    assert out.subPattern == 3
    assert out.tone == 1
    assert out.seed == 0xDEADBEEF


def test_wall_material_round_trip() -> None:
    from nhc.rendering.ir._fb.CornerStyle import CornerStyle
    from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily
    from nhc.rendering.ir._fb.WallMaterial import WallMaterial, WallMaterialT
    from nhc.rendering.ir._fb.WallTreatment import WallTreatment

    src = WallMaterialT()
    src.family = MaterialFamily.Stone
    src.style = 4
    src.treatment = WallTreatment.Fortification
    src.cornerStyle = CornerStyle.Diamond
    src.tone = 2
    src.seed = 0xC0FFEE

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = WallMaterial.GetRootAs(builder.Output(), 0)
    out = WallMaterialT.InitFromObj(parsed)

    assert out.family == MaterialFamily.Stone
    assert out.style == 4
    assert out.treatment == WallTreatment.Fortification
    assert out.cornerStyle == CornerStyle.Diamond
    assert out.tone == 2
    assert out.seed == 0xC0FFEE


# ── Region with parent_id + cuts (no Region.kind) ──────────────


def test_region_carries_parent_id_and_cuts_no_kind() -> None:
    from nhc.rendering.ir._fb.Cut import CutT
    from nhc.rendering.ir._fb.CutStyle import CutStyle
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.Region import Region, RegionT
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    src = RegionT()
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
    parsed = Region.GetRootAs(builder.Output(), 0)
    out = RegionT.InitFromObj(parsed)

    assert out.id.decode() == "aisle.1"
    assert out.parentId.decode() == "temple.5"
    assert out.shapeTag.decode() == "rect"
    assert out.outline is not None
    assert len(out.cuts) == 1
    assert out.cuts[0].style == CutStyle.DoorWood
    # Region.kind eliminated in v5; the binding has no `kind` attr
    # on RegionT.
    assert not hasattr(out, "kind")


# ── Op tables — round-trip each new shape ──────────────────────


def test_paint_op_round_trip() -> None:
    from nhc.rendering.ir._fb.Material import MaterialT
    from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily
    from nhc.rendering.ir._fb.PaintOp import PaintOp, PaintOpT

    src = PaintOpT()
    src.regionRef = "temple.5"
    src.subtractRegionRefs = ["altar.0", "plinth.1"]
    src.material = MaterialT()
    src.material.family = MaterialFamily.Stone
    src.material.style = 0  # Cobblestone
    src.material.subPattern = 0  # Herringbone
    src.material.tone = 1
    src.material.seed = 0x1234

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = PaintOp.GetRootAs(builder.Output(), 0)
    out = PaintOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "temple.5"
    assert [s.decode() for s in out.subtractRegionRefs] == ["altar.0", "plinth.1"]
    assert out.material.family == MaterialFamily.Stone
    assert out.material.seed == 0x1234


def test_stamp_op_round_trip_decorator_mask_and_density() -> None:
    from nhc.rendering.ir._fb.StampOp import StampOp, StampOpT

    src = StampOpT()
    src.regionRef = "room.3"
    src.subtractRegionRefs = []
    # bits: 0=GridLines | 1=Cracks | 5=Moss
    src.decoratorMask = (1 << 0) | (1 << 1) | (1 << 5)
    src.density = 64
    src.seed = 0xABCD

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = StampOp.GetRootAs(builder.Output(), 0)
    out = StampOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "room.3"
    assert out.decoratorMask == (1 << 0) | (1 << 1) | (1 << 5)
    assert out.density == 64
    assert out.seed == 0xABCD


def test_path_op_round_trip() -> None:
    from nhc.rendering.ir._fb.TileCoord import TileCoordT
    from nhc.rendering.ir._fb.PathOp import PathOp, PathOpT
    from nhc.rendering.ir._fb.PathStyle import PathStyle

    src = PathOpT()
    src.regionRef = "corridor.2"
    src.tiles = [TileCoordT(), TileCoordT()]
    src.tiles[0].x = 5
    src.tiles[0].y = 7
    src.tiles[1].x = 6
    src.tiles[1].y = 7
    src.style = PathStyle.CartTracks
    src.seed = 0xFACE

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = PathOp.GetRootAs(builder.Output(), 0)
    out = PathOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "corridor.2"
    assert len(out.tiles) == 2
    assert out.tiles[1].x == 6
    assert out.style == PathStyle.CartTracks


def test_fixture_op_round_trip_with_anchors() -> None:
    from nhc.rendering.ir._fb.Anchor import AnchorT
    from nhc.rendering.ir._fb.FixtureKind import FixtureKind
    from nhc.rendering.ir._fb.FixtureOp import FixtureOp, FixtureOpT

    src = FixtureOpT()
    src.regionRef = "site.0"
    src.kind = FixtureKind.Tree
    a0 = AnchorT()
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
    parsed = FixtureOp.GetRootAs(builder.Output(), 0)
    out = FixtureOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "site.0"
    assert out.kind == FixtureKind.Tree
    assert len(out.anchors) == 1
    assert out.anchors[0].x == 10
    assert out.anchors[0].y == 12
    assert out.anchors[0].variant == 1
    assert out.anchors[0].groupId == 7


def test_stroke_op_round_trip() -> None:
    from nhc.rendering.ir._fb.Outline import OutlineT
    from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily
    from nhc.rendering.ir._fb.StrokeOp import StrokeOp, StrokeOpT
    from nhc.rendering.ir._fb.WallMaterial import WallMaterialT
    from nhc.rendering.ir._fb.WallTreatment import WallTreatment
    from nhc.rendering.ir._fb.Vec2 import Vec2T

    src = StrokeOpT()
    src.regionRef = "room.7"
    src.outline = OutlineT()
    src.outline.vertices = [Vec2T(), Vec2T(), Vec2T()]
    src.wallMaterial = WallMaterialT()
    src.wallMaterial.family = MaterialFamily.Stone
    src.wallMaterial.style = 0
    src.wallMaterial.treatment = WallTreatment.Masonry
    src.wallMaterial.tone = 0
    src.wallMaterial.seed = 0x77

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = StrokeOp.GetRootAs(builder.Output(), 0)
    out = StrokeOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "room.7"
    assert out.wallMaterial.family == MaterialFamily.Stone
    assert out.wallMaterial.treatment == WallTreatment.Masonry


def test_hatch_op_uses_subtract_region_refs() -> None:
    from nhc.rendering.ir._fb.HatchKind import HatchKind
    from nhc.rendering.ir._fb.HatchOp import HatchOp, HatchOpT

    src = HatchOpT()
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
    parsed = HatchOp.GetRootAs(builder.Output(), 0)
    out = HatchOpT.InitFromObj(parsed)

    assert out.kind == HatchKind.Hole
    assert out.regionRef.decode() == "cave"
    assert [s.decode() for s in out.subtractRegionRefs] == ["dungeon"]
    assert out.extentTiles == 2.0
    assert out.seed == 777


def test_roof_op_carries_tone_seed_and_extended_styles() -> None:
    from nhc.rendering.ir._fb.RoofOp import RoofOp, RoofOpT
    from nhc.rendering.ir._fb.RoofStyle import RoofStyle
    from nhc.rendering.ir._fb.RoofTilePattern import RoofTilePattern

    src = RoofOpT()
    src.regionRef = "building.3"
    src.style = RoofStyle.Pyramid
    src.tone = 2
    src.tint = "#A07050"
    src.seed = 0xCAFE0003

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = RoofOp.GetRootAs(builder.Output(), 0)
    out = RoofOpT.InitFromObj(parsed)

    assert out.regionRef.decode() == "building.3"
    assert out.style == RoofStyle.Pyramid
    assert out.tone == 2
    assert out.tint.decode() == "#A07050"
    assert out.seed == 0xCAFE0003
    # sub_pattern defaults to Plain when not set — preserves
    # forward-compat with buffers written before the field was
    # appended to the table.
    assert out.subPattern == RoofTilePattern.Plain


def test_fixture_op_scale_defaults_to_unit() -> None:
    from nhc.rendering.ir._fb.Anchor import AnchorT
    from nhc.rendering.ir._fb.FixtureKind import FixtureKind
    from nhc.rendering.ir._fb.FixtureOp import FixtureOp, FixtureOpT

    src = FixtureOpT()
    src.regionRef = "cell.0.0"
    src.kind = FixtureKind.Chest
    src.seed = 0xC0FFEE
    src.anchors = [AnchorT()]

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = FixtureOp.GetRootAs(builder.Output(), 0)
    out = FixtureOpT.InitFromObj(parsed)

    # Forward-compat default — unset scale reads as 1.0.
    assert out.scale == 1.0


def test_fixture_op_round_trips_explicit_scale() -> None:
    from nhc.rendering.ir._fb.Anchor import AnchorT
    from nhc.rendering.ir._fb.FixtureKind import FixtureKind
    from nhc.rendering.ir._fb.FixtureOp import FixtureOp, FixtureOpT

    src = FixtureOpT()
    src.regionRef = "cell.1.2"
    src.kind = FixtureKind.Pillar
    src.seed = 0xDEAD0001
    src.anchors = [AnchorT()]
    src.scale = 3.0

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = FixtureOp.GetRootAs(builder.Output(), 0)
    out = FixtureOpT.InitFromObj(parsed)

    assert out.scale == 3.0


def test_roof_op_round_trips_explicit_sub_pattern() -> None:
    from nhc.rendering.ir._fb.RoofOp import RoofOp, RoofOpT
    from nhc.rendering.ir._fb.RoofStyle import RoofStyle
    from nhc.rendering.ir._fb.RoofTilePattern import RoofTilePattern

    src = RoofOpT()
    src.regionRef = "building.7"
    src.style = RoofStyle.Gable
    src.tone = 1
    src.tint = "#7A5A3A"
    src.seed = 0xDEAD0007
    src.subPattern = RoofTilePattern.Fishscale

    builder = flatbuffers.Builder(0)
    builder.Finish(src.Pack(builder))
    parsed = RoofOp.GetRootAs(builder.Output(), 0)
    out = RoofOpT.InitFromObj(parsed)

    assert out.style == RoofStyle.Gable
    assert out.subPattern == RoofTilePattern.Fishscale


# ── Op union — canonical 8-variant v5 set ─────────────────────


def test_op_union_exposes_canonical_eight_variants() -> None:
    """The Op union is the post-cut canonical set of 8 variants."""
    from nhc.rendering.ir._fb.Op import Op

    # Numeric values for canonical op variants — must remain stable.
    assert Op.NONE == 0
    assert Op.PaintOp == 1
    assert Op.StampOp == 2
    assert Op.PathOp == 3
    assert Op.FixtureOp == 4
    assert Op.StrokeOp == 5
    assert Op.ShadowOp == 6
    assert Op.HatchOp == 7
    assert Op.RoofOp == 8
    # v4-only variants are gone post-cut.
    assert not hasattr(Op, "FloorOp")
    assert not hasattr(Op, "ExteriorWallOp")


def test_floor_ir_major_is_5() -> None:
    """Schema major was bumped to 5 at the atomic cut."""
    from nhc.rendering.ir_emitter import SCHEMA_MAJOR

    assert SCHEMA_MAJOR == 5
