"""Phase 9.1a — emitter shape gate for ``TerrainDetailOp.tiles[]``.

Per §Phase 9 of ``plans/nhc_ir_migration_plan.md`` the terrain-detail
op grows a structured per-tile representation alongside the existing
``room_groups`` / ``corridor_groups`` passthrough. The tile list is
the authoritative input for the upcoming Rust port (Phase 9.1c) and
for the Python from-IR painter (Phase 9.1b).

Contract pinned here:

* ``tiles[]`` carries every WATER / LAVA / CHASM tile in row-major
  (y outer, x inner) order, regardless of dungeon-poly clipping.
* Each tile records the matching ``TerrainKind`` enum and a
  corridor flag mirroring ``_terrain_tile_bucket`` (``True`` iff
  the tile's ``surface_type`` is ``SurfaceType.CORRIDOR``).
* During the 9.1a transition the legacy ``room_groups`` /
  ``corridor_groups`` passthrough remains populated so byte-equal
  SVG parity holds; that part is covered by the existing
  ``test_emit_terrain_detail_parity`` gate.
"""
from __future__ import annotations

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.TerrainDetailOp import (
    TerrainDetailOp as TerrainDetailOpReader,
)
from nhc.rendering.ir._fb.TerrainKind import TerrainKind
from nhc.rendering.ir_emitter import build_floor_ir

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


_TERRAIN_TO_KIND = {
    Terrain.WATER: TerrainKind.Water,
    Terrain.LAVA: TerrainKind.Lava,
    Terrain.CHASM: TerrainKind.Chasm,
}


def _build_buf(inputs):
    return build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )


def _expected_tiles(
    inputs,
) -> list[tuple[int, int, int, bool]]:
    """Re-derive the structured tile list the emitter should produce.

    Mirrors the row-major tile walk the legacy
    ``walk_and_paint`` pipeline does for ``_TERRAIN_DECORATORS``,
    flattened across the three terrain kinds in the order they
    appear during the walk.
    """
    level = inputs.level
    out: list[tuple[int, int, int, bool]] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            kind = _TERRAIN_TO_KIND.get(tile.terrain)
            if kind is None:
                continue
            is_corridor = tile.surface_type is SurfaceType.CORRIDOR
            out.append((x, y, kind, is_corridor))
    return out


def _terrain_detail_op(buf: bytes):
    fir = FloorIR.GetRootAs(buf, 0)
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.TerrainDetailOp:
            continue
        op = TerrainDetailOpReader()
        op.Init(entry.Op().Bytes, entry.Op().Pos)
        return op
    return None


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_tiles_match_terrain_walk(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    expected = _expected_tiles(inputs)
    op = _terrain_detail_op(_build_buf(inputs))
    if not expected:
        # Fixtures with no water/lava/chasm tiles emit no op at all.
        assert op is None, (
            f"{descriptor}: TerrainDetailOp emitted but no matching "
            f"terrain tiles exist"
        )
        return
    assert op is not None, (
        f"{descriptor}: emitter produced no TerrainDetailOp"
    )
    actual = [
        (
            op.Tiles(i).X(),
            op.Tiles(i).Y(),
            op.Tiles(i).Kind(),
            bool(op.Tiles(i).IsCorridor()),
        )
        for i in range(op.TilesLength())
    ]
    assert actual == expected, (
        f"{descriptor}: TerrainDetailOp.tiles[] does not match the "
        f"row-major water/lava/chasm walk (len actual={len(actual)} "
        f"expected={len(expected)})"
    )
