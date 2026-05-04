"""Integration test for the ``nhc_render.ir_to_svg`` PyO3 export.

Phase 2.17 of the Painter-trait migration exposes the Rust SVG
entry point at ``crate::transform::svg::floor_ir_to_svg`` to
Python through PyO3, mirroring the existing
``nhc_render.ir_to_png(buf, scale=1.0, layer=None) -> bytes``
shape.

The legacy Python ``nhc.rendering.ir_to_svg`` consumers keep
their imports until 2.18 / 2.19 — this test only validates the
new FFI surface shape:

1. The export exists.
2. It accepts ``(buf, scale=1.0, layer=None)``.
3. Output is a structurally valid SVG document (``<?xml`` /
   ``<svg`` prefix, ``</svg>`` suffix).
4. The Rust SVG can round-trip through ``svg_to_png`` without
   errors (sanity gate that the document is syntactically valid).

Cross-rasteriser PSNR parity vs ``ir_to_png`` is intentionally
NOT asserted here: the SvgPainter port is still partial during
Phase 2.x, so byte-equal parity is gated by the layer-by-layer
parity tests in ``test_ir_to_svg_*.py`` instead. The full
parity gate lives at ``test_ir_png_parity.py`` and pivots to the
Rust ``ir_to_svg`` once Phase 2.18 retires the Python emitter.
"""

from __future__ import annotations

from pathlib import Path

import pytest


nhc_render = pytest.importorskip(
    "nhc_render",
    reason=(
        "nhc_render extension not installed — run `make rust-build` "
        "or `pip install -e crates/nhc-render` first"
    ),
)


_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "floor_ir"
    / "seed42_rect_dungeon_dungeon"
    / "floor.nir"
)


def test_ir_to_svg_export_exists() -> None:
    """The PyO3 module exposes ``ir_to_svg``."""
    assert hasattr(nhc_render, "ir_to_svg"), (
        "nhc_render.ir_to_svg missing — run `make rust-build` "
        "after Phase 2.17 lands the FFI shim"
    )


def test_ir_to_svg_returns_structurally_valid_svg() -> None:
    """``ir_to_svg(buf)`` returns a complete SVG document string."""
    buf = _FIXTURE.read_bytes()
    svg = nhc_render.ir_to_svg(buf)
    assert isinstance(svg, str)
    assert svg.startswith("<?xml") or svg.startswith("<svg"), (
        f"unexpected SVG prefix: {svg[:80]!r}"
    )
    assert svg.rstrip().endswith("</svg>"), (
        f"unexpected SVG suffix: {svg[-80:]!r}"
    )


def test_ir_to_svg_accepts_scale_and_layer_kwargs() -> None:
    """Mirror of ``ir_to_png``: ``(buf, scale=1.0, layer=None)``."""
    buf = _FIXTURE.read_bytes()
    # Positional and keyword argument shapes both work.
    svg_default = nhc_render.ir_to_svg(buf)
    svg_kwargs = nhc_render.ir_to_svg(buf, scale=1.0, layer=None)
    assert svg_default == svg_kwargs


def test_ir_to_svg_round_trips_through_svg_to_png() -> None:
    """Output is syntactically valid: ``svg_to_png`` accepts it.

    A rasteriser-level sanity gate. Doesn't assert PSNR against
    the tiny-skia reference (the SvgPainter port is partial; full
    parity is tracked in the layer-by-layer parity suites and
    closes in Phase 2.18 when ``test_ir_png_parity.py`` pivots to
    the Rust ``ir_to_svg``).
    """
    buf = _FIXTURE.read_bytes()
    svg = nhc_render.ir_to_svg(buf)
    png_bytes = bytes(nhc_render.svg_to_png(svg))
    # PNG signature: 8-byte magic header.
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", (
        "svg_to_png(ir_to_svg(buf)) did not produce a PNG"
    )
