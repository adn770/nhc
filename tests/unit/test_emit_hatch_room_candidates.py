"""Sub-step 1.b — emitter shape gate for ``HatchOp(kind=Room)``.

Per §8 of ``plans/nhc_ir_migration_plan.md`` (Boundary B, locked
2026-04-28), the room-hatch emitter no longer ships the floor-tile
set in ``op.tiles[]``; it ships the candidate hatch tiles
(post-Perlin distance filter) in row-major order, plus a parallel
``is_outer[]`` bit array that flags ``dist > base_distance_limit *
0.5``. The 10 % RNG skip moves to the consumer (Python handler
during the transition; Rust handler after the port).

This test pins that shape against an independent re-derivation of
the legacy filter — guarding both the iteration order and the
``is_outer`` semantics. Once the Rust port lands, the consumer
side ports too; this gate stays as the emitter contract.
"""

from __future__ import annotations

import math

import pytest
from shapely.geometry import Point

from nhc.dungeon.model import Terrain
from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._render_context import build_render_context
from nhc.rendering._svg_helpers import CELL
from nhc.rendering import _perlin as _noise
from nhc.rendering.ir._fb import HatchKind, Op
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


def _expected_room_candidates(
    inputs,
) -> tuple[list[tuple[int, int]], list[bool]]:
    """Re-derive the candidate set the emitter should produce.

    Mirrors the deterministic prefix of legacy ``_render_hatching``
    (the candidate walk + Perlin distance filter), stopping before
    the RNG-driven 10 % skip. Returns the tiles in iteration order
    plus an ``is_outer`` flag per tile (``False`` in cave mode so
    the consumer's skip-gate short-circuits cleanly).
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
    dungeon_poly = ctx.dungeon_poly
    if dungeon_poly is None or dungeon_poly.is_empty:
        return [], []
    cave_mode = ctx.cave_wall_poly is not None
    boundary = dungeon_poly.boundary
    base_distance_limit = ctx.hatch_distance * CELL

    floor_set: set[tuple[int, int]] = set()
    for ty in range(level.height):
        for tx in range(level.width):
            if level.tiles[ty][tx].terrain == Terrain.FLOOR:
                floor_set.add((tx, ty))

    tiles: list[tuple[int, int]] = []
    is_outer: list[bool] = []
    for gy in range(-1, level.height + 1):
        for gx in range(-1, level.width + 1):
            if (gx, gy) in floor_set:
                continue
            min_dist = float("inf")
            for ddx in range(-2, 3):
                for ddy in range(-2, 3):
                    if (gx + ddx, gy + ddy) in floor_set:
                        d = math.hypot(ddx, ddy) * CELL
                        if d < min_dist:
                            min_dist = d
            if min_dist == float("inf"):
                center = Point(
                    (gx + 0.5) * CELL, (gy + 0.5) * CELL,
                )
                min_dist = boundary.distance(center)
            dist = min_dist
            if not cave_mode:
                noise_var = (
                    _noise.pnoise2(gx * 0.3, gy * 0.3, base=50)
                    * CELL * 0.8
                )
                tile_limit = base_distance_limit + noise_var
            else:
                tile_limit = base_distance_limit
            if dist > tile_limit:
                continue
            tiles.append((gx, gy))
            is_outer.append(
                (not cave_mode)
                and dist > base_distance_limit * 0.5
            )
    return tiles, is_outer


def _room_hatch_op(buf: bytes):
    fir = FloorIR.GetRootAs(buf, 0)
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.HatchOp:
            continue
        from nhc.rendering.ir._fb.HatchOp import HatchOp as HatchOpReader
        op = HatchOpReader()
        op.Init(entry.Op().Bytes, entry.Op().Pos)
        if op.Kind() == HatchKind.HatchKind.Room:
            return op
    return None


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_room_tiles_match_candidate_walk(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    expected_tiles, _ = _expected_room_candidates(inputs)
    op = _room_hatch_op(_build_buf(inputs))
    assert op is not None, (
        f"{descriptor}: emitter produced no HatchOp(kind=Room)"
    )
    actual = [
        (op.Tiles(i).X(), op.Tiles(i).Y())
        for i in range(op.TilesLength())
    ]
    assert actual == expected_tiles, (
        f"{descriptor}: HatchOp(Room).tiles[] does not match "
        f"the expected candidate walk (len actual={len(actual)} "
        f"expected={len(expected_tiles)})"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_room_is_outer_matches_distance_threshold(
    descriptor: str,
) -> None:
    inputs = descriptor_inputs(descriptor)
    _, expected_is_outer = _expected_room_candidates(inputs)
    op = _room_hatch_op(_build_buf(inputs))
    assert op is not None, (
        f"{descriptor}: emitter produced no HatchOp(kind=Room)"
    )
    actual = [bool(op.IsOuter(i)) for i in range(op.IsOuterLength())]
    assert actual == expected_is_outer, (
        f"{descriptor}: HatchOp(Room).is_outer[] does not match "
        f"dist > base_distance_limit*0.5 (cave-aware)"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_room_tiles_and_is_outer_parallel(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    op = _room_hatch_op(_build_buf(inputs))
    assert op is not None
    assert op.TilesLength() == op.IsOuterLength(), (
        f"{descriptor}: HatchOp(Room) tiles[] length "
        f"{op.TilesLength()} != is_outer[] length "
        f"{op.IsOuterLength()}"
    )
