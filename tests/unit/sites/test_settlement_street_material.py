"""Per-size-class street material on settlements.

Settlements paint their street network (``SurfaceType.STREET`` tiles
collected as a ``paved.*`` region) with a material that varies by
size class to make each tier visually distinctive:

- hamlet  → Stone / FieldStone
- village → Stone / Cobblestone, sub_pattern Rubble
- town    → Stone / Flagstone
- city    → Stone / Brick, sub_pattern Flemish Bond

The override rides on ``Level.metadata.street_material`` (a
``(family, style, sub_pattern)`` triple). When set, the v5 emit
pipeline emits the configured material on every ``paved.*`` PaintOp
instead of the global Cobble Herringbone default. None falls back
to the default — non-settlement IRs (synthetic fixtures, keep
courtyards) keep the existing look.
"""

from __future__ import annotations

import json
import random

from nhc.rendering.ir.dump import dump
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.sites.town import assemble_town


# Mirrors ``nhc/rendering/emit/materials.py``.
_STONE = 3  # MaterialFamily.Stone

_STONE_COBBLESTONE = 0
_STONE_BRICK = 1
_STONE_FLAGSTONE = 2
_STONE_FIELDSTONE = 4

_STONE_COBBLE_RUBBLE = 2
_STONE_BRICK_FLEMISH_BOND = 2

_EXPECTED_STREET_MATERIAL: dict[str, tuple[str, int, int]] = {
    # (family_name, style, sub_pattern)
    "hamlet": ("Stone", _STONE_FIELDSTONE, 0),
    "village": ("Stone", _STONE_COBBLESTONE, _STONE_COBBLE_RUBBLE),
    "town": ("Stone", _STONE_FLAGSTONE, 0),
    # City pairs Flagstone streets with Ashlar Staggered open
    # pavement (see ``test_city_pavement_material.py``) for a
    # uniformly dressed-stone urban look.
    "city": ("Stone", _STONE_FLAGSTONE, 0),
}


def _ir_dict_for_settlement(size_class: str, seed: int) -> dict:
    site = assemble_town(
        f"settlement_{size_class}_seed{seed}",
        random.Random(seed),
        size_class=size_class,
    )
    buf = build_floor_ir(site.surface, seed=seed, site=site)
    return json.loads(dump(bytes(buf)))


def _paved_paint_ops(d: dict) -> list[dict]:
    out: list[dict] = []
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "PaintOp":
            continue
        op = entry.get("op") or {}
        rr = op.get("regionRef") or ""
        if rr.startswith("paved."):
            out.append(op)
    return out


class TestSettlementStreetMaterial:
    """Each settlement size class emits its paved.* PaintOp with the
    designated stone material — pin the material triple via the
    region prefix instead of pulling on rendered pixels."""

    def test_hamlet_street_renders_as_fieldstone(self) -> None:
        d = _ir_dict_for_settlement("hamlet", 7)
        ops = _paved_paint_ops(d)
        assert ops, "hamlet seed7: expected at least one paved.* PaintOp"
        for op in ops:
            mat = op.get("material") or {}
            assert mat.get("family") == "Stone", (
                f"hamlet street material family={mat.get('family')!r}"
            )
            assert mat.get("style") == _STONE_FIELDSTONE, (
                f"hamlet street style={mat.get('style')} "
                f"(expected FieldStone={_STONE_FIELDSTONE})"
            )

    def test_village_street_renders_as_cobble_rubble(self) -> None:
        d = _ir_dict_for_settlement("village", 7)
        ops = _paved_paint_ops(d)
        assert ops, "village seed7: expected at least one paved.* PaintOp"
        for op in ops:
            mat = op.get("material") or {}
            assert mat.get("family") == "Stone"
            assert mat.get("style") == _STONE_COBBLESTONE, (
                f"village street style={mat.get('style')} "
                f"(expected Cobblestone={_STONE_COBBLESTONE})"
            )
            assert mat.get("subPattern") == _STONE_COBBLE_RUBBLE, (
                f"village street sub_pattern={mat.get('subPattern')} "
                f"(expected Rubble={_STONE_COBBLE_RUBBLE})"
            )

    def test_town_street_renders_as_flagstone(self) -> None:
        d = _ir_dict_for_settlement("town", 7)
        ops = _paved_paint_ops(d)
        assert ops, "town seed7: expected at least one paved.* PaintOp"
        for op in ops:
            mat = op.get("material") or {}
            assert mat.get("family") == "Stone"
            assert mat.get("style") == _STONE_FLAGSTONE, (
                f"town street style={mat.get('style')} "
                f"(expected Flagstone={_STONE_FLAGSTONE})"
            )

    def test_city_street_renders_as_flagstone(self) -> None:
        d = _ir_dict_for_settlement("city", 7)
        ops = _paved_paint_ops(d)
        assert ops, "city seed7: expected at least one paved.* PaintOp"
        for op in ops:
            mat = op.get("material") or {}
            assert mat.get("family") == "Stone"
            assert mat.get("style") == _STONE_FLAGSTONE, (
                f"city street style={mat.get('style')} "
                f"(expected Flagstone={_STONE_FLAGSTONE})"
            )

    def test_smaller_size_classes_produce_distinct_street_material(
        self,
    ) -> None:
        """Hamlet / village / town carry distinct
        (style, sub_pattern) tuples on their paved.* PaintOps.
        City currently shares Flagstone with town on the routed
        streets — the visual distinction at the city tier comes
        from the separate ``pavement.*`` Ashlar Staggered open
        plaza (see ``test_city_pavement_material.py``) plus the
        stone fortification."""
        seen: dict[tuple[int, int], str] = {}
        for size_class in ("hamlet", "village", "town"):
            d = _ir_dict_for_settlement(size_class, 7)
            ops = _paved_paint_ops(d)
            assert ops
            mat = ops[0].get("material") or {}
            key = (
                int(mat.get("style") or 0),
                int(mat.get("subPattern") or 0),
            )
            assert key not in seen, (
                f"{size_class} reuses (style, sub) {key} from "
                f"{seen[key]} — distinct materials per size required"
            )
            seen[key] = size_class
