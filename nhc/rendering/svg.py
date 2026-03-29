"""SVG floor renderer — Dyson Logos style.

Generates a static SVG image of a dungeon floor from nhc's Level model.
The SVG contains rooms, corridors, walls, doors, stairs, and decorative
hatching. No entities (player, creatures, items) — those are overlaid
by the browser client using the tileset.

Inspired by dmap's SVG renderer (ppdf/dmap_lib/rendering/).
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nhc.dungeon.model import Level, Tile

# ── Constants ────────────────────────────────────────────────────

CELL = 32          # pixels per grid cell
PADDING = 16       # padding around the map
WALL_WIDTH = 3.0   # wall stroke width
DOOR_WIDTH = 2.0   # door stroke width

# ── Colors (Dyson Logos palette) ─────────────────────────────────

BG_COLOR = "#EDE0CE"       # aged parchment
FLOOR_COLOR = "#FFFFFF"    # room interior
WALL_COLOR = "#000000"     # wall strokes
SHADOW_COLOR = "#999999"   # room shadow
CORRIDOR_COLOR = "#F5F0E8" # slightly off-white corridors
DOOR_COLOR = "#8B4513"     # brown doors
DOOR_LOCKED_COLOR = "#B22222"  # red locked doors
STAIRS_COLOR = "#555555"   # stair markers
WATER_COLOR = "#AEC6CF"    # water tiles
HATCH_COLOR = "#C0C0C0"    # exterior hatching


def render_floor_svg(level: "Level", seed: int = 0) -> str:
    """Generate a Dyson-style SVG for a dungeon floor.

    Args:
        level: The nhc Level to render.
        seed: RNG seed for hatching variation.

    Returns:
        Complete SVG string.
    """
    w = level.width * CELL + 2 * PADDING
    h = level.height * CELL + 2 * PADDING

    svg: list[str] = []
    svg.append(
        f'<svg width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )
    # Background
    svg.append(f'<rect width="100%" height="100%" fill="{BG_COLOR}"/>')

    # Content group with padding offset
    svg.append(f'<g transform="translate({PADDING},{PADDING})">')

    # Layer 1: Room shadows
    _render_room_shadows(svg, level)

    # Layer 2: Floor fills (rooms + corridors)
    _render_floors(svg, level)

    # Layer 3: Water/terrain
    _render_terrain(svg, level)

    # Layer 4: Walls
    _render_walls(svg, level)

    # Layer 5: Doors
    _render_doors(svg, level)

    # Layer 6: Stairs
    _render_stairs(svg, level)

    # Layer 7: Hatching around perimeter
    _render_hatching(svg, level, seed)

    svg.append("</g>")
    svg.append("</svg>")
    return "\n".join(svg)


# ── Layer renderers ──────────────────────────────────────────────

def _render_room_shadows(svg: list[str], level: "Level") -> None:
    """Render offset shadow rectangles for each room."""
    for room in level.rooms:
        r = room.rect
        x = r.x * CELL + 2
        y = r.y * CELL + 2
        svg.append(
            f'<rect x="{x}" y="{y}" '
            f'width="{r.width * CELL}" height="{r.height * CELL}" '
            f'fill="{SHADOW_COLOR}" opacity="0.3"/>'
        )


def _render_floors(svg: list[str], level: "Level") -> None:
    """Render floor tiles as small rectangles."""
    from nhc.dungeon.model import Terrain
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain == Terrain.FLOOR:
                color = CORRIDOR_COLOR if tile.is_corridor else FLOOR_COLOR
                svg.append(
                    f'<rect x="{x * CELL}" y="{y * CELL}" '
                    f'width="{CELL}" height="{CELL}" fill="{color}"/>'
                )


def _render_terrain(svg: list[str], level: "Level") -> None:
    """Render water and other terrain features."""
    from nhc.dungeon.model import Terrain
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain == Terrain.WATER:
                cx = x * CELL + CELL // 2
                cy = y * CELL + CELL // 2
                svg.append(
                    f'<rect x="{x * CELL}" y="{y * CELL}" '
                    f'width="{CELL}" height="{CELL}" '
                    f'fill="{WATER_COLOR}" opacity="0.6"/>'
                )
                # Ripple circles
                for r in (5, 9):
                    svg.append(
                        f'<circle cx="{cx}" cy="{cy}" r="{r}" '
                        f'fill="none" stroke="{WATER_COLOR}" '
                        f'stroke-width="0.5" opacity="0.4"/>'
                    )


def _render_walls(svg: list[str], level: "Level") -> None:
    """Render wall edges between floor and non-floor tiles.

    Draws line segments along tile boundaries where a floor tile
    meets a wall/void tile, producing clean wall outlines.
    """
    from nhc.dungeon.model import Terrain

    def _is_floor(x: int, y: int) -> bool:
        if not level.in_bounds(x, y):
            return False
        t = level.tiles[y][x]
        return t.terrain in (Terrain.FLOOR, Terrain.WATER)

    segments: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            if not _is_floor(x, y):
                continue
            px, py = x * CELL, y * CELL
            # Top edge
            if not _is_floor(x, y - 1):
                segments.append(
                    f'M{px},{py} L{px + CELL},{py}'
                )
            # Bottom edge
            if not _is_floor(x, y + 1):
                segments.append(
                    f'M{px},{py + CELL} L{px + CELL},{py + CELL}'
                )
            # Left edge
            if not _is_floor(x - 1, y):
                segments.append(
                    f'M{px},{py} L{px},{py + CELL}'
                )
            # Right edge
            if not _is_floor(x + 1, y):
                segments.append(
                    f'M{px + CELL},{py} L{px + CELL},{py + CELL}'
                )

    if segments:
        path_data = " ".join(segments)
        svg.append(
            f'<path d="{path_data}" fill="none" '
            f'stroke="{WALL_COLOR}" stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round"/>'
        )


def _render_doors(svg: list[str], level: "Level") -> None:
    """Render doors as colored rectangles."""
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not tile.feature:
                continue
            if tile.feature in ("door_closed", "door_open",
                                "door_secret", "door_locked"):
                px, py = x * CELL, y * CELL
                color = DOOR_LOCKED_COLOR if tile.feature == "door_locked" \
                    else DOOR_COLOR
                # Determine orientation: horizontal or vertical
                # A door is vertical if floor is to the left/right
                from nhc.dungeon.model import Terrain
                left_floor = (level.in_bounds(x - 1, y) and
                              level.tiles[y][x - 1].terrain == Terrain.FLOOR)
                right_floor = (level.in_bounds(x + 1, y) and
                               level.tiles[y][x + 1].terrain == Terrain.FLOOR)
                if left_floor or right_floor:
                    # Vertical door
                    dw, dh = CELL * 0.3, CELL * 0.8
                    dx = px + (CELL - dw) / 2
                    dy = py + (CELL - dh) / 2
                else:
                    # Horizontal door
                    dw, dh = CELL * 0.8, CELL * 0.3
                    dx = px + (CELL - dw) / 2
                    dy = py + (CELL - dh) / 2
                svg.append(
                    f'<rect x="{dx:.1f}" y="{dy:.1f}" '
                    f'width="{dw:.1f}" height="{dh:.1f}" '
                    f'fill="{color}" stroke="{WALL_COLOR}" '
                    f'stroke-width="{DOOR_WIDTH}" rx="2"/>'
                )


def _render_stairs(svg: list[str], level: "Level") -> None:
    """Render stair markers."""
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature in ("stairs_down", "stairs_up"):
                px, py = x * CELL, y * CELL
                cx, cy = px + CELL // 2, py + CELL // 2
                # Draw stair lines
                going_down = tile.feature == "stairs_down"
                for i in range(3):
                    offset = (i - 1) * 6
                    y1 = cy + offset - 3
                    y2 = cy + offset + 3
                    x1 = cx - 8
                    x2 = cx + 8
                    if going_down:
                        svg.append(
                            f'<line x1="{x1}" y1="{y1}" '
                            f'x2="{x2}" y2="{y1}" '
                            f'stroke="{STAIRS_COLOR}" '
                            f'stroke-width="1.5"/>'
                        )
                    else:
                        svg.append(
                            f'<line x1="{x1}" y1="{y2}" '
                            f'x2="{x2}" y2="{y2}" '
                            f'stroke="{STAIRS_COLOR}" '
                            f'stroke-width="1.5"/>'
                        )
                # Arrow indicator
                if going_down:
                    svg.append(
                        f'<polygon points="{cx},{cy + 10} '
                        f'{cx - 4},{cy + 5} {cx + 4},{cy + 5}" '
                        f'fill="{STAIRS_COLOR}"/>'
                    )
                else:
                    svg.append(
                        f'<polygon points="{cx},{cy - 10} '
                        f'{cx - 4},{cy - 5} {cx + 4},{cy - 5}" '
                        f'fill="{STAIRS_COLOR}"/>'
                    )


def _render_hatching(
    svg: list[str], level: "Level", seed: int,
) -> None:
    """Render cross-hatching around the dungeon perimeter.

    Draws short random lines in void tiles adjacent to floor tiles,
    giving the Dyson Logos hand-drawn border effect.
    """
    from nhc.dungeon.model import Terrain
    rng = random.Random(seed)

    perimeter: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain not in (Terrain.WALL, Terrain.VOID):
                continue
            # Check if adjacent to floor
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if level.in_bounds(nx, ny):
                    neighbor = level.tiles[ny][nx]
                    if neighbor.terrain in (Terrain.FLOOR, Terrain.WATER):
                        perimeter.add((x, y))
                        break

    lines: list[str] = []
    for px, py in perimeter:
        cx = px * CELL + CELL // 2
        cy = py * CELL + CELL // 2
        n_lines = rng.randint(2, 5)
        for _ in range(n_lines):
            angle = rng.uniform(0, math.pi)
            length = rng.uniform(4, CELL * 0.6)
            dx = math.cos(angle) * length / 2
            dy = math.sin(angle) * length / 2
            ox = rng.uniform(-4, 4)
            oy = rng.uniform(-4, 4)
            x1 = cx + ox - dx
            y1 = cy + oy - dy
            x2 = cx + ox + dx
            y2 = cy + oy + dy
            lines.append(f'M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}')

    if lines:
        path_data = " ".join(lines)
        svg.append(
            f'<path d="{path_data}" fill="none" '
            f'stroke="{HATCH_COLOR}" stroke-width="1" '
            f'stroke-linecap="round" opacity="0.6"/>'
        )
