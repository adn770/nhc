"""Tests for ``nhc.rendering.ir.dump``.

The dumper is the only debugging surface that surfaces an IR
buffer to humans (debug tooling, fixture diffs, /admin views), so
it gets to be picky about output stability:

- Field order matches schema declaration order.
- Enum int values are translated to their member name strings.
- Union variants surface as their concrete table type.
- The ``NIR3`` file_identifier is required; non-IR buffers raise
  ``ValueError`` early instead of leaking arbitrary bytes.

These tests pin the public contract; if the schema or generator
changes, this is where to update — or, more often, where to start
debugging when the dumper goes red.
"""

from __future__ import annotations

import json

import flatbuffers
import pytest

from nhc.rendering.ir._fb import FloorIR as FloorIRMod
from nhc.rendering.ir._fb import HatchKind as HatchKindMod
from nhc.rendering.ir._fb import HatchOp as HatchOpMod
from nhc.rendering.ir._fb import Op as OpMod
from nhc.rendering.ir._fb import OpEntry as OpEntryMod
from nhc.rendering.ir.dump import dump


def _build_minimal(file_identifier: bytes = b"NIR4") -> bytes:
    b = flatbuffers.Builder(64)
    theme = b.CreateString("dungeon")
    FloorIRMod.Start(b)
    FloorIRMod.AddMajor(b, 1)
    FloorIRMod.AddMinor(b, 0)
    FloorIRMod.AddWidthTiles(b, 80)
    FloorIRMod.AddHeightTiles(b, 50)
    FloorIRMod.AddTheme(b, theme)
    FloorIRMod.AddBaseSeed(b, 12345)
    root = FloorIRMod.End(b)
    b.Finish(root, file_identifier=file_identifier)
    return bytes(b.Output())


def _build_with_hatch_hole_op() -> bytes:
    b = flatbuffers.Builder(256)
    underlay = b.CreateString("#1f1612")
    HatchOpMod.Start(b)
    HatchOpMod.AddKind(b, HatchKindMod.HatchKind.Hole)
    HatchOpMod.AddSeed(b, 777)
    HatchOpMod.AddExtentTiles(b, 2.0)
    HatchOpMod.AddStride(b, 0.5)
    HatchOpMod.AddHatchUnderlayColor(b, underlay)
    hatch_off = HatchOpMod.End(b)

    OpEntryMod.Start(b)
    OpEntryMod.AddOpType(b, OpMod.Op.HatchOp)
    OpEntryMod.AddOp(b, hatch_off)
    oe_off = OpEntryMod.End(b)

    FloorIRMod.StartOpsVector(b, 1)
    b.PrependUOffsetTRelative(oe_off)
    ops_vec = b.EndVector()

    theme = b.CreateString("dungeon")
    FloorIRMod.Start(b)
    FloorIRMod.AddMajor(b, 1)
    FloorIRMod.AddTheme(b, theme)
    FloorIRMod.AddOps(b, ops_vec)
    root = FloorIRMod.End(b)
    b.Finish(root, file_identifier=b"NIR4")
    return bytes(b.Output())


def test_minimal_buffer_dump_field_order() -> None:
    out = json.loads(dump(_build_minimal()))
    assert list(out.keys()) == [
        "__type",
        "major",
        "minor",
        "widthTiles",
        "heightTiles",
        "cell",
        "padding",
        "floorKind",
        "theme",
        "baseSeed",
        "flags",
        "regions",
        "ops",
    ]
    assert out["__type"] == "FloorIRT"
    assert out["major"] == 1
    assert out["theme"] == "dungeon"


def test_enum_translation_floor_kind() -> None:
    out = json.loads(dump(_build_minimal()))
    # Default FloorKind.Dungeon == 0; dump should render the name.
    assert out["floorKind"] == "Dungeon"


def test_union_variant_dispatch_and_nested_enum() -> None:
    out = json.loads(dump(_build_with_hatch_hole_op()))
    assert len(out["ops"]) == 1
    op_entry = out["ops"][0]
    # Discriminator translated to op-name string.
    assert op_entry["opType"] == "HatchOp"
    # Concrete union variant carries the right table type tag.
    assert op_entry["op"]["__type"] == "HatchOpT"
    # Nested HatchKind enum translates to its member name.
    assert op_entry["op"]["kind"] == "Hole"
    assert op_entry["op"]["seed"] == 777


def test_rejects_non_nir_buffer() -> None:
    bad = _build_minimal(file_identifier=b"XXXX")
    with pytest.raises(ValueError, match="NIR3"):
        dump(bad)
