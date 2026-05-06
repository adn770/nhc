"""Builder / ctx walk → ``V5OpEntry(V5HatchOp)``.

:func:`emit_hatches` walks ``builder.ctx`` + ``level`` directly
to produce v5 hatch ops — mirrors the source logic of
:func:`nhc.rendering._floor_layers._emit_hatch_ir` and adopts the
v5 anti-geometry convention (``region_in`` / ``region_out`` →
``region_ref`` + ``subtract_region_refs[]``) per
``design/map_ir_v5.md`` §2.4.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.V5HatchOp import V5HatchOpT
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT


def _wrap(hatch_op: V5HatchOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5HatchOp
    entry.op = hatch_op
    return entry


def emit_hatches(builder: Any) -> list[V5OpEntryT]:
    """Walk builder.ctx + level to produce V5HatchOp entries.

    Honours ``ctx.hatching_enabled`` (building floors and pre-revealed
    surfaces disable hatching). Order matches
    :func:`_floor_layers._emit_hatch_ir`: room halo first, then
    corridor halo.

    Defensive on synthetic fixture builders: if ``ctx.dungeon_poly``
    is missing / None and ``level`` lacks the per-tile grid the
    function returns whatever has been emitted so far (typically an
    empty list).
    """
    import math

    from shapely.geometry import Point

    from nhc.dungeon.model import SurfaceType, Terrain
    from nhc.rendering import _perlin as _noise
    from nhc.rendering._svg_helpers import CELL, _is_door
    from nhc.rendering.ir._fb import HatchKind
    from nhc.rendering.ir._fb.TileCoord import TileCoordT

    ctx = builder.ctx
    if not ctx.hatching_enabled:
        return []

    level = ctx.level
    base_seed = ctx.seed
    result: list[V5OpEntryT] = []

    dungeon_poly = getattr(ctx, "dungeon_poly", None)
    tiles_grid = getattr(level, "tiles", None)
    cave_wall_poly = getattr(ctx, "cave_wall_poly", None)
    hatch_distance = getattr(ctx, "hatch_distance", 2.0)

    # Room (perimeter) halo — gated on dungeon_poly + per-tile grid.
    if (
        dungeon_poly is not None
        and not dungeon_poly.is_empty
        and tiles_grid is not None
    ):
        cave_mode = cave_wall_poly is not None
        boundary = dungeon_poly.boundary
        base_distance_limit = hatch_distance * CELL

        floor_set: set[tuple[int, int]] = set()
        for ty in range(level.height):
            for tx in range(level.width):
                if level.tiles[ty][tx].terrain == Terrain.FLOOR:
                    floor_set.add((tx, ty))

        candidate_tiles: list[TileCoordT] = []
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
                t = TileCoordT()
                t.x = gx
                t.y = gy
                candidate_tiles.append(t)
                is_outer.append(
                    (not cave_mode)
                    and dist > base_distance_limit * 0.5
                )

        op = V5HatchOpT()
        op.kind = HatchKind.HatchKind.Room
        op.regionRef = ""
        op.subtractRegionRefs = ["dungeon"]
        op.tiles = candidate_tiles
        op.isOuter = is_outer
        op.seed = base_seed
        op.extentTiles = hatch_distance
        op.hatchUnderlayColor = ""
        result.append(_wrap(op))

    # Corridor halo — gated on per-tile grid.
    if tiles_grid is None:
        return result

    hatch_tiles: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
            ):
                continue
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if not level.in_bounds(nx, ny):
                    continue
                nb = level.tiles[ny][nx]
                if (
                    nb.terrain == Terrain.VOID
                    and nb.surface_type != SurfaceType.CORRIDOR
                ):
                    hatch_tiles.add((nx, ny))
    if not hatch_tiles:
        return result

    tiles: list[TileCoordT] = []
    for tx, ty in sorted(hatch_tiles):
        t = TileCoordT()
        t.x = tx
        t.y = ty
        tiles.append(t)

    op = V5HatchOpT()
    op.kind = HatchKind.HatchKind.Corridor
    op.regionRef = ""
    op.subtractRegionRefs = []
    op.tiles = tiles
    op.isOuter = []
    op.seed = base_seed + 7
    op.extentTiles = hatch_distance
    op.hatchUnderlayColor = ""
    result.append(_wrap(op))

    return result
