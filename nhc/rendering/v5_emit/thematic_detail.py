"""``ThematicDetailOp`` / ``FloorDetailOp`` → ``V5FixtureOp`` anchors.

The v4 ThematicDetailOp ships a candidate-tile list (every floor
tile that could host a web / bone / skull) plus the per-tile
wall-corner bitmap; the v4 painter applies a per-tile probability
gate to decide which tiles get which fixture. v5 anchors are
explicit — every anchor IS a stamp, no probability gate at paint
time. This translator runs the v4 gate at emit time (via the
PyO3 binding ``nhc_render.thematic_detail_anchors``, which walks
the same Pcg64Mcg RNG stream as the v4 painter) and lands one
V5FixtureOp(Web / Skull / Bone) per gated tile.

Same shape for ``FloorDetailOp`` → ``V5FixtureOp(LooseStone)`` —
the v4 floor-detail painter's stones bucket maps to the v5
LooseStone fixture kind. The ``floor_detail_loose_stone_anchors``
binding runs the gate and returns the tile coords where the v4
painter would have rendered loose-stone clusters.

Both translators share the (theme, macabre) defaults: theme is
the v4 op's theme string; macabre defaults to True (the v4 emit
path enables macabre detail unless the dungeon flags explicitly
turn it off — see ``ctx.macabre_detail``).
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5Anchor import V5AnchorT
from nhc.rendering.ir._fb.V5FixtureKind import V5FixtureKind
from nhc.rendering.ir._fb.V5FixtureOp import V5FixtureOpT
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT


# Match ``primitives::thematic_detail::KIND_*`` constants.
_THEM_KIND_TO_V5: dict[int, int] = {
    0: V5FixtureKind.Web,
    1: V5FixtureKind.Skull,
    2: V5FixtureKind.Bone,
}


def _make_anchor(
    x: int, y: int, *, variant: int = 0, orientation: int = 0,
) -> V5AnchorT:
    a = V5AnchorT()
    a.x = x
    a.y = y
    a.variant = variant
    a.orientation = orientation
    a.scale = 0
    a.groupId = 0
    return a


def _wrap(fixture_op: V5FixtureOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5FixtureOp
    entry.op = fixture_op
    return entry


def _make_fixture_op(
    *, kind: int, anchors: list[V5AnchorT], seed: int,
) -> V5FixtureOpT:
    op = V5FixtureOpT()
    op.regionRef = ""
    op.kind = kind
    op.anchors = list(anchors)
    op.seed = seed
    return op


def translate_thematic_detail_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate ThematicDetailOp into per-kind V5FixtureOp entries.

    Calls into ``nhc_render.thematic_detail_anchors`` to run the
    v4 probability gate; buckets the resulting placements per
    V5FixtureKind so each kind ships as its own V5FixtureOp.
    """
    try:
        from nhc_render import thematic_detail_anchors
    except (ImportError, AttributeError):
        # Rust binding unavailable (eg. tests running before
        # ``make rust-build``). Skip emit-side translation; the v4
        # render path still ships a working ThematicDetailOp.
        return []

    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.ThematicDetailOp:
            continue
        op = entry.op
        tiles_payload: list[tuple[int, int, bool, int]] = []
        n = len(op.tiles or [])
        is_corridor = list(op.isCorridor or [])
        wall_corners = list(op.wallCorners or [])
        for i, t in enumerate(op.tiles or []):
            ic = bool(is_corridor[i]) if i < len(is_corridor) else False
            wc = int(wall_corners[i]) if i < len(wall_corners) else 0
            tiles_payload.append((int(t.x), int(t.y), ic, wc))
        seed = int(getattr(op, "seed", 0) or 0)
        theme = (getattr(op, "theme", "") or "dungeon").decode("utf-8") if isinstance(getattr(op, "theme", ""), bytes) else (getattr(op, "theme", "") or "dungeon")
        # Macabre defaults to True — v4 emit path gates this on
        # ``ctx.macabre_detail`` but ThematicDetailOp doesn't carry
        # the flag. Phase 4.x emit can plumb it through; for now
        # match the v4 painter's default (macabre=True when the
        # ThematicDetailOp is emitted at all).
        macabre = True
        placements = thematic_detail_anchors(tiles_payload, seed, theme, macabre)

        # Bucket placements per kind.
        per_kind: dict[int, list[V5AnchorT]] = {}
        for kind_u8, x, y, orientation in placements:
            v5_kind = _THEM_KIND_TO_V5.get(int(kind_u8))
            if v5_kind is None:
                continue
            per_kind.setdefault(v5_kind, []).append(
                _make_anchor(int(x), int(y), orientation=int(orientation))
            )

        for v5_kind, anchors in per_kind.items():
            if not anchors:
                continue
            result.append(
                _wrap(_make_fixture_op(kind=v5_kind, anchors=anchors, seed=seed))
            )
        # Sort by kind for deterministic ordering across runs.
        n = n  # silence unused-var lints
    return result


def translate_floor_detail_loose_stones(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate the FloorDetailOp's stones bucket into a single
    V5FixtureOp(LooseStone). Cracks and Scratches buckets are
    handled by ``v5_emit.stamp.translate_stamp_ops`` — same source
    op, different output op kind.
    """
    try:
        from nhc_render import floor_detail_loose_stone_anchors
    except (ImportError, AttributeError):
        return []

    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.FloorDetailOp:
            continue
        op = entry.op
        tiles_payload: list[tuple[int, int, bool]] = []
        is_corridor = list(getattr(op, "isCorridor", []) or [])
        for i, t in enumerate(op.tiles or []):
            ic = bool(is_corridor[i]) if i < len(is_corridor) else False
            tiles_payload.append((int(t.x), int(t.y), ic))
        seed = int(getattr(op, "seed", 0) or 0)
        theme = getattr(op, "theme", "") or "dungeon"
        if isinstance(theme, bytes):
            theme = theme.decode("utf-8")
        macabre = True
        coords = floor_detail_loose_stone_anchors(
            tiles_payload, seed, theme, macabre
        )
        if not coords:
            continue
        anchors = [_make_anchor(int(x), int(y)) for (x, y) in coords]
        result.append(
            _wrap(_make_fixture_op(
                kind=V5FixtureKind.LooseStone,
                anchors=anchors,
                seed=seed,
            ))
        )
    return result
