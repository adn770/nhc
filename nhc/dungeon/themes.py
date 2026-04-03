"""Depth-based dungeon theme selection."""

from __future__ import annotations


def theme_for_depth(depth: int) -> str:
    """Map dungeon depth to a visual theme.

    Progression: dungeon → crypt → cave → castle → abyss.
    """
    if depth <= 4:
        return "dungeon"
    elif depth <= 8:
        return "crypt"
    elif depth <= 12:
        return "cave"
    elif depth <= 16:
        return "castle"
    else:
        return "abyss"
