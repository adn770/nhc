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

from typing import Any, Callable, Iterable

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.rendering._ir_helpers import _is_door


def _grid_components(
    tiles: set[tuple[int, int]],
) -> list[set[tuple[int, int]]]:
    """Partition ``tiles`` into 4-connected components (flood fill).

    Replaces the former Shapely ``unary_union`` + per-tile
    ``contains`` partition, which constructed a polygon per tile per
    component (O(components × tiles), ~87 % of ``build_floor_ir`` on a
    city). This is a plain O(tiles) grid flood fill.

    Connectivity matches Shapely's tile-box union exactly:
    **4-connected** — tiles sharing an edge join; tiles touching only
    at a corner stay separate.

    Deterministic ordering: components come out sorted by their
    topmost-leftmost (row-major) tile, so independent callers that
    re-run this (e.g. the cave Region in ``ir_emitter`` and the cave
    PaintOp in ``emit.paint``) agree on component order and their
    ``f"<kind>.<i>"`` cross-references resolve.
    """
    remaining = set(tiles)
    components: list[set[tuple[int, int]]] = []
    # Seed BFS from tiles in row-major order so component order is the
    # row-major order of each component's first-encountered tile.
    for seed in sorted(remaining, key=lambda t: (t[1], t[0])):
        if seed not in remaining:
            continue
        remaining.discard(seed)
        comp = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nb in remaining:
                    remaining.discard(nb)
                    comp.add(nb)
                    stack.append(nb)
        components.append(comp)
    return components


def _collect_corridor_tiles(
    level: Any,
    cave_tiles: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Collect every corridor (or door) tile on ``level``.

    Walks the level row-major, picks tiles whose terrain is FLOOR /
    WATER / GRASS / LAVA AND whose surface_type is CORRIDOR (or
    whose feature carries ``"door"``), excluding any tile already
    covered by ``cave_tiles``.

    Door tiles are folded in only on dungeon floors, where a door
    sits in a corridor and reads as a framed doorway. They are left
    out on:

    - building floors (``building_id`` set) — doors connect rooms,
      not corridors; and
    - site surfaces (``metadata.prerevealed``) — building *entry*
      doors sit on the street.

    On both, boxing each door tile draws a spurious square around it,
    so they collect real CORRIDOR tiles only.
    """
    meta = getattr(level, "metadata", None)
    prerevealed = bool(getattr(meta, "prerevealed", False))
    include_doors = (
        getattr(level, "building_id", None) is None
        and not prerevealed
    )
    tiles: set[tuple[int, int]] = set()
    for y in range(level.origin_y, level.origin_y + level.height):
        for x in range(level.origin_x, level.origin_x + level.width):
            if (x, y) in cave_tiles:
                continue
            tile = level.tile_at(x, y)
            if tile.terrain not in (
                Terrain.FLOOR, Terrain.WATER,
                Terrain.GRASS, Terrain.LAVA,
            ):
                continue
            if (
                tile.surface_type == SurfaceType.CORRIDOR
                or (include_doors
                    and tile.feature and "door" in (tile.feature or ""))
            ):
                tiles.add((x, y))
    return tiles


def _collect_corridor_components(
    corridor_tiles: set[tuple[int, int]] | Iterable[tuple[int, int]],
) -> list[set[tuple[int, int]]]:
    """Partition ``corridor_tiles`` into disjoint connected components.

    4-connected grid flood fill (see :func:`_grid_components`).
    Returns one ``set[(tx, ty)]`` per disjoint component in
    deterministic row-major order. Single-component corridor systems
    return the original set unchanged.
    """
    tiles_set = (
        corridor_tiles
        if isinstance(corridor_tiles, set)
        else set(corridor_tiles)
    )
    if not tiles_set:
        return []
    components = _grid_components(tiles_set)
    if len(components) == 1:
        return [tiles_set]
    return components


def _collect_cave_systems(
    cave_tiles: set[tuple[int, int]],
) -> list[set[tuple[int, int]]]:
    """Partition ``cave_tiles`` into disjoint cave systems.

    Determinism contract: for the common single-component path,
    return ``[cave_tiles]`` UNCHANGED so the downstream outline's ring
    starting-point stays stable across all callers (a re-iterated
    subset would hash in a different order).

    4-connected grid flood fill (see :func:`_grid_components`),
    matching the former Shapely tile-box union.
    """
    if not cave_tiles:
        return []
    components = _grid_components(cave_tiles)
    if len(components) == 1:
        # Single connected cave region — the common path. Pass the
        # original set through so the ring start is deterministic.
        return [cave_tiles]
    return components


def _collect_predicate_components(
    level: Any,
    predicate: Callable[[Any, int, int], bool],
    *,
    exclude: set[tuple[int, int]] | None = None,
) -> list[set[tuple[int, int]]]:
    """Partition tiles matching ``predicate(level, x, y)`` into disjoint
    connected components.

    Generalisation of :func:`_collect_terrain_systems` for predicates
    that aren't a single :class:`Terrain` value (e.g.
    :func:`nhc.rendering._floor_detail._is_cobble_tile` keys on
    ``surface_type ∈ {STREET, PAVED}``).

    ``exclude`` skips tiles already owned by another region.

    4-connected grid flood fill (see :func:`_grid_components`),
    matching the former Shapely tile-box union. Single-component
    results return the matching-tile set unchanged.
    """
    excluded = exclude or set()
    tiles: set[tuple[int, int]] = set()
    for y in range(level.origin_y, level.origin_y + level.height):
        for x in range(level.origin_x, level.origin_x + level.width):
            if (x, y) in excluded:
                continue
            if predicate(level, x, y):
                tiles.add((x, y))
    if not tiles:
        return []
    components = _grid_components(tiles)
    if len(components) == 1:
        return [tiles]
    return components


def _collect_terrain_systems(
    level: Any, terrain: Terrain,
    *,
    exclude: set[tuple[int, int]] | None = None,
) -> list[set[tuple[int, int]]]:
    """Partition level tiles of ``terrain`` into disjoint connected
    components.

    Used by ``emit_regions`` to register one ``Region(id="<kind>.<i>")``
    per disjoint cluster (water / lava / chasm / grass), and by
    ``emit_paints`` to emit a corresponding ``PaintOp`` per cluster.
    Thin wrapper over :func:`_collect_predicate_components`.

    ``exclude`` (typically the cave-tile set) skips tiles already
    owned by another region — water tiles inside a cave system stay
    on the cave region.
    """
    return _collect_predicate_components(
        level,
        lambda lv, x, y: lv.tile_at(x, y).terrain == terrain,
        exclude=exclude,
    )


def _terrain_cluster_coords(
    cluster: set[tuple[int, int]],
) -> list[tuple[float, float]]:
    """Return the exterior pixel-coord ring of a terrain tile cluster.

    Builds a 32-pixel tile box per ``(tx, ty)``, unions them via
    Shapely, and returns the exterior ring of the resulting polygon
    in CCW order (Shapely's ``Polygon.exterior``). Multi-component
    clusters (which shouldn't reach this helper — :func:`_collect_terrain_systems`
    already partitions by component) fall back to the bounding box.
    """
    if not cluster:
        return []
    from shapely.geometry import Polygon as _ShapelyPolygon
    from shapely.ops import unary_union as _unary_union
    from nhc.rendering._ir_helpers import CELL

    tile_boxes = [
        _ShapelyPolygon([
            (tx * CELL, ty * CELL),
            ((tx + 1) * CELL, ty * CELL),
            ((tx + 1) * CELL, (ty + 1) * CELL),
            (tx * CELL, (ty + 1) * CELL),
        ])
        for tx, ty in cluster
    ]
    merged = _unary_union(tile_boxes)
    if hasattr(merged, "geoms"):
        # Multi-polygon — pick the largest. Shouldn't happen if the
        # caller partitioned via _collect_terrain_systems.
        merged = max(merged.geoms, key=lambda p: p.area)
    coords = list(merged.exterior.coords)
    return [(float(x), float(y)) for x, y in coords]


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
    for y in range(level.origin_y, level.origin_y + level.height):
        for x in range(level.origin_x, level.origin_x + level.width):
            tile = level.tile_at(x, y)
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
