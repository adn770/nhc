"""Hatching renderers extracted from svg.py.

Provides cross-hatching for dungeon perimeters, corridors, and
cave interior holes.
"""
from __future__ import annotations

import math
import random

from nhc.rendering import _perlin as _noise
from shapely.geometry import LineString, Point, Polygon

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.rendering._svg_helpers import (
    CELL,
    HATCH_UNDERLAY,
    INK,
    _is_door,
)
from nhc.rendering._dungeon_polygon import (
    _build_dungeon_polygon,
    _build_sections,
    _pick_section_points,
)


def _render_corridor_hatching(
    svg: list[str], level: "Level", seed: int,
) -> None:
    """Hatch VOID tiles adjacent to corridors (one tile each side).

    Reuses the same visual style as room hatching — grey underlay,
    stones, and section-partitioned hatch lines.
    """

    rng = random.Random(seed + 7)

    # Collect VOID tiles that border a corridor or door tile
    hatch_tiles: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (tile.surface_type == SurfaceType.CORRIDOR
                    or _is_door(level, x, y)):
                continue
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if not level.in_bounds(nx, ny):
                    continue
                nb = level.tiles[ny][nx]
                if (nb.terrain == Terrain.VOID
                        and nb.surface_type != SurfaceType.CORRIDOR):
                    hatch_tiles.add((nx, ny))

    if not hatch_tiles:
        return

    min_stroke = 1.0
    max_stroke = 1.8
    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gx, gy in sorted(hatch_tiles):
        # Grey underlay tile
        tile_fills.append(
            f'<rect x="{gx * CELL}" y="{gy * CELL}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{HATCH_UNDERLAY}"/>')

        # Scatter 0-2 stones
        n_stones = rng.choices(
            [0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
        for _ in range(n_stones):
            sx = (gx + rng.uniform(0.15, 0.85)) * CELL
            sy = (gy + rng.uniform(0.15, 0.85)) * CELL
            rx = rng.uniform(2, CELL * 0.25)
            ry = rng.uniform(2, CELL * 0.2)
            angle = rng.uniform(0, 180)
            sw = rng.uniform(1.2, 2.0)
            hatch_stones.append(
                f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                f'rx="{rx:.1f}" ry="{ry:.1f}" '
                f'transform="rotate({angle:.0f},'
                f'{sx:.1f},{sy:.1f})" '
                f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                f'stroke-width="{sw:.1f}"/>')

        # Perlin-displaced cluster anchor
        nr = CELL * 0.1
        adx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
        ady = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
        anchor = ((gx + 0.5) * CELL + adx,
                  (gy + 0.5) * CELL + ady)

        corners = [
            (gx * CELL, gy * CELL),
            ((gx + 1) * CELL, gy * CELL),
            ((gx + 1) * CELL, (gy + 1) * CELL),
            (gx * CELL, (gy + 1) * CELL),
        ]

        pts = _pick_section_points(corners, anchor, CELL, rng)
        sections = _build_sections(anchor, pts, corners)

        for i, section in enumerate(sections):
            if section.is_empty or section.area < 1:
                continue
            if i == 0:
                angle = math.atan2(
                    pts[1][1] - pts[0][1],
                    pts[1][0] - pts[0][0])
            else:
                angle = rng.uniform(0, math.pi)

            bounds = section.bounds
            diag = math.hypot(
                bounds[2] - bounds[0], bounds[3] - bounds[1])
            spacing = CELL * 0.20
            n_lines = max(3, int(diag / spacing))

            for j in range(n_lines):
                offset = (j - (n_lines - 1) / 2) * spacing
                scx = section.centroid.x
                scy = section.centroid.y
                perp_x = math.cos(angle + math.pi / 2) * offset
                perp_y = math.sin(angle + math.pi / 2) * offset
                line = LineString([
                    (scx + perp_x - math.cos(angle) * diag,
                     scy + perp_y - math.sin(angle) * diag),
                    (scx + perp_x + math.cos(angle) * diag,
                     scy + perp_y + math.sin(angle) * diag),
                ])
                clipped = section.intersection(line)
                if (clipped.is_empty
                        or not isinstance(clipped, LineString)):
                    continue
                p1, p2 = list(clipped.coords)
                wb = CELL * 0.03
                p1 = (
                    p1[0] + _noise.pnoise2(
                        p1[0] * 0.1, p1[1] * 0.1, base=10) * wb,
                    p1[1] + _noise.pnoise2(
                        p1[0] * 0.1, p1[1] * 0.1, base=11) * wb,
                )
                p2 = (
                    p2[0] + _noise.pnoise2(
                        p2[0] * 0.1, p2[1] * 0.1, base=12) * wb,
                    p2[1] + _noise.pnoise2(
                        p2[0] * 0.1, p2[1] * 0.1, base=13) * wb,
                )
                lsw = rng.uniform(min_stroke, max_stroke)
                hatch_lines.append(
                    f'<line x1="{p1[0]:.1f}" '
                    f'y1="{p1[1]:.1f}" '
                    f'x2="{p2[0]:.1f}" '
                    f'y2="{p2[1]:.1f}" '
                    f'stroke="{INK}" '
                    f'stroke-width="{lsw:.2f}" '
                    f'stroke-linecap="round"/>')

    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')


def _render_hole_hatching(
    svg: list[str], level: "Level", seed: int,
    cave_wall_poly,
) -> None:
    """Render hatching inside interior holes of the cave polygon.

    Interior holes (islands of wall/void surrounded by floor) need
    hatching rendered AFTER the cave floor fill so it's not covered
    by the brown fill.  Uses the same grey underlay + stone style
    as the perimeter hatching.
    """
    rng = random.Random(seed + 777)
    polys = (
        list(cave_wall_poly.geoms)
        if hasattr(cave_wall_poly, 'geoms')
        else [cave_wall_poly]
    )
    hole_polys = []
    for p in polys:
        for interior in p.interiors:
            hole_polys.append(Polygon(interior.coords))
    if not hole_polys:
        return

    tile_fills: list[str] = []
    hatch_stones: list[str] = []
    hatch_lines: list[str] = []

    for gy in range(level.height):
        for gx in range(level.width):
            center = Point((gx + 0.5) * CELL, (gy + 0.5) * CELL)
            if not any(hp.contains(center) for hp in hole_polys):
                continue
            # Grey underlay
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')
            # Stones
            n_stones = rng.choices(
                [0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15],
            )[0]
            for _ in range(n_stones):
                sx = (gx + rng.uniform(0.15, 0.85)) * CELL
                sy = (gy + rng.uniform(0.15, 0.85)) * CELL
                rx = rng.uniform(2, CELL * 0.25)
                ry = rng.uniform(2, CELL * 0.2)
                angle = rng.uniform(0, 180)
                sw = rng.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},'
                    f'{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" '
                    f'stroke="{INK}" '
                    f'stroke-width="{sw:.1f}"/>')
            # Cross-hatch lines
            n_lines = rng.randint(2, 4)
            for _ in range(n_lines):
                x1 = (gx + rng.uniform(0.05, 0.95)) * CELL
                y1 = (gy + rng.uniform(0.05, 0.95)) * CELL
                angle = rng.uniform(0, math.pi)
                length = rng.uniform(CELL * 0.2, CELL * 0.5)
                x2 = x1 + math.cos(angle) * length
                y2 = y1 + math.sin(angle) * length
                sw = rng.uniform(0.8, 1.5)
                hatch_lines.append(
                    f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
                    f'x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="{INK}" stroke-width="{sw:.1f}" '
                    f'stroke-linecap="round"/>')

    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_stones:
        svg.append(
            f'<g opacity="0.5">{"".join(hatch_stones)}</g>')
    if hatch_lines:
        svg.append(
            f'<g opacity="0.5">{"".join(hatch_lines)}</g>')


def _render_hatching(
    svg: list[str], level: "Level", seed: int,
    dungeon_poly=None, hatch_distance: float = 2.0,
    cave_wall_poly=None,
) -> None:
    """Procedural cross-hatching around the dungeon perimeter.

    Uses Shapely for geometry clipping, Perlin noise for organic
    displacement, and tile-based section partitioning.

    *hatch_distance* is the max distance in tiles from the dungeon
    edge that hatching extends.  Interior holes in the cave wall
    polygon (islands of wall/void surrounded by floor) are also
    hatched.
    """
    rng = random.Random(seed)
    if dungeon_poly is None:
        dungeon_poly = _build_dungeon_polygon(level)
    if dungeon_poly.is_empty:
        return

    # No buffer — hatching renders right up to the dungeon edge.
    # Walls and floor fills (rendered after hatching) cover the
    # interior, so overlap is handled by the layer order.
    hatching_boundary = dungeon_poly

    # Collect interior holes from the cave wall polygon — these
    # are islands of wall/void surrounded by floor that should
    # receive hatching even though they're geometrically "inside"
    # the dungeon boundary.
    hole_polys: list = []
    if cave_wall_poly is not None and not cave_wall_poly.is_empty:
        polys = (
            list(cave_wall_poly.geoms)
            if hasattr(cave_wall_poly, 'geoms')
            else [cave_wall_poly]
        )
        for p in polys:
            for interior in p.interiors:
                hole_polys.append(Polygon(interior.coords))

    base_distance_limit = hatch_distance * CELL
    min_stroke = 1.0
    max_stroke = 1.8

    # Pre-compute floor tile set for grid-based skip check.
    # Using the tile grid instead of the polygon ensures every
    # floor tile is surrounded by hatching — the polygon boundary
    # can deviate from the tile grid due to jitter/smoothing,
    # leaving some adjacent wall tiles unhatched.  Any hatching
    # that overlaps floor area is covered by the floor fill.
    floor_set: set[tuple[int, int]] = set()
    for ty in range(level.height):
        for tx in range(level.width):
            if level.tiles[ty][tx].terrain == Terrain.FLOOR:
                floor_set.add((tx, ty))

    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gy in range(-1, level.height + 1):
        for gx in range(-1, level.width + 1):
            # Skip actual floor tiles — they're covered by fill
            if (gx, gy) in floor_set:
                continue
            # Distance: use nearest floor tile as reference
            # (faster than polygon boundary distance)
            min_dist = float('inf')
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if (gx + dx, gy + dy) in floor_set:
                        min_dist = min(min_dist,
                                       math.hypot(dx, dy) * CELL)
            if min_dist == float('inf'):
                # No floor tile nearby — use polygon distance
                center = Point(
                    (gx + 0.5) * CELL, (gy + 0.5) * CELL)
                min_dist = hatching_boundary.boundary.distance(
                    center)
            dist = min_dist

            # Irregular contour: vary distance limit per tile with
            # Perlin noise so the hatching edge flows organically.
            # Caves use a fixed limit — dense, continuous hatching
            # sells the solid rock illusion.
            if cave_wall_poly is None:
                noise_var = _noise.pnoise2(
                    gx * 0.3, gy * 0.3, base=50) * CELL * 0.8
                tile_limit = base_distance_limit + noise_var
            else:
                tile_limit = base_distance_limit
            if dist > tile_limit:
                continue

            # Random discontinuities: skip ~10% of edge tiles.
            # Caves skip this — they need dense, continuous hatching
            # to sell the solid rock illusion.
            if (cave_wall_poly is None
                    and dist > base_distance_limit * 0.5
                    and rng.random() < 0.10):
                continue

            # Grey underlay tile
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')

            # Scatter 0-2 stones of varying sizes in this tile
            n_stones = rng.choices([0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15])[0]
            for _ in range(n_stones):
                sx = (gx + rng.uniform(0.15, 0.85)) * CELL
                sy = (gy + rng.uniform(0.15, 0.85)) * CELL
                rx = rng.uniform(2, CELL * 0.25)
                ry = rng.uniform(2, CELL * 0.2)
                angle = rng.uniform(0, 180)
                sw = rng.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                    f'stroke-width="{sw:.1f}"/>')

            # Perlin-displaced cluster anchor
            nr = CELL * 0.1
            dx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
            dy = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
            anchor = ((gx + 0.5) * CELL + dx, (gy + 0.5) * CELL + dy)

            corners = [
                (gx * CELL, gy * CELL),
                ((gx + 1) * CELL, gy * CELL),
                ((gx + 1) * CELL, (gy + 1) * CELL),
                (gx * CELL, (gy + 1) * CELL),
            ]

            # Pick 3 random perimeter points to partition tile
            pts = _pick_section_points(corners, anchor, CELL, rng)
            sections = _build_sections(anchor, pts, corners)

            for i, section in enumerate(sections):
                if section.is_empty or section.area < 1:
                    continue
                if i == 0:
                    angle = math.atan2(
                        pts[1][1] - pts[0][1],
                        pts[1][0] - pts[0][0])
                else:
                    angle = rng.uniform(0, math.pi)

                bounds = section.bounds
                diag = math.hypot(
                    bounds[2] - bounds[0], bounds[3] - bounds[1])
                spacing = CELL * 0.20
                n_lines = max(3, int(diag / spacing))

                for j in range(n_lines):
                    offset = (j - (n_lines - 1) / 2) * spacing
                    cx = section.centroid.x
                    cy = section.centroid.y
                    perp_x = math.cos(angle + math.pi / 2) * offset
                    perp_y = math.sin(angle + math.pi / 2) * offset
                    line = LineString([
                        (cx + perp_x - math.cos(angle) * diag,
                         cy + perp_y - math.sin(angle) * diag),
                        (cx + perp_x + math.cos(angle) * diag,
                         cy + perp_y + math.sin(angle) * diag),
                    ])
                    clipped = section.intersection(line)
                    if clipped.is_empty or not isinstance(clipped, LineString):
                        continue
                    p1, p2 = list(clipped.coords)
                    # Perlin wobble
                    wb = CELL * 0.03
                    p1 = (
                        p1[0] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=10) * wb,
                        p1[1] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=11) * wb,
                    )
                    p2 = (
                        p2[0] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=12) * wb,
                        p2[1] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=13) * wb,
                    )
                    sw = rng.uniform(min_stroke, max_stroke)
                    hatch_lines.append(
                        f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" '
                        f'x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
                        f'stroke="{INK}" stroke-width="{sw:.2f}" '
                        f'stroke-linecap="round"/>')

    if not (tile_fills or hatch_lines or hatch_stones):
        return

    # Clip hatching to the exterior of the dungeon polygon.
    # Walls cover the tile-staircase-to-curve transition at
    # smooth room boundaries, so tile-based precision is fine.
    map_w = level.width * CELL
    map_h = level.height * CELL
    margin = CELL * 2
    clip_d = (
        f'M{-margin},{-margin} '
        f'H{map_w + margin} V{map_h + margin} '
        f'H{-margin} Z '
    )
    if not dungeon_poly.is_empty:
        geoms = (dungeon_poly.geoms
                 if hasattr(dungeon_poly, 'geoms')
                 else [dungeon_poly])
        for geom in geoms:
            coords = list(geom.exterior.coords)
            clip_d += f'M{coords[0][0]:.0f},{coords[0][1]:.0f} '
            clip_d += ' '.join(
                f'L{x:.0f},{y:.0f}' for x, y in coords[1:])
            clip_d += ' Z '
            # Do NOT add interior holes here — the evenodd rule
            # means the exterior ring already cuts out the dungeon
            # interior from the hatch region.  Interior holes
            # should remain INSIDE the hatch region (they are
            # void/wall islands that need hatching), so we leave
            # them out of the clip.  The outer rect + exterior
            # ring with evenodd = hatch everywhere EXCEPT dungeon
            # floor.  Adding holes would re-include dungeon floor
            # at the hole, but we actually want the opposite:
            # holes are NOT dungeon floor, so they should hatch.
            #
            # The trick: the exterior ring cuts out the dungeon.
            # Adding a hole ring (which is INSIDE the exterior)
            # would flip it back to "hatch" under evenodd — which
            # is exactly what we want.
            for hole in geom.interiors:
                h = list(hole.coords)
                clip_d += f'M{h[0][0]:.0f},{h[0][1]:.0f} '
                clip_d += ' '.join(
                    f'L{x:.0f},{y:.0f}' for x, y in h[1:])
                clip_d += ' Z '
    svg.append(
        f'<defs><clipPath id="hatch-clip">'
        f'<path d="{clip_d}" clip-rule="evenodd"/>'
        f'</clipPath></defs>')

    svg.append('<g clip-path="url(#hatch-clip)">')
    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')
    svg.append('</g>')
