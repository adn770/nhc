"""Per-terrain detail rendering and terrain tints for SVG dungeons.

Terrain detail (water waves, grass blades, lava cracks, chasm
hatching) flows through the unified :class:`TileDecorator`
pipeline as of Phase 4 of the rendering refactor. The four
``terrain_*`` decorators below register on the ``terrain_detail``
layer and split per-tile output into the ``"room"`` / ``"corridor"``
buckets so room fragments stay clipped to the dungeon polygon.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.rendering._decorators import TileDecorator, walk_and_paint
from nhc.rendering._floor_detail import _dungeon_interior_clip
from nhc.rendering._svg_helpers import CELL
from nhc.rendering.terrain_palette import ROOM_TYPE_TINTS, get_palette


# ── Terrain tints ───────────────────────────────────────────────

def _render_terrain_tints(
    svg: list[str], level: Level, dungeon_poly=None,
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


# ── Per-terrain detail painters ─────────────────────────────────

def _water_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Wavy horizontal lines for a water tile.

    ``stroke`` and ``stroke-linecap`` are inherited from the
    parent ``<g>`` group (see :func:`_terrain_group_open`); only
    the per-element variance (``stroke-width`` for waves, no
    extra attrs for the ripple) ships per element.
    """
    del ink, opacity  # inherited from parent <g>
    elements: list[str] = []
    n_waves = rng.randint(2, 3)
    for i in range(n_waves):
        t = (i + 1) / (n_waves + 1)
        y0 = py + CELL * t
        segs = [f"M{px + CELL * 0.1:.1f},{y0:.1f}"]
        steps = 5
        for s in range(1, steps + 1):
            sx = px + CELL * 0.1 + (CELL * 0.8) * s / steps
            sy = y0 + rng.uniform(-CELL * 0.06, CELL * 0.06)
            segs.append(f"L{sx:.1f},{sy:.1f}")
        sw = rng.uniform(0.4, 0.8)
        elements.append(
            f'<path d="{" ".join(segs)}" fill="none" '
            f'stroke-width="{sw:.1f}"/>'
        )
    if rng.random() < 0.10:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        r = rng.uniform(CELL * 0.06, CELL * 0.12)
        elements.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="none" stroke-width="0.4"/>'
        )
    return elements


def _grass_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Short upward strokes for a grass tile.

    Stroke colour and linecap are inherited from the parent
    ``<g>`` group (see :func:`_water_detail`)."""
    del ink, opacity  # inherited from parent <g>
    elements: list[str] = []
    n_blades = rng.randint(3, 6)
    for _ in range(n_blades):
        bx = px + rng.uniform(CELL * 0.1, CELL * 0.9)
        by = py + rng.uniform(CELL * 0.4, CELL * 0.9)
        h = rng.uniform(CELL * 0.12, CELL * 0.25)
        angle = rng.uniform(-0.3, 0.3)
        tx = bx + h * angle
        ty = by - h
        sw = rng.uniform(0.4, 0.8)
        elements.append(
            f'<line x1="{bx:.1f}" y1="{by:.1f}" '
            f'x2="{tx:.1f}" y2="{ty:.1f}" '
            f'stroke-width="{sw:.1f}"/>'
        )
    if rng.random() < 0.15:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.5, CELL * 0.8)
        for _ in range(3):
            dx = rng.uniform(-CELL * 0.08, CELL * 0.08)
            h = rng.uniform(CELL * 0.15, CELL * 0.25)
            elements.append(
                f'<line x1="{cx + dx:.1f}" y1="{cy:.1f}" '
                f'x2="{cx + dx * 0.3:.1f}" y2="{cy - h:.1f}" '
                f'stroke-width="0.6"/>'
            )
    return elements


def _lava_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Crack lines and ember dots for a lava tile.

    Stroke colour and linecap are inherited; ember dots use the
    same colour explicitly via ``fill`` since they aren't
    stroked."""
    del opacity  # inherited from parent <g>
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
            f'stroke-width="{sw:.1f}"/>'
        )
    if rng.random() < 0.20:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        r = rng.uniform(CELL * 0.04, CELL * 0.08)
        # The ember is a filled dot, not a stroke -- keep ink and
        # the small per-dot opacity local.
        elements.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{ink}" stroke="none" opacity="0.4"/>'
        )
    return elements


def _chasm_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Diagonal hatch lines for a chasm tile."""
    del ink, opacity  # inherited from parent <g>
    elements: list[str] = []
    n_lines = rng.randint(2, 3)
    for i in range(n_lines):
        t = (i + 1) / (n_lines + 1)
        offset = CELL * t
        sw = rng.uniform(0.4, 0.8)
        x0 = px + offset + rng.uniform(-2, 2)
        y0 = py + rng.uniform(0, CELL * 0.15)
        x1 = px + offset + rng.uniform(-2, 2)
        y1 = py + CELL - rng.uniform(0, CELL * 0.15)
        elements.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" '
            f'x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke-width="{sw:.1f}"/>'
        )
    return elements


# ── Decorator factories ─────────────────────────────────────────

def _terrain_paint(
    detail_fn,
    terrain: Terrain,
):
    """Build a paint callable that delegates to ``detail_fn``.

    ``detail_fn`` is one of :func:`_water_detail`,
    :func:`_grass_detail`, :func:`_lava_detail`,
    :func:`_chasm_detail` -- the same per-tile painters used by the
    legacy ``_render_terrain_detail`` loop.
    """
    def paint(args):
        theme = args.ctx.theme
        palette = get_palette(theme)
        style = {
            Terrain.WATER: palette.water,
            Terrain.GRASS: palette.grass,
            Terrain.LAVA: palette.lava,
            Terrain.CHASM: palette.chasm,
        }[terrain]
        return detail_fn(
            args.rng, args.px, args.py,
            style.detail_ink, style.detail_opacity,
        )
    return paint


def _terrain_predicate(terrain: Terrain):
    def pred(level: Level, x: int, y: int) -> bool:
        return level.tiles[y][x].terrain is terrain
    return pred


def _terrain_group_open(terrain: Terrain) -> str:
    """Return the wrapping group for a terrain detail decorator.

    Both ``opacity`` and the shared ``stroke`` / ``stroke-linecap``
    come from the *dungeon* theme's palette so the ``<g>``
    matches the legacy emission for any level whose theme falls
    back to the dungeon palette (every site surface today). With
    stroke baked into the group the per-element ``stroke=...
    stroke-linecap=round`` attributes drop, shaving ~40 bytes off
    every grass blade / water wave / chasm line / lava crack.
    """
    palette = get_palette("dungeon")
    style = {
        Terrain.WATER: palette.water,
        Terrain.GRASS: palette.grass,
        Terrain.LAVA: palette.lava,
        Terrain.CHASM: palette.chasm,
    }[terrain]
    cls = _TERRAIN_CLASS[terrain]
    return (
        f'<g class="{cls}" opacity="{style.detail_opacity}" '
        f'stroke="{style.detail_ink}" stroke-linecap="round">'
    )


_TERRAIN_CLASS = {
    Terrain.WATER: "terrain-water",
    Terrain.GRASS: "terrain-grass",
    Terrain.LAVA: "terrain-lava",
    Terrain.CHASM: "terrain-chasm",
}


TERRAIN_WATER = TileDecorator(
    name="terrain_water",
    layer="terrain_detail",
    predicate=_terrain_predicate(Terrain.WATER),
    paint=_terrain_paint(_water_detail, Terrain.WATER),
    group_open=_terrain_group_open(Terrain.WATER),
    z_order=10,
)
TERRAIN_GRASS = TileDecorator(
    name="terrain_grass",
    layer="terrain_detail",
    predicate=_terrain_predicate(Terrain.GRASS),
    paint=_terrain_paint(_grass_detail, Terrain.GRASS),
    group_open=_terrain_group_open(Terrain.GRASS),
    z_order=20,
)
TERRAIN_LAVA = TileDecorator(
    name="terrain_lava",
    layer="terrain_detail",
    predicate=_terrain_predicate(Terrain.LAVA),
    paint=_terrain_paint(_lava_detail, Terrain.LAVA),
    group_open=_terrain_group_open(Terrain.LAVA),
    z_order=30,
)
TERRAIN_CHASM = TileDecorator(
    name="terrain_chasm",
    layer="terrain_detail",
    predicate=_terrain_predicate(Terrain.CHASM),
    paint=_terrain_paint(_chasm_detail, Terrain.CHASM),
    group_open=_terrain_group_open(Terrain.CHASM),
    z_order=40,
)


_TERRAIN_DECORATORS = (
    TERRAIN_WATER, TERRAIN_GRASS, TERRAIN_LAVA, TERRAIN_CHASM,
)


def _terrain_tile_bucket(level: Level, x: int, y: int) -> str:
    """Bucket a tile into ``"corridor"`` for SurfaceType.CORRIDOR
    tiles, ``"room"`` for everything else. Mirrors the
    classification the legacy ``_render_terrain_detail`` loop used."""
    if level.tiles[y][x].surface_type is SurfaceType.CORRIDOR:
        return "corridor"
    return "room"


def _render_terrain_detail(
    svg: list[str], level: Level, seed: int,
    dungeon_poly=None,
    ctx=None,
) -> None:
    """Render terrain-specific hand-drawn marks (wavy lines, etc.).

    Routes through the unified :func:`walk_and_paint` helper. Room
    fragments end up clipped to the dungeon polygon; corridor
    fragments stay unclipped so they reach into the connecting
    passages.
    """
    if ctx is None:
        from dataclasses import replace
        from nhc.rendering._render_context import build_render_context
        ctx = build_render_context(level, seed=seed)
        if dungeon_poly is not ctx.dungeon_poly:
            ctx = replace(ctx, dungeon_poly=dungeon_poly)
    svg.extend(walk_and_paint(
        ctx,
        _TERRAIN_DECORATORS,
        layer_name="terrain_detail",
        tile_bucket=_terrain_tile_bucket,
        room_clip_id="terrain-detail-clip",
    ))
