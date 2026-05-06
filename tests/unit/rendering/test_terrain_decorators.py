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
