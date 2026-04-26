"""Surface-feature decorations for the floor SVG renderer.

Most ``Tile.feature`` tags (well, shrine, signpost, campfire,
tomb_entrance, ...) carry no glyph in :func:`render_floor_svg` --
the interactable is an ECS entity placed by the populator at
runtime and rendered by the web client's tileset on top of the
SVG. A handful of features benefit from a static decoration baked
into the SVG so they read on the surface map even before any
entity is overlaid (and on the standalone sample SVGs produced by
``tests/samples/generate_svg.py``).

This module owns those decorations. Today it covers wells; future
features (shrine altar, campfire pit, etc.) should grow their
own ``render_*_features`` helper here so the dispatcher stays
centralised.
"""

from __future__ import annotations

import colorsys
import math

from nhc.dungeon.model import Level
from nhc.rendering._svg_helpers import CELL, INK


# ── Well ──────────────────────────────────────────────────────

# Outer / inner ring radii in tile units. Outer = 0.85 of a tile
# half-diagonal so the decoration fits comfortably inside the
# 3x3 tile neighbourhood around the centerpiece without leaking
# into adjacent rooms or the cobblestone seams.
WELL_OUTER_RADIUS = 0.85 * CELL
WELL_INNER_RADIUS = 0.55 * CELL
WELL_WATER_RADIUS = 0.42 * CELL
WELL_KEYSTONE_COUNT = 16
WELL_KEYSTONE_GAP_RAD = math.radians(2.5)
WELL_STONE_FILL = "#EFE4D2"
WELL_STONE_STROKE = INK
WELL_STONE_STROKE_WIDTH = 1.4
WELL_OUTER_RING_STROKE_WIDTH = 1.8
WELL_WATER_FILL = "#3F6E9A"
WELL_WATER_STROKE = "#22466B"
WELL_WATER_STROKE_WIDTH = 1.0
WELL_HIGHLIGHT_FILL = "rgba(255,255,255,0.18)"
"""Legacy soft-fill colour. No longer used; kept exported so
 callers / tests that still reference the constant compile."""

# Water movement: irregular short curved strokes scattered inside
# the water disc representing surface ripples / motion. Replaces
# the older concentric "light glint" rings -- maps in
# docs/maps/Legend2.jpg show water bodies with wavy lines, not
# light bands, and the cartographer style is closer to "stream"
# / "pool" markings than to a metallic sheen.
WATER_MOVEMENT_STROKE = "#FFFFFF"
"""White ripples read clearly against the dark blue water disc."""

WATER_MOVEMENT_STROKE_WIDTH = 0.9
WATER_MOVEMENT_STROKE_ALPHA = 0.65
WATER_MOVEMENT_DASH = "2 2"
WATER_MOVEMENT_MARK_COUNT = 4
WATER_MOVEMENT_AREA_FACTOR = 0.55
"""Marks scatter inside this fraction of the water radius -- keeps
ripples away from the rim where the keystone gap reads."""
WATER_MOVEMENT_RADIUS_MIN_FACTOR = 0.18
WATER_MOVEMENT_RADIUS_MAX_FACTOR = 0.34
WATER_MOVEMENT_SWEEP_MIN = 0.5
"""Min sweep length in radians (~30 deg)."""
WATER_MOVEMENT_SWEEP_MAX = 1.4
"""Max sweep length in radians (~80 deg)."""

_WATER_MOVEMENT_SALT = 22013


def _water_movement_fragments(
    cx: float, cy: float, water_radius: float, *,
    tx: int, ty: int,
    cls: str = "well-water-movement",
) -> list[str]:
    """Short irregular arc strokes scattered inside the water disc.

    Suggests surface ripples / movement (cartographer style)
    rather than a single light glint. Determined by ``(tx, ty)``
    so the same well always paints the same ripples.

    Note: ``_scatter_volume_marks`` and friends are defined later
    in this module; Python resolves the names at call time, so
    placement is fine."""
    paths = _scatter_volume_marks(
        cx=cx, cy=cy,
        tx=tx, ty=ty, salt=_WATER_MOVEMENT_SALT,
        n_marks=WATER_MOVEMENT_MARK_COUNT,
        area_radius=water_radius * WATER_MOVEMENT_AREA_FACTOR,
        mark_radius_min=(
            water_radius * WATER_MOVEMENT_RADIUS_MIN_FACTOR
        ),
        mark_radius_max=(
            water_radius * WATER_MOVEMENT_RADIUS_MAX_FACTOR
        ),
        sweep_min=WATER_MOVEMENT_SWEEP_MIN,
        sweep_max=WATER_MOVEMENT_SWEEP_MAX,
    )
    return [
        (
            f'<path class="{cls}" d="{d}" '
            f'fill="none" stroke="{WATER_MOVEMENT_STROKE}" '
            f'stroke-width="{WATER_MOVEMENT_STROKE_WIDTH:.2f}" '
            f'stroke-opacity="{WATER_MOVEMENT_STROKE_ALPHA:.2f}" '
            f'stroke-dasharray="{WATER_MOVEMENT_DASH}" '
            f'stroke-linecap="round"/>'
        )
        for d in paths
    ]

# Square well geometry. Outer / inner / water radii are reused
# from the circle constants (so a square well sits in the same
# tile-centred bounding box as the circle variant); the only
# new dimensions are stone counts and gaps.
#
# Layout: top + bottom rows span the full outer width with
# ``WELL_SQUARE_STONES_PER_LONG_SIDE`` stones each, taking
# ownership of the corners. Left + right rows span only the
# inner section (between the top and bottom rows) with
# ``WELL_SQUARE_STONES_PER_SHORT_SIDE`` stones each, so corners
# don't double up. Total = 2L + 2S stones.
WELL_SQUARE_STONES_PER_LONG_SIDE = 4
WELL_SQUARE_STONES_PER_SHORT_SIDE = 4
WELL_SQUARE_STONE_COUNT = (
    2 * WELL_SQUARE_STONES_PER_LONG_SIDE
    + 2 * WELL_SQUARE_STONES_PER_SHORT_SIDE
)
WELL_SQUARE_STONE_GAP_PX = 1.5
WELL_SQUARE_STONE_RADIUS_PX = 1.6
WELL_SQUARE_OUTER_RX_PX = 3.0
WELL_SQUARE_WATER_RX_PX = 2.0


# ── Fountain (2x2 footprint) ─────────────────────────────────
#
# Fountains share the well's water-feature aesthetic but scale
# up to a 2x2 tile footprint. The top-left tile of the 2x2
# carries the ``feature`` tag; the decoration is centred on the
# corner shared by the four tiles -- (tx+1, ty+1) * CELL.
#
# Outer radius is sized so the rim spans almost the full 2x2
# area without bleeding into adjacent tiles. Stone counts are
# higher than the well's so each individual stone keeps roughly
# the same visible arc length / edge length as a well stone.
FOUNTAIN_OUTER_RADIUS = 0.92 * CELL
FOUNTAIN_INNER_RADIUS = 0.74 * CELL
FOUNTAIN_WATER_RADIUS = 0.66 * CELL
FOUNTAIN_PEDESTAL_OUTER_RADIUS = 0.22 * CELL
FOUNTAIN_PEDESTAL_INNER_RADIUS = 0.12 * CELL
FOUNTAIN_KEYSTONE_COUNT = 24
FOUNTAIN_KEYSTONE_GAP_RAD = math.radians(2.0)
FOUNTAIN_OUTER_RING_STROKE_WIDTH = 1.8
FOUNTAIN_PEDESTAL_STROKE_WIDTH = 1.4
FOUNTAIN_WATER_FILL = WELL_WATER_FILL
FOUNTAIN_WATER_STROKE = WELL_WATER_STROKE
FOUNTAIN_STONE_FILL = WELL_STONE_FILL
FOUNTAIN_STONE_STROKE = INK
FOUNTAIN_STONE_STROKE_WIDTH = 1.4
FOUNTAIN_PEDESTAL_FILL = "#D9C9AE"
FOUNTAIN_SPOUT_FILL = "#7FB6E0"
FOUNTAIN_HIGHLIGHT_FILL = WELL_HIGHLIGHT_FILL

FOUNTAIN_SQUARE_STONES_PER_LONG_SIDE = 6
FOUNTAIN_SQUARE_STONES_PER_SHORT_SIDE = 6
FOUNTAIN_SQUARE_STONE_COUNT = (
    2 * FOUNTAIN_SQUARE_STONES_PER_LONG_SIDE
    + 2 * FOUNTAIN_SQUARE_STONES_PER_SHORT_SIDE
)
FOUNTAIN_SQUARE_STONE_GAP_PX = 1.5
FOUNTAIN_SQUARE_STONE_RADIUS_PX = 1.6
FOUNTAIN_SQUARE_OUTER_RX_PX = 4.0
FOUNTAIN_SQUARE_WATER_RX_PX = 2.5
FOUNTAIN_SQUARE_PEDESTAL_RX_PX = 2.0


def _keystone_path(
    cx: float, cy: float,
    inner_r: float, outer_r: float,
    a0: float, a1: float,
) -> str:
    """SVG path for one keystone-shaped stone in the ring.

    The stone is the radial wedge between angles ``a0`` and ``a1``
    on the inner / outer radii. The two short edges (the sides
    of the wedge) are flat radial segments; the long edges follow
    the inner and outer arcs. ``stroke-linejoin="round"`` on the
    output shape softens the four corners so the keystone reads
    as a hand-drawn stone rather than a CAD slice.
    """
    ox0 = cx + math.cos(a0) * outer_r
    oy0 = cy + math.sin(a0) * outer_r
    ox1 = cx + math.cos(a1) * outer_r
    oy1 = cy + math.sin(a1) * outer_r
    ix1 = cx + math.cos(a1) * inner_r
    iy1 = cy + math.sin(a1) * inner_r
    ix0 = cx + math.cos(a0) * inner_r
    iy0 = cy + math.sin(a0) * inner_r
    # sweep_flag=1 outer arc clockwise (positive angle direction);
    # sweep_flag=0 inner arc counter-clockwise back to start.
    return (
        f'M{ox0:.2f},{oy0:.2f} '
        f'A{outer_r:.2f},{outer_r:.2f} 0 0 1 {ox1:.2f},{oy1:.2f} '
        f'L{ix1:.2f},{iy1:.2f} '
        f'A{inner_r:.2f},{inner_r:.2f} 0 0 0 {ix0:.2f},{iy0:.2f} '
        f'Z'
    )


def _well_fragment_for_tile(tx: int, ty: int) -> str:
    """SVG ``<g>`` fragment for a single well at tile ``(tx, ty)``.

    Composition (back to front):

    * Outer black ring (the masonry rim seen from above).
    * 16 keystone stones sitting between the inner and outer
      radius, each separated by :data:`WELL_KEYSTONE_GAP_RAD`.
    * Water disc -- a deep-blue circle inside the inner ring with
      a thin darker stroke for the waterline.
    * A faint translucent highlight crescent on the water for a
      subtle wet-stone glint.
    """
    cx = (tx + 0.5) * CELL
    cy = (ty + 0.5) * CELL

    parts: list[str] = [
        f'<g id="well-{tx}-{ty}" class="well-feature" '
        'stroke-linejoin="round">',
    ]

    # Outer ring (masonry rim outline). Drawn first so the
    # keystones layer on top of it; the rim's stroke peeks out
    # at the gaps between stones to read as the rim's shadow.
    parts.append(
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" '
        f'r="{WELL_OUTER_RADIUS:.2f}" '
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{WELL_OUTER_RING_STROKE_WIDTH:.2f}"/>'
    )

    step = (2 * math.pi) / WELL_KEYSTONE_COUNT
    for i in range(WELL_KEYSTONE_COUNT):
        a0 = i * step + WELL_KEYSTONE_GAP_RAD / 2
        a1 = (i + 1) * step - WELL_KEYSTONE_GAP_RAD / 2
        d = _keystone_path(
            cx, cy,
            WELL_INNER_RADIUS, WELL_OUTER_RADIUS,
            a0, a1,
        )
        parts.append(
            f'<path class="well-keystone" d="{d}" '
            f'fill="{WELL_STONE_FILL}" '
            f'stroke="{WELL_STONE_STROKE}" '
            f'stroke-width="{WELL_STONE_STROKE_WIDTH:.2f}"/>'
        )

    # Water disc + waterline.
    parts.append(
        f'<circle class="well-water" cx="{cx:.2f}" cy="{cy:.2f}" '
        f'r="{WELL_WATER_RADIUS:.2f}" '
        f'fill="{WELL_WATER_FILL}" '
        f'stroke="{WELL_WATER_STROKE}" '
        f'stroke-width="{WELL_WATER_STROKE_WIDTH:.2f}"/>'
    )

    # Surface ripples (irregular discontinuous arcs) scattered
    # across the water disc -- reads as movement / motion in the
    # cartographer style, not as a single light glint.
    parts.extend(_water_movement_fragments(
        cx, cy, WELL_WATER_RADIUS,
        tx=tx, ty=ty,
        cls="well-water-movement",
    ))

    parts.append('</g>')
    return "".join(parts)


def _square_stone_rect(
    x: float, y: float, w: float, h: float,
) -> str:
    """Single perimeter stone for a square well."""
    return (
        f'<rect class="well-stone" '
        f'x="{x:.2f}" y="{y:.2f}" '
        f'width="{w:.2f}" height="{h:.2f}" '
        f'rx="{WELL_SQUARE_STONE_RADIUS_PX:.2f}" '
        f'fill="{WELL_STONE_FILL}" '
        f'stroke="{WELL_STONE_STROKE}" '
        f'stroke-width="{WELL_STONE_STROKE_WIDTH:.2f}"/>'
    )


def _square_well_fragment_for_tile(tx: int, ty: int) -> str:
    """SVG ``<g>`` fragment for a square well at tile ``(tx, ty)``.

    Mirrors :func:`_well_fragment_for_tile` but with a rectangular
    rim and a square water pool. Stones are arranged around the
    perimeter -- the long (top + bottom) rows own the corners,
    the short (left + right) rows fill only the inner span so
    corners don't overlap. Same outer half-width as the circle
    variant so both shapes occupy the same footprint.
    """
    cx = (tx + 0.5) * CELL
    cy = (ty + 0.5) * CELL
    outer = WELL_OUTER_RADIUS
    inner = WELL_INNER_RADIUS
    depth = outer - inner
    gap = WELL_SQUARE_STONE_GAP_PX

    parts: list[str] = [
        f'<g id="well-{tx}-{ty}" class="well-feature" '
        'stroke-linejoin="round">',
    ]

    # Outer ring (rounded square outline).
    parts.append(
        f'<rect x="{cx - outer:.2f}" y="{cy - outer:.2f}" '
        f'width="{2 * outer:.2f}" height="{2 * outer:.2f}" '
        f'rx="{WELL_SQUARE_OUTER_RX_PX:.2f}" '
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{WELL_OUTER_RING_STROKE_WIDTH:.2f}"/>'
    )

    # Top + bottom rows: full outer width, four stones each.
    long_n = WELL_SQUARE_STONES_PER_LONG_SIDE
    long_span = 2 * outer
    long_stone = (long_span - (long_n + 1) * gap) / long_n
    for i in range(long_n):
        x0 = cx - outer + gap + i * (long_stone + gap)
        # Top row.
        parts.append(_square_stone_rect(
            x0, cy - outer + gap, long_stone, depth - 2 * gap,
        ))
        # Bottom row.
        parts.append(_square_stone_rect(
            x0, cy + inner + gap, long_stone, depth - 2 * gap,
        ))

    # Left + right rows: only the inner span, four stones each.
    short_n = WELL_SQUARE_STONES_PER_SHORT_SIDE
    short_span = 2 * inner
    short_stone = (short_span - (short_n + 1) * gap) / short_n
    for i in range(short_n):
        y0 = cy - inner + gap + i * (short_stone + gap)
        # Left column.
        parts.append(_square_stone_rect(
            cx - outer + gap, y0, depth - 2 * gap, short_stone,
        ))
        # Right column.
        parts.append(_square_stone_rect(
            cx + inner + gap, y0, depth - 2 * gap, short_stone,
        ))

    # Square water pool with rounded corners + waterline stroke.
    water = WELL_WATER_RADIUS
    parts.append(
        f'<rect class="well-water" '
        f'x="{cx - water:.2f}" y="{cy - water:.2f}" '
        f'width="{2 * water:.2f}" height="{2 * water:.2f}" '
        f'rx="{WELL_SQUARE_WATER_RX_PX:.2f}" '
        f'fill="{WELL_WATER_FILL}" '
        f'stroke="{WELL_WATER_STROKE}" '
        f'stroke-width="{WELL_WATER_STROKE_WIDTH:.2f}"/>'
    )

    parts.extend(_water_movement_fragments(
        cx, cy, water, tx=tx, ty=ty,
        cls="well-water-movement",
    ))

    parts.append('</g>')
    return "".join(parts)


def _circle_fountain_fragment_for_tile(tx: int, ty: int) -> str:
    """SVG ``<g>`` fragment for a circular fountain anchored at
    tile ``(tx, ty)`` (top-left of the 2x2 footprint).

    Composition (back to front):

    * Outer black ring (the basin's masonry rim).
    * 24 keystone stones along the perimeter, separated by small
      angular gaps so they read as discrete blocks.
    * Water disc filling the inner ring.
    * Wet-stone highlight crescent on the upper-left of the water.
    * Central pedestal -- a small stone disc with a darker
      light-blue spout opening on top, suggesting water rising
      from a sculpted basin.
    """
    cx = (tx + 1) * CELL
    cy = (ty + 1) * CELL

    parts: list[str] = [
        f'<g id="fountain-{tx}-{ty}" class="fountain-feature" '
        'stroke-linejoin="round">',
    ]

    parts.append(
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" '
        f'r="{FOUNTAIN_OUTER_RADIUS:.2f}" '
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2f}"/>'
    )

    step = (2 * math.pi) / FOUNTAIN_KEYSTONE_COUNT
    for i in range(FOUNTAIN_KEYSTONE_COUNT):
        a0 = i * step + FOUNTAIN_KEYSTONE_GAP_RAD / 2
        a1 = (i + 1) * step - FOUNTAIN_KEYSTONE_GAP_RAD / 2
        d = _keystone_path(
            cx, cy,
            FOUNTAIN_INNER_RADIUS, FOUNTAIN_OUTER_RADIUS,
            a0, a1,
        )
        parts.append(
            f'<path class="fountain-keystone" d="{d}" '
            f'fill="{FOUNTAIN_STONE_FILL}" '
            f'stroke="{FOUNTAIN_STONE_STROKE}" '
            f'stroke-width="{FOUNTAIN_STONE_STROKE_WIDTH:.2f}"/>'
        )

    parts.append(
        f'<circle class="fountain-water" '
        f'cx="{cx:.2f}" cy="{cy:.2f}" '
        f'r="{FOUNTAIN_WATER_RADIUS:.2f}" '
        f'fill="{FOUNTAIN_WATER_FILL}" '
        f'stroke="{FOUNTAIN_WATER_STROKE}" '
        f'stroke-width="{WELL_WATER_STROKE_WIDTH:.2f}"/>'
    )

    parts.extend(_water_movement_fragments(
        cx, cy, FOUNTAIN_WATER_RADIUS,
        tx=tx, ty=ty,
        cls="fountain-water-movement",
    ))

    # Pedestal: stone disc + spout opening on top.
    parts.append(
        f'<circle class="fountain-pedestal" '
        f'cx="{cx:.2f}" cy="{cy:.2f}" '
        f'r="{FOUNTAIN_PEDESTAL_OUTER_RADIUS:.2f}" '
        f'fill="{FOUNTAIN_PEDESTAL_FILL}" '
        f'stroke="{INK}" '
        f'stroke-width="{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2f}"/>'
    )
    parts.append(
        f'<circle class="fountain-spout" '
        f'cx="{cx:.2f}" cy="{cy:.2f}" '
        f'r="{FOUNTAIN_PEDESTAL_INNER_RADIUS:.2f}" '
        f'fill="{FOUNTAIN_SPOUT_FILL}" '
        f'stroke="{FOUNTAIN_WATER_STROKE}" '
        f'stroke-width="{WELL_WATER_STROKE_WIDTH:.2f}"/>'
    )

    parts.append('</g>')
    return "".join(parts)


def _fountain_stone_rect(
    x: float, y: float, w: float, h: float,
) -> str:
    """Single perimeter stone for a square fountain."""
    return (
        f'<rect class="fountain-stone" '
        f'x="{x:.2f}" y="{y:.2f}" '
        f'width="{w:.2f}" height="{h:.2f}" '
        f'rx="{FOUNTAIN_SQUARE_STONE_RADIUS_PX:.2f}" '
        f'fill="{FOUNTAIN_STONE_FILL}" '
        f'stroke="{FOUNTAIN_STONE_STROKE}" '
        f'stroke-width="{FOUNTAIN_STONE_STROKE_WIDTH:.2f}"/>'
    )


def _square_fountain_fragment_for_tile(tx: int, ty: int) -> str:
    """Square (rectangular-rim) fountain at tile ``(tx, ty)``
    anchor (top-left of the 2x2 footprint).

    Mirrors :func:`_circle_fountain_fragment_for_tile` with a
    rounded-square rim, perimeter stones owned by the long
    rows on the corners, square water pool, and a square
    pedestal at the centre.
    """
    cx = (tx + 1) * CELL
    cy = (ty + 1) * CELL
    outer = FOUNTAIN_OUTER_RADIUS
    inner = FOUNTAIN_INNER_RADIUS
    depth = outer - inner
    gap = FOUNTAIN_SQUARE_STONE_GAP_PX

    parts: list[str] = [
        f'<g id="fountain-{tx}-{ty}" class="fountain-feature" '
        'stroke-linejoin="round">',
    ]

    parts.append(
        f'<rect x="{cx - outer:.2f}" y="{cy - outer:.2f}" '
        f'width="{2 * outer:.2f}" height="{2 * outer:.2f}" '
        f'rx="{FOUNTAIN_SQUARE_OUTER_RX_PX:.2f}" '
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2f}"/>'
    )

    long_n = FOUNTAIN_SQUARE_STONES_PER_LONG_SIDE
    long_span = 2 * outer
    long_stone = (long_span - (long_n + 1) * gap) / long_n
    for i in range(long_n):
        x0 = cx - outer + gap + i * (long_stone + gap)
        parts.append(_fountain_stone_rect(
            x0, cy - outer + gap, long_stone, depth - 2 * gap,
        ))
        parts.append(_fountain_stone_rect(
            x0, cy + inner + gap, long_stone, depth - 2 * gap,
        ))

    short_n = FOUNTAIN_SQUARE_STONES_PER_SHORT_SIDE
    short_span = 2 * inner
    short_stone = (short_span - (short_n + 1) * gap) / short_n
    for i in range(short_n):
        y0 = cy - inner + gap + i * (short_stone + gap)
        parts.append(_fountain_stone_rect(
            cx - outer + gap, y0, depth - 2 * gap, short_stone,
        ))
        parts.append(_fountain_stone_rect(
            cx + inner + gap, y0, depth - 2 * gap, short_stone,
        ))

    water = FOUNTAIN_WATER_RADIUS
    parts.append(
        f'<rect class="fountain-water" '
        f'x="{cx - water:.2f}" y="{cy - water:.2f}" '
        f'width="{2 * water:.2f}" height="{2 * water:.2f}" '
        f'rx="{FOUNTAIN_SQUARE_WATER_RX_PX:.2f}" '
        f'fill="{FOUNTAIN_WATER_FILL}" '
        f'stroke="{FOUNTAIN_WATER_STROKE}" '
        f'stroke-width="{WELL_WATER_STROKE_WIDTH:.2f}"/>'
    )

    parts.extend(_water_movement_fragments(
        cx, cy, water, tx=tx, ty=ty,
        cls="fountain-water-movement",
    ))

    pedestal = FOUNTAIN_PEDESTAL_OUTER_RADIUS
    parts.append(
        f'<rect class="fountain-pedestal" '
        f'x="{cx - pedestal:.2f}" y="{cy - pedestal:.2f}" '
        f'width="{2 * pedestal:.2f}" height="{2 * pedestal:.2f}" '
        f'rx="{FOUNTAIN_SQUARE_PEDESTAL_RX_PX:.2f}" '
        f'fill="{FOUNTAIN_PEDESTAL_FILL}" '
        f'stroke="{INK}" '
        f'stroke-width="{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2f}"/>'
    )
    spout = FOUNTAIN_PEDESTAL_INNER_RADIUS
    parts.append(
        f'<rect class="fountain-spout" '
        f'x="{cx - spout:.2f}" y="{cy - spout:.2f}" '
        f'width="{2 * spout:.2f}" height="{2 * spout:.2f}" '
        f'rx="{FOUNTAIN_SQUARE_PEDESTAL_RX_PX:.2f}" '
        f'fill="{FOUNTAIN_SPOUT_FILL}" '
        f'stroke="{FOUNTAIN_WATER_STROKE}" '
        f'stroke-width="{WELL_WATER_STROKE_WIDTH:.2f}"/>'
    )

    parts.append('</g>')
    return "".join(parts)


_WELL_DISPATCH = {
    "well": _well_fragment_for_tile,
    "well_square": _square_well_fragment_for_tile,
}

_FOUNTAIN_DISPATCH = {
    "fountain": _circle_fountain_fragment_for_tile,
    "fountain_square": _square_fountain_fragment_for_tile,
}


# ── Tree (Phase 4b: town periphery vegetation) ───────────────
#
# Single-canopy palette, biome variants deferred (Q4). Canopy
# radius ~0.7 * CELL gives a medium-sized tree (~1.5 tiles wide)
# so individual trees still feel substantial and adjacent trees
# overlap into a dense grove. Phase 4a's scatter excludes tiles
# 4-adjacent to building footprints so the canopy never bleeds
# onto a building roof in the SVG render.

TREE_CANOPY_FILL = "#6B8A56"
"""Soft FIELD-tinted green; blends with the periphery wash."""

TREE_CANOPY_STROKE = "#3F5237"
"""Darker outline so the canopy reads as foliage on greenscale
 surfaces."""

TREE_CANOPY_STROKE_WIDTH = 1.2

TREE_CANOPY_STROKE_ALPHA = 0.78
"""Silhouette stroke alpha; a low-alpha rim instead of a hard
 outline so adjacent canopies blend rather than stamp."""

# Cartographer-style canopy: a "broccoli head" silhouette built
# by unioning N small overlapping circles (lobes). Each lobe is
# placed around the tile centre with deterministic per-tile
# angle / offset / radius jitter so adjacent canopies look
# distinct rather than tiled. The union outline reads as a
# multi-lobed cloud, mirroring the Mike Schley / Dyson Logos
# tree style in docs/maps.

TREE_CANOPY_RADIUS = 0.66 * CELL
"""Approximate outer extent of a single canopy. Used by
:func:`_tree_canopy_polygon` to size the lobe cluster and by the
M2 grove union when picking the fallback radius."""

TREE_CANOPY_LOBE_COUNT = 6
TREE_CANOPY_LOBE_RADIUS = 0.32 * CELL
"""Each lobe's base radius (overlap creates the puffy outline)."""

TREE_CANOPY_CLUSTER_RADIUS = 0.30 * CELL
"""Distance from canopy centre to the centre of each lobe."""

TREE_CANOPY_LOBE_RADIUS_JITTER = 0.20
"""+/- multiplier on lobe radius (per-tile, per-lobe)."""

TREE_CANOPY_LOBE_OFFSET_JITTER = 0.30
"""+/- multiplier on lobe offset distance from centre."""

TREE_CANOPY_LOBE_ANGLE_JITTER = 0.35
"""+/- radians on lobe angular position."""

TREE_CANOPY_SHADOW_FILL = "#2F4527"
"""Darker green sitting behind the canopy to give the silhouette
 visual weight."""

TREE_CANOPY_SHADOW_LOBE_RADIUS = 0.36 * CELL
"""Shadow uses larger lobes than the canopy so the silhouette
peeks out as a darker rim."""

TREE_CANOPY_SHADOW_OFFSET = 0.05 * CELL
"""Offset (down-right) for the shadow lobe centres -- the
classic cartographer drop-shadow on the lower-right face."""

# Volume marks: short irregular arc strokes inside the canopy
# representing leaf-cluster shadows (where one foliage clump
# meets the next). Drawn in the silhouette stroke colour (darker
# than the canopy fill) so they read as inner shadow / volume
# rather than as light glints. Discontinuous by construction
# (each is a partial-circle arc, not a closed loop) plus an
# extra ``stroke-dasharray`` to break each arc further.

TREE_VOLUME_MARK_COUNT = 6
TREE_VOLUME_MARK_AREA_RADIUS = 0.45 * CELL
"""Radius around tile centre within which volume marks scatter."""

TREE_VOLUME_MARK_RADIUS_MIN = 0.07 * CELL
TREE_VOLUME_MARK_RADIUS_MAX = 0.13 * CELL

TREE_VOLUME_MARK_SWEEP_MIN = 0.7
"""Min arc sweep length in radians (~40 deg)."""
TREE_VOLUME_MARK_SWEEP_MAX = 1.8
"""Max arc sweep length in radians (~103 deg)."""

TREE_VOLUME_STROKE_WIDTH = 0.8
TREE_VOLUME_STROKE_ALPHA = 0.55
TREE_VOLUME_DASH = "2 2"

TREE_HUE_JITTER_DEG = 6.0
TREE_SAT_JITTER = 0.05
TREE_LIGHT_JITTER = 0.04

TREE_TRUNK_FILL = "#4A3320"
TREE_TRUNK_STROKE = INK
TREE_TRUNK_STROKE_WIDTH = 0.9
TREE_TRUNK_RADIUS = 0.16 * CELL
TREE_TRUNK_OFFSET_Y = 0.32 * CELL
"""Trunk dot anchors slightly below the canopy centre so the
 tree reads as standing on the tile rather than floating."""


def _hash_norm(tx: int, ty: int, salt: int) -> float:
    """Deterministic hash mapping ``(tx, ty, salt)`` to ``[-1, 1]``.

    Knuth-style multiply-and-xor; same shape as the original
    ``_tree_canopy_jitter`` but factored so highlight, shadow,
    hue, and bush layers can each pick a unique salt.
    """
    h = (tx * 73856093) ^ (ty * 19349663) ^ (salt * 83492791)
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    return (h / 0xFFFFFFFF) * 2.0 - 1.0


def _hash_unit(tx: int, ty: int, salt: int) -> float:
    """Deterministic hash mapping ``(tx, ty, salt)`` to ``[0, 1]``.

    Distinct from :func:`_hash_norm` (which returns ``[-1, 1]``).
    Used when we want a positive-only random factor (e.g.,
    picking a length within ``[min, max]``)."""
    h = (tx * 73856093) ^ (ty * 19349663) ^ (salt * 83492791)
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    return h / 0xFFFFFFFF


def _hex_to_rgb01(hex_str: str) -> tuple[float, float, float]:
    s = hex_str.lstrip("#")
    return (
        int(s[0:2], 16) / 255.0,
        int(s[2:4], 16) / 255.0,
        int(s[4:6], 16) / 255.0,
    )


def _rgb01_to_hex(r: float, g: float, b: float) -> str:
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))
    return f"#{int(round(r * 255)):02X}{int(round(g * 255)):02X}{int(round(b * 255)):02X}"


def _shift_color(
    base_hex: str,
    *,
    hue_deg: float = 0.0,
    sat: float = 0.0,
    light: float = 0.0,
) -> str:
    """Return ``base_hex`` shifted in HLS space by the given deltas.

    ``hue_deg`` is in degrees (full circle = 360); ``sat`` and
    ``light`` are absolute deltas on the HLS [0, 1] range.
    """
    r, g, b = _hex_to_rgb01(base_hex)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h = (h + hue_deg / 360.0) % 1.0
    s = max(0.0, min(1.0, s + sat))
    l = max(0.0, min(1.0, l + light))
    rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
    return _rgb01_to_hex(rr, gg, bb)


# Salts: keep distinct integers per channel so hue / sat / light
# don't collapse to the same hash output for a given tile.
_HUE_SALT = 1009
_SAT_SALT = 2017
_LIGHT_SALT = 3041


def _canopy_fill_jitter(tx: int, ty: int) -> str:
    """Per-tile jittered canopy fill derived from
    :data:`TREE_CANOPY_FILL`."""
    dh = _hash_norm(tx, ty, _HUE_SALT) * TREE_HUE_JITTER_DEG
    ds = _hash_norm(tx, ty, _SAT_SALT) * TREE_SAT_JITTER
    dl = _hash_norm(tx, ty, _LIGHT_SALT) * TREE_LIGHT_JITTER
    return _shift_color(
        TREE_CANOPY_FILL, hue_deg=dh, sat=ds, light=dl,
    )


def _lobe_circles(
    cx: float, cy: float, *,
    tx: int, ty: int, salt: int,
    n_lobes: int,
    lobe_radius: float,
    cluster_radius: float,
    radius_jitter: float = 0.20,
    offset_jitter: float = 0.30,
    angle_jitter: float = 0.35,
) -> list[tuple[float, float, float]]:
    """Deterministic per-tile list of ``(lcx, lcy, lr)`` lobe
    circles arranged in a cluster around ``(cx, cy)``.

    ``n_lobes`` circles are placed roughly evenly on a ring of
    radius ``cluster_radius`` then perturbed in angle / offset /
    radius. Unioning them produces the puffy multi-lobed
    cartographer silhouette."""
    step = (2 * math.pi) / n_lobes
    out: list[tuple[float, float, float]] = []
    for i in range(n_lobes):
        a_jit = _hash_norm(tx, ty, salt + i * 7) * angle_jitter
        o_jit = 1.0 + _hash_norm(
            tx, ty, salt + i * 11 + 1,
        ) * offset_jitter
        r_jit = 1.0 + _hash_norm(
            tx, ty, salt + i * 13 + 2,
        ) * radius_jitter
        ang = i * step + a_jit
        offs = cluster_radius * o_jit
        lr = lobe_radius * r_jit
        out.append((
            cx + math.cos(ang) * offs,
            cy + math.sin(ang) * offs,
            lr,
        ))
    return out


def _polygon_to_svg_path(geom) -> str:
    """Convert a Shapely Polygon / MultiPolygon to an SVG ``d``
    string. Each exterior ring + interior hole becomes its own
    closed sub-path; ``fill-rule="evenodd"`` is the responsibility
    of the caller's ``<path>`` attributes."""
    geoms = (
        list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    )
    parts: list[str] = []
    for poly in geoms:
        rings = [list(poly.exterior.coords)]
        for hole in poly.interiors:
            rings.append(list(hole.coords))
        for coords in rings:
            if not coords:
                continue
            parts.append(
                f"M{coords[0][0]:.2f},{coords[0][1]:.2f}"
            )
            for x, y in coords[1:]:
                parts.append(f"L{x:.2f},{y:.2f}")
            parts.append("Z")
    return " ".join(parts)


def _union_path_from_lobes(
    lobes: list[tuple[float, float, float]],
) -> str:
    """Shapely-union the lobe circles and return an SVG ``d``."""
    from shapely.geometry import Point
    from shapely.ops import unary_union
    polys = [Point(c[0], c[1]).buffer(c[2]) for c in lobes]
    return _polygon_to_svg_path(unary_union(polys))


def _tree_canopy_lobes(
    cx: float, cy: float, tx: int, ty: int,
) -> list[tuple[float, float, float]]:
    return _lobe_circles(
        cx, cy,
        tx=tx, ty=ty, salt=4001,
        n_lobes=TREE_CANOPY_LOBE_COUNT,
        lobe_radius=TREE_CANOPY_LOBE_RADIUS,
        cluster_radius=TREE_CANOPY_CLUSTER_RADIUS,
        radius_jitter=TREE_CANOPY_LOBE_RADIUS_JITTER,
        offset_jitter=TREE_CANOPY_LOBE_OFFSET_JITTER,
        angle_jitter=TREE_CANOPY_LOBE_ANGLE_JITTER,
    )


def _tree_shadow_lobes(
    cx: float, cy: float, tx: int, ty: int,
) -> list[tuple[float, float, float]]:
    """Shadow lobes mirror the canopy positions but use a larger
    radius and a small down-right offset so the shadow peeks out
    on the lower-right face."""
    return _lobe_circles(
        cx + TREE_CANOPY_SHADOW_OFFSET,
        cy + TREE_CANOPY_SHADOW_OFFSET,
        tx=tx, ty=ty, salt=5003,
        n_lobes=TREE_CANOPY_LOBE_COUNT,
        lobe_radius=TREE_CANOPY_SHADOW_LOBE_RADIUS,
        cluster_radius=TREE_CANOPY_CLUSTER_RADIUS,
        radius_jitter=TREE_CANOPY_LOBE_RADIUS_JITTER,
        offset_jitter=TREE_CANOPY_LOBE_OFFSET_JITTER,
        angle_jitter=TREE_CANOPY_LOBE_ANGLE_JITTER,
    )


def _tree_canopy_path(cx: float, cy: float, tx: int, ty: int) -> str:
    """Canopy outline ``d`` -- shapely union of lobe circles."""
    return _union_path_from_lobes(
        _tree_canopy_lobes(cx, cy, tx, ty),
    )


def _tree_shadow_path(cx: float, cy: float, tx: int, ty: int) -> str:
    """Shadow outline ``d`` -- shapely union of larger lobes."""
    return _union_path_from_lobes(
        _tree_shadow_lobes(cx, cy, tx, ty),
    )


def _arc_path(
    cx: float, cy: float, r: float, a0: float, a1: float,
) -> str:
    """Open arc segment from angle ``a0`` to ``a1`` (radians).

    Returns a non-closing ``d`` string (no ``Z``) so the stroke
    reads as a curved line rather than a closed shape."""
    sx = cx + math.cos(a0) * r
    sy = cy + math.sin(a0) * r
    ex = cx + math.cos(a1) * r
    ey = cy + math.sin(a1) * r
    sweep_len = a1 - a0
    large_arc = 1 if abs(sweep_len) > math.pi else 0
    sweep_dir = 1 if sweep_len >= 0 else 0
    return (
        f"M{sx:.2f},{sy:.2f} "
        f"A{r:.2f},{r:.2f} 0 {large_arc} {sweep_dir} "
        f"{ex:.2f},{ey:.2f}"
    )


def _scatter_volume_marks(
    *, cx: float, cy: float,
    tx: int, ty: int, salt: int,
    n_marks: int,
    area_radius: float,
    mark_radius_min: float,
    mark_radius_max: float,
    sweep_min: float,
    sweep_max: float,
) -> list[str]:
    """Generate ``n_marks`` short irregular arcs scattered inside
    the area around ``(cx, cy)``. Each mark's centre, radius,
    sweep start and sweep length are deterministically derived
    from ``(tx, ty, salt)``.

    Returns SVG ``d`` strings; the caller wraps each in a
    ``<path>`` with the desired stroke style."""
    out: list[str] = []
    for i in range(n_marks):
        # Position inside area circle (use sqrt to avoid centre
        # bias).
        u = _hash_unit(tx, ty, salt + i * 17 + 3)
        ang = _hash_norm(
            tx, ty, salt + i * 19 + 5,
        ) * math.pi  # [-pi, pi]
        r_pos = area_radius * math.sqrt(u)
        mx = cx + math.cos(ang) * r_pos
        my = cy + math.sin(ang) * r_pos
        # Mark radius
        u_r = _hash_unit(tx, ty, salt + i * 23 + 7)
        mr = mark_radius_min + (
            mark_radius_max - mark_radius_min
        ) * u_r
        # Sweep start + length
        sweep_start = _hash_norm(
            tx, ty, salt + i * 29 + 11,
        ) * math.pi
        u_sw = _hash_unit(tx, ty, salt + i * 31 + 13)
        sweep_len = sweep_min + (sweep_max - sweep_min) * u_sw
        out.append(_arc_path(
            mx, my, mr,
            sweep_start, sweep_start + sweep_len,
        ))
    return out


def _tree_volume_fragments(
    cx: float, cy: float, tx: int, ty: int, stroke_color: str,
    *, salt: int = 7011,
) -> list[str]:
    """Volume-mark fragments for one tree at ``(cx, cy)``.

    Short irregular arcs scattered inside the canopy in the
    silhouette stroke colour, suggesting where leaf clusters
    meet (inner shadow / volume cue, not light)."""
    paths = _scatter_volume_marks(
        cx=cx, cy=cy,
        tx=tx, ty=ty, salt=salt,
        n_marks=TREE_VOLUME_MARK_COUNT,
        area_radius=TREE_VOLUME_MARK_AREA_RADIUS,
        mark_radius_min=TREE_VOLUME_MARK_RADIUS_MIN,
        mark_radius_max=TREE_VOLUME_MARK_RADIUS_MAX,
        sweep_min=TREE_VOLUME_MARK_SWEEP_MIN,
        sweep_max=TREE_VOLUME_MARK_SWEEP_MAX,
    )
    return [
        (
            f'<path class="tree-volume" d="{d}" '
            f'fill="none" stroke="{stroke_color}" '
            f'stroke-width="{TREE_VOLUME_STROKE_WIDTH:.2f}" '
            f'stroke-opacity="{TREE_VOLUME_STROKE_ALPHA:.2f}" '
            f'stroke-dasharray="{TREE_VOLUME_DASH}" '
            f'stroke-linecap="round"/>'
        )
        for d in paths
    ]


def _tree_fragment_for_tile(tx: int, ty: int) -> str:
    """SVG ``<g>`` fragment for a single tree at tile ``(tx, ty)``.

    Composition (back to front):

    * Brown trunk dot anchored slightly below the canopy centre.
    * Multi-lobed shadow silhouette (shapely union of larger
      lobes, offset down-right) sitting behind the canopy.
    * Multi-lobed canopy silhouette (shapely union of small
      overlapping circles -- a "broccoli head") with per-tile
      hue / sat / light jitter so adjacent canopies read as
      distinct.
    * Volume marks: short irregular arc strokes scattered inside
      the canopy in the silhouette stroke colour, suggesting
      where leaf clusters meet (inner shadow / volume cue).
    * Low-alpha silhouette stroke (re-uses the canopy ``d``)
      tracing the bumpy outline.
    """
    cx = (tx + 0.5) * CELL
    cy = (ty + 0.5) * CELL
    trunk_cx = cx
    trunk_cy = cy + TREE_TRUNK_OFFSET_Y
    canopy_d = _tree_canopy_path(cx, cy, tx, ty)
    shadow_d = _tree_shadow_path(cx, cy, tx, ty)
    canopy_fill = _canopy_fill_jitter(tx, ty)
    parts = [
        f'<g id="tree-{tx}-{ty}" class="tree-feature">',
        (
            f'<circle class="tree-trunk" cx="{trunk_cx:.2f}" '
            f'cy="{trunk_cy:.2f}" r="{TREE_TRUNK_RADIUS:.2f}" '
            f'fill="{TREE_TRUNK_FILL}" '
            f'stroke="{TREE_TRUNK_STROKE}" '
            f'stroke-width="{TREE_TRUNK_STROKE_WIDTH:.2f}"/>'
        ),
        (
            f'<path class="tree-canopy-shadow" d="{shadow_d}" '
            f'fill="{TREE_CANOPY_SHADOW_FILL}" stroke="none"/>'
        ),
        (
            f'<path class="tree-canopy" d="{canopy_d}" '
            f'fill="{canopy_fill}" stroke="none"/>'
        ),
    ]
    parts.extend(_tree_volume_fragments(
        cx, cy, tx, ty, TREE_CANOPY_STROKE,
    ))
    parts.extend([
        (
            f'<path class="tree-silhouette" d="{canopy_d}" '
            f'fill="none" stroke="{TREE_CANOPY_STROKE}" '
            f'stroke-width="{TREE_CANOPY_STROKE_WIDTH:.2f}" '
            f'stroke-opacity="{TREE_CANOPY_STROKE_ALPHA:.2f}"/>'
        ),
        '</g>',
    ])
    return "".join(parts)


# ── Tree grove merging (M2) ──────────────────────────────────
#
# Adjacent trees (4-adjacency) form a connected component;
# components of size >= 3 collapse into a single Shapely-unioned
# silhouette so the canopies fuse into one organic mass like the
# cartographer maps. Singles + pairs keep the per-tile path so
# the visual weight of two distinct trunks reads.


def _connected_tree_groves(level) -> list[frozenset[tuple[int, int]]]:
    """4-adjacency BFS over ``tile.feature == "tree"``.

    Returns one frozenset of ``(tx, ty)`` tuples per connected
    grove. Diagonal-only neighbours stay separate."""
    height = level.height
    width = level.width
    visited: list[list[bool]] = [
        [False] * width for _ in range(height)
    ]
    groves: list[frozenset[tuple[int, int]]] = []
    for sy in range(height):
        for sx in range(width):
            if visited[sy][sx]:
                continue
            if level.tiles[sy][sx].feature != "tree":
                continue
            grove: set[tuple[int, int]] = set()
            stack: list[tuple[int, int]] = [(sx, sy)]
            while stack:
                cx, cy = stack.pop()
                if cx < 0 or cy < 0 or cx >= width or cy >= height:
                    continue
                if visited[cy][cx]:
                    continue
                if level.tiles[cy][cx].feature != "tree":
                    continue
                visited[cy][cx] = True
                grove.add((cx, cy))
                stack.append((cx + 1, cy))
                stack.append((cx - 1, cy))
                stack.append((cx, cy + 1))
                stack.append((cx, cy - 1))
            if grove:
                groves.append(frozenset(grove))
    return groves


def _grove_for_tile(
    level, tx: int, ty: int,
) -> frozenset[tuple[int, int]] | None:
    """Return the grove containing ``(tx, ty)`` or ``None`` if
    the tile isn't a tree (or the level is missing)."""
    if level is None:
        return None
    for grove in _connected_tree_groves(level):
        if (tx, ty) in grove:
            return grove
    return None


def _grove_union_fragment(
    grove: frozenset[tuple[int, int]],
) -> str:
    """One ``<g class='tree-grove'>`` fragment representing the
    union of every per-tree lobe cluster in ``grove``.

    Layered identically to :func:`_tree_fragment_for_tile`:
    shadow union -> canopy union -> volume marks (one set per
    tile in the grove) -> low-alpha silhouette stroke. Trunks
    are dropped -- a fused grove reads as merged foliage rather
    than as a row of distinct trunks.

    Per-grove hue jitter seeds from ``min(grove)`` so adding /
    removing one tree nudges the colour rather than flipping it
    across the whole silhouette."""
    from shapely.geometry import Point  # local import: hot path
    from shapely.ops import unary_union

    anchor = min(grove)
    canopy_polys = []
    shadow_polys = []
    for tx, ty in grove:
        cx = (tx + 0.5) * CELL
        cy = (ty + 0.5) * CELL
        # Use the same per-tile lobe cluster so the grove silhouette
        # has the same bumpy character as a row of single trees,
        # then unions across all tiles.
        for lcx, lcy, lr in _tree_canopy_lobes(cx, cy, tx, ty):
            canopy_polys.append(Point(lcx, lcy).buffer(lr))
        for lcx, lcy, lr in _tree_shadow_lobes(cx, cy, tx, ty):
            shadow_polys.append(Point(lcx, lcy).buffer(lr))
    canopy_d = _polygon_to_svg_path(unary_union(canopy_polys))
    shadow_d = _polygon_to_svg_path(unary_union(shadow_polys))

    canopy_fill = _canopy_fill_jitter(*anchor)
    parts = [
        f'<g id="tree-grove-{anchor[0]}-{anchor[1]}" '
        'class="tree-grove">',
        (
            f'<path class="tree-canopy-shadow" d="{shadow_d}" '
            f'fill="{TREE_CANOPY_SHADOW_FILL}" stroke="none"/>'
        ),
        (
            f'<path class="tree-canopy" d="{canopy_d}" '
            f'fill="{canopy_fill}" stroke="none"/>'
        ),
    ]
    # Volume marks: emit one set per tile in the grove so the
    # union surface stays evenly speckled regardless of grove
    # shape.
    for tx, ty in sorted(grove):
        cx = (tx + 0.5) * CELL
        cy = (ty + 0.5) * CELL
        parts.extend(_tree_volume_fragments(
            cx, cy, tx, ty, TREE_CANOPY_STROKE,
        ))
    parts.extend([
        (
            f'<path class="tree-silhouette" d="{canopy_d}" '
            f'fill="none" stroke="{TREE_CANOPY_STROKE}" '
            f'stroke-width="{TREE_CANOPY_STROKE_WIDTH:.2f}" '
            f'stroke-opacity="{TREE_CANOPY_STROKE_ALPHA:.2f}"/>'
        ),
        '</g>',
    ])
    return "".join(parts)


def _tree_paint_for_tile(
    level, tx: int, ty: int,
) -> str | None:
    """Tree paint dispatcher: per-tile fragment for groves of
    size <= 2; one grove fragment at ``min(grove)`` for groves
    of size >= 3 (other tiles return ``None``)."""
    grove = _grove_for_tile(level, tx, ty)
    if grove is None or len(grove) <= 2:
        return _tree_fragment_for_tile(tx, ty)
    if (tx, ty) != min(grove):
        return None
    return _grove_union_fragment(grove)


_TREE_DISPATCH = {
    "tree": _tree_fragment_for_tile,
}


# ── Bush (M3: small foliage decorator) ───────────────────────
#
# Smaller pom-pom canopy with no trunk. Canopy radius + jitter
# stays strictly below ``0.5 * CELL`` so the silhouette never
# crosses the tile boundary -- the M4 placement pass can then
# sit bushes 4-adjacent to building footprints without bleeding
# canopy onto roofs (the differentiator from trees, which keep
# a one-tile clearance for canopy / roof overlap).

BUSH_CANOPY_FILL = "#7A9560"
"""Lighter than :data:`TREE_CANOPY_FILL` so bushes read as
shorter foliage."""

BUSH_CANOPY_STROKE = "#3F5237"

BUSH_CANOPY_STROKE_WIDTH = 1.0

BUSH_CANOPY_STROKE_ALPHA = 0.78

BUSH_CANOPY_RADIUS = 0.32 * CELL
"""Approximate outer extent of a bush silhouette. Used to size
the lobe cluster and as a sanity bound for tile-clearance tests."""

BUSH_CANOPY_LOBE_COUNT = 3
"""Fewer lobes than a tree -- a bush is small enough that 3-4
bumps already read as multi-lobed."""

BUSH_CANOPY_LOBE_RADIUS = 0.16 * CELL
BUSH_CANOPY_CLUSTER_RADIUS = 0.10 * CELL

BUSH_CANOPY_LOBE_RADIUS_JITTER = 0.18
BUSH_CANOPY_LOBE_OFFSET_JITTER = 0.30
BUSH_CANOPY_LOBE_ANGLE_JITTER = 0.40

BUSH_CANOPY_SHADOW_FILL = "#3F5237"
"""Shadow lobes for the bush silhouette -- darker than the
canopy fill (mirrors the tree shadow but smaller)."""

BUSH_CANOPY_SHADOW_LOBE_RADIUS = 0.18 * CELL
BUSH_CANOPY_SHADOW_OFFSET = 0.03 * CELL

# Volume marks for bushes: fewer + smaller than tree marks.
BUSH_VOLUME_MARK_COUNT = 2
BUSH_VOLUME_MARK_AREA_RADIUS = 0.14 * CELL
BUSH_VOLUME_MARK_RADIUS_MIN = 0.04 * CELL
BUSH_VOLUME_MARK_RADIUS_MAX = 0.07 * CELL
BUSH_VOLUME_MARK_SWEEP_MIN = 0.6
BUSH_VOLUME_MARK_SWEEP_MAX = 1.5
BUSH_VOLUME_STROKE_WIDTH = 0.6
BUSH_VOLUME_STROKE_ALPHA = 0.55
BUSH_VOLUME_DASH = "1.5 1.5"

# Compatibility floor: max possible extent of any bush point
# from its tile centre (cluster + lobe + jitter slack). Used by
# the tile-clearance test as the strict upper bound.
BUSH_CANOPY_MAX_EXTENT = (
    BUSH_CANOPY_CLUSTER_RADIUS
    + BUSH_CANOPY_LOBE_RADIUS
    * (1.0 + BUSH_CANOPY_LOBE_RADIUS_JITTER)
)
"""Cluster offset + maximum jittered lobe radius. Must stay
strictly below 0.5 * CELL so a bush placed 4-adjacent to a
building footprint never bleeds onto the roof (M3 contract)."""

BUSH_HUE_JITTER_DEG = 6.0
BUSH_SAT_JITTER = 0.05
BUSH_LIGHT_JITTER = 0.04

# Distinct salts so bush hue jitter doesn't mirror tree jitter
# at the same tile.
_BUSH_HUE_SALT = 7019
_BUSH_SAT_SALT = 8053
_BUSH_LIGHT_SALT = 9091
_BUSH_CANOPY_SHAPE_SALT = 11117
_BUSH_SHADOW_SHAPE_SALT = 11201
_BUSH_VOLUME_SALT = 12119


def _bush_fill_jitter(tx: int, ty: int) -> str:
    dh = _hash_norm(tx, ty, _BUSH_HUE_SALT) * BUSH_HUE_JITTER_DEG
    ds = _hash_norm(tx, ty, _BUSH_SAT_SALT) * BUSH_SAT_JITTER
    dl = _hash_norm(tx, ty, _BUSH_LIGHT_SALT) * BUSH_LIGHT_JITTER
    return _shift_color(
        BUSH_CANOPY_FILL, hue_deg=dh, sat=ds, light=dl,
    )


def _bush_canopy_lobes(
    cx: float, cy: float, tx: int, ty: int,
) -> list[tuple[float, float, float]]:
    return _lobe_circles(
        cx, cy,
        tx=tx, ty=ty, salt=_BUSH_CANOPY_SHAPE_SALT,
        n_lobes=BUSH_CANOPY_LOBE_COUNT,
        lobe_radius=BUSH_CANOPY_LOBE_RADIUS,
        cluster_radius=BUSH_CANOPY_CLUSTER_RADIUS,
        radius_jitter=BUSH_CANOPY_LOBE_RADIUS_JITTER,
        offset_jitter=BUSH_CANOPY_LOBE_OFFSET_JITTER,
        angle_jitter=BUSH_CANOPY_LOBE_ANGLE_JITTER,
    )


def _bush_shadow_lobes(
    cx: float, cy: float, tx: int, ty: int,
) -> list[tuple[float, float, float]]:
    return _lobe_circles(
        cx + BUSH_CANOPY_SHADOW_OFFSET,
        cy + BUSH_CANOPY_SHADOW_OFFSET,
        tx=tx, ty=ty, salt=_BUSH_SHADOW_SHAPE_SALT,
        n_lobes=BUSH_CANOPY_LOBE_COUNT,
        lobe_radius=BUSH_CANOPY_SHADOW_LOBE_RADIUS,
        cluster_radius=BUSH_CANOPY_CLUSTER_RADIUS,
        radius_jitter=BUSH_CANOPY_LOBE_RADIUS_JITTER,
        offset_jitter=BUSH_CANOPY_LOBE_OFFSET_JITTER,
        angle_jitter=BUSH_CANOPY_LOBE_ANGLE_JITTER,
    )


def _bush_canopy_path(cx: float, cy: float, tx: int, ty: int) -> str:
    return _union_path_from_lobes(
        _bush_canopy_lobes(cx, cy, tx, ty),
    )


def _bush_shadow_path(cx: float, cy: float, tx: int, ty: int) -> str:
    return _union_path_from_lobes(
        _bush_shadow_lobes(cx, cy, tx, ty),
    )


def _bush_volume_fragments(
    cx: float, cy: float, tx: int, ty: int, stroke_color: str,
) -> list[str]:
    paths = _scatter_volume_marks(
        cx=cx, cy=cy,
        tx=tx, ty=ty, salt=_BUSH_VOLUME_SALT,
        n_marks=BUSH_VOLUME_MARK_COUNT,
        area_radius=BUSH_VOLUME_MARK_AREA_RADIUS,
        mark_radius_min=BUSH_VOLUME_MARK_RADIUS_MIN,
        mark_radius_max=BUSH_VOLUME_MARK_RADIUS_MAX,
        sweep_min=BUSH_VOLUME_MARK_SWEEP_MIN,
        sweep_max=BUSH_VOLUME_MARK_SWEEP_MAX,
    )
    return [
        (
            f'<path class="bush-volume" d="{d}" '
            f'fill="none" stroke="{stroke_color}" '
            f'stroke-width="{BUSH_VOLUME_STROKE_WIDTH:.2f}" '
            f'stroke-opacity="{BUSH_VOLUME_STROKE_ALPHA:.2f}" '
            f'stroke-dasharray="{BUSH_VOLUME_DASH}" '
            f'stroke-linecap="round"/>'
        )
        for d in paths
    ]


def _bush_fragment_for_tile(tx: int, ty: int) -> str:
    """SVG ``<g>`` fragment for a single bush at tile ``(tx, ty)``.

    Composition (back to front):

    * Multi-lobed shadow silhouette (smaller / fewer lobes than
      a tree, offset down-right) for visual weight.
    * Multi-lobed canopy silhouette (3 small overlapping lobes).
    * Volume marks: short irregular arcs scattered inside in the
      silhouette stroke colour.
    * Low-alpha silhouette stroke tracing the canopy outline.

    No trunk -- bushes are small enough that the silhouette
    alone reads as a shrub."""
    cx = (tx + 0.5) * CELL
    cy = (ty + 0.5) * CELL
    canopy_d = _bush_canopy_path(cx, cy, tx, ty)
    shadow_d = _bush_shadow_path(cx, cy, tx, ty)
    canopy_fill = _bush_fill_jitter(tx, ty)
    parts = [
        f'<g id="bush-{tx}-{ty}" class="bush-feature">',
        (
            f'<path class="bush-canopy-shadow" d="{shadow_d}" '
            f'fill="{BUSH_CANOPY_SHADOW_FILL}" stroke="none"/>'
        ),
        (
            f'<path class="bush-canopy" d="{canopy_d}" '
            f'fill="{canopy_fill}" stroke="none"/>'
        ),
    ]
    parts.extend(_bush_volume_fragments(
        cx, cy, tx, ty, BUSH_CANOPY_STROKE,
    ))
    parts.extend([
        (
            f'<path class="bush-silhouette" d="{canopy_d}" '
            f'fill="none" stroke="{BUSH_CANOPY_STROKE}" '
            f'stroke-width="{BUSH_CANOPY_STROKE_WIDTH:.2f}" '
            f'stroke-opacity="{BUSH_CANOPY_STROKE_ALPHA:.2f}"/>'
        ),
        '</g>',
    ])
    return "".join(parts)


_BUSH_DISPATCH = {
    "bush": _bush_fragment_for_tile,
}


# ── Phase 5: TileDecorator wrappers ───────────────────────────
#
# Each surface feature renders identically regardless of floor
# kind, so the orchestrator drives them through the unified
# :func:`walk_and_paint` helper. The dispatch tables above stay
# as the single source of truth for the per-feature geometry.

from nhc.rendering._decorators import TileDecorator  # noqa: E402


def _feature_predicate(feature: str):
    def pred(level, x, y) -> bool:
        return level.tiles[y][x].feature == feature
    return pred


def _feature_paint(fragment_fn):
    def paint(args):
        return [fragment_fn(args.x, args.y)]
    return paint


WELL_FEATURE = TileDecorator(
    name="well_feature",
    layer="surface_features",
    predicate=_feature_predicate("well"),
    paint=_feature_paint(_well_fragment_for_tile),
    z_order=10,
)
WELL_SQUARE_FEATURE = TileDecorator(
    name="well_square_feature",
    layer="surface_features",
    predicate=_feature_predicate("well_square"),
    paint=_feature_paint(_square_well_fragment_for_tile),
    z_order=11,
)
FOUNTAIN_FEATURE = TileDecorator(
    name="fountain_feature",
    layer="surface_features",
    predicate=_feature_predicate("fountain"),
    paint=_feature_paint(_circle_fountain_fragment_for_tile),
    z_order=20,
)
FOUNTAIN_SQUARE_FEATURE = TileDecorator(
    name="fountain_square_feature",
    layer="surface_features",
    predicate=_feature_predicate("fountain_square"),
    paint=_feature_paint(_square_fountain_fragment_for_tile),
    z_order=21,
)
def _tree_paint_decorator(args):
    fragment = _tree_paint_for_tile(args.ctx.level, args.x, args.y)
    if fragment is None:
        return []
    return [fragment]


TREE_FEATURE = TileDecorator(
    name="tree_feature",
    layer="surface_features",
    predicate=_feature_predicate("tree"),
    paint=_tree_paint_decorator,
    z_order=30,
)
BUSH_FEATURE = TileDecorator(
    name="bush_feature",
    layer="surface_features",
    predicate=_feature_predicate("bush"),
    paint=_feature_paint(_bush_fragment_for_tile),
    z_order=31,
)


def render_fountain_features(level: Level) -> list[str]:
    """SVG fragments for every fountain tile on ``level``.

    Dispatches on ``Tile.feature`` -- ``"fountain"`` paints the
    circular variant (24 keystone stones, central pedestal +
    spout); ``"fountain_square"`` paints the square variant
    (24 perimeter stones, square pool, square pedestal). Both
    occupy a 2x2 tile footprint anchored at the tagged tile.
    """
    out: list[str] = []
    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            fn = _FOUNTAIN_DISPATCH.get(tile.feature)
            if fn is not None:
                out.append(fn(x, y))
    return out


def render_well_features(level: Level) -> list[str]:
    """SVG fragments for every well tile on ``level``.

    Dispatches on ``Tile.feature`` -- ``"well"`` paints the
    Dyson-style circular ring (16 keystone stones); ``"well_square"``
    paints the masonry-square variant (16 perimeter stones, square
    water pool). Both variants share the same outer footprint so
    they fit the same tile-centred placement contract.
    """
    out: list[str] = []
    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            fn = _WELL_DISPATCH.get(tile.feature)
            if fn is not None:
                out.append(fn(x, y))
    return out


def render_bush_features(level: Level) -> list[str]:
    """SVG fragments for every bush tile on ``level``.

    Mirrors :func:`render_tree_features` but with no grove
    merging -- bushes stay per-tile so neighbour-bias clusters
    read as a row of distinct shrubs rather than one fused mass.
    """
    out: list[str] = []
    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            fn = _BUSH_DISPATCH.get(tile.feature)
            if fn is not None:
                out.append(fn(x, y))
    return out


def render_tree_features(level: Level) -> list[str]:
    """SVG fragments for every tree on ``level``.

    Routes through :func:`_tree_paint_for_tile` so groves of 3+
    4-adjacent trees collapse into a single Shapely-unioned
    silhouette anchored at the lowest ``(tx, ty)``; smaller
    groves keep the per-tile shadow / canopy / highlight stack.
    """
    out: list[str] = []
    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            if tile.feature != "tree":
                continue
            fragment = _tree_paint_for_tile(level, x, y)
            if fragment is not None:
                out.append(fragment)
    return out
