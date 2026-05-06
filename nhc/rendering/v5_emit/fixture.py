"""Builder / level walk → ``V5OpEntry(V5FixtureOp)``.

Phase 4.3a entry point. :func:`emit_fixtures` walks level features
(stairs, wells, fountains, trees, bushes) directly to produce one
``V5FixtureOp`` per kind / variant / grove. Mirrors the source
logic of :func:`nhc.rendering._floor_layers._emit_stairs_ir` and
:func:`nhc.rendering._floor_layers._emit_surface_features_ir`.

The emit order matches the v4 IR_STAGES sequence: stairs first,
then wells / fountains / trees / bushes (the surface-features
layer). Web / Skull / Bone / LooseStone fixtures continue to ride
through :mod:`thematic_detail` for the moment; that module owns
the per-tile probability gate from the Rust binding.

:func:`translate_fixtures` is retained as a back-compat shim for
:func:`translate_all` and walks ``builder.ops`` for v4 feature
ops + stairs.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5Anchor import V5AnchorT
from nhc.rendering.ir._fb.V5FixtureKind import V5FixtureKind
from nhc.rendering.ir._fb.V5FixtureOp import V5FixtureOpT
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT


def _make_anchor(
    x: int, y: int, *, variant: int = 0, orientation: int = 0,
    scale: int = 0, group_id: int = 0,
) -> V5AnchorT:
    a = V5AnchorT()
    a.x = x
    a.y = y
    a.variant = variant
    a.orientation = orientation
    a.scale = scale
    a.groupId = group_id
    return a


def _wrap(fixture_op: V5FixtureOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5FixtureOp
    entry.op = fixture_op
    return entry


def _make_fixture_op(
    *, region_ref: str, kind: int, anchors: list[V5AnchorT], seed: int,
) -> V5FixtureOpT:
    op = V5FixtureOpT()
    op.regionRef = region_ref
    op.kind = kind
    op.anchors = list(anchors)
    op.seed = seed
    return op


def emit_fixtures(builder: Any) -> list[V5OpEntryT]:
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
    result: list[V5OpEntryT] = []

    # 1. Stairs — emitted in IR_STAGES before surface features, so
    # they appear first in builder.ops; mirror that order.
    stair_anchors: list[V5AnchorT] = []
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
            kind=V5FixtureKind.Stair,
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
            kind=V5FixtureKind.Well,
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
            kind=V5FixtureKind.Fountain,
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
                kind=V5FixtureKind.Tree,
                anchors=free_anchors,
                seed=seed,
            )))
        grove_anchors: list[V5AnchorT] = []
        for grove_idx, grove_tiles in enumerate(tree_groves):
            group_id = grove_idx + 1
            for (x, y) in grove_tiles:
                grove_anchors.append(
                    _make_anchor(x, y, group_id=group_id)
                )
        if grove_anchors:
            result.append(_wrap(_make_fixture_op(
                region_ref="",
                kind=V5FixtureKind.Tree,
                anchors=grove_anchors,
                seed=seed,
            )))

    # 5. Bushes — gated on vegetation_enabled.
    if getattr(ctx, "vegetation_enabled", False):
        bush_anchors: list[V5AnchorT] = []
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature == "bush":
                    bush_anchors.append(_make_anchor(x, y))
        if bush_anchors:
            result.append(_wrap(_make_fixture_op(
                region_ref="",
                kind=V5FixtureKind.Bush,
                anchors=bush_anchors,
                seed=seed,
            )))

    return result


def _tiles_to_anchors(tiles: Any) -> list[V5AnchorT]:
    return [_make_anchor(int(t.x), int(t.y)) for t in (tiles or [])]


def translate_fixtures(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate per-feature v4 ops into ``V5FixtureOp`` entries.

    Retained for back-compat with :func:`translate_all`. Mirrors
    the pre-Phase-4.3a translator.
    """
    result: list[V5OpEntryT] = []
    for entry in ops:
        op_type = getattr(entry, "opType", None)
        if op_type == Op.TreeFeatureOp:
            tree = entry.op
            seed = int(getattr(tree, "seed", 0) or 0)
            free_anchors = _tiles_to_anchors(tree.tiles)
            if free_anchors:
                result.append(_wrap(_make_fixture_op(
                    region_ref="",
                    kind=V5FixtureKind.Tree,
                    anchors=free_anchors,
                    seed=seed,
                )))
            grove_anchors: list[V5AnchorT] = []
            cursor = 0
            for grove_idx, grove_size in enumerate(tree.groveSizes or []):
                group_id = grove_idx + 1
                size = int(grove_size)
                for j in range(size):
                    if cursor + j >= len(tree.groveTiles or []):
                        break
                    t = tree.groveTiles[cursor + j]
                    grove_anchors.append(
                        _make_anchor(int(t.x), int(t.y), group_id=group_id)
                    )
                cursor += size
            if grove_anchors:
                result.append(_wrap(_make_fixture_op(
                    region_ref="",
                    kind=V5FixtureKind.Tree,
                    anchors=grove_anchors,
                    seed=seed,
                )))
        elif op_type == Op.BushFeatureOp:
            bush = entry.op
            anchors = _tiles_to_anchors(bush.tiles)
            if anchors:
                result.append(_wrap(_make_fixture_op(
                    region_ref="",
                    kind=V5FixtureKind.Bush,
                    anchors=anchors,
                    seed=int(getattr(bush, "seed", 0) or 0),
                )))
        elif op_type == Op.WellFeatureOp:
            well = entry.op
            anchors = [
                _make_anchor(int(t.x), int(t.y), variant=int(well.shape))
                for t in (well.tiles or [])
            ]
            if anchors:
                result.append(_wrap(_make_fixture_op(
                    region_ref="",
                    kind=V5FixtureKind.Well,
                    anchors=anchors,
                    seed=int(getattr(well, "seed", 0) or 0),
                )))
        elif op_type == Op.FountainFeatureOp:
            fountain = entry.op
            anchors = [
                _make_anchor(
                    int(t.x), int(t.y), variant=int(fountain.shape)
                )
                for t in (fountain.tiles or [])
            ]
            if anchors:
                result.append(_wrap(_make_fixture_op(
                    region_ref="",
                    kind=V5FixtureKind.Fountain,
                    anchors=anchors,
                    seed=int(getattr(fountain, "seed", 0) or 0),
                )))
        elif op_type == Op.StairsOp:
            stairs = entry.op
            anchors_st: list[V5AnchorT] = []
            for st in stairs.stairs or []:
                anchors_st.append(_make_anchor(
                    int(st.x), int(st.y),
                    variant=0,
                    orientation=int(st.direction),
                ))
            if anchors_st:
                result.append(_wrap(_make_fixture_op(
                    region_ref="",
                    kind=V5FixtureKind.Stair,
                    anchors=anchors_st,
                    seed=0,
                )))
    return result
