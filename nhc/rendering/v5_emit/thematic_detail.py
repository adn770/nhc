"""Builder / level walk → ``V5OpEntry(V5FixtureOp)`` for thematic +
loose-stone fixtures.

Phase 4.3a entry point. :func:`emit_thematic_details` walks the
floor-detail candidate set + the per-tile wall-corner bitmap and
runs the v4 probability gate via the
``nhc_render.thematic_detail_anchors`` PyO3 binding to produce
per-kind ``V5FixtureOp(Web | Skull | Bone)`` entries.
:func:`emit_loose_stones` runs the analogous gate via
``nhc_render.floor_detail_loose_stone_anchors`` to produce a
single ``V5FixtureOp(LooseStone)``.

Both translators share the (theme, macabre) defaults from the v4
emit pipeline; macabre defaults to True (the v4 emit path enables
macabre detail unless the dungeon flags explicitly turn it off —
see ``ctx.macabre_detail``).

:func:`translate_thematic_detail_ops` and
:func:`translate_floor_detail_loose_stones` are retained as
back-compat shims for :func:`translate_all`.
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


def emit_thematic_details(builder: Any) -> list[V5OpEntryT]:
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

    per_kind: dict[int, list[V5AnchorT]] = {}
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


def emit_loose_stones(builder: Any) -> list[V5OpEntryT]:
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
        kind=V5FixtureKind.LooseStone,
        anchors=anchors,
        seed=seed,
    ))]


# ── Back-compat shims for translate_all ────────────────────────


def translate_thematic_detail_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Walk every v4 ``ThematicDetailOp`` and emit per-kind fixtures.

    Retained for back-compat with :func:`translate_all`.
    """
    try:
        from nhc_render import thematic_detail_anchors
    except (ImportError, AttributeError):
        return []

    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.ThematicDetailOp:
            continue
        op = entry.op
        tiles_payload: list[tuple[int, int, bool, int]] = []
        is_corridor = list(op.isCorridor or [])
        wall_corners = list(op.wallCorners or [])
        for i, t in enumerate(op.tiles or []):
            ic = bool(is_corridor[i]) if i < len(is_corridor) else False
            wc = int(wall_corners[i]) if i < len(wall_corners) else 0
            tiles_payload.append((int(t.x), int(t.y), ic, wc))
        seed = int(getattr(op, "seed", 0) or 0)
        theme_raw = getattr(op, "theme", "") or "dungeon"
        theme = theme_raw.decode("utf-8") if isinstance(
            theme_raw, bytes
        ) else theme_raw
        macabre = True
        placements = thematic_detail_anchors(
            tiles_payload, seed, theme, macabre,
        )

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
            result.append(_wrap(_make_fixture_op(
                kind=v5_kind, anchors=anchors, seed=seed,
            )))
    return result


def translate_floor_detail_loose_stones(ops: list[Any]) -> list[V5OpEntryT]:
    """Walk every v4 ``FloorDetailOp`` and emit a LooseStone fixture.

    Retained for back-compat with :func:`translate_all`.
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
        theme_raw = getattr(op, "theme", "") or "dungeon"
        theme = theme_raw.decode("utf-8") if isinstance(
            theme_raw, bytes
        ) else theme_raw
        macabre = True
        coords = floor_detail_loose_stone_anchors(
            tiles_payload, seed, theme, macabre,
        )
        if not coords:
            continue
        anchors = [_make_anchor(int(x), int(y)) for (x, y) in coords]
        result.append(_wrap(_make_fixture_op(
            kind=V5FixtureKind.LooseStone,
            anchors=anchors,
            seed=seed,
        )))
    return result
