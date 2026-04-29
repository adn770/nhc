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
