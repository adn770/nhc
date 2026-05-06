"""Builder / level walk → ``V5OpEntry(V5FixtureOp)`` for thematic +
loose-stone fixtures.

:func:`emit_thematic_details` walks the floor-detail candidate set
+ the per-tile wall-corner bitmap and runs the v4 probability
gate via the ``nhc_render.thematic_detail_anchors`` PyO3 binding
to produce per-kind ``V5FixtureOp(Web | Skull | Bone)`` entries.
:func:`emit_loose_stones` runs the analogous gate via
``nhc_render.floor_detail_loose_stone_anchors`` to produce a
single ``V5FixtureOp(LooseStone)``.

Both translators share the (theme, macabre) defaults from the v4
emit pipeline; macabre defaults to True (the v4 emit path enables
macabre detail unless the dungeon flags explicitly turn it off —
see ``ctx.macabre_detail``).
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Anchor import AnchorT
from nhc.rendering.ir._fb.FixtureKind import FixtureKind
from nhc.rendering.ir._fb.FixtureOp import FixtureOpT
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT


# Match ``primitives::thematic_detail::KIND_*`` constants.
_THEM_KIND_TO_V5: dict[int, int] = {
    0: FixtureKind.Web,
    1: FixtureKind.Skull,
    2: FixtureKind.Bone,
}


def _make_anchor(
    x: int, y: int, *, variant: int = 0, orientation: int = 0,
) -> AnchorT:
    a = AnchorT()
    a.x = x
    a.y = y
    a.variant = variant
    a.orientation = orientation
    a.scale = 0
    a.groupId = 0
    return a


def _wrap(fixture_op: FixtureOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.FixtureOp
    entry.op = fixture_op
    return entry


def _make_fixture_op(
    *, kind: int, anchors: list[AnchorT], seed: int,
) -> FixtureOpT:
    op = FixtureOpT()
    op.regionRef = ""
    op.kind = kind
    op.anchors = list(anchors)
    op.seed = seed
    return op


def _candidates_with_wall_corners(level: Any) -> tuple[
    list[tuple[int, int, bool, int]],
    list[tuple[int, int, bool]],
]:
    """Walk the floor-detail candidate set once and return
    ``(thematic_payload, floor_detail_payload)``.

    ``thematic_payload`` is ``[(x, y, is_corridor, wall_corners), ...]``
    matching the v4 ``ThematicDetailOp`` per-tile shape (4-bit
    wall-adjacency bitmap from ``_emit_thematic_detail_ir``).
    ``floor_detail_payload`` is ``[(x, y, is_corridor), ...]`` matching
    the v4 ``FloorDetailOp`` per-tile shape used by the
    loose-stones gate.
    """
    from nhc.rendering._floor_layers import _floor_detail_candidates
    from nhc.rendering._svg_helpers import _is_floor

    candidates = _floor_detail_candidates(level)
    thematic_payload: list[tuple[int, int, bool, int]] = []
    detail_payload: list[tuple[int, int, bool]] = []
    for x, y, is_cor in candidates:
        bits = 0
        if not _is_floor(level, x, y - 1) and not _is_floor(level, x - 1, y):
            bits |= 0x01
        if not _is_floor(level, x, y - 1) and not _is_floor(level, x + 1, y):
            bits |= 0x02
        if not _is_floor(level, x, y + 1) and not _is_floor(level, x - 1, y):
            bits |= 0x04
        if not _is_floor(level, x, y + 1) and not _is_floor(level, x + 1, y):
            bits |= 0x08
        thematic_payload.append((x, y, is_cor, bits))
        detail_payload.append((x, y, is_cor))
    return thematic_payload, detail_payload


def emit_thematic_details(builder: Any) -> list[OpEntryT]:
    """Walk the candidate set and emit Web / Skull / Bone fixtures.

    Wood-floor short-circuit and missing-binding fallback both
    return an empty list.
    """
    try:
        from nhc_render import thematic_detail_anchors
    except (ImportError, AttributeError):
        return []

    ctx = builder.ctx
    level = ctx.level
    if getattr(ctx, "interior_finish", "") == "wood":
        return []
    if getattr(level, "tiles", None) is None:
        return []

    thematic_payload, _ = _candidates_with_wall_corners(level)
    if not thematic_payload:
        return []

    seed = ctx.seed + 199
    theme = getattr(ctx, "theme", "") or "dungeon"
    if isinstance(theme, bytes):
        theme = theme.decode("utf-8")
    macabre = True

    placements = thematic_detail_anchors(
        thematic_payload, seed, theme, macabre,
    )

    per_kind: dict[int, list[AnchorT]] = {}
    for kind_u8, x, y, orientation in placements:
        v5_kind = _THEM_KIND_TO_V5.get(int(kind_u8))
        if v5_kind is None:
            continue
        per_kind.setdefault(v5_kind, []).append(
            _make_anchor(int(x), int(y), orientation=int(orientation))
        )

    return [
        _wrap(_make_fixture_op(kind=v5_kind, anchors=anchors, seed=seed))
        for v5_kind, anchors in per_kind.items()
        if anchors
    ]


def emit_loose_stones(builder: Any) -> list[OpEntryT]:
    """Walk the candidate set and emit the LooseStone fixture op.

    Wood-floor short-circuit and missing-binding fallback both
    return an empty list.
    """
    try:
        from nhc_render import floor_detail_loose_stone_anchors
    except (ImportError, AttributeError):
        return []

    ctx = builder.ctx
    level = ctx.level
    if getattr(ctx, "interior_finish", "") == "wood":
        return []
    if getattr(level, "tiles", None) is None:
        return []

    _, detail_payload = _candidates_with_wall_corners(level)
    if not detail_payload:
        return []

    seed = ctx.seed + 99
    theme = getattr(ctx, "theme", "") or "dungeon"
    if isinstance(theme, bytes):
        theme = theme.decode("utf-8")
    macabre = True

    coords = floor_detail_loose_stone_anchors(
        detail_payload, seed, theme, macabre,
    )
    if not coords:
        return []
    anchors = [_make_anchor(int(x), int(y)) for (x, y) in coords]
    return [_wrap(_make_fixture_op(
        kind=FixtureKind.LooseStone,
        anchors=anchors,
        seed=seed,
    ))]

