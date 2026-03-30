"""Entity to ASCII glyph and color mapping.

All glyph/color definitions are delegated to the active theme
(see themes.py).  This module re-exports the same API that the
rest of the codebase expects so existing imports keep working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.dungeon.model import Terrain
from nhc.rendering.terminal.themes import get_theme, set_theme

if TYPE_CHECKING:
    from blessed import Terminal


# ── Active palette accessors ──────────────────────────────────────────
# These are properties that read from the active theme every time,
# so switching theme at runtime immediately takes effect.

def _get_terrain_glyphs():
    return get_theme().terrain

def _get_corridor_glyph():
    return get_theme().corridor

def _get_feature_glyphs():
    return get_theme().features

def _get_feature_dim():
    return get_theme().feature_dim


# For backward compat: module-level names that renderers import.
# These are now thin wrappers.
class _TerrainProxy(dict):
    """Dict-like object that always reads from the active theme."""
    def __getitem__(self, key):
        return get_theme().terrain[key]
    def get(self, key, default=None):
        return get_theme().terrain.get(key, default)
    def __contains__(self, key):
        return key in get_theme().terrain


TERRAIN_GLYPHS = _TerrainProxy()
FEATURE_GLYPHS = type("_FeatureProxy", (), {
    "__getitem__": lambda self, k: get_theme().features[k],
    "get": lambda self, k, d=None: get_theme().features.get(k, d),
    "__contains__": lambda self, k: k in get_theme().features,
})()

# Module-level color_mode for backward compat
color_mode: str = "256"

# Feature dim RGB (for 256-mode explored-but-not-visible features)
FEATURE_DIM_RGB = (50, 50, 55)


def set_color_mode(mode: str) -> None:
    """Switch the active palette.  Call before the first render.

    For backward compatibility: translates old color_mode strings
    to theme names.  "256" → "modern", "16" → "basic".
    """
    global color_mode, FEATURE_DIM_RGB
    color_mode = mode
    theme = get_theme()
    # Only auto-switch if the caller is using the old API
    # (not if a theme was explicitly set)
    if mode == "256" and theme.name == "basic":
        set_theme("modern")
    elif mode == "16" and theme.name != "basic":
        set_theme("basic")
    FEATURE_DIM_RGB = get_theme().feature_dim


def dim_color_fn(term: "Terminal", dim_value):
    """Return a callable that applies the dim color to text.

    *dim_value* is either a named color string (16-mode) or an
    ``(r, g, b)`` tuple (256-mode).
    """
    if isinstance(dim_value, tuple):
        r, g, b = dim_value
        return term.color_rgb(r, g, b)
    return getattr(term, dim_value, None) or term.bright_black


@property
def _corridor_glyph_prop():
    return get_theme().corridor

# Backward compat: CORRIDOR_GLYPH is accessed as a module-level tuple.
# We use a class trick to make it dynamic.
class _CorridorProxy:
    def __iter__(self):
        return iter(get_theme().corridor)
    def __getitem__(self, i):
        return get_theme().corridor[i]
    def __len__(self):
        return len(get_theme().corridor)

CORRIDOR_GLYPH = _CorridorProxy()


def wall_glyph(
    n: bool, s: bool, e: bool, w: bool,
    rounded: bool = False,
) -> str:
    """Return the wall character for given neighbour connections.

    When *rounded* is True and the theme provides a rounded variant
    for this connection pattern (typically L-shaped corners), the
    rounded glyph is returned instead (e.g. ╭ instead of ┌).
    """
    theme = get_theme()
    key = (n, s, e, w)
    if rounded and theme.walls_rounded:
        glyph = theme.walls_rounded.get(key)
        if glyph:
            return glyph
    return theme.walls.get(key, theme.terrain.get(
        Terrain.WALL, ("-", "white", "bright_black"))[0])
