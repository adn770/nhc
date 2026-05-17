"""SVG helpers retained for the future authoring tool.

NIR-only: the game renders floors browser-side from the NIR. This
module survives as two narrow entry points:

* :func:`render_floor_svg_from_ir` — a thin shim that builds the
  floor IR and rasterises it via the Rust ``ir_to_svg``. Kept so an
  authoring tool (and the legacy SVG-shape tests) can obtain a
  floor SVG without going through the web server.
* :func:`render_hatch_svg` — generates the tileable Dyson
  cross-hatch patch used by the offline ``gen_hatch_pattern`` tool
  (Shapely geometry + Perlin noise for organic strokes).
"""

from __future__ import annotations

import math
import random

from nhc.rendering import _perlin as _noise
from shapely.geometry import LineString

from nhc.rendering._svg_helpers import BG, CELL, HATCH_UNDERLAY, INK


def render_floor_svg_from_ir(
    level: "Level", seed: int = 0, hatch_distance: float = 2.0,
    building_footprint: set[tuple[int, int]] | None = None,
    building_polygon: list[tuple[float, float]] | None = None,
) -> str:
    """Generate a Dyson-style SVG for a dungeon floor.

    *hatch_distance* controls how far (in tiles) the cross-hatching
    extends from the dungeon perimeter.  Default 2.0 gives the full
    Dyson look; lower values (e.g. 1.0) reduce SVG complexity and
    rendering time significantly.

    Cave levels always use at least 2 tiles of hatch extent — the
    wider grey halo is a defining feature of the Dyson cavern style
    and matters more than render-time savings at that theme.

    *building_footprint* is the set of tiles that lie INSIDE the
    enclosing Building's shape (octagon, circle, ...). When set,
    the IR emitter skips tile-edge wall segments where the void
    neighbour sits OUTSIDE the footprint so the smooth-shape
    ExteriorWallOp owns the chamfer outline. Pass ``None`` (or
    omit) for a non-building level (dungeon floor, town surface,
    ...).

    *building_polygon* is the pixel-space outer outline of the
    enclosing Building (level-local coords, no PADDING) forwarded
    to the IR emitter so a wooden tower's planks reach the chamfer
    diagonal rather than the bbox edge.

    This is a thin shim: it builds the floor IR and rasterises it
    via the Rust ``ir_to_svg``. There is no Python SVG path left.
    """
    import nhc_render
    from nhc.rendering.ir_emitter import build_floor_ir

    buf = build_floor_ir(
        level,
        seed=seed,
        hatch_distance=hatch_distance,
        building_footprint=building_footprint,
        building_polygon=building_polygon,
    )
    return nhc_render.ir_to_svg(bytes(buf))


HATCH_PATCH_SIZE = 16  # tiles per side of the repeating hatch patch


def render_hatch_svg(seed: int = 0) -> str:
    """Generate a small tileable hatching SVG patch.

    Produces an 8x8 tile patch of Dyson-style cross-hatching that
    the web client stamps across the full hatch canvas using
    createPattern.  Typically under 100 KB.
    """
    size = HATCH_PATCH_SIZE
    w = size * CELL
    h = size * CELL

    svg: list[str] = []
    svg.append(
        f'<svg width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )
    svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')

    rng = random.Random(seed + 77)

    min_stroke = 1.0
    max_stroke = 1.8
    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gy in range(size):
        for gx in range(size):
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')

            n_stones = rng.choices(
                [0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
            for _ in range(n_stones):
                sx = (gx + rng.uniform(0.15, 0.85)) * CELL
                sy = (gy + rng.uniform(0.15, 0.85)) * CELL
                rx = rng.uniform(2, CELL * 0.25)
                ry = rng.uniform(2, CELL * 0.2)
                angle = rng.uniform(0, 180)
                sw = rng.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},'
                    f'{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                    f'stroke-width="{sw:.1f}"/>')

            nr = CELL * 0.1
            adx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
            ady = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
            anchor = ((gx + 0.5) * CELL + adx,
                      (gy + 0.5) * CELL + ady)

            corners = [
                (gx * CELL, gy * CELL),
                ((gx + 1) * CELL, gy * CELL),
                ((gx + 1) * CELL, (gy + 1) * CELL),
                (gx * CELL, (gy + 1) * CELL),
            ]

            pts = _pick_section_points(corners, anchor, CELL, rng)
            sections = _build_sections(anchor, pts, corners)

            for i, section in enumerate(sections):
                if section.is_empty or section.area < 1:
                    continue
                if i == 0:
                    a = math.atan2(
                        pts[1][1] - pts[0][1],
                        pts[1][0] - pts[0][0])
                else:
                    a = rng.uniform(0, math.pi)

                bounds = section.bounds
                diag = math.hypot(
                    bounds[2] - bounds[0], bounds[3] - bounds[1])
                spacing = CELL * 0.20
                n_lines = max(3, int(diag / spacing))

                for j in range(n_lines):
                    offset = (j - (n_lines - 1) / 2) * spacing
                    scx = section.centroid.x
                    scy = section.centroid.y
                    perp_x = math.cos(a + math.pi / 2) * offset
                    perp_y = math.sin(a + math.pi / 2) * offset
                    line = LineString([
                        (scx + perp_x - math.cos(a) * diag,
                         scy + perp_y - math.sin(a) * diag),
                        (scx + perp_x + math.cos(a) * diag,
                         scy + perp_y + math.sin(a) * diag),
                    ])
                    clipped = section.intersection(line)
                    if (clipped.is_empty
                            or not isinstance(clipped, LineString)):
                        continue
                    p1, p2 = list(clipped.coords)
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
                    lsw = rng.uniform(min_stroke, max_stroke)
                    hatch_lines.append(
                        f'<line x1="{p1[0]:.1f}" '
                        f'y1="{p1[1]:.1f}" '
                        f'x2="{p2[0]:.1f}" '
                        f'y2="{p2[1]:.1f}" '
                        f'stroke="{INK}" '
                        f'stroke-width="{lsw:.2f}" '
                        f'stroke-linecap="round"/>')

    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')

    svg.append("</svg>")
    return "\n".join(svg)


# render_hatch_svg's only collaborators. Imported here (not at the
# top) so the module's public surface — render_floor_svg_from_ir (the IR
# shim) and render_hatch_svg — reads first; the legacy re-export
# blocks for the pre-IR renderer were removed with the NIR-only
# migration.
from nhc.rendering._dungeon_polygon import (  # noqa: E402
    _build_sections,
    _pick_section_points,
)



