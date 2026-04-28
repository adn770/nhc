"""Sub-step 4.b — emitter shape gate for ``ThematicDetailOp``.

Per §8 of ``plans/nhc_ir_migration_plan.md`` (Q5 step 4, locked
2026-04-28), the thematic-detail emitter ships the post-filter
candidate tile set in ``op.tiles[]`` (identical to
``FloorDetailOp.tiles[]`` from sub-step 3.b) plus parallel
``isCorridor[]`` and ``wallCorners[]`` arrays — the latter is a
4-bit bitmap encoding which tile corners are wall-adjacent
(legacy ``_tile_thematic_detail`` checked ``_is_floor`` against
the four neighbours; sub-step 4.b lifts those checks to the
emitter so the consumer doesn't need level access).

This test pins the emitter contract against an independent
re-derivation of the legacy filter. Once the Rust port lands at
sub-step 4.e, the consumer side ports too; this gate stays as
the emitter contract.
"""
from __future__ import annotations

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.rendering._floor_detail import _is_door
from nhc.rendering._svg_helpers import _is_floor
from nhc.rendering._render_context import build_render_context
from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.ThematicDetailOp import (
    ThematicDetailOp as ThematicDetailOpReader,
)
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


def _expected(
    inputs,
) -> tuple[list[tuple[int, int]], list[bool], list[int]]:
    """Re-derive the candidate set + per-tile metadata.

    Mirrors the deterministic walk in
    :func:`_floor_layers._floor_detail_candidates` plus the
    wall-corner bitmap computation in
    :func:`_floor_layers._emit_thematic_detail_ir`.
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
    wall_corners: list[int] = []
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
            bits = 0
            if not _is_floor(level, x, y - 1) and not _is_floor(level, x - 1, y):
                bits |= 0x01
            if not _is_floor(level, x, y - 1) and not _is_floor(level, x + 1, y):
                bits |= 0x02
            if not _is_floor(level, x, y + 1) and not _is_floor(level, x - 1, y):
                bits |= 0x04
            if not _is_floor(level, x, y + 1) and not _is_floor(level, x + 1, y):
                bits |= 0x08
            wall_corners.append(bits)
    return tiles, is_corridor, wall_corners


def _thematic_op(buf: bytes):
    fir = FloorIR.GetRootAs(buf, 0)
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.ThematicDetailOp:
            continue
        op = ThematicDetailOpReader()
        op.Init(entry.Op().Bytes, entry.Op().Pos)
        return op
    return None


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_tiles_match_candidate_walk(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    expected_tiles, _, _ = _expected(inputs)
    op = _thematic_op(_build_buf(inputs))
    assert op is not None, (
        f"{descriptor}: emitter produced no ThematicDetailOp"
    )
    actual = [
        (op.Tiles(i).X(), op.Tiles(i).Y())
        for i in range(op.TilesLength())
    ]
    assert actual == expected_tiles, (
        f"{descriptor}: ThematicDetailOp.tiles[] does not match "
        f"the expected candidate walk (len actual={len(actual)} "
        f"expected={len(expected_tiles)})"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_is_corridor_matches_classification(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    _, expected_is_cor, _ = _expected(inputs)
    op = _thematic_op(_build_buf(inputs))
    assert op is not None
    actual = [
        bool(op.IsCorridor(i)) for i in range(op.IsCorridorLength())
    ]
    assert actual == expected_is_cor


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_wall_corners_match_re_derivation(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    _, _, expected_corners = _expected(inputs)
    op = _thematic_op(_build_buf(inputs))
    assert op is not None
    actual = [
        int(op.WallCorners(i))
        for i in range(op.WallCornersLength())
    ]
    assert actual == expected_corners, (
        f"{descriptor}: ThematicDetailOp.wallCorners[] does not "
        f"match the re-derived 4-bit bitmap"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_arrays_parallel(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    op = _thematic_op(_build_buf(inputs))
    assert op is not None
    n = op.TilesLength()
    assert op.IsCorridorLength() == n, (
        f"{descriptor}: tiles[] / isCorridor[] length mismatch"
    )
    assert op.WallCornersLength() == n, (
        f"{descriptor}: tiles[] / wallCorners[] length mismatch"
    )
