"""Field of view using recursive shadowcasting (8-octant).

Reference: http://www.roguebasin.com/index.php/FOV_using_recursive_shadowcasting
"""

from __future__ import annotations

from typing import Callable


def compute_fov(
    origin_x: int,
    origin_y: int,
    radius: int,
    is_blocking: Callable[[int, int], bool],
) -> set[tuple[int, int]]:
    """Compute visible tiles from origin using recursive shadowcasting.

    Args:
        origin_x, origin_y: Observer position.
        radius: Maximum sight radius.
        is_blocking: Returns True if (x, y) blocks line of sight.

    Returns:
        Set of (x, y) positions visible from origin.
    """
    visible: set[tuple[int, int]] = {(origin_x, origin_y)}

    # Process each of the 8 octants
    for octant in range(8):
        _cast_light(
            visible, origin_x, origin_y, radius,
            1, 1.0, 0.0, octant, is_blocking,
        )

    return visible


# Octant multipliers: maps (row, col) to (dx, dy) for each octant
_MULT = [
    (1, 0, 0, -1, -1, 0, 0, 1),   # xx
    (0, 1, -1, 0, 0, -1, 1, 0),   # xy
    (0, 1, 1, 0, 0, -1, -1, 0),   # yx
    (1, 0, 0, 1, -1, 0, 0, -1),   # yy
]


def _cast_light(
    visible: set[tuple[int, int]],
    cx: int, cy: int,
    radius: int,
    row: int,
    start_slope: float,
    end_slope: float,
    octant: int,
    is_blocking: Callable[[int, int], bool],
) -> None:
    if start_slope < end_slope:
        return

    xx = _MULT[0][octant]
    xy = _MULT[1][octant]
    yx = _MULT[2][octant]
    yy = _MULT[3][octant]

    next_start_slope = start_slope

    for j in range(row, radius + 1):
        blocked = False

        for dx in range(-j, 1):
            dy = -j

            # Map octant-relative coordinates to real coordinates
            map_x = cx + dx * xx + dy * xy
            map_y = cy + dx * yx + dy * yy

            l_slope = (dx - 0.5) / (dy + 0.5)
            r_slope = (dx + 0.5) / (dy - 0.5)

            if start_slope < r_slope:
                continue
            if end_slope > l_slope:
                break

            # Check if tile is within radius
            if dx * dx + dy * dy <= radius * radius:
                visible.add((map_x, map_y))

            if blocked:
                if is_blocking(map_x, map_y):
                    next_start_slope = r_slope
                else:
                    blocked = False
                    start_slope = next_start_slope
            elif is_blocking(map_x, map_y):
                blocked = True
                next_start_slope = r_slope
                _cast_light(
                    visible, cx, cy, radius,
                    j + 1, start_slope, l_slope,
                    octant, is_blocking,
                )

        if blocked:
            break
