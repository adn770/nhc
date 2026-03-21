"""Entity to ASCII glyph and color mapping."""

from nhc.dungeon.model import Terrain

# Terrain → (glyph, color_name, dim_color_name)
# dim_color is used for explored-but-not-visible tiles
TERRAIN_GLYPHS: dict[Terrain, tuple[str, str, str]] = {
    Terrain.VOID:  (" ", "black", "black"),
    Terrain.WALL:  ("#", "white", "bright_black"),
    Terrain.FLOOR: (".", "bright_black", "black_on_black"),
    Terrain.WATER: ("~", "bright_blue", "blue"),
    Terrain.LAVA:  ("~", "bright_red", "red"),
    Terrain.CHASM: (" ", "black", "black"),
}

# Feature → (glyph, color_name)
FEATURE_GLYPHS: dict[str, tuple[str, str]] = {
    "door_closed": ("+", "yellow"),
    "door_open":   ("'", "yellow"),
    "door_locked": ("+", "bright_red"),
    "stairs_up":   ("<", "bright_white"),
    "stairs_down": (">", "bright_white"),
    "trap":        ("^", "bright_yellow"),
}
