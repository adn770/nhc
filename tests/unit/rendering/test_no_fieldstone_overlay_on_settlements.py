"""Settlement countryside renders as plain grass, not fieldstone.

The 611af983 commit hooked ``_is_field_overlay_tile`` (any
``Terrain.GRASS`` + ``SurfaceType.FIELD`` tile) into the v5
predicate-based stone-decorator emit pipeline, generating one
``fieldstone.<i>`` Region + PaintOp per disjoint cluster of FIELD
tiles. The v5 ``paint_field_stone`` painter renders 100% coverage
(``pal.shadow`` substrate fill at ``#4A5A3A`` plus 16 px-cell
greenish polygon stones), so every settlement countryside got
buried under a dark moss-like tessellation that read as "thick
foliage" before any tree / bush stamp landed.

The v4 reference rendered FIELD tiles as plain grass with a
sparse 10% scattered-ellipse decorator on top — the heavy substrate
treatment is a v5 emit drift, not the original design intent.

These tests pin the corrected behaviour: settlement IRs (towns,
hamlets, villages, cities) emit no ``fieldstone.*`` regions and
no Stone/4 PaintOps. Buildings + courtyard fills (paved, brick,
flagstone, opus_romano) are unaffected.
"""

from __future__ import annotations

import json
import random

from nhc.rendering.ir.dump import dump
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.sites.town import assemble_town


# Stone family / FieldStone style indices in the v5 material registry.
# Mirrors ``STONE_FIELDSTONE = 4`` in ``nhc/rendering/emit/materials.py``.
_STONE_FAMILY = "Stone"
_STONE_STYLE_FIELDSTONE = 4


def _ir_dict_for_settlement(size_class: str, seed: int) -> dict:
    site = assemble_town(
        f"settlement_{size_class}_seed{seed}",
        random.Random(seed),
        size_class=size_class,
    )
    buf = build_floor_ir(site.surface, seed=seed, site=site)
    return json.loads(dump(bytes(buf)))


def _region_ids_with_prefix(d: dict, prefix: str) -> list[str]:
    return [
        r["id"] for r in (d.get("regions") or [])
        if r.get("id", "").startswith(f"{prefix}.")
    ]


def _stone_paint_ops_with_style(d: dict, style: int) -> list[dict]:
    out: list[dict] = []
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "PaintOp":
            continue
        op = entry.get("op") or {}
        mat = op.get("material") or {}
        if mat.get("family") == _STONE_FAMILY and mat.get("style") == style:
            out.append(op)
    return out


class TestNoFieldstoneOnSettlements:
    """Settlement countryside (FIELD tiles) renders as Earth Grass,
    not Stone FieldStone. Pin the absence of fieldstone regions +
    PaintOps so the moss-overlay regression can't sneak back in."""

    def test_town_seed7_emits_no_fieldstone_region(self) -> None:
        d = _ir_dict_for_settlement("town", 7)
        assert _region_ids_with_prefix(d, "fieldstone") == [], (
            "town_seed7: expected no fieldstone.* regions; "
            "the FIELD tile predicate over-selects the entire "
            "countryside and the v5 painter renders 100% coverage"
        )

    def test_town_seed7_emits_no_stone_fieldstone_paint_op(self) -> None:
        d = _ir_dict_for_settlement("town", 7)
        ops = _stone_paint_ops_with_style(d, _STONE_STYLE_FIELDSTONE)
        assert ops == [], (
            f"town_seed7: expected zero Stone/FieldStone PaintOps; "
            f"got {len(ops)} (region_refs="
            f"{[op.get('regionRef') for op in ops]})"
        )

    def test_no_settlement_size_emits_fieldstone(self) -> None:
        for size_class in ("hamlet", "village", "town", "city"):
            d = _ir_dict_for_settlement(size_class, 7)
            assert _region_ids_with_prefix(d, "fieldstone") == [], (
                f"{size_class}_seed7: unexpected fieldstone.* regions"
            )
            ops = _stone_paint_ops_with_style(d, _STONE_STYLE_FIELDSTONE)
            assert ops == [], (
                f"{size_class}_seed7: unexpected Stone/FieldStone PaintOps"
            )


class TestPavedAndCourtyardEmitsUnaffected:
    """The fix only drops fieldstone — paved (Stone style 0) and the
    other courtyard surface emitters keep emitting normally."""

    def test_town_seed7_still_emits_paved_region(self) -> None:
        d = _ir_dict_for_settlement("town", 7)
        paved = _region_ids_with_prefix(d, "paved")
        assert paved, (
            "town_seed7: expected at least one paved.* region "
            "(road / street network); the fieldstone fix must not "
            "regress paved emit"
        )
