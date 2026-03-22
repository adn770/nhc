"""Entity to ASCII glyph and color mapping."""

from nhc.dungeon.model import Terrain

# Terrain → (glyph, color_name, dim_color_name)
# dim_color is used for explored-but-not-visible tiles
TERRAIN_GLYPHS: dict[Terrain, tuple[str, str, str]] = {
    Terrain.VOID:  (" ", "black", "black"),
    Terrain.WALL:  ("─", "white", "bright_black"),   # fallback; see wall_glyph()
    Terrain.FLOOR: (".", "bright_black", "black_on_black"),
    Terrain.WATER: ("~", "bright_blue", "blue"),
    Terrain.LAVA:  ("~", "bright_red", "red"),
    Terrain.CHASM: (" ", "black", "black"),
}

# Corridor tiles render as # (distinct from room floors)
CORRIDOR_GLYPH: tuple[str, str, str] = ("#", "bright_black", "black_on_black")

# Feature → (glyph, color_name)
FEATURE_GLYPHS: dict[str, tuple[str, str]] = {
    "door_closed": ("+", "yellow"),
    "door_open":   ("'", "yellow"),
    "door_locked": ("+", "bright_red"),
    "stairs_up":   ("<", "bright_white"),
    "stairs_down": (">", "bright_white"),
    "trap":        ("^", "bright_yellow"),
}

# Box-drawing wall glyph lookup: (connects_n, connects_s, connects_e, connects_w)
_WALL_GLYPHS: dict[tuple[bool, bool, bool, bool], str] = {
    (True,  True,  True,  True ): "┼",
    (True,  True,  True,  False): "├",
    (True,  True,  False, True ): "┤",
    (True,  False, True,  True ): "┴",
    (False, True,  True,  True ): "┬",
    (True,  True,  False, False): "│",
    (False, False, True,  True ): "─",
    (True,  False, True,  False): "└",
    (True,  False, False, True ): "┘",
    (False, True,  True,  False): "┌",
    (False, True,  False, True ): "┐",
    # Single-arm: extend in the one connecting direction
    (True,  False, False, False): "│",
    (False, True,  False, False): "│",
    (False, False, True,  False): "─",
    (False, False, False, True ): "─",
    (False, False, False, False): "─",
}


def wall_glyph(n: bool, s: bool, e: bool, w: bool) -> str:
    """Return the box-drawing character for a wall tile given neighbour connections.

    Each flag is True when that cardinal neighbour is also a wall (or
    out-of-bounds), meaning the wall continues in that direction.
    """
    return _WALL_GLYPHS.get((n, s, e, w), "─")
