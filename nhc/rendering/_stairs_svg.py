"""Stair wedge rendering for SVG dungeons."""

from __future__ import annotations

from nhc.dungeon.model import Level
from nhc.rendering._svg_helpers import CELL, INK

STAIR_FILL = "#E0E0E0"  # bright grey fill for stairs in caves


def _render_stairs(svg: list[str], level: Level) -> None:
    """Render stairs as tapering wedges with parallel step lines.

    Classic dungeon map convention: steps taper in the direction of
    descent. Wide end = current level, narrow end = where stairs go.

    stairs_down (>) : wide on left, narrows to right
    stairs_up   (<) : wide on right, narrows to left
    """
    rail_sw = 1.5
    step_sw = 1.0
    n_steps = 5
    theme = (level.metadata.theme
             if level.metadata else "dungeon")

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

            # In caves, fill the stair trapezoid with bright grey
            # so stairs stand out against the brown cave floor.
            if theme == "cave":
                left_x = px + m
                right_x = px + CELL - m
                if down:
                    pts = (f'{left_x:.1f},{cy - wide_h:.1f} '
                           f'{right_x:.1f},{cy - narrow_h:.1f} '
                           f'{right_x:.1f},{cy + narrow_h:.1f} '
                           f'{left_x:.1f},{cy + wide_h:.1f}')
                else:
                    pts = (f'{left_x:.1f},{cy - narrow_h:.1f} '
                           f'{right_x:.1f},{cy - wide_h:.1f} '
                           f'{right_x:.1f},{cy + wide_h:.1f} '
                           f'{left_x:.1f},{cy + narrow_h:.1f}')
                svg.append(
                    f'<polygon points="{pts}" '
                    f'fill="{STAIR_FILL}" stroke="none"/>')

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
