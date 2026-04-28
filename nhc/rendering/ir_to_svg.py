"""IR → SVG transformer.

Cold-path transformer: consumes a ``FloorIR`` FlatBuffer and emits
the SVG string ``render_floor_svg`` used to produce. The byte-equal
gate in :mod:`tests.unit.test_ir_to_svg` is the contract that
protects every Phase 1–7 transition.

Phase 1.a wired the envelope (``<svg>`` header, background rect,
``<g transform>`` translate) and the dispatch loop. Phase 1.b.1
adds the ``ShadowOp(Corridor)`` handler and the
:func:`layer_to_svg` helper that grounds every per-layer parity
test in the rest of Phase 1. Subsequent layer commits (1.b.2 +
1.c–1.j) register one handler per op kind; Phase 1.k populates the
fixture ``.nir`` files and the integration parity gate flips green.

Op-handler signature::

    handler(op_entry: OpEntry, fir: FloorIR) -> list[str]

Each handler returns a list of SVG element-line strings that are
``\\n``-joined with the rest of the output, matching the legacy
``render_layers`` joining behaviour.
"""

from __future__ import annotations

import re

from typing import Any, Callable

from nhc.rendering._svg_helpers import (
    BG, CAVE_FLOOR_COLOR, CELL, FLOOR_COLOR, GRID_WIDTH,
    HATCH_UNDERLAY, INK, WALL_WIDTH, _wobbly_grid_seg,
)
from nhc.rendering.ir._fb import (
    HatchKind, Op, ShadowKind, StairDirection, TerrainKind,
)
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir._fb.Op import OpCreator
from nhc.rendering.ir._fb.OpEntry import OpEntry
from nhc.rendering.ir._fb.Region import Region


# Maps Op union tag → handler. Layer commits 1.b–1.j each register
# one entry; an op surfacing without a handler is a contract
# violation, not an extensibility hook.
_OP_HANDLERS: dict[int, Callable[[OpEntry, FloorIR], list[str]]] = {}


# Layer render order. Mirrors `nhc/rendering/_floor_layers.py:FLOOR_LAYERS`
# (sorted by `Layer.order`) so `ir_to_svg` emits the per-layer comment
# stats and op output in the same sequence as the legacy
# `render_layers`. Source of truth: design/map_ir.md §6.
_LAYER_ORDER: tuple[str, ...] = (
    "shadows",
    "hatching",
    "walls_and_floors",
    "terrain_tints",
    "floor_grid",
    "floor_detail",
    "thematic_detail",
    "terrain_detail",
    "stairs",
    "surface_features",
)


# Element-tag counter mirroring `_pipeline._OPEN_TAG` so the IR-
# driven renderer reports the same per-layer element count in its
# `<!-- layer.NAME: N elements, M bytes -->` comment.
_OPEN_TAG = re.compile(r"<[a-zA-Z]")


# Maps layer name → set of Op union tags belonging to that layer.
# Source: design/map_ir.md §6 layer ordering. Each layer commit
# adds an entry as it lands its first op; the dict is the contract
# the per-layer parity tests dispatch against.
_LAYER_OPS: dict[str, frozenset[int]] = {
    "shadows": frozenset({Op.Op.ShadowOp}),
    "hatching": frozenset({Op.Op.HatchOp}),
    "walls_and_floors": frozenset({Op.Op.WallsAndFloorsOp}),
    "terrain_tints": frozenset({Op.Op.TerrainTintOp}),
    "floor_grid": frozenset({Op.Op.FloorGridOp}),
    "floor_detail": frozenset({
        Op.Op.FloorDetailOp,
        # Sub-step 5 (Q2 schema bump B): the structured
        # decorator pipeline rides in the same layer slot as the
        # legacy passthrough. Per-variant ports (sub-steps 6–12)
        # populate ``DecoratorOp``'s vectors one decorator at a
        # time; the passthrough (``FloorDetailOp.decorator_groups``)
        # keeps serving rendering until step 12 lands.
        Op.Op.DecoratorOp,
    }),
    "thematic_detail": frozenset({Op.Op.ThematicDetailOp}),
    "terrain_detail": frozenset({Op.Op.TerrainDetailOp}),
    "stairs": frozenset({Op.Op.StairsOp}),
    "surface_features": frozenset({
        Op.Op.WellFeatureOp,
        Op.Op.FountainFeatureOp,
        Op.Op.TreeFeatureOp,
        Op.Op.BushFeatureOp,
        # Phase 1 transitional — _emit_surface_features_ir
        # produces a single GenericProceduralOp(name="surface_features")
        # that carries the layer's pre-rendered groups. The four
        # dedicated ops above stay schema-reserved for Phase 4's
        # structured port.
        Op.Op.GenericProceduralOp,
    }),
}


_BARE_SKIP_LAYERS: frozenset[str] = frozenset({
    "floor_detail",
    "thematic_detail",
    "terrain_detail",
    "surface_features",
})


def ir_to_svg(buf: bytes, *, bare: bool = False) -> str:
    """Render a ``FloorIR`` FlatBuffer to its legacy SVG output.

    Layers stream in :data:`_LAYER_ORDER` sequence, each prefixed
    by a ``<!-- layer.NAME: N elements, M bytes -->`` comment that
    matches the legacy ``_pipeline.render_layers`` shape — the
    self-describing stats the byte-equal parity gate locks in.

    ``bare=True`` (Phase 2.5 of plans/nhc_ir_migration_plan.md)
    elides the decoration layers (``floor_detail``,
    ``terrain_detail``, ``surface_features``) entirely — same
    "skip layer, skip comment" shape that the inactive-flag path
    uses for shadows / hatching. Used by the ``?bare=1`` query
    parameter on the .svg route for /admin debug visualisation,
    where seeing the underlying geometry matters more than seeing
    the cobblestone overlay.
    """
    fir = _root_or_raise(buf)
    cell = fir.Cell()
    padding = fir.Padding()
    w = fir.WidthTiles() * cell + 2 * padding
    h = fir.HeightTiles() * cell + 2 * padding

    parts: list[str] = [
        (
            f'<svg width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" '
            'xmlns="http://www.w3.org/2000/svg">'
        ),
        f'<rect width="100%" height="100%" fill="{BG}"/>',
        f'<g transform="translate({padding},{padding})">',
    ]
    flags = fir.Flags()
    inactive: set[str] = set()
    if flags is not None:
        # Shadows + hatching are gated on RenderContext flags in
        # the legacy `FLOOR_LAYERS`. When inactive, `render_layers`
        # skips the layer entirely (no comment, no fragments) — the
        # IR matches by suppressing the comment header here. The
        # other seven layers default to active.
        if not flags.ShadowsEnabled():
            inactive.add("shadows")
        if not flags.HatchingEnabled():
            inactive.add("hatching")
    if bare:
        inactive |= _BARE_SKIP_LAYERS
    for layer_name in _LAYER_ORDER:
        if layer_name in inactive:
            continue
        layer_frags = _dispatch_ops(
            fir, op_filter=_LAYER_OPS[layer_name],
        )
        joined = "".join(layer_frags)
        n_elements = len(_OPEN_TAG.findall(joined))
        n_bytes = len(joined)
        parts.append(
            f"<!-- layer.{layer_name}: {n_elements} elements, "
            f"{n_bytes} bytes -->"
        )
        parts.extend(layer_frags)
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


def layer_to_svg(buf: bytes, *, layer: str) -> str:
    """Render only the ops belonging to ``layer``.

    Returns the joined SVG fragment for the layer, no envelope.
    Per-layer parity tests in 1.b–1.j use this to compare the
    IR-rendered slice against the legacy paint-helper output for
    one layer in isolation, so a regression bisects to a single
    layer commit instead of "something broke between 1.b and 1.j".
    """
    if layer not in _LAYER_OPS:
        raise KeyError(
            f"unknown layer: {layer!r}; known layers: "
            f"{sorted(_LAYER_OPS)}"
        )
    fir = _root_or_raise(buf)
    return "\n".join(_dispatch_ops(fir, op_filter=_LAYER_OPS[layer]))


def _root_or_raise(buf: bytes) -> FloorIR:
    if not FloorIR.FloorIRBufferHasIdentifier(buf, 0):
        raise ValueError(
            "Buffer does not carry the NIRF file_identifier — is "
            "this a FloorIR buffer at the current schema major?"
        )
    return FloorIR.GetRootAs(buf, 0)


def _dispatch_ops(
    fir: FloorIR,
    *,
    op_filter: frozenset[int] | None,
) -> list[str]:
    parts: list[str] = []
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        op_type = entry.OpType()
        if op_filter is not None and op_type not in op_filter:
            continue
        handler = _OP_HANDLERS.get(op_type)
        if handler is None:
            raise NotImplementedError(
                f"no IR→SVG handler registered for Op tag {op_type}; "
                "the matching Phase 1 layer commit must register one"
            )
        parts.extend(handler(entry, fir))
    return parts


# ── Op handlers ─────────────────────────────────────────────────


def _draw_shadow_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Reproduce ``_render_room_shadows`` / ``_render_corridor_shadows``.

    Phase 4.2 — the per-tile corridor rects and the per-shape
    room shadows live in
    ``crates/nhc-render/src/primitives/shadow.rs`` and are reached
    via the four ``nhc_render.draw_*_shadow*`` functions. The Python
    side resolves the room region's shape_tag from the IR and
    dispatches; the legacy 0.08-opacity / +3-offset / #000000-ink
    constants are baked into the Rust side.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    kind = op.kind
    if kind == ShadowKind.ShadowKind.Corridor:
        tiles = [(t.x, t.y) for t in op.tiles]
        return nhc_render.draw_corridor_shadows(tiles)
    if kind == ShadowKind.ShadowKind.Room:
        return [_draw_room_shadow(op, fir)]
    raise ValueError(f"unknown ShadowKind: {kind}")


def _draw_room_shadow(op: Any, fir: FloorIR) -> str:  # type: ignore[name-defined]
    """Reproduce ``_shadows._room_shadow_svg`` from the IR.

    Dispatches on the referenced region's ``shape_tag`` and routes
    to the matching Rust primitive (rect / octagon / cave). The
    cave→rect fallback that
    :func:`nhc.rendering.ir_emitter._room_region_data` collapses
    into ``shape_tag == "rect"`` is handled by the rect branch.
    """
    import nhc_render

    region = _find_region(fir, op.regionRef)
    if region is None:
        raise ValueError(
            f"ShadowOp(Room) references unknown region "
            f"{op.regionRef!r}; emit_regions must register one"
        )
    shape_tag = region.ShapeTag()
    coords = _polygon_paths_to_coords(region.Polygon())

    if shape_tag == b"rect":
        return nhc_render.draw_room_shadow_rect(coords)
    if shape_tag == b"octagon":
        return nhc_render.draw_room_shadow_octagon(coords)
    if shape_tag == b"cave":
        return nhc_render.draw_room_shadow_cave(coords)

    raise NotImplementedError(
        f"Room shadow handler for shape_tag {shape_tag!r} not "
        "implemented; the starter fixtures only exercise rect / "
        "octagon / cave"
    )


def _find_region(fir: FloorIR, region_ref: bytes) -> Region | None:
    """Linear scan of regions[] by id.

    Cheap for the starter fixtures (~20 regions × ~20 room ops per
    parity test). Revisit with a regions-by-id dict if a fixture
    grows past a couple hundred regions and the lookup shows up in
    the fast-suite timing budget.
    """
    for j in range(fir.RegionsLength()):
        region = fir.Regions(j)
        if region.Id() == region_ref:
            return region
    return None


def _polygon_paths_to_coords(polygon: Any) -> list[tuple[float, float]]:
    """Flatten a single-ring FB Polygon into an (x, y) coord list.

    The single-ring assumption matches every region the room shadow
    handler resolves: ``_room_region_data`` builds rect / octagon /
    cave polygons via ``_coords_to_polygon`` which always emits one
    exterior ring with no holes. If a future commit registers
    multi-ring room regions, this helper will need a rings-aware
    counterpart.
    """
    return [
        (polygon.Paths(i).X(), polygon.Paths(i).Y())
        for i in range(polygon.PathsLength())
    ]


_OP_HANDLERS[Op.Op.ShadowOp] = _draw_shadow_from_ir


def _draw_hatch_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Dispatch to the corridor / room / hole hatch handler.

    Sub-step 1.e (plan §8) routes Corridor + Room through the Rust
    `nhc_render.draw_hatch_*` entry points; the relaxed parity gate
    (1.a invariants + 1.f snapshot lock) replaces the legacy
    byte-equal contract for these branches. Hole stays schema-
    reserved — the emitter never produces it under the Phase 1
    contract.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    if op.kind == HatchKind.HatchKind.Corridor:
        return _draw_hatch_corridor(op)
    if op.kind == HatchKind.HatchKind.Room:
        return _draw_hatch_room(op, fir)
    if op.kind == HatchKind.HatchKind.Hole:
        # Schema-reserved; the legacy `_render_hole_hatching` is
        # never wired into `_hatching_paint` in Phase 1, so a Hole
        # op surfacing here is a contract violation.
        raise NotImplementedError(
            "Hole hatching is schema-reserved but unused in Phase "
            "1; the emitter must not produce HatchOp(kind=Hole)"
        )
    raise ValueError(f"unknown HatchKind: {op.kind}")


def _draw_hatch_corridor(op: Any) -> list[str]:
    """Corridor halo — Phase 4 sub-step 1.e: delegate to Rust.

    The Rust impl
    (``crates/nhc-render/src/primitives/hatch.rs::draw_hatch_corridor``)
    owns the per-tile painting (stone scatter, section
    partitioning, Perlin-wobbled strokes); this handler wraps the
    three returned fragment buckets in the legacy
    ``<g opacity="...">`` envelopes. The relaxed parity gate
    (sub-step 1.a invariants + 1.f snapshot lock) is the contract
    going forward — byte-equal-with-legacy is dropped.
    """
    import nhc_render

    tiles = [(t.x, t.y) for t in op.tiles]
    if not tiles:
        return []
    tile_fills, hatch_lines, hatch_stones = (
        nhc_render.draw_hatch_corridor(tiles, op.seed)
    )
    out: list[str] = []
    if tile_fills:
        out.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        out.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        out.append(f'<g>{"".join(hatch_stones)}</g>')
    return out


def _draw_hatch_room(op: Any, fir: FloorIR) -> list[str]:
    """Room halo — Phase 4 sub-step 1.e: delegate to Rust.

    Sub-step 1.b shifted the candidate walk + Perlin distance
    filter to the emitter; sub-step 1.d ported the painting
    passes to Rust
    (``crates/nhc-render/src/primitives/hatch.rs::draw_hatch_room``).
    This handler resolves the dungeon-region polygon for the
    clipPath envelope, calls into Rust for the three SVG fragment
    buckets, and wraps the result. The clipPath construction
    stays Python-side because it depends on the IR's
    ``op.regionOut`` polygon directly — exposing the FB Polygon
    walker through PyO3 would buy nothing under the relaxed
    parity gate. The Hole kind is unreachable at the dispatcher
    level; this branch only handles Room.
    """
    import nhc_render

    region = _find_region(fir, op.regionOut)
    if region is None:
        return []
    tiles = [(t.x, t.y) for t in op.tiles]
    if not tiles:
        return []

    is_outer_raw = op.isOuter
    if is_outer_raw is None:
        is_outer = [False] * len(tiles)
    else:
        # ``isOuter`` may surface as a numpy array; normalise to a
        # list[bool] for the PyO3 boundary.
        is_outer = [bool(b) for b in is_outer_raw]

    tile_fills, hatch_lines, hatch_stones = (
        nhc_render.draw_hatch_room(tiles, is_outer, op.seed)
    )
    if not (tile_fills or hatch_lines or hatch_stones):
        return []

    # Outer rect + dungeon polygon path produces an evenodd clip
    # that hatches everything outside the dungeon floor — see the
    # rationale comment in `_render_hatching`. Holes inside cave
    # walls flip back to "hatch" by re-including the hole rings.
    width = fir.WidthTiles()
    height = fir.HeightTiles()
    map_w = width * CELL
    map_h = height * CELL
    margin = CELL * 2
    clip_d = (
        f"M{-margin},{-margin} "
        f"H{map_w + margin} V{map_h + margin} "
        f"H{-margin} Z "
    )
    poly = region.Polygon()
    for i in range(poly.RingsLength()):
        ring = poly.Rings(i)
        start = ring.Start()
        count = ring.Count()
        coords = [
            (poly.Paths(start + j).X(), poly.Paths(start + j).Y())
            for j in range(count)
        ]
        clip_d += f"M{coords[0][0]:.0f},{coords[0][1]:.0f} "
        clip_d += " ".join(
            f"L{x:.0f},{y:.0f}" for x, y in coords[1:]
        )
        clip_d += " Z "

    out: list[str] = [
        f'<defs><clipPath id="hatch-clip">'
        f'<path d="{clip_d}" clip-rule="evenodd"/>'
        f'</clipPath></defs>',
        '<g clip-path="url(#hatch-clip)">',
    ]
    if tile_fills:
        out.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        out.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        out.append(f'<g>{"".join(hatch_stones)}</g>')
    out.append("</g>")
    return out


_OP_HANDLERS[Op.Op.HatchOp] = _draw_hatch_from_ir


def _draw_walls_and_floors_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_walls_and_floors``.

    Phase 4.4 — partial port. Structural geometry (smooth-room
    outlines, cave region path, wall extension data) is computed
    Python-side during emission and travels into Rust as
    pre-rendered SVG fragment strings; only the stroke-emission
    envelope (rect emission for corridor tiles + rect rooms, and
    the two ``/>``-replacement wraps around the cave region) lives
    in ``crates/nhc-render/src/primitives/walls_and_floors.rs``.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    corridor_tiles = [
        (t.x, t.y) for t in (op.corridorTiles or [])
    ]
    rect_rooms = [
        (rr.x, rr.y, rr.w, rr.h) for rr in (op.rectRooms or [])
    ]
    smooth_fills = [_to_str(s) for s in (op.smoothFillSvg or [])]
    smooth_walls = [_to_str(s) for s in (op.smoothWallSvg or [])]
    wall_segments = [_to_str(s) for s in (op.wallSegments or [])]
    return nhc_render.draw_walls_and_floors(
        corridor_tiles,
        rect_rooms,
        smooth_fills,
        _to_str(op.caveRegion),
        smooth_walls,
        _to_str(op.wallExtensionsD),
        wall_segments,
    )


def _to_str(value: Any) -> str:
    """FB strings surface as bytes; decode to str at the boundary."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8")
    return value


_OP_HANDLERS[Op.Op.WallsAndFloorsOp] = _draw_walls_and_floors_from_ir


def _draw_terrain_tint_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_terrain_tints``.

    Phase 4.1 — the per-tile tint rect emission and the per-room
    wash emission live in
    ``crates/nhc-render/src/primitives/terrain_tints.rs`` and are
    reached via ``nhc_render.draw_terrain_tints``. The Python
    side resolves the palette from ``fir.theme`` (display data,
    stays Python-side) and owns the dungeon-interior clip
    envelope (the IR's region polygon stays Python-side too —
    only the layer's RNG-free string emission moved to Rust).
    """
    import nhc_render
    from nhc.rendering.terrain_palette import get_palette

    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []

    theme = _to_str(fir.Theme())
    palette = get_palette(theme)
    # Discriminant-keyed palette (matches `TerrainKind` in
    # `floor_ir.fbs`: Water=1, Lava=2, Chasm=3, Grass=4; None=0
    # is the schema sentinel and never appears in emitted tiles).
    palette_map = {
        TerrainKind.TerrainKind.Water: (
            palette.water.tint, palette.water.tint_opacity),
        TerrainKind.TerrainKind.Lava: (
            palette.lava.tint, palette.lava.tint_opacity),
        TerrainKind.TerrainKind.Chasm: (
            palette.chasm.tint, palette.chasm.tint_opacity),
        TerrainKind.TerrainKind.Grass: (
            palette.grass.tint, palette.grass.tint_opacity),
    }
    tiles = [
        (tile.x, tile.y, int(tile.kind))
        for tile in (op.tiles or [])
    ]
    washes = [
        (w.x, w.y, w.w, w.h, _to_str(w.color), float(w.opacity))
        for w in (op.roomWashes or [])
    ]
    tint_rects, wash_rects = nhc_render.draw_terrain_tints(
        tiles, palette_map, washes,
    )

    clip_id = _to_str(op.clipRegion)
    if tint_rects:
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "terrain-clip"))
                out.append('<g clip-path="url(#terrain-clip)">')
                out.extend(tint_rects)
                out.append("</g>")
            else:
                out.extend(tint_rects)
        else:
            out.extend(tint_rects)

    out.extend(wash_rects)
    return out


def _dungeon_clip_defs(poly: Any, clip_id: str) -> str:
    """Build the legacy ``_dungeon_interior_clip`` defs element.

    Walks every ring (exterior + holes) once, M / L / Z encoded
    with ``:.0f`` formatting, ``fill-rule="evenodd"`` so the holes
    cut the clipped region. Reused by terrain tints (1.e) and any
    later layer that needs a dungeon-interior clip.
    """
    clip_d = ""
    for i in range(poly.RingsLength()):
        ring = poly.Rings(i)
        start = ring.Start()
        count = ring.Count()
        coords = [
            (poly.Paths(start + j).X(), poly.Paths(start + j).Y())
            for j in range(count)
        ]
        clip_d += f"M{coords[0][0]:.0f},{coords[0][1]:.0f} "
        clip_d += " ".join(
            f"L{x:.0f},{y:.0f}" for x, y in coords[1:]
        )
        clip_d += " Z "
    return (
        f'<defs><clipPath id="{clip_id}">'
        f'<path d="{clip_d}" fill-rule="evenodd"/>'
        f'</clipPath></defs>'
    )


_OP_HANDLERS[Op.Op.TerrainTintOp] = _draw_terrain_tint_from_ir


def _draw_floor_grid_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_floor_grid``.

    Phase 3 canary — the per-edge wobbly-grid segment generator
    lives in ``crates/nhc-render/src/primitives/floor_grid.rs`` and
    is reached via ``nhc_render.draw_floor_grid``. The byte-equal
    parity gate is ``tests/unit/test_emit_floor_grid_parity.py``.
    Python keeps ownership of the SVG envelope (clip-path defs,
    ``<path>`` wrapping) because those bits are not RNG-sensitive
    and the IR's region polygon stays Python-side.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    width = fir.WidthTiles()
    height = fir.HeightTiles()
    tiles = [
        (tile.x, tile.y, bool(tile.isCorridor))
        for tile in (op.tiles or [])
    ]
    room_d, corridor_d = nhc_render.draw_floor_grid(
        width, height, tiles, op.seed,
    )

    style = (
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{GRID_WIDTH}" '
        f'opacity="0.7" stroke-linecap="round"'
    )

    out: list[str] = []
    if room_d:
        clip_id = _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "grid-clip"))
                out.append(
                    f'<path d="{room_d}" '
                    f'{style} clip-path="url(#grid-clip)"/>'
                )
            else:
                out.append(f'<path d="{room_d}" {style}/>')
        else:
            out.append(f'<path d="{room_d}" {style}/>')

    if corridor_d:
        out.append(f'<path d="{corridor_d}" {style}/>')

    return out


_OP_HANDLERS[Op.Op.FloorGridOp] = _draw_floor_grid_from_ir


def _draw_floor_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_floor_detail``.

    Three modes:

    - ``wood_floor_groups`` non-empty → emit them verbatim and
      return. The legacy wood-floor short-circuit owns its own
      clipPath envelope; the IR carries the fragments end-to-end.
    - Otherwise: floor-detail-proper from Rust
      (``nhc_render.draw_floor_detail``) plus thematic-detail
      passthrough (``room_groups`` / ``corridor_groups``) under
      the dungeon-interior clipPath envelope on the room side,
      with ``corridor_groups`` and ``decorator_groups`` appended
      unclipped. Sub-step 3.e — the structured op carries
      ``tiles[]`` + ``isCorridor[]`` + ``theme``; the thematic
      ``<g>`` groups still ride the legacy passthrough until
      step 4 ports them to ``ThematicDetailOp``.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())

    wood_floor = [_to_str(g) for g in (op.woodFloorGroups or [])]
    if wood_floor:
        return wood_floor

    out: list[str] = []
    thematic_room = [_to_str(g) for g in (op.roomGroups or [])]
    thematic_corridor = [
        _to_str(g) for g in (op.corridorGroups or [])
    ]
    decorator_groups = [_to_str(g) for g in (op.decoratorGroups or [])]

    rust_room: list[str] = []
    rust_corridor: list[str] = []
    op_tiles = op.tiles if op.tiles is not None else []
    op_is_corridor = (
        op.isCorridor if op.isCorridor is not None else []
    )
    if len(op_tiles) > 0:
        tiles = [
            (t.x, t.y, bool(op_is_corridor[i]))
            for i, t in enumerate(op_tiles)
        ]
        flags = fir.Flags()
        macabre = (
            bool(flags.MacabreDetail()) if flags is not None else True
        )
        rust_room, rust_corridor = nhc_render.draw_floor_detail(
            tiles, int(op.seed), _to_str(op.theme), macabre,
        )

    room_groups = rust_room + thematic_room
    corridor_groups = rust_corridor + thematic_corridor

    if room_groups:
        clip_id = _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "detail-clip"))
                out.append('<g clip-path="url(#detail-clip)">')
                out.extend(room_groups)
                out.append("</g>")
            else:
                out.extend(room_groups)
        else:
            out.extend(room_groups)

    out.extend(corridor_groups)
    out.extend(decorator_groups)
    return out


_OP_HANDLERS[Op.Op.FloorDetailOp] = _draw_floor_detail_from_ir


def _draw_thematic_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce the thematic-detail layer (webs / bones / skulls).

    Sub-step 4.e wires the Rust port at
    ``nhc_render.draw_thematic_detail``. Walks ``op.tiles[]``
    plus the parallel ``isCorridor[]`` / ``wallCorners[]``
    arrays through the FFI boundary; the painter handles the
    per-theme probability table, the legacy
    ``random.choice``-style web-corner pick, and the macabre
    gate. Output rides under the dungeon-interior clipPath
    envelope on the room side, with the corridor side appended
    unclipped.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) == 0:
        return []

    op_is_corridor = (
        op.isCorridor if op.isCorridor is not None else []
    )
    op_wall_corners = (
        op.wallCorners if op.wallCorners is not None else []
    )
    theme = _to_str(op.theme)
    flags = fir.Flags()
    macabre = (
        bool(flags.MacabreDetail()) if flags is not None else True
    )

    tiles = [
        (
            t.x,
            t.y,
            bool(op_is_corridor[i]),
            int(op_wall_corners[i]) if i < len(op_wall_corners) else 0,
        )
        for i, t in enumerate(op_tiles)
    ]
    room_groups, corridor_groups = nhc_render.draw_thematic_detail(
        tiles, int(op.seed), theme, macabre,
    )

    out: list[str] = []
    if room_groups:
        clip_id = _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(
                    _dungeon_clip_defs(region.Polygon(), "thematic-clip")
                )
                out.append('<g clip-path="url(#thematic-clip)">')
                out.extend(room_groups)
                out.append("</g>")
            else:
                out.extend(room_groups)
        else:
            out.extend(room_groups)

    out.extend(corridor_groups)
    return out


_OP_HANDLERS[Op.Op.ThematicDetailOp] = _draw_thematic_detail_from_ir


def _draw_terrain_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_terrain_detail``.

    Wraps room_groups in the ``terrain-detail-clip`` envelope, then
    appends corridor_groups unclipped. Same shape as 1.g's
    floor-detail handler — the unified ``walk_and_paint`` pipeline
    means both layers share the bucketed clipPath structure.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []

    room_groups = [_to_str(g) for g in (op.roomGroups or [])]
    corridor_groups = [_to_str(g) for g in (op.corridorGroups or [])]

    if room_groups:
        clip_id = _to_str(op.clipRegion)
        if clip_id:
            region = _find_region(fir, clip_id.encode())
            if region is not None:
                out.append(_dungeon_clip_defs(region.Polygon(), "terrain-detail-clip"))
                out.append('<g clip-path="url(#terrain-detail-clip)">')
                out.extend(room_groups)
                out.append("</g>")
            else:
                out.extend(room_groups)
        else:
            out.extend(room_groups)

    out.extend(corridor_groups)
    return out


_OP_HANDLERS[Op.Op.TerrainDetailOp] = _draw_terrain_detail_from_ir


def _draw_decorator_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Render the structured decorator pipeline (``DecoratorOp``).

    Sub-step 6 promotes the empty-arm stub from step 5 into a
    real handler that walks the per-variant vectors and routes
    each to its Rust port. Cobblestone is wired here; the
    remaining six variants land at sub-steps 7–12 (each port
    plugs in additional per-vector dispatch). Until then the
    other variants' fragments still ride through
    ``FloorDetailOp.decorator_groups`` (the passthrough) and
    the dispatcher must not double-draw them.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    out: list[str] = []
    seed = int(op.seed)

    cobble_variants = op.cobblestone if op.cobblestone is not None else []
    for variant in cobble_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_cobblestone(tiles, seed))

    brick_variants = op.brick if op.brick is not None else []
    for variant in brick_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_brick(tiles, seed))

    return out


_OP_HANDLERS[Op.Op.DecoratorOp] = _draw_decorator_from_ir


def _draw_stairs_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_stairs``.

    Phase 4.3 — per-stair geometry lives in
    ``crates/nhc-render/src/primitives/stairs.rs`` and is reached
    via ``nhc_render.draw_stairs``. The Python side just unpacks
    the IR's stair list and forwards theme + fill_color; everything
    else (tapering wedge math, cave fill polygon, parallel step
    lines) is in Rust.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    theme = _to_str(op.theme)
    fill_color = _to_str(op.fillColor)
    stairs = [
        (s.x, s.y, int(s.direction)) for s in (op.stairs or [])
    ]
    return nhc_render.draw_stairs(stairs, theme, fill_color)


_OP_HANDLERS[Op.Op.StairsOp] = _draw_stairs_from_ir


def _draw_generic_procedural_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 1 escape hatch — emit ``op.groups`` verbatim.

    Used by 1.m's surface_features passthrough (and any future
    layer-level passthrough that doesn't yet have a structured
    op). The handler is intentionally trivial: it just decodes
    the FB string list and returns it. ``op.name`` selects which
    layer slot the groups land in via ``_LAYER_OPS`` membership;
    this handler stays neutral on the dispatch since the slot
    decision is the dispatcher's job.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    return [_to_str(g) for g in (op.groups or [])]


_OP_HANDLERS[Op.Op.GenericProceduralOp] = _draw_generic_procedural_from_ir
