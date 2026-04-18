"""Theme-aware terrain color palettes for SVG rendering.

Defines soft watercolor-style tints for each terrain type, varied
by dungeon theme.  All colors are deliberately desaturated to
preserve the Dyson Logos parchment aesthetic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TerrainStyle:
    """Visual parameters for one terrain type within a theme."""
    tint: str             # hex fill color for the semi-transparent wash
    tint_opacity: float   # 0.08-0.30 (soft watercolor range)
    detail_ink: str       # stroke color for hand-drawn detail marks
    detail_opacity: float # 0.2-0.6


@dataclass(frozen=True)
class ThemePalette:
    """Full terrain palette for a single dungeon theme."""
    water: TerrainStyle
    grass: TerrainStyle
    lava: TerrainStyle
    chasm: TerrainStyle


# ── Theme palettes ─────────────────────────────────────────────
#
# Opacity scales with theme darkness: castle is lightest,
# abyss is strongest.  Tints are desaturated washes that
# blend into the #F5EDE0 parchment background.

THEME_PALETTES: dict[str, ThemePalette] = {
    "dungeon": ThemePalette(
        water=TerrainStyle("#8BB8D0", 0.15, "#4A7888", 0.35),
        grass=TerrainStyle("#7BA87B", 0.12, "#3A6A3A", 0.30),
        lava=TerrainStyle("#D4816B", 0.18, "#A04030", 0.40),
        chasm=TerrainStyle("#888888", 0.10, "#444444", 0.35),
    ),
    "crypt": ThemePalette(
        water=TerrainStyle("#7A9EAA", 0.12, "#4A6E7A", 0.30),
        grass=TerrainStyle("#6B8B6B", 0.10, "#3A5A3A", 0.25),
        lava=TerrainStyle("#C47060", 0.15, "#903828", 0.35),
        chasm=TerrainStyle("#777777", 0.12, "#3A3A3A", 0.35),
    ),
    "cave": ThemePalette(
        water=TerrainStyle("#5B8FA0", 0.18, "#3A6070", 0.40),
        grass=TerrainStyle("#5A7A5A", 0.15, "#2A4A2A", 0.35),
        lava=TerrainStyle("#D49070", 0.20, "#A06040", 0.45),
        chasm=TerrainStyle("#666666", 0.15, "#333333", 0.40),
    ),
    "sewer": ThemePalette(
        water=TerrainStyle("#6A9A80", 0.20, "#3A6A50", 0.40),
        grass=TerrainStyle("#5A8A5A", 0.18, "#2A5A2A", 0.35),
        lava=TerrainStyle("#C48060", 0.15, "#904830", 0.35),
        chasm=TerrainStyle("#707070", 0.12, "#383838", 0.35),
    ),
    "castle": ThemePalette(
        water=TerrainStyle("#90C0D8", 0.12, "#5A8A9A", 0.30),
        grass=TerrainStyle("#88B888", 0.10, "#4A7A4A", 0.25),
        lava=TerrainStyle("#D4816B", 0.15, "#A04030", 0.35),
        chasm=TerrainStyle("#999999", 0.08, "#555555", 0.30),
    ),
    "forest": ThemePalette(
        water=TerrainStyle("#7AACB8", 0.15, "#4A7A88", 0.35),
        grass=TerrainStyle("#5A9A5A", 0.20, "#2A6A2A", 0.40),
        lava=TerrainStyle("#C48060", 0.15, "#904830", 0.35),
        chasm=TerrainStyle("#777777", 0.10, "#444444", 0.35),
    ),
    "abyss": ThemePalette(
        water=TerrainStyle("#4A7888", 0.22, "#2A5060", 0.45),
        grass=TerrainStyle("#3A5A3A", 0.08, "#1A3A1A", 0.20),
        lava=TerrainStyle("#E06040", 0.25, "#B03020", 0.50),
        chasm=TerrainStyle("#444444", 0.20, "#222222", 0.45),
    ),
    "tower": ThemePalette(
        water=TerrainStyle("#8AAABE", 0.12, "#5A7A8A", 0.30),
        grass=TerrainStyle("#7A9A7A", 0.08, "#4A6A4A", 0.22),
        lava=TerrainStyle("#C08070", 0.12, "#8A5A4A", 0.30),
        chasm=TerrainStyle("#9A9AAA", 0.10, "#5A5A6A", 0.30),
    ),
    "settlement": ThemePalette(
        water=TerrainStyle("#90C0D0", 0.10, "#5A8A9A", 0.25),
        grass=TerrainStyle("#88B888", 0.12, "#4A7A4A", 0.28),
        lava=TerrainStyle("#D4816B", 0.10, "#A04030", 0.25),
        chasm=TerrainStyle("#999999", 0.08, "#555555", 0.25),
    ),
    "mine": ThemePalette(
        water=TerrainStyle("#6A8A8A", 0.15, "#4A6868", 0.35),
        grass=TerrainStyle("#6A7A5A", 0.10, "#4A5A3A", 0.28),
        lava=TerrainStyle("#D08050", 0.20, "#A06030", 0.45),
        chasm=TerrainStyle("#5A4A3A", 0.18, "#3A2A1A", 0.40),
    ),
    "fungal_cavern": ThemePalette(
        water=TerrainStyle("#5A8A70", 0.18, "#3A6A50", 0.38),
        grass=TerrainStyle("#4A8A4A", 0.25, "#2A6A2A", 0.45),
        lava=TerrainStyle("#C07060", 0.12, "#904838", 0.30),
        chasm=TerrainStyle("#5A5A4A", 0.15, "#3A3A2A", 0.35),
    ),
    "lava_chamber": ThemePalette(
        water=TerrainStyle("#4A6878", 0.12, "#2A4858", 0.30),
        grass=TerrainStyle("#4A5A3A", 0.06, "#2A3A1A", 0.18),
        lava=TerrainStyle("#E06030", 0.28, "#C04020", 0.55),
        chasm=TerrainStyle("#3A2A1A", 0.22, "#1A1008", 0.45),
    ),
    "underground_lake": ThemePalette(
        water=TerrainStyle("#4A7898", 0.25, "#2A5878", 0.50),
        grass=TerrainStyle("#4A6A4A", 0.10, "#2A4A2A", 0.25),
        lava=TerrainStyle("#C08060", 0.10, "#905838", 0.25),
        chasm=TerrainStyle("#3A4A5A", 0.18, "#1A2A3A", 0.40),
    ),
}

# ── Room-type hint tints ───────────────────────────────────────
#
# Extremely subtle whole-room washes (opacity ~0.06) that hint
# at a room's purpose without being garish.

ROOM_TYPE_TINTS: dict[str, tuple[str, float]] = {
    "shrine":   ("#D0C8E8", 0.06),
    "garden":   ("#C8E0C0", 0.06),
    "library":  ("#E0D8C0", 0.06),
    "treasury": ("#E8E0B0", 0.06),
    "armory":   ("#D0C0B0", 0.06),
    "crypt":    ("#B8B0A0", 0.06),
    "trap_room":   ("#E0C0C0", 0.06),
    "barracks":    ("#C0B0A0", 0.06),
    "courtyard":   ("#D0E0C0", 0.06),
    "gate":        ("#B0A090", 0.06),
    "market":      ("#E0D0B0", 0.06),
    "residential": ("#D8D0C0", 0.06),
}


def get_palette(theme: str) -> ThemePalette:
    """Return the terrain palette for *theme*, defaulting to dungeon."""
    return THEME_PALETTES.get(theme, THEME_PALETTES["dungeon"])
