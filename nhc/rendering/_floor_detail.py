"""Floor-detail predicates + remaining composite renderers.

Phase 7 retired the legacy procedural inner-detail helpers
(_floor_stone / _tile_detail / _emit_detail / _tile_thematic_detail
/ _emit_thematic_detail / _web_detail / _bone_detail /
_skull_detail / _render_floor_detail). The IR emitter at
nhc.rendering._floor_layers._emit_floor_detail_ir and
_emit_thematic_detail_ir owns the per-layer dispatch via
FloorDetailOp / ThematicDetailOp; the Rust port handles the per-
tile geometry. This module keeps the surface-tile predicates
(_is_*_tile / _track_horizontal_at) consumed by the IR emitter,
plus _render_floor_grid and the wood-floor short-circuit
(_render_wood_floor) wired through walk_and_paint.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.rendering._svg_helpers import (
    CELL,
    GRID_WIDTH,
    INK,
    _is_door,
    _wobbly_grid_seg,
)


# ── Helpers ───────────────────────────────────────────────────

def _dungeon_interior_clip(svg: list[str], dungeon_poly, clip_id: str):
    """Emit an SVG clipPath for the dungeon interior polygon.

    Includes interior holes (cave islands) so that grid lines
    and floor details are clipped away inside them, letting the
    hatching layer show through.
    """
    if dungeon_poly is None or dungeon_poly.is_empty:
        return
    geoms = (dungeon_poly.geoms
             if hasattr(dungeon_poly, 'geoms')
             else [dungeon_poly])
    clip_d = ""
    for geom in geoms:
        coords = list(geom.exterior.coords)
        clip_d += f'M{coords[0][0]:.0f},{coords[0][1]:.0f} '
        clip_d += ' '.join(
            f'L{x:.0f},{y:.0f}' for x, y in coords[1:])
        clip_d += ' Z '
        # Add interior holes so the clip excludes them
        for hole in geom.interiors:
            h = list(hole.coords)
            clip_d += f'M{h[0][0]:.0f},{h[0][1]:.0f} '
            clip_d += ' '.join(
                f'L{x:.0f},{y:.0f}' for x, y in h[1:])
            clip_d += ' Z '
    svg.append(
        f'<defs><clipPath id="{clip_id}">'
        f'<path d="{clip_d}" fill-rule="evenodd"/>'
        f'</clipPath></defs>')


# ── Composite renderers ──────────────────────────────────────
#
# The procedural inner-detail helpers (_floor_stone, _tile_detail,
# _emit_detail, _tile_thematic_detail, _emit_thematic_detail,
# _web_detail, _bone_detail, _skull_detail) were ported to Rust
# in §8 steps 3-4. The IR emitter at
# nhc.rendering._floor_layers._emit_floor_detail_ir and
# _emit_thematic_detail_ir routes to the Rust handlers via
# FloorDetailOp / ThematicDetailOp; the Python pipeline no longer
# emits these fragments directly.

def _render_floor_grid(
    svg: list[str], level: "Level", dungeon_poly=None,
) -> None:
    """Draw a hand-drawn style grid.

    Room tiles: generated for all tiles, clipped to dungeon polygon.
    Corridor/door tiles: generated directly, no clipping needed.
    """
    rng = random.Random(41)
    room_segments: list[str] = []
    corridor_segments: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            # Skip VOID tiles: they're truly empty space, never
            # rendered on surface levels (no dungeon_poly to clip
            # against) and on dungeon levels their grid edges
            # would be clipped out anyway.
            if tile.terrain == Terrain.VOID:
                continue
            # Secret doors sit on the wall line between rooms
            # and fall outside the room shapely polygons used
            # by grid-clip. Route their grid edges through the
            # unclipped bucket alongside visible doors, so the
            # segment stroke doesn't land on the clip boundary
            # and get half-masked to invisibility.
            is_cor = (tile.surface_type == SurfaceType.CORRIDOR
                      or _is_door(level, x, y)
                      or tile.feature == "door_secret")
            px, py = x * CELL, y * CELL

            # Right edge
            if x + 1 < level.width:
                seg = _wobbly_grid_seg(
                    rng, px + CELL, py, px + CELL, py + CELL,
                    x * 0.7, y * 0.7, base=20,
                )
                if is_cor:
                    corridor_segments.append(seg)
                else:
                    room_segments.append(seg)

            # Bottom edge
            if y + 1 < level.height:
                seg = _wobbly_grid_seg(
                    rng, px, py + CELL, px + CELL, py + CELL,
                    x * 0.3, y * 0.7, base=24,
                )
                if is_cor:
                    corridor_segments.append(seg)
                else:
                    room_segments.append(seg)

    _GRID_STYLE = (
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{GRID_WIDTH}" '
        f'opacity="0.7" stroke-linecap="round"'
    )

    # Room grid — clipped to dungeon polygon
    if room_segments:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(svg, dungeon_poly, "grid-clip")
            svg.append(
                f'<path d="{" ".join(room_segments)}" '
                f'{_GRID_STYLE} clip-path="url(#grid-clip)"/>'
            )
        else:
            svg.append(
                f'<path d="{" ".join(room_segments)}" '
                f'{_GRID_STYLE}/>'
            )

    # Corridor grid — no clipping
    if corridor_segments:
        svg.append(
            f'<path d="{" ".join(corridor_segments)}" '
            f'{_GRID_STYLE}/>'
        )


# ── Cobblestone (STREET + PAVED) ─────────────────────────────

_COBBLESTONE_SURFACES = (SurfaceType.STREET, SurfaceType.PAVED)


def _is_cobble_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].surface_type in _COBBLESTONE_SURFACES


# ── Cobblestone variants ─────────────────────────────────────


def _is_brick_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].surface_type is SurfaceType.BRICK


def _is_flagstone_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].surface_type is SurfaceType.FLAGSTONE


def _is_opus_romano_tile(
    level: "Level", x: int, y: int,
) -> bool:
    return (
        level.tiles[y][x].surface_type
        is SurfaceType.OPUS_ROMANO
    )


# ── Field and garden surfaces (tunable constants) ─────────────

# FIELD_TINT is retained for sample-generator info panels and the
# legacy "green family" sanity test. The Phase 3b grass-overlay
# pipeline no longer uses it as a fill -- the theme grass tint
# from ``terrain_palette.get_palette(theme).grass.tint`` paints
# the base; this constant is the historical hardcoded green.
FIELD_TINT = "#6B8A56"
FIELD_STONE_FILL = "#8A9A6A"
FIELD_STONE_STROKE = "#4A5A3A"


def _is_field_overlay_tile(level: "Level", x: int, y: int) -> bool:
    """Predicate for the field-stone decorator IR op.

    Phase 3b moved field tiles to ``Terrain.GRASS`` so the theme
    grass tint + blade strokes paint the base look; the decorator
    only adds the scattered-stone overlay.
    """
    tile = level.tiles[y][x]
    return (
        tile.terrain is Terrain.GRASS
        and tile.surface_type is SurfaceType.FIELD
    )


# ── Wood interior floors (tunable constants) ──────────────────

# Neutral building-wide base. Painted by the WoodFloor FloorOp on
# the entire building polygon so chamfered-corner triangles and
# inter-room passages keep a coherent base colour. Per-room
# overlays (see ``_WOOD_SPECIES`` below) paint the room's tone
# variant on top inside ``_draw_wood_floor_from_ir``.
WOOD_FLOOR_FILL = "#B58B5A"
WOOD_SEAM_STROKE = "#8A5A2A"
WOOD_SEAM_WIDTH = 0.8
# Laminated-parquet plank geometry: 1/4 tile cross-axis, random
# along-axis length in [1.5, 2.5] tiles per plank. With per-plank
# randomness the running-bond offset mechanism is unnecessary --
# adjacent strips naturally stagger because each uses its own
# random length sequence.
WOOD_PLANK_WIDTH_PX = CELL / 4
WOOD_PLANK_LENGTH_MIN = CELL * 0.5
WOOD_PLANK_LENGTH_MAX = CELL * 2.5
# Subtle grain overlay: two thin streaks per strip, one lighter
# and one darker than the base fill, at low opacity so the base
# colour still dominates.
WOOD_GRAIN_LIGHT = "#C4A076"
WOOD_GRAIN_DARK = "#8F6540"
WOOD_GRAIN_STROKE_WIDTH = 0.4
WOOD_GRAIN_OPACITY = 0.35
WOOD_GRAIN_LINES_PER_STRIP = 2

# Wood-species palette — five species, each with three tone
# variants (light / medium / dark). The medium tone is the
# "canonical" species colour; light and dark are ±1 step
# variants that read as "same wood, different cut / patina"
# rather than a different species. A building picks ONE species
# from ``FloorDetailOp.seed`` and each room inside picks one of
# the species' three tones from ``hash(room.regionRef) % 3``,
# so a manor reads as a coherent material with per-room nuance
# instead of a wood-sample catalog. Each tone carries the full
# render quartet:
#
#   (fill, grain_light, grain_dark, seam)
#
# - ``fill`` paints the per-room rect overlay.
# - ``grain_light`` / ``grain_dark`` paint the parquet grain
#   streaks (two per plank strip, alternating).
# - ``seam`` paints the plank-edge stroke.
#
# Order of species: oak (warm tan), walnut (cocoa), cherry
# (red-brown), pine (pale honey), weathered (silvered grey).
_WOOD_SPECIES: tuple[tuple[tuple[str, str, str, str], ...], ...] = (
    # Oak — warm tan, the "default" species closest to the legacy
    # WOOD_FLOOR_FILL palette. Light / medium / dark.
    (
        ("#C4A076", "#D4B690", "#A88058", "#8A5A2A"),  # light
        ("#B58B5A", "#C4A076", "#8F6540", "#8A5A2A"),  # medium (legacy)
        ("#9B7548", "#AC8A60", "#7A5530", "#683E1E"),  # dark
    ),
    # Walnut — deep cocoa, redder hue.
    (
        ("#8C6440", "#A07A55", "#684A2C", "#553820"),  # light
        ("#6E4F32", "#8B6446", "#523820", "#3F2818"),  # medium
        ("#553820", "#6E4F32", "#3F2818", "#2A1A10"),  # dark
    ),
    # Cherry — reddish brown, slight orange.
    (
        ("#B07A55", "#C49075", "#8E5C3A", "#683C20"),  # light
        ("#9B6442", "#B07A55", "#7A4D2E", "#553820"),  # medium
        ("#7E4F32", "#955F44", "#5F3820", "#42261A"),  # dark
    ),
    # Pine — pale honey, the lightest species.
    (
        ("#D8B888", "#E6CDA8", "#B8966C", "#9A7A50"),  # light
        ("#C4A176", "#D8B888", "#A48458", "#856A40"),  # medium
        ("#A88556", "#BFA070", "#88683C", "#6A5028"),  # dark
    ),
    # Weathered grey — silvered teak / driftwood.
    (
        ("#8A8478", "#A09A8E", "#6E695F", "#544F46"),  # light
        ("#6E695F", "#8A8478", "#544F46", "#3D3932"),  # medium
        ("#544F46", "#6E695F", "#3D3932", "#2A2723"),  # dark
    ),
)


def _fnv1a_32(text: str) -> int:
    """Implementation-stable FNV-1a 32-bit hash of ``text`` UTF-8.

    The standard library's ``hash()`` is randomised per process so
    every consumer that needs a deterministic per-room pick has to
    use a stable hash. Mirrored byte-for-byte by Rust's
    ``primitives::wood_floor::fnv1a_32``.
    """
    h = 2166136261
    for ch in text.encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _wood_palette_for_room(
    building_seed: int,
    region_ref: str | bytes | None,
) -> tuple[str, str, str, str]:
    """Pick (fill, grain_light, grain_dark, seam) for a wood room.

    Building species derives from ``building_seed`` (the
    FloorDetailOp.seed field — same per IR build, varies per
    building); room tone derives from a stable hash of the
    room's ``regionRef``. Without a ``regionRef`` the room falls
    back to the building's medium tone — the legacy single-colour
    look.
    """
    species_idx = building_seed % len(_WOOD_SPECIES)
    species = _WOOD_SPECIES[species_idx]
    if region_ref is None:
        return species[1]  # medium
    if isinstance(region_ref, bytes):
        ref = region_ref.decode() if region_ref else ""
    else:
        ref = region_ref or ""
    if not ref:
        return species[1]
    # Distribution across 3 buckets is plenty for 1-6 rooms per
    # building. Use the stable FNV-1a hash so Python and Rust
    # agree on the tone pick.
    return species[_fnv1a_32(ref) % 3]


# Wood-floor patterns. Each room picks one from ``regionRef`` —
# most rooms ship with the standard plank layout; ~1 in 3 picks
# basket-weave, the "fancy floor" variant where 1-tile cells
# alternate horizontal and vertical plank orientation in a
# checkerboard. Pattern choice is independent of palette (different
# hash salts) so basket-weave rooms read as a deliberate visual
# accent rather than coincidentally matching tone variation.
WOOD_PATTERN_PLANK = "plank"
WOOD_PATTERN_BASKET = "basket"


def _wood_pattern_for_room(region_ref: str | bytes | None) -> str:
    """Pick the wood layout pattern for a room.

    Hash mod 3 → ~1/3 of rooms get ``basket``, rest get
    ``plank``. Empty / unknown ``regionRef`` falls back to plank
    so external callers without a region see the legacy look.
    """
    if region_ref is None:
        return WOOD_PATTERN_PLANK
    if isinstance(region_ref, bytes):
        ref = region_ref.decode() if region_ref else ""
    else:
        ref = region_ref or ""
    if not ref:
        return WOOD_PATTERN_PLANK
    # Salt the hash with a constant so the pattern bucket is
    # statistically independent from the tone bucket (a room can
    # pick "dark walnut + basket-weave" or "dark walnut + plank"
    # with equal probability).
    h = _fnv1a_32("pattern:" + ref)
    return WOOD_PATTERN_BASKET if (h % 3) == 0 else WOOD_PATTERN_PLANK


# ── Mine cart tracks ─────────────────────────────────────────


def _is_track_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].surface_type is SurfaceType.TRACK


def _track_horizontal_at(level: "Level", x: int, y: int) -> bool:
    """Pick rail orientation for a TRACK tile from its neighbours."""
    e = level.tile_at(x + 1, y)
    w = level.tile_at(x - 1, y)
    return (
        (e is not None and e.surface_type is SurfaceType.TRACK)
        or (w is not None and w.surface_type is SurfaceType.TRACK)
    )


# ── Ore deposits ─────────────────────────────────────────────


def _is_ore_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].feature == "ore_deposit"
