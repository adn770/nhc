"""Room and corridor shadow rendering for SVG dungeons."""

from __future__ import annotations

from nhc.dungeon.model import Level, Room, SurfaceType
from nhc.rendering._svg_helpers import CELL, INK, _is_door


def _room_shadow_svg(room: Room) -> str:
    """Return an SVG element for a room's shadow.

    Reuses _room_svg_outline for non-rect shapes, applying fill
    and a (3,3) offset.  Rect rooms get a simple rect shadow.
    """
    # Import here to avoid circular dependency — _room_outlines
    # also uses helpers from _svg_helpers.
    from nhc.rendering.svg import _room_svg_outline

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


def _render_room_shadows(svg: list[str], level: Level) -> None:
    """Subtle offset shadow for rooms (shape-aware)."""
    for room in level.rooms:
        svg.append(_room_shadow_svg(room))


def _render_corridor_shadows(svg: list[str], level: Level) -> None:
    """Per-tile offset shadow for corridor and door tiles."""
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (tile.surface_type == SurfaceType.CORRIDOR
                    or _is_door(level, x, y)):
                continue
            px, py = x * CELL + 3, y * CELL + 3
            svg.append(
                f'<rect x="{px}" y="{py}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{INK}" opacity="0.08"/>')
