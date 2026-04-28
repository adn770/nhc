"""Sub-step 3.b — emitter shape gate for ``FloorDetailOp``.

Per §8 of ``plans/nhc_ir_migration_plan.md`` (Q5 step 3, locked
2026-04-28), the floor-detail emitter ships the post-filter
candidate tile set in ``op.tiles[]`` with a parallel
``is_corridor[]`` bit array marking corridor / door tiles. The
shared ``random.Random(seed + 99)`` painter walk consumes the
list in the same y-major / x-minor order so SVG output stays
byte-equal during the transition.

This test pins the emitter contract against an independent
re-derivation of the legacy filter — guarding both the
iteration order and the corridor classification. Once the Rust
port lands at sub-step 3.d, the consumer side ports too; this
gate stays as the emitter contract.
"""
from __future__ import annotations

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.rendering._floor_detail import _is_door
from nhc.rendering._render_context import build_render_context
from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorDetailOp import (
    FloorDetailOp as FloorDetailOpReader,
)
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir_emitter import build_floor_ir

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


def _build_buf(inputs):
    return build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )


def _expected_candidates(
    inputs,
) -> tuple[list[tuple[int, int]], list[bool]]:
    """Re-derive the candidate set the emitter should produce.

    Mirrors the deterministic prefix of legacy
    ``_emit_floor_detail_ir``: walk all (x, y), keep floor tiles
    that are not stair features and not on a STREET / FIELD /
    GARDEN surface, and tag each with the corridor / door
    classification. Stops before the RNG-driven painter pass.
    """
    ctx = build_render_context(
        inputs.level,
        seed=inputs.seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    level = ctx.level
    tiles: list[tuple[int, int]] = []
    is_corridor: list[bool] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain != Terrain.FLOOR:
                continue
            if tile.feature in ("stairs_up", "stairs_down"):
                continue
            if tile.surface_type in (
                SurfaceType.STREET,
                SurfaceType.FIELD,
                SurfaceType.GARDEN,
            ):
                continue
            tiles.append((x, y))
            is_corridor.append(
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
            )
    return tiles, is_corridor


def _floor_detail_op(buf: bytes):
    fir = FloorIR.GetRootAs(buf, 0)
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.FloorDetailOp:
            continue
        op = FloorDetailOpReader()
        op.Init(entry.Op().Bytes, entry.Op().Pos)
        return op
    return None


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_tiles_match_candidate_walk(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    expected_tiles, _ = _expected_candidates(inputs)
    op = _floor_detail_op(_build_buf(inputs))
    assert op is not None, (
        f"{descriptor}: emitter produced no FloorDetailOp"
    )
    actual = [
        (op.Tiles(i).X(), op.Tiles(i).Y())
        for i in range(op.TilesLength())
    ]
    assert actual == expected_tiles, (
        f"{descriptor}: FloorDetailOp.tiles[] does not match "
        f"the expected candidate walk (len actual={len(actual)} "
        f"expected={len(expected_tiles)})"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_is_corridor_matches_classification(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    _, expected_is_cor = _expected_candidates(inputs)
    op = _floor_detail_op(_build_buf(inputs))
    assert op is not None, (
        f"{descriptor}: emitter produced no FloorDetailOp"
    )
    actual = [
        bool(op.IsCorridor(i)) for i in range(op.IsCorridorLength())
    ]
    assert actual == expected_is_cor, (
        f"{descriptor}: FloorDetailOp.is_corridor[] does not "
        f"match the corridor / door classification"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_tiles_and_is_corridor_parallel(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    op = _floor_detail_op(_build_buf(inputs))
    assert op is not None
    assert op.TilesLength() == op.IsCorridorLength(), (
        f"{descriptor}: FloorDetailOp tiles[] length "
        f"{op.TilesLength()} != is_corridor[] length "
        f"{op.IsCorridorLength()}"
    )
