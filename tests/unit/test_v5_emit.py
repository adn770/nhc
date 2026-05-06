"""Tests for the v5 emit pipeline.

Each module under :mod:`nhc.rendering.v5_emit` exports an
``emit_*(builder)`` function that walks ``builder.ctx`` /
``regions`` / ``site`` to produce the v5 op stream directly. The
tests below build a real :class:`FloorIRBuilder` against a
synthetic level + ctx and assert the resulting v5 op shapes.
"""

from __future__ import annotations

from nhc.rendering.ir._fb import FloorIR as FloorIRMod
from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.RegionKind import RegionKind
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.V5FixtureKind import V5FixtureKind
from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5RoofStyle import V5RoofStyle
from nhc.rendering.ir._fb.V5WallTreatment import V5WallTreatment
from nhc.rendering.ir._fb.Vec2 import Vec2T
from nhc.rendering.ir._fb.WallStyle import WallStyle


# ── materials.py — factory invariants ──────────────────────────


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


def test_translate_region_drops_kind_adds_parent_id_and_cuts() -> None:
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
    assert not hasattr(out, "kind")
    assert out.parentId == ""
    assert out.cuts == []
    assert out.outline is src.outline


# ── End-to-end round-trip: build_floor_ir populates v5 fields ──


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
    assert fir.RegionsLength() > 0
    assert fir.OpsLength() > 0
    assert fir.V5RegionsLength() == fir.RegionsLength()
    assert fir.V5OpsLength() > 0


# ── emit_shadows(builder) ──────────────────────────────────────


def test_emit_shadows_returns_empty_when_shadows_disabled() -> None:
    """``ctx.shadows_enabled = False`` (e.g. on building floors)
    skips the layer entirely — :func:`emit_shadows` returns []."""

    class _StubCtx:
        shadows_enabled = False
        level = None

    class _StubBuilder:
        ctx = _StubCtx()

    from nhc.rendering.v5_emit import emit_shadows

    assert emit_shadows(_StubBuilder()) == []


def test_emit_shadows_smoke() -> None:
    """``emit_shadows(builder)`` produces ShadowOp entries for a
    real level: one Room shadow per room (gated through
    _room_region_data) plus one aggregated Corridor shadow."""
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder
    from nhc.rendering.v5_emit import emit_shadows

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

    shadows = emit_shadows(builder)
    assert all(s.opType == V5Op.ShadowOp for s in shadows)
    # At least one Room shadow + the merged Corridor shadow.
    assert len(shadows) >= 2


# ── emit_roofs(builder) ────────────────────────────────────────


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


# ── emit_all(builder) — orchestrator ───────────────────────────


def test_emit_all_returns_same_count_via_build_floor_ir() -> None:
    """``emit_all`` is the canonical entry point used by
    :meth:`FloorIRBuilder.finish`. Exercise it through the public
    ``build_floor_ir`` to confirm the v5 stream stays non-empty
    across the full IR_STAGES pipeline."""
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder, IR_STAGES
    from nhc.rendering.v5_emit import emit_all

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

    v5_regions, v5_ops = emit_all(builder)
    assert len(v5_regions) == len(builder.regions)
    # Every op kind that the v5 pipeline produces should land in
    # v5_ops; assert presence of at least Paint + Stroke + Shadow
    # for a baseline dungeon fixture.
    op_types = {entry.opType for entry in v5_ops}
    assert V5Op.V5PaintOp in op_types
    assert V5Op.V5StrokeOp in op_types
    assert V5Op.ShadowOp in op_types
    assert V5Op.V5FixtureOp in op_types
