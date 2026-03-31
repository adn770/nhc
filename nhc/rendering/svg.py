"""SVG floor renderer — Dyson Logos style.

Generates a static SVG image of a dungeon floor from nhc's Level model.
Black and white only. The SVG contains rooms, corridors, walls, doors
(as gaps in walls), stairs (triangular parallel lines), and procedural
cross-hatching. No entities — those are overlaid by the
browser client using the tileset.

Hatching uses Shapely geometry and Perlin noise for organic effects.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import noise as _noise
from shapely.geometry import LineString, Point, Polygon

if TYPE_CHECKING:
    from nhc.dungeon.model import Level

# ── Constants ────────────────────────────────────────────────────

CELL = 32          # pixels per grid cell
PADDING = 32       # padding around the map (room for hatching)
WALL_WIDTH = 4.0   # wall stroke width (bold Dyson style)
WALL_THIN = 2.0    # thinner wall for corridors
GRID_WIDTH = 0.3   # soft floor grid line width
HATCH_UNDERLAY = "#D0D0D0"

# ── Colors (black & white) ──────────────────────────────────────

BG = "#F5EDE0"
INK = "#000000"
FLOOR_STONE_FILL = "#E8D5B8"  # soft brown for room floor stones
FLOOR_STONE_STROKE = "#666666"


def render_floor_svg(level: "Level", seed: int = 0) -> str:
    """Generate a Dyson-style SVG for a dungeon floor."""
    w = level.width * CELL + 2 * PADDING
    h = level.height * CELL + 2 * PADDING

    svg: list[str] = []
    svg.append(
        f'<svg width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )
    svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')
    svg.append(f'<g transform="translate({PADDING},{PADDING})">')

    # Precompute tiles owned by smooth-outlined rooms so they
    # can be excluded from the tile-based grid/detail passes and
    # drawn separately with clipped smooth outlines.
    smooth_tiles: set[tuple[int, int]] = set()
    for room in level.rooms:
        if _room_svg_outline(room):
            smooth_tiles |= room.floor_tiles()

    # Layer 1: Room shadows (subtle)
    _render_room_shadows(svg, level)

    # Layer 2: Floor fills
    _render_floors(svg, level)

    # Layer 3: Soft floor grid (rooms + corridors, excluding smooth)
    _render_floor_grid(svg, level, smooth_tiles)

    # Layer 3b: Floor detail — cracks and stones (excluding smooth)
    _render_floor_detail(svg, level, seed, smooth_tiles)

    # Layer 4: Hatching (behind walls)
    _render_hatching(svg, level, seed)

    # Layer 4b: Fill smooth-shaped rooms over hatching
    _render_smooth_floor_fills(svg, level)

    # Layer 4c: Floor grid + detail inside smooth-shaped rooms
    _render_smooth_floor_grid(svg, level, seed)

    # Layer 5: Walls (on top of hatching)
    _render_walls(svg, level)

    # Layer 6: Stairs
    _render_stairs(svg, level)

    svg.append("</g>")
    svg.append("</svg>")
    return "\n".join(svg)


# ── Helpers ──────────────────────────────────────────────────────

def _is_floor(level: "Level", x: int, y: int) -> bool:
    from nhc.dungeon.model import Terrain
    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    return t.terrain in (Terrain.FLOOR, Terrain.WATER)


def _is_door(level: "Level", x: int, y: int) -> bool:
    """True for visible doors (not secret — those look like walls)."""
    if not level.in_bounds(x, y):
        return False
    f = level.tiles[y][x].feature
    return f in ("door_closed", "door_open", "door_locked")


# ── Smooth shape outlines ────────────────────────────────────────


def _room_svg_outline(room: "Room") -> str | None:
    """Return an SVG path for a room's smooth geometric outline.

    Returns None for shapes that should use the default tile-edge
    walls (e.g. RectShape or unknown shapes).  Coordinates are in
    pixel space (tile * CELL).
    """
    from nhc.dungeon.model import (
        CircleShape, CrossShape, HexShape, HybridShape,
        OctagonShape, RectShape,
    )
    r = room.rect
    shape = room.shape

    # Pixel bounding box
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if isinstance(shape, CircleShape):
        cx = px + pw / 2
        cy = py + ph / 2
        radius = min(pw, ph) / 2
        return (
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
            f'r="{radius:.1f}"/>'
        )

    if isinstance(shape, HexShape):
        # Flat-topped hexagon: 6 vertices
        cx = px + pw / 2
        cy = py + ph / 2
        hw = pw / 2     # half width
        hh = ph / 2     # half height
        inset = pw / 4   # horizontal inset at top/bottom
        pts = [
            (px + inset, py),           # top-left
            (px + pw - inset, py),      # top-right
            (px + pw, cy),              # right
            (px + pw - inset, py + ph), # bottom-right
            (px + inset, py + ph),      # bottom-left
            (px, cy),                   # left
        ]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polygon points="{points}"/>'

    if isinstance(shape, OctagonShape):
        clip = max(1, min(r.width, r.height) // 3) * CELL
        pts = [
            (px + clip, py),             # top-left flat
            (px + pw - clip, py),        # top-right flat
            (px + pw, py + clip),        # right-top flat
            (px + pw, py + ph - clip),   # right-bottom flat
            (px + pw - clip, py + ph),   # bottom-right flat
            (px + clip, py + ph),        # bottom-left flat
            (px, py + ph - clip),        # left-bottom flat
            (px, py + clip),             # left-top flat
        ]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polygon points="{points}"/>'

    if isinstance(shape, CrossShape):
        bar_w = max(2, r.width // 3) * CELL
        bar_h = max(2, r.height // 3) * CELL
        # Center of cross
        cx_tile = r.x + r.width // 2
        cy_tile = r.y + r.height // 2
        # Vertical bar left/right edges
        vl = (cx_tile - max(2, r.width // 3) // 2) * CELL
        vr = vl + bar_w
        # Horizontal bar top/bottom edges
        ht = (cy_tile - max(2, r.height // 3) // 2) * CELL
        hb = ht + bar_h
        # 12-point polygon tracing the + outline clockwise
        pts = [
            (vl, py),           # top-left of vertical bar
            (vr, py),           # top-right of vertical bar
            (vr, ht),           # inner corner: right arm top
            (px + pw, ht),      # right arm top-right
            (px + pw, hb),      # right arm bottom-right
            (vr, hb),           # inner corner: right arm bottom
            (vr, py + ph),      # bottom-right of vertical bar
            (vl, py + ph),      # bottom-left of vertical bar
            (vl, hb),           # inner corner: left arm bottom
            (px, hb),           # left arm bottom-left
            (px, ht),           # left arm top-left
            (vl, ht),           # inner corner: left arm top
        ]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polygon points="{points}"/>'

    if isinstance(shape, HybridShape):
        return _hybrid_svg_outline(room)

    # RectShape or unknown — use tile-edge walls
    return None


def _hybrid_svg_outline(room: "Room") -> str | None:
    """Build an SVG path for a hybrid room.

    Traces the outer contour combining the curved sub-shape on
    one side and straight lines on the rect side.
    """
    from nhc.dungeon.model import (
        CircleShape, HexShape, HybridShape, OctagonShape, RectShape,
    )
    shape = room.shape
    if not isinstance(shape, HybridShape):
        return None

    r = room.rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if shape.split == "vertical":
        mid = px + (r.width // 2) * CELL
        # Left sub-shape occupies [px, mid], right occupies [mid, px+pw]
        left_path = _half_outline(
            shape.left, px, py, mid - px, ph, side="left",
        )
        right_path = _half_outline(
            shape.right, mid, py, px + pw - mid, ph, side="right",
        )
        if left_path and right_path:
            # Combine: start top-left, trace left outer edge down,
            # then right outer edge back up
            return (
                f'<path d="'
                f'M{mid:.1f},{py:.1f} '  # top-mid
                f'{left_path} '           # left side → bottom-mid
                f'{right_path} '          # right side → top-mid
                f'Z"/>'
            )
    else:
        mid = py + (r.height // 2) * CELL
        top_path = _half_outline(
            shape.left, px, py, pw, mid - py, side="top",
        )
        bottom_path = _half_outline(
            shape.right, px, mid, pw, py + ph - mid, side="bottom",
        )
        if top_path and bottom_path:
            return (
                f'<path d="'
                f'M{px:.1f},{mid:.1f} '
                f'{top_path} '
                f'{bottom_path} '
                f'Z"/>'
            )

    return None


def _half_outline(
    sub_shape: "RoomShape",
    px: float, py: float, pw: float, ph: float,
    side: str,
) -> str | None:
    """Return SVG path commands for one half of a hybrid outline.

    *side* is which outer edge this half contributes:
    - "left": traces top→left→bottom (clockwise down the left)
    - "right": traces bottom→right→top (clockwise up the right)
    - "top": traces left→top→right (clockwise across the top)
    - "bottom": traces right→bottom→left (clockwise across bottom)
    """
    from nhc.dungeon.model import (
        CircleShape, HexShape, OctagonShape, RectShape,
    )

    if isinstance(sub_shape, RectShape):
        if side == "left":
            # top-mid → top-left → bottom-left → bottom-mid
            return (
                f'L{px:.1f},{py:.1f} '
                f'L{px:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "right":
            # bottom-mid → bottom-right → top-right → top-mid
            return (
                f'L{px + pw:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py:.1f} '
                f'L{px:.1f},{py:.1f}'
            )
        if side == "top":
            # left-mid → top-left → top-right → right-mid
            return (
                f'L{px:.1f},{py:.1f} '
                f'L{px + pw:.1f},{py:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "bottom":
            # right-mid → bottom-right → bottom-left → left-mid
            return (
                f'L{px + pw:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py:.1f}'
            )

    if isinstance(sub_shape, CircleShape):
        cx = px + pw / 2
        cy = py + ph / 2
        # Must match CircleShape.floor_tiles: radius = min(w,h)/2
        # where w,h are in tiles. Convert to pixels.
        tw = int(round(pw / CELL))
        th = int(round(ph / CELL))
        r = min(tw, th) * CELL / 2
        # SVG arc: A rx ry x-rotation large-arc sweep x y
        if side == "left":
            # Arc from (cx, cy-r) clockwise down to (cx, cy+r)
            return (
                f'L{cx:.1f},{cy - r:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,0 '
                f'{cx:.1f},{cy + r:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "right":
            return (
                f'L{cx:.1f},{cy + r:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,0 '
                f'{cx:.1f},{cy - r:.1f} '
                f'L{px:.1f},{py:.1f}'
            )
        if side == "top":
            return (
                f'L{cx - r:.1f},{cy:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,0 '
                f'{cx + r:.1f},{cy:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "bottom":
            return (
                f'L{cx + r:.1f},{cy:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,0 '
                f'{cx - r:.1f},{cy:.1f} '
                f'L{px:.1f},{py:.1f}'
            )

    if isinstance(sub_shape, HexShape):
        inset = pw / 4
        cy = py + ph / 2
        if side == "left":
            return (
                f'L{px + inset:.1f},{py:.1f} '
                f'L{px:.1f},{cy:.1f} '
                f'L{px + inset:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "right":
            return (
                f'L{px + pw - inset:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{cy:.1f} '
                f'L{px + pw - inset:.1f},{py:.1f} '
                f'L{px:.1f},{py:.1f}'
            )
        if side == "top":
            cx = px + pw / 2
            inset_v = ph / 4
            return (
                f'L{px:.1f},{py + inset_v:.1f} '
                f'L{cx:.1f},{py:.1f} '
                f'L{px + pw:.1f},{py + inset_v:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "bottom":
            cx = px + pw / 2
            inset_v = ph / 4
            return (
                f'L{px + pw:.1f},{py + ph - inset_v:.1f} '
                f'L{cx:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py + ph - inset_v:.1f} '
                f'L{px:.1f},{py:.1f}'
            )

    if isinstance(sub_shape, OctagonShape):
        from nhc.dungeon.model import Rect
        # Approximate clip from the tile-based algorithm
        tw = int(pw / CELL)
        th = int(ph / CELL)
        clip = max(1, min(tw, th) // 3) * CELL
        if side == "left":
            return (
                f'L{px + clip:.1f},{py:.1f} '
                f'L{px:.1f},{py + clip:.1f} '
                f'L{px:.1f},{py + ph - clip:.1f} '
                f'L{px + clip:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "right":
            return (
                f'L{px + pw - clip:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py + ph - clip:.1f} '
                f'L{px + pw:.1f},{py + clip:.1f} '
                f'L{px + pw - clip:.1f},{py:.1f} '
                f'L{px:.1f},{py:.1f}'
            )
        if side == "top":
            return (
                f'L{px:.1f},{py + clip:.1f} '
                f'L{px + clip:.1f},{py:.1f} '
                f'L{px + pw - clip:.1f},{py:.1f} '
                f'L{px + pw:.1f},{py + clip:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "bottom":
            return (
                f'L{px + pw:.1f},{py + ph - clip:.1f} '
                f'L{px + pw - clip:.1f},{py + ph:.1f} '
                f'L{px + clip:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py + ph - clip:.1f} '
                f'L{px:.1f},{py:.1f}'
            )

    return None


def _room_shadow_svg(room: "Room") -> str:
    """Return an SVG element for a room's shadow.

    Reuses _room_svg_outline for non-rect shapes, applying fill
    and a (3,3) offset.  Rect rooms get a simple rect shadow.
    """
    outline = _room_svg_outline(room)
    if outline:
        el = outline.replace(
            '/>', f' fill="{INK}" opacity="0.08"/>')
        return f'<g transform="translate(3,3)">{el}</g>'

    # Rect — default rectangle shadow
    r = room.rect
    px, py = r.x * CELL + 3, r.y * CELL + 3
    pw, ph = r.width * CELL, r.height * CELL
    return (
        f'<rect x="{px}" y="{py}" '
        f'width="{pw}" height="{ph}" '
        f'fill="{INK}" opacity="0.08"/>'
    )


# ── Layer renderers ──────────────────────────────────────────────

def _render_room_shadows(svg: list[str], level: "Level") -> None:
    """Subtle offset shadow for rooms (shape-aware)."""
    for room in level.rooms:
        svg.append(_room_shadow_svg(room))


def _render_floors(svg: list[str], level: "Level") -> None:
    """Fill floor tiles with white."""
    for y in range(level.height):
        for x in range(level.width):
            if _is_floor(level, x, y) or _is_door(level, x, y):
                svg.append(
                    f'<rect x="{x * CELL}" y="{y * CELL}" '
                    f'width="{CELL}" height="{CELL}" fill="{BG}"/>'
                )


def _wobbly_grid_seg(
    rng: random.Random, x0: float, y0: float,
    x1: float, y1: float, noise_x: float, noise_y: float,
    base: int,
) -> str:
    """Build one wobbly grid segment with optional gap."""
    wobble = CELL * 0.05
    n_sub = 5
    dx, dy = x1 - x0, y1 - y0
    pts = []
    for i in range(n_sub + 1):
        t = i / n_sub
        lx = x0 + dx * t + _noise.pnoise2(
            noise_x + t * 0.5, noise_y, base=base) * wobble
        ly = y0 + dy * t + _noise.pnoise2(
            noise_x + t * 0.5, noise_y, base=base + 4) * wobble
        # Keep wobble perpendicular only: for vertical lines wobble
        # x, for horizontal wobble y
        if abs(dx) > abs(dy):
            # Mostly horizontal — wobble y only
            lx = x0 + dx * t
            ly = y0 + dy * t + _noise.pnoise2(
                noise_x + t * 0.5, noise_y, base=base) * wobble
        else:
            # Mostly vertical — wobble x only
            lx = x0 + dx * t + _noise.pnoise2(
                noise_x + t * 0.5, noise_y, base=base) * wobble
            ly = y0 + dy * t
        pts.append((lx, ly))
    gap_pos = rng.randint(1, n_sub - 1)
    seg = f'M{pts[0][0]:.1f},{pts[0][1]:.1f}'
    for i in range(1, len(pts)):
        if i == gap_pos and rng.random() < 0.25:
            seg += f' M{pts[i][0]:.1f},{pts[i][1]:.1f}'
        else:
            seg += f' L{pts[i][0]:.1f},{pts[i][1]:.1f}'
    return seg


def _tile_detail(
    rng: random.Random, x: int, y: int, seed: int,
    cracks: list[str], stones: list[str], scratches: list[str],
) -> None:
    """Generate floor detail (cracks, stones, scratches) for one tile."""
    px, py = x * CELL, y * CELL

    roll = rng.random()
    if roll < 0.08:
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
    elif roll < 0.13:
        scratches.append(_y_scratch(rng, px, py, x, y, seed))

    if rng.random() < 0.06:
        stones.append(_floor_stone(rng, px, py))

    if rng.random() < 0.03:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        for _ in range(3):
            sx = cx + rng.uniform(-CELL * 0.2, CELL * 0.2)
            sy = cy + rng.uniform(-CELL * 0.2, CELL * 0.2)
            scale = rng.uniform(0.5, 1.3)
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


def _render_floor_grid(
    svg: list[str], level: "Level",
    skip: set[tuple[int, int]] | None = None,
) -> None:
    """Draw a hand-drawn style grid on floor tiles.

    Tiles in *skip* are excluded (they get their grid from the
    smooth-shape renderer instead).
    """
    rng = random.Random(41)
    segments: list[str] = []
    _skip = skip or set()

    for y in range(level.height):
        for x in range(level.width):
            if (x, y) in _skip:
                continue
            if not (_is_floor(level, x, y) or _is_door(level, x, y)):
                continue
            px, py = x * CELL, y * CELL
            nx_floor = _is_floor(level, x + 1, y) or _is_door(level, x + 1, y)
            ny_floor = _is_floor(level, x, y + 1) or _is_door(level, x, y + 1)

            # Right edge — skip if neighbor is also in a smooth room
            if nx_floor and (x + 1, y) not in _skip:
                segments.append(_wobbly_grid_seg(
                    rng, px + CELL, py, px + CELL, py + CELL,
                    x * 0.7, y * 0.7, base=20,
                ))

            # Bottom edge
            if ny_floor and (x, y + 1) not in _skip:
                segments.append(_wobbly_grid_seg(
                    rng, px, py + CELL, px + CELL, py + CELL,
                    x * 0.3, y * 0.7, base=24,
                ))

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{GRID_WIDTH}" '
            f'opacity="0.7" stroke-linecap="round"/>'
        )


def _render_floor_detail(
    svg: list[str], level: "Level", seed: int,
    skip: set[tuple[int, int]] | None = None,
) -> None:
    """Scatter cracks and small stones on floor tiles.

    Tiles in *skip* are excluded (they get their detail from the
    smooth-shape renderer instead).
    """
    rng = random.Random(seed + 99)
    _skip = skip or set()
    cracks: list[str] = []
    stones: list[str] = []
    scratches: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            if not _is_floor(level, x, y):
                continue
            if (x, y) in _skip:
                # Consume RNG to keep deterministic sequence
                _tile_detail(rng, x, y, seed, [], [], [])
                continue
            _tile_detail(rng, x, y, seed, cracks, stones, scratches)

    _emit_detail(svg, cracks, stones, scratches)


def _wobble_line(
    rng: random.Random, x0: float, y0: float,
    x1: float, y1: float, seed: int, n_seg: int = 4,
) -> str:
    """Build a wobbly SVG path segment from (x0,y0) to (x1,y1).

    Uses Perlin noise to displace intermediate points perpendicular
    to the line direction, giving an organic hand-scratched look.
    """
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 0.1:
        return f"M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}"
    # Unit perpendicular
    nx, ny = -dy / length, dx / length
    wobble = length * 0.12
    parts = [f"M{x0:.1f},{y0:.1f}"]
    for i in range(1, n_seg + 1):
        t = i / n_seg
        mx = x0 + dx * t
        my = y0 + dy * t
        if i < n_seg:  # don't wobble the endpoint
            w = _noise.pnoise2(
                mx * 0.15 + seed, my * 0.15, base=77) * wobble
            w += rng.uniform(-wobble * 0.3, wobble * 0.3)
            mx += nx * w
            my += ny * w
        parts.append(f"L{mx:.1f},{my:.1f}")
    return " ".join(parts)


def _edge_point(
    rng: random.Random, edge: int, px: float, py: float,
) -> tuple[float, float]:
    """Random point on a tile edge. Edges: 0=top, 1=right, 2=bottom, 3=left."""
    t = rng.uniform(0.15, 0.85)
    if edge == 0:
        return (px + t * CELL, py)
    if edge == 1:
        return (px + CELL, py + t * CELL)
    if edge == 2:
        return (px + t * CELL, py + CELL)
    return (px, py + t * CELL)


def _y_scratch(
    rng: random.Random, px: float, py: float,
    gx: int, gy: int, seed: int,
) -> str:
    """Y-shaped scratch with all 3 ends on tile edges.

    Picks 3 points on different tile edges, a fork point inside the
    tile, and draws 3 wobbly lines from the fork to each edge point.
    """
    # Pick 3 distinct edges
    edges = rng.sample([0, 1, 2, 3], 3)
    p0 = _edge_point(rng, edges[0], px, py)
    p1 = _edge_point(rng, edges[1], px, py)
    p2 = _edge_point(rng, edges[2], px, py)

    # Fork point: weighted average biased toward tile center
    # with some random jitter
    cx = (p0[0] + p1[0] + p2[0]) / 3
    cy = (p0[1] + p1[1] + p2[1]) / 3
    # Pull toward tile center and add jitter
    tc_x = px + CELL * 0.5
    tc_y = py + CELL * 0.5
    fx = cx * 0.4 + tc_x * 0.6 + rng.uniform(-CELL * 0.1, CELL * 0.1)
    fy = cy * 0.4 + tc_y * 0.6 + rng.uniform(-CELL * 0.1, CELL * 0.1)

    # Build 3 wobbly branches from fork to each edge point
    ns = seed + gx * 7 + gy
    b0 = _wobble_line(rng, fx, fy, p0[0], p0[1], ns, 4)
    b1 = _wobble_line(rng, fx, fy, p1[0], p1[1], ns + 13, 4)
    b2 = _wobble_line(rng, fx, fy, p2[0], p2[1], ns + 29, 4)

    sw = rng.uniform(0.3, 0.7)
    return (
        f'<path d="{b0} {b1} {b2}" '
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{sw:.1f}" '
        f'stroke-linecap="round"/>')


def _floor_stone(rng: random.Random, px: float, py: float) -> str:
    """Single floor stone ellipse — original small size, brown fill."""
    sx = px + rng.uniform(CELL * 0.25, CELL * 0.75)
    sy = py + rng.uniform(CELL * 0.25, CELL * 0.75)
    rx = rng.uniform(2, CELL * 0.15)
    ry = rng.uniform(2, CELL * 0.12)
    angle = rng.uniform(0, 180)
    sw = rng.uniform(1.2, 2.0)
    return (
        f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
        f'rx="{rx:.1f}" ry="{ry:.1f}" '
        f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
        f'fill="{FLOOR_STONE_FILL}" '
        f'stroke="{FLOOR_STONE_STROKE}" '
        f'stroke-width="{sw:.1f}"/>')


def _render_smooth_floor_fills(svg: list[str], level: "Level") -> None:
    """Fill smooth-shaped rooms with BG color over the hatching layer.

    The hatching pass covers the full map area; this paints over it
    inside non-rect rooms so the floor is clean before walls are drawn.
    """
    fills: list[str] = []
    for room in level.rooms:
        outline = _room_svg_outline(room)
        if not outline:
            continue
        # Replace the closing /> with fill attribute
        el = outline.replace(
            '/>',
            f' fill="{BG}" stroke="none"/>')
        fills.append(el)
    if fills:
        svg.append(f'<g>{"".join(fills)}</g>')


def _render_smooth_floor_grid(
    svg: list[str], level: "Level", seed: int = 0,
) -> None:
    """Draw floor grid and detail inside smooth-shaped rooms.

    Uses SVG clip paths to extend the wobbly grid and floor detail
    (cracks, stones, scratches) to the smooth shape boundary.
    Reuses the same helpers as the tile-based renderer.
    """
    rooms_with_outlines: list[tuple] = []
    for room in level.rooms:
        outline = _room_svg_outline(room)
        if outline:
            rooms_with_outlines.append((room, outline))

    if not rooms_with_outlines:
        return

    grid_rng = random.Random(41)
    detail_rng = random.Random(seed + 99)

    for idx, (room, outline) in enumerate(rooms_with_outlines):
        r = room.rect
        clip_id = f"smooth-clip-{idx}"

        clip_el = outline.replace('/>', ' fill="white"/>')
        svg.append(
            f'<defs><clipPath id="{clip_id}">'
            f'{clip_el}</clipPath></defs>')

        # Per-tile-edge grid segments spanning the bounding rect,
        # clipped to the shape. Same short segments as the tile-based
        # grid so wobble and gaps look identical.
        segments: list[str] = []
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                px, py = x * CELL, y * CELL
                # Right edge (vertical)
                if x + 1 < r.x2:
                    segments.append(_wobbly_grid_seg(
                        grid_rng,
                        px + CELL, py, px + CELL, py + CELL,
                        x * 0.7, y * 0.7, base=20,
                    ))
                # Bottom edge (horizontal)
                if y + 1 < r.y2:
                    segments.append(_wobbly_grid_seg(
                        grid_rng,
                        px, py + CELL, px + CELL, py + CELL,
                        x * 0.3, y * 0.7, base=24,
                    ))

        if segments:
            svg.append(
                f'<path d="{" ".join(segments)}" fill="none" '
                f'stroke="{INK}" stroke-width="{GRID_WIDTH}" '
                f'opacity="0.7" stroke-linecap="round" '
                f'clip-path="url(#{clip_id})"/>')

        # Floor detail (cracks, stones, scratches) clipped
        cracks: list[str] = []
        stones: list[str] = []
        scratches: list[str] = []
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                _tile_detail(
                    detail_rng, x, y, seed,
                    cracks, stones, scratches,
                )

        # Wrap detail in a clipped group
        detail_els: list[str] = []
        if cracks:
            crack_lines = "".join(
                f'<line x1="{c.split()[0].split(",")[0]}" '
                f'y1="{c.split()[0].split(",")[1]}" '
                f'x2="{c.split()[1].split(",")[0]}" '
                f'y2="{c.split()[1].split(",")[1]}" '
                f'stroke="{INK}" stroke-width="0.5" '
                f'stroke-linecap="round"/>'
                for c in cracks
            )
            detail_els.append(f'<g opacity="0.5">{crack_lines}</g>')
        if scratches:
            detail_els.append(
                f'<g opacity="0.45">{"".join(scratches)}</g>')
        if stones:
            detail_els.append(
                f'<g opacity="0.8">{"".join(stones)}</g>')
        if detail_els:
            svg.append(
                f'<g clip-path="url(#{clip_id})">'
                f'{"".join(detail_els)}</g>')


def _render_walls(svg: list[str], level: "Level") -> None:
    """Render walls around rooms and corridors.

    Rooms with smooth geometric shapes (circle, hex, octagon) get
    proper SVG outlines (ellipse, polygon).  All other walls use
    tile-edge segments like terminal box-drawing.
    """
    from nhc.dungeon.model import RectShape

    # Collect floor tiles belonging to smooth-outlined rooms so
    # we can skip their tile-edge walls
    smooth_tiles: set[tuple[int, int]] = set()
    smooth_outlines: list[str] = []
    for room in level.rooms:
        outline = _room_svg_outline(room)
        if outline:
            smooth_outlines.append(outline)
            smooth_tiles |= room.floor_tiles()

    # Draw smooth room outlines
    if smooth_outlines:
        styled = []
        for el in smooth_outlines:
            # Add fill="none" stroke attributes to each element
            el = el.replace('/>',
                f' fill="none" stroke="{INK}" '
                f'stroke-width="{WALL_WIDTH}" '
                f'stroke-linecap="round" '
                f'stroke-linejoin="round"/>')
            styled.append(el)
        svg.append(f'<g>{"".join(styled)}</g>')

    # Tile-edge walls for corridors, doors, and rect rooms
    segments: list[str] = []

    def _walkable(x: int, y: int) -> bool:
        return _is_floor(level, x, y) or _is_door(level, x, y)

    for y in range(level.height):
        for x in range(level.width):
            if not _walkable(x, y):
                continue
            # Skip tiles that belong to a smooth-outlined room,
            # UNLESS the neighbor is a corridor or door (we still
            # need those connection edges)
            if (x, y) in smooth_tiles:
                # Only draw edges where this tile meets a corridor
                # or another room — skip edges facing void/wall
                # (those are covered by the smooth outline)
                px, py = x * CELL, y * CELL
                for nx, ny, seg in [
                    (x, y - 1, f'M{px},{py} L{px + CELL},{py}'),
                    (x, y + 1,
                     f'M{px},{py + CELL} L{px + CELL},{py + CELL}'),
                    (x - 1, y, f'M{px},{py} L{px},{py + CELL}'),
                    (x + 1, y,
                     f'M{px + CELL},{py} L{px + CELL},{py + CELL}'),
                ]:
                    nb = level.tile_at(nx, ny)
                    if nb and nb.is_corridor and not _walkable(nx, ny):
                        segments.append(seg)
                continue

            px, py = x * CELL, y * CELL
            # Top edge
            if not _walkable(x, y - 1):
                segments.append(f'M{px},{py} L{px + CELL},{py}')
            # Bottom edge
            if not _walkable(x, y + 1):
                segments.append(
                    f'M{px},{py + CELL} L{px + CELL},{py + CELL}')
            # Left edge
            if not _walkable(x - 1, y):
                segments.append(f'M{px},{py} L{px},{py + CELL}')
            # Right edge
            if not _walkable(x + 1, y):
                segments.append(
                    f'M{px + CELL},{py} L{px + CELL},{py + CELL}')

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )


def _render_stairs(svg: list[str], level: "Level") -> None:
    """Render stairs as tapering wedges with parallel step lines.

    Classic dungeon map convention: steps taper in the direction of
    descent. Wide end = current level, narrow end = where stairs go.

    stairs_down (>) : wide on left, narrows to right
    stairs_up   (<) : wide on right, narrows to left
    """
    rail_sw = 1.5
    step_sw = 1.0
    n_steps = 5

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature not in ("stairs_down", "stairs_up"):
                continue

            px, py = x * CELL, y * CELL
            m = CELL * 0.1  # margin from tile edge
            down = tile.feature == "stairs_down"
            cx = px + CELL / 2
            cy = py + CELL / 2

            # Wide end half-height and narrow end half-height
            wide_h = CELL * 0.4
            narrow_h = CELL * 0.1

            if down:
                # Wide on left, narrow on right
                left_x = px + m
                right_x = px + CELL - m
                # Top rail: top-left → top-right (tapering)
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy - wide_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy - narrow_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Bottom rail
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy + wide_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy + narrow_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Step lines (vertical, between the rails)
                span = right_x - left_x
                for i in range(n_steps + 1):
                    t = i / n_steps
                    sx = left_x + span * t
                    half = wide_h + (narrow_h - wide_h) * t
                    svg.append(
                        f'<line x1="{sx:.1f}" '
                        f'y1="{cy - half:.1f}" '
                        f'x2="{sx:.1f}" '
                        f'y2="{cy + half:.1f}" '
                        f'stroke="{INK}" stroke-width="{step_sw}" '
                        f'stroke-linecap="round"/>')
            else:
                # Wide on right, narrow on left
                left_x = px + m
                right_x = px + CELL - m
                # Top rail
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy - narrow_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy - wide_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Bottom rail
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy + narrow_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy + wide_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Step lines
                span = right_x - left_x
                for i in range(n_steps + 1):
                    t = i / n_steps
                    sx = left_x + span * t
                    half = narrow_h + (wide_h - narrow_h) * t
                    svg.append(
                        f'<line x1="{sx:.1f}" '
                        f'y1="{cy - half:.1f}" '
                        f'x2="{sx:.1f}" '
                        f'y2="{cy + half:.1f}" '
                        f'stroke="{INK}" stroke-width="{step_sw}" '
                        f'stroke-linecap="round"/>')


# ── Hatching ─────────────────────────────────────────────────────

def _render_hatching(
    svg: list[str], level: "Level", seed: int,
) -> None:
    """Procedural cross-hatching around the dungeon perimeter.

    Uses Shapely for geometry clipping, Perlin noise for organic
    displacement, and tile-based section partitioning.
    """
    random.seed(seed)
    dungeon_poly = _build_dungeon_polygon(level)
    if dungeon_poly.is_empty:
        return

    # Buffer the polygon outward by half the wall width so hatching
    # starts right outside the wall line, not overlapping it
    wall_buffer = WALL_WIDTH
    hatching_boundary = dungeon_poly.buffer(wall_buffer)

    base_distance_limit = 2.0 * CELL
    min_stroke = 1.0
    max_stroke = 1.8

    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gy in range(-1, level.height + 1):
        for gx in range(-1, level.width + 1):
            center = Point((gx + 0.5) * CELL, (gy + 0.5) * CELL)
            if hatching_boundary.contains(center):
                continue
            dist = hatching_boundary.boundary.distance(center)

            # Irregular contour: vary distance limit per tile with
            # Perlin noise so the hatching edge flows organically
            noise_var = _noise.pnoise2(
                gx * 0.3, gy * 0.3, base=50) * CELL * 0.8
            tile_limit = base_distance_limit + noise_var
            if dist > tile_limit:
                continue

            # Random discontinuities: skip ~10% of edge tiles
            if dist > base_distance_limit * 0.5 and random.random() < 0.10:
                continue

            # Grey underlay tile
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')

            # Scatter 0-2 stones of varying sizes in this tile
            n_stones = random.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
            for _ in range(n_stones):
                sx = (gx + random.uniform(0.15, 0.85)) * CELL
                sy = (gy + random.uniform(0.15, 0.85)) * CELL
                rx = random.uniform(2, CELL * 0.25)
                ry = random.uniform(2, CELL * 0.2)
                angle = random.uniform(0, 180)
                sw = random.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                    f'stroke-width="{sw:.1f}"/>')

            # Perlin-displaced cluster anchor
            nr = CELL * 0.1
            dx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
            dy = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
            anchor = ((gx + 0.5) * CELL + dx, (gy + 0.5) * CELL + dy)

            corners = [
                (gx * CELL, gy * CELL),
                ((gx + 1) * CELL, gy * CELL),
                ((gx + 1) * CELL, (gy + 1) * CELL),
                (gx * CELL, (gy + 1) * CELL),
            ]

            # Pick 3 random perimeter points to partition tile
            pts = _pick_section_points(corners, anchor, CELL)
            sections = _build_sections(anchor, pts, corners)

            for i, section in enumerate(sections):
                if section.is_empty or section.area < 1:
                    continue
                if i == 0:
                    angle = math.atan2(
                        pts[1][1] - pts[0][1],
                        pts[1][0] - pts[0][0])
                else:
                    angle = random.uniform(0, math.pi)

                bounds = section.bounds
                diag = math.hypot(
                    bounds[2] - bounds[0], bounds[3] - bounds[1])
                spacing = CELL * 0.20
                n_lines = max(3, int(diag / spacing))

                for j in range(n_lines):
                    offset = (j - (n_lines - 1) / 2) * spacing
                    cx = section.centroid.x
                    cy = section.centroid.y
                    perp_x = math.cos(angle + math.pi / 2) * offset
                    perp_y = math.sin(angle + math.pi / 2) * offset
                    line = LineString([
                        (cx + perp_x - math.cos(angle) * diag,
                         cy + perp_y - math.sin(angle) * diag),
                        (cx + perp_x + math.cos(angle) * diag,
                         cy + perp_y + math.sin(angle) * diag),
                    ])
                    clipped = section.intersection(line)
                    if clipped.is_empty or not isinstance(clipped, LineString):
                        continue
                    p1, p2 = list(clipped.coords)
                    # Perlin wobble
                    wb = CELL * 0.03
                    p1 = (
                        p1[0] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=10) * wb,
                        p1[1] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=11) * wb,
                    )
                    p2 = (
                        p2[0] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=12) * wb,
                        p2[1] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=13) * wb,
                    )
                    sw = random.uniform(min_stroke, max_stroke)
                    hatch_lines.append(
                        f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" '
                        f'x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
                        f'stroke="{INK}" stroke-width="{sw:.2f}" '
                        f'stroke-linecap="round"/>')

    # Render underlay first, then hatch lines on top
    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')


def _build_dungeon_polygon(level: "Level") -> Polygon:
    """Build a Shapely polygon covering all floor/door tiles."""
    from shapely.ops import unary_union
    polys = []
    for y in range(level.height):
        for x in range(level.width):
            if _is_floor(level, x, y) or _is_door(level, x, y):
                polys.append(Polygon([
                    (x * CELL, y * CELL),
                    ((x + 1) * CELL, y * CELL),
                    ((x + 1) * CELL, (y + 1) * CELL),
                    (x * CELL, (y + 1) * CELL),
                ]))
    if not polys:
        return Polygon()
    return unary_union(polys)


def _pick_section_points(
    corners: list[tuple[float, float]],
    anchor: tuple[float, float],
    grid_size: float,
) -> list[tuple[float, float]]:
    """Pick 3 random perimeter points and sort by angle from anchor."""

    def _random_perimeter_point(edge: int) -> tuple[float, float]:
        t = random.uniform(0, grid_size)
        if edge == 0:
            return (corners[0][0] + t, corners[0][1])
        if edge == 1:
            return (corners[1][0], corners[1][1] + t)
        if edge == 2:
            return (corners[2][0] - t, corners[2][1])
        return (corners[3][0], corners[3][1] - t)

    edges = [random.randint(0, 3) for _ in range(3)]
    pts = [_random_perimeter_point(e) for e in edges]
    pts.sort(key=lambda p: math.atan2(
        p[1] - anchor[1], p[0] - anchor[0]))
    return pts


def _get_edge_index(
    p: tuple[float, float],
    corners: list[tuple[float, float]],
    grid_size: float,
) -> int:
    gx_px = corners[0][0]
    gy_px = corners[0][1]
    if abs(p[1] - gy_px) < 1e-3:
        return 0
    if abs(p[0] - (gx_px + grid_size)) < 1e-3:
        return 1
    if abs(p[1] - (gy_px + grid_size)) < 1e-3:
        return 2
    return 3


def _build_sections(
    anchor: tuple[float, float],
    pts: list[tuple[float, float]],
    corners: list[tuple[float, float]],
) -> list[Polygon]:
    """Partition a tile into 3 sections from anchor through 3 perimeter points."""
    gs = corners[1][0] - corners[0][0]  # grid_size
    sections = []
    for i in range(3):
        p1 = pts[i]
        p2 = pts[(i + 1) % 3]
        verts = [anchor, p1]
        idx1 = _get_edge_index(p1, corners, gs)
        idx2 = _get_edge_index(p2, corners, gs)
        j = idx1
        while j != idx2:
            verts.append(corners[(j + 1) % 4])
            j = (j + 1) % 4
        verts.append(p2)
        try:
            poly = Polygon(verts)
            if poly.is_valid and poly.area > 0:
                sections.append(poly)
        except Exception:
            pass
    return sections
