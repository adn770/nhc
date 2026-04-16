"""Pure-function ASCII renderer for the overland hex view.

The terminal TUI renders the :class:`HexWorld` as a flat-top
odd-q staggered grid, one character per hex. Odd columns sit a
half-hex lower than their even neighbours so the result reads
visually as honeycomb even in plain ASCII.

Layout math, per hex at axial (q, r):

* column on screen : ``2 * q``           (two chars per hex)
* row on screen    : ``2 * r + (q % 2)`` (odd-q half-row shift)

Glyphs:

* Revealed hex → feature glyph if set, else biome glyph.
* Unrevealed (in-shape) hex → :data:`UNREVEALED_GLYPH`.
* Player's current coord → :data:`PLAYER_GLYPH` (wins over feature).

Status line (trailing frame row) reports day, time-of-day, axial
coord, biome, and any feature the player stands on.

The :class:`TerminalRenderer` calls :func:`build_hex_frame` and
prints the result. Keeping the renderer a pure function makes
every glyph choice unit-testable without a live ``blessed``
terminal.
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import Biome, HexFeatureType, HexWorld


# Single-char glyphs per biome. Chosen to read at a glance in a
# monochrome terminal: greenlands as a dot, forest as a hash,
# mountain as a caret, etc.
BIOME_GLYPH: dict[Biome, str] = {
    Biome.GREENLANDS: ".",
    Biome.DRYLANDS: ",",
    Biome.SANDLANDS: ":",
    Biome.ICELANDS: "_",
    Biome.DEADLANDS: "%",
    Biome.FOREST: "#",
    Biome.MOUNTAIN: "^",
    # Hills read as a rolling line, marsh as shallow water,
    # swamp as a denser wave motif. All three kept distinct
    # from the seven existing glyphs.
    Biome.HILLS: "n",
    Biome.MARSH: "~",
    Biome.SWAMP: "=",
}

# Feature overlays take priority over biome glyphs.
FEATURE_GLYPH: dict[HexFeatureType, str] = {
    HexFeatureType.VILLAGE: "v",
    HexFeatureType.CITY: "C",
    HexFeatureType.TOWER: "T",
    HexFeatureType.KEEP: "K",
    HexFeatureType.CAVE: "c",
    HexFeatureType.RUIN: "R",
    HexFeatureType.HOLE: "h",
    HexFeatureType.GRAVEYARD: "+",
    HexFeatureType.CRYSTALS: "*",
    HexFeatureType.STONES: "s",
    HexFeatureType.WONDER: "W",
    HexFeatureType.PORTAL: "P",
    HexFeatureType.LAKE: "~",
    HexFeatureType.RIVER: "=",
}

PLAYER_GLYPH = "@"
UNREVEALED_GLYPH = " "
OUT_OF_SHAPE_GLYPH = " "   # beyond the populated cells


def _screen_pos(coord: HexCoord) -> tuple[int, int]:
    """Return ``(col, row)`` for a hex at ``coord``.

    Two chars per hex horizontally so the stagger reads cleanly;
    odd-q columns shift one row down via ``(q % 2)``.
    """
    return 2 * coord.q, 2 * coord.r + (coord.q % 2)


def _glyph_for(world: HexWorld, coord: HexCoord) -> str:
    """Pick the single-char glyph for ``coord`` honouring fog."""
    cell = world.cells.get(coord)
    if cell is None:
        return OUT_OF_SHAPE_GLYPH
    if coord not in world.revealed:
        return UNREVEALED_GLYPH
    if cell.feature is not HexFeatureType.NONE:
        return FEATURE_GLYPH.get(cell.feature, "?")
    return BIOME_GLYPH.get(cell.biome, "?")


def build_hex_frame(
    world: HexWorld,
    player: HexCoord,
) -> str:
    """Return the ASCII frame for the current overland state.

    The frame is a newline-joined string: N grid rows followed by
    a one-line status bar. Grid rows are padded to a uniform width
    so downstream terminal code can slice rectangles without
    surprise.
    """
    # Compute pixel bounds from populated cells so the grid
    # always fits the in-shape cells exactly.
    coords = list(world.cells.keys())
    if not coords:
        return build_hex_status_line(world, player)

    max_col = 0
    max_row = 0
    for c in coords:
        col, row = _screen_pos(c)
        if col > max_col:
            max_col = col
        if row > max_row:
            max_row = row

    width = max_col + 1
    height = max_row + 1
    grid: list[list[str]] = [
        [OUT_OF_SHAPE_GLYPH] * width for _ in range(height)
    ]

    for coord in world.cells:
        col, row = _screen_pos(coord)
        grid[row][col] = _glyph_for(world, coord)

    # Player overlays whatever is beneath.
    p_col, p_row = _screen_pos(player)
    if 0 <= p_row < height and 0 <= p_col < width:
        grid[p_row][p_col] = PLAYER_GLYPH

    lines = ["".join(row) for row in grid]
    lines.append(build_hex_status_line(world, player))
    return "\n".join(lines)


def build_hex_status_line(
    world: HexWorld,
    player: HexCoord,
) -> str:
    """Single-line "Day N, <time> - (q, r) <biome>[, <feature>]"
    status bar rendered under the grid."""
    cell = world.cells.get(player)
    biome = cell.biome.value if cell else "unknown"
    feature = (
        cell.feature.value
        if cell and cell.feature is not HexFeatureType.NONE
        else None
    )
    feature_part = f", {feature}" if feature else ""
    return (
        f"Day {world.day}, {world.time.name.lower()} "
        f"- ({player.q}, {player.r}) {biome}{feature_part}"
    )
