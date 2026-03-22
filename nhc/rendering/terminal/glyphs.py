"""Entity to ASCII glyph and color mapping.

Two color modes are supported:

- **16** — classic 16-color terminals (xterm / linux console).
- **256** — 256-color / truecolor terminals (iTerm2, kitty, etc.).
  Explored-but-not-visible walls and corridors use a very dark grey
  so they remain subtly visible without competing with the FOV area.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.dungeon.model import Terrain

if TYPE_CHECKING:
    from blessed import Terminal

# ── 16-color palette (classic) ──────────────────────────────────────

# Terrain → (glyph, color_name, dim_color_name)
TERRAIN_GLYPHS_16: dict[Terrain, tuple[str, str, str]] = {
    Terrain.VOID:  (" ", "black", "black"),
    Terrain.WALL:  ("─", "white", "bright_black"),
    Terrain.FLOOR: (".", "bright_black", "bright_black"),
    Terrain.WATER: ("~", "bright_blue", "blue"),
    Terrain.LAVA:  ("~", "bright_red", "red"),
    Terrain.CHASM: (" ", "black", "black"),
}

CORRIDOR_GLYPH_16: tuple[str, str, str] = ("#", "bright_black", "bright_black")

# ── 256-color palette ───────────────────────────────────────────────
# dim colors are RGB tuples resolved at render time via term.color_rgb()

# Very dark grey for explored-but-not-visible structural tiles
_DIM_WALL = (45, 45, 50)       # blue-ish dark grey for walls
_DIM_CORRIDOR = (40, 40, 40)   # neutral dark grey for corridors
_DIM_FLOOR = (25, 25, 25)      # nearly invisible for floor dots

# Terrain → (glyph, color_name, dim_rgb)
TERRAIN_GLYPHS_256: dict[Terrain, tuple[str, str, tuple[int, int, int]]] = {
    Terrain.VOID:  (" ", "black", (0, 0, 0)),
    Terrain.WALL:  ("─", "white", _DIM_WALL),
    Terrain.FLOOR: (".", "bright_black", _DIM_FLOOR),
    Terrain.WATER: ("~", "bright_blue", (20, 30, 80)),
    Terrain.LAVA:  ("~", "bright_red", (80, 20, 20)),
    Terrain.CHASM: (" ", "black", (0, 0, 0)),
}

CORRIDOR_GLYPH_256: tuple[str, str, tuple[int, int, int]] = (
    "#", "bright_black", _DIM_CORRIDOR,
)

# Feature dim color in 256 mode
FEATURE_DIM_RGB = (50, 50, 55)

# ── Active palette (set by set_color_mode) ──────────────────────────

color_mode: str = "256"

# These are the tables the renderer imports.  They start as aliases for
# the 16-color tables and are swapped by set_color_mode().
TERRAIN_GLYPHS = dict(TERRAIN_GLYPHS_16)
CORRIDOR_GLYPH = CORRIDOR_GLYPH_16


def set_color_mode(mode: str) -> None:
    """Switch the active palette.  Call before the first render."""
    global color_mode, TERRAIN_GLYPHS, CORRIDOR_GLYPH  # noqa: PLW0603
    color_mode = mode
    if mode == "256":
        TERRAIN_GLYPHS.update(TERRAIN_GLYPHS_256)       # type: ignore[arg-type]
        CORRIDOR_GLYPH = CORRIDOR_GLYPH_256              # type: ignore[assignment]
    else:
        TERRAIN_GLYPHS.update(TERRAIN_GLYPHS_16)
        CORRIDOR_GLYPH = CORRIDOR_GLYPH_16


def dim_color_fn(term: "Terminal", dim_value: str | tuple[int, int, int]):
    """Return a callable that applies the dim color to text.

    *dim_value* is either a named color string (16-mode) or an
    ``(r, g, b)`` tuple (256-mode).
    """
    if isinstance(dim_value, tuple):
        r, g, b = dim_value
        return term.color_rgb(r, g, b)
    return getattr(term, dim_value, None) or term.bright_black

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
