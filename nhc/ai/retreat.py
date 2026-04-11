"""Shared retreat-step picker.

Used by any creature that wants to back away from a threat one
tile at a time: morale-broken monsters in the fleeing state, and
unhired adventurers running into a hostile (henchman_ai). The
caller supplies its own walkability predicate so that the helper
stays free of any specific entity / movement rules.
"""

from __future__ import annotations

from typing import Callable

from nhc.utils.spatial import chebyshev


def best_retreat_step(
    pos: tuple[int, int],
    threat_pos: tuple[int, int],
    is_walkable: Callable[[int, int], bool],
) -> tuple[int, int] | None:
    """Return the (dx, dy) step that puts the most distance
    between ``pos`` and ``threat_pos``.

    Considers the eight cardinal/diagonal neighbours, skips the
    no-op (0, 0) step, and only picks a step strictly farther
    from the threat than the current tile. Returns ``None`` when
    no walkable neighbour improves on the current distance — the
    creature is effectively cornered and the caller should fall
    back to fighting (or holding).
    """
    px, py = pos
    tx, ty = threat_pos
    current = chebyshev(px, py, tx, ty)

    best: tuple[int, int] | None = None
    best_dist = current
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = px + dx, py + dy
            if not is_walkable(nx, ny):
                continue
            d = chebyshev(nx, ny, tx, ty)
            if d > best_dist:
                best_dist = d
                best = (dx, dy)
    return best
