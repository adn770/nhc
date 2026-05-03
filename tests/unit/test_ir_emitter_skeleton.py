"""Skeleton sentinel for the IR emitter.

Pins the contract of the foundation commit: ``build_floor_ir`` exists,
returns a non-empty FlatBuffer carrying the ``NIR4`` identifier
(post-1.27 schema cut), the metadata fields (major / minor /
dimensions / theme / seed / flags) match the input level, ``regions[]``
is populated by the ``emit_regions`` stage, and ``dump.dump``
round-trips the buffer cleanly.

This sentinel also pins the schema-cut invariants from Phase 1.27 of
``plans/nhc_pure_ir_plan.md``: the op union no longer carries the
retired v3 variants, and the deprecated v4-prep fields
(``Region.polygon`` / ``FloorOp.outline`` / ``ExteriorWallOp.outline``
/ ``Outline.cuts`` / per-tile ``clip_region``) no longer appear on
the generated bindings.
"""

from __future__ import annotations

import pytest

from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir.dump import dump

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.fixture(scope="module", params=all_descriptors())
def emitted(request):
    """Build each starter-fixture level once per module."""
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(request.param)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    return inputs, buf, fir


def test_file_identifier_is_nir4(emitted) -> None:
    """Phase 1.27 — atomic NIR3 → NIR4 cut.

    ``FloorIRBufferHasIdentifier`` checks the buffer's
    ``file_identifier`` slot (offset 4..8) against the value compiled
    into the generated bindings. After the schema cut at 1.27 both
    sides advance to ``NIR4`` together, so the handshake stays valid
    for fresh IR.
    """
    _, buf, _ = emitted
    assert buf, "build_floor_ir returned an empty buffer"
    assert FloorIR.FloorIRBufferHasIdentifier(buf, 0), (
        "emitted buffer is missing the NIR4 file_identifier — "
        "builder.Finish was not called with b'NIR4'"
    )
    assert bytes(buf[4:8]) == b"NIR4", (
        f"expected file_identifier b'NIR4', got {bytes(buf[4:8])!r}; "
        "Phase 1.27 atomic schema cut bumps NIR3 → NIR4."
    )


def test_schema_major_is_4(emitted) -> None:
    """Phase 1.27 atomic cut — major bumps to 4, minor resets to 0."""
    _, _, fir = emitted
    assert fir.major == 4, (
        f"expected SCHEMA_MAJOR == 4 after the 1.27 atomic cut, "
        f"got {fir.major}"
    )
    assert fir.minor == 0, (
        f"expected SCHEMA_MINOR == 0 after the 1.27 atomic cut "
        f"(reset on major bump), got {fir.minor}"
    )


def test_no_legacy_ops_in_op_union() -> None:
    """Phase 1.27 — retired v3 op-union variants are gone.

    Introspects the generated ``Op`` enum and asserts the five legacy
    op-union variants no longer appear. The schema cut deletes their
    table declarations + union slots together; the regenerated Python
    bindings drop the matching attributes.
    """
    from nhc.rendering.ir._fb import Op

    for retired in (
        "WallsAndFloorsOp",
        "BuildingExteriorWallOp",
        "BuildingInteriorWallOp",
        "EnclosureOp",
        "GenericProceduralOp",
    ):
        assert not hasattr(Op.Op, retired), (
            f"Op.Op still carries the retired variant {retired!r}; "
            "Phase 1.27 atomic cut must drop it from the FB schema."
        )


def test_no_deprecated_outlines_in_schema() -> None:
    """Phase 1.27 — deprecated v4-prep fields are gone.

    Introspects the generated ``Region`` / ``FloorOp`` /
    ``ExteriorWallOp`` / ``Outline`` / per-tile op classes and asserts
    the deprecated v4-prep fields no longer appear. Each
    ``Region.polygon`` / ``FloorOp.outline`` /
    ``ExteriorWallOp.outline`` / ``Outline.cuts`` /
    per-tile ``clip_region`` was retired at 1.27 — consumers read
    through ``Region.outline`` and op-level ``cuts``/``region_ref``
    only after the cut.
    """
    from nhc.rendering.ir._fb import (
        DecoratorOp,
        ExteriorWallOp,
        FloorDetailOp,
        FloorGridOp,
        FloorOp,
        Outline,
        Region,
        TerrainDetailOp,
        TerrainTintOp,
        ThematicDetailOp,
    )

    region_methods = dir(Region.Region)
    assert "Polygon" not in region_methods, (
        "Region still exposes a Polygon() reader — "
        "Phase 1.27 must drop Region.polygon."
    )

    floor_op_methods = dir(FloorOp.FloorOp)
    assert "Outline" not in floor_op_methods, (
        "FloorOp still exposes an Outline() reader — "
        "Phase 1.27 must drop FloorOp.outline (use region_ref only)."
    )

    ext_methods = dir(ExteriorWallOp.ExteriorWallOp)
    assert "Outline" not in ext_methods, (
        "ExteriorWallOp still exposes an Outline() reader — "
        "Phase 1.27 must drop ExteriorWallOp.outline (use region_ref)."
    )

    outline_methods = dir(Outline.Outline)
    assert "Cuts" not in outline_methods, (
        "Outline still exposes a Cuts() reader — Phase 1.27 must drop "
        "Outline.cuts (op-level cuts is canonical post-1.24)."
    )

    for op_module, op_name in (
        (TerrainTintOp, "TerrainTintOp"),
        (FloorGridOp, "FloorGridOp"),
        (FloorDetailOp, "FloorDetailOp"),
        (ThematicDetailOp, "ThematicDetailOp"),
        (TerrainDetailOp, "TerrainDetailOp"),
        (DecoratorOp, "DecoratorOp"),
    ):
        cls = getattr(op_module, op_name)
        assert "ClipRegion" not in dir(cls), (
            f"{op_name} still exposes a ClipRegion() reader — "
            "Phase 1.27 must drop clip_region from per-tile ops."
        )

    fd_methods = dir(FloorDetailOp.FloorDetailOp)
    for retired in ("RoomGroups", "CorridorGroups", "WoodFloorGroups"):
        assert retired not in fd_methods, (
            f"FloorDetailOp still exposes {retired}() — "
            "Phase 1.27 must drop the legacy passthrough fields."
        )


def test_metadata_matches_inputs(emitted) -> None:
    inputs, _, fir = emitted
    assert fir.widthTiles == inputs.level.width
    assert fir.heightTiles == inputs.level.height
    # FlatBuffers Object-API surfaces string fields as bytes; decode
    # at the boundary. ir_to_svg / dump.py do the same.
    assert fir.theme.decode() == inputs.theme
    assert fir.baseSeed == inputs.seed


def test_flags_match_render_context(emitted) -> None:
    _, _, fir = emitted
    assert fir.flags is not None
    # vegetation defaults to True on the starter fixtures; the other
    # flag values vary by floor_kind so just assert the surface is
    # populated rather than locking exact values that 1.b–1.j tests
    # will check via per-layer parity.
    assert fir.flags.vegetationEnabled is True


def test_regions_populated_by_emit_regions(emitted) -> None:
    _, _, fir = emitted
    assert fir.regions, (
        "emit_regions wrote no regions — at least the dungeon polygon "
        "should always register"
    )
    for region in fir.regions:
        assert region.id, "region has empty id"
        assert region.outline is not None, (
            f"region {region.id!r} has no outline"
        )
        # Polygon outlines carry vertices + rings; Circle / Pill
        # descriptors carry parametric values (cx / cy / rx / ry)
        # instead. Just assert the outline carries SOMETHING — per-kind
        # invariants live in test_ir_emit_regions_outline.py.
        has_geometry = (
            region.outline.vertices
            or region.outline.descriptorKind != 0
        )
        assert has_geometry, (
            f"region {region.id!r} outline is empty — "
            "neither vertices nor a parametric descriptor populated."
        )


def test_dump_round_trip(emitted) -> None:
    _, buf, _ = emitted
    text = dump(buf)
    assert text, "dump returned empty text"
    assert "FloorIRT" in text, (
        "dump output is missing the FloorIRT root marker"
    )
