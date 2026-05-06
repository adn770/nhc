"""Portability tests for the Phase 4 terrain decorators.

Each terrain (water / grass / lava / chasm) emits the same
decorator op regardless of floor kind: drop a single tile of the
matching terrain into a synthetic level and the corresponding
v5 op appears in the IR.

Phase 4.1 of plans/nhc_pure_ir_v5_migration_plan.md migrated the
read-side off the v4 op stream. Water / lava surface motion now
reads as a V5StampOp ``decoratorMask`` bit (Ripples for water,
LavaCracks for lava); chasm carries through as a V5StampOp from
v5_emit's TerrainDetailOp translator.
"""

from __future__ import annotations

import json

from nhc.dungeon.model import (
    Level, Rect, Room, Terrain, Tile,
)
from nhc.rendering.ir.dump import dump
from nhc.rendering.ir_emitter import build_floor_ir


# Decorator bit values mirror ``stamp_op::bit::*`` in
# crates/nhc-render/src/transform/png/v5/stamp_op.rs.
_V5_BIT_RIPPLES = 1 << 3
_V5_BIT_LAVA_CRACKS = 1 << 4


def _level_with_one_tile(terrain: Terrain) -> Level:
    level = Level.create_empty("L", "L", 1, 6, 6)
    for y in range(6):
        for x in range(6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.tiles[3][3] = Tile(terrain=terrain)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 6, 6))]
    return level


def _v5_stamp_decorator_bit_set(level: Level, bit: int) -> bool:
    buf = bytes(build_floor_ir(level, seed=0))
    d = json.loads(dump(buf))
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "StampOp":
            continue
        mask = int((entry.get("op") or {}).get("decoratorMask", 0) or 0)
        if mask & bit:
            return True
    return False


def _v5_stamp_op_count(level: Level) -> int:
    buf = bytes(build_floor_ir(level, seed=0))
    d = json.loads(dump(buf))
    return sum(
        1 for e in (d.get("ops") or []) if e.get("opType") == "StampOp"
    )


class TestTerrainDecoratorPortability:
    def test_water_tile_renders_with_ripples_bit(self) -> None:
        """Water tiles emit a V5StampOp with the Ripples decorator
        bit set (the v5 successor to the v4
        ``class="terrain-water"`` SVG marker)."""
        assert _v5_stamp_decorator_bit_set(
            _level_with_one_tile(Terrain.WATER),
            _V5_BIT_RIPPLES,
        )

    def test_grass_tile_emits_no_terrain_detail_stamp(self) -> None:
        """Grass renders as tint-only; the v4 emitter does not
        produce a TerrainDetailOp for grass tiles, so v5_emit's
        TerrainDetailOp → V5StampOp translator emits nothing.
        Floor-grid + cracks/scratches stamps still ride other
        StampOps; pin only that the Ripples / LavaCracks bits
        stay zero."""
        level = _level_with_one_tile(Terrain.GRASS)
        assert not _v5_stamp_decorator_bit_set(level, _V5_BIT_RIPPLES)
        assert not _v5_stamp_decorator_bit_set(level, _V5_BIT_LAVA_CRACKS)

    def test_lava_tile_renders_with_lava_cracks_bit(self) -> None:
        """Lava tiles emit a V5StampOp with the LavaCracks
        decorator bit set."""
        assert _v5_stamp_decorator_bit_set(
            _level_with_one_tile(Terrain.LAVA),
            _V5_BIT_LAVA_CRACKS,
        )

    def test_chasm_tile_renders_at_least_one_stamp_op(self) -> None:
        """Chasm tiles emit a V5StampOp (chasm doesn't have a
        dedicated v5 decorator bit; the v5_emit's TerrainDetailOp
        translator ships the same Ripples | LavaCracks mask for
        every TerrainDetailOp regardless of terrain kind, so the
        portability invariant ``chasm tile → at least one V5StampOp``
        holds even though no chasm-specific bit fires)."""
        # Baseline (no chasm tile): floor grid still emits stamps
        # for the rest of the floor. Subtract that baseline to
        # isolate the chasm tile's contribution.
        baseline = _v5_stamp_op_count(_level_with_one_tile(Terrain.FLOOR))
        with_chasm = _v5_stamp_op_count(_level_with_one_tile(Terrain.CHASM))
        assert with_chasm > baseline, (
            f"adding a chasm tile must add at least one V5StampOp "
            f"(baseline {baseline}, with chasm {with_chasm})"
        )


# ── Terrain → PaintOp(Material) translator ─────────────────────


def _ops_referencing_region(level: Level, region_id_prefix: str) -> list[dict]:
    """Return all ops whose region_ref starts with ``region_id_prefix``."""
    buf = bytes(build_floor_ir(level, seed=0))
    d = json.loads(dump(buf))
    out: list[dict] = []
    for entry in (d.get("ops") or []):
        op = entry.get("op") or {}
        rr = op.get("regionRef") or ""
        if rr.startswith(region_id_prefix):
            out.append(entry)
    return out


def _regions(level: Level) -> list[dict]:
    buf = bytes(build_floor_ir(level, seed=0))
    d = json.loads(dump(buf))
    return d.get("regions") or []


def _region_ids(level: Level) -> set[str]:
    return {r.get("id", "") for r in _regions(level)}


class TestTerrainPaintOpTranslator:
    """Water / lava / chasm / grass tiles emit a PaintOp with the
    canonical v5 family material on a per-cluster region. Mirrors
    the v4 TerrainTintOp translucent-tint behaviour."""

    def test_water_tile_registers_water_region(self) -> None:
        ids = _region_ids(_level_with_one_tile(Terrain.WATER))
        assert "water.0" in ids, f"water region missing: {ids}"

    def test_water_tile_emits_paint_op_liquid_water(self) -> None:
        ops = _ops_referencing_region(
            _level_with_one_tile(Terrain.WATER), "water.",
        )
        paint_ops = [e for e in ops if e.get("opType") == "PaintOp"]
        assert len(paint_ops) >= 1, "no PaintOp on water region"
        material = paint_ops[0]["op"]["material"]
        assert material["family"] == "Liquid"
        assert material["style"] == 0  # LIQUID_WATER

    def test_lava_tile_registers_lava_region(self) -> None:
        ids = _region_ids(_level_with_one_tile(Terrain.LAVA))
        assert "lava.0" in ids

    def test_lava_tile_emits_paint_op_liquid_lava(self) -> None:
        ops = _ops_referencing_region(
            _level_with_one_tile(Terrain.LAVA), "lava.",
        )
        paint_ops = [e for e in ops if e.get("opType") == "PaintOp"]
        assert len(paint_ops) >= 1
        material = paint_ops[0]["op"]["material"]
        assert material["family"] == "Liquid"
        assert material["style"] == 1  # LIQUID_LAVA

    def test_chasm_tile_registers_chasm_region(self) -> None:
        ids = _region_ids(_level_with_one_tile(Terrain.CHASM))
        assert "chasm.0" in ids

    def test_chasm_tile_emits_paint_op_special_chasm(self) -> None:
        ops = _ops_referencing_region(
            _level_with_one_tile(Terrain.CHASM), "chasm.",
        )
        paint_ops = [e for e in ops if e.get("opType") == "PaintOp"]
        assert len(paint_ops) >= 1
        material = paint_ops[0]["op"]["material"]
        assert material["family"] == "Special"
        assert material["style"] == 0  # SPECIAL_CHASM

    def test_grass_tile_registers_grass_region(self) -> None:
        ids = _region_ids(_level_with_one_tile(Terrain.GRASS))
        assert "grass.0" in ids

    def test_grass_tile_emits_paint_op_earth_grass(self) -> None:
        ops = _ops_referencing_region(
            _level_with_one_tile(Terrain.GRASS), "grass.",
        )
        paint_ops = [e for e in ops if e.get("opType") == "PaintOp"]
        assert len(paint_ops) >= 1
        material = paint_ops[0]["op"]["material"]
        assert material["family"] == "Earth"
        assert material["style"] == 1  # EARTH_GRASS

    def test_pure_floor_emits_no_terrain_paint_ops(self) -> None:
        """Floor-only level registers no terrain regions and emits
        no terrain PaintOps. Ensures the translator only fires when
        terrain tiles exist."""
        level = _level_with_one_tile(Terrain.FLOOR)
        ids = _region_ids(level)
        for prefix in ("water.", "lava.", "chasm.", "grass."):
            assert not any(rid.startswith(prefix) for rid in ids), (
                f"floor-only level registered terrain region {prefix}*"
            )

    def test_two_disjoint_water_clusters_register_two_regions(self) -> None:
        """Two non-adjacent water tiles produce two regions.
        Mirrors the cave-system per-cluster pattern."""
        level = Level.create_empty("L", "L", 1, 10, 10)
        for y in range(10):
            for x in range(10):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.tiles[2][2] = Tile(terrain=Terrain.WATER)
        level.tiles[7][7] = Tile(terrain=Terrain.WATER)
        level.rooms = [Room(id="r1", rect=Rect(0, 0, 10, 10))]
        ids = _region_ids(level)
        assert "water.0" in ids and "water.1" in ids, (
            f"expected two water regions, got {sorted(ids)}"
        )


# ── ctx.macabre_detail flag plumbing ──────────────────────────


def _emit_thematic_with_macabre(
    macabre: bool,
) -> set[str]:
    """Emit thematic-detail FixtureOps with ``ctx.macabre_detail``
    forced to ``macabre``; return the set of FixtureKind names that
    appear."""
    import dataclasses
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering._cave_geometry import _build_cave_wall_geometry
    from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
    from nhc.rendering.ir_emitter import FloorIRBuilder
    from nhc.rendering.emit.thematic_detail import emit_thematic_details

    # 30×30 floor-only room — large enough for the per-tile
    # Pcg64Mcg gate to land at least one bone / skull when
    # macabre=True.
    level = Level.create_empty("L", "L", 1, 30, 30)
    for y in range(30):
        for x in range(30):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 30, 30))]
    ctx = build_render_context(
        level,
        seed=42,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
    )
    ctx = dataclasses.replace(ctx, macabre_detail=macabre)
    builder = FloorIRBuilder(ctx)
    ops = emit_thematic_details(builder)

    # FixtureKind values: Web=0, Skull=1, Bone=2.
    kinds_present: set[str] = set()
    for entry in ops:
        op = entry.op
        kind = op.kind
        if kind == 0:
            kinds_present.add("Web")
        elif kind == 1:
            kinds_present.add("Skull")
        elif kind == 2:
            kinds_present.add("Bone")
    return kinds_present


class TestMacabreDetailFlag:
    """``ctx.macabre_detail`` gates Skull / Bone fixture emission.

    Mirrors the v4 ``if not macabre_detail: bones, skulls = [], []``
    post-pass on the Rust thematic_detail painter.
    """

    def test_macabre_true_emits_skulls_and_bones(self) -> None:
        kinds = _emit_thematic_with_macabre(True)
        # At least one of skull / bone fires on a 30×30 floor at
        # seed=42; Web is independent of macabre.
        assert "Skull" in kinds or "Bone" in kinds, (
            f"macabre=True should emit Skull or Bone; got {sorted(kinds)}"
        )

    def test_macabre_false_drops_skulls_and_bones(self) -> None:
        kinds = _emit_thematic_with_macabre(False)
        assert "Skull" not in kinds, (
            f"macabre=False must not emit Skull; got {sorted(kinds)}"
        )
        assert "Bone" not in kinds, (
            f"macabre=False must not emit Bone; got {sorted(kinds)}"
        )

    def test_macabre_false_drops_loose_stones(self) -> None:
        """``emit_loose_stones`` mirrors the macabre gate: when
        ``ctx.macabre_detail`` is False, the v5 emit produces no
        LooseStone FixtureOps (the Rust helper returns an empty
        list for ``macabre=False``)."""
        import dataclasses
        from nhc.rendering._render_context import build_render_context
        from nhc.rendering._cave_geometry import _build_cave_wall_geometry
        from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
        from nhc.rendering.ir_emitter import FloorIRBuilder
        from nhc.rendering.emit.thematic_detail import emit_loose_stones

        level = Level.create_empty("L", "L", 1, 30, 30)
        for y in range(30):
            for x in range(30):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms = [Room(id="r1", rect=Rect(0, 0, 30, 30))]
        ctx = build_render_context(
            level, seed=42,
            cave_geometry_builder=_build_cave_wall_geometry,
            dungeon_polygon_builder=_build_dungeon_polygon,
        )
        ctx_off = dataclasses.replace(ctx, macabre_detail=False)
        builder = FloorIRBuilder(ctx_off)
        ops = emit_loose_stones(builder)
        assert ops == [], (
            f"macabre=False must not emit LooseStone; got {len(ops)} ops"
        )
