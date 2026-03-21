"""Grid math, coordinates, direction helpers."""

from __future__ import annotations

# Direction vectors: (dx, dy)
DIRECTIONS: dict[str, tuple[int, int]] = {
    "n":  (0, -1),
    "s":  (0, 1),
    "e":  (1, 0),
    "w":  (-1, 0),
    "ne": (1, -1),
    "nw": (-1, -1),
    "se": (1, 1),
    "sw": (-1, 1),
}


def chebyshev(x1: int, y1: int, x2: int, y2: int) -> int:
    """Chebyshev (chessboard) distance between two points."""
    return max(abs(x2 - x1), abs(y2 - y1))


def adjacent(x1: int, y1: int, x2: int, y2: int) -> bool:
    """Check if two positions are adjacent (Chebyshev distance <= 1)."""
    return chebyshev(x1, y1, x2, y2) == 1


def neighbors(x: int, y: int) -> list[tuple[int, int]]:
    """Return all 8 neighboring positions."""
    return [(x + dx, y + dy) for dx, dy in DIRECTIONS.values()]
