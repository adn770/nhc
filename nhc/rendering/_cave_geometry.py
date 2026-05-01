"""Cave geometry helpers for the SVG renderer.

Pure functions that trace, smooth, jitter, and build Shapely
geometry for cave-region walls and outlines.
"""

from __future__ import annotations

import math
import random
import re

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient as _shapely_orient
from shapely.ops import unary_union

from nhc.dungeon.model import Level, Room, SurfaceType, Terrain
from nhc.dungeon.generators.cellular import CaveShape
from nhc.rendering._svg_helpers import CELL, WALL_WIDTH  # noqa: F401


def _cave_svg_outline(room: "Room") -> str | None:
    """Build an organic closed SVG path for a cave room (fill).

    Traces the contour of the cave's floor tiles and smooths it
    using Catmull-Rom → cubic Bézier conversion.  Always returns
    a closed path — used for the floor fill.  Wall rendering uses
    _cave_with_gaps instead so corridor openings become gaps.
    """
    tiles = room.floor_tiles()
    if not tiles:
        return None

    coords = _trace_cave_boundary_coords(tiles)
    if not coords or len(coords) < 4:
        return None

    return _smooth_closed_path(coords)


def _trace_cave_boundary_coords(
    tiles: set[tuple[int, int]],
) -> list[tuple[float, float]]:
    """Trace the outer contour of a set of tiles as pixel corners.

    Returns an ordered list of (x, y) corner points walking the
    boundary clockwise.  Uses Shapely's unary_union to handle the
    merge and extract the exterior ring.
    """
    boxes = []
    for tx, ty in tiles:
        px, py = tx * CELL, ty * CELL
        boxes.append(Polygon([
            (px, py), (px + CELL, py),
            (px + CELL, py + CELL), (px, py + CELL),
        ]))
    merged = unary_union(boxes)
    if merged.is_empty:
        return []

    # Simplify to remove collinear tile-edge vertices
    simplified = merged.simplify(CELL * 0.35, preserve_topology=True)
    if hasattr(simplified, 'geoms'):
        simplified = max(simplified.geoms, key=lambda g: g.area)

    coords = list(simplified.exterior.coords)
    if coords and coords[-1] == coords[0]:
        coords = coords[:-1]
    return coords


def _cave_raw_exterior_coords(
    tiles: set[tuple[int, int]],
) -> list[tuple[float, float]]:
    """Return the raw (un-simplified) exterior ring of a tile set.

    Like :func:`_trace_cave_boundary_coords` but skips the
    Douglas-Peucker simplification step so the returned coords
    exactly describe the tile-boundary polygon produced by
    :func:`_build_cave_polygon`.  The consumer stores these coords
    in ``FloorOp.outline.vertices`` / ``ExteriorWallOp.outline.vertices``
    so that :func:`_cave_path_from_outline` can reconstruct the
    original polygon via ``Polygon(vertices)`` and apply the
    buffer+jitter pipeline to produce a byte-identical result to
    :func:`_build_cave_wall_geometry`.
    """
    boxes = []
    for tx, ty in tiles:
        px, py = tx * CELL, ty * CELL
        boxes.append(Polygon([
            (px, py), (px + CELL, py),
            (px + CELL, py + CELL), (px, py + CELL),
        ]))
    merged = unary_union(boxes)
    if merged.is_empty:
        return []

    if hasattr(merged, 'geoms'):
        merged = max(merged.geoms, key=lambda g: g.area)

    coords = list(merged.exterior.coords)
    if coords and coords[-1] == coords[0]:
        coords = coords[:-1]
    return coords


def _smooth_closed_path(
    coords: list[tuple[float, float]],
) -> str:
    """Build an SVG path (closed, centripetal Catmull-Rom → cubic bezier).

    Uses centripetal parameterization (α=0.5) which eliminates
    cusps and self-intersections that uniform Catmull-Rom produces
    when control points are unevenly spaced (common after jitter).
    """
    n = len(coords)
    parts = [f'M{coords[0][0]:.1f},{coords[0][1]:.1f}']
    for i in range(n):
        p0 = coords[(i - 1) % n]
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        p3 = coords[(i + 2) % n]
        c1x, c1y, c2x, c2y = _centripetal_bezier_cps(
            p0, p1, p2, p3,
        )
        parts.append(
            f'C{c1x:.1f},{c1y:.1f} '
            f'{c2x:.1f},{c2y:.1f} '
            f'{p2[0]:.1f},{p2[1]:.1f}'
        )
    parts.append('Z')
    return f'<path d="{" ".join(parts)}"/>'


def _centripetal_bezier_cps(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    alpha: float = 0.5,
) -> tuple[float, float, float, float]:
    """Compute cubic Bézier control points for centripetal Catmull-Rom.

    Given four sequential Catmull-Rom points, returns (c1x, c1y,
    c2x, c2y) — the two interior control points of the cubic
    Bézier segment between *p1* and *p2*.

    *alpha* = 0.5 is centripetal (eliminates cusps/loops),
    0.0 is uniform (classic), 1.0 is chordal.
    """
    # Knot intervals: t_{i+1} - t_i = |P_{i+1} - P_i|^alpha
    d01 = max(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) ** alpha,
              1e-6)
    d12 = max(math.hypot(p2[0] - p1[0], p2[1] - p1[1]) ** alpha,
              1e-6)
    d23 = max(math.hypot(p3[0] - p2[0], p3[1] - p2[1]) ** alpha,
              1e-6)
    # Tangent at p1 for the segment p1→p2 (Barry-Goldman):
    #   m1 = d12 * [(p1-p0)/d01 - (p2-p0)/(d01+d12) + (p2-p1)/d12]
    m1x = d12 * ((p1[0] - p0[0]) / d01
                  - (p2[0] - p0[0]) / (d01 + d12)
                  + (p2[0] - p1[0]) / d12)
    m1y = d12 * ((p1[1] - p0[1]) / d01
                  - (p2[1] - p0[1]) / (d01 + d12)
                  + (p2[1] - p1[1]) / d12)
    # Tangent at p2:
    #   m2 = d12 * [(p2-p1)/d12 - (p3-p1)/(d12+d23) + (p3-p2)/d23]
    m2x = d12 * ((p2[0] - p1[0]) / d12
                  - (p3[0] - p1[0]) / (d12 + d23)
                  + (p3[0] - p2[0]) / d23)
    m2y = d12 * ((p2[1] - p1[1]) / d12
                  - (p3[1] - p1[1]) / (d12 + d23)
                  + (p3[1] - p2[1]) / d23)
    # Bézier control points
    c1x = p1[0] + m1x / 3
    c1y = p1[1] + m1y / 3
    c2x = p2[0] - m2x / 3
    c2y = p2[1] - m2y / 3
    return c1x, c1y, c2x, c2y


def _smooth_open_path(
    coords: list[tuple[float, float]],
) -> str:
    """Build an SVG path (open, centripetal Catmull-Rom → cubic bezier).

    For open curves, endpoints use duplicated neighbors as the
    virtual p0/p3 so the curve passes exactly through them.
    Uses centripetal parameterization (α=0.5) to match closed paths.
    """
    n = len(coords)
    if n < 2:
        return ""
    parts = [f'M{coords[0][0]:.1f},{coords[0][1]:.1f}']
    for i in range(n - 1):
        p0 = coords[i - 1] if i > 0 else coords[i]
        p1 = coords[i]
        p2 = coords[i + 1]
        p3 = coords[i + 2] if i + 2 < n else coords[i + 1]
        c1x, c1y, c2x, c2y = _centripetal_bezier_cps(
            p0, p1, p2, p3,
        )
        parts.append(
            f'C{c1x:.1f},{c1y:.1f} '
            f'{c2x:.1f},{c2y:.1f} '
            f'{p2[0]:.1f},{p2[1]:.1f}'
        )
    return " ".join(parts)


def _collect_cave_region(level: "Level") -> set[tuple[int, int]]:
    """Collect all tiles belonging to the unified cave region.

    Seeds the flood-fill with every floor tile belonging to a
    CaveShape room, then expands through adjacent walkable
    corridor tiles.  A corridor is considered part of the cave
    region if it is reachable from any cave room via a chain of
    walkable (FLOOR/WATER/GRASS) tiles that includes at least
    one corridor step — i.e. any corridor connected (directly or
    transitively) to a cave room is pulled in.
    """
    walkable = (Terrain.FLOOR, Terrain.WATER, Terrain.GRASS)

    # Seed with cave room floor tiles
    seed: set[tuple[int, int]] = set()
    for room in level.rooms:
        if isinstance(room.shape, CaveShape):
            seed |= room.floor_tiles()
    if not seed:
        return set()

    # Flood through corridor tiles adjacent to the region
    region: set[tuple[int, int]] = set(seed)
    frontier: list[tuple[int, int]] = list(seed)
    while frontier:
        x, y = frontier.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in region:
                continue
            nb = level.tile_at(nx, ny)
            if not nb or nb.terrain not in walkable:
                continue
            # Only expand into corridor tiles — we don't want to
            # absorb adjacent non-cave rooms.
            if nb.surface_type != SurfaceType.CORRIDOR:
                continue
            region.add((nx, ny))
            frontier.append((nx, ny))
    return region


def _build_cave_polygon(
    tiles: set[tuple[int, int]],
):
    """Union tile squares into a Shapely Polygon or MultiPolygon.

    Returns None for empty input.  Exteriors come out CCW and
    holes CW (Shapely default), which the outward-normal jitter
    relies on for direction.
    """
    if not tiles:
        return None
    boxes = []
    for tx, ty in tiles:
        px, py = tx * CELL, ty * CELL
        boxes.append(Polygon([
            (px, py), (px + CELL, py),
            (px + CELL, py + CELL), (px, py + CELL),
        ]))
    merged = unary_union(boxes)
    if merged.is_empty:
        return None
    return merged


def _densify_ring(
    coords: list[tuple[float, float]],
    step: float,
) -> list[tuple[float, float]]:
    """Insert synthetic vertices along long edges.

    Walks *coords* (assumed non-repeating, ring closes implicitly)
    and inserts intermediate points every ~*step* pixels on any
    edge longer than *step*.  Preserves the original corners so
    the tile-edge polygon's shape is not distorted before jitter.
    """
    if len(coords) < 2:
        return list(coords)
    n = len(coords)
    out: list[tuple[float, float]] = []
    for i in range(n):
        a = coords[i]
        b = coords[(i + 1) % n]
        out.append(a)
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        dist = math.hypot(dx, dy)
        if dist <= step:
            continue
        n_sub = int(dist // step)
        for k in range(1, n_sub + 1):
            t = k / (n_sub + 1)
            out.append((a[0] + dx * t, a[1] + dy * t))
    return out


def _jitter_ring_outward(
    coords: list[tuple[float, float]],
    floor_poly,
    rng: random.Random,
    is_hole: bool = False,
    direction_poly=None,
) -> list[tuple[float, float]]:
    """Push each control point outward along its outward normal.

    *coords* is a non-repeating ring (no duplicated closing point).
    *floor_poly* is the hard containment invariant — the jittered
    result is guaranteed to stay outside this polygon (so floor
    tiles always remain inside the final wall ring).
    *direction_poly* is the shape whose boundary *coords* actually
    lies on; it is used to decide which perpendicular is "outward"
    when the vertices live on a buffered ring that is some distance
    from *floor_poly*.  Defaults to *floor_poly* for backwards
    compatibility.

    Jitter magnitude combines a base random offset, corner-aware
    damping, and a sinusoidal S-curve modulation keyed to
    arc-length position for organic Dyson-style undulation.
    The result is clamped to half the local edge length so two
    adjacent jittered points can never cross each other.
    """
    n = len(coords)
    if n < 3:
        return list(coords)

    from shapely.geometry import Point as ShPoint

    if direction_poly is None:
        direction_poly = floor_poly

    # Pre-compute cumulative arc-length for S-curve modulation.
    arc_lengths = [0.0]
    for i in range(n):
        a = coords[i]
        b = coords[(i + 1) % n]
        arc_lengths.append(
            arc_lengths[-1] + math.hypot(b[0] - a[0], b[1] - a[1])
        )
    total_arc = max(arc_lengths[-1], 1e-6)
    # S-curve parameters: frequency scales with perimeter so
    # larger caves get more undulations.  Phase is random per
    # ring so each wall segment looks different.
    # Low frequency → fewer, bolder lobes (Dyson style).
    scurve_freq = max(4.0, total_arc / (CELL * 2.0))
    scurve_phase = rng.uniform(0, 2 * math.pi)
    # Second harmonic at ~1.7× frequency for organic variation
    # (avoids the mechanical look of a pure single sine wave).
    scurve_freq2 = scurve_freq * 1.7
    scurve_phase2 = rng.uniform(0, 2 * math.pi)
    # Tangential wave — shifts points along the wall to create
    # true S-curves, not just in/out wobble.
    tang_freq = scurve_freq * 0.8
    tang_phase = rng.uniform(0, 2 * math.pi)

    out: list[tuple[float, float]] = []
    for i in range(n):
        prev_p = coords[(i - 1) % n]
        cur_p = coords[i]
        next_p = coords[(i + 1) % n]
        # Average of incoming and outgoing edge directions
        e1x, e1y = cur_p[0] - prev_p[0], cur_p[1] - prev_p[1]
        e2x, e2y = next_p[0] - cur_p[0], next_p[1] - cur_p[1]
        tx = e1x + e2x
        ty = e1y + e2y
        tlen = math.hypot(tx, ty)
        if tlen < 1e-6:
            out.append(cur_p)
            continue
        tx /= tlen
        ty /= tlen
        # The tangent has two perpendiculars; "outward" is the one
        # that leaves the floor polygon.  Probe both and pick the
        # one whose small test offset lands outside.  This is
        # orientation-agnostic — works whether Shapely returned the
        # ring CW or CCW, and whether this is an exterior or a hole.
        cand_a = (ty, -tx)
        cand_b = (-ty, tx)
        probe = 0.5
        a_outside = not direction_poly.contains(
            ShPoint(cur_p[0] + cand_a[0] * probe,
                    cur_p[1] + cand_a[1] * probe)
        )
        if a_outside:
            nx, ny = cand_a
        else:
            nx, ny = cand_b
        # Sub-tile outward jitter, deterministic via rng order.
        # Magnitude chosen so the wobble amplitude reads at
        # full-map zoom while staying within the one-tile hatching
        # band that Dyson leaves around cave boundaries.  Clamp to
        # half the local edge length so two adjacent jittered
        # points cannot cross each other and the ring stays simple.
        e1_len = math.hypot(e1x, e1y)
        e2_len = math.hypot(e2x, e2y)
        # Cap to prevent ring self-intersection.  Sine-based
        # displacement moves adjacent points similarly, so a
        # generous cap is safe.
        local_cap = max(1.0, min(e1_len, e2_len) * 0.85)
        # Corner-aware damping: reduce jitter at sharp corners
        # where knots are most likely to form.  Compute the
        # cosine of the angle between incoming/outgoing edges;
        # a sharp concave corner (cos → −1) gets damped to ~30%,
        # a straight edge (cos → 1) gets full magnitude.
        if e1_len > 1e-6 and e2_len > 1e-6:
            cos_angle = (
                (e1x * e2x + e1y * e2y) / (e1_len * e2_len)
            )
            # Map cos_angle from [-1, 1] to damping [0.3, 1.0]
            corner_damp = 0.3 + 0.7 * (cos_angle + 1) / 2
        else:
            corner_damp = 1.0
        # S-curve modulation: the sine wave is the PRIMARY
        # displacement; random noise is just a small perturbation.
        # This ensures the wall boundary visibly undulates in a
        # Dyson hand-drawn style rather than looking randomly
        # jittered around a straight edge.
        arc_frac = arc_lengths[i] / total_arc
        theta = 2 * math.pi * scurve_freq * arc_frac
        wave = math.sin(theta + scurve_phase)
        wave2 = math.sin(
            2 * math.pi * scurve_freq2 * arc_frac + scurve_phase2
        )
        # Combined wave: primary + 40% second harmonic
        combined_wave = wave + 0.4 * wave2
        # Constant outward base + sinusoidal undulation + noise
        base_offset = CELL * 0.15
        wave_amp = CELL * 0.25
        noise = CELL * rng.uniform(-0.08, 0.08)
        mag = (base_offset + wave_amp * combined_wave
               + noise) * corner_damp
        mag = min(max(mag, CELL * 0.05), local_cap)
        # Tangential shift — small slide along the wall direction
        # to break up the pure-normal look.  Kept small relative
        # to step to avoid ring self-intersection.
        tang_wave = math.sin(
            2 * math.pi * tang_freq * arc_frac + tang_phase
        )
        tang_shift = CELL * 0.08 * tang_wave * corner_damp
        px = cur_p[0] + nx * mag + tx * tang_shift
        py = cur_p[1] + ny * mag + ty * tang_shift
        # Safety: at deeply concave vertices the outward ray can
        # still re-enter the polygon at distance.  Shrink until out.
        attempts = 0
        while floor_poly.contains(ShPoint(px, py)) and attempts < 4:
            mag *= 0.5
            px = cur_p[0] + nx * mag
            py = cur_p[1] + ny * mag
            attempts += 1
        if attempts == 4 and floor_poly.contains(ShPoint(px, py)):
            # Give up — fall back to the unjittered vertex (on the
            # boundary, so the floor still stays enclosed).
            px, py = cur_p
        out.append((px, py))
    return out


def _ring_to_subpath(
    coords: list[tuple[float, float]],
) -> str:
    """Smooth a closed ring into a Catmull-Rom cubic-Bézier subpath.

    Returns just the path data string (M…C…Z), without the
    <path> wrapper, so multiple rings can be concatenated into a
    single <path> element.
    """
    if len(coords) < 3:
        return ""
    smoothed = _smooth_closed_path(coords)
    # _smooth_closed_path wraps in <path d="…"/>; unwrap.
    m = re.search(r'd="([^"]+)"', smoothed)
    return m.group(1) if m else ""


def _build_cave_wall_geometry(
    level: "Level", rng: random.Random,
):
    """Build the unified cave region wall geometry.

    Returns a tuple ``(svg_path, wall_polygon, tiles)``:
      * ``svg_path`` is the smoothed ``<path>`` element for the
        wall stroke (one subpath per ring).
      * ``wall_polygon`` is a Shapely Polygon/MultiPolygon whose
        rings match the jittered wall path — used as the clip
        boundary for floor fill and grid, so both extend out to
        (and are cut by) the same curve the wall stroke follows.
      * ``tiles`` is the set of cave-region tiles (rooms +
        connected corridors) so callers can skip per-tile
        rendering for them.

    Returns ``(None, None, empty_set)`` when the level has no cave
    region.

    Collects every cave-region tile, unions into a Shapely geometry,
    simplifies the tile-edge staircase with Douglas-Peucker, then
    for every ring emits one Catmull-Rom smoothed subpath whose
    control points are densified and pushed outward along each
    vertex's outward normal so the floor polygon stays strictly
    enclosed by the wall ring.
    """
    tiles = _collect_cave_region(level)
    if not tiles:
        return None, None, set()
    geom = _build_cave_polygon(tiles)
    if geom is None or geom.is_empty:
        return None, None, tiles

    # Normalize into a list of Polygons
    polys: list = []
    if hasattr(geom, 'geoms'):
        polys = [g for g in geom.geoms if not g.is_empty]
    else:
        polys = [geom]
    if not polys:
        return None, None, tiles

    # Expand the tile-edge polygon outward with Shapely's round-
    # join buffer.  This does two things at once:
    #   1. Every 90° stairstep corner becomes a quarter-circle
    #      arc — no pronounced L silhouettes in the wall.
    #   2. The wall gains ~0.4 CELL of slack into the void, so
    #      the subsequent outward jitter has room to bulge without
    #      immediately bumping into adjacent regions.
    # The outward jitter still uses the UNBUFFERED ``poly`` for the
    # containment safety check, so no floor tile can end up outside
    # the final wall ring no matter how the jitter lands.
    buffer_r = CELL * 0.3
    # Light simplification after buffering to remove collinear
    # points introduced by adjacent arc segments while keeping the
    # arcs themselves intact.
    simplify_tol = CELL * 0.15
    step = CELL * 0.8
    subpaths: list[str] = []
    wall_polys: list[Polygon] = []
    for poly in polys:
        inflated = poly.buffer(
            buffer_r, join_style='round', quad_segs=8,
        )
        if inflated.is_empty:
            continue
        # Buffering a MultiPolygon may fuse or split into multiple
        # parts; keep the largest component for this source poly.
        if hasattr(inflated, 'geoms'):
            inflated = max(inflated.geoms, key=lambda g: g.area)
        simp = inflated.simplify(
            simplify_tol, preserve_topology=True,
        )
        simp = _shapely_orient(simp, sign=1.0)
        if simp.is_empty or not hasattr(simp, 'exterior'):
            continue
        # Exterior ring (CCW)
        ext = list(simp.exterior.coords)
        if ext and ext[0] == ext[-1]:
            ext = ext[:-1]
        ext_d = _densify_ring(ext, step)
        ext_j = _jitter_ring_outward(
            ext_d, poly, rng, is_hole=False,
            direction_poly=simp,
        )
        s = _ring_to_subpath(ext_j)
        if s:
            subpaths.append(s)
        # Holes (CW).  Buffer the source polygon's holes INWARD
        # (i.e. use poly.interiors directly — they are already
        # rings, and we want the wall around each hole to match
        # the outward buffer semantics when viewed from inside).
        jittered_holes: list[list[tuple[float, float]]] = []
        for hole in simp.interiors:
            h = list(hole.coords)
            if h and h[0] == h[-1]:
                h = h[:-1]
            h_d = _densify_ring(h, step)
            h_j = _jitter_ring_outward(
                h_d, poly, rng, is_hole=True,
                direction_poly=simp,
            )
            s = _ring_to_subpath(h_j)
            if s:
                subpaths.append(s)
                jittered_holes.append(h_j)
        # Matching polygon for clip/fill, built from the same
        # jittered rings so floor + grid align exactly with the
        # wall stroke.
        if len(ext_j) >= 3:
            wp = Polygon(ext_j, holes=jittered_holes)
            if wp.is_valid and not wp.is_empty:
                wall_polys.append(wp)
            else:
                # Fix tiny self-intersections from aggressive jitter.
                wp_fixed = wp.buffer(0)
                if not wp_fixed.is_empty:
                    wall_polys.append(wp_fixed)

    if not subpaths:
        return None, None, tiles
    svg_path = f'<path d="{" ".join(subpaths)}"/>'
    wall_polygon = (
        unary_union(wall_polys) if wall_polys else None
    )
    return svg_path, wall_polygon, tiles


def _cave_region_walls(
    level: "Level", rng: random.Random,
) -> str | None:
    """Return only the SVG wall path for a cave region.

    Thin wrapper around :func:`_build_cave_wall_geometry` kept for
    the unit tests and any caller that does not need the clip
    polygon.
    """
    svg_path, _poly, _tiles = _build_cave_wall_geometry(level, rng)
    return svg_path
