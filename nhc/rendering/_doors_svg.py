"""Sample-only door overlay for site-surface SVGs.

The production web / console clients render doors themselves from
``Tile.door_side`` metadata; the SVG pipeline never draws them.
The sample generator (tests/samples/) needs visible doors on its
standalone SVG exports for offline visual review, so it imports
this helper and concatenates the fragments before ``</svg>``.

``door_overlay_fragments`` walks every tile of a ``Level`` and
emits one ``<rect>`` per visible door (closed / open / locked).
The rect is anchored to the tile edge indicated by
``door_side``; when the field is empty (interior dungeons that
never got their sides computed), the fallback is a centred rect
so the sample still shows where the door is.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level
from nhc.rendering._svg_helpers import CELL, PADDING, _is_door


# Door rect occupies 60% of the wall edge and 22% of the
# perpendicular axis, flush to the building-side edge.
_DOOR_LONG = 0.60
_DOOR_SHORT = 0.22

_CLOSED_FILL = "#7a5238"
_OPEN_FILL = "#c8a878"
_DOOR_STROKE = "#2a1a0e"
_DOOR_STROKE_WIDTH = 0.8


def _door_rect(
    x: int, y: int, door_side: str,
) -> tuple[float, float, float, float]:
    """Return (rx, ry, rw, rh) in SVG pixel coords for a door at
    cell (x, y) anchored to *door_side*. Empty side → centre rect.
    """
    tile_left = PADDING + x * CELL
    tile_top = PADDING + y * CELL
    long_px = _DOOR_LONG * CELL
    short_px = _DOOR_SHORT * CELL

    if door_side == "north":
        rx = tile_left + (CELL - long_px) / 2
        ry = tile_top
        rw, rh = long_px, short_px
    elif door_side == "south":
        rx = tile_left + (CELL - long_px) / 2
        ry = tile_top + CELL - short_px
        rw, rh = long_px, short_px
    elif door_side == "east":
        rx = tile_left + CELL - short_px
        ry = tile_top + (CELL - long_px) / 2
        rw, rh = short_px, long_px
    elif door_side == "west":
        rx = tile_left
        ry = tile_top + (CELL - long_px) / 2
        rw, rh = short_px, long_px
    else:
        # Centred fallback for doors without a recorded side.
        side = min(long_px, short_px * 2)
        rx = tile_left + (CELL - side) / 2
        ry = tile_top + (CELL - side) / 2
        rw = rh = side
    return rx, ry, rw, rh


def _door_fill(feature: str, rng: random.Random) -> str:
    """Pick a fill for the door based on its state. A tiny
    seed-driven luminance jitter keeps rows of identical doors
    from reading as a perfect stencil."""
    base = _OPEN_FILL if feature == "door_open" else _CLOSED_FILL
    # Scale by ±6% for organic variation.
    factor = 0.94 + rng.random() * 0.12
    r = int(int(base[1:3], 16) * factor)
    g = int(int(base[3:5], 16) * factor)
    b = int(int(base[5:7], 16) * factor)
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def door_overlay_fragments(
    level: Level, seed: int = 0,
) -> list[str]:
    """One SVG rect fragment per visible door on *level*."""
    fragments: list[str] = []
    rng = random.Random(seed)
    for y in range(level.height):
        for x in range(level.width):
            if not _is_door(level, x, y):
                continue
            tile = level.tiles[y][x]
            rx, ry, rw, rh = _door_rect(x, y, tile.door_side or "")
            fill = _door_fill(tile.feature, rng)
            fragments.append(
                f'<rect x="{rx:.2f}" y="{ry:.2f}" '
                f'width="{rw:.2f}" height="{rh:.2f}" '
                f'fill="{fill}" stroke="{_DOOR_STROKE}" '
                f'stroke-width="{_DOOR_STROKE_WIDTH}"/>'
            )
    return fragments
