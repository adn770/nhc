"""Rendering themes for terminal display.

Three themes are available:
- **basic**: ASCII only, 16 colors, | and - for walls/borders.
- **modern** (default): Unicode box-drawing, 256 colors.
- **experimental**: Rich unicode symbols for a graphical feel, 256 colors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nhc.dungeon.model import Terrain


@dataclass
class Theme:
    """Complete rendering theme configuration."""

    name: str
    color_depth: str  # "16" or "256"

    # Terrain → (glyph, color, dim_color)
    terrain: dict = field(default_factory=dict)

    # Corridor: (glyph, color, dim_color)
    corridor: tuple = ("#", "bright_black", "bright_black")

    # Feature → (glyph, color)
    features: dict = field(default_factory=dict)

    # Wall connectivity: (n, s, e, w) → glyph
    walls: dict = field(default_factory=dict)

    # Rounded corner variants (╭╮╰╯) for wall corners
    walls_rounded: dict = field(default_factory=dict)

    # Feature dim color (for explored-but-not-visible)
    feature_dim: str | tuple = "bright_black"

    # UI chrome
    h_line: str = "-"
    v_sep: str = " | "
    box_tl: str = "+"  # top-left corner
    box_tr: str = "+"  # top-right corner
    box_bl: str = "+"  # bottom-left corner
    box_br: str = "+"  # bottom-right corner
    box_h: str = "-"   # horizontal border
    box_v: str = "|"   # vertical border

    # Player glyph override (None = use entity Renderable)
    player_glyph: str | None = None


# ── Shared feature table ──────────────────────────────────────────────

_FEATURES_BASE: dict[str, tuple[str, str]] = {
    "door_closed": ("+", "yellow"),
    "door_open":   ("'", "yellow"),
    "door_locked": ("+", "bright_red"),
    "stairs_up":   ("<", "bright_white"),
    "stairs_down": (">", "bright_white"),
    "trap":        ("^", "bright_yellow"),
}

# ── Wall lookup tables ────────────────────────────────────────────────

_WALLS_UNICODE: dict[tuple[bool, bool, bool, bool], str] = {
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
    (True,  False, False, False): "│",
    (False, True,  False, False): "│",
    (False, False, True,  False): "─",
    (False, False, False, True ): "─",
    (False, False, False, False): "─",
}

_WALLS_ASCII: dict[tuple[bool, bool, bool, bool], str] = {
    (True,  True,  True,  True ): "+",
    (True,  True,  True,  False): "+",
    (True,  True,  False, True ): "+",
    (True,  False, True,  True ): "+",
    (False, True,  True,  True ): "+",
    (True,  True,  False, False): "|",
    (False, False, True,  True ): "-",
    (True,  False, True,  False): "+",
    (True,  False, False, True ): "+",
    (False, True,  True,  False): "+",
    (False, True,  False, True ): "+",
    (True,  False, False, False): "|",
    (False, True,  False, False): "|",
    (False, False, True,  False): "-",
    (False, False, False, True ): "-",
    (False, False, False, False): "-",
}

_WALLS_EXPERIMENTAL: dict[tuple[bool, bool, bool, bool], str] = {
    (True,  True,  True,  True ): "╋",
    (True,  True,  True,  False): "┣",
    (True,  True,  False, True ): "┫",
    (True,  False, True,  True ): "┻",
    (False, True,  True,  True ): "┳",
    (True,  True,  False, False): "┃",
    (False, False, True,  True ): "━",
    (True,  False, True,  False): "┗",
    (True,  False, False, True ): "┛",
    (False, True,  True,  False): "┏",
    (False, True,  False, True ): "┓",
    (True,  False, False, False): "┃",
    (False, True,  False, False): "┃",
    (False, False, True,  False): "━",
    (False, False, False, True ): "━",
    (False, False, False, False): "━",
}

# ── Rounded corner variants ──────────────────────────────────────────
# Only the four L-shaped corner patterns get rounded glyphs.
# All other keys fall through to the regular walls dict.

_WALLS_ROUNDED_UNICODE: dict[tuple[bool, bool, bool, bool], str] = {
    (False, True,  True,  False): "╭",  # ┌ → ╭
    (False, True,  False, True ): "╮",  # ┐ → ╮
    (True,  False, True,  False): "╰",  # └ → ╰
    (True,  False, False, True ): "╯",  # ┘ → ╯
}

_WALLS_ROUNDED_EXPERIMENTAL: dict[tuple[bool, bool, bool, bool], str] = {
    (False, True,  True,  False): "╭",
    (False, True,  False, True ): "╮",
    (True,  False, True,  False): "╰",
    (True,  False, False, True ): "╯",
}

# ── Experimental feature glyphs (more graphical) ─────────────────────

_FEATURES_EXPERIMENTAL: dict[str, tuple[str, str]] = {
    "door_closed": ("⌸", "yellow"),
    "door_open":   ("⌷", "yellow"),
    "door_locked": ("⌸", "bright_red"),
    "stairs_up":   ("△", "bright_white"),
    "stairs_down": ("▽", "bright_white"),
    "trap":        ("⚠", "bright_yellow"),
}

# ── 16-color dim values ───────────────────────────────────────────────

_DIM_WALL_16 = "bright_black"
_DIM_CORRIDOR_16 = "bright_black"
_DIM_FLOOR_16 = "bright_black"

# ── 256-color dim values (RGB) ────────────────────────────────────────

_DIM_WALL_256 = (45, 45, 50)
_DIM_CORRIDOR_256 = (40, 40, 40)
_DIM_FLOOR_256 = (25, 25, 25)

# =====================================================================
# Theme definitions
# =====================================================================

THEME_BASIC = Theme(
    name="basic",
    color_depth="16",
    terrain={
        Terrain.VOID:  (" ", "black", "black"),
        Terrain.WALL:  ("-", "white", _DIM_WALL_16),
        Terrain.FLOOR: (".", "bright_black", _DIM_FLOOR_16),
        Terrain.WATER: ("~", "bright_blue", "blue"),
        Terrain.LAVA:  ("~", "bright_red", "red"),
        Terrain.CHASM: (" ", "black", "black"),
        Terrain.GRASS: (",", "green", "green"),
    },
    corridor=("#", "bright_black", _DIM_CORRIDOR_16),
    features=dict(_FEATURES_BASE),
    walls=_WALLS_ASCII,
    feature_dim="bright_black",
    h_line="-",
    v_sep=" | ",
    box_tl="+", box_tr="+", box_bl="+", box_br="+",
    box_h="-", box_v="|",
)

THEME_MODERN = Theme(
    name="modern",
    color_depth="256",
    terrain={
        Terrain.VOID:  (" ", "black", (0, 0, 0)),
        Terrain.WALL:  ("─", "white", _DIM_WALL_256),
        Terrain.FLOOR: (".", "bright_black", _DIM_FLOOR_256),
        Terrain.WATER: ("~", "bright_blue", (20, 30, 80)),
        Terrain.LAVA:  ("~", "bright_red", (80, 20, 20)),
        Terrain.CHASM: (" ", "black", (0, 0, 0)),
        Terrain.GRASS: (",", "green", (20, 60, 20)),
    },
    corridor=("#", "bright_black", _DIM_CORRIDOR_256),
    features=dict(_FEATURES_BASE),
    walls=_WALLS_UNICODE,
    walls_rounded=_WALLS_ROUNDED_UNICODE,
    feature_dim=(50, 50, 55),
    h_line="─",
    v_sep=" │ ",
    box_tl="╭", box_tr="╮", box_bl="╰", box_br="╯",
    box_h="─", box_v="│",
)

THEME_EXPERIMENTAL = Theme(
    name="experimental",
    color_depth="256",
    terrain={
        Terrain.VOID:  (" ", "black", (0, 0, 0)),
        Terrain.WALL:  ("━", "white", (50, 50, 60)),
        Terrain.FLOOR: (".", "bright_black", (20, 20, 20)),
        Terrain.WATER: ("≈", "bright_blue", (15, 25, 70)),
        Terrain.LAVA:  ("≈", "bright_red", (70, 15, 15)),
        Terrain.CHASM: ("░", "bright_black", (10, 10, 10)),
        Terrain.GRASS: (",", "green", (15, 55, 15)),
    },
    corridor=("⣿", "bright_black", (35, 35, 35)),
    features=_FEATURES_EXPERIMENTAL,
    walls=_WALLS_EXPERIMENTAL,
    walls_rounded=_WALLS_ROUNDED_EXPERIMENTAL,
    feature_dim=(50, 50, 55),
    h_line="─",
    v_sep=" │ ",
    box_tl="╭", box_tr="╮", box_bl="╰", box_br="╯",
    box_h="─", box_v="│",
)

# ── Registry ──────────────────────────────────────────────────────────

THEMES: dict[str, Theme] = {
    "basic": THEME_BASIC,
    "modern": THEME_MODERN,
    "experimental": THEME_EXPERIMENTAL,
}

# Active theme (set by set_theme)
_active: Theme = THEME_MODERN


def set_theme(name: str) -> None:
    """Activate a rendering theme by name."""
    global _active
    if name not in THEMES:
        raise ValueError(f"Unknown theme: {name!r} (available: {list(THEMES)})")
    _active = THEMES[name]


def get_theme() -> Theme:
    """Return the currently active theme."""
    return _active
