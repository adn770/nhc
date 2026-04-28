"""Concrete layer registry for ``render_floor_svg``.

Wraps each existing pass as a :class:`Layer` and bundles them
into the ordered :data:`FLOOR_LAYERS` tuple. Phase 5 of the
rendering refactor.

IR emit-siblings (one per layer, named ``_emit_<name>_ir``) live
alongside the legacy ``_<name>_paint`` helpers. They are wired into
:data:`nhc.rendering.ir_emitter.IR_STAGES` and write FlatBuffer ops
that 1.k will route through ``ir_to_svg`` instead of the legacy
paint helpers. The paint helpers stay until Phase 4 deletes them
after the Rust ports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.rendering._decorators import TileDecorator
from nhc.rendering._features_svg import (
    BUSH_FEATURE, FOUNTAIN_CROSS_FEATURE, FOUNTAIN_FEATURE,
    FOUNTAIN_LARGE_FEATURE, FOUNTAIN_LARGE_SQUARE_FEATURE,
    FOUNTAIN_SQUARE_FEATURE, TREE_FEATURE, WELL_FEATURE,
    WELL_SQUARE_FEATURE,
)
from nhc.rendering._pipeline import (
    Layer, TileWalkLayer, make_tile_walk_layer,
)
from nhc.rendering._render_context import RenderContext
from nhc.rendering._svg_helpers import _is_door

if TYPE_CHECKING:
    from nhc.rendering.ir_emitter import FloorIRBuilder


# ── Bespoke layer paint wrappers ─────────────────────────────


def _shadows_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._shadows import (
        _render_corridor_shadows, _render_room_shadows,
    )
    out: list[str] = []
    _render_room_shadows(out, ctx.level)
    _render_corridor_shadows(out, ctx.level)
    return out


def _emit_shadows_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the shadows layer.

    Honours the legacy ``layer.is_active`` gate: building floors
    have ``ctx.shadows_enabled = False`` and skip the layer
    entirely (no comment, no fragments). The IR matches by
    returning early so the dispatcher's per-layer loop sees zero
    ops and ``ir_to_svg`` reads the flag to suppress the comment.

    Order matches the legacy ``_shadows_paint`` (room shadows
    first, then corridor shadows) so ``layer_to_svg(buf, "shadows")``
    streams op output in the same sequence as
    ``_render_room_shadows`` + ``_render_corridor_shadows`` joined.
    """
    if not builder.ctx.shadows_enabled:
        return

    from nhc.rendering.ir._fb import Op, ShadowKind
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.ShadowOp import ShadowOpT
    from nhc.rendering.ir._fb.TileCoord import TileCoordT
    from nhc.rendering.ir_emitter import _room_region_data

    level = builder.ctx.level

    # Room shadows — one op per room, in level.rooms order.
    for room in level.rooms:
        if _room_region_data(room) is None:
            continue
        op = ShadowOpT()
        op.kind = ShadowKind.ShadowKind.Room
        op.regionRef = room.id
        entry = OpEntryT()
        entry.opType = Op.Op.ShadowOp
        entry.op = op
        builder.add_op(entry)

    # Corridor shadows — single aggregated op, row-major traversal
    # to match the legacy double-loop append order.
    tiles: list[TileCoordT] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
            ):
                continue
            t = TileCoordT()
            t.x = x
            t.y = y
            tiles.append(t)
    if not tiles:
        return
    op = ShadowOpT()
    op.kind = ShadowKind.ShadowKind.Corridor
    op.tiles = tiles
    entry = OpEntryT()
    entry.opType = Op.Op.ShadowOp
    entry.op = op
    builder.add_op(entry)


def _hatching_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._hatching import (
        _render_corridor_hatching, _render_hatching,
    )
    out: list[str] = []
    _render_hatching(
        out, ctx.level, ctx.seed, ctx.dungeon_poly,
        hatch_distance=ctx.hatch_distance,
        cave_wall_poly=ctx.cave_wall_poly,
    )
    _render_corridor_hatching(out, ctx.level, ctx.seed)
    return out


def _emit_hatch_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the hatching layer.

    Honours the legacy ``layer.is_active`` gate: building floors
    and prerevealed surfaces have ``ctx.hatching_enabled = False``
    and skip the layer entirely. ``ir_to_svg`` reads the flag to
    suppress the per-layer comment when no ops are present.

    Order matches the legacy ``_hatching_paint`` (room halo first,
    then corridor halo) so ``layer_to_svg(buf, "hatching")``
    streams op output in the same sequence as the joined legacy
    output.

    Sub-step 1.b (Boundary B, plan §8) flips the Room payload:
    ``tiles[]`` now holds the **candidate hatch tiles** in row-major
    order (y outer, x inner over ``range(-1, h+1) × range(-1, w+1)``,
    skipping floor tiles and tiles that fail the Perlin distance
    filter), and a parallel ``is_outer[]`` bit array flags
    ``dist > base_distance_limit * 0.5`` so the consumer can apply
    the 10 % RNG skip without reconstructing dist. ``is_outer`` is
    all-False in cave mode (the legacy skip is gated on
    ``cave_wall_poly is None``). The deterministic prefix that
    used to live in the handler now lives here; the consumer just
    iterates and rolls RNG.

    1.c.1 emits the Corridor halo as a sorted tile list (handler's
    rng walks the same order).

    Hole hatching is out of scope for Phase 1: the legacy
    ``_render_hole_hatching`` is defined but never invoked by
    ``_hatching_paint``, so emitting ``HatchOp(kind=Hole)`` would
    diverge from the parity contract.
    """
    if not builder.ctx.hatching_enabled:
        return

    import math

    from shapely.geometry import Point

    from nhc.rendering import _perlin as _noise
    from nhc.rendering._svg_helpers import CELL
    from nhc.rendering.ir._fb import HatchKind, Op
    from nhc.rendering.ir._fb.HatchOp import HatchOpT
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.TileCoord import TileCoordT

    ctx = builder.ctx
    level = ctx.level
    base_seed = ctx.seed

    # ── Room (perimeter) halo ────────────────────────────────
    # Sub-step 1.b: walk the candidate space and apply the Perlin
    # distance filter here so the consumer (Python handler today,
    # Rust handler post-port) just iterates and rolls RNG. Skip the
    # op when the dungeon polygon is empty — matches the legacy
    # `_render_hatching` `if dungeon_poly.is_empty: return`.
    if ctx.dungeon_poly is not None and not ctx.dungeon_poly.is_empty:
        cave_mode = ctx.cave_wall_poly is not None
        boundary = ctx.dungeon_poly.boundary
        base_distance_limit = ctx.hatch_distance * CELL

        floor_set: set[tuple[int, int]] = set()
        for ty in range(level.height):
            for tx in range(level.width):
                if level.tiles[ty][tx].terrain == Terrain.FLOOR:
                    floor_set.add((tx, ty))

        candidate_tiles: list[TileCoordT] = []
        is_outer: list[bool] = []
        for gy in range(-1, level.height + 1):
            for gx in range(-1, level.width + 1):
                if (gx, gy) in floor_set:
                    continue
                min_dist = float("inf")
                for ddx in range(-2, 3):
                    for ddy in range(-2, 3):
                        if (gx + ddx, gy + ddy) in floor_set:
                            d = math.hypot(ddx, ddy) * CELL
                            if d < min_dist:
                                min_dist = d
                if min_dist == float("inf"):
                    center = Point(
                        (gx + 0.5) * CELL, (gy + 0.5) * CELL,
                    )
                    min_dist = boundary.distance(center)
                dist = min_dist
                if not cave_mode:
                    noise_var = (
                        _noise.pnoise2(gx * 0.3, gy * 0.3, base=50)
                        * CELL * 0.8
                    )
                    tile_limit = base_distance_limit + noise_var
                else:
                    tile_limit = base_distance_limit
                if dist > tile_limit:
                    continue
                t = TileCoordT()
                t.x = gx
                t.y = gy
                candidate_tiles.append(t)
                is_outer.append(
                    (not cave_mode)
                    and dist > base_distance_limit * 0.5
                )

        op = HatchOpT()
        op.kind = HatchKind.HatchKind.Room
        op.regionOut = "dungeon"
        op.regionIn = ""
        op.tiles = candidate_tiles
        op.isOuter = is_outer
        op.seed = base_seed
        op.extentTiles = ctx.hatch_distance
        entry = OpEntryT()
        entry.opType = Op.Op.HatchOp
        entry.op = op
        builder.add_op(entry)

    # ── Corridor halo ────────────────────────────────────────
    hatch_tiles: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
            ):
                continue
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if not level.in_bounds(nx, ny):
                    continue
                nb = level.tiles[ny][nx]
                if (
                    nb.terrain == Terrain.VOID
                    and nb.surface_type != SurfaceType.CORRIDOR
                ):
                    hatch_tiles.add((nx, ny))
    if not hatch_tiles:
        return

    tiles: list[TileCoordT] = []
    for tx, ty in sorted(hatch_tiles):
        t = TileCoordT()
        t.x = tx
        t.y = ty
        tiles.append(t)

    op = HatchOpT()
    op.kind = HatchKind.HatchKind.Corridor
    op.tiles = tiles
    op.seed = base_seed + 7
    entry = OpEntryT()
    entry.opType = Op.Op.HatchOp
    entry.op = op
    builder.add_op(entry)


def _walls_and_floors_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._walls_floors import _render_walls_and_floors
    out: list[str] = []
    footprint = (
        set(ctx.building_footprint)
        if ctx.building_footprint is not None
        else None
    )
    _render_walls_and_floors(
        out, ctx.level,
        cave_wall_path=ctx.cave_wall_path,
        cave_wall_poly=ctx.cave_wall_poly,
        cave_tiles=set(ctx.cave_tiles) if ctx.cave_tiles else set(),
        building_footprint=footprint,
    )
    return out


def _emit_walls_and_floors_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the walls + floors layer.

    Deterministic — no RNG, no Perlin. The challenge is data shape:
    ``_render_walls_and_floors`` calls ``_room_svg_outline`` and
    ``_outline_with_gaps`` which need the live :class:`Room` and
    :class:`Level` (per-room openings, shape-specific gap geometry).
    This emitter pre-renders those into the schema-additive
    ``smooth_fill_svg`` / ``smooth_wall_svg`` / ``wall_extensions_d``
    fields on :class:`WallsAndFloorsOp` (Phase 1 transitional —
    Phase 4 refactors to structured geometry when porting to Rust).

    The handler then walks the IR data in legacy output order:
    corridor / door rects, rect-room rects, smooth fills, cave
    region (fill + wall), smooth walls, wall extensions, tile-edge
    walls.
    """
    from nhc.dungeon.generators.cellular import CaveShape
    from nhc.dungeon.model import RectShape
    from nhc.rendering._room_outlines import (
        _outline_with_gaps, _room_svg_outline,
    )
    from nhc.rendering._svg_helpers import (
        CELL, FLOOR_COLOR, INK, WALL_WIDTH,
        _find_doorless_openings, _is_floor,
    )
    from nhc.rendering.ir._fb import Op
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.RectRoom import RectRoomT
    from nhc.rendering.ir._fb.TileCoord import TileCoordT
    from nhc.rendering.ir._fb.WallsAndFloorsOp import WallsAndFloorsOpT

    ctx = builder.ctx
    level = ctx.level
    cave_tiles: set[tuple[int, int]] = (
        set(ctx.cave_tiles) if ctx.cave_tiles else set()
    )
    cave_wall_path = ctx.cave_wall_path or ""
    building_footprint = ctx.building_footprint

    cave_region_rooms: set[int] = set()
    if cave_tiles:
        for idx, room in enumerate(level.rooms):
            if isinstance(room.shape, CaveShape):
                cave_region_rooms.add(idx)

    smooth_room_regions: list[str] = []
    smooth_fill_svg: list[str] = []
    smooth_wall_svg: list[str] = []
    wall_extensions: list[str] = []
    smooth_tiles: set[tuple[int, int]] = set()

    stroke_style = (
        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )

    for idx, room in enumerate(level.rooms):
        if idx in cave_region_rooms:
            smooth_tiles |= room.floor_tiles()
            continue
        outline = _room_svg_outline(room)
        if not outline:
            continue
        openings = _find_doorless_openings(room, level)
        smooth_room_regions.append(room.id)
        smooth_fill_svg.append(
            outline.replace(
                "/>", f' fill="{FLOOR_COLOR}" stroke="none"/>'
            )
        )
        if openings:
            gapped, extensions = _outline_with_gaps(
                room, outline, openings,
            )
            wall_extensions.extend(extensions)
            smooth_wall_svg.append(
                gapped.replace(
                    "/>", f' fill="none" {stroke_style}/>'
                )
            )
            for _, _, cx, cy in openings:
                smooth_tiles.add((cx, cy))
        else:
            smooth_wall_svg.append(
                outline.replace(
                    "/>", f' fill="none" {stroke_style}/>'
                )
            )
        smooth_tiles |= room.floor_tiles()

    smooth_tiles |= cave_tiles

    corridor_tiles_list: list[TileCoordT] = []
    for y in range(level.height):
        for x in range(level.width):
            if (x, y) in cave_tiles:
                continue
            tile = level.tiles[y][x]
            if tile.terrain not in (
                Terrain.FLOOR, Terrain.WATER,
                Terrain.GRASS, Terrain.LAVA,
            ):
                continue
            if (
                tile.surface_type == SurfaceType.CORRIDOR
                or (tile.feature and "door" in (tile.feature or ""))
            ):
                t = TileCoordT()
                t.x = x
                t.y = y
                corridor_tiles_list.append(t)

    rect_rooms_list: list[RectRoomT] = []
    for room in level.rooms:
        if isinstance(room.shape, RectShape):
            r = room.rect
            rr = RectRoomT()
            rr.x = r.x
            rr.y = r.y
            rr.w = r.width
            rr.h = r.height
            rr.regionRef = room.id
            rect_rooms_list.append(rr)

    segments: list[str] = []
    if level.rooms:
        def _walkable(x: int, y: int) -> bool:
            return _is_floor(level, x, y) or _is_door(level, x, y)

        def _draw_wall_to(nx: int, ny: int) -> bool:
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
                        (x, y - 1,
                         f'M{px},{py} L{px + CELL},{py}'),
                        (x, y + 1,
                         f'M{px},{py + CELL} '
                         f'L{px + CELL},{py + CELL}'),
                        (x - 1, y,
                         f'M{px},{py} L{px},{py + CELL}'),
                        (x + 1, y,
                         f'M{px + CELL},{py} '
                         f'L{px + CELL},{py + CELL}'),
                    ]:
                        nb = level.tile_at(nx, ny)
                        if (
                            nb
                            and nb.surface_type == SurfaceType.CORRIDOR
                            and not _walkable(nx, ny)
                        ):
                            segments.append(seg)
                    continue
                tile = level.tiles[y][x]
                if tile.surface_type in (
                    SurfaceType.STREET,
                    SurfaceType.FIELD,
                    SurfaceType.GARDEN,
                ):
                    continue
                px, py = x * CELL, y * CELL
                if (
                    not _walkable(x, y - 1)
                    and _draw_wall_to(x, y - 1)
                ):
                    segments.append(
                        f'M{px},{py} L{px + CELL},{py}'
                    )
                if (
                    not _walkable(x, y + 1)
                    and _draw_wall_to(x, y + 1)
                ):
                    segments.append(
                        f'M{px},{py + CELL} '
                        f'L{px + CELL},{py + CELL}'
                    )
                if (
                    not _walkable(x - 1, y)
                    and _draw_wall_to(x - 1, y)
                ):
                    segments.append(
                        f'M{px},{py} L{px},{py + CELL}'
                    )
                if (
                    not _walkable(x + 1, y)
                    and _draw_wall_to(x + 1, y)
                ):
                    segments.append(
                        f'M{px + CELL},{py} '
                        f'L{px + CELL},{py + CELL}'
                    )

    op = WallsAndFloorsOpT()
    op.smoothRoomRegions = smooth_room_regions
    op.smoothFillSvg = smooth_fill_svg
    op.smoothWallSvg = smooth_wall_svg
    op.rectRooms = rect_rooms_list
    op.corridorTiles = corridor_tiles_list
    op.caveRegion = cave_wall_path
    op.wallSegments = segments
    op.wallExtensionsD = (
        " ".join(wall_extensions) if wall_extensions else ""
    )
    if building_footprint:
        op.buildingFootprint = []
        for tx, ty in sorted(building_footprint):
            t = TileCoordT()
            t.x = tx
            t.y = ty
            op.buildingFootprint.append(t)

    entry = OpEntryT()
    entry.opType = Op.Op.WallsAndFloorsOp
    entry.op = op
    builder.add_op(entry)


def _terrain_tints_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._terrain_detail import _render_terrain_tints
    out: list[str] = []
    _render_terrain_tints(out, ctx.level, ctx.dungeon_poly)
    return out


def _emit_terrain_tints_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the terrain-tints layer.

    Deterministic. Walks the level for WATER / GRASS / LAVA / CHASM
    tiles and emits one ``TerrainTintTile`` per match. Per-room
    tags are checked against ``ROOM_TYPE_TINTS``; rooms with a
    matching tag emit one ``RoomWash`` carrying the color + opacity
    inline (the palette table the legacy looks up isn't available
    in the IR, so resolved values travel with the op).
    """
    from nhc.rendering.terrain_palette import ROOM_TYPE_TINTS
    from nhc.rendering.ir._fb import Op, TerrainKind
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.RoomWash import RoomWashT
    from nhc.rendering.ir._fb.TerrainTintOp import TerrainTintOpT
    from nhc.rendering.ir._fb.TerrainTintTile import TerrainTintTileT

    ctx = builder.ctx
    level = ctx.level

    _kind_map = {
        Terrain.WATER: TerrainKind.TerrainKind.Water,
        Terrain.GRASS: TerrainKind.TerrainKind.Grass,
        Terrain.LAVA: TerrainKind.TerrainKind.Lava,
        Terrain.CHASM: TerrainKind.TerrainKind.Chasm,
    }

    tiles: list[TerrainTintTileT] = []
    for y in range(level.height):
        for x in range(level.width):
            kind = _kind_map.get(level.tiles[y][x].terrain)
            if kind is None:
                continue
            t = TerrainTintTileT()
            t.x = x
            t.y = y
            t.kind = kind
            tiles.append(t)

    washes: list[RoomWashT] = []
    for room in level.rooms:
        tint = None
        for tag in room.tags:
            if tag in ROOM_TYPE_TINTS:
                tint = ROOM_TYPE_TINTS[tag]
                break
        if tint is None:
            continue
        color, opacity = tint
        r = room.rect
        w = RoomWashT()
        w.x = r.x
        w.y = r.y
        w.w = r.width
        w.h = r.height
        w.color = color
        w.opacity = opacity
        washes.append(w)

    if not tiles and not washes:
        return

    op = TerrainTintOpT()
    op.tiles = tiles
    op.roomWashes = washes
    op.clipRegion = (
        "dungeon"
        if (
            ctx.dungeon_poly is not None
            and not ctx.dungeon_poly.is_empty
        )
        else ""
    )
    entry = OpEntryT()
    entry.opType = Op.Op.TerrainTintOp
    entry.op = op
    builder.add_op(entry)


def _floor_grid_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._floor_detail import _render_floor_grid
    out: list[str] = []
    _render_floor_grid(out, ctx.level, ctx.dungeon_poly)
    return out


def _emit_floor_grid_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the floor-grid layer.

    Walks the level y-major, x-minor (matching the legacy
    ``_render_floor_grid`` iteration so the handler's
    ``random.Random(seed)`` stream replays in lock-step) and
    collects every non-VOID tile with its ``is_corridor`` flag
    (CORRIDOR surface, door tile, or secret-door feature). The
    handler decides per-edge whether to drop into the room bucket
    or corridor bucket from this flag — same routing the legacy
    does inline.
    """
    from nhc.rendering.ir._fb import Op
    from nhc.rendering.ir._fb.FloorGridOp import FloorGridOpT
    from nhc.rendering.ir._fb.FloorGridTile import FloorGridTileT
    from nhc.rendering.ir._fb.OpEntry import OpEntryT

    ctx = builder.ctx
    level = ctx.level

    tiles: list[FloorGridTileT] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain == Terrain.VOID:
                continue
            is_cor = (
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
                or tile.feature == "door_secret"
            )
            t = FloorGridTileT()
            t.x = x
            t.y = y
            t.isCorridor = is_cor
            tiles.append(t)

    if not tiles:
        return

    op = FloorGridOpT()
    # The fixed `41` seed is the documented code/design discrepancy
    # in design/ir_primitives.md — Phase 1 honours legacy behaviour.
    op.seed = 41
    op.theme = ctx.theme
    op.tiles = tiles
    op.clipRegion = (
        "dungeon"
        if (
            ctx.dungeon_poly is not None
            and not ctx.dungeon_poly.is_empty
        )
        else ""
    )
    entry = OpEntryT()
    entry.opType = Op.Op.FloorGridOp
    entry.op = op
    builder.add_op(entry)


def _floor_detail_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._floor_detail import _render_floor_detail
    building_polygon = (
        list(ctx.building_polygon)
        if ctx.building_polygon is not None
        else None
    )
    out: list[str] = []
    _render_floor_detail(
        out, ctx.level, ctx.seed, ctx.dungeon_poly,
        building_polygon=building_polygon,
        ctx=ctx,
    )
    return out


def _floor_detail_candidates(
    level,
) -> list[tuple[int, int, bool]]:
    """Walk the level once and return the floor-detail candidate
    set: floor tiles that are not stair features and not on a
    STREET / FIELD / GARDEN surface, with a per-tile corridor /
    door classification. Used by both
    :func:`_emit_floor_detail_ir` (sub-step 3.b) and
    :func:`_emit_thematic_detail_ir` (sub-step 4.b) so the two
    ops walk identical tile sets in the same y-major / x-minor
    order.
    """
    candidates: list[tuple[int, int, bool]] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain != Terrain.FLOOR:
                continue
            if tile.feature in ("stairs_up", "stairs_down"):
                continue
            if tile.surface_type in (
                SurfaceType.STREET,
                SurfaceType.FIELD,
                SurfaceType.GARDEN,
            ):
                continue
            is_cor = (
                tile.surface_type == SurfaceType.CORRIDOR
                or _is_door(level, x, y)
            )
            candidates.append((x, y, is_cor))
    return candidates


def _emit_floor_detail_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the floor-detail layer.

    Sub-step 3.e migrated the floor-detail-proper painters
    (cracks / scratches / stones) to Rust; the dispatcher
    reaches the port via ``op.tiles[]`` + ``op.isCorridor[]`` +
    ``op.theme``. Sub-step 4.b moves the thematic-detail
    portion (webs / bones / skulls) to its own
    ``ThematicDetailOp`` (see :func:`_emit_thematic_detail_ir`),
    so this emitter only ships floor-detail data and the
    decorator / wood-floor passthroughs.

    Phase 1.l extends the emitter to also cover the wood-floor
    short-circuit (interior_finish == "wood") and the post-pass
    decorator pipeline (cobblestone / brick / flagstone /
    opus_romano / field_stone / cart_tracks / ore_deposit).
    """
    import random

    from nhc.rendering._floor_detail import (
        _is_brick_tile, _is_cobble_tile,
        _is_field_overlay_tile, _is_flagstone_tile,
        _is_opus_romano_tile, _is_ore_tile, _is_track_tile,
        _render_wood_floor, _track_horizontal_at,
    )
    from nhc.rendering.ir._fb import CobblePattern, Op
    from nhc.rendering.ir._fb.BrickVariant import BrickVariantT
    from nhc.rendering.ir._fb.CartTracksVariant import (
        CartTracksVariantT,
    )
    from nhc.rendering.ir._fb.CobblestoneVariant import (
        CobblestoneVariantT,
    )
    from nhc.rendering.ir._fb.DecoratorOp import DecoratorOpT
    from nhc.rendering.ir._fb.FieldStoneVariant import (
        FieldStoneVariantT,
    )
    from nhc.rendering.ir._fb.FlagstoneVariant import (
        FlagstoneVariantT,
    )
    from nhc.rendering.ir._fb.FloorDetailOp import FloorDetailOpT
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.OpusRomanoVariant import (
        OpusRomanoVariantT,
    )
    from nhc.rendering.ir._fb.OreDepositVariant import (
        OreDepositVariantT,
    )
    from nhc.rendering.ir._fb.TileCoord import TileCoordT

    ctx = builder.ctx
    seed = ctx.seed
    if ctx.interior_finish == "wood":
        # Wood-floor short-circuit. The legacy renderer takes its
        # own seeded rng + clip-path envelope, so we just stash
        # the produced fragments and emit the op early; the
        # handler's per-bucket dispatch is bypassed.
        wood_out: list[str] = []
        building_polygon = (
            list(ctx.building_polygon)
            if ctx.building_polygon is not None
            else None
        )
        _render_wood_floor(
            wood_out, ctx.level, random.Random(seed + 99),
            ctx.dungeon_poly,
            building_polygon=building_polygon,
            ctx=ctx,
        )
        if not wood_out:
            return
        op = FloorDetailOpT()
        op.seed = seed + 99
        op.theme = ctx.theme
        op.woodFloorGroups = wood_out
        op.clipRegion = ""
        entry = OpEntryT()
        entry.opType = Op.Op.FloorDetailOp
        entry.op = op
        builder.add_op(entry)
        return

    level = ctx.level
    theme = ctx.theme
    candidates = _floor_detail_candidates(level)

    # Sub-steps 6-12: all seven decorator types now flow through
    # the structured DecoratorOp vectors below. The legacy
    # walk_and_paint decorator pipeline is fully retired for the
    # floor_detail layer slot — FloorDetailOp.decorator_groups
    # ships empty and is slated for Phase 7 cleanup.
    cobble_tiles: list[tuple[int, int]] = []
    brick_tiles: list[tuple[int, int]] = []
    flagstone_tiles: list[tuple[int, int]] = []
    opus_romano_tiles: list[tuple[int, int]] = []
    field_stone_tiles: list[tuple[int, int]] = []
    track_tiles: list[tuple[int, int, bool]] = []
    ore_tiles: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            if _is_cobble_tile(level, x, y):
                cobble_tiles.append((x, y))
            if _is_brick_tile(level, x, y):
                brick_tiles.append((x, y))
            if _is_flagstone_tile(level, x, y):
                flagstone_tiles.append((x, y))
            if _is_opus_romano_tile(level, x, y):
                opus_romano_tiles.append((x, y))
            if _is_field_overlay_tile(level, x, y):
                field_stone_tiles.append((x, y))
            if _is_track_tile(level, x, y):
                track_tiles.append(
                    (x, y, _track_horizontal_at(level, x, y)),
                )
            if _is_ore_tile(level, x, y):
                ore_tiles.append((x, y))

    if not (
        candidates
        or cobble_tiles or brick_tiles
        or flagstone_tiles or opus_romano_tiles
        or field_stone_tiles or track_tiles
        or ore_tiles
    ):
        return

    if candidates:
        op = FloorDetailOpT()
        op.seed = seed + 99
        op.theme = theme
        op.tiles = [TileCoordT(x=x, y=y) for x, y, _ in candidates]
        op.isCorridor = [is_cor for _, _, is_cor in candidates]
        op.clipRegion = (
            "dungeon"
            if (
                ctx.dungeon_poly is not None
                and not ctx.dungeon_poly.is_empty
            )
            else ""
        )
        entry = OpEntryT()
        entry.opType = Op.Op.FloorDetailOp
        entry.op = op
        builder.add_op(entry)

    if (
        cobble_tiles or brick_tiles
        or flagstone_tiles or opus_romano_tiles
        or field_stone_tiles or track_tiles
        or ore_tiles
    ):
        deco_op = DecoratorOpT()
        deco_op.seed = seed + 333
        deco_op.theme = theme
        deco_op.clipRegion = ""
        if cobble_tiles:
            deco_op.cobblestone = [CobblestoneVariantT(
                tiles=[TileCoordT(x=x, y=y) for x, y in cobble_tiles],
                pattern=CobblePattern.CobblePattern.Cobble,
            )]
        if brick_tiles:
            deco_op.brick = [BrickVariantT(
                tiles=[TileCoordT(x=x, y=y) for x, y in brick_tiles],
            )]
        if flagstone_tiles:
            deco_op.flagstone = [FlagstoneVariantT(
                tiles=[TileCoordT(x=x, y=y) for x, y in flagstone_tiles],
            )]
        if opus_romano_tiles:
            deco_op.opusRomano = [OpusRomanoVariantT(
                tiles=[TileCoordT(x=x, y=y) for x, y in opus_romano_tiles],
            )]
        if field_stone_tiles:
            deco_op.fieldStone = [FieldStoneVariantT(
                tiles=[TileCoordT(x=x, y=y) for x, y in field_stone_tiles],
            )]
        if track_tiles:
            deco_op.cartTracks = [CartTracksVariantT(
                tiles=[
                    TileCoordT(x=x, y=y) for x, y, _ in track_tiles
                ],
                isHorizontal=[h for _, _, h in track_tiles],
            )]
        if ore_tiles:
            deco_op.oreDeposit = [OreDepositVariantT(
                tiles=[TileCoordT(x=x, y=y) for x, y in ore_tiles],
            )]
        deco_entry = OpEntryT()
        deco_entry.opType = Op.Op.DecoratorOp
        deco_entry.op = deco_op
        builder.add_op(deco_entry)


def _emit_thematic_detail_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR op for the thematic-detail layer.

    Sub-step 4.b splits webs / bones / skulls off the
    floor-detail layer's passthrough and gives them their own
    ``ThematicDetailOp``. The emitter walks the same candidate
    set as :func:`_emit_floor_detail_ir` (so the two ops align
    tile-for-tile) but additionally pre-resolves the per-tile
    wall-corner bitmap that the painter needs for web placement
    (legacy ``_tile_thematic_detail`` calls ``_is_floor`` against
    the four neighbours; we lift those checks to the emitter so
    the consumer doesn't need level access). The dispatcher
    drives the painter from the IR, Python-side at this commit
    and Rust-side at sub-step 4.e.
    """
    from nhc.rendering._svg_helpers import _is_floor
    from nhc.rendering.ir._fb import Op
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.ThematicDetailOp import (
        ThematicDetailOpT,
    )
    from nhc.rendering.ir._fb.TileCoord import TileCoordT

    ctx = builder.ctx
    level = ctx.level
    if ctx.interior_finish == "wood":
        # Wood-floor short-circuit. Thematic painters never run
        # on wood floors today; mirror that by emitting nothing.
        return

    candidates = _floor_detail_candidates(level)
    if not candidates:
        return

    wall_corners: list[int] = []
    for x, y, _ in candidates:
        bits = 0
        # 0x01 TL, 0x02 TR, 0x04 BL, 0x08 BR.
        # A corner is wall-adjacent when both adjacent neighbours
        # are non-floor (legacy ``_tile_thematic_detail`` shape).
        if not _is_floor(level, x, y - 1) and not _is_floor(level, x - 1, y):
            bits |= 0x01
        if not _is_floor(level, x, y - 1) and not _is_floor(level, x + 1, y):
            bits |= 0x02
        if not _is_floor(level, x, y + 1) and not _is_floor(level, x - 1, y):
            bits |= 0x04
        if not _is_floor(level, x, y + 1) and not _is_floor(level, x + 1, y):
            bits |= 0x08
        wall_corners.append(bits)

    op = ThematicDetailOpT()
    op.seed = ctx.seed + 199
    op.theme = ctx.theme
    op.tiles = [TileCoordT(x=x, y=y) for x, y, _ in candidates]
    op.isCorridor = [is_cor for _, _, is_cor in candidates]
    op.wallCorners = wall_corners
    op.clipRegion = (
        "dungeon"
        if (
            ctx.dungeon_poly is not None
            and not ctx.dungeon_poly.is_empty
        )
        else ""
    )
    entry = OpEntryT()
    entry.opType = Op.Op.ThematicDetailOp
    entry.op = op
    builder.add_op(entry)


def _terrain_detail_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._terrain_detail import _render_terrain_detail
    out: list[str] = []
    _render_terrain_detail(
        out, ctx.level, ctx.seed, ctx.dungeon_poly, ctx=ctx,
    )
    return out


def _emit_terrain_detail_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the terrain-detail layer.

    Inlines the bucket-collection logic of ``walk_and_paint`` so
    we get separate room / corridor pre-rendered groups (without
    the clip envelope, which the handler reapplies). Phase 1
    transitional — the legacy ``_water_detail`` / ``_lava_detail``
    / ``_chasm_detail`` painters consume per-decorator seeded RNG
    streams; reproducing them from a structured tile list would
    mean porting the painters and the per-decorator seeding into
    the handler. Phase 4 refactors when the Rust port lands.
    """
    from nhc.rendering._decorators import (
        PaintArgs, _flags_satisfy, _seeded_rng,
    )
    from nhc.rendering._svg_helpers import CELL
    from nhc.rendering._terrain_detail import (
        _TERRAIN_DECORATORS, _terrain_tile_bucket,
    )
    from nhc.rendering.ir._fb import Op
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.TerrainDetailOp import TerrainDetailOpT

    ctx = builder.ctx
    level = ctx.level

    active = [d for d in _TERRAIN_DECORATORS if _flags_satisfy(ctx, d)]
    if not active:
        return

    active_sorted = sorted(
        enumerate(active),
        key=lambda pair: (pair[1].z_order, pair[0]),
    )
    rngs = {d.name: _seeded_rng(ctx, d.name) for _, d in active_sorted}
    fragments: dict[str, dict[str, list[str]]] = {
        d.name: {"room": [], "corridor": []} for _, d in active_sorted
    }

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            for _, dec in active_sorted:
                if not dec.predicate(level, x, y):
                    continue
                args = PaintArgs(
                    rng=rngs[dec.name],
                    x=x, y=y,
                    px=x * CELL, py=y * CELL,
                    ctx=ctx, tile=tile,
                )
                produced = dec.paint(args)
                if produced is None:
                    continue
                bucket = _terrain_tile_bucket(level, x, y)
                fragments[dec.name][bucket].extend(produced)

    def _emit_bucket(bucket: str) -> list[str]:
        out: list[str] = []
        for _, dec in active_sorted:
            frags = fragments[dec.name][bucket]
            if not frags:
                continue
            if dec.group_open is not None:
                out.append(dec.group_open)
            out.extend(frags)
            if dec.group_open is not None:
                out.append(dec.group_close)
        return out

    room_groups = _emit_bucket("room")
    corridor_groups = _emit_bucket("corridor")

    if not (room_groups or corridor_groups):
        return

    op = TerrainDetailOpT()
    op.seed = ctx.seed + 200
    op.theme = ctx.theme
    op.roomGroups = room_groups
    op.corridorGroups = corridor_groups
    op.clipRegion = (
        "dungeon"
        if (
            ctx.dungeon_poly is not None
            and not ctx.dungeon_poly.is_empty
        )
        else ""
    )
    entry = OpEntryT()
    entry.opType = Op.Op.TerrainDetailOp
    entry.op = op
    builder.add_op(entry)


def _stairs_paint(ctx: RenderContext) -> Iterable[str]:
    from nhc.rendering._stairs_svg import _render_stairs
    out: list[str] = []
    _render_stairs(out, ctx.level)
    return out


def _emit_stairs_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the stairs layer.

    Deterministic — per-tile up/down stair markers. Walks the
    level y-major, x-minor (matches legacy
    ``_render_stairs`` iteration), emits one ``StairTile`` per
    ``stairs_up`` / ``stairs_down`` feature. The handler renders
    the tapering wedge + step lines + cave-theme fill polygon.
    """
    from nhc.rendering._stairs_svg import STAIR_FILL
    from nhc.rendering.ir._fb import Op, StairDirection
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.StairsOp import StairsOpT
    from nhc.rendering.ir._fb.StairTile import StairTileT

    ctx = builder.ctx
    level = ctx.level

    stairs: list[StairTileT] = []
    for y in range(level.height):
        for x in range(level.width):
            feat = level.tiles[y][x].feature
            if feat not in ("stairs_up", "stairs_down"):
                continue
            t = StairTileT()
            t.x = x
            t.y = y
            t.direction = (
                StairDirection.StairDirection.Down
                if feat == "stairs_down"
                else StairDirection.StairDirection.Up
            )
            stairs.append(t)
    if not stairs:
        return

    op = StairsOpT()
    op.stairs = stairs
    op.theme = ctx.theme
    op.fillColor = STAIR_FILL
    entry = OpEntryT()
    entry.opType = Op.Op.StairsOp
    entry.op = op
    builder.add_op(entry)


# ── Surface features layer (TileWalkLayer) ────────────────────


def _surface_features_paint(ctx: RenderContext) -> Iterable[str]:
    """Paint helper for the surface-features TileWalkLayer.

    The layer registers via :func:`make_tile_walk_layer` which
    builds the paint closure inline; this wrapper exists so per-
    layer parity tests can call ``_surface_features_paint(ctx)``
    by name, matching the convention the other ``_*_paint``
    helpers establish.
    """
    from nhc.rendering._decorators import walk_and_paint
    return walk_and_paint(
        ctx,
        _SURFACE_FEATURE_DECORATORS,
        layer_name="surface_features",
    )


def _emit_surface_features_ir(builder: "FloorIRBuilder") -> None:
    """Emit the IR ops for the surface-features layer.

    Sub-step 13-prep (transitional schema shift): the legacy
    ``walk_and_paint`` decorator pipeline is split per feature
    category — wells (``WELL_FEATURE`` + ``WELL_SQUARE_FEATURE``)
    feed ``WellFeatureOp.groups``, the five fountain decorators
    feed ``FountainFeatureOp.groups``, ``TREE_FEATURE`` feeds
    ``TreeFeatureOp.groups``, and ``BUSH_FEATURE`` feeds
    ``BushFeatureOp.groups``. The pre-rendered ``<g>`` groups
    still travel as opaque strings while sub-steps 13–16 land
    the per-category Rust ports; the dispatcher reads
    ``op.groups`` verbatim. After step 16 the field drops empty
    and Phase 7 cleanup removes it. The legacy
    ``GenericProceduralOp(name="surface_features")`` emit goes
    away in this commit.
    """
    from nhc.rendering._decorators import walk_and_paint
    from nhc.rendering.ir._fb import FountainShape, Op, WellShape
    from nhc.rendering.ir._fb.BushFeatureOp import BushFeatureOpT
    from nhc.rendering.ir._fb.FountainFeatureOp import (
        FountainFeatureOpT,
    )
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.TileCoord import TileCoordT
    from nhc.rendering.ir._fb.TreeFeatureOp import TreeFeatureOpT
    from nhc.rendering.ir._fb.WellFeatureOp import WellFeatureOpT

    ctx = builder.ctx
    seed = ctx.seed
    theme = ctx.theme
    level = ctx.level

    # Sub-step 13: walk well tiles per shape and emit one
    # WellFeatureOp per shape variant. The Rust port reads
    # op.tiles[] + op.shape; the legacy walk_and_paint pipeline
    # is no longer invoked for wells.
    well_round_tiles: list[tuple[int, int]] = []
    well_square_tiles: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            feature = level.tiles[y][x].feature
            if feature == "well":
                well_round_tiles.append((x, y))
            elif feature == "well_square":
                well_square_tiles.append((x, y))

    # Sub-step 14: fountain tiles split per shape variant.
    # Each FountainFeatureOp carries one shape (FountainShape enum).
    fountain_round: list[tuple[int, int]] = []
    fountain_square: list[tuple[int, int]] = []
    fountain_large_round: list[tuple[int, int]] = []
    fountain_large_square: list[tuple[int, int]] = []
    fountain_cross: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            feature = level.tiles[y][x].feature
            if feature == "fountain":
                fountain_round.append((x, y))
            elif feature == "fountain_square":
                fountain_square.append((x, y))
            elif feature == "fountain_large":
                fountain_large_round.append((x, y))
            elif feature == "fountain_large_square":
                fountain_large_square.append((x, y))
            elif feature == "fountain_cross":
                fountain_cross.append((x, y))
    tree_groups = list(walk_and_paint(
        ctx, [TREE_FEATURE], layer_name="surface_features",
    ))
    # Sub-step 16: bush tiles flow through the structured
    # BushFeatureOp; the legacy walk_and_paint passthrough is
    # gone for bushes. The vegetation_enabled context flag still
    # gates emission, mirroring the legacy ``requires=
    # frozenset({"vegetation_enabled"})`` on BUSH_FEATURE.
    bush_tiles: list[tuple[int, int]] = []
    if ctx.vegetation_enabled:
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature == "bush":
                    bush_tiles.append((x, y))

    for shape_kind, shape_tiles in (
        (WellShape.WellShape.Round, well_round_tiles),
        (WellShape.WellShape.Square, well_square_tiles),
    ):
        if not shape_tiles:
            continue
        op = WellFeatureOpT()
        op.seed = seed
        op.theme = theme
        op.shape = shape_kind
        op.tiles = [TileCoordT(x=x, y=y) for x, y in shape_tiles]
        entry = OpEntryT()
        entry.opType = Op.Op.WellFeatureOp
        entry.op = op
        builder.add_op(entry)

    for shape_kind, shape_tiles in (
        (FountainShape.FountainShape.Round, fountain_round),
        (FountainShape.FountainShape.Square, fountain_square),
        (FountainShape.FountainShape.LargeRound, fountain_large_round),
        (FountainShape.FountainShape.LargeSquare, fountain_large_square),
        (FountainShape.FountainShape.Cross, fountain_cross),
    ):
        if not shape_tiles:
            continue
        op = FountainFeatureOpT()
        op.seed = seed
        op.theme = theme
        op.shape = shape_kind
        op.tiles = [TileCoordT(x=x, y=y) for x, y in shape_tiles]
        entry = OpEntryT()
        entry.opType = Op.Op.FountainFeatureOp
        entry.op = op
        builder.add_op(entry)
    if tree_groups:
        op = TreeFeatureOpT()
        op.seed = seed
        op.theme = theme
        op.groups = tree_groups
        entry = OpEntryT()
        entry.opType = Op.Op.TreeFeatureOp
        entry.op = op
        builder.add_op(entry)
    if bush_tiles:
        op = BushFeatureOpT()
        op.seed = seed
        op.theme = theme
        op.tiles = [TileCoordT(x=x, y=y) for x, y in bush_tiles]
        entry = OpEntryT()
        entry.opType = Op.Op.BushFeatureOp
        entry.op = op
        builder.add_op(entry)


_SURFACE_FEATURE_DECORATORS: tuple[TileDecorator, ...] = (
    WELL_FEATURE,
    WELL_SQUARE_FEATURE,
    FOUNTAIN_FEATURE,
    FOUNTAIN_SQUARE_FEATURE,
    FOUNTAIN_LARGE_FEATURE,
    FOUNTAIN_LARGE_SQUARE_FEATURE,
    FOUNTAIN_CROSS_FEATURE,
    TREE_FEATURE,
    BUSH_FEATURE,
)


# ── Layer registry ────────────────────────────────────────────
#
# Order numbers preserve the legacy pass order: shadows=100,
# hatching=200, walls=300, terrain_tints=350, grid=400,
# floor_detail=500, terrain_detail=600, stairs=700,
# surface_features=800. Gaps of 100 leave room to slot future
# passes between existing ones.


FLOOR_LAYERS: tuple[Layer, ...] = (
    Layer(
        name="shadows",
        order=100,
        is_active=lambda ctx: ctx.shadows_enabled,
        paint=_shadows_paint,
    ),
    Layer(
        name="hatching",
        order=200,
        is_active=lambda ctx: ctx.hatching_enabled,
        paint=_hatching_paint,
    ),
    Layer(
        name="walls_and_floors",
        order=300,
        is_active=lambda ctx: True,
        paint=_walls_and_floors_paint,
    ),
    Layer(
        name="terrain_tints",
        order=350,
        is_active=lambda ctx: True,
        paint=_terrain_tints_paint,
    ),
    Layer(
        name="floor_grid",
        order=400,
        is_active=lambda ctx: True,
        paint=_floor_grid_paint,
    ),
    Layer(
        name="floor_detail",
        order=500,
        is_active=lambda ctx: True,
        paint=_floor_detail_paint,
    ),
    Layer(
        name="terrain_detail",
        order=600,
        is_active=lambda ctx: True,
        paint=_terrain_detail_paint,
    ),
    Layer(
        name="stairs",
        order=700,
        is_active=lambda ctx: True,
        paint=_stairs_paint,
    ),
    make_tile_walk_layer(
        name="surface_features",
        order=800,
        decorators=_SURFACE_FEATURE_DECORATORS,
    ),
)
