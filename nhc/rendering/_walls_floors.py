"""Wall and floor fill rendering for SVG dungeons."""

from __future__ import annotations

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import Level, RectShape, SurfaceType, Terrain
from nhc.rendering._room_outlines import (
    _outline_with_gaps,
    _room_svg_outline,
)
from nhc.rendering._svg_helpers import (
    CAVE_FLOOR_COLOR,
    CELL,
    FLOOR_COLOR,
    INK,
    WALL_WIDTH,
    _find_doorless_openings,
    _is_door,
    _is_floor,
)


def _render_walls_and_floors(
    svg: list[str], level: Level,
    cave_wall_path: str | None = None,
    cave_wall_poly=None,
    cave_tiles: set[tuple[int, int]] | None = None,
    building_footprint: set[tuple[int, int]] | None = None,
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

    ``building_footprint`` is the set of tiles INSIDE the
    Building's shape (octagon / circle / ...). When supplied, the
    tile-edge wall pass skips segments where the void neighbour
    lies OUTSIDE the footprint -- those chamfer steps are owned
    by the diagonal masonry renderer.
    """

    _STROKE_STYLE = (
        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )

    # ── Unified cave region (rooms + connected corridors) ──
    cave_region: set[tuple[int, int]] = cave_tiles or set()
    cave_region_rooms: set[int] = set()
    if cave_region:
        for idx, room in enumerate(level.rooms):
            if isinstance(room.shape, CaveShape):
                cave_region_rooms.add(idx)

    cave_region_svg: list[str] = []
    if cave_wall_path:
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
            if (tile.surface_type == SurfaceType.CORRIDOR
                    or (tile.feature and "door" in
                        (tile.feature or ""))):
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
    # Surface levels (no rooms) are open-air sites: town /
    # mansion / farm / tower surface backdrops. Their building
    # footprints are VOID tiles not rooms, and the only
    # enclosure is the palisade / fortification drawn separately.
    # Skipping the tile-edge wall pass here keeps the thick wall
    # stroke off the surface entirely.
    if not level.rooms:
        return

    segments: list[str] = []

    def _walkable(x: int, y: int) -> bool:
        return _is_floor(level, x, y) or _is_door(level, x, y)

    def _draw_wall_to(nx: int, ny: int) -> bool:
        """Decide whether a tile-edge wall should be stamped
        between a walkable source tile and its non-walkable
        neighbour ``(nx, ny)``. When a building footprint is
        supplied, neighbours OUTSIDE the footprint are owned by
        the diagonal masonry renderer and the floor SVG must
        not double-paint them."""
        if building_footprint is None:
            return True
        return (nx, ny) in building_footprint

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
                    if (nb and nb.surface_type == SurfaceType.CORRIDOR
                            and not _walkable(nx, ny)):
                        segments.append(seg)
                continue

            tile = level.tiles[y][x]

            # Outdoor surfaces are open-air -- no side walls.
            # Covers STREET (town / keep), plus FIELD / GARDEN
            # (farm / mansion) surface backdrops.
            if tile.surface_type in (
                SurfaceType.STREET,
                SurfaceType.FIELD,
                SurfaceType.GARDEN,
            ):
                continue

            px, py = x * CELL, y * CELL
            if (not _walkable(x, y - 1)
                    and _draw_wall_to(x, y - 1)):
                segments.append(f'M{px},{py} L{px + CELL},{py}')
            if (not _walkable(x, y + 1)
                    and _draw_wall_to(x, y + 1)):
                segments.append(
                    f'M{px},{py + CELL} L{px + CELL},{py + CELL}')
            if (not _walkable(x - 1, y)
                    and _draw_wall_to(x - 1, y)):
                segments.append(f'M{px},{py} L{px},{py + CELL}')
            if (not _walkable(x + 1, y)
                    and _draw_wall_to(x + 1, y)):
                segments.append(
                    f'M{px + CELL},{py} L{px + CELL},{py + CELL}')

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
