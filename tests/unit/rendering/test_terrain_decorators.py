"""Portability tests for the Phase 4 terrain decorators.

Each terrain (water / grass / lava / chasm) emits the same
decorator op regardless of floor kind: drop a single tile of the
matching terrain into a synthetic level and the corresponding
``TerrainDetailOp`` appears in the IR.

Phase 2.19 retired the Python emitter's ``class="terrain-..."``
SVG markers; portability is now checked at the IR layer.
"""

from __future__ import annotations

from nhc.dungeon.model import (
    Level, Rect, Room, Terrain, Tile,
)
from nhc.rendering.ir.structural import compute_structural
from nhc.rendering.ir_emitter import build_floor_ir


def _level_with_one_tile(terrain: Terrain) -> Level:
    level = Level.create_empty("L", "L", 1, 6, 6)
    for y in range(6):
        for x in range(6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.tiles[3][3] = Tile(terrain=terrain)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 6, 6))]
    return level


def _op_counts(level: Level, *, seed: int = 0) -> dict[str, int]:
    buf = bytes(build_floor_ir(level, seed=seed))
    return compute_structural(buf)["op_counts"]


class TestTerrainDecoratorPortability:
    def test_water_tile_renders_water_class(self) -> None:
        """Water tiles emit a ``TerrainDetailOp`` (the IR-level
        successor to the legacy ``class="terrain-water"`` SVG
        marker)."""
        counts = _op_counts(_level_with_one_tile(Terrain.WATER))
        assert counts.get("TerrainDetailOp", 0) >= 1

    def test_grass_tile_emits_no_detail_class(self) -> None:
        """Grass renders as tint-only; the per-tile blade
        strokes were removed because they're ~half of
        terrain_detail and visually noisy on town surfaces. The
        IR omits ``TerrainDetailOp`` on grass-only floors."""
        counts = _op_counts(_level_with_one_tile(Terrain.GRASS))
        assert counts.get("TerrainDetailOp", 0) == 0

    def test_lava_tile_renders_lava_class(self) -> None:
        """Lava tiles emit a ``TerrainDetailOp`` (the IR-level
        successor to the legacy ``class="terrain-lava"`` SVG
        marker)."""
        counts = _op_counts(_level_with_one_tile(Terrain.LAVA))
        assert counts.get("TerrainDetailOp", 0) >= 1

    def test_chasm_tile_renders_chasm_class(self) -> None:
        """Chasm tiles emit a ``TerrainDetailOp`` (the IR-level
        successor to the legacy ``class="terrain-chasm"`` SVG
        marker)."""
        counts = _op_counts(_level_with_one_tile(Terrain.CHASM))
        assert counts.get("TerrainDetailOp", 0) >= 1
