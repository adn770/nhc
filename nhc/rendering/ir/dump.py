"""Canonicalised JSON dump of a FloorIR FlatBuffer.

For human inspection (debug + admin tooling) and git-reviewable
test fixtures. Output is deterministic — fields appear in schema
declaration order, enum int values are translated to their member
names, and union variants surface as their concrete table type so
diffs read cleanly.

Usage:
    >>> from nhc.rendering.ir.dump import dump
    >>> json_text = dump(open("floor.nir", "rb").read())

CLI:
    python -m nhc.rendering.ir.dump path/to/floor.nir
"""

from __future__ import annotations

import json
import sys
from typing import Any

from nhc.rendering.ir._fb import (
    CobblePattern,
    CornerStyle,
    FloorKind,
    FountainShape,
    HatchKind,
    Op,
    RegionKind,
    ShadowKind,
    StairDirection,
    TerrainKind,
    V5FixtureKind,
    V5MaterialFamily,
    V5Op,
    V5PathStyle,
    V5RoofStyle,
    V5WallTreatment,
    WellShape,
)
from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT


def _enum_value_to_name(enum_cls: type) -> dict[int, str]:
    """Build {int_value: member_name} from a flatc enum class."""
    return {
        v: k
        for k, v in vars(enum_cls).items()
        if not k.startswith("_") and isinstance(v, int)
    }


# (table_class_name, attribute_name) → reverse-map(int → name).
# Enum-typed scalar fields land here so the dumper can render their
# member name instead of a bare int. Fields not in this map pass
# through as raw scalars.
_ENUM_FIELDS: dict[tuple[str, str], dict[int, str]] = {
    ("FloorIRT", "floorKind"): _enum_value_to_name(FloorKind.FloorKind),
    ("RegionT", "kind"): _enum_value_to_name(RegionKind.RegionKind),
    ("ShadowOpT", "kind"): _enum_value_to_name(ShadowKind.ShadowKind),
    ("HatchOpT", "kind"): _enum_value_to_name(HatchKind.HatchKind),
    ("CobblestoneVariantT", "pattern"): _enum_value_to_name(
        CobblePattern.CobblePattern
    ),
    ("WellFeatureOpT", "shape"): _enum_value_to_name(WellShape.WellShape),
    ("FountainFeatureOpT", "shape"): _enum_value_to_name(
        FountainShape.FountainShape
    ),
    ("StairTileT", "direction"): _enum_value_to_name(
        StairDirection.StairDirection
    ),
    ("TerrainTintTileT", "kind"): _enum_value_to_name(TerrainKind.TerrainKind),
    ("TerrainDetailTileT", "kind"): _enum_value_to_name(
        TerrainKind.TerrainKind
    ),
    ("OpEntryT", "opType"): _enum_value_to_name(Op.Op),
    # v5 enum-typed fields — Phase 1.1 schema scaffold lifted them
    # into the IR, Phase 4.1 lifts them into the canonical dump
    # representation so consumers (ir_query, structural diffs)
    # can read v5 op kinds as strings.
    ("V5OpEntryT", "opType"): _enum_value_to_name(V5Op.V5Op),
    ("V5MaterialT", "family"): _enum_value_to_name(
        V5MaterialFamily.V5MaterialFamily
    ),
    ("V5WallMaterialT", "family"): _enum_value_to_name(
        V5MaterialFamily.V5MaterialFamily
    ),
    ("V5WallMaterialT", "treatment"): _enum_value_to_name(
        V5WallTreatment.V5WallTreatment
    ),
    ("V5WallMaterialT", "cornerStyle"): _enum_value_to_name(
        CornerStyle.CornerStyle
    ),
    ("V5FixtureOpT", "kind"): _enum_value_to_name(
        V5FixtureKind.V5FixtureKind
    ),
    ("V5PathOpT", "style"): _enum_value_to_name(V5PathStyle.V5PathStyle),
    ("V5RoofOpT", "style"): _enum_value_to_name(V5RoofStyle.V5RoofStyle),
    ("V5HatchOpT", "kind"): _enum_value_to_name(HatchKind.HatchKind),
}


def _to_jsonable(
    value: Any,
    *,
    parent_cls: str | None = None,
    attr_name: str | None = None,
) -> Any:
    """Recursively turn an Object-API node into a JSON-friendly value."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if parent_cls and attr_name:
            mapping = _ENUM_FIELDS.get((parent_cls, attr_name))
            if mapping is not None:
                return mapping.get(value, value)
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [
            _to_jsonable(v, parent_cls=parent_cls, attr_name=attr_name)
            for v in value
        ]
    # Object-API table / struct: walk attrs in declaration order
    # (Python preserves insertion order in __dict__ since 3.7).
    if hasattr(value, "__dict__"):
        cls_name = type(value).__name__
        out: dict[str, Any] = {"__type": cls_name}
        for k, v in vars(value).items():
            out[k] = _to_jsonable(v, parent_cls=cls_name, attr_name=k)
        return out
    return repr(value)


def dump(buf: bytes) -> str:
    """Return canonicalised JSON for a FloorIR FlatBuffer.

    Raises ``ValueError`` if the buffer does not carry the
    ``NIR3`` file_identifier handshake — a quick guard against
    feeding the dumper a binary blob that was not produced by
    ``build_floor_ir`` (or by some past schema major).
    """
    if not FloorIR.FloorIRBufferHasIdentifier(buf, 0):
        raise ValueError(
            "Buffer does not carry the NIR3 file_identifier — is "
            "this a Floor IR buffer at the current schema major?"
        )
    root = FloorIR.GetRootAs(buf, 0)
    obj = FloorIRT.InitFromObj(root)
    return json.dumps(_to_jsonable(obj), indent=2, ensure_ascii=False)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python -m nhc.rendering.ir.dump <floor.nir>",
            file=sys.stderr,
        )
        return 2
    with open(argv[1], "rb") as fh:
        buf = fh.read()
    print(dump(buf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
