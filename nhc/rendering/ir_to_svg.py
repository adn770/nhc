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
    "structural",
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
    "structural": frozenset({
        Op.Op.WallsAndFloorsOp,
        # Phase 8.1: per-building roof primitives. Within `ops[]`,
        # site IRs emit RoofOps after WallsAndFloorsOp so the roof
        # paints over the floor — see design/map_ir.md §6.1.
        Op.Op.RoofOp,
        # Phase 8.2: site enclosure primitive (palisade /
        # fortification). Site IRs emit one EnclosureOp after
        # the per-building RoofOps so the enclosure perimeter
        # overlays roof corners but stays beneath atmospherics.
        Op.Op.EnclosureOp,
        # Phase 8.3: per-building wall primitives. Building IRs
        # emit BuildingInteriorWallOp before BuildingExteriorWallOp
        # so the curved exterior masonry overlays any partition
        # extension into the rim zone (cleans up T-junctions for
        # circle / octagon footprints).
        Op.Op.BuildingExteriorWallOp,
        Op.Op.BuildingInteriorWallOp,
    }),
    "terrain_tints": frozenset({Op.Op.TerrainTintOp}),
    "floor_grid": frozenset({Op.Op.FloorGridOp}),
    "floor_detail": frozenset({
        Op.Op.FloorDetailOp,
        # The structured decorator pipeline (cobblestone / brick /
        # flagstone / opus_romano / field_stone / cart_tracks /
        # ore_deposit) rides in the floor_detail layer slot via
        # DecoratorOp's per-variant vector tables.
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


def layer_to_svg_full(buf: bytes, *, layer: str) -> str:
    """Render ``layer`` wrapped in the standard SVG envelope.

    The envelope is the same one ``ir_to_svg`` writes:
    ``<svg viewBox=...>``, the ``BG`` background rect, and a
    ``<g transform="translate(padding,padding)">`` group around
    the per-layer fragments. Used by the Phase 5 PNG parity
    harness — feeding the result into ``resvg-py`` produces the
    baseline that ``nhc_render.ir_to_png(buf, layer=...)`` is
    measured against.
    """
    if layer not in _LAYER_OPS:
        raise KeyError(
            f"unknown layer: {layer!r}; known layers: "
            f"{sorted(_LAYER_OPS)}"
        )
    fir = _root_or_raise(buf)
    cell = fir.Cell()
    padding = fir.Padding()
    w = fir.WidthTiles() * cell + 2 * padding
    h = fir.HeightTiles() * cell + 2 * padding
    body = "\n".join(_dispatch_ops(fir, op_filter=_LAYER_OPS[layer]))
    return (
        f'<svg width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="100%" height="100%" fill="{BG}"/>'
        f'<g transform="translate({padding},{padding})">'
        f'{body}'
        '</g></svg>'
    )


def _root_or_raise(buf: bytes) -> FloorIR:
    if not FloorIR.FloorIRBufferHasIdentifier(buf, 0):
        raise ValueError(
            "Buffer does not carry the NIR3 file_identifier — is "
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


def _draw_wood_floor_from_ir(op, fir: FloorIR) -> list[str]:
    """Reproduce ``_render_wood_floor`` from structured fields.

    Phase 9.2b: drives the wood-floor SVG output from
    ``op.woodTiles`` (per-tile rect fill), ``op.woodBuildingPolygon``
    (chamfer / curved-wall outline for octagon and circle floors)
    and ``op.woodRooms`` (per-room rects for the parquet plank +
    grain generators). Output stays byte-equal to the legacy
    ``_render_wood_floor`` walk by replaying the same row-major
    iteration and the ``random.Random(seed)`` draw order on
    grain (per-strip jittered offsets) followed by seams (per-
    plank lengths).
    """
    import random

    from nhc.rendering._floor_detail import (
        WOOD_FLOOR_FILL, WOOD_GRAIN_DARK, WOOD_GRAIN_LIGHT,
        WOOD_GRAIN_LINES_PER_STRIP, WOOD_GRAIN_OPACITY,
        WOOD_GRAIN_STROKE_WIDTH, WOOD_PLANK_LENGTH_MAX,
        WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_WIDTH_PX,
        WOOD_SEAM_STROKE, WOOD_SEAM_WIDTH,
    )

    out: list[str] = []
    rng = random.Random(int(op.seed))

    clip_id = _to_str(op.clipRegion)
    region = (
        _find_region(fir, clip_id.encode()) if clip_id else None
    )
    has_dungeon_clip = region is not None
    clip_attr = (
        ' clip-path="url(#wood-interior-clip)"'
        if has_dungeon_clip else ""
    )

    if has_dungeon_clip:
        out.append(_dungeon_clip_defs(
            region.Polygon(), "wood-interior-clip",
        ))

    polygon = list(op.woodBuildingPolygon or [])
    if polygon:
        poly_points = " ".join(
            f"{p.x:.1f},{p.y:.1f}" for p in polygon
        )
        out.append(
            '<defs><clipPath id="wood-bldg-clip">'
            f'<polygon points="{poly_points}"/>'
            '</clipPath></defs>'
        )
        xs = [p.x for p in polygon]
        ys = [p.y for p in polygon]
        bx, by = min(xs), min(ys)
        bw = max(xs) - bx
        bh = max(ys) - by
        out.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" '
            f'width="{bw:.1f}" height="{bh:.1f}" '
            f'fill="{WOOD_FLOOR_FILL}" '
            'clip-path="url(#wood-bldg-clip)"/>'
        )
    else:
        # Per-tile rect fill — mirrors walk_and_paint's emit shape
        # for the WOOD_FLOOR_FILL_DECORATOR with bucket="room".
        tiles = list(op.woodTiles or [])
        if tiles and has_dungeon_clip:
            # walk_and_paint re-emits its own clip defs even when
            # the caller already emitted one above; preserve the
            # legacy duplicate to keep byte-equal SVG parity.
            out.append(_dungeon_clip_defs(
                region.Polygon(), "wood-interior-clip",
            ))
            out.append('<g clip-path="url(#wood-interior-clip)">')
        for tile in tiles:
            px = tile.x * CELL
            py = tile.y * CELL
            out.append(
                f'<rect x="{px:.0f}" y="{py:.0f}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{WOOD_FLOOR_FILL}"/>'
            )
        if tiles and has_dungeon_clip:
            out.append("</g>")

    rooms = list(op.woodRooms or [])
    if not rooms:
        return out

    lines_light: list[str] = []
    lines_dark: list[str] = []
    for room in rooms:
        x0 = room.x * CELL
        y0 = room.y * CELL
        x1 = (room.x + room.w) * CELL
        y1 = (room.y + room.h) * CELL
        horizontal = room.w >= room.h
        width = WOOD_PLANK_WIDTH_PX

        if horizontal:
            y = y0
            while y < y1:
                strip_bot = min(y + width, y1)
                span = strip_bot - y
                if span <= 0.5:
                    y += width
                    continue
                for i in range(WOOD_GRAIN_LINES_PER_STRIP):
                    gy = rng.uniform(
                        y + span * 0.15, strip_bot - span * 0.15,
                    )
                    dest = lines_light if i % 2 == 0 else lines_dark
                    dest.append(
                        f'<line x1="{x0:.1f}" y1="{gy:.1f}" '
                        f'x2="{x1:.1f}" y2="{gy:.1f}"/>'
                    )
                y += width
        else:
            x = x0
            while x < x1:
                strip_right = min(x + width, x1)
                span = strip_right - x
                if span <= 0.5:
                    x += width
                    continue
                for i in range(WOOD_GRAIN_LINES_PER_STRIP):
                    gx = rng.uniform(
                        x + span * 0.15, strip_right - span * 0.15,
                    )
                    dest = lines_light if i % 2 == 0 else lines_dark
                    dest.append(
                        f'<line x1="{gx:.1f}" y1="{y0:.1f}" '
                        f'x2="{gx:.1f}" y2="{y1:.1f}"/>'
                    )
                x += width

    for colour, group in (
        (WOOD_GRAIN_LIGHT, lines_light),
        (WOOD_GRAIN_DARK, lines_dark),
    ):
        if not group:
            continue
        out.append(
            f'<g fill="none" stroke="{colour}" '
            f'stroke-width="{WOOD_GRAIN_STROKE_WIDTH}" '
            f'opacity="{WOOD_GRAIN_OPACITY}"{clip_attr}>'
        )
        out.append("".join(group))
        out.append("</g>")

    seams: list[str] = []
    for room in rooms:
        seams.extend(_parquet_seams_from_room_ir(
            room, rng,
            WOOD_PLANK_WIDTH_PX,
            WOOD_PLANK_LENGTH_MIN,
            WOOD_PLANK_LENGTH_MAX,
        ))
    if not seams:
        return out
    out.append(
        f'<g fill="none" stroke="{WOOD_SEAM_STROKE}" '
        f'stroke-width="{WOOD_SEAM_WIDTH}"{clip_attr}>'
    )
    out.append("".join(seams))
    out.append("</g>")
    return out


def _parquet_seams_from_room_ir(
    room, rng, width: float, length_min: float, length_max: float,
) -> list[str]:
    x0 = room.x * CELL
    y0 = room.y * CELL
    x1 = (room.x + room.w) * CELL
    y1 = (room.y + room.h) * CELL
    horizontal = room.w >= room.h
    seams: list[str] = []
    if horizontal:
        y = y0
        while y < y1:
            strip_bot = min(y + width, y1)
            x_end = x0 + rng.uniform(length_min, length_max)
            while x_end < x1:
                seams.append(
                    f'<line x1="{x_end:.1f}" y1="{y:.1f}" '
                    f'x2="{x_end:.1f}" y2="{strip_bot:.1f}"/>'
                )
                x_end += rng.uniform(length_min, length_max)
            y += width
            if y < y1:
                seams.append(
                    f'<line x1="{x0:.1f}" y1="{y:.1f}" '
                    f'x2="{x1:.1f}" y2="{y:.1f}"/>'
                )
    else:
        x = x0
        while x < x1:
            strip_right = min(x + width, x1)
            y_end = y0 + rng.uniform(length_min, length_max)
            while y_end < y1:
                seams.append(
                    f'<line x1="{x:.1f}" y1="{y_end:.1f}" '
                    f'x2="{strip_right:.1f}" y2="{y_end:.1f}"/>'
                )
                y_end += rng.uniform(length_min, length_max)
            x += width
            if x < x1:
                seams.append(
                    f'<line x1="{x:.1f}" y1="{y0:.1f}" '
                    f'x2="{x:.1f}" y2="{y1:.1f}"/>'
                )
    return seams


def _draw_floor_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_floor_detail``.

    Three modes:

    - Wood-floor short-circuit (``wood_tiles`` / ``wood_rooms`` /
      ``wood_building_polygon`` populated) → drive
      ``_draw_wood_floor_from_ir`` from the structured fields.
    - Otherwise: floor-detail-proper from Rust
      (``nhc_render.draw_floor_detail``) plus thematic-detail
      passthrough (``room_groups`` / ``corridor_groups``) under
      the dungeon-interior clipPath envelope on the room side,
      with ``corridor_groups`` appended unclipped.
    """
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())

    if op.woodTiles or op.woodBuildingPolygon or op.woodRooms:
        return _draw_wood_floor_from_ir(op, fir)

    out: list[str] = []
    thematic_room = [_to_str(g) for g in (op.roomGroups or [])]
    thematic_corridor = [
        _to_str(g) for g in (op.corridorGroups or [])
    ]

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


def _terrain_detail_seeded_rng(seed: int, name: str):
    """Per-decorator deterministic RNG used by the terrain-detail
    handler.

    Mirrors the legacy ``_decorators._seeded_rng`` formula
    (Mersenne Twister keyed by ``(ctx.seed, decorator_name)``) so
    SVG output stays byte-equal to the historical fixture
    snapshots in ``tests/fixtures/floor_ir/<descriptor>/floor.svg``.
    """
    import random
    name_seed = sum(
        (ord(c) * 31 ** i) for i, c in enumerate(name)
    ) & 0xFFFF_FFFF
    return random.Random((seed * 1_000_003) ^ name_seed)


# Per-terrain-kind metadata for the from-IR painter. Mirrors the
# (name, z_order, palette) tuple the legacy `_terrain_detail.py`
# `TileDecorator` instances carried; keeping it inline here lets
# `ir_to_svg` consume the painters without depending on the
# legacy decorator infrastructure.
_TERRAIN_DETAIL_DISPATCH: tuple[tuple[int, str, int, str], ...] = (
    # (TerrainKind value, decorator name, z_order, css class)
    (1, "terrain_water", 10, "terrain-water"),
    (2, "terrain_lava", 30, "terrain-lava"),
    (3, "terrain_chasm", 40, "terrain-chasm"),
)


def _draw_terrain_detail_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Reproduce ``_render_terrain_detail`` from ``tiles[]``.

    Drives the per-tile water / lava / chasm painters directly
    from the structured tile list, mirroring the (now-retired)
    ``walk_and_paint`` row-major dispatch + room/corridor
    bucketing + dungeon-poly clip envelope. Per-decorator
    ``random.Random`` keying matches the
    ``_terrain_detail_seeded_rng`` formula above so output stays
    byte-equal to the snapshot fixtures.
    """
    from nhc.rendering._terrain_detail import (
        _chasm_detail, _lava_detail, _water_detail,
    )
    from nhc.rendering.terrain_palette import get_palette

    op = OpCreator(entry.OpType(), entry.Op())
    if not op.tiles:
        return []

    theme_str = _to_str(op.theme) or "dungeon"
    palette = get_palette(theme_str)
    dungeon_palette = get_palette("dungeon")

    painter_by_kind = {
        1: (_water_detail, palette.water, dungeon_palette.water),
        2: (_lava_detail, palette.lava, dungeon_palette.lava),
        3: (_chasm_detail, palette.chasm, dungeon_palette.chasm),
    }

    ctx_seed = int(op.seed) - 200
    rngs = {
        kind: _terrain_detail_seeded_rng(ctx_seed, name)
        for kind, name, _, _ in _TERRAIN_DETAIL_DISPATCH
    }
    buckets: dict[int, dict[str, list[str]]] = {
        kind: {"room": [], "corridor": []}
        for kind, _, _, _ in _TERRAIN_DETAIL_DISPATCH
    }

    for tile in op.tiles:
        info = painter_by_kind.get(int(tile.kind))
        if info is None:
            continue
        painter, style, _ = info
        produced = painter(
            rngs[int(tile.kind)],
            tile.x * CELL, tile.y * CELL,
            style.detail_ink, style.detail_opacity,
        )
        bucket = "corridor" if tile.isCorridor else "room"
        buckets[int(tile.kind)][bucket].extend(produced)

    # Emit in z_order ascending. Group-open uses the dungeon-theme
    # palette to match the legacy `_terrain_group_open`, which
    # hard-codes the "dungeon" palette regardless of running theme.
    active_in_z = sorted(
        _TERRAIN_DETAIL_DISPATCH, key=lambda row: row[2],
    )

    def _group_open(kind: int, css_class: str) -> str:
        d_style = painter_by_kind[kind][2]
        return (
            f'<g class="{css_class}" '
            f'opacity="{d_style.detail_opacity}" '
            f'stroke="{d_style.detail_ink}" '
            f'stroke-linecap="round">'
        )

    def _emit_group(
        target: list[str], kind: int, css_class: str,
        frags: list[str],
    ) -> None:
        if not frags:
            return
        target.append(_group_open(kind, css_class))
        target.extend(frags)
        target.append("</g>")

    out: list[str] = []
    has_any_room = any(
        buckets[kind]["room"] for kind, _, _, _ in active_in_z
    )
    clip_id_str = _to_str(op.clipRegion)
    region = (
        _find_region(fir, clip_id_str.encode())
        if (has_any_room and clip_id_str)
        else None
    )
    use_clip = region is not None

    if use_clip:
        out.append(_dungeon_clip_defs(
            region.Polygon(), "terrain-detail-clip",
        ))
        out.append('<g clip-path="url(#terrain-detail-clip)">')
    for kind, _, _, css_class in active_in_z:
        _emit_group(out, kind, css_class, buckets[kind]["room"])
    if use_clip:
        out.append("</g>")
    for kind, _, _, css_class in active_in_z:
        _emit_group(out, kind, css_class, buckets[kind]["corridor"])
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

    flagstone_variants = (
        op.flagstone if op.flagstone is not None else []
    )
    for variant in flagstone_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_flagstone(tiles, seed))

    opus_variants = (
        op.opusRomano if op.opusRomano is not None else []
    )
    for variant in opus_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_opus_romano(tiles, seed))

    field_variants = (
        op.fieldStone if op.fieldStone is not None else []
    )
    for variant in field_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_field_stone(tiles, seed))

    cart_variants = (
        op.cartTracks if op.cartTracks is not None else []
    )
    for variant in cart_variants:
        v_tiles = variant.tiles or []
        v_horiz = (
            variant.isHorizontal
            if variant.isHorizontal is not None
            else []
        )
        if not v_tiles:
            continue
        tiles = [
            (t.x, t.y, bool(v_horiz[i]))
            for i, t in enumerate(v_tiles)
        ]
        out.extend(nhc_render.draw_cart_tracks(tiles, seed))

    ore_variants = (
        op.oreDeposit if op.oreDeposit is not None else []
    )
    for variant in ore_variants:
        v_tiles = variant.tiles or []
        if not v_tiles:
            continue
        tiles = [(t.x, t.y) for t in v_tiles]
        out.extend(nhc_render.draw_ore_deposit(tiles, seed))

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


def _draw_feature_groups(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Generic groups-passthrough handler used by surface-feature
    ops that haven't ported their per-tile painter to Rust yet
    (fountain / tree / bush — sub-steps 14-16).

    The op carries pre-rendered ``<g>`` strings in ``op.groups``;
    the handler emits them verbatim. Each feature's Rust port
    swaps this for a structured-tile dispatch arm.
    """
    del fir
    op = OpCreator(entry.OpType(), entry.Op())
    return [_to_str(g) for g in (op.groups or [])]


def _draw_well_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Well surface feature — Phase 4 sub-step 13.

    Reads ``op.tiles[]`` + ``op.shape`` and dispatches to the
    Rust port at ``nhc_render.draw_well``. Falls back to the
    transitional ``op.groups`` passthrough when the structured
    fields are empty (e.g. for fixtures emitted before the port
    landed).
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) > 0:
        tiles = [(t.x, t.y) for t in op_tiles]
        return nhc_render.draw_well(tiles, int(op.shape))
    return [_to_str(g) for g in (op.groups or [])]


def _draw_fountain_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Fountain surface feature — Phase 4 sub-step 14.

    Reads ``op.tiles[]`` + ``op.shape`` and dispatches to the
    Rust port. Falls back to ``op.groups`` for legacy IR buffers.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) > 0:
        tiles = [(t.x, t.y) for t in op_tiles]
        return nhc_render.draw_fountain(tiles, int(op.shape))
    return [_to_str(g) for g in (op.groups or [])]


def _draw_bush_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Bush surface feature — Phase 4 sub-step 16.

    Reads ``op.tiles[]`` and dispatches to the Rust port at
    ``nhc_render.draw_bush``. Falls back to ``op.groups`` for
    legacy IR buffers.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    if len(op_tiles) > 0:
        tiles = [(t.x, t.y) for t in op_tiles]
        return nhc_render.draw_bush(tiles)
    return [_to_str(g) for g in (op.groups or [])]


def _draw_tree_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Tree surface feature — Phase 4 sub-step 15.

    Reads ``op.tiles[]`` (free trees) plus
    ``op.groveTiles[]`` + ``op.groveSizes[]`` (groves of size
    ≥ 3 partitioned across the flat list) and dispatches to
    ``nhc_render.draw_tree``. Falls back to ``op.groups`` for
    legacy IR buffers.
    """
    del fir
    import nhc_render

    op = OpCreator(entry.OpType(), entry.Op())
    op_tiles = op.tiles if op.tiles is not None else []
    op_grove_tiles = (
        op.groveTiles if op.groveTiles is not None else []
    )
    op_grove_sizes = (
        op.groveSizes if op.groveSizes is not None else []
    )
    if len(op_tiles) > 0 or len(op_grove_tiles) > 0:
        free_trees = [(t.x, t.y) for t in op_tiles]
        flat = [(t.x, t.y) for t in op_grove_tiles]
        groves: list[list[tuple[int, int]]] = []
        cursor = 0
        for size in op_grove_sizes:
            n = int(size)
            groves.append(flat[cursor : cursor + n])
            cursor += n
        return nhc_render.draw_tree(free_trees, groves)
    return [_to_str(g) for g in (op.groups or [])]


_OP_HANDLERS[Op.Op.WellFeatureOp] = _draw_well_from_ir
_OP_HANDLERS[Op.Op.FountainFeatureOp] = _draw_fountain_from_ir
_OP_HANDLERS[Op.Op.TreeFeatureOp] = _draw_tree_from_ir
_OP_HANDLERS[Op.Op.BushFeatureOp] = _draw_bush_from_ir


# ── RoofOp (Phase 8.1c.1) ───────────────────────────────────────
#
# Per-building shingle roof. The handler resolves region_ref to the
# matching Region(kind=Building), reads its polygon (pixel coords),
# picks gable / pyramid mode from shape_tag + bbox aspect, and
# emits a clip-path-bounded shingle running-bond plus ridge lines.
#
# Both rasterisers (this Python SVG path and the future tiny-skia
# port at crates/nhc-render/src/transform/png/roof.rs in 8.1c.2)
# walk the same splitmix64 stream seeded with RoofOp.rng_seed so
# their shingle layouts agree at PSNR > 40 dB. The Phase 8.1c.1
# Python implementation is the *reference* — the Rust port mirrors
# it constant-for-constant.


_ROOF_GOLDEN_GAMMA: int = 0x9E3779B97F4A7C15
_ROOF_MIX_C1: int = 0xBF58476D1CE4E5B9
_ROOF_MIX_C2: int = 0x94D049BB133111EB
_U64_MASK: int = 0xFFFFFFFFFFFFFFFF


_ROOF_SHADOW_FACTOR: float = 0.5
_ROOF_SHINGLE_WIDTH: float = 14.0
_ROOF_SHINGLE_HEIGHT: float = 5.0
_ROOF_SHINGLE_JITTER: float = 2.0
_ROOF_RIDGE_STROKE: str = "#000000"
_ROOF_RIDGE_WIDTH: float = 1.5
_ROOF_SHINGLE_STROKE: str = "#000000"
_ROOF_SHINGLE_STROKE_OPACITY: float = 0.2
_ROOF_SHINGLE_STROKE_WIDTH: float = 0.3


class _SplitMix64:
    """Stateful splitmix64 — mirrors crates/nhc-render/src/rng.rs.

    The Rust port at 8.1c.2 will pull from a parallel stream
    seeded with the same ``RoofOp.rng_seed``. Both sides advance
    state by ``GOLDEN_GAMMA`` each call before the 3-step mix, so
    ``next_u64`` outputs match value-for-value.
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _U64_MASK

    def next_u64(self) -> int:
        self._state = (self._state + _ROOF_GOLDEN_GAMMA) & _U64_MASK
        z = self._state
        z = ((z ^ (z >> 30)) * _ROOF_MIX_C1) & _U64_MASK
        z = ((z ^ (z >> 27)) * _ROOF_MIX_C2) & _U64_MASK
        return z ^ (z >> 31)

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * (self.next_u64() / 2 ** 64)

    def choice(self, seq: list) -> Any:
        return seq[self.next_u64() % len(seq)]


def _roof_scale_hex(hx: str, factor: float) -> str:
    r = min(255, max(0, int(int(hx[1:3], 16) * factor)))
    g = min(255, max(0, int(int(hx[3:5], 16) * factor)))
    b = min(255, max(0, int(int(hx[5:7], 16) * factor)))
    return f"#{r:02X}{g:02X}{b:02X}"


def _roof_shade_palette(tint: str, *, sunlit: bool) -> list[str]:
    if sunlit:
        factors = (1.15, 1.00, 0.88)
    else:
        c = _ROOF_SHADOW_FACTOR
        factors = (c * 1.15, c, c * 0.88)
    return [_roof_scale_hex(tint, f) for f in factors]


def _roof_shingle_region(
    x: float, y: float, w: float, h: float,
    shades: list[str], rng: _SplitMix64,
) -> list[str]:
    """Running-bond rows of shingle rects filling a bounding box."""
    sw = _ROOF_SHINGLE_WIDTH
    sh = _ROOF_SHINGLE_HEIGHT
    jitter = _ROOF_SHINGLE_JITTER
    frags: list[str] = []
    row = 0
    cy = y
    while cy < y + h:
        sx = x - (sw / 2 if row % 2 else 0)
        while sx < x + w:
            sw_j = sw + rng.uniform(-jitter, jitter)
            shade = rng.choice(shades)
            frags.append(
                f'<rect x="{sx:.1f}" y="{cy:.1f}" '
                f'width="{sw_j:.1f}" height="{sh:.1f}" '
                f'fill="{shade}" '
                f'stroke="{_ROOF_SHINGLE_STROKE}" '
                f'stroke-opacity="{_ROOF_SHINGLE_STROKE_OPACITY}" '
                f'stroke-width="{_ROOF_SHINGLE_STROKE_WIDTH}"/>'
            )
            sx += sw_j
        cy += sh
        row += 1
    return frags


def _roof_gable_sides(
    px: float, py: float, pw: float, ph: float,
    horizontal: bool,
    sunlit_shades: list[str], shadow_shades: list[str],
    rng: _SplitMix64,
) -> list[str]:
    frags: list[str] = []
    if horizontal:
        frags.extend(_roof_shingle_region(
            px, py, pw, ph / 2, shadow_shades, rng,
        ))
        frags.extend(_roof_shingle_region(
            px, py + ph / 2, pw, ph / 2, sunlit_shades, rng,
        ))
        frags.append(
            f'<line x1="{px:.1f}" y1="{py + ph / 2:.1f}" '
            f'x2="{px + pw:.1f}" y2="{py + ph / 2:.1f}" '
            f'stroke="{_ROOF_RIDGE_STROKE}" '
            f'stroke-width="{_ROOF_RIDGE_WIDTH}"/>'
        )
    else:
        frags.extend(_roof_shingle_region(
            px, py, pw / 2, ph, shadow_shades, rng,
        ))
        frags.extend(_roof_shingle_region(
            px + pw / 2, py, pw / 2, ph, sunlit_shades, rng,
        ))
        frags.append(
            f'<line x1="{px + pw / 2:.1f}" y1="{py:.1f}" '
            f'x2="{px + pw / 2:.1f}" y2="{py + ph:.1f}" '
            f'stroke="{_ROOF_RIDGE_STROKE}" '
            f'stroke-width="{_ROOF_RIDGE_WIDTH}"/>'
        )
    return frags


def _roof_pyramid_sides(
    polygon: list[tuple[float, float]],
    sunlit_shades: list[str], shadow_shades: list[str],
    rng: _SplitMix64,
) -> list[str]:
    """N triangles from polygon centre, shaded by edge midpoint
    direction (north / west = shadow, south / east = sunlit), plus
    ridges from centre to each polygon vertex."""
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    frags: list[str] = []
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        mx = (a[0] + b[0]) / 2
        my = (a[1] + b[1]) / 2
        is_shadow = my < cy - 1e-3 or (
            mx < cx - 1e-3 and my < cy + 1e-3
        )
        shades = shadow_shades if is_shadow else sunlit_shades
        fill = rng.choice(shades)
        pts = (
            f"{a[0]:.1f},{a[1]:.1f} "
            f"{b[0]:.1f},{b[1]:.1f} "
            f"{cx:.1f},{cy:.1f}"
        )
        frags.append(
            f'<polygon points="{pts}" fill="{fill}" '
            f'stroke="{_ROOF_SHINGLE_STROKE}" '
            f'stroke-opacity="{_ROOF_SHINGLE_STROKE_OPACITY}" '
            f'stroke-width="{_ROOF_SHINGLE_STROKE_WIDTH}"/>'
        )
    for (vx, vy) in polygon:
        frags.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" '
            f'x2="{vx:.1f}" y2="{vy:.1f}" '
            f'stroke="{_ROOF_RIDGE_STROKE}" '
            f'stroke-width="{_ROOF_RIDGE_WIDTH}"/>'
        )
    return frags


def _roof_geometry_mode(shape_tag: str, polygon: list[tuple[float, float]]) -> str:
    """Pick "gable" or "pyramid" from shape_tag + footprint bbox.

    Mirrors design/map_ir.md §7.14:
    - rect non-square / l_shape_*  → gable
    - rect square / octagon / circle / fallback → pyramid
    """
    if shape_tag.startswith("l_shape"):
        return "gable"
    if shape_tag == "rect":
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        return "pyramid" if abs(w - h) < 1e-6 else "gable"
    return "pyramid"  # octagon / circle / unknown


def _draw_roof_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Phase 8.1c.1: per-building shingle roof.

    Reads the referenced ``Region(kind=Building)``, picks geometry
    from its ``shape_tag`` + polygon bbox, and emits a clip-path-
    bounded roof body. The Python implementation is the reference;
    the Rust tiny-skia port at 8.1c.2 mirrors the same RNG +
    constants so PSNR > 40 dB across both rasterisers.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    region_ref = _to_str(op.regionRef)
    region = _find_region(fir, op.regionRef)
    if region is None:
        raise ValueError(
            f"RoofOp references unknown region {region_ref!r}; "
            "emit_regions / emit_building_regions must register it"
        )
    shape_tag = _to_str(region.ShapeTag())
    polygon_paths = region.Polygon()
    if polygon_paths is None or polygon_paths.PathsLength() < 3:
        raise ValueError(
            f"RoofOp region {region_ref!r} polygon is empty or "
            "degenerate; cannot emit roof"
        )
    polygon: list[tuple[float, float]] = []
    for i in range(polygon_paths.PathsLength()):
        v = polygon_paths.Paths(i)
        polygon.append((v.X(), v.Y()))

    tint = _to_str(op.tint) or "#8A7A5A"
    rng = _SplitMix64(int(op.rngSeed))
    sunlit_shades = _roof_shade_palette(tint, sunlit=True)
    shadow_shades = _roof_shade_palette(tint, sunlit=False)

    mode = _roof_geometry_mode(shape_tag, polygon)
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    px, py = min(xs), min(ys)
    pw, ph = max(xs) - px, max(ys) - py

    body: list[str]
    if mode == "gable":
        body = _roof_gable_sides(
            px, py, pw, ph, pw >= ph,
            sunlit_shades, shadow_shades, rng,
        )
    else:
        body = _roof_pyramid_sides(
            polygon, sunlit_shades, shadow_shades, rng,
        )

    # Clip-path id derives from region_ref so the same Building
    # always yields the same clipPath id — stable across re-emits.
    clip_id = f"roof_{region_ref.replace('.', '_')}"
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in polygon)
    return [
        (
            f'<defs><clipPath id="{clip_id}">'
            f'<polygon points="{pts}"/>'
            f'</clipPath></defs>'
        ),
        f'<g clip-path="url(#{clip_id})">{"".join(body)}</g>',
    ]


_OP_HANDLERS[Op.Op.RoofOp] = _draw_roof_from_ir


# ── EnclosureOp (Phase 8.2) ─────────────────────────────────────
#
# Site-level palisade ring or fortification battlement. Reads the
# closed polygon, walks its edges (cut by per-edge gate spans into
# open sub-polylines), and dispatches each sub-segment on
# EnclosureStyle. Per-edge palisade RNG seeds derive from
# `rng_seed + edge_idx` so adding / removing a gate on edge X
# doesn't shift state on other edges. Both rasterisers walk the
# same splitmix64 stream — the Rust port at
# crates/nhc-render/src/transform/png/enclosure.rs lands at 8.2c.
#
# Constants mirror nhc/rendering/_enclosures.py value-for-value
# (palette + dimensions). The legacy module stays alive until the
# site-surface IR wiring at Phase 8.4 obsoletes it.


# Fortification (battlement) constants.
_ENC_FORTIF_STROKE = "#1A1A1A"
_ENC_FORTIF_STROKE_WIDTH = 0.8
_ENC_FORTIF_MERLON_FILL = "#D8D8D8"
_ENC_FORTIF_CRENEL_FILL = "#000000"
_ENC_FORTIF_CORNER_FILL = "#000000"
_ENC_FORTIF_SIZE = 8.0
_ENC_FORTIF_RATIO = 1.4142135623730951  # sqrt(2) — DIN A
_ENC_FORTIF_CORNER_SCALE = 3.0


# Palisade constants.
_ENC_PALI_FILL = "#8A5A2A"
_ENC_PALI_STROKE = "#4A2E1A"
_ENC_PALI_STROKE_WIDTH = 1.5
_ENC_PALI_RADIUS_MIN = 3.0
_ENC_PALI_RADIUS_MAX = 4.0
_ENC_PALI_RADIUS_JITTER = 0.3
_ENC_PALI_CIRCLE_STEP = 9.0
_ENC_PALI_DOOR_LENGTH_PX = 64.0


def _enc_corner_inset() -> float:
    return _ENC_FORTIF_SIZE / 2.0


def _enc_merge_cuts(
    cuts: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not cuts:
        return []
    cuts = sorted(cuts)
    merged = [cuts[0]]
    for lo, hi in cuts[1:]:
        plo, phi = merged[-1]
        if lo <= phi:
            merged[-1] = (plo, max(phi, hi))
        else:
            merged.append((lo, hi))
    return merged


def _enc_subsegments(
    a: tuple[float, float], b: tuple[float, float],
    cuts: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    ax, ay = a
    bx, by = b

    def _at(t: float) -> tuple[float, float]:
        return (ax + (bx - ax) * t, ay + (by - ay) * t)

    if not cuts:
        return [(a, b)]
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    prev = 0.0
    for lo, hi in cuts:
        if lo > prev:
            out.append((_at(prev), _at(lo)))
        prev = hi
    if prev < 1.0:
        out.append((_at(prev), _at(1.0)))
    return out


def _enc_fortification_rect(
    cx: float, cy: float, w: float, h: float, fill: str,
) -> str:
    return (
        f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'fill="{fill}" '
        f'stroke="{_ENC_FORTIF_STROKE}" '
        f'stroke-width="{_ENC_FORTIF_STROKE_WIDTH}"/>'
    )


def _enc_centered_fortification_chain(
    a: tuple[float, float], b: tuple[float, float],
) -> list[str]:
    """``C M C M ... C`` chain inside a horizontal / vertical sub-segment."""
    import math
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-6:
        return []
    horizontal = abs(dy) < 1e-6 and abs(dx) > 1e-6
    vertical = abs(dx) < 1e-6 and abs(dy) > 1e-6
    if not (horizontal or vertical):
        return []
    size = _ENC_FORTIF_SIZE
    rect_len = size * _ENC_FORTIF_RATIO
    k = int((seg_len + size) / (rect_len + size))
    if k < 1:
        return []
    used = k * rect_len + (k - 1) * size
    offset = (seg_len - used) / 2.0
    ux = dx / seg_len
    uy = dy / seg_len
    out: list[str] = []
    pos = offset
    alternate = 1  # start with crenel
    for _ in range(2 * k - 1):
        length = size if alternate == 0 else rect_len
        cx = ax + ux * (pos + length / 2.0)
        cy = ay + uy * (pos + length / 2.0)
        if horizontal:
            shape_w, shape_h = length, size
        else:
            shape_w, shape_h = size, length
        fill = (
            _ENC_FORTIF_MERLON_FILL if alternate == 0
            else _ENC_FORTIF_CRENEL_FILL
        )
        out.append(_enc_fortification_rect(cx, cy, shape_w, shape_h, fill))
        pos += length
        alternate = 1 - alternate
    return out


def _enc_corner_shape(
    x: float, y: float, corner_style: int,
) -> str:
    """Per-vertex corner block. corner_style is the raw FB enum int."""
    from nhc.rendering.ir._fb.CornerStyle import CornerStyle
    size = _ENC_FORTIF_SIZE * _ENC_FORTIF_CORNER_SCALE
    half = size / 2.0
    if corner_style == CornerStyle.Diamond:
        return (
            f'<rect x="{x - half:.1f}" y="{y - half:.1f}" '
            f'width="{size:.1f}" height="{size:.1f}" '
            f'fill="{_ENC_FORTIF_CORNER_FILL}" '
            f'stroke="{_ENC_FORTIF_STROKE}" '
            f'stroke-width="{_ENC_FORTIF_STROKE_WIDTH}" '
            f'transform="rotate(45 {x:.1f} {y:.1f})"/>'
        )
    # Merlon (and Tower fallback): axis-aligned black square.
    return _enc_fortification_rect(
        x, y, size, size, _ENC_FORTIF_CORNER_FILL,
    )


def _enc_palisade_circles(
    points: list[tuple[float, float]], rng: _SplitMix64,
) -> list[str]:
    import math
    if len(points) < 2:
        return []
    out: list[str] = []
    carry = 0.0
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        dx, dy = bx - ax, by - ay
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-6:
            continue
        ux, uy = dx / seg_len, dy / seg_len
        t = carry
        while t < seg_len:
            cx = ax + ux * t
            cy = ay + uy * t
            base_r = rng.uniform(_ENC_PALI_RADIUS_MIN, _ENC_PALI_RADIUS_MAX)
            jitter = rng.uniform(
                -_ENC_PALI_RADIUS_JITTER, _ENC_PALI_RADIUS_JITTER,
            )
            r = max(0.1, base_r + jitter)
            out.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                f'r="{r:.1f}" '
                f'fill="{_ENC_PALI_FILL}" '
                f'stroke="{_ENC_PALI_STROKE}" '
                f'stroke-width="{_ENC_PALI_STROKE_WIDTH}"/>'
            )
            t += _ENC_PALI_CIRCLE_STEP
        carry = max(0.0, t - seg_len)
    return out


def _enc_palisade_door_rect(
    a: tuple[float, float], b: tuple[float, float], t_center: float,
) -> str:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    cx = ax + dx * t_center
    cy = ay + dy * t_center
    horizontal = abs(dy) < 1e-6
    thickness = 2.0 * _ENC_PALI_RADIUS_MAX
    if horizontal:
        x = cx - _ENC_PALI_DOOR_LENGTH_PX / 2
        y = cy - thickness / 2
        w, h = _ENC_PALI_DOOR_LENGTH_PX, thickness
    else:
        x = cx - thickness / 2
        y = cy - _ENC_PALI_DOOR_LENGTH_PX / 2
        w, h = thickness, _ENC_PALI_DOOR_LENGTH_PX
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'fill="{_ENC_PALI_FILL}" '
        f'stroke="{_ENC_PALI_STROKE}" '
        f'stroke-width="{_ENC_PALI_STROKE_WIDTH}"/>'
    )


def _draw_enclosure_from_ir(entry: OpEntry, fir: FloorIR) -> list[str]:
    """Phase 8.2: site palisade or fortification ring.

    Walks the closed polygon, applies per-edge gate cuts, and
    dispatches each open sub-segment on EnclosureStyle. Per-edge
    palisade RNG state is `splitmix64(rng_seed + edge_idx)` so a
    gate edit on edge X leaves other edges' circle layouts pinned.
    """
    import math
    from nhc.rendering.ir._fb.EnclosureStyle import EnclosureStyle

    op = OpCreator(entry.OpType(), entry.Op())
    poly = op.polygon
    if poly is None or not poly.paths:
        return []
    polygon: list[tuple[float, float]] = [
        (v.x, v.y) for v in poly.paths
    ]
    n = len(polygon)
    if n < 3:
        return []

    # Group gates by edge.
    by_edge: dict[int, list[tuple[float, float]]] = {}
    midpoints: dict[int, list[tuple[float, float]]] = {}
    for g in (op.gates or []):
        edge_idx = int(g.edgeIdx)
        if not 0 <= edge_idx < n:
            continue
        a = polygon[edge_idx]
        b = polygon[(edge_idx + 1) % n]
        edge_len = math.hypot(b[0] - a[0], b[1] - a[1])
        if edge_len < 1e-6:
            continue
        half_t = float(g.halfPx) / edge_len
        lo = max(0.0, float(g.tCenter) - half_t)
        hi = min(1.0, float(g.tCenter) + half_t)
        if hi > lo:
            by_edge.setdefault(edge_idx, []).append((lo, hi))
            midpoints.setdefault(edge_idx, []).append(
                (float(g.tCenter), float(g.halfPx)),
            )

    style = int(op.style)
    rng_seed = int(op.rngSeed)
    out: list[str] = []

    if style == EnclosureStyle.Palisade:
        for i in range(n):
            a = polygon[i]
            b = polygon[(i + 1) % n]
            cuts = _enc_merge_cuts(by_edge.get(i, []))
            subs = _enc_subsegments(a, b, cuts)
            edge_rng = _SplitMix64(rng_seed + i)
            for (sa, sb) in subs:
                out.extend(_enc_palisade_circles(
                    [sa, sb], edge_rng,
                ))
            for t_center, _ in midpoints.get(i, []):
                out.append(_enc_palisade_door_rect(a, b, t_center))
        return out

    # Fortification: edges inset, centered chains, corner blocks
    # last so they sit on top.
    inset = _enc_corner_inset()
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        edge_len = math.hypot(b[0] - a[0], b[1] - a[1])
        if edge_len <= 2 * inset + 1e-6:
            continue
        ux = (b[0] - a[0]) / edge_len
        uy = (b[1] - a[1]) / edge_len
        a_in = (a[0] + ux * inset, a[1] + uy * inset)
        b_in = (b[0] - ux * inset, b[1] - uy * inset)
        cuts = _enc_merge_cuts(by_edge.get(i, []))
        t_inset = inset / edge_len
        denom = 1.0 - 2.0 * t_inset
        inset_cuts: list[tuple[float, float]] = []
        if denom > 1e-9:
            for lo, hi in cuts:
                new_lo = max(0.0, (lo - t_inset) / denom)
                new_hi = min(1.0, (hi - t_inset) / denom)
                if new_hi > new_lo:
                    inset_cuts.append((new_lo, new_hi))
        subs = _enc_subsegments(a_in, b_in, inset_cuts)
        for (sa, sb) in subs:
            out.extend(_enc_centered_fortification_chain(sa, sb))

    # Wood gate visuals (legacy fortification drew nothing here;
    # design/map_ir.md §7.15 makes gates a first-class concept and
    # always paints their rect).
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        for t_center, _ in midpoints.get(i, []):
            out.append(_enc_palisade_door_rect(a, b, t_center))

    corner_style = int(op.cornerStyle)
    for (x, y) in polygon:
        out.append(_enc_corner_shape(x, y, corner_style))
    return out


_OP_HANDLERS[Op.Op.EnclosureOp] = _draw_enclosure_from_ir


# ── BuildingExteriorWallOp + BuildingInteriorWallOp (Phase 8.3) ─
#
# Constants mirror nhc/rendering/_building_walls.py + building.py
# value-for-value (palette, dimensions, edge-extension trick).
# Both rasterisers walk the same splitmix64 stream — the Rust
# port at crates/nhc-render/src/transform/png/building_*.rs
# lands at 8.3c.


_MASONRY_STRIP_COUNT = 2
_MASONRY_MEAN_WIDTH = 12.0
_MASONRY_WIDTH_LOW = 0.9
_MASONRY_WIDTH_HIGH = 1.1
_MASONRY_CORNER_RADIUS = 1.2
_MASONRY_STROKE_WIDTH = 1.0
_MASONRY_WALL_THICKNESS = 8.0
_MASONRY_STRIP_OFFSETS = (0.0, _MASONRY_MEAN_WIDTH / 2)

_BRICK_FILL = "#B4695A"
_BRICK_SEAM = "#6A3A2A"
_STONE_FILL = "#9A8E80"
_STONE_SEAM = "#4A3E35"

_INTERIOR_WALL_COLORS: dict[int, str] = {
    # InteriorWallMaterial: Stone=0, Brick=1, Wood=2.
    0: "#707070",
    1: "#c4651d",
    2: "#7a4e2c",
}
_INTERIOR_WALL_STROKE_WIDTH = CELL * 0.25


def _masonry_palette(material: int) -> tuple[str, str]:
    """``WallMaterial`` int -> (fill, seam) hex strings."""
    from nhc.rendering.ir._fb.WallMaterial import WallMaterial
    if material == WallMaterial.Brick:
        return (_BRICK_FILL, _BRICK_SEAM)
    return (_STONE_FILL, _STONE_SEAM)


def _masonry_ortho_rect(
    horizontal: bool, run_start: float, perp: float,
    pos: float, width: float, strip_thick: float,
    fill: str, stroke: str,
) -> str:
    if horizontal:
        x = run_start + pos
        y = perp
        w = width
        h = strip_thick
    else:
        x = perp
        y = run_start + pos
        w = strip_thick
        h = width
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'rx="{_MASONRY_CORNER_RADIUS}" '
        f'ry="{_MASONRY_CORNER_RADIUS}" '
        f'fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{_MASONRY_STROKE_WIDTH}"/>'
    )


def _masonry_diagonal_rect(
    pos: float, perp: float, width: float, strip_thick: float,
    x0: float, y0: float, angle_deg: float,
    fill: str, stroke: str,
) -> str:
    return (
        f'<rect x="{pos:.1f}" y="{perp:.1f}" '
        f'width="{width:.1f}" height="{strip_thick:.1f}" '
        f'rx="{_MASONRY_CORNER_RADIUS}" '
        f'ry="{_MASONRY_CORNER_RADIUS}" '
        f'fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{_MASONRY_STROKE_WIDTH}" '
        f'transform="translate({x0:.1f} {y0:.1f}) '
        f'rotate({angle_deg:.2f})"/>'
    )


def _render_masonry_wall_run(
    x0: float, y0: float, x1: float, y1: float,
    *, rng: _SplitMix64, fill: str, stroke: str,
) -> list[str]:
    """Two-strip running-bond chain along a wall centerline.

    Mirrors nhc/rendering/_building_walls._render_masonry_wall_run
    but uses splitmix64 instead of random.Random.
    """
    import math
    if x0 == x1 and y0 == y1:
        return []
    horizontal = y0 == y1
    vertical = x0 == x1
    strip_thick = _MASONRY_WALL_THICKNESS / _MASONRY_STRIP_COUNT
    out: list[str] = []
    if horizontal or vertical:
        run_len = abs(x1 - x0) if horizontal else abs(y1 - y0)
        run_start = min(x0, x1) if horizontal else min(y0, y1)
        perp_start = (y0 if horizontal else x0) - _MASONRY_WALL_THICKNESS / 2
        for idx in range(_MASONRY_STRIP_COUNT):
            perp = perp_start + idx * strip_thick
            pos = max(0.0, _MASONRY_STRIP_OFFSETS[idx])
            while pos < run_len:
                width = _MASONRY_MEAN_WIDTH * rng.uniform(
                    _MASONRY_WIDTH_LOW, _MASONRY_WIDTH_HIGH,
                )
                width = min(width, run_len - pos)
                out.append(_masonry_ortho_rect(
                    horizontal, run_start, perp,
                    pos, width, strip_thick, fill, stroke,
                ))
                pos += width
        return out
    # Diagonal run.
    dx = x1 - x0
    dy = y1 - y0
    run_len = math.hypot(dx, dy)
    angle_deg = math.degrees(math.atan2(dy, dx))
    for idx in range(_MASONRY_STRIP_COUNT):
        perp = -_MASONRY_WALL_THICKNESS / 2 + idx * strip_thick
        pos = max(0.0, _MASONRY_STRIP_OFFSETS[idx])
        while pos < run_len:
            width = _MASONRY_MEAN_WIDTH * rng.uniform(
                _MASONRY_WIDTH_LOW, _MASONRY_WIDTH_HIGH,
            )
            width = min(width, run_len - pos)
            out.append(_masonry_diagonal_rect(
                pos, perp, width, strip_thick,
                x0, y0, angle_deg, fill, stroke,
            ))
            pos += width
    return out


def _draw_building_exterior_wall_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 8.3: per-building masonry perimeter pass.

    Resolves region_ref, walks polygon edges, and emits a 2-strip
    running-bond chain along each. Adjacent edges overlap by half
    the wall thickness at every vertex so the corner square paints
    fully (mirrors building.py:113-130).
    """
    import math
    op = OpCreator(entry.OpType(), entry.Op())
    region_ref = _to_str(op.regionRef)
    region = _find_region(fir, op.regionRef)
    if region is None:
        raise ValueError(
            f"BuildingExteriorWallOp references unknown region "
            f"{region_ref!r}"
        )
    polygon_paths = region.Polygon()
    if polygon_paths is None or polygon_paths.PathsLength() < 3:
        return []
    polygon: list[tuple[float, float]] = [
        (polygon_paths.Paths(i).X(), polygon_paths.Paths(i).Y())
        for i in range(polygon_paths.PathsLength())
    ]
    fill, stroke = _masonry_palette(int(op.material))
    rng_seed = int(op.rngSeed)
    ext = _MASONRY_WALL_THICKNESS / 2
    out: list[str] = []
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        dx = bx - ax
        dy = by - ay
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        ux = dx / length
        uy = dy / length
        ax_ext = ax - ux * ext
        ay_ext = ay - uy * ext
        bx_ext = bx + ux * ext
        by_ext = by + uy * ext
        edge_rng = _SplitMix64(rng_seed + i)
        out.extend(_render_masonry_wall_run(
            ax_ext, ay_ext, bx_ext, by_ext,
            rng=edge_rng, fill=fill, stroke=stroke,
        ))
    return out


_OP_HANDLERS[Op.Op.BuildingExteriorWallOp] = (
    _draw_building_exterior_wall_from_ir
)


def _tile_corner_delta(corner: int) -> tuple[int, int]:
    """``TileCorner`` int -> (Δx, Δy)."""
    from nhc.rendering.ir._fb.TileCorner import TileCorner
    if corner == TileCorner.NW:
        return (0, 0)
    if corner == TileCorner.NE:
        return (1, 0)
    if corner == TileCorner.SE:
        return (1, 1)
    return (0, 1)  # SW


def _draw_building_interior_wall_from_ir(
    entry: OpEntry, fir: FloorIR,
) -> list[str]:
    """Phase 8.3: per-building partition lines.

    InteriorEdge endpoints are corner-grid vertices `(tile + Δ)`.
    The op carries the pre-coalesced + door-suppression-filtered
    edge list — the rasteriser is a thin per-edge stroke pass.
    """
    op = OpCreator(entry.OpType(), entry.Op())
    edges = op.edges or []
    if not edges:
        return []
    color = _INTERIOR_WALL_COLORS.get(int(op.material), _INTERIOR_WALL_COLORS[0])
    out: list[str] = []
    for edge in edges:
        adx, ady = _tile_corner_delta(int(edge.aCorner))
        bdx, bdy = _tile_corner_delta(int(edge.bCorner))
        px0 = (edge.ax + adx) * CELL
        py0 = (edge.ay + ady) * CELL
        px1 = (edge.bx + bdx) * CELL
        py1 = (edge.by + bdy) * CELL
        out.append(
            f'<line x1="{px0}" y1="{py0}" '
            f'x2="{px1}" y2="{py1}" '
            f'stroke="{color}" '
            f'stroke-width="{_INTERIOR_WALL_STROKE_WIDTH}" '
            f'stroke-linecap="round"/>'
        )
    return out


_OP_HANDLERS[Op.Op.BuildingInteriorWallOp] = (
    _draw_building_interior_wall_from_ir
)
