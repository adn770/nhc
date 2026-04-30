"""Parity gate: ``ir_to_svg(ir)`` matches the legacy SVG byte-for-byte.

For each fixture under ``tests/fixtures/floor_ir/<descriptor>/``,
loading the committed ``floor.nir`` and running it through the IR
→ SVG transformer must produce a string byte-equal to
``floor.svg``. This is the contract that protects every Phase
1–7 transition: the ``render_floor_svg`` output is fixed, the IR
pipeline must reproduce it. Phase 1.k rewired ``render_floor_svg``
to drive through the IR — both sides of the parity check now flow
through the same code path, so any drift in handler-side
formatting or layer ordering breaks this gate.

Phase 5 introduces a parallel ``test_ir_png_parity.py`` (tiny-skia
output vs resvg of the SVG). Phase 6 introduces
``test_ir_canvas_parity.py`` (WASM Canvas vs PNG). The three
together cover the full transformer triangle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.floor_ir._inputs import all_descriptors


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "floor_ir"
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_ir_to_svg_byte_equal_legacy(descriptor: str) -> None:
    from nhc.rendering.ir_to_svg import ir_to_svg

    fixture = _FIXTURE_ROOT / descriptor
    nir = (fixture / "floor.nir").read_bytes()
    expected_svg = (fixture / "floor.svg").read_text()
    assert nir, (
        f"fixture .nir is empty — re-run "
        f"`python -m tests.samples.regenerate_fixtures`"
    )

    actual_svg = ir_to_svg(nir)

    assert actual_svg == expected_svg, (
        f"{descriptor}: IR→SVG diverges from legacy render_floor_svg"
    )


# ── Phase 2.5: bare-mode SVG (decoration ops elided) ────────


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_ir_to_svg_bare_skips_decoration_layers(descriptor: str) -> None:
    """Bare mode skips the three decoration layers entirely.

    Mirrors the inactive-flag policy for shadows / hatching: when a
    layer is gated off, ``ir_to_svg`` emits no per-layer comment
    and no ops for it. Bare mode pins the same shape for
    floor_detail / terrain_detail / surface_features so the output
    is the structural skeleton ``/admin`` debug visualisation
    expects, not a full render with the decorators silently mangled.
    """
    from nhc.rendering.ir_to_svg import ir_to_svg

    nir = (_FIXTURE_ROOT / descriptor / "floor.nir").read_bytes()
    bare = ir_to_svg(nir, bare=True)
    for layer in (
        "floor_detail", "terrain_detail", "surface_features",
    ):
        assert f"<!-- layer.{layer}:" not in bare, (
            f"{descriptor}: bare SVG must not include "
            f"layer.{layer} comment"
        )
    # The structural layers all stay (cave fixtures still go
    # through structural / floor_grid / stairs even if a given
    # layer ends up empty).
    for layer in (
        "structural", "floor_grid", "stairs",
    ):
        assert f"<!-- layer.{layer}:" in bare, (
            f"{descriptor}: bare SVG must keep layer.{layer} "
            f"comment"
        )


def test_ir_to_svg_bare_default_off_matches_full_render() -> None:
    """``bare=False`` is the default and must reproduce the legacy
    output. Pins the bare flag as additive — no behaviour change
    for callers that don't opt in."""
    from nhc.rendering.ir_to_svg import ir_to_svg
    descriptor = next(iter(all_descriptors()))
    nir = (_FIXTURE_ROOT / descriptor / "floor.nir").read_bytes()
    assert ir_to_svg(nir) == ir_to_svg(nir, bare=False)


# ── Phase 0.1: FloorDetailOp.{room,corridor}_groups reads dropped ──


def test_floor_detail_ignores_legacy_group_strings() -> None:
    """3.1: room_groups / corridor_groups consumer reads dropped.

    Build a FloorIR (from the seed42 fixture) where one
    FloorDetailOp's roomGroups / corridorGroups carry sentinel
    strings, repack, then assert the rendered SVG does NOT contain
    those sentinels.

    Regression for the dead-code cleanup at Phase 0.1 of
    plans/nhc_pure_ir_plan.md: the schema fields stay declared
    until the 4.0 cut, but the Python and Rust consumers must
    no longer concatenate them into the rendered output.
    """
    import flatbuffers

    from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
    from nhc.rendering.ir._fb import Op as OpModule
    from nhc.rendering.ir_to_svg import ir_to_svg

    fixture = _FIXTURE_ROOT / "seed42_rect_dungeon_dungeon"
    nir = (fixture / "floor.nir").read_bytes()
    fir_t = FloorIRT.InitFromObj(FloorIR.GetRootAs(nir, 0))

    sentinel_room = "<g id=\"sentinel-room-poison\"/>"
    sentinel_corridor = "<g id=\"sentinel-corridor-poison\"/>"

    poisoned = False
    for entry in fir_t.ops or []:
        if entry.opType == OpModule.Op.FloorDetailOp:
            entry.op.roomGroups = [sentinel_room]
            entry.op.corridorGroups = [sentinel_corridor]
            poisoned = True
            break
    assert poisoned, (
        "fixture seed42_rect_dungeon_dungeon has no FloorDetailOp; "
        "test setup is stale"
    )

    builder = flatbuffers.Builder(1024)
    builder.Finish(fir_t.Pack(builder), b"NIR3")
    poisoned_nir = bytes(builder.Output())

    svg = ir_to_svg(poisoned_nir)
    assert sentinel_room not in svg, (
        "ir_to_svg leaked FloorDetailOp.roomGroups into the output; "
        "the consumer must not read this field at 3.1+"
    )
    assert sentinel_corridor not in svg, (
        "ir_to_svg leaked FloorDetailOp.corridorGroups into the "
        "output; the consumer must not read this field at 3.1+"
    )
