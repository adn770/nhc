"""Floor detail rendering — cracks, stones, scratches, webs, bones, skulls.

Extracted from svg.py to reduce module size.  All public names are
re-exported by svg.py so existing imports keep working.
"""

from __future__ import annotations

import math
import random
import sys

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.rendering._decorators import TileDecorator
from nhc.rendering._svg_helpers import (
    CELL,
    FLOOR_STONE_FILL,
    FLOOR_STONE_STROKE,
    GRID_WIDTH,
    INK,
    _is_door,
    _is_floor,
    _wobbly_grid_seg,
    _y_scratch,
)


# ── Constants ─────────────────────────────────────────────────

_DETAIL_SCALE: dict[str, float] = {
    "dungeon": 1.0,
    "crypt":   2.0,
    "cave":    2.0,
    "sewer":   1.0,
    "castle":  0.8,
    "forest":  0.6,
    "abyss":   1.5,
}

# Per-theme probabilities for thematic detail types.
# Each value is the probability of that detail appearing per tile.
_THEMATIC_DETAIL_PROBS: dict[str, dict[str, float]] = {
    "dungeon": {"web": 0.03, "bones": 0.02, "skull": 0.01},
    "crypt":   {"web": 0.08, "bones": 0.10, "skull": 0.06},
    "cave":    {"web": 0.12, "bones": 0.04, "skull": 0.02},
    "sewer":   {"web": 0.06, "bones": 0.03, "skull": 0.01},
    "castle":  {"web": 0.02, "bones": 0.01, "skull": 0.005},
    "forest":  {"web": 0.04, "bones": 0.01, "skull": 0.005},
    "abyss":   {"web": 0.05, "bones": 0.08, "skull": 0.10},
}
_THEMATIC_DEFAULT: dict[str, float] = {
    "web": 0.03, "bones": 0.02, "skull": 0.01,
}

_TERRAIN_TYPES = {Terrain.WATER, Terrain.GRASS, Terrain.LAVA, Terrain.CHASM}


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


# ── Floor stone ───────────────────────────────────────────────

def _floor_stone(
    rng: random.Random, px: float, py: float,
    scale: float = 1.0,
) -> str:
    """Single floor stone ellipse — brown fill, scaled by *scale*."""
    sx = px + rng.uniform(CELL * 0.25, CELL * 0.75)
    sy = py + rng.uniform(CELL * 0.25, CELL * 0.75)
    rx = rng.uniform(2, CELL * 0.15) * scale
    ry = rng.uniform(2, CELL * 0.12) * scale
    angle = rng.uniform(0, 180)
    sw = rng.uniform(1.2, 2.0)
    return (
        f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
        f'rx="{rx:.1f}" ry="{ry:.1f}" '
        f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
        f'fill="{FLOOR_STONE_FILL}" '
        f'stroke="{FLOOR_STONE_STROKE}" '
        f'stroke-width="{sw:.1f}"/>')


# ── Tile detail ───────────────────────────────────────────────

def _tile_detail(
    rng: random.Random, x: int, y: int, seed: int,
    cracks: list[str], stones: list[str], scratches: list[str],
    detail_scale: float = 1.0,
    theme: str = "dungeon",
) -> None:
    """Generate floor detail (cracks, stones, scratches) for one tile."""
    px, py = x * CELL, y * CELL
    is_cave = theme == "cave"

    # Caves: more cracks, fewer scratches, bigger stones
    crack_prob = 0.32 if is_cave else 0.08
    scratch_prob = 0.01 if is_cave else 0.05
    stone_prob = 0.10 if is_cave else 0.06
    cluster_prob = 0.06 if is_cave else 0.03
    stone_scale = 1.8 if is_cave else 1.0

    roll = rng.random()
    if roll < crack_prob * detail_scale:
        # Crack line from a tile corner into the tile interior.
        # The tile grid edges complete the triangle visually.
        corner = rng.randint(0, 3)
        s1 = rng.uniform(CELL * 0.15, CELL * 0.4)
        s2 = rng.uniform(CELL * 0.15, CELL * 0.4)
        if corner == 0:      # top-left
            cracks.append(f'{px + s1},{py} {px},{py + s2}')
        elif corner == 1:    # top-right
            cracks.append(
                f'{px + CELL - s1},{py} {px + CELL},{py + s2}')
        elif corner == 2:    # bottom-left
            cracks.append(
                f'{px + s1},{py + CELL} {px},{py + CELL - s2}')
        else:                # bottom-right
            cracks.append(
                f'{px + CELL - s1},{py + CELL} '
                f'{px + CELL},{py + CELL - s2}')
    elif roll < crack_prob * detail_scale + scratch_prob * detail_scale:
        scratches.append(_y_scratch(rng, px, py, x, y, seed))

    if rng.random() < stone_prob * detail_scale:
        stones.append(_floor_stone(rng, px, py, scale=stone_scale))

    if rng.random() < cluster_prob * detail_scale:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        for _ in range(3):
            sx = cx + rng.uniform(-CELL * 0.2, CELL * 0.2)
            sy = cy + rng.uniform(-CELL * 0.2, CELL * 0.2)
            scale = rng.uniform(0.5, 1.3) * stone_scale
            rx = rng.uniform(2, CELL * 0.15) * scale
            ry = rng.uniform(2, CELL * 0.12) * scale
            angle = rng.uniform(0, 180)
            sw = rng.uniform(1.2, 2.0)
            stones.append(
                f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                f'rx="{rx:.1f}" ry="{ry:.1f}" '
                f'transform="rotate({angle:.0f},'
                f'{sx:.1f},{sy:.1f})" '
                f'fill="{FLOOR_STONE_FILL}" '
                f'stroke="{FLOOR_STONE_STROKE}" '
                f'stroke-width="{sw:.1f}"/>')


def _emit_detail(
    svg: list[str],
    cracks: list[str], stones: list[str], scratches: list[str],
) -> None:
    """Append accumulated floor detail elements to the SVG."""
    if cracks:
        lines = "".join(
            f'<line x1="{c.split()[0].split(",")[0]}" '
            f'y1="{c.split()[0].split(",")[1]}" '
            f'x2="{c.split()[1].split(",")[0]}" '
            f'y2="{c.split()[1].split(",")[1]}" '
            f'stroke="{INK}" stroke-width="0.5" '
            f'stroke-linecap="round"/>'
            for c in cracks
        )
        svg.append(f'<g opacity="0.5">{lines}</g>')
    if scratches:
        svg.append(
            f'<g class="y-scratch" opacity="0.45">'
            f'{"".join(scratches)}</g>')
    if stones:
        svg.append(f'<g opacity="0.8">{"".join(stones)}</g>')


# ── Thematic detail ───────────────────────────────────────────

def _tile_thematic_detail(
    rng: random.Random, x: int, y: int,
    level: "Level",
    probs: dict[str, float],
    webs: list[str], bones: list[str], skulls: list[str],
) -> None:
    """Generate thematic details (webs, bones, skulls) for one tile.

    Webs only appear in corners adjacent to walls.
    Bones and skulls can appear on any floor tile.
    Only processes actual floor tiles (not walls inside room rects).
    """
    tile = level.tiles[y][x]
    if tile.terrain != Terrain.FLOOR:
        return
    px, py = x * CELL, y * CELL

    # Webs — only in corners that touch walls on both sides
    if rng.random() < probs.get("web", 0):
        wall_corners = []
        # Check each corner: needs wall on both adjacent sides
        if not _is_floor(level, x, y - 1) and \
                not _is_floor(level, x - 1, y):
            wall_corners.append(0)  # top-left
        if not _is_floor(level, x, y - 1) and \
                not _is_floor(level, x + 1, y):
            wall_corners.append(1)  # top-right
        if not _is_floor(level, x, y + 1) and \
                not _is_floor(level, x - 1, y):
            wall_corners.append(2)  # bottom-left
        if not _is_floor(level, x, y + 1) and \
                not _is_floor(level, x + 1, y):
            wall_corners.append(3)  # bottom-right
        if wall_corners:
            corner = rng.choice(wall_corners)
            webs.append(_web_detail(rng, px, py, corner))

    # Bone piles
    if rng.random() < probs.get("bones", 0):
        bones.append(_bone_detail(rng, px, py))

    # Skulls
    if rng.random() < probs.get("skull", 0):
        skulls.append(_skull_detail(rng, px, py))


def _emit_thematic_detail(
    svg: list[str],
    webs: list[str], bones: list[str], skulls: list[str],
) -> None:
    """Append thematic detail elements to the SVG."""
    if webs:
        svg.append(
            f'<g class="detail-webs">{"".join(webs)}</g>')
    if bones:
        svg.append(
            f'<g class="detail-bones">{"".join(bones)}</g>')
    if skulls:
        svg.append(
            f'<g class="detail-skulls">{"".join(skulls)}</g>')


# ── Thematic detail generators ────────────────────────────────


def _web_detail(
    rng: random.Random, px: float, py: float,
    corner: int,
) -> str:
    """Spider web radiating from a tile corner.

    Draws 3-4 radial threads from the corner into the tile,
    connected by 2 concentric arc-like cross-threads.
    *corner*: 0=TL, 1=TR, 2=BL, 3=BR.
    """
    # Corner anchor point
    cx = px if corner in (0, 2) else px + CELL
    cy = py if corner in (0, 1) else py + CELL
    # Direction signs (into the tile)
    sx = 1 if corner in (0, 2) else -1
    sy = 1 if corner in (0, 1) else -1

    n_radials = rng.randint(3, 4)
    radial_len = rng.uniform(CELL * 0.5, CELL * 0.85)
    angles = sorted(
        rng.uniform(0, math.pi / 2) for _ in range(n_radials)
    )
    parts: list[str] = []

    # Radial endpoints at full length
    endpoints: list[list[tuple[float, float]]] = []
    for a in angles:
        dx = sx * math.cos(a) * radial_len
        dy = sy * math.sin(a) * radial_len
        ex, ey = cx + dx, cy + dy
        parts.append(
            f'M{cx:.1f},{cy:.1f} L{ex:.1f},{ey:.1f}'
        )
        # Store intermediate points for cross-threads
        ring_pts: list[tuple[float, float]] = []
        for frac in (0.4, 0.7):
            ring_pts.append((cx + dx * frac, cy + dy * frac))
        endpoints.append(ring_pts)

    # Cross-threads connecting radials at each ring
    for ring_idx in range(2):
        for i in range(len(endpoints) - 1):
            p1 = endpoints[i][ring_idx]
            p2 = endpoints[i + 1][ring_idx]
            # Slight sag for organic feel
            mx = (p1[0] + p2[0]) / 2 + rng.uniform(-1.5, 1.5)
            my = (p1[1] + p2[1]) / 2 + rng.uniform(-1.5, 1.5)
            parts.append(
                f'M{p1[0]:.1f},{p1[1]:.1f} '
                f'Q{mx:.1f},{my:.1f} '
                f'{p2[0]:.1f},{p2[1]:.1f}'
            )

    sw = rng.uniform(0.3, 0.6)
    return (
        f'<path d="{" ".join(parts)}" fill="none" '
        f'stroke="{INK}" stroke-width="{sw:.1f}" '
        f'stroke-linecap="round" opacity="0.35"/>'
    )


def _bone_detail(rng: random.Random, px: float, py: float) -> str:
    """Pile of 2-3 crossed bones with bulbous epiphyses.

    Each bone is a line with small circles at both ends,
    arranged in a small cluster within the tile.
    """
    cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
    cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
    n_bones = rng.randint(2, 3)
    parts: list[str] = []

    for _ in range(n_bones):
        angle = rng.uniform(0, math.pi)
        length = rng.uniform(CELL * 0.2, CELL * 0.35)
        dx = math.cos(angle) * length / 2
        dy = math.sin(angle) * length / 2
        bx = cx + rng.uniform(-CELL * 0.08, CELL * 0.08)
        by = cy + rng.uniform(-CELL * 0.08, CELL * 0.08)
        x1, y1 = bx - dx, by - dy
        x2, y2 = bx + dx, by + dy
        # Bone shaft
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{INK}" stroke-width="1.2" '
            f'stroke-linecap="round"/>'
        )
        # Epiphyses (bulbous ends)
        er = rng.uniform(1.2, 1.8)
        for ex, ey in [(x1, y1), (x2, y2)]:
            parts.append(
                f'<ellipse cx="{ex:.1f}" cy="{ey:.1f}" '
                f'rx="{er:.1f}" ry="{er:.1f}" fill="{INK}"/>'
            )

    return f'<g opacity="0.4">{"".join(parts)}</g>'


def _skull_detail(rng: random.Random, px: float, py: float) -> str:
    """Small hand-drawn skull with separate cranium and mandible.

    Anatomy (top to bottom, all in local coords centered at 0,0):
    - Cranium: dome path curving from zygomatic arch, over the top,
      back down to the other arch.  Narrower at the bottom than a
      full ellipse so it reads as a skull, not a mask.
    - Eye sockets: two filled ellipses.
    - Nasal cavity: small inverted triangle.
    - Tooth line: short horizontal dashes between upper and lower jaw.
    - Mandible: separate U-shaped jawbone with ascending rami
      connecting near the zygomatic arches and a rounded chin.

    Fits within ~10-12px, positioned randomly inside the tile.
    """
    cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
    cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
    s = rng.uniform(0.8, 1.2)
    rot = rng.uniform(-20, 20)
    sw = 0.7  # stroke width

    # Proportions (half-widths/heights from center)
    cw = 4.5 * s   # cranium half-width at widest (temples)
    ch = 5.0 * s   # cranium half-height (top of dome to maxilla)
    zw = cw * 0.85  # zygomatic arch width (cheekbone, narrower)
    mw = cw * 0.55  # maxilla half-width (bottom of upper skull)

    parts: list[str] = []

    # ── Cranium path ──
    # Start at right zygomatic arch, arc over the dome, down to
    # left zygomatic, then straight across the maxilla base.
    top_y = -ch           # top of dome
    zyg_y = ch * 0.35     # zygomatic arch y (below center)
    max_y = ch * 0.55     # maxilla base y

    parts.append(
        f'<path d="'
        f'M{-zw:.1f},{zyg_y:.1f} '
        f'C{-cw:.1f},{-ch * 0.2:.1f} '    # left temple
        f'{-cw * 0.6:.1f},{top_y:.1f} '    # left-top
        f'0,{top_y:.1f} '                  # top center
        f'C{cw * 0.6:.1f},{top_y:.1f} '    # right-top
        f'{cw:.1f},{-ch * 0.2:.1f} '       # right temple
        f'{zw:.1f},{zyg_y:.1f} '           # right zygomatic
        f'L{mw:.1f},{max_y:.1f} '          # right maxilla
        f'L{-mw:.1f},{max_y:.1f} '         # left maxilla
        f'Z" '
        f'fill="none" stroke="{INK}" stroke-width="{sw}"/>'
    )

    # ── Eye sockets ──
    eye_y = -ch * 0.05
    eye_sep = cw * 0.42
    eye_rx = cw * 0.26
    eye_ry = ch * 0.16
    for ex in (-eye_sep, eye_sep):
        parts.append(
            f'<ellipse cx="{ex:.1f}" cy="{eye_y:.1f}" '
            f'rx="{eye_rx:.1f}" ry="{eye_ry:.1f}" '
            f'fill="{INK}"/>'
        )

    # ── Nasal cavity ──
    nose_y = ch * 0.2
    nose_w = cw * 0.18
    nose_h = ch * 0.2
    parts.append(
        f'<path d="M0,{nose_y:.1f} '
        f'L{-nose_w:.1f},{nose_y + nose_h:.1f} '
        f'L{nose_w:.1f},{nose_y + nose_h:.1f} Z" '
        f'fill="{INK}"/>'
    )

    # ── Tooth line ──
    tooth_y = max_y + s * 0.8
    tooth_w = mw * 0.75
    parts.append(
        f'<line x1="{-tooth_w:.1f}" y1="{tooth_y:.1f}" '
        f'x2="{tooth_w:.1f}" y2="{tooth_y:.1f}" '
        f'stroke="{INK}" stroke-width="0.4" '
        f'stroke-dasharray="1.2,0.8"/>'
    )

    # ── Mandible (jawbone) ──
    # U-shape: ascending rami from zygomatic arches curving down
    # to a rounded chin below the tooth line.
    jaw_top = max_y + s * 0.4   # top of ramus (near zygomatic)
    chin_y = max_y + ch * 0.55  # chin bottom
    ramus_w = mw * 1.05         # ramus outer width
    chin_w = mw * 0.35          # chin half-width at bottom

    parts.append(
        f'<path d="'
        f'M{-ramus_w:.1f},{jaw_top:.1f} '
        f'C{-ramus_w:.1f},{chin_y - s:.1f} '
        f'{-chin_w:.1f},{chin_y:.1f} '
        f'0,{chin_y:.1f} '
        f'C{chin_w:.1f},{chin_y:.1f} '
        f'{ramus_w:.1f},{chin_y - s:.1f} '
        f'{ramus_w:.1f},{jaw_top:.1f}" '
        f'fill="none" stroke="{INK}" stroke-width="{sw}"/>'
    )

    inner = "".join(parts)
    return (
        f'<g transform="translate({cx:.1f},{cy:.1f}) '
        f'rotate({rot:.0f})" opacity="0.45">{inner}</g>'
    )


# ── Composite renderers ──────────────────────────────────────

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


def _render_floor_detail(
    svg: list[str], level: "Level", seed: int,
    dungeon_poly=None,
    building_polygon: list[tuple[float, float]] | None = None,
    ctx=None,
) -> None:
    """Scatter cracks, stones, scratches, and thematic details.

    Room tiles: generated for all tiles, clipped to dungeon polygon.
    Corridor/door tiles: generated directly, no clipping needed.
    Thematic details (webs, bones, skulls) added based on theme.
    Wood Building floors short-circuit to a dedicated plank renderer
    that skips cracks, scratches, and the surface-type passes.

    ``building_polygon`` (when set) extends the wood-floor fill to
    the building's outer outline (octagon chamfer / circle curve)
    instead of the rect-aligned tile boundaries.

    ``ctx`` is the frozen :class:`RenderContext` the orchestrator
    builds once. It centralises the floor-kind / interior-finish /
    macabre-detail decisions previously rederived here. Optional so
    direct callers (older tests) keep working — when ``None`` the
    function falls back to lazily building a context from ``level``.
    """
    if ctx is None:
        from nhc.rendering._render_context import build_render_context
        ctx = build_render_context(level, seed=seed)

    rng = random.Random(seed + 99)
    if ctx.interior_finish == "wood":
        _render_wood_floor(
            svg, level, rng, dungeon_poly,
            building_polygon=building_polygon,
            ctx=ctx,
        )
        return
    theme = ctx.theme
    scale = _DETAIL_SCALE.get(theme, 1.0)
    probs = _THEMATIC_DETAIL_PROBS.get(theme, _THEMATIC_DEFAULT)
    room_cracks: list[str] = []
    room_stones: list[str] = []
    room_scratches: list[str] = []
    cor_cracks: list[str] = []
    cor_stones: list[str] = []
    cor_scratches: list[str] = []
    room_webs: list[str] = []
    room_bones: list[str] = []
    room_skulls: list[str] = []
    cor_webs: list[str] = []
    cor_bones: list[str] = []
    cor_skulls: list[str] = []

    # Look up helpers through the svg module so that
    # unittest.mock.patch('nhc.rendering.svg._tile_detail', ...)
    # takes effect inside this loop.
    _svg = sys.modules['nhc.rendering.svg']
    _td = _svg._tile_detail
    _ttd = _svg._tile_thematic_detail

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            # Only FLOOR tiles get indoor floor detail. WALL /
            # VOID / terrain tiles previously entered the loop and
            # relied on dungeon-polygon clipping at emission time;
            # the town / keep surface levels have no rooms, so
            # dungeon_poly is empty and the clip never fires --
            # that's how spurious cracks / stones leaked out.
            if tile.terrain != Terrain.FLOOR:
                continue
            if tile.feature in ("stairs_up", "stairs_down"):
                continue
            # Outdoor surfaces (STREET / FIELD / GARDEN) have
            # their own per-tile decorators. Skip the indoor pass
            # here so town / keep / farm surfaces don't pick up
            # bones, skulls, floor stones, scratches, or cracks.
            # Interior cobble variants (PAVED / BRICK / FLAGSTONE)
            # intentionally keep the indoor-stone detail so the
            # decorative pattern reads as an overlay on the
            # building's stone floor.
            if tile.surface_type in (
                SurfaceType.STREET,
                SurfaceType.FIELD,
                SurfaceType.GARDEN,
            ):
                continue
            is_cor = (tile.surface_type == SurfaceType.CORRIDOR
                      or _is_door(level, x, y))
            if is_cor:
                _td(rng, x, y, seed,
                    cor_cracks, cor_stones, cor_scratches,
                    detail_scale=scale, theme=theme)
                _ttd(rng, x, y, level, probs,
                     cor_webs, cor_bones, cor_skulls)
            else:
                _td(rng, x, y, seed,
                    room_cracks, room_stones, room_scratches,
                    detail_scale=scale, theme=theme)
                _ttd(rng, x, y, level, probs,
                     room_webs, room_bones,
                     room_skulls)

    # Building floors are inhabited architecture -- no bones,
    # skulls, or scattered floor stones. Webs are kept (a dusty
    # room is plausible). The macabre-detail flag rolls
    # ``floor_kind == "building"`` into the ``RenderContext``, so
    # this stays a one-line gate even after future biome variants.
    if not ctx.macabre_detail:
        room_bones = []
        room_skulls = []
        room_stones = []
        cor_bones = []
        cor_skulls = []
        cor_stones = []

    # Room detail — clipped to dungeon polygon
    has_room = (room_cracks or room_stones or room_scratches
                or room_webs or room_bones or room_skulls)
    if has_room:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(svg, dungeon_poly, "detail-clip")
            svg.append('<g clip-path="url(#detail-clip)">')
            _emit_detail(svg, room_cracks, room_stones,
                         room_scratches)
            _emit_thematic_detail(svg, room_webs, room_bones,
                                 room_skulls)
            svg.append('</g>')
        else:
            _emit_detail(svg, room_cracks, room_stones,
                         room_scratches)
            _emit_thematic_detail(svg, room_webs, room_bones,
                                 room_skulls)

    # Corridor detail — no clipping
    has_cor = (cor_cracks or cor_stones or cor_scratches
               or cor_webs or cor_bones or cor_skulls)
    if has_cor:
        _emit_detail(svg, cor_cracks, cor_stones, cor_scratches)
        _emit_thematic_detail(svg, cor_webs, cor_bones, cor_skulls)

    # Phase 2 / 3a / 3b decorators — cobblestone, garden, field,
    # cart tracks, ore deposits. All run through the unified
    # TileDecorator pipeline so adding biome variants is one new
    # entry per decorator.
    from nhc.rendering._decorators import walk_and_paint
    svg.extend(walk_and_paint(
        ctx,
        [
            COBBLESTONE, COBBLE_STONE,
            BRICK, FLAGSTONE, OPUS_RETICULATUM,
            FIELD_STONE,
            GARDEN_LINE,
            CART_TRACK_RAILS, CART_TRACK_TIES,
            ORE_DEPOSIT,
        ],
        layer_name="floor_detail",
    ))


# ── Cobblestone (STREET + PAVED) ─────────────────────────────

_COBBLE_STROKE = "#8A7A6A"
_COBBLE_FILL = "#E8DFD0"
_STONE_FILL = "#C8BEB0"
_STONE_STROKE = "#9A8A7A"

_COBBLESTONE_SURFACES = (SurfaceType.STREET, SurfaceType.PAVED)


def _is_cobble_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].surface_type in _COBBLESTONE_SURFACES


def _cobblestone_paint(args) -> list[str]:
    """Paint the 3x3 cobblestone grid for one tile.

    Decorator entry point for :data:`COBBLESTONE`. Forwards to the
    geometry helper :func:`_cobblestone_tile`.
    """
    cobbles: list[str] = []
    _cobblestone_tile(args.rng, args.px, args.py, cobbles)
    return cobbles


def _cobble_stone_paint(args) -> list[str]:
    """Paint an occasional decorative stone on a cobble tile."""
    if args.rng.random() >= 0.12:
        return []
    stones: list[str] = []
    _cobble_stone(args.rng, args.px, args.py, stones)
    return stones


def _cobblestone_tile(
    rng: random.Random, px: float, py: float,
    cobbles: list[str],
) -> None:
    """Draw a grid of irregular small rectangles for one tile."""
    # 3x3 cobblestone grid within the tile
    cols, rows = 3, 3
    cw = CELL / cols
    ch = CELL / rows
    for row in range(rows):
        for col in range(cols):
            # Jitter position and size for irregularity
            jx = rng.uniform(-cw * 0.1, cw * 0.1)
            jy = rng.uniform(-ch * 0.1, ch * 0.1)
            jw = rng.uniform(-cw * 0.08, cw * 0.08)
            jh = rng.uniform(-ch * 0.08, ch * 0.08)
            cx = px + col * cw + jx + 0.5
            cy = py + row * ch + jy + 0.5
            sw = cw + jw - 1.0
            sh = ch + jh - 1.0
            if sw > 2 and sh > 2:
                cobbles.append(
                    f'<rect x="{cx:.1f}" y="{cy:.1f}" '
                    f'width="{sw:.1f}" height="{sh:.1f}" '
                    f'rx="1"/>'
                )


def _cobble_stone(
    rng: random.Random, px: float, py: float,
    stones: list[str],
) -> None:
    """Place a small decorative stone on a cobble tile."""
    cx = px + rng.uniform(CELL * 0.2, CELL * 0.8)
    cy = py + rng.uniform(CELL * 0.2, CELL * 0.8)
    rx = rng.uniform(1.5, 3.0)
    ry = rng.uniform(1.0, 2.5)
    angle = rng.uniform(0, 180)
    stones.append(
        f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
        f'rx="{rx:.1f}" ry="{ry:.1f}" '
        f'transform="rotate({angle:.0f},{cx:.1f},{cy:.1f})" '
        f'fill="{_STONE_FILL}" stroke="{_STONE_STROKE}" '
        f'stroke-width="0.5"/>'
    )


# Decorators (Phase 2). Both fire on STREET (town surfaces) and
# PAVED (keep / castle interior floors). The two are split so each
# can wrap its fragments in its own SVG group with the right
# opacity / stroke style.
COBBLESTONE = TileDecorator(
    name="cobblestone",
    layer="floor_detail",
    predicate=_is_cobble_tile,
    paint=_cobblestone_paint,
    group_open=(
        f'<g opacity="0.35" fill="none" '
        f'stroke="{_COBBLE_STROKE}" stroke-width="0.4">'
    ),
    z_order=10,
)
COBBLE_STONE = TileDecorator(
    name="cobble_stone",
    layer="floor_detail",
    predicate=_is_cobble_tile,
    paint=_cobble_stone_paint,
    group_open='<g opacity="0.5">',
    z_order=11,
)


# ── Cobblestone variants ─────────────────────────────────────
#
# Three decorative cousins of the COBBLESTONE pattern. Each fires
# on its own SurfaceType tag so a site assembler can pick the
# pattern that fits the building / plaza role. They share the
# COBBLESTONE wrapping shape (opacity-0.35 stroked group) but use
# distinct strokes + per-tile geometry:
#
#   BRICK              running-bond rectangles (wider than tall)
#   FLAGSTONE          irregular polygon plates with thin gaps
#   OPUS_RETICULATUM   classical Roman diamond-net (45-deg grid
#                      of square stones forming a continuous net
#                      across tile boundaries)
#
# Adding a new variant is one stroke constant + one paint helper
# + one ``TileDecorator`` constant + one assembler stamp.

BRICK_STROKE = "#A05530"   # warm red-brown, classic fired brick
FLAGSTONE_STROKE = "#6A6055"  # cool grey-brown, slate / quarried stone
OPUS_RETICULATUM_STROKE = "#7A5A3A"
"""Warm grey-brown for the diamond-net mortar lines."""

OPUS_RETICULATUM_DIAMOND_DIAGONAL_PX = 4.0
"""Half-diagonal of each diamond stone (centre-to-vertex). Each
diamond's full diagonal is ``2 * 4 = 8 px``, so 4 diamonds tile
across a 32-px CELL (16 per tile in the 4x4 grid)."""


def _is_brick_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].surface_type is SurfaceType.BRICK


def _is_flagstone_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].surface_type is SurfaceType.FLAGSTONE


def _is_opus_reticulatum_tile(
    level: "Level", x: int, y: int,
) -> bool:
    return (
        level.tiles[y][x].surface_type
        is SurfaceType.OPUS_RETICULATUM
    )


def _brick_paint(args) -> list[str]:
    """Running-bond brick layout for one tile.

    4 rows of 2 bricks each (brick aspect ratio ~2:1). Even rows
    align with the tile edge; odd rows offset by half a brick so
    the courses interlock visually. Per-brick jitter keeps the
    look hand-drawn rather than CAD-perfect.
    """
    rng = args.rng
    px, py = args.px, args.py
    bw = CELL / 2
    bh = CELL / 4
    bricks: list[str] = []
    for row in range(4):
        offset = bw / 2 if row % 2 == 1 else 0.0
        # Each row paints the half-brick at the left edge (when
        # offset) plus the two full bricks; offsetting back keeps
        # the row tilable across adjacent BRICK tiles.
        for col in range(3 if offset else 2):
            x0 = px + col * bw - offset
            y0 = py + row * bh
            jx = rng.uniform(-bw * 0.06, bw * 0.06)
            jy = rng.uniform(-bh * 0.06, bh * 0.06)
            jw = rng.uniform(-bw * 0.06, bw * 0.06)
            jh = rng.uniform(-bh * 0.06, bh * 0.06)
            bx = x0 + jx + 0.5
            by = y0 + jy + 0.5
            bw_jit = bw + jw - 1.0
            bh_jit = bh + jh - 1.0
            # Clip the rect to the tile bounds so the half-brick at
            # the left edge of an odd row doesn't leak out.
            if bx < px:
                bw_jit -= (px - bx)
                bx = px
            if bx + bw_jit > px + CELL:
                bw_jit = px + CELL - bx
            if bw_jit > 1.5 and bh_jit > 1.5:
                bricks.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" '
                    f'width="{bw_jit:.1f}" '
                    f'height="{bh_jit:.1f}" rx="0.5"/>'
                )
    return bricks


def _flagstone_paint(args) -> list[str]:
    """Four irregular polygon plates per tile.

    Divides the tile into 2x2 quadrants, then inside each quadrant
    draws a jittered pentagon whose corners avoid the quadrant
    boundary -- the implicit gap between adjacent pentagons reads
    as the mortar line between paving stones.
    """
    rng = args.rng
    px, py = args.px, args.py
    half = CELL / 2
    inset = half * 0.08  # mortar gap from quadrant boundary
    plates: list[str] = []
    for qy in range(2):
        for qx in range(2):
            cx = px + qx * half
            cy = py + qy * half
            # Five corner points: TL, T, TR, BR, BL with jitter.
            jitter = lambda: rng.uniform(-half * 0.07, half * 0.07)
            pts = [
                (cx + inset + jitter(), cy + inset + jitter()),
                (
                    cx + half * 0.5 + jitter(),
                    cy + inset * 0.5 + jitter(),
                ),
                (
                    cx + half - inset + jitter(),
                    cy + inset + jitter(),
                ),
                (
                    cx + half - inset + jitter(),
                    cy + half - inset + jitter(),
                ),
                (
                    cx + inset + jitter(),
                    cy + half - inset + jitter(),
                ),
            ]
            polygon = " ".join(
                f"{x:.1f},{y:.1f}" for x, y in pts
            )
            plates.append(f'<polygon points="{polygon}"/>')
    return plates


def _opus_reticulatum_paint(args) -> list[str]:
    """Diamond-net pattern for one tile (Opus Reticulatum).

    Each tile contains a 4x4 grid of diamond stones at a fixed
    half-diagonal of :data:`OPUS_RETICULATUM_DIAMOND_DIAGONAL_PX`.
    The diamonds are positioned so the pattern tiles continuously
    across cell boundaries -- a tile's east-edge diamond shares
    its vertex with the neighbouring tile's west-edge diamond,
    forming the classical Roman 'net' (reticulum).

    Stroke-only; the wrapping group sets opacity / colour.
    """
    px, py = args.px, args.py
    half = OPUS_RETICULATUM_DIAMOND_DIAGONAL_PX
    full = 2 * half
    diamonds: list[str] = []
    # Centres on a uniform grid aligned to the tile origin so
    # the pattern phase repeats per tile. Each diamond has its
    # vertex at (cx, cy +/- half) and (cx +/- half, cy).
    n_axis = int(round(CELL / full))
    for j in range(n_axis):
        for i in range(n_axis):
            cx = px + (i + 0.5) * full
            cy = py + (j + 0.5) * full
            d = (
                f"M{cx:.1f},{cy - half:.1f} "
                f"L{cx + half:.1f},{cy:.1f} "
                f"L{cx:.1f},{cy + half:.1f} "
                f"L{cx - half:.1f},{cy:.1f} Z"
            )
            diamonds.append(f'<path d="{d}"/>')
    return diamonds


BRICK = TileDecorator(
    name="brick",
    layer="floor_detail",
    predicate=_is_brick_tile,
    paint=_brick_paint,
    group_open=(
        f'<g opacity="0.35" fill="none" '
        f'stroke="{BRICK_STROKE}" stroke-width="0.4">'
    ),
    z_order=12,
)
FLAGSTONE = TileDecorator(
    name="flagstone",
    layer="floor_detail",
    predicate=_is_flagstone_tile,
    paint=_flagstone_paint,
    group_open=(
        f'<g opacity="0.35" fill="none" '
        f'stroke="{FLAGSTONE_STROKE}" stroke-width="0.4">'
    ),
    z_order=13,
)
OPUS_RETICULATUM = TileDecorator(
    name="opus_reticulatum",
    layer="floor_detail",
    predicate=_is_opus_reticulatum_tile,
    paint=_opus_reticulatum_paint,
    group_open=(
        f'<g opacity="0.45" fill="none" '
        f'stroke="{OPUS_RETICULATUM_STROKE}" stroke-width="0.4">'
    ),
    z_order=14,
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
FIELD_STONE_PROBABILITY = 0.10

GARDEN_LINE_STROKE = "#4A6A3A"
GARDEN_LINE_WIDTH = 0.5
GARDEN_LINE_PROBABILITY = 0.35


def _is_field_overlay_tile(level: "Level", x: int, y: int) -> bool:
    """Predicate for the FIELD_STONE decorator.

    Phase 3b moved field tiles to ``Terrain.GRASS`` so the theme
    grass tint + blade strokes paint the base look; the decorator
    only adds the scattered-stone overlay.
    """
    tile = level.tiles[y][x]
    return (
        tile.terrain is Terrain.GRASS
        and tile.surface_type is SurfaceType.FIELD
    )


def _field_stone_paint(args) -> list[str]:
    """Probabilistic scattered stone for one field tile."""
    if args.rng.random() >= FIELD_STONE_PROBABILITY:
        return []
    return [_field_stone(args.rng, args.px, args.py)]


def _field_stone(
    rng: random.Random, px: float, py: float,
) -> str:
    cx = px + rng.uniform(CELL * 0.2, CELL * 0.8)
    cy = py + rng.uniform(CELL * 0.2, CELL * 0.8)
    rx = rng.uniform(1.5, 2.8)
    ry = rng.uniform(1.2, 2.2)
    angle = rng.uniform(0, 180)
    return (
        f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
        f'rx="{rx:.1f}" ry="{ry:.1f}" '
        f'transform="rotate({angle:.0f},{cx:.1f},{cy:.1f})" '
        f'fill="{FIELD_STONE_FILL}" '
        f'stroke="{FIELD_STONE_STROKE}" '
        f'stroke-width="0.5"/>'
    )


FIELD_STONE = TileDecorator(
    name="field_stone",
    layer="floor_detail",
    predicate=_is_field_overlay_tile,
    paint=_field_stone_paint,
    group_open='<g opacity="0.8">',
    z_order=15,
)


def _is_garden_overlay_tile(level: "Level", x: int, y: int) -> bool:
    """Predicate for the GARDEN_LINE decorator.

    Phase 3a moved garden tiles to ``Terrain.GRASS`` so the theme
    grass tint + blade strokes paint the base look. The hoe-row
    overlay rides on top — fire only on tiles that carry both
    ``GRASS`` terrain and the ``GARDEN`` surface tag.
    """
    tile = level.tiles[y][x]
    return (
        tile.terrain is Terrain.GRASS
        and tile.surface_type is SurfaceType.GARDEN
    )


def _garden_line_paint(args) -> list[str]:
    """Probabilistic hoe-row line for one garden tile."""
    if args.rng.random() >= GARDEN_LINE_PROBABILITY:
        return []
    return [_garden_line(args.rng, args.px, args.py)]


def _garden_line(
    rng: random.Random, px: float, py: float,
) -> str:
    x0 = px + rng.uniform(CELL * 0.15, CELL * 0.4)
    y0 = py + rng.uniform(CELL * 0.15, CELL * 0.85)
    x1 = px + rng.uniform(CELL * 0.6, CELL * 0.85)
    y1 = py + rng.uniform(CELL * 0.15, CELL * 0.85)
    return f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}"/>'


GARDEN_LINE = TileDecorator(
    name="garden_line",
    layer="floor_detail",
    predicate=_is_garden_overlay_tile,
    paint=_garden_line_paint,
    group_open=(
        f'<g fill="none" stroke="{GARDEN_LINE_STROKE}" '
        f'stroke-width="{GARDEN_LINE_WIDTH}" opacity="0.65">'
    ),
    z_order=20,
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


def _is_wood_floor_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].terrain is Terrain.FLOOR


def _wood_floor_fill_paint(args) -> list[str]:
    """Paint one wood-floor rect for a FLOOR tile."""
    return [
        f'<rect x="{args.px:.0f}" y="{args.py:.0f}" '
        f'width="{CELL}" height="{CELL}" '
        f'fill="{WOOD_FLOOR_FILL}"/>'
    ]


WOOD_FLOOR_FILL_DECORATOR = TileDecorator(
    name="wood_floor_fill",
    layer="floor_detail",
    predicate=_is_wood_floor_tile,
    paint=_wood_floor_fill_paint,
    requires=frozenset({"interior_finish_wood"}),
    z_order=1,
)


def _wood_floor_room_bucket(level: "Level", x: int, y: int) -> str:
    """Always return ``"room"`` so the wood-fill decorator routes
    through the dungeon-poly clip group when present."""
    return "room"


def _render_wood_floor(
    svg: list[str], level: "Level", rng: random.Random,
    dungeon_poly=None,
    building_polygon: list[tuple[float, float]] | None = None,
    ctx=None,
) -> None:
    """Wood plank fill and parquet seams for Building interior floors.

    Emits one ``<rect>`` filled with :data:`WOOD_FLOOR_FILL` per
    FLOOR tile, then a laminated-parquet seam pattern per room:
    strips of :data:`WOOD_PLANK_WIDTH_PX` thickness aligned with
    the room's major axis, each strip divided into planks
    :data:`WOOD_PLANK_LENGTH_PX` long, with a
    :data:`WOOD_PLANK_OFFSET_PX` running-bond offset per strip so
    plank ends never line up across adjacent strips.

    When ``dungeon_poly`` is supplied, the seam group is clipped
    to the dungeon interior so plank ends don't bleed onto walls.

    When ``building_polygon`` is supplied (octagon / circle
    buildings), the wood fill stretches to the building's outer
    outline rather than stopping at the rect-aligned tile
    boundaries -- the planks visually reach the chamfer diagonal
    or curved wall the masonry renderer paints.
    """
    # Emit the clip first (if any) so per-tile fills AND the
    # grain / seam overlays share it. Non-orthogonal footprints
    # (octagon, circle) otherwise let the square per-tile wood
    # rects overflow past the diagonal wall.
    clip_attr = ""
    if dungeon_poly is not None and not dungeon_poly.is_empty:
        _dungeon_interior_clip(svg, dungeon_poly, "wood-interior-clip")
        clip_attr = ' clip-path="url(#wood-interior-clip)"'

    if building_polygon is not None:
        poly_points = " ".join(
            f"{x:.1f},{y:.1f}" for x, y in building_polygon
        )
        svg.append(
            '<defs><clipPath id="wood-bldg-clip">'
            f'<polygon points="{poly_points}"/>'
            '</clipPath></defs>'
        )
        xs = [p[0] for p in building_polygon]
        ys = [p[1] for p in building_polygon]
        bx, by = min(xs), min(ys)
        bw = max(xs) - bx
        bh = max(ys) - by
        svg.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" '
            f'width="{bw:.1f}" height="{bh:.1f}" '
            f'fill="{WOOD_FLOOR_FILL}" '
            'clip-path="url(#wood-bldg-clip)"/>'
        )
        # The building polygon already covers the entire wood
        # area (including chamfer slivers); skip the per-tile
        # fills below, which would only redundantly stamp under
        # what we just painted.
    else:
        # Per-tile wood rects flow through the unified
        # TileDecorator pipeline. The dungeon-poly clip is owned
        # by ``walk_and_paint`` via ``room_clip_id``; the
        # ``requires={"interior_finish_wood"}`` flag on the
        # decorator gates it so a future ``interior_finish="earth"``
        # bundle can swap in without touching this branch.
        from nhc.rendering._decorators import walk_and_paint
        if ctx is None:
            from nhc.rendering._render_context import (
                build_render_context,
            )
            ctx = build_render_context(level, seed=0)
        svg.extend(walk_and_paint(
            ctx,
            [WOOD_FLOOR_FILL_DECORATOR],
            layer_name="wood_floor_fill",
            tile_bucket=_wood_floor_room_bucket,
            room_clip_id="wood-interior-clip",
        ))

    if not level.rooms:
        return

    # Grain first (sits under the plank seams).
    _render_wood_grain(svg, level, rng, clip_attr)

    seams: list[str] = []
    for room in level.rooms:
        seams.extend(_parquet_seams_for_room(room, rng))
    if not seams:
        return
    svg.append(
        f'<g fill="none" stroke="{WOOD_SEAM_STROKE}" '
        f'stroke-width="{WOOD_SEAM_WIDTH}"{clip_attr}>'
    )
    svg.append("".join(seams))
    svg.append("</g>")


def _render_wood_grain(
    svg: list[str], level: "Level", rng: random.Random,
    clip_attr: str,
) -> None:
    """Overlay subtle grain streaks along the parquet direction.

    Each strip carries :data:`WOOD_GRAIN_LINES_PER_STRIP` streaks
    at jittered positions, alternating between the lighter and
    darker grain colours. Each streak spans the room's full
    major-axis extent so the grain reads as a continuous flow
    rather than per-plank strokes.
    """
    lines_light: list[str] = []
    lines_dark: list[str] = []
    for room in level.rooms:
        r = room.rect
        x0 = r.x * CELL
        y0 = r.y * CELL
        x1 = (r.x + r.width) * CELL
        y1 = (r.y + r.height) * CELL
        horizontal = r.width >= r.height
        width = WOOD_PLANK_WIDTH_PX

        if horizontal:
            y = y0
            while y < y1:
                strip_bot = min(y + width, y1)
                span = strip_bot - y
                if span <= 0.5:
                    y += width
                    continue
                for i in range(WOOD_GRAIN_LINES_PER_STRIP):
                    gy = rng.uniform(
                        y + span * 0.15, strip_bot - span * 0.15,
                    )
                    dest = lines_light if i % 2 == 0 else lines_dark
                    dest.append(
                        f'<line x1="{x0:.1f}" y1="{gy:.1f}" '
                        f'x2="{x1:.1f}" y2="{gy:.1f}"/>'
                    )
                y += width
        else:
            x = x0
            while x < x1:
                strip_right = min(x + width, x1)
                span = strip_right - x
                if span <= 0.5:
                    x += width
                    continue
                for i in range(WOOD_GRAIN_LINES_PER_STRIP):
                    gx = rng.uniform(
                        x + span * 0.15, strip_right - span * 0.15,
                    )
                    dest = lines_light if i % 2 == 0 else lines_dark
                    dest.append(
                        f'<line x1="{gx:.1f}" y1="{y0:.1f}" '
                        f'x2="{gx:.1f}" y2="{y1:.1f}"/>'
                    )
                x += width

    for colour, group in (
        (WOOD_GRAIN_LIGHT, lines_light),
        (WOOD_GRAIN_DARK, lines_dark),
    ):
        if not group:
            continue
        svg.append(
            f'<g fill="none" stroke="{colour}" '
            f'stroke-width="{WOOD_GRAIN_STROKE_WIDTH}" '
            f'opacity="{WOOD_GRAIN_OPACITY}"{clip_attr}>'
        )
        svg.append("".join(group))
        svg.append("</g>")


def _parquet_seams_for_room(
    room, rng: random.Random,
) -> list[str]:
    r = room.rect
    x0 = r.x * CELL
    y0 = r.y * CELL
    x1 = (r.x + r.width) * CELL
    y1 = (r.y + r.height) * CELL
    horizontal = r.width >= r.height
    width = WOOD_PLANK_WIDTH_PX

    seams: list[str] = []
    if horizontal:
        y = y0
        while y < y1:
            strip_bot = min(y + width, y1)
            # Walk along the strip picking a random plank length
            # in [MIN, MAX] per plank. A random initial offset in
            # the same range keeps the first plank from always
            # starting flush with the left edge.
            x_end = x0 + rng.uniform(
                WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_LENGTH_MAX,
            )
            while x_end < x1:
                seams.append(
                    f'<line x1="{x_end:.1f}" y1="{y:.1f}" '
                    f'x2="{x_end:.1f}" y2="{strip_bot:.1f}"/>'
                )
                x_end += rng.uniform(
                    WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_LENGTH_MAX,
                )
            y += width
            if y < y1:
                seams.append(
                    f'<line x1="{x0:.1f}" y1="{y:.1f}" '
                    f'x2="{x1:.1f}" y2="{y:.1f}"/>'
                )
    else:
        x = x0
        while x < x1:
            strip_right = min(x + width, x1)
            y_end = y0 + rng.uniform(
                WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_LENGTH_MAX,
            )
            while y_end < y1:
                seams.append(
                    f'<line x1="{x:.1f}" y1="{y_end:.1f}" '
                    f'x2="{strip_right:.1f}" y2="{y_end:.1f}"/>'
                )
                y_end += rng.uniform(
                    WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_LENGTH_MAX,
                )
            x += width
            if x < x1:
                seams.append(
                    f'<line x1="{x:.1f}" y1="{y0:.1f}" '
                    f'x2="{x:.1f}" y2="{y1:.1f}"/>'
                )
    return seams


# ── Mine cart tracks ─────────────────────────────────────────

_TRACK_RAIL = "#6A5A4A"
_TRACK_TIE = "#8A7A5A"


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


def _cart_track_rails_paint(args) -> list[str]:
    """Two parallel rails for one TRACK tile."""
    px, py = args.px, args.py
    if _track_horizontal_at(args.ctx.level, args.x, args.y):
        y1 = py + CELL * 0.35
        y2 = py + CELL * 0.65
        return [
            f'<line x1="{px:.1f}" y1="{y1:.1f}" '
            f'x2="{px + CELL:.1f}" y2="{y1:.1f}"/>',
            f'<line x1="{px:.1f}" y1="{y2:.1f}" '
            f'x2="{px + CELL:.1f}" y2="{y2:.1f}"/>',
        ]
    x1 = px + CELL * 0.35
    x2 = px + CELL * 0.65
    return [
        f'<line x1="{x1:.1f}" y1="{py:.1f}" '
        f'x2="{x1:.1f}" y2="{py + CELL:.1f}"/>',
        f'<line x1="{x2:.1f}" y1="{py:.1f}" '
        f'x2="{x2:.1f}" y2="{py + CELL:.1f}"/>',
    ]


def _cart_track_ties_paint(args) -> list[str]:
    """One cross-tie for one TRACK tile."""
    px, py = args.px, args.py
    cx, cy = px + CELL / 2, py + CELL / 2
    if _track_horizontal_at(args.ctx.level, args.x, args.y):
        y1 = py + CELL * 0.35
        y2 = py + CELL * 0.65
        return [
            f'<line x1="{cx:.1f}" y1="{y1 - 1:.1f}" '
            f'x2="{cx:.1f}" y2="{y2 + 1:.1f}"/>'
        ]
    x1 = px + CELL * 0.35
    x2 = px + CELL * 0.65
    return [
        f'<line x1="{x1 - 1:.1f}" y1="{cy:.1f}" '
        f'x2="{x2 + 1:.1f}" y2="{cy:.1f}"/>'
    ]


CART_TRACK_RAILS = TileDecorator(
    name="cart_track_rails",
    layer="floor_detail",
    predicate=_is_track_tile,
    paint=_cart_track_rails_paint,
    group_open=(
        f'<g id="cart-tracks" opacity="0.55" '
        f'stroke="{_TRACK_RAIL}" stroke-width="0.9" '
        f'stroke-linecap="round">'
    ),
    z_order=30,
)
CART_TRACK_TIES = TileDecorator(
    name="cart_track_ties",
    layer="floor_detail",
    predicate=_is_track_tile,
    paint=_cart_track_ties_paint,
    group_open=(
        f'<g id="cart-track-ties" opacity="0.5" '
        f'stroke="{_TRACK_TIE}" stroke-width="1.4" '
        f'stroke-linecap="round">'
    ),
    z_order=31,
)


# ── Ore deposits ─────────────────────────────────────────────

_ORE_FILL = "#D4B14A"
_ORE_STROKE = "#6A4A1A"


def _is_ore_tile(level: "Level", x: int, y: int) -> bool:
    return level.tiles[y][x].feature == "ore_deposit"


def _ore_deposit_paint(args) -> list[str]:
    """Diamond glint for one ore-deposit wall tile."""
    rng = args.rng
    px, py = args.px, args.py
    cx = px + CELL / 2 + rng.uniform(-1.0, 1.0)
    cy = py + CELL / 2 + rng.uniform(-1.0, 1.0)
    r = rng.uniform(1.8, 2.6)
    return [
        f'<polygon points="'
        f'{cx:.1f},{cy - r:.1f} '
        f'{cx + r:.1f},{cy:.1f} '
        f'{cx:.1f},{cy + r:.1f} '
        f'{cx - r:.1f},{cy:.1f}"/>'
    ]


ORE_DEPOSIT = TileDecorator(
    name="ore_deposit",
    layer="floor_detail",
    predicate=_is_ore_tile,
    paint=_ore_deposit_paint,
    group_open=(
        f'<g id="ore-deposits" fill="{_ORE_FILL}" '
        f'stroke="{_ORE_STROKE}" stroke-width="0.4">'
    ),
    z_order=40,
)
