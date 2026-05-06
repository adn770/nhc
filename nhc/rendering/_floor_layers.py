"""Pure tile-walk + geometry-grouping helpers for the v5 emit pipeline.

The v4 stage-emit functions (``_emit_*_ir``) retired with the
schema-5 cut. What remains here are the per-tile classification
and connected-component helpers that survived because the
canonical emit pipeline (``nhc.rendering.emit.*``) walks the same
tile sets:

- :func:`_collect_corridor_tiles` — every corridor / door tile on
  a level, excluding cave tiles. Shared between
  :func:`emit_regions` (corridor Region outline) and
  :func:`nhc.rendering.emit.stroke.emit_strokes` (corridor wall op).
- :func:`_collect_corridor_components` — partitions a corridor
  tile set into disjoint connected components (one ring per
  component on the corridor Region's multi-ring outline).
- :func:`_collect_cave_systems` — partitions a cave tile set into
  disjoint cave systems (one ``Region(id="cave.<i>")`` per system).
- :func:`_floor_detail_candidates` — every floor tile eligible for
  decorator-bit overlays + per-tile corridor / door classification.
  Shared between :mod:`nhc.rendering.emit.stamp` and
  :mod:`nhc.rendering.emit.thematic_detail` so both walk identical
  candidate lists.
"""

from __future__ import annotations

from typing import Any, Iterable

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.rendering._svg_helpers import _is_door


def _collect_corridor_tiles(
    level: Any,
    cave_tiles: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Collect every corridor (or door) tile on ``level``.

    Walks the level row-major, picks tiles whose terrain is FLOOR /
    WATER / GRASS / LAVA AND whose surface_type is CORRIDOR (or
    whose feature carries ``"door"``), excluding any tile already
    covered by ``cave_tiles``.
    """
    tiles: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            if (x, y) in cave_tiles:
                continue
            tile = level.tiles[y][x]
            if tile.terrain not in (
                Terrain.FLOOR, Terrain.WATER,
                Terrain.GRASS, Terrain.LAVA,
            ):
                continue
            if (
                tile.surface_type == SurfaceType.CORRIDOR
                or (tile.feature and "door" in (tile.feature or ""))
            ):
                tiles.add((x, y))
    return tiles


def _collect_corridor_components(
    corridor_tiles: set[tuple[int, int]] | Iterable[tuple[int, int]],
) -> list[set[tuple[int, int]]]:
    """Partition ``corridor_tiles`` into disjoint connected components.

    Builds a 32-pixel tile box per ``(tx, ty)``, unions them via
    Shapely's ``unary_union``, and walks the resulting MultiPolygon
    geoms (or single Polygon for a single-component corridor system).
    Returns one ``set[(tx, ty)]`` per disjoint component, in Shapely
    iteration order.
    """
    tiles_set = (
        corridor_tiles
        if isinstance(corridor_tiles, set)
        else set(corridor_tiles)
    )
    if not tiles_set:
        return []
    from shapely.geometry import Polygon as _ShapelyPolygon
    from shapely.ops import unary_union as _unary_union
    from nhc.rendering._svg_helpers import CELL

    tile_boxes = [
        _ShapelyPolygon([
            (tx * CELL, ty * CELL),
            ((tx + 1) * CELL, ty * CELL),
            ((tx + 1) * CELL, (ty + 1) * CELL),
            (tx * CELL, (ty + 1) * CELL),
        ])
        for tx, ty in tiles_set
    ]
    merged_geom = _unary_union(tile_boxes)
    if not hasattr(merged_geom, "geoms"):
        return [tiles_set]

    groups: list[set[tuple[int, int]]] = []
    for component in merged_geom.geoms:
        if component.is_empty:
            continue
        comp_tiles: set[tuple[int, int]] = {
            (tx, ty)
            for tx, ty in tiles_set
            if component.contains(
                _ShapelyPolygon([
                    (tx * CELL, ty * CELL),
                    ((tx + 1) * CELL, ty * CELL),
                    ((tx + 1) * CELL, (ty + 1) * CELL),
                    (tx * CELL, (ty + 1) * CELL),
                ])
            )
        }
        if comp_tiles:
            groups.append(comp_tiles)
    return groups


def _collect_cave_systems(
    cave_tiles: set[tuple[int, int]],
) -> list[set[tuple[int, int]]]:
    """Partition ``cave_tiles`` into disjoint cave systems.

    Determinism contract: for the common single-component path,
    return ``[cave_tiles]`` UNCHANGED. A containment-filtered subset
    of the same set may iterate in different hash order and produce
    a different ``exterior.coords[0]`` from Shapely's ``unary_union``
    even though the full vertex set is identical.
    """
    if not cave_tiles:
        return []
    from shapely.geometry import Polygon as _ShapelyPolygon
    from shapely.ops import unary_union as _unary_union
    from nhc.rendering._svg_helpers import CELL

    tile_boxes = [
        _ShapelyPolygon([
            (tx * CELL, ty * CELL),
            ((tx + 1) * CELL, ty * CELL),
            ((tx + 1) * CELL, (ty + 1) * CELL),
            (tx * CELL, (ty + 1) * CELL),
        ])
        for tx, ty in cave_tiles
    ]
    merged_geom = _unary_union(tile_boxes)
    if not hasattr(merged_geom, "geoms"):
        # Single connected cave region — the common path. Pass the
        # original ``cave_tiles`` set directly so the Shapely ring
        # starting-point is deterministic across all callers.
        return [cave_tiles]

    groups: list[set[tuple[int, int]]] = []
    for component in merged_geom.geoms:
        if component.is_empty:
            continue
        comp_tiles: set[tuple[int, int]] = {
            (tx, ty)
            for tx, ty in cave_tiles
            if component.contains(
                _ShapelyPolygon([
                    (tx * CELL, ty * CELL),
                    ((tx + 1) * CELL, ty * CELL),
                    ((tx + 1) * CELL, (ty + 1) * CELL),
                    (tx * CELL, (ty + 1) * CELL),
                ])
            )
        }
        if comp_tiles:
            groups.append(comp_tiles)
    return groups


def _floor_detail_candidates(
    level,
) -> list[tuple[int, int, bool]]:
    """Walk the level once and return the floor-detail candidate set.

    Returns ``(x, y, is_corridor)`` tuples for floor tiles that are
    not stair features and not on a STREET / FIELD / GARDEN surface,
    with a per-tile corridor / door classification. Shared between
    :mod:`nhc.rendering.emit.stamp` and
    :mod:`nhc.rendering.emit.thematic_detail` so both walk identical
    candidate lists in y-major / x-minor order.
    """
    candidates: list[tuple[int, int, bool]] = []
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
            is_cor = (
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
            )
            candidates.append((x, y, is_cor))
    return candidates
