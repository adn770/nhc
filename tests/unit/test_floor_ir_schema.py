"""Sentinel: floor_ir.fbs bindings import and round-trip cleanly.

The IR schema (``nhc/rendering/ir/floor_ir.fbs``) is the wire
format for the multi-runtime rendering architecture in
``design/map_ir.md``. This test confirms the FB bindings produced
by ``make ir-bindings`` are present and self-consistent, so that
later phases (emitter, ir-to-svg, ir-to-png, WASM) have a solid
foundation to build on.

If this test goes red:

- ``ModuleNotFoundError`` on the imports below means
  ``make ir-bindings`` was never run after a checkout, or the
  Python sub-package layout drifted from the .fbs namespace.
- A round-trip mismatch means the schema or generator changed in
  a way that breaks read/write compatibility — investigate before
  bumping the schema version.
"""

from __future__ import annotations

import flatbuffers


def test_bindings_importable() -> None:
    from nhc.rendering.ir._fb.FloorIR import FloorIR
    from nhc.rendering.ir._fb.HatchKind import HatchKind
    from nhc.rendering.ir._fb.CobblePattern import CobblePattern
    from nhc.rendering.ir._fb.OpEntry import OpEntry

    # Every kind enumerated in the design doc is reachable; this is
    # the cheapest possible "schema is wired" check.
    assert HatchKind.Room == 0
    assert HatchKind.Hole == 1
    assert HatchKind.Corridor == 2
    assert CobblePattern.Cobble == 0
    assert CobblePattern.Versailles4 == 5
    assert FloorIR is not None
    assert OpEntry is not None


def test_round_trip_minimal_buffer() -> None:
    """Build the smallest possible FloorIR buffer and read it back.

    Confirms the file_identifier handshake (``NIR3``) and that
    scalar setters / getters round-trip through the wire format.
    """
    from nhc.rendering.ir._fb import FloorIR as FloorIRMod

    builder = flatbuffers.Builder(64)
    theme_offset = builder.CreateString("dungeon")
    FloorIRMod.Start(builder)
    FloorIRMod.AddMajor(builder, 1)
    FloorIRMod.AddMinor(builder, 0)
    FloorIRMod.AddWidthTiles(builder, 80)
    FloorIRMod.AddHeightTiles(builder, 50)
    FloorIRMod.AddTheme(builder, theme_offset)
    FloorIRMod.AddBaseSeed(builder, 12345)
    root = FloorIRMod.End(builder)
    builder.Finish(root, file_identifier=b"NIR3")
    buf = bytes(builder.Output())

    assert FloorIRMod.FloorIR.FloorIRBufferHasIdentifier(buf, 0), (
        "file_identifier mismatch — NIR3 handshake broken"
    )

    ir = FloorIRMod.FloorIR.GetRootAs(buf, 0)
    assert ir.Major() == 1
    assert ir.Minor() == 0
    assert ir.WidthTiles() == 80
    assert ir.HeightTiles() == 50
    assert ir.Theme() == b"dungeon"
    assert ir.BaseSeed() == 12345
