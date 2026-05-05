"""Per-feature v4 ops → ``V5FixtureOp``.

Translates the discrete-object v4 ops (``TreeFeatureOp``,
``BushFeatureOp``, ``WellFeatureOp``, ``FountainFeatureOp``,
``StairsOp``) plus the scatter parts of ``ThematicDetailOp``
(webs / bones / skulls) into per-kind ``V5FixtureOp`` entries.

Phase 1.4 ships a thin scaffold:
- One ``V5FixtureOp`` per source op, with anchors built from the
  source op's tile list.
- Variants / orientations / scales default to 0 (the v5 painter
  picks a per-tile variant from the op seed).
- ``group_id`` defaults to 0 (no fusion). Tree groves and other
  cluster fusion lands at Phase 2.11 when the per-fixture
  painters are built out.
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
    x: int, y: int, *, variant: int = 0, orientation: int = 0, scale: int = 0,
    group_id: int = 0,
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
    *, region_ref: str, kind: int, anchors: list[V5AnchorT], seed: int
) -> V5FixtureOpT:
    op = V5FixtureOpT()
    op.regionRef = region_ref
    op.kind = kind
    op.anchors = list(anchors)
    op.seed = seed
    return op


def _tiles_to_anchors(tiles) -> list[V5AnchorT]:
    return [_make_anchor(int(t.x), int(t.y)) for t in (tiles or [])]


def translate_fixtures(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate per-feature v4 ops into ``V5FixtureOp`` entries."""
    result: list[V5OpEntryT] = []
    for entry in ops:
        op_type = getattr(entry, "opType", None)
        if op_type == Op.TreeFeatureOp:
            tree = entry.op
            seed = int(getattr(tree, "seed", 0) or 0)
            # Free trees (tiles) — one anchor each, no group.
            free_anchors = _tiles_to_anchors(tree.tiles)
            if free_anchors:
                result.append(
                    _wrap(
                        _make_fixture_op(
                            region_ref="",
                            kind=V5FixtureKind.Tree,
                            anchors=free_anchors,
                            seed=seed,
                        )
                    )
                )
            # Groves — anchors share a group_id per grove. The v5
            # painter unions canopies across the same group_id.
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
                result.append(
                    _wrap(
                        _make_fixture_op(
                            region_ref="",
                            kind=V5FixtureKind.Tree,
                            anchors=grove_anchors,
                            seed=seed,
                        )
                    )
                )
        elif op_type == Op.BushFeatureOp:
            bush = entry.op
            anchors = _tiles_to_anchors(bush.tiles)
            if anchors:
                result.append(
                    _wrap(
                        _make_fixture_op(
                            region_ref="",
                            kind=V5FixtureKind.Bush,
                            anchors=anchors,
                            seed=int(getattr(bush, "seed", 0) or 0),
                        )
                    )
                )
        elif op_type == Op.WellFeatureOp:
            well = entry.op
            anchors = [
                _make_anchor(int(t.x), int(t.y), variant=int(well.shape))
                for t in (well.tiles or [])
            ]
            if anchors:
                result.append(
                    _wrap(
                        _make_fixture_op(
                            region_ref="",
                            kind=V5FixtureKind.Well,
                            anchors=anchors,
                            seed=int(getattr(well, "seed", 0) or 0),
                        )
                    )
                )
        elif op_type == Op.FountainFeatureOp:
            fountain = entry.op
            anchors = [
                _make_anchor(int(t.x), int(t.y), variant=int(fountain.shape))
                for t in (fountain.tiles or [])
            ]
            if anchors:
                result.append(
                    _wrap(
                        _make_fixture_op(
                            region_ref="",
                            kind=V5FixtureKind.Fountain,
                            anchors=anchors,
                            seed=int(getattr(fountain, "seed", 0) or 0),
                        )
                    )
                )
        elif op_type == Op.StairsOp:
            stairs = entry.op
            anchors: list[V5AnchorT] = []
            for st in stairs.stairs or []:
                anchors.append(
                    _make_anchor(
                        int(st.x), int(st.y),
                        variant=0,
                        orientation=int(st.direction),
                    )
                )
            if anchors:
                result.append(
                    _wrap(
                        _make_fixture_op(
                            region_ref="",
                            kind=V5FixtureKind.Stair,
                            anchors=anchors,
                            seed=0,
                        )
                    )
                )
    return result
