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

from nhc.rendering import _perlin as _noise
from shapely.geometry import LineString

from nhc.dungeon.generators.cellular import CaveShape
from nhc.rendering._floor_layers import FLOOR_LAYERS
from nhc.rendering._pipeline import render_layers
from nhc.rendering._render_context import build_render_context
from nhc.rendering._svg_helpers import (
    BG,
    CAVE_FLOOR_COLOR,
    CELL,
    FLOOR_COLOR,
    FLOOR_STONE_FILL,
    FLOOR_STONE_STROKE,
    GRID_WIDTH,
    HATCH_UNDERLAY,
    INK,
    PADDING,
    PILL_ARC_SEGMENTS,
    TEMPLE_ARC_SEGMENTS,
    WALL_THIN,
    WALL_WIDTH,
    _edge_point,
    _find_doorless_openings,
    _is_door,
    _is_floor,
    _wobble_line,
    _wobbly_grid_seg,
    _y_scratch,
)
from nhc.rendering._room_outlines import (  # noqa: E402
    _circle_with_gaps,
    _gap_on_edge,
    _half_outline,
    _hybrid_svg_outline,
    _hybrid_vertices,
    _intersect_circle,
    _intersect_hybrid,
    _intersect_line_seg,
    _intersect_outline,
    _intersect_polygon_edges,
    _outline_with_gaps,
    _pill_vertices,
    _point_on_segment,
    _polygon_vertices,
    _polygon_with_gaps,
    _room_svg_outline,
    _temple_vertices,
)


def render_floor_svg(
    level: "Level", seed: int = 0, hatch_distance: float = 2.0,
    building_footprint: set[tuple[int, int]] | None = None,
    building_polygon: list[tuple[float, float]] | None = None,
    vegetation: bool = True,
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
    the wall pass skips tile-edge segments where the void
    neighbour sits OUTSIDE the footprint -- those chamfer steps
    are owned by the diagonal masonry renderer in
    :mod:`nhc.rendering._building_walls`. Pass ``None`` (or omit)
    when rendering a non-building level (dungeon floor, town
    surface, ...) and the legacy "all tile-edge walls" pass
    runs unchanged.

    *building_polygon* is the pixel-space outer outline of the
    enclosing Building (level-local coords, no PADDING). When
    set, the wood-floor renderer clips its fill to this polygon
    instead of stopping at the rect-aligned tile boundaries, so
    a wooden tower's planks visually reach the chamfer diagonal
    rather than the bbox edge.

    Phase 1.n of the IR migration rewires this entry to route
    through ``ir_to_svg(build_floor_ir(...))``. Every legacy
    code path (wood floor, decorator pipeline, surface features,
    inactive-layer gating) flows through the IR pipeline; the
    legacy ``_*_paint`` helpers stay alive because the IR emit
    shells call into them for Phase 1's transitional passthroughs.
    Phase 4 deletes them after the Rust ports.
    """
    from nhc.rendering.ir_emitter import build_floor_ir
    from nhc.rendering.ir_to_svg import ir_to_svg

    buf = build_floor_ir(
        level,
        seed=seed,
        hatch_distance=hatch_distance,
        building_footprint=building_footprint,
        building_polygon=building_polygon,
        vegetation=vegetation,
    )
    return ir_to_svg(buf)


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


from nhc.rendering._dungeon_polygon import (  # noqa: E402
    _approximate_arc,
    _build_dungeon_polygon,
    _build_sections,
    _get_edge_index,
    _pick_section_points,
    _room_shapely_polygon,
    _svg_path_to_polygon,
)
from nhc.rendering._shadows import (  # noqa: E402
    _render_corridor_shadows,
    _render_room_shadows,
    _room_shadow_svg,
)
from nhc.rendering._cave_geometry import (  # noqa: E402
    _build_cave_polygon,
    _build_cave_wall_geometry,
    _cave_region_walls,
    _cave_svg_outline,
    _centripetal_bezier_cps,
    _collect_cave_region,
    _densify_ring,
    _jitter_ring_outward,
    _ring_to_subpath,
    _smooth_closed_path,
    _smooth_open_path,
    _trace_cave_boundary_coords,
)
from nhc.rendering._hatching import (  # noqa: E402
    _render_corridor_hatching,
    _render_hatching,
    _render_hole_hatching,
)

from nhc.rendering._floor_detail import (  # noqa: E402
    _DETAIL_SCALE,
    _TERRAIN_TYPES,
    _THEMATIC_DEFAULT,
    _THEMATIC_DETAIL_PROBS,
    _bone_detail,
    _dungeon_interior_clip,
    _emit_detail,
    _emit_thematic_detail,
    _floor_stone,
    _render_floor_detail,
    _render_floor_grid,
    _skull_detail,
    _tile_detail,
    _tile_thematic_detail,
    _web_detail,
)
from nhc.rendering._terrain_detail import (  # noqa: E402
    _chasm_detail,
    _lava_detail,
    _render_terrain_detail,
    _render_terrain_tints,
    _water_detail,
)
from nhc.rendering._walls_floors import (  # noqa: E402
    _render_walls_and_floors,
)
from nhc.rendering._stairs_svg import _render_stairs  # noqa: E402


