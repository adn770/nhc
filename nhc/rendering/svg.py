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
import re
import noise as _noise
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient as _shapely_orient
from shapely.ops import unary_union

from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, Level,
    OctagonShape, PillShape, Rect, RectShape, Room,
    TempleShape, Terrain,
)
from nhc.dungeon.generators.cellular import CaveShape
from nhc.rendering.terrain_palette import (
    ROOM_TYPE_TINTS, get_palette,
)
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
) -> str:
    """Generate a Dyson-style SVG for a dungeon floor.

    *hatch_distance* controls how far (in tiles) the cross-hatching
    extends from the dungeon perimeter.  Default 2.0 gives the full
    Dyson look; lower values (e.g. 1.0) reduce SVG complexity and
    rendering time significantly.

    Cave levels always use at least 2 tiles of hatch extent — the
    wider grey halo is a defining feature of the Dyson cavern style
    and matters more than render-time savings at that theme.
    """
    if any(isinstance(r.shape, CaveShape) for r in level.rooms):
        hatch_distance = max(hatch_distance, 2.0)
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

    # Build the unified cave region geometry once: the SVG wall
    # path, the matching jittered wall polygon (clip/fill), and
    # the set of cave-region tiles.  Computed here so the polygon
    # can feed both the dungeon clip (hatching, grid, detail) and
    # the floor/wall renderer.
    cave_rng = random.Random(seed + 0x5A17E5)
    cave_wall_path, cave_wall_poly, cave_tiles = (
        _build_cave_wall_geometry(level, cave_rng)
    )

    # Build dungeon polygon once — used for hatching and grid clips
    dungeon_poly = _build_dungeon_polygon(
        level, cave_wall_poly=cave_wall_poly,
        cave_tiles=cave_tiles,
    )

    # Layer 1: Shadows (rooms + corridors)
    _render_room_shadows(svg, level)
    _render_corridor_shadows(svg, level)

    # Layer 2: Hatching (rooms clipped to exterior of dungeon
    # polygon, corridors hatched one tile on each side)
    _render_hatching(svg, level, seed, dungeon_poly,
                     hatch_distance=hatch_distance,
                     cave_wall_poly=cave_wall_poly)
    _render_corridor_hatching(svg, level, seed)

    # Layer 3: Walls + floor fills
    _render_walls_and_floors(
        svg, level,
        cave_wall_path=cave_wall_path,
        cave_wall_poly=cave_wall_poly,
        cave_tiles=cave_tiles,
    )

    # Layer 3.5: Terrain tints + room-type hints
    _render_terrain_tints(svg, level, dungeon_poly)

    # Layer 4: Floor grid (clipped to interior of dungeon polygon)
    _render_floor_grid(svg, level, dungeon_poly)

    # Layer 5: Floor detail (clipped to interior of dungeon polygon)
    _render_floor_detail(svg, level, seed, dungeon_poly)

    # Layer 6: Terrain detail (wavy lines, grass strokes, etc.)
    _render_terrain_detail(svg, level, seed, dungeon_poly)

    # Layer 7: Stairs
    _render_stairs(svg, level)

    svg.append("</g>")
    svg.append("</svg>")
    return "\n".join(svg)


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


def _render_terrain_tints(
    svg: list[str], level: "Level", dungeon_poly=None,
) -> None:
    """Render soft terrain tints and room-type hint washes.

    Emits semi-transparent colored rects for WATER, GRASS, LAVA,
    and CHASM tiles, plus very subtle room-type washes.  Clipped
    to the dungeon polygon so tints don't bleed outside rooms.
    """
    theme = level.metadata.theme if level.metadata else "dungeon"
    palette = get_palette(theme)

    terrain_map = {
        Terrain.WATER: palette.water,
        Terrain.GRASS: palette.grass,
        Terrain.LAVA: palette.lava,
        Terrain.CHASM: palette.chasm,
    }

    # ── Per-tile terrain tints ──
    tint_rects: list[str] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            style = terrain_map.get(tile.terrain)
            if style is None:
                continue
            tint_rects.append(
                f'<rect x="{x * CELL}" y="{y * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{style.tint}" opacity="{style.tint_opacity}"/>'
            )

    if tint_rects:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(svg, dungeon_poly, "terrain-clip")
            svg.append('<g clip-path="url(#terrain-clip)">')
            svg.extend(tint_rects)
            svg.append('</g>')
        else:
            svg.extend(tint_rects)

    # ── Room-type hint washes ──
    for room in level.rooms:
        tint_info = None
        for tag in room.tags:
            if tag in ROOM_TYPE_TINTS:
                tint_info = ROOM_TYPE_TINTS[tag]
                break
        if tint_info is None:
            continue
        color, opacity = tint_info
        r = room.rect
        svg.append(
            f'<rect x="{r.x * CELL}" y="{r.y * CELL}" '
            f'width="{r.width * CELL}" height="{r.height * CELL}" '
            f'fill="{color}" opacity="{opacity}"/>'
        )


# ── Terrain detail ─────────────────────────────────────────────


def _water_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Wavy horizontal lines for a water tile."""
    elements: list[str] = []
    n_waves = rng.randint(2, 3)
    for i in range(n_waves):
        t = (i + 1) / (n_waves + 1)
        y0 = py + CELL * t
        # Build a wavy path across the tile
        segs = [f"M{px + CELL * 0.1:.1f},{y0:.1f}"]
        steps = 5
        for s in range(1, steps + 1):
            sx = px + CELL * 0.1 + (CELL * 0.8) * s / steps
            sy = y0 + rng.uniform(-CELL * 0.06, CELL * 0.06)
            segs.append(f"L{sx:.1f},{sy:.1f}")
        sw = rng.uniform(0.4, 0.8)
        elements.append(
            f'<path d="{" ".join(segs)}" fill="none" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    # 10% chance of a ripple circle
    if rng.random() < 0.10:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        r = rng.uniform(CELL * 0.06, CELL * 0.12)
        elements.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="none" stroke="{ink}" stroke-width="0.4"/>'
        )
    return elements


def _grass_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Short upward strokes for a grass tile."""
    elements: list[str] = []
    n_blades = rng.randint(3, 6)
    for _ in range(n_blades):
        bx = px + rng.uniform(CELL * 0.1, CELL * 0.9)
        by = py + rng.uniform(CELL * 0.4, CELL * 0.9)
        h = rng.uniform(CELL * 0.12, CELL * 0.25)
        angle = rng.uniform(-0.3, 0.3)  # slight lean
        tx = bx + h * angle
        ty = by - h
        sw = rng.uniform(0.4, 0.8)
        elements.append(
            f'<line x1="{bx:.1f}" y1="{by:.1f}" '
            f'x2="{tx:.1f}" y2="{ty:.1f}" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    # 15% chance of a converging tuft
    if rng.random() < 0.15:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.5, CELL * 0.8)
        for _ in range(3):
            dx = rng.uniform(-CELL * 0.08, CELL * 0.08)
            h = rng.uniform(CELL * 0.15, CELL * 0.25)
            elements.append(
                f'<line x1="{cx + dx:.1f}" y1="{cy:.1f}" '
                f'x2="{cx + dx * 0.3:.1f}" y2="{cy - h:.1f}" '
                f'stroke="{ink}" stroke-width="0.6" '
                f'stroke-linecap="round"/>'
            )
    return elements


def _lava_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Crack lines and ember dots for a lava tile."""
    elements: list[str] = []
    n_cracks = rng.randint(1, 2)
    for _ in range(n_cracks):
        x0 = px + rng.uniform(CELL * 0.1, CELL * 0.9)
        y0 = py + rng.uniform(CELL * 0.1, CELL * 0.9)
        x1 = px + rng.uniform(CELL * 0.1, CELL * 0.9)
        y1 = py + rng.uniform(CELL * 0.1, CELL * 0.9)
        sw = rng.uniform(0.5, 1.0)
        elements.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" '
            f'x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    # 20% chance of ember circle
    if rng.random() < 0.20:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        r = rng.uniform(CELL * 0.04, CELL * 0.08)
        elements.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{ink}" opacity="0.4"/>'
        )
    return elements


def _chasm_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Diagonal hatch lines for a chasm tile."""
    elements: list[str] = []
    n_lines = rng.randint(2, 3)
    for i in range(n_lines):
        t = (i + 1) / (n_lines + 1)
        offset = CELL * t
        sw = rng.uniform(0.4, 0.8)
        # Diagonal from top-left to bottom-right direction
        x0 = px + offset + rng.uniform(-2, 2)
        y0 = py + rng.uniform(0, CELL * 0.15)
        x1 = px + offset + rng.uniform(-2, 2)
        y1 = py + CELL - rng.uniform(0, CELL * 0.15)
        elements.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" '
            f'x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    return elements


_TERRAIN_DETAIL_FN = {
    Terrain.WATER: _water_detail,
    Terrain.GRASS: _grass_detail,
    Terrain.LAVA: _lava_detail,
    Terrain.CHASM: _chasm_detail,
}

_TERRAIN_CLASS = {
    Terrain.WATER: "terrain-water",
    Terrain.GRASS: "terrain-grass",
    Terrain.LAVA: "terrain-lava",
    Terrain.CHASM: "terrain-chasm",
}


def _render_terrain_detail(
    svg: list[str], level: "Level", seed: int,
    dungeon_poly=None,
) -> None:
    """Render terrain-specific hand-drawn marks (wavy lines, etc.).

    Groups output by terrain type with CSS class markers for
    future canvas-layer targeting.
    """
    theme = level.metadata.theme if level.metadata else "dungeon"
    palette = get_palette(theme)
    terrain_styles = {
        Terrain.WATER: palette.water,
        Terrain.GRASS: palette.grass,
        Terrain.LAVA: palette.lava,
        Terrain.CHASM: palette.chasm,
    }

    rng = random.Random(seed + 200)

    # Collect elements per terrain type, split room vs corridor
    room_els: dict[Terrain, list[str]] = {t: [] for t in _TERRAIN_TYPES}
    cor_els: dict[Terrain, list[str]] = {t: [] for t in _TERRAIN_TYPES}

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            fn = _TERRAIN_DETAIL_FN.get(tile.terrain)
            if fn is None:
                continue
            style = terrain_styles[tile.terrain]
            px, py = x * CELL, y * CELL
            els = fn(rng, px, py, style.detail_ink, style.detail_opacity)
            if tile.is_corridor:
                cor_els[tile.terrain].extend(els)
            else:
                room_els[tile.terrain].extend(els)

    # Emit room terrain detail — clipped to dungeon polygon
    has_room = any(room_els[t] for t in _TERRAIN_TYPES)
    if has_room:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(
                svg, dungeon_poly, "terrain-detail-clip",
            )
            svg.append(
                '<g clip-path="url(#terrain-detail-clip)">')
        for terrain_type in _TERRAIN_TYPES:
            els = room_els[terrain_type]
            if els:
                cls = _TERRAIN_CLASS[terrain_type]
                style = terrain_styles[terrain_type]
                svg.append(
                    f'<g class="{cls}" '
                    f'opacity="{style.detail_opacity}">'
                )
                svg.extend(els)
                svg.append('</g>')
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            svg.append('</g>')

    # Emit corridor terrain detail — no clipping
    for terrain_type in _TERRAIN_TYPES:
        els = cor_els[terrain_type]
        if els:
            cls = _TERRAIN_CLASS[terrain_type]
            style = terrain_styles[terrain_type]
            svg.append(
                f'<g class="{cls}" '
                f'opacity="{style.detail_opacity}">'
            )
            svg.extend(els)
            svg.append('</g>')


def _render_walls_and_floors(
    svg: list[str], level: "Level",
    cave_wall_path: str | None = None,
    cave_wall_poly=None,
    cave_tiles: set[tuple[int, int]] | None = None,
) -> None:
    """Render walls and floor fills in one pass.

    Smooth rooms: outline drawn with fill=BG + stroke=INK,
    so the interior is filled and the wall is drawn together.
    Rect rooms: a filled BG rect, then tile-edge wall segments.
    Corridors: per-tile BG rects (no enclosing shape).

    The unified cave region (rooms + connected corridors) is
    rendered from the precomputed *cave_wall_path* and
    *cave_wall_poly* built by :func:`_build_cave_wall_geometry`.
    Both the floor fill and the wall stroke come from the same
    jittered polygon, so the wall silhouette and the floor fill
    are pixel-aligned — mirroring the strategy used for circular
    rooms where the circle polygon is both clip and fill.
    """


    _STROKE_STYLE = (
        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )

    # ── Unified cave region (rooms + connected corridors) ──
    # All tiles in this set skip the per-room cave branch, the
    # per-tile corridor rect fill, AND the per-tile straight-wall
    # segment loop below.  Rendering is driven by the precomputed
    # jittered polygon passed in from render_floor_svg.
    cave_region: set[tuple[int, int]] = cave_tiles or set()
    cave_region_rooms: set[int] = set()
    if cave_region:
        for idx, room in enumerate(level.rooms):
            if isinstance(room.shape, CaveShape):
                cave_region_rooms.add(idx)

    cave_region_svg: list[str] = []
    if cave_wall_path:
        # Use the same smoothed Bézier path for both fill and
        # stroke — the wall path already contains subpaths for
        # exterior + holes, so evenodd fill-rule cuts out holes
        # precisely along the same curves the stroke follows.
        cave_region_svg.append(cave_wall_path.replace(
            '/>',
            f' fill="{CAVE_FLOOR_COLOR}" stroke="none" '
            f'fill-rule="evenodd"/>',
        ))
        cave_region_svg.append(cave_wall_path.replace(
            '/>', f' fill="none" {_STROKE_STYLE}/>'))

    # ── Pre-compute smooth room outlines and wall data ──
    smooth_tiles: set[tuple[int, int]] = set()
    smooth_fills: list[str] = []
    smooth_walls: list[str] = []
    wall_extensions: list[str] = []
    for idx, room in enumerate(level.rooms):
        # Cave-region rooms are handled collectively above.
        if idx in cave_region_rooms:
            smooth_tiles |= room.floor_tiles()
            continue
        outline = _room_svg_outline(room)
        if not outline:
            continue
        openings = _find_doorless_openings(room, level)
        fill_el = outline.replace(
            '/>', f' fill="{FLOOR_COLOR}" stroke="none"/>')
        smooth_fills.append(fill_el)

        if openings:
            gapped, extensions = _outline_with_gaps(
                room, outline, openings,
            )
            wall_extensions.extend(extensions)
            smooth_walls.append(gapped.replace(
                '/>', f' fill="none" {_STROKE_STYLE}/>'))
            for _, _, cx, cy in openings:
                smooth_tiles.add((cx, cy))
        else:
            smooth_walls.append(outline.replace(
                '/>', f' fill="none" {_STROKE_STYLE}/>'))
        smooth_tiles |= room.floor_tiles()

    # Cave region tiles must also skip the per-tile wall segment
    # loop — their walls come from the organic outline above.
    smooth_tiles |= cave_region

    # ── 1. Corridors + doors: per-tile floor rects ──
    for y in range(level.height):
        for x in range(level.width):
            if (x, y) in cave_region:
                continue
            tile = level.tiles[y][x]
            if tile.terrain not in (
                Terrain.FLOOR, Terrain.WATER,
                Terrain.GRASS, Terrain.LAVA,
            ):
                continue
            if tile.is_corridor or (tile.feature and "door" in
                                    (tile.feature or "")):
                svg.append(
                    f'<rect x="{x * CELL}" y="{y * CELL}" '
                    f'width="{CELL}" height="{CELL}" '
                    f'fill="{FLOOR_COLOR}" stroke="none"/>'
                )

    # ── 2. Rect rooms: filled rect ──
    for room in level.rooms:
        if isinstance(room.shape, RectShape):
            r = room.rect
            svg.append(
                f'<rect x="{r.x * CELL}" y="{r.y * CELL}" '
                f'width="{r.width * CELL}" height="{r.height * CELL}" '
                f'fill="{FLOOR_COLOR}" stroke="none"/>'
            )

    # ── 3. Smooth rooms: filled outline + wall stroke ──
    for el in smooth_fills:
        svg.append(el)
    # Cave region: unified floor fill + organic wall stroke.
    for el in cave_region_svg:
        svg.append(el)
    for el in smooth_walls:
        svg.append(el)
    if wall_extensions:
        svg.append(
            f'<path d="{" ".join(wall_extensions)}" '
            f'fill="none" {_STROKE_STYLE}/>'
        )

    # ── 4. Tile-edge wall segments (rect rooms + corridors) ──
    segments: list[str] = []

    def _walkable(x: int, y: int) -> bool:
        return _is_floor(level, x, y) or _is_door(level, x, y)

    for y in range(level.height):
        for x in range(level.width):
            if not _walkable(x, y):
                continue
            if (x, y) in smooth_tiles:
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
            if not _walkable(x, y - 1):
                segments.append(f'M{px},{py} L{px + CELL},{py}')
            if not _walkable(x, y + 1):
                segments.append(
                    f'M{px},{py + CELL} L{px + CELL},{py + CELL}')
            if not _walkable(x - 1, y):
                segments.append(f'M{px},{py} L{px},{py + CELL}')
            if not _walkable(x + 1, y):
                segments.append(
                    f'M{px + CELL},{py} L{px + CELL},{py + CELL}')

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )


from nhc.rendering._stairs_svg import _render_stairs  # noqa: E402


