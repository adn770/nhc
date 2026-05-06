"""Builder / level walk → ``V5OpEntry(V5StrokeOp)``.

:func:`emit_strokes` walks ``builder.ctx`` + ``level`` + ``site``
to produce the v5 wall stroke stream — mirrors the
ExteriorWallOp / InteriorWallOp / CorridorWallOp emission order
across :func:`_emit_walls_and_floors_ir`,
:func:`emit_site_overlays`, and :func:`emit_building_overlays`.

Ordering matches the v4 IR_STAGES sequence so the v5 op stream
stays positionally identical to the legacy translator output:

1. Per RectShape room ExteriorWallOp(DungeonInk).
2. Per smooth-shape room ExteriorWallOp(DungeonInk).
3. Per disjoint cave system ExteriorWallOp(CaveInk).
4. Single CorridorWallOp(DungeonInk).
5. Site enclosure ExteriorWallOp (when ``builder.site`` is set
   and the level is the site's surface).
6. Building-floor InteriorWallOps + masonry ExteriorWallOp (when
   ``builder.site`` is set and ``level.building_id`` matches one
   of ``site.buildings``).
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.StrokeOp import StrokeOpT
from nhc.rendering.emit.materials import (
    STONE_ASHLAR, STONE_BRICK, WOOD_OAK,
    wall_material_fortification, wall_material_masonry,
    wall_material_palisade, wall_material_partition,
    wall_material_plain_stroke,
)


def _wrap(stroke_op: StrokeOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.StrokeOp
    entry.op = stroke_op
    return entry


def _make_stroke_op(
    *,
    region_ref: str = "",
    outline: Any | None = None,
    wall_material: Any,
    cuts: list[Any] | None = None,
) -> StrokeOpT:
    op = StrokeOpT()
    op.regionRef = region_ref
    op.outline = outline
    op.wallMaterial = wall_material
    op.cuts = list(cuts or [])
    return op


def emit_strokes(builder: Any) -> list[OpEntryT]:
    """Walk builder.ctx + level + site to produce V5StrokeOp entries.

    Defensive on synthetic fixture builders: skips the dungeon-path
    (rect / smooth / cave / corridor) layer when the level lacks
    per-tile data, but still surfaces site / building strokes when
    the matching builder.site stub is present.
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
    result: list[OpEntryT] = []

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
                wm = wall_material_plain_stroke()
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
                wm = wall_material_plain_stroke()
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
                wm = wall_material_plain_stroke()
                result.append(_wrap(_make_stroke_op(
                    region_ref=f"cave.{i}",
                    wall_material=wm,
                    cuts=[],
                )))

        # 4. Corridor (single op).
        corridor_tiles = _collect_corridor_tiles(level, cave_tiles)
        if corridor_tiles:
            wm = wall_material_plain_stroke()
            result.append(_wrap(_make_stroke_op(
                region_ref="corridor",
                wall_material=wm,
                cuts=[],
            )))

    # 5. Site enclosure (when site.surface == level).
    site = getattr(builder, "site", None)
    if site is not None and level is getattr(site, "surface", None):
        result.extend(_emit_site_enclosure_strokes(builder, site))

    # 6. Building-floor walls (when level.building_id matches a
    # building in site.buildings).
    if site is not None:
        building_id = getattr(level, "building_id", None)
        if building_id is not None:
            for i, b in enumerate(getattr(site, "buildings", []) or []):
                if b.id == building_id:
                    result.extend(_emit_building_floor_strokes(
                        builder, b, level, building_index=i,
                    ))
                    break

    return result


def _emit_site_enclosure_strokes(
    builder: Any, site: Any,
) -> list[OpEntryT]:
    """Replicate :func:`emit_site_enclosure` as v5 strokes.

    Reads ``site.enclosure.kind`` / ``.polygon`` / ``.gates``.
    Gate format dispatch:

    - Real :class:`Site.Enclosure` ships ``(x, y, length_tiles)``
      int triples; we project them to ``(edge_idx, t, half_px)``
      via closest-edge mapping (same logic as
      :func:`emit_site_overlays`).
    - Synthetic fixtures ship pre-projected ``(edge_idx, t,
      half_px)`` triples (detected via float in slots 1 / 2);
      passed through unchanged.
    """
    from nhc.rendering._outline_helpers import cuts_for_enclosure_gates
    from nhc.rendering._svg_helpers import CELL, PADDING

    enclosure = getattr(site, "enclosure", None)
    if enclosure is None:
        return []
    kind = enclosure.kind
    if kind not in ("palisade", "fortification"):
        return []
    if len(enclosure.polygon) < 3:
        return []

    coords_px = [
        (float(x * CELL), float(y * CELL))
        for (x, y) in enclosure.polygon
    ]
    poly_px = [
        (PADDING + x * CELL, PADDING + y * CELL)
        for (x, y) in enclosure.polygon
    ]
    n = len(poly_px)

    raw_gates = list(enclosure.gates or [])
    gates_param: list[tuple[int, float, float]] = []
    for gate in raw_gates:
        if (
            len(gate) == 3
            and isinstance(gate[1], float)
        ):
            # Pre-projected (edge_idx, t_center, half_px).
            gates_param.append(
                (int(gate[0]), float(gate[1]), float(gate[2]))
            )
            continue
        # Real Site format: (x, y, length_tiles) — closest-edge
        # projection (mirrors emit_site_overlays).
        gx, gy, length_tiles = gate
        gx_px = PADDING + gx * CELL
        gy_px = PADDING + gy * CELL
        best_idx = 0
        best_d = float("inf")
        best_t = 0.5
        for i in range(n):
            ax, ay = poly_px[i]
            bx, by = poly_px[(i + 1) % n]
            dx, dy = bx - ax, by - ay
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq == 0:
                continue
            t = max(0.0, min(1.0, (
                (gx_px - ax) * dx + (gy_px - ay) * dy
            ) / seg_len_sq))
            ix = ax + dx * t
            iy = ay + dy * t
            d = (ix - gx_px) ** 2 + (iy - gy_px) ** 2
            if d < best_d:
                best_d = d
                best_idx = i
                best_t = t
        gates_param.append(
            (best_idx, best_t, float(length_tiles) * CELL / 2.0),
        )
    cuts = cuts_for_enclosure_gates(
        coords_px, gates_param, CutStyle.WoodGate,
    )
    base_seed = builder.ctx.seed
    rng_seed = (base_seed + 0xE101) & 0xFFFFFFFFFFFFFFFF
    corner_style = getattr(enclosure, "corner_style", CornerStyle.Merlon)
    if kind == "palisade":
        wm = wall_material_palisade(
            corner_style=corner_style, seed=rng_seed,
        )
    else:
        wm = wall_material_fortification(
            corner_style=corner_style, seed=rng_seed,
        )
    return [_wrap(_make_stroke_op(
        region_ref="enclosure",
        wall_material=wm,
        cuts=cuts,
    ))]


def _emit_building_floor_strokes(
    builder: Any, building: Any, level: Any, *, building_index: int,
) -> list[OpEntryT]:
    """Replicate :func:`emit_building_walls` as v5 strokes."""
    from nhc.rendering._outline_helpers import (
        cuts_for_building_doors, outline_from_polygon,
    )
    from nhc.rendering._svg_helpers import CELL
    from nhc.rendering.ir_emitter import (
        _coalesced_interior_edges, _tile_corner_delta,
    )

    # Map building.interior_wall_material → v5 partition (family, style).
    _PARTITION_FAMILY_STYLE: dict[str, tuple[int, int]] = {
        "stone": (MaterialFamily.Stone, STONE_ASHLAR),
        "brick": (MaterialFamily.Stone, STONE_BRICK),
        "wood":  (MaterialFamily.Wood,  WOOD_OAK),
    }
    # Map building.wall_material → v5 masonry (family, style).
    _MASONRY_FAMILY_STYLE: dict[str, tuple[int, int]] = {
        "brick": (MaterialFamily.Stone, STONE_BRICK),
        "stone": (MaterialFamily.Stone, STONE_ASHLAR),
    }

    result: list[OpEntryT] = []

    edges = _coalesced_interior_edges(level)
    if edges:
        family, style = _PARTITION_FAMILY_STYLE.get(
            getattr(building, "interior_wall_material", "stone"),
            (MaterialFamily.Stone, STONE_ASHLAR),
        )
        wm = wall_material_partition(family=family, style=style, seed=0)
        for (ax, ay, a_corner, bx, by, b_corner) in edges:
            adx, ady = _tile_corner_delta(a_corner)
            bdx, bdy = _tile_corner_delta(b_corner)
            point_a = ((ax + adx) * CELL, (ay + ady) * CELL)
            point_b = ((bx + bdx) * CELL, (by + bdy) * CELL)
            outline = outline_from_polygon(
                [point_a, point_b], closed=False,
            )
            result.append(_wrap(_make_stroke_op(
                outline=outline,
                wall_material=wm,
                cuts=[],
            )))

    wall_material = getattr(building, "wall_material", None)
    if wall_material in _MASONRY_FAMILY_STYLE:
        family, style = _MASONRY_FAMILY_STYLE[wall_material]
        base_seed = builder.ctx.seed
        rng_seed = (
            base_seed + 0xBE71 + building_index
        ) & 0xFFFFFFFFFFFFFFFF
        wm = wall_material_masonry(
            family=family, style=style,
            corner_style=CornerStyle.Merlon, seed=rng_seed,
        )
        cuts = cuts_for_building_doors(building, level)
        result.append(_wrap(_make_stroke_op(
            region_ref=f"building.{building_index}",
            wall_material=wm,
            cuts=cuts,
        )))

    return result
