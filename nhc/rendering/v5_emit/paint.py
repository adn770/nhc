"""``FloorOp`` (+ DecoratorOp stone variants) → ``V5PaintOp``.

The v4 emitter splits "base floor fill" (``FloorOp``) from "stone
pattern overlay" (``DecoratorOp.cobblestone`` /
``.brick`` / ``.flagstone`` / ``.opus_romano`` / ``.field_stone``).
v5 collapses both into a single ``V5PaintOp`` per region with a
Material that carries the full ``(family, style, sub_pattern,
tone)`` tuple.

For the Phase 1.4 scaffold the translator emits one
``V5PaintOp`` per ``FloorOp`` (mapping ``FloorStyle`` →
``Material``) and one additional ``V5PaintOp`` per non-empty
``DecoratorOp`` stone variant (mapping the variant to
``Material(family=Stone, ...)`` against the same region). Phase 1.5
validates the resulting visual via the parity gate; Phase 2.4
introduces real Stone-family painters that consume these ops.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5PaintOp import V5PaintOpT
from nhc.rendering.v5_emit.materials import (
    material_from_cobble_pattern,
    material_from_floor_style,
    material_stone,
    STONE_BRICK,
    STONE_BRICK_RUNNING_BOND,
    STONE_FIELDSTONE,
    STONE_FLAGSTONE,
    STONE_OPUS_ROMANO,
)


def _wrap(paint_op: V5PaintOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5PaintOp
    entry.op = paint_op
    return entry


def _make_paint_op(
    *, region_ref: str, material, subtract_region_refs: list[str] | None = None
) -> V5PaintOpT:
    op = V5PaintOpT()
    op.regionRef = region_ref
    op.subtractRegionRefs = list(subtract_region_refs or [])
    op.material = material
    return op


def translate_paint_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate every paint-shaped v4 op into ``V5PaintOp`` entries.

    Walks the v4 op stream:
    - ``FloorOp`` → one ``V5PaintOp(material_from_floor_style)``
    - ``DecoratorOp`` stone variants → one ``V5PaintOp`` per
      non-empty variant, all targeting the DecoratorOp's
      ``region_ref`` (typically the dungeon polygon).
    """
    result: list[V5OpEntryT] = []
    for entry in ops:
        op_type = getattr(entry, "opType", None)
        if op_type == Op.FloorOp:
            floor_op = entry.op
            material = material_from_floor_style(
                floor_op.style, seed=getattr(entry, "_seed", 0)
            )
            paint_op = _make_paint_op(
                region_ref=floor_op.regionRef or "",
                material=material,
            )
            result.append(_wrap(paint_op))
        elif op_type == Op.DecoratorOp:
            result.extend(_translate_decorator_op(entry.op))
    return result


def _translate_decorator_op(deco) -> list[V5OpEntryT]:
    """Walk DecoratorOp's parallel variant lists and emit one
    ``V5PaintOp`` per non-empty stone-pattern variant.

    Cart-tracks and ore-deposit ride through ``translate_path_ops``;
    they're skipped here.
    """
    rr = deco.regionRef or ""
    seed = int(getattr(deco, "seed", 0))
    out: list[V5OpEntryT] = []

    for variant in deco.cobblestone or []:
        if not variant.tiles:
            continue
        material = material_from_cobble_pattern(variant.pattern, seed=seed)
        out.append(_wrap(_make_paint_op(region_ref=rr, material=material)))

    for variant in deco.brick or []:
        if not variant.tiles:
            continue
        material = material_stone(
            style=STONE_BRICK,
            sub_pattern=STONE_BRICK_RUNNING_BOND,
            seed=seed,
        )
        out.append(_wrap(_make_paint_op(region_ref=rr, material=material)))

    for variant in deco.flagstone or []:
        if not variant.tiles:
            continue
        material = material_stone(style=STONE_FLAGSTONE, seed=seed)
        out.append(_wrap(_make_paint_op(region_ref=rr, material=material)))

    for variant in deco.opusRomano or []:
        if not variant.tiles:
            continue
        material = material_stone(style=STONE_OPUS_ROMANO, seed=seed)
        out.append(_wrap(_make_paint_op(region_ref=rr, material=material)))

    for variant in deco.fieldStone or []:
        if not variant.tiles:
            continue
        material = material_stone(style=STONE_FIELDSTONE, seed=seed)
        out.append(_wrap(_make_paint_op(region_ref=rr, material=material)))

    return out
