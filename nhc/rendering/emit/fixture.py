"""Builder / level walk → ``V5OpEntry(V5FixtureOp)``.

:func:`emit_fixtures` walks level features (stairs, wells,
fountains, trees, bushes) directly to produce one ``V5FixtureOp``
per kind / variant / grove. Mirrors the source logic of
:func:`nhc.rendering._floor_layers._emit_stairs_ir` and
:func:`nhc.rendering._floor_layers._emit_surface_features_ir`.

The emit order matches the v4 IR_STAGES sequence: stairs first,
then wells / fountains / trees / bushes (the surface-features
layer). Web / Skull / Bone / LooseStone fixtures continue to ride
through :mod:`thematic_detail`; that module owns the per-tile
probability gate from the Rust binding.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Anchor import AnchorT
from nhc.rendering.ir._fb.FixtureKind import FixtureKind
from nhc.rendering.ir._fb.FixtureOp import FixtureOpT
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT


def _make_anchor(
    x: int, y: int, *, variant: int = 0, orientation: int = 0,
    scale: int = 0, group_id: int = 0,
    cx_off: int = 0, cy_off: int = 0,
) -> AnchorT:
    """Build an AnchorT with the v5 schema fields populated.

    ``cx_off`` / ``cy_off`` are optional sub-tile fractional
    offsets in 1/256 units (0..255 → 0..0.996 fractional position
    within the tile). Default ``0, 0`` is the back-compat sentinel
    that asks the painter to fall back to its anchor_rng-derived
    placement; setting either non-zero switches the painter to
    the explicit-position path. See ``floor_ir.fbs::Anchor`` for
    the wire-format contract.
    """
    a = AnchorT()
    a.x = x
    a.y = y
    a.variant = variant
    a.orientation = orientation
    a.scale = scale
    a.cxOff = cx_off
    a.groupId = group_id
    a.cyOff = cy_off
    return a


def _wrap(fixture_op: FixtureOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.FixtureOp
    entry.op = fixture_op
    return entry


def _make_fixture_op(
    *, region_ref: str, kind: int, anchors: list[AnchorT], seed: int,
) -> FixtureOpT:
    op = FixtureOpT()
    op.regionRef = region_ref
    op.kind = kind
    op.anchors = list(anchors)
    op.seed = seed
    return op


def emit_fixtures(builder: Any) -> list[OpEntryT]:
    """Walk level features to produce V5FixtureOp entries.

    Defensive on synthetic fixture builders: returns an empty list
    when ``level.tiles`` is missing.
    """
    ctx = builder.ctx
    level = ctx.level
    tiles_grid = getattr(level, "tiles", None)
    if tiles_grid is None:
        return []

    seed = ctx.seed
    result: list[OpEntryT] = []

    # 1. Stairs — emitted in IR_STAGES before surface features, so
    # they appear first in builder.ops; mirror that order.
    stair_anchors: list[AnchorT] = []
    for y in range(level.height):
        for x in range(level.width):
            feat = level.tiles[y][x].feature
            # StairDirection enum: Up=0, Down=1 (per floor_ir.fbs).
            if feat == "stairs_up":
                stair_anchors.append(_make_anchor(
                    x, y, variant=0, orientation=0,
                ))
            elif feat == "stairs_down":
                stair_anchors.append(_make_anchor(
                    x, y, variant=0, orientation=1,
                ))
    if stair_anchors:
        result.append(_wrap(_make_fixture_op(
            region_ref="",
            kind=FixtureKind.Stair,
            anchors=stair_anchors,
            seed=0,  # translate_fixtures passes seed=0 for stairs
        )))

    # 2. Wells — per shape, in (Round, Square) order.
    well_round: list[tuple[int, int]] = []
    well_square: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            f = level.tiles[y][x].feature
            if f == "well":
                well_round.append((x, y))
            elif f == "well_square":
                well_square.append((x, y))
    for shape_idx, shape_tiles in ((0, well_round), (1, well_square)):
        if not shape_tiles:
            continue
        anchors = [
            _make_anchor(x, y, variant=shape_idx)
            for (x, y) in shape_tiles
        ]
        result.append(_wrap(_make_fixture_op(
            region_ref="",
            kind=FixtureKind.Well,
            anchors=anchors,
            seed=seed,
        )))

    # 3. Fountains — per shape, in (Round, Square, LargeRound,
    # LargeSquare, Cross) order.
    fountain_buckets: list[tuple[int, list[tuple[int, int]]]] = [
        (0, []),  # Round
        (1, []),  # Square
        (2, []),  # LargeRound
        (3, []),  # LargeSquare
        (4, []),  # Cross
    ]
    fountain_feature_to_idx = {
        "fountain": 0,
        "fountain_square": 1,
        "fountain_large": 2,
        "fountain_large_square": 3,
        "fountain_cross": 4,
    }
    for y in range(level.height):
        for x in range(level.width):
            idx = fountain_feature_to_idx.get(
                level.tiles[y][x].feature
            )
            if idx is None:
                continue
            fountain_buckets[idx][1].append((x, y))
    for shape_idx, shape_tiles in fountain_buckets:
        if not shape_tiles:
            continue
        anchors = [
            _make_anchor(x, y, variant=shape_idx)
            for (x, y) in shape_tiles
        ]
        result.append(_wrap(_make_fixture_op(
            region_ref="",
            kind=FixtureKind.Fountain,
            anchors=anchors,
            seed=seed,
        )))

    # 4. Trees — split into free anchors (size <= 2 groves) and
    # grove anchors (size >= 3 groves), each emitted as a separate
    # V5FixtureOp; the grove path attaches a per-grove group_id so
    # the painter can fuse canopies.
    free_tree_tiles: list[tuple[int, int]] = []
    tree_groves: list[list[tuple[int, int]]] = []
    if getattr(ctx, "vegetation_enabled", False):
        from nhc.rendering._features_svg import _connected_tree_groves
        for grove in _connected_tree_groves(level):
            tiles = sorted(grove)
            if len(tiles) <= 2:
                free_tree_tiles.extend(tiles)
            else:
                tree_groves.append(tiles)
    if free_tree_tiles or tree_groves:
        free_anchors = [
            _make_anchor(x, y) for (x, y) in free_tree_tiles
        ]
        if free_anchors:
            result.append(_wrap(_make_fixture_op(
                region_ref="",
                kind=FixtureKind.Tree,
                anchors=free_anchors,
                seed=seed,
            )))
        grove_anchors: list[AnchorT] = []
        for grove_idx, grove_tiles in enumerate(tree_groves):
            group_id = grove_idx + 1
            for (x, y) in grove_tiles:
                grove_anchors.append(
                    _make_anchor(x, y, group_id=group_id)
                )
        if grove_anchors:
            result.append(_wrap(_make_fixture_op(
                region_ref="",
                kind=FixtureKind.Tree,
                anchors=grove_anchors,
                seed=seed,
            )))

    # 5. Bushes — gated on vegetation_enabled.
    if getattr(ctx, "vegetation_enabled", False):
        bush_anchors: list[AnchorT] = []
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature == "bush":
                    bush_anchors.append(_make_anchor(x, y))
        if bush_anchors:
            result.append(_wrap(_make_fixture_op(
                region_ref="",
                kind=FixtureKind.Bush,
                anchors=bush_anchors,
                seed=seed,
            )))

    # 6. Flowers — manicured garden beds; gated on
    # vegetation_enabled like bushes.
    if getattr(ctx, "vegetation_enabled", False):
        flower_anchors: list[AnchorT] = []
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature == "flower":
                    flower_anchors.append(_make_anchor(x, y))
        if flower_anchors:
            result.append(_wrap(_make_fixture_op(
                region_ref="",
                kind=FixtureKind.Flower,
                anchors=flower_anchors,
                seed=seed,
            )))

    return result

