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


# ── emit_shadows(builder) — Phase 4.3a per-module migration ────


def test_emit_shadows_walks_builder_ctx_and_matches_translate_shadow_ops() -> None:
    """``emit_shadows(builder)`` derives the v5 ShadowOp stream from
    builder.ctx + level (no v4-op input). Asserts the output matches
    what ``translate_shadow_ops(builder.ops)`` would produce when v4
    emit also ran on the same builder."""
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder, IR_STAGES
    from nhc.rendering.v5_emit import emit_shadows, translate_shadow_ops

    params = GenerationParams(
        width=24, height=16, depth=1, seed=42, theme="dungeon",
        shape_variety=0.0,
    )
    level = generate_level(params)
    ctx = build_render_context(
        level,
        seed=42,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
    )
    builder = FloorIRBuilder(ctx)
    for stage in IR_STAGES:
        stage(builder)

    via_emit = emit_shadows(builder)
    via_translate = translate_shadow_ops(builder.ops)

    assert len(via_emit) == len(via_translate)
    for a, b in zip(via_emit, via_translate):
        assert a.opType == V5Op.ShadowOp
        assert b.opType == V5Op.ShadowOp
        assert a.op.kind == b.op.kind
        # Room shadows carry regionRef; Corridor shadows carry tiles.
        assert getattr(a.op, "regionRef", "") == getattr(
            b.op, "regionRef", ""
        )
        a_tiles = getattr(a.op, "tiles", None) or []
        b_tiles = getattr(b.op, "tiles", None) or []
        assert len(a_tiles) == len(b_tiles)


def test_emit_shadows_returns_empty_when_shadows_disabled() -> None:
    """``ctx.shadows_enabled = False`` (e.g. on building floors) skips
    the layer entirely — :func:`emit_shadows` returns an empty list."""

    class _StubCtx:
        shadows_enabled = False
        level = None

    class _StubBuilder:
        ctx = _StubCtx()

    from nhc.rendering.v5_emit import emit_shadows

    assert emit_shadows(_StubBuilder()) == []


# ── emit_roofs(builder) — Phase 4.3a per-module migration ──────


def test_emit_roofs_walks_building_regions_with_canonical_seeds() -> None:
    """``emit_roofs(builder)`` walks Building regions and emits one
    V5RoofOp each, with the same seed / tint algorithm as
    :func:`ir_emitter.emit_building_roofs`."""
    from nhc.rendering.ir_emitter import (
        FloorIRBuilder, _ROOF_TINTS, _SM64_MASK, _splitmix64_first,
        emit_building_regions,
    )
    from nhc.rendering.v5_emit import emit_roofs
    from nhc.dungeon.model import RectShape, Rect

    class _StubLevel:
        width = 32
        height = 24

    class _StubCtx:
        level = _StubLevel()
        seed = 0x42
        theme = "dungeon"
        floor_kind = "surface"
        shadows_enabled = False
        hatching_enabled = False
        atmospherics_enabled = False
        macabre_detail = False
        vegetation_enabled = False
        interior_finish = ""

    class _Building:
        def __init__(self) -> None:
            self.base_shape = RectShape()
            self.base_rect = Rect(2, 2, 4, 4)

    builder = FloorIRBuilder(_StubCtx())
    emit_building_regions(builder, [_Building(), _Building()])

    roofs = emit_roofs(builder)
    assert len(roofs) == 2
    for i, entry in enumerate(roofs):
        assert entry.opType == V5Op.V5RoofOp
        op = entry.op
        assert op.regionRef == f"building.{i}"
        assert op.style == V5RoofStyle.Simple
        rng_seed = (0x42 + 0xCAFE + i) & _SM64_MASK
        assert op.seed == rng_seed
        tint_seed = (rng_seed ^ 0xC0FFEE) & _SM64_MASK
        assert op.tint == _ROOF_TINTS[
            _splitmix64_first(tint_seed) % len(_ROOF_TINTS)
        ]


def test_emit_roofs_skips_non_surface_irs() -> None:
    """Roofs only fire on surface IRs (``ctx.floor_kind == "surface"``).
    Dungeon / cave / building-floor IRs skip the layer even if their
    builder happens to carry a Building region."""
    from nhc.rendering.ir_emitter import FloorIRBuilder, emit_building_regions
    from nhc.rendering.v5_emit import emit_roofs
    from nhc.dungeon.model import RectShape, Rect

    class _StubLevel:
        width = 16
        height = 16

    class _StubCtx:
        level = _StubLevel()
        seed = 0
        shadows_enabled = False
        hatching_enabled = False
        atmospherics_enabled = False
        macabre_detail = False
        vegetation_enabled = False
        theme = ""
        floor_kind = "building"
        interior_finish = ""

    class _Building:
        def __init__(self) -> None:
            self.base_shape = RectShape()
            self.base_rect = Rect(0, 0, 4, 4)

    builder = FloorIRBuilder(_StubCtx())
    emit_building_regions(builder, [_Building()])

    assert emit_roofs(builder) == []


# ── emit_hatches(builder) — Phase 4.3a per-module migration ────


def test_emit_hatches_walks_builder_ctx_and_matches_translate_hatch_ops() -> None:
    """``emit_hatches(builder)`` derives the v5 HatchOp stream from
    builder.ctx + level. Asserts the output matches what
    ``translate_hatch_ops(builder.ops)`` produces when v4 emit also
    ran on the same builder."""
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder, IR_STAGES
    from nhc.rendering.v5_emit import emit_hatches, translate_hatch_ops

    params = GenerationParams(
        width=24, height=16, depth=1, seed=42, theme="dungeon",
        shape_variety=0.0,
    )
    level = generate_level(params)
    ctx = build_render_context(
        level,
        seed=42,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
    )
    builder = FloorIRBuilder(ctx)
    for stage in IR_STAGES:
        stage(builder)

    via_emit = emit_hatches(builder)
    via_translate = translate_hatch_ops(builder.ops)

    assert len(via_emit) == len(via_translate)
    for a, b in zip(via_emit, via_translate):
        assert a.opType == V5Op.V5HatchOp
        assert b.opType == V5Op.V5HatchOp
        assert a.op.kind == b.op.kind
        a_tiles = a.op.tiles or []
        b_tiles = b.op.tiles or []
        assert len(a_tiles) == len(b_tiles)
        assert a.op.seed == b.op.seed


# ── emit_paths(builder) — Phase 4.3a per-module migration ──────


def test_emit_paths_walks_level_and_matches_translate_path_ops() -> None:
    """``emit_paths(builder)`` walks the level for cart-tracks / ore
    candidate tiles directly. Matches ``translate_path_ops(builder.ops)``
    when v4 emit also ran on the same builder."""
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder, IR_STAGES
    from nhc.rendering.v5_emit import emit_paths, translate_path_ops

    params = GenerationParams(
        width=24, height=16, depth=1, seed=42, theme="dungeon",
        shape_variety=0.0,
    )
    level = generate_level(params)
    ctx = build_render_context(
        level,
        seed=42,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
    )
    builder = FloorIRBuilder(ctx)
    for stage in IR_STAGES:
        stage(builder)

    via_emit = emit_paths(builder)
    via_translate = translate_path_ops(builder.ops)

    assert len(via_emit) == len(via_translate)
    for a, b in zip(via_emit, via_translate):
        assert a.opType == V5Op.V5PathOp
        assert b.opType == V5Op.V5PathOp
        assert a.op.style == b.op.style
        assert len(a.op.tiles or []) == len(b.op.tiles or [])
        assert a.op.seed == b.op.seed


# ── emit_stamps(builder) — Phase 4.3a per-module migration ─────


def test_emit_stamps_walks_level_and_matches_translate_stamp_ops() -> None:
    """``emit_stamps(builder)`` walks level tiles directly to derive
    the GridLines / Cracks|Scratches / Ripples|LavaCracks stamps.
    Asserts parity with ``translate_stamp_ops(builder.ops)`` when v4
    emit also ran on the same builder."""
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder, IR_STAGES
    from nhc.rendering.v5_emit import emit_stamps, translate_stamp_ops

    params = GenerationParams(
        width=24, height=16, depth=1, seed=42, theme="dungeon",
        shape_variety=0.0,
    )
    level = generate_level(params)
    ctx = build_render_context(
        level,
        seed=42,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
    )
    builder = FloorIRBuilder(ctx)
    for stage in IR_STAGES:
        stage(builder)

    via_emit = emit_stamps(builder)
    via_translate = translate_stamp_ops(builder.ops)

    assert len(via_emit) == len(via_translate)
    for a, b in zip(via_emit, via_translate):
        assert a.opType == V5Op.V5StampOp
        assert b.opType == V5Op.V5StampOp
        assert a.op.decoratorMask == b.op.decoratorMask
        assert a.op.seed == b.op.seed


# ── emit_all(builder) — Phase 4.3a entry point ─────────────────


def test_emit_all_takes_builder_and_returns_same_output_as_translate_all() -> None:
    """Phase 4.3a entry point: ``emit_all(builder)`` is the canonical
    way to populate v5 regions + ops from a FloorIRBuilder. It walks
    the builder's ctx / regions / site directly (no v4-op input).

    For this scaffolding commit, ``emit_all`` produces output structurally
    identical to ``translate_all(regions=builder.regions, ops=builder.ops)``
    — subsequent module-level commits replace each translator with a
    direct ctx-walk while keeping output invariant.
    """
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder, IR_STAGES
    from nhc.rendering.v5_emit import emit_all, translate_all

    params = GenerationParams(
        width=24, height=16, depth=1, seed=42, theme="dungeon",
        shape_variety=0.0,
    )
    level = generate_level(params)
    ctx = build_render_context(
        level,
        seed=42,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
    )
    builder = FloorIRBuilder(ctx)
    for stage in IR_STAGES:
        stage(builder)

    via_emit_all = emit_all(builder)
    via_translate_all = translate_all(
        regions=builder.regions, ops=builder.ops,
    )

    assert len(via_emit_all[0]) == len(via_translate_all[0])
    assert len(via_emit_all[1]) == len(via_translate_all[1])
    # Each pair lines up by op-type tag; exact field equality is
    # asserted by downstream parity gates.
    for a, b in zip(via_emit_all[1], via_translate_all[1]):
        assert a.opType == b.opType
