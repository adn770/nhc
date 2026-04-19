"""SVG rendering of site-level enclosures (fortification, palisade).

See ``design/building_generator.md`` section 7.2. A fortification
wall is drawn as a continuous dark base stroke with an
equally-spaced white dashed overlay. Gates cut the closed polygon
into open polylines; each segment is stroked independently.

Palisades (M7) live in the same module once implemented.
"""

from __future__ import annotations

import random


# ── Fortification rendering constants (initial values, tunable) ──

FORTIFICATION_BASE_COLOR = "#1A1A1A"
FORTIFICATION_BASE_WIDTH = 6.0
FORTIFICATION_OVERLAY_COLOR = "#FFFFFF"
FORTIFICATION_OVERLAY_WIDTH = 3.0
FORTIFICATION_DASH_ARRAY = "8 6"


# ── Palisade rendering constants (initial values, tunable) ───────

PALISADE_FILL = "#8A5A2A"
PALISADE_STROKE = "#4A2E1A"
PALISADE_STROKE_WIDTH = 1.5
PALISADE_RADIUS_MIN = 3.0
PALISADE_RADIUS_MAX = 4.0
PALISADE_RADIUS_JITTER = 0.3
# Step >= 2 * (RADIUS_MAX + RADIUS_JITTER) guarantees that any two
# adjacent circles are tangent-or-separated regardless of their
# individually sampled radii. 2 * 4.3 = 8.6; we round up to 9 so
# typical-radius circles show a small visible gap between them.
PALISADE_CIRCLE_STEP = 9.0
PALISADE_DOOR_LENGTH_PX = 64.0      # gate rect length (2 tiles)


def render_fortification_polyline(
    points: list[tuple[float, float]],
) -> list[str]:
    """Render an open polyline as one fortification wall segment.

    Emits two ``<path>`` elements: a continuous dark base stroke and
    an equally-spaced white dashed overlay along the same path.
    Returns an empty list for fewer than two points.
    """
    if len(points) < 2:
        return []
    parts = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for (x, y) in points[1:]:
        parts.append(f"L{x:.1f},{y:.1f}")
    d = " ".join(parts)
    base = (
        f'<path d="{d}" fill="none" '
        f'stroke="{FORTIFICATION_BASE_COLOR}" '
        f'stroke-width="{FORTIFICATION_BASE_WIDTH}" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    )
    overlay = (
        f'<path d="{d}" fill="none" '
        f'stroke="{FORTIFICATION_OVERLAY_COLOR}" '
        f'stroke-width="{FORTIFICATION_OVERLAY_WIDTH}" '
        f'stroke-dasharray="{FORTIFICATION_DASH_ARRAY}" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    )
    return [base, overlay]


def render_fortification_enclosure(
    polygon: list[tuple[float, float]],
    gates: list[tuple[int, float, float]] | None = None,
) -> list[str]:
    """Render a closed fortification polygon with optional gates.

    ``polygon`` is a list of pixel-coordinate vertices; the closing
    edge from the last point back to the first is implicit.

    ``gates`` is a list of ``(edge_index, t_center, half_len_px)``.
    ``edge_index`` addresses the edge from ``polygon[i]`` to
    ``polygon[(i + 1) % n]``; ``t_center`` is the gate midpoint
    parameter along that edge in ``[0, 1]``; ``half_len_px`` is the
    half-width of the gap in pixels. Gates on the same edge merge
    if their gaps overlap.

    When no gates are given, the polygon is closed and stroked as a
    single polyline. With gates, each edge is split into
    sub-polylines by its gate gaps and every surviving segment is
    stroked independently (base + overlay).
    """
    if not polygon:
        return []
    n = len(polygon)
    if n < 2:
        return []

    if not gates:
        closed = list(polygon) + [polygon[0]]
        return render_fortification_polyline(closed)

    # Group gates by edge index.
    by_edge: dict[int, list[tuple[float, float]]] = {}
    for edge_idx, t_center, half_px in gates:
        if not 0 <= edge_idx < n:
            continue
        a = polygon[edge_idx]
        b = polygon[(edge_idx + 1) % n]
        edge_len = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if edge_len < 1e-6:
            continue
        half_t = half_px / edge_len
        lo = max(0.0, t_center - half_t)
        hi = min(1.0, t_center + half_t)
        if hi > lo:
            by_edge.setdefault(edge_idx, []).append((lo, hi))

    # If every gate was rejected, fall back to the closed-loop render
    # so the caller sees a single polyline (consistent with the
    # gates=None path).
    if not by_edge:
        closed = list(polygon) + [polygon[0]]
        return render_fortification_polyline(closed)

    segments: list[list[tuple[float, float]]] = []
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        cuts = _merge_cuts(by_edge.get(i, []))
        subs = _subsegments(a, b, cuts)
        segments.extend(subs)

    out: list[str] = []
    for seg in segments:
        out.extend(render_fortification_polyline(seg))
    return out


def _merge_cuts(
    cuts: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not cuts:
        return []
    cuts = sorted(cuts)
    merged = [cuts[0]]
    for lo, hi in cuts[1:]:
        plo, phi = merged[-1]
        if lo <= phi:
            merged[-1] = (plo, max(phi, hi))
        else:
            merged.append((lo, hi))
    return merged


def _subsegments(
    a: tuple[float, float], b: tuple[float, float],
    cuts: list[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    ax, ay = a
    bx, by = b

    def _at(t: float) -> tuple[float, float]:
        return (ax + (bx - ax) * t, ay + (by - ay) * t)

    if not cuts:
        return [[a, b]]
    result: list[list[tuple[float, float]]] = []
    prev = 0.0
    for lo, hi in cuts:
        if lo > prev:
            result.append([_at(prev), _at(lo)])
        prev = hi
    if prev < 1.0:
        result.append([_at(prev), _at(1.0)])
    return result


def render_palisade_polyline(
    points: list[tuple[float, float]], *, seed: int = 0,
) -> list[str]:
    """Chain of overlapping circles along a polyline.

    Circles step every :data:`PALISADE_CIRCLE_STEP` pixels along the
    path, with radius uniformly sampled in
    ``[PALISADE_RADIUS_MIN, PALISADE_RADIUS_MAX]`` plus
    ``±PALISADE_RADIUS_JITTER`` jitter. Each circle carries the
    palisade fill and stroke.
    """
    if len(points) < 2:
        return []
    rng = random.Random(seed)
    out: list[str] = []
    carry = 0.0
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        dx, dy = bx - ax, by - ay
        seg_len = (dx * dx + dy * dy) ** 0.5
        if seg_len < 1e-6:
            continue
        ux, uy = dx / seg_len, dy / seg_len
        t = carry
        while t < seg_len:
            cx = ax + ux * t
            cy = ay + uy * t
            base_r = rng.uniform(
                PALISADE_RADIUS_MIN, PALISADE_RADIUS_MAX,
            )
            jitter = rng.uniform(
                -PALISADE_RADIUS_JITTER, PALISADE_RADIUS_JITTER,
            )
            r = max(0.1, base_r + jitter)
            out.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                f'r="{r:.1f}" '
                f'fill="{PALISADE_FILL}" '
                f'stroke="{PALISADE_STROKE}" '
                f'stroke-width="{PALISADE_STROKE_WIDTH}"/>'
            )
            t += PALISADE_CIRCLE_STEP
        carry = max(0.0, t - seg_len)
    return out


def render_palisade_enclosure(
    polygon: list[tuple[float, float]],
    gates: list[tuple[int, float, float]] | None = None,
    *, seed: int = 0,
) -> list[str]:
    """Render a closed palisade polygon with optional gate rectangles.

    Circles run along every surviving sub-segment of the polygon;
    each gate is replaced by a single brown rectangle of length
    :data:`PALISADE_DOOR_LENGTH_PX` centred on the gate midpoint and
    oriented along the edge. Edges retain a shared per-edge RNG
    stream so circle counts reduce in predictable amounts when a
    gate punches through.
    """
    if not polygon:
        return []
    n = len(polygon)
    if n < 2:
        return []

    if not gates:
        closed = list(polygon) + [polygon[0]]
        return render_palisade_polyline(closed, seed=seed)

    by_edge: dict[int, list[tuple[float, float]]] = {}
    midpoints: dict[int, list[tuple[float, float, float]]] = {}
    for edge_idx, t_center, half_px in gates:
        if not 0 <= edge_idx < n:
            continue
        a = polygon[edge_idx]
        b = polygon[(edge_idx + 1) % n]
        edge_len = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if edge_len < 1e-6:
            continue
        half_t = half_px / edge_len
        lo = max(0.0, t_center - half_t)
        hi = min(1.0, t_center + half_t)
        if hi > lo:
            by_edge.setdefault(edge_idx, []).append((lo, hi))
            midpoints.setdefault(edge_idx, []).append(
                (t_center, half_px, edge_len),
            )

    if not by_edge:
        closed = list(polygon) + [polygon[0]]
        return render_palisade_polyline(closed, seed=seed)

    out: list[str] = []
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        cuts = _merge_cuts(by_edge.get(i, []))
        subs = _subsegments(a, b, cuts)
        for sub in subs:
            out.extend(render_palisade_polyline(
                sub, seed=seed + i,
            ))
        for t_center, half_px, edge_len in midpoints.get(i, []):
            out.append(_palisade_door_rect(a, b, t_center, edge_len))
    return out


def _palisade_door_rect(
    a: tuple[float, float], b: tuple[float, float],
    t_center: float, edge_len: float,
) -> str:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    # Centre of the door in pixel coords.
    cx = ax + dx * t_center
    cy = ay + dy * t_center
    horizontal = abs(dy) < 1e-6
    vertical = abs(dx) < 1e-6
    thickness = 2.0 * PALISADE_RADIUS_MAX
    if horizontal:
        return (
            f'<rect x="{cx - PALISADE_DOOR_LENGTH_PX / 2:.1f}" '
            f'y="{cy - thickness / 2:.1f}" '
            f'width="{PALISADE_DOOR_LENGTH_PX:.1f}" '
            f'height="{thickness:.1f}" '
            f'fill="{PALISADE_FILL}" '
            f'stroke="{PALISADE_STROKE}" '
            f'stroke-width="{PALISADE_STROKE_WIDTH}"/>'
        )
    if vertical:
        return (
            f'<rect x="{cx - thickness / 2:.1f}" '
            f'y="{cy - PALISADE_DOOR_LENGTH_PX / 2:.1f}" '
            f'width="{thickness:.1f}" '
            f'height="{PALISADE_DOOR_LENGTH_PX:.1f}" '
            f'fill="{PALISADE_FILL}" '
            f'stroke="{PALISADE_STROKE}" '
            f'stroke-width="{PALISADE_STROKE_WIDTH}"/>'
        )
    # Oblique edge fallback: axis-aligned bounding box centred on
    # the door midpoint. Buildings are rectilinear so this path is
    # rarely taken.
    return (
        f'<rect x="{cx - PALISADE_DOOR_LENGTH_PX / 2:.1f}" '
        f'y="{cy - thickness / 2:.1f}" '
        f'width="{PALISADE_DOOR_LENGTH_PX:.1f}" '
        f'height="{thickness:.1f}" '
        f'fill="{PALISADE_FILL}" '
        f'stroke="{PALISADE_STROKE}" '
        f'stroke-width="{PALISADE_STROKE_WIDTH}"/>'
    )
