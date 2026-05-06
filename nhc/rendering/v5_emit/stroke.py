"""Builder / level walk → ``V5OpEntry(V5StrokeOp)``.

Phase 4.3a entry point. :func:`emit_strokes` walks the dungeon /
cave / corridor path of the wall stroke stream directly off
``builder.ctx`` + ``level`` — mirrors the room and cave-system
ExteriorWallOp emission branches in
:func:`nhc.rendering._floor_layers._emit_walls_and_floors_ir`
plus the merged CorridorWallOp emit.

For the site-enclosure and building-floor paths the function
falls back to walking ``builder.ops`` for the corresponding v4
``ExteriorWallOp`` / ``InteriorWallOp`` entries. Those paths
require a richer ctx surface (``site.enclosure.gates`` projection
helpers, building wall_material discovery) than the synthetic
fixtures currently expose; migrating them landed deferred behind
the 4.3b schema cut, where the wall stage rewrite happens together
with the schema flip.

:func:`translate_stroke_ops` is retained as a back-compat shim
for :func:`translate_all`.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5StrokeOp import V5StrokeOpT
from nhc.rendering.ir._fb.WallStyle import WallStyle
from nhc.rendering.v5_emit.materials import wall_material_from_wall_style


def _wrap(stroke_op: V5StrokeOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5StrokeOp
    entry.op = stroke_op
    return entry


def _make_stroke_op(
    *,
    region_ref: str = "",
    outline: Any | None = None,
    wall_material: Any,
    cuts: list[Any] | None = None,
) -> V5StrokeOpT:
    op = V5StrokeOpT()
    op.regionRef = region_ref
    op.outline = outline
    op.wallMaterial = wall_material
    op.cuts = list(cuts or [])
    return op


def emit_strokes(builder: Any) -> list[V5OpEntryT]:
    """Walk builder.ctx + level + builder.ops to produce V5StrokeOp
    entries.

    Dungeon / cave / corridor paths walk level + ctx directly. Site
    enclosure + building-floor wall ops fall back to walking
    builder.ops (deferred to the 4.3b cut). Defensive on synthetic
    fixture builders: returns an empty dungeon-path stream when
    ``level.tiles`` is missing, but still surfaces site / building
    walls via the ops fallback.
    """
    from nhc.dungeon.generators.cellular import CaveShape
    from nhc.dungeon.model import (
        CircleShape, CrossShape, HybridShape, LShape, OctagonShape,
        PillShape, RectShape, TempleShape,
    )
    from nhc.rendering._cave_geometry import _cave_raw_exterior_coords
    from nhc.rendering._floor_layers import (
        _collect_cave_systems, _collect_corridor_tiles,
    )
    from nhc.rendering._outline_helpers import (
        cuts_for_doorless_openings, cuts_for_room_corridor_openings,
        cuts_for_room_doors,
    )

    ctx = builder.ctx
    level = ctx.level

    result: list[V5OpEntryT] = []

    if getattr(level, "tiles", None) is not None:
        cave_tiles: set[tuple[int, int]] = (
            set(ctx.cave_tiles)
            if getattr(ctx, "cave_tiles", None) else set()
        )
        cave_region_rooms: set[int] = set()
        if cave_tiles:
            for idx, room in enumerate(level.rooms):
                if isinstance(room.shape, CaveShape):
                    cave_region_rooms.add(idx)
        suppress_room_walls = bool(getattr(ctx, "building_polygon", None))

        # 1. Rect rooms.
        if not suppress_room_walls:
            for room in level.rooms:
                if not isinstance(room.shape, RectShape):
                    continue
                wm = wall_material_from_wall_style(
                    WallStyle.DungeonInk,
                    corner_style=CornerStyle.Merlon,
                    seed=0,
                )
                cuts = (
                    cuts_for_room_doors(room, level)
                    + cuts_for_room_corridor_openings(room, level)
                )
                result.append(_wrap(_make_stroke_op(
                    region_ref=room.id,
                    wall_material=wm,
                    cuts=cuts,
                )))

        # 2. Smooth-shape rooms.
        if not suppress_room_walls:
            for idx, room in enumerate(level.rooms):
                if idx in cave_region_rooms:
                    continue
                shape = room.shape
                if not isinstance(shape, (
                    OctagonShape, LShape, TempleShape, CircleShape,
                    PillShape, CrossShape, HybridShape,
                )):
                    continue
                wm = wall_material_from_wall_style(
                    WallStyle.DungeonInk,
                    corner_style=CornerStyle.Merlon,
                    seed=0,
                )
                cuts = (
                    cuts_for_room_doors(room, level)
                    + cuts_for_doorless_openings(room, level)
                )
                result.append(_wrap(_make_stroke_op(
                    region_ref=room.id,
                    wall_material=wm,
                    cuts=cuts,
                )))

        # 3. Cave systems.
        if cave_tiles:
            for i, tile_group in enumerate(_collect_cave_systems(cave_tiles)):
                coords = _cave_raw_exterior_coords(tile_group)
                if not coords or len(coords) < 4:
                    continue
                wm = wall_material_from_wall_style(
                    WallStyle.CaveInk,
                    corner_style=CornerStyle.Merlon,
                    seed=0,
                )
                result.append(_wrap(_make_stroke_op(
                    region_ref=f"cave.{i}",
                    wall_material=wm,
                    cuts=[],
                )))

        # 4. Corridor (single op).
        corridor_tiles = _collect_corridor_tiles(level, cave_tiles)
        if corridor_tiles:
            wm = wall_material_from_wall_style(WallStyle.DungeonInk)
            result.append(_wrap(_make_stroke_op(
                region_ref="corridor",
                wall_material=wm,
                cuts=[],
            )))

    # 5. + 6. Site enclosure + building-floor walls. These paths
    # rely on richer ctx surface than synthetic fixtures expose;
    # migration deferred to the 4.3b schema cut. For now walk
    # builder.ops for any ExteriorWallOp / InteriorWallOp / Corridor
    # that the dungeon-path block above didn't already emit (i.e.
    # ops whose region_ref isn't a room / cave / corridor we
    # already covered).
    seen_region_refs = {
        entry.op.regionRef
        for entry in result
        if entry.op.regionRef
    }
    for entry in builder.ops:
        op_type = getattr(entry, "opType", None)
        if op_type == Op.ExteriorWallOp:
            ext = entry.op
            ext_rr = ext.regionRef.decode() if isinstance(
                ext.regionRef, bytes
            ) else (ext.regionRef or "")
            if ext_rr and ext_rr in seen_region_refs:
                continue
            wm = wall_material_from_wall_style(
                ext.style,
                corner_style=ext.cornerStyle,
                seed=int(getattr(ext, "rngSeed", 0) or 0),
            )
            result.append(_wrap(_make_stroke_op(
                region_ref=ext_rr,
                wall_material=wm,
                cuts=list(ext.cuts or []),
            )))
        elif op_type == Op.InteriorWallOp:
            interior = entry.op
            wm = wall_material_from_wall_style(interior.style)
            result.append(_wrap(_make_stroke_op(
                outline=interior.outline,
                wall_material=wm,
                cuts=list(interior.cuts or []),
            )))
        elif op_type == Op.CorridorWallOp:
            corridor = entry.op
            corr_rr = "corridor"
            if corr_rr in seen_region_refs:
                continue
            wm = wall_material_from_wall_style(corridor.style)
            result.append(_wrap(_make_stroke_op(
                region_ref=corr_rr,
                wall_material=wm,
                cuts=[],
            )))

    return result


def translate_stroke_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate v4 wall ops into ``V5StrokeOp`` entries.

    Retained for back-compat with :func:`translate_all`.
    """
    result: list[V5OpEntryT] = []
    for entry in ops:
        op_type = getattr(entry, "opType", None)
        if op_type == Op.ExteriorWallOp:
            ext = entry.op
            wm = wall_material_from_wall_style(
                ext.style,
                corner_style=ext.cornerStyle,
                seed=int(getattr(ext, "rngSeed", 0) or 0),
            )
            result.append(_wrap(_make_stroke_op(
                region_ref=ext.regionRef or "",
                wall_material=wm,
                cuts=list(ext.cuts or []),
            )))
        elif op_type == Op.InteriorWallOp:
            interior = entry.op
            wm = wall_material_from_wall_style(interior.style)
            result.append(_wrap(_make_stroke_op(
                outline=interior.outline,
                wall_material=wm,
                cuts=list(interior.cuts or []),
            )))
        elif op_type == Op.CorridorWallOp:
            corridor = entry.op
            wm = wall_material_from_wall_style(corridor.style)
            result.append(_wrap(_make_stroke_op(
                region_ref="corridor",
                wall_material=wm,
                cuts=[],
            )))
    return result
