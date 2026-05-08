"""City courtyard renders as Ashlar Staggered, streets as Brick.

Cities pave their entire fortified courtyard but split the
surface into two visually distinct regions:

- Routed streets (``SurfaceType.STREET``) → ``paved.*`` region →
  Stone Brick / FlemishBond (via the size-class
  ``street_material`` override).
- Open courtyard / plaza (``SurfaceType.PAVEMENT``) →
  ``pavement.*`` region → Stone Ashlar / StaggeredJoint (the
  city ``pavement_material`` default).

The split lets the routed network read as the dominant urban
fabric while the open spaces between cluster groups carry a
crisp dressed-stone treatment befitting a fortified city.
"""

from __future__ import annotations

import json
import random

from nhc.rendering.ir.dump import dump
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.sites.town import assemble_town


_STONE = "Stone"
_STONE_FLAGSTONE = 2
_STONE_ASHLAR = 8
_STONE_ASHLAR_STAGGERED = 1


def _ir_dict(size_class: str, seed: int) -> dict:
    site = assemble_town(
        f"settlement_{size_class}_seed{seed}",
        random.Random(seed),
        size_class=size_class,
    )
    buf = build_floor_ir(site.surface, seed=seed, site=site)
    return json.loads(dump(bytes(buf)))


def _paint_ops_with_prefix(d: dict, prefix: str) -> list[dict]:
    out: list[dict] = []
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "PaintOp":
            continue
        op = entry.get("op") or {}
        rr = op.get("regionRef") or ""
        if rr.startswith(f"{prefix}."):
            out.append(op)
    return out


def _region_ids_with_prefix(d: dict, prefix: str) -> list[str]:
    return [
        r["id"] for r in (d.get("regions") or [])
        if r.get("id", "").startswith(f"{prefix}.")
    ]


class TestCityPavementMaterial:
    def test_city_emits_pavement_region(self) -> None:
        d = _ir_dict("city", 7)
        assert _region_ids_with_prefix(d, "pavement"), (
            "city seed7: expected at least one pavement.* region "
            "(the open courtyard / plaza area outside routed streets)"
        )

    def test_city_pavement_renders_as_ashlar_staggered(self) -> None:
        d = _ir_dict("city", 7)
        ops = _paint_ops_with_prefix(d, "pavement")
        assert ops, "city seed7: expected at least one pavement.* PaintOp"
        for op in ops:
            mat = op.get("material") or {}
            assert mat.get("family") == _STONE
            assert mat.get("style") == _STONE_ASHLAR, (
                f"city pavement style={mat.get('style')} "
                f"(expected Ashlar={_STONE_ASHLAR})"
            )
            assert mat.get("subPattern") == _STONE_ASHLAR_STAGGERED, (
                f"city pavement sub_pattern={mat.get('subPattern')} "
                f"(expected StaggeredJoint={_STONE_ASHLAR_STAGGERED})"
            )

    def test_city_streets_remain_flagstone(self) -> None:
        """The pavement split must not steal from the street
        material. Routed streets keep Flagstone (paired with the
        Ashlar Staggered pavement for a uniformly dressed-stone
        urban look)."""
        d = _ir_dict("city", 7)
        ops = _paint_ops_with_prefix(d, "paved")
        assert ops, "city seed7: expected at least one paved.* PaintOp"
        for op in ops:
            mat = op.get("material") or {}
            assert mat.get("family") == _STONE
            assert mat.get("style") == _STONE_FLAGSTONE


class TestNonCityHasNoPavement:
    """Only the city tier emits pavement.* regions. Hamlet /
    village / town keep their existing street + grass / garden
    layout — the pavement split is a city-specific feature."""

    def test_no_pavement_region_on_smaller_settlements(self) -> None:
        for size_class in ("hamlet", "village", "town"):
            d = _ir_dict(size_class, 7)
            assert _region_ids_with_prefix(d, "pavement") == [], (
                f"{size_class}_seed7: unexpected pavement.* regions; "
                f"only the city tier should ship the Ashlar plaza"
            )
