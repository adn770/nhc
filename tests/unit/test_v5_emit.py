"""Tests for the v5 emit translators (Phase 1.4).

Each translator under ``nhc.rendering.v5_emit.*`` is pure: it
takes a v4 op (or list) and returns a v5 op (or list). The tests
build synthetic v4 op fixtures and assert the translator produces
the expected v5 shape per the contract in
``design/map_ir_v5.md`` §3 / §4.
"""

from __future__ import annotations

from typing import Any

import flatbuffers

from nhc.rendering.ir._fb import FloorIR as FloorIRMod
from nhc.rendering.ir._fb.CobblePattern import CobblePattern
from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.DecoratorOp import DecoratorOpT
from nhc.rendering.ir._fb.ExteriorWallOp import ExteriorWallOpT
from nhc.rendering.ir._fb.FloorOp import FloorOpT
from nhc.rendering.ir._fb.FloorStyle import FloorStyle
from nhc.rendering.ir._fb.InteriorWallOp import InteriorWallOpT
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.RegionKind import RegionKind
from nhc.rendering.ir._fb.RoofOp import RoofOpT
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.TileCoord import TileCoordT
from nhc.rendering.ir._fb.TreeFeatureOp import TreeFeatureOpT
from nhc.rendering.ir._fb.V5FixtureKind import V5FixtureKind
from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5PathStyle import V5PathStyle
from nhc.rendering.ir._fb.V5RoofStyle import V5RoofStyle
from nhc.rendering.ir._fb.V5WallTreatment import V5WallTreatment
from nhc.rendering.ir._fb.WallStyle import WallStyle
from nhc.rendering.ir._fb.CartTracksVariant import CartTracksVariantT
from nhc.rendering.ir._fb.CobblestoneVariant import CobblestoneVariantT
from nhc.rendering.ir._fb.OreDepositVariant import OreDepositVariantT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.Vec2 import Vec2T


# ── materials.py — factory + v4→v5 mappings ────────────────────


def test_material_from_floor_style_dungeon_is_plain() -> None:
    from nhc.rendering.v5_emit.materials import material_from_floor_style

    m = material_from_floor_style(FloorStyle.DungeonFloor, seed=42)
    assert m.family == V5MaterialFamily.Plain
    assert m.style == 0
    assert m.subPattern == 0
    assert m.tone == 0
    assert m.seed == 42


def test_material_from_floor_style_wood_is_oak_plank_medium() -> None:
    from nhc.rendering.v5_emit.materials import material_from_floor_style

    m = material_from_floor_style(FloorStyle.WoodFloor)
    assert m.family == V5MaterialFamily.Wood
    assert m.style == 0  # Oak
    assert m.subPattern == 0  # Plank
    assert m.tone == 1  # Medium


def test_material_from_floor_style_cave_is_limestone() -> None:
    from nhc.rendering.v5_emit.materials import material_from_floor_style

    m = material_from_floor_style(FloorStyle.CaveFloor)
    assert m.family == V5MaterialFamily.Cave
    assert m.style == 0  # Limestone


def test_material_from_cobble_pattern_brick_is_running_bond() -> None:
    from nhc.rendering.v5_emit.materials import material_from_cobble_pattern

    m = material_from_cobble_pattern(CobblePattern.Brick, seed=7)
    assert m.family == V5MaterialFamily.Stone
    assert m.style == 1  # Brick
    assert m.subPattern == 0  # RunningBond


def test_wall_material_from_masonry_brick() -> None:
    from nhc.rendering.v5_emit.materials import wall_material_from_wall_style

    wm = wall_material_from_wall_style(WallStyle.MasonryBrick, seed=99)
    assert wm.family == V5MaterialFamily.Stone
    assert wm.style == 1  # Brick
    assert wm.treatment == V5WallTreatment.Masonry
    assert wm.cornerStyle == CornerStyle.Merlon
    assert wm.seed == 99


def test_wall_material_palisade_uses_wood_family() -> None:
    from nhc.rendering.v5_emit.materials import wall_material_from_wall_style

    wm = wall_material_from_wall_style(WallStyle.Palisade)
    assert wm.family == V5MaterialFamily.Wood
    assert wm.treatment == V5WallTreatment.Palisade


def test_wall_material_fortification_uses_stone_with_corner_style() -> None:
    from nhc.rendering.v5_emit.materials import wall_material_from_wall_style

    wm = wall_material_from_wall_style(
        WallStyle.FortificationMerlon, corner_style=CornerStyle.Diamond
    )
    assert wm.treatment == V5WallTreatment.Fortification
    assert wm.cornerStyle == CornerStyle.Diamond


# ── regions.py — Region → V5Region ─────────────────────────────


def test_region_translation_drops_kind_adds_parent_id_and_cuts() -> None:
    from nhc.rendering.v5_emit.regions import translate_region

    src = RegionT()
    src.id = "room.7"
    src.kind = RegionKind.Room
    src.shapeTag = "octagon"
    src.outline = OutlineT()
    src.outline.descriptorKind = OutlineKind.Polygon
    src.outline.closed = True
    src.outline.vertices = [Vec2T(), Vec2T(), Vec2T()]

    out = translate_region(src)
    assert out.id == "room.7"
    assert out.shapeTag == "octagon"
    # ``kind`` does not exist on V5RegionT
    assert not hasattr(out, "kind")
    assert out.parentId == ""
    assert out.cuts == []
    assert out.outline is src.outline


# ── paint.py — FloorOp + DecoratorOp → V5PaintOp ───────────────


def _floor_op_entry(style: int, region_ref: str) -> OpEntryT:
    op = FloorOpT()
    op.style = style
    op.regionRef = region_ref
    entry = OpEntryT()
    entry.opType = Op.FloorOp
    entry.op = op
    return entry


def _decorator_op_entry(*, region_ref: str, seed: int = 333) -> OpEntryT:
    deco = DecoratorOpT()
    deco.regionRef = region_ref
    deco.seed = seed
    deco.theme = "dungeon"
    return _wrap_decorator(deco)


def _wrap_decorator(deco: DecoratorOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.DecoratorOp
    entry.op = deco
    return entry


def test_translate_floor_op_dungeon_emits_plain_paint_op() -> None:
    from nhc.rendering.v5_emit.paint import translate_paint_ops

    entry = _floor_op_entry(FloorStyle.DungeonFloor, "room.0")
    out = translate_paint_ops([entry])
    assert len(out) == 1
    assert out[0].opType == V5Op.V5PaintOp
    paint_op = out[0].op
    assert paint_op.regionRef == "room.0"
    assert paint_op.material.family == V5MaterialFamily.Plain


def test_translate_floor_op_wood_emits_wood_paint_op() -> None:
    from nhc.rendering.v5_emit.paint import translate_paint_ops

    entry = _floor_op_entry(FloorStyle.WoodFloor, "building.0")
    out = translate_paint_ops([entry])
    paint_op = out[0].op
    assert paint_op.material.family == V5MaterialFamily.Wood
    assert paint_op.material.style == 0  # Oak
    assert paint_op.material.subPattern == 0  # Plank
    assert paint_op.material.tone == 1  # Medium


def test_translate_decorator_cobblestone_emits_stone_paint_op() -> None:
    from nhc.rendering.v5_emit.paint import translate_paint_ops

    deco = DecoratorOpT()
    deco.regionRef = "dungeon"
    deco.seed = 333
    cob = CobblestoneVariantT()
    cob.tiles = [TileCoordT(), TileCoordT()]
    cob.pattern = CobblePattern.Cobble
    deco.cobblestone = [cob]

    entry = _wrap_decorator(deco)
    out = translate_paint_ops([entry])
    assert len(out) == 1
    assert out[0].op.material.family == V5MaterialFamily.Stone
    assert out[0].op.material.style == 0  # Cobblestone
    assert out[0].op.material.subPattern == 0  # Herringbone (default)


def test_translate_decorator_skips_empty_variants() -> None:
    from nhc.rendering.v5_emit.paint import translate_paint_ops

    deco = DecoratorOpT()
    deco.regionRef = "dungeon"
    cob = CobblestoneVariantT()
    cob.tiles = []  # empty — should be skipped
    deco.cobblestone = [cob]

    entry = _wrap_decorator(deco)
    out = translate_paint_ops([entry])
    assert out == []


# ── stroke.py — wall ops → V5StrokeOp ──────────────────────────


def test_translate_exterior_wall_emits_v5_stroke_with_region_ref() -> None:
    from nhc.rendering.v5_emit.stroke import translate_stroke_ops

    ext = ExteriorWallOpT()
    ext.style = WallStyle.MasonryBrick
    ext.cornerStyle = CornerStyle.Merlon
    ext.regionRef = "building.0"
    ext.rngSeed = 17

    entry = OpEntryT()
    entry.opType = Op.ExteriorWallOp
    entry.op = ext

    out = translate_stroke_ops([entry])
    assert len(out) == 1
    assert out[0].opType == V5Op.V5StrokeOp
    stroke = out[0].op
    assert stroke.regionRef == "building.0"
    assert stroke.outline is None
    assert stroke.wallMaterial.family == V5MaterialFamily.Stone
    assert stroke.wallMaterial.treatment == V5WallTreatment.Masonry
    assert stroke.wallMaterial.seed == 17


def test_translate_interior_wall_carries_outline_and_cuts() -> None:
    from nhc.rendering.v5_emit.stroke import translate_stroke_ops

    interior = InteriorWallOpT()
    interior.style = WallStyle.PartitionWood
    interior.outline = OutlineT()
    interior.outline.closed = False
    interior.outline.vertices = [Vec2T(), Vec2T()]

    entry = OpEntryT()
    entry.opType = Op.InteriorWallOp
    entry.op = interior

    out = translate_stroke_ops([entry])
    stroke = out[0].op
    assert stroke.regionRef == ""
    assert stroke.outline is interior.outline
    assert stroke.wallMaterial.treatment == V5WallTreatment.Partition
    assert stroke.wallMaterial.family == V5MaterialFamily.Wood


# ── roof.py — RoofOp → V5RoofOp ────────────────────────────────


def test_translate_roof_op_carries_seed_and_tint() -> None:
    from nhc.rendering.v5_emit.roof import translate_roof_ops

    roof = RoofOpT()
    roof.regionRef = "building.0"
    roof.style = RoofStyle.Simple
    roof.tint = "#A07050"
    roof.rngSeed = 0xCAFE

    entry = OpEntryT()
    entry.opType = Op.RoofOp
    entry.op = roof

    out = translate_roof_ops([entry])
    assert len(out) == 1
    assert out[0].opType == V5Op.V5RoofOp
    v5 = out[0].op
    assert v5.regionRef == "building.0"
    assert v5.style == V5RoofStyle.Simple
    assert v5.tint == "#A07050"
    assert v5.seed == 0xCAFE


# ── path.py — DecoratorOp.cart_tracks / ore_deposit → V5PathOp ─


def test_translate_cart_tracks_emits_v5_path_op_with_cart_tracks_style() -> None:
    from nhc.rendering.v5_emit.path import translate_path_ops

    deco = DecoratorOpT()
    deco.regionRef = "corridor"
    deco.seed = 555
    ct = CartTracksVariantT()
    ct.tiles = [TileCoordT(), TileCoordT()]
    deco.cartTracks = [ct]

    entry = OpEntryT()
    entry.opType = Op.DecoratorOp
    entry.op = deco

    out = translate_path_ops([entry])
    assert len(out) == 1
    assert out[0].opType == V5Op.V5PathOp
    path_op = out[0].op
    assert path_op.regionRef == "corridor"
    assert path_op.style == V5PathStyle.CartTracks
    assert path_op.seed == 555


def test_translate_ore_deposit_emits_v5_path_op_with_ore_vein_style() -> None:
    from nhc.rendering.v5_emit.path import translate_path_ops

    deco = DecoratorOpT()
    deco.regionRef = "cave"
    deco.seed = 12
    ore = OreDepositVariantT()
    ore.tiles = [TileCoordT()]
    deco.oreDeposit = [ore]

    entry = OpEntryT()
    entry.opType = Op.DecoratorOp
    entry.op = deco

    out = translate_path_ops([entry])
    assert out[0].op.style == V5PathStyle.OreVein


# ── fixture.py — feature ops → V5FixtureOp ─────────────────────


def test_translate_tree_feature_emits_free_anchors_then_grove() -> None:
    from nhc.rendering.v5_emit.fixture import translate_fixtures

    tree = TreeFeatureOpT()
    tree.seed = 42
    tree.tiles = [TileCoordT(), TileCoordT()]  # 2 free trees
    grove_tiles = [TileCoordT(), TileCoordT(), TileCoordT()]
    tree.groveTiles = grove_tiles
    tree.groveSizes = [3]  # one grove of 3

    entry = OpEntryT()
    entry.opType = Op.TreeFeatureOp
    entry.op = tree

    out = translate_fixtures([entry])
    # 2 fixture ops: free trees + 1 grove
    assert len(out) == 2
    free_op = out[0].op
    grove_op = out[1].op
    assert free_op.kind == V5FixtureKind.Tree
    assert len(free_op.anchors) == 2
    assert all(a.groupId == 0 for a in free_op.anchors)
    assert grove_op.kind == V5FixtureKind.Tree
    assert len(grove_op.anchors) == 3
    assert all(a.groupId == 1 for a in grove_op.anchors)


# ── End-to-end round-trip: build_floor_ir populates v5_regions / v5_ops ──


def test_build_floor_ir_populates_v5_regions_and_v5_ops() -> None:
    """Smoke: a real ``build_floor_ir`` call produces a buffer with
    ``v5_regions`` and ``v5_ops`` populated alongside the v4 fields."""
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering.ir_emitter import build_floor_ir

    params = GenerationParams(
        width=24, height=16, depth=1, seed=42, theme="dungeon",
        shape_variety=0.0,
    )
    level = generate_level(params)
    buf = build_floor_ir(level, seed=42)

    fir = FloorIRMod.FloorIR.GetRootAs(buf, 0)
    # Mainline v4 regions / ops populated as before.
    assert fir.RegionsLength() > 0
    assert fir.OpsLength() > 0
    # v5 scaffold: regions count matches; v5_ops at least one entry
    # since the level emits FloorOps + wall ops.
    assert fir.V5RegionsLength() == fir.RegionsLength()
    assert fir.V5OpsLength() > 0
