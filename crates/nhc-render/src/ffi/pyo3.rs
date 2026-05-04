//! PyO3 binding stub.
//!
//! Exposes the Rust crate as a Python extension module named
//! `nhc_render`. Phase 2.19 retired the seventeen legacy
//! `draw_*` SVG-string emitters that the now-deleted Python
//! `nhc/rendering/ir_to_svg.py` dispatched against; the surface
//! shrank to:
//!
//! - `splitmix64_next` / `perlin2` — cross-language RNG / noise
//!   helpers used by the IR emitter (deterministic-stream gates).
//! - `ir_to_png` / `svg_to_png` / `ir_to_svg` — the three transform
//!   entry points the web layer drives (PNG via the Painter +
//!   tiny-skia path; SVG via the Painter + `SvgPainter` path;
//!   `svg_to_png` is the cross-rasteriser parity helper).
//!
//! Only compiled when the `pyo3` feature is on — disabled for
//! WASM builds and for `cargo test`-without-features.

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;

use crate::perlin;
use crate::rng::SplitMix64;
use crate::transform::png as transform_png;
use crate::transform::svg as transform_svg;

/// Pull the next splitmix64 output for a given seed.
///
/// One-call helper rather than a stateful Python class — the IR
/// emitter is the only consumer right now and it materialises a
/// fresh stream per primitive. A class wrapper can land later if
/// streaming becomes the bottleneck.
#[pyfunction]
fn splitmix64_next(seed: u64) -> u64 {
    SplitMix64::from_seed(seed).next_u64()
}

/// 2D Perlin noise — same call shape as `nhc.rendering._perlin.pnoise2`.
///
/// Byte-equal to the Python reference; the cross-language gate is
/// `tests/fixtures/perlin/pnoise2_vectors.json` (Phase 0.6).
#[pyfunction]
#[pyo3(signature = (x, y, base = 0))]
fn perlin2(x: f64, y: f64, base: i32) -> f64 {
    perlin::pnoise2(x, y, base)
}

/// IR → PNG raster — Phase 5.1.1 envelope.
///
/// Reads a `FloorIR` FlatBuffer and returns the rasterised PNG
/// bytes. `scale` multiplies the SVG-equivalent canvas size; the
/// `.png` web endpoint passes 1.0 to match the legacy `resvg-py`
/// rendering. `layer` (when not None) dispatches a single named
/// layer — the parity harness in `tests/unit/test_ir_png_parity.py`
/// uses this to gate per-primitive 5.2 / 5.3 / 5.4 commits one
/// layer at a time.
#[pyfunction]
#[pyo3(signature = (ir_bytes, scale = 1.0, layer = None))]
fn ir_to_png(
    ir_bytes: &[u8],
    scale: f32,
    layer: Option<&str>,
) -> PyResult<Vec<u8>> {
    transform_png::floor_ir_to_png(ir_bytes, scale, layer)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// SVG → PNG rasteriser — Phase 10.4 cross-rasteriser parity
/// gate. The parity harness in `tests/unit/test_ir_png_parity.py`
/// pipes `ir_to_svg(buf)` through this function and compares the
/// resulting pixels against the reference image, replacing the
/// legacy `resvg-py` Python wheel. Production code never calls
/// this — the `.png` endpoint flows straight through
/// `ir_to_png` from the IR buffer.
#[pyfunction]
fn svg_to_png(svg: &str) -> PyResult<Vec<u8>> {
    transform_svg::svg_to_png(svg)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// IR → SVG document — Phase 2.17 envelope.
///
/// Reads a `FloorIR` FlatBuffer and returns a complete SVG
/// document string. Mirrors `ir_to_png`'s argument shape:
/// `scale` multiplies the canvas dimensions (1.0 matches the
/// legacy emitter's natural canvas), `layer` (when not None)
/// dispatches a single named layer through the same
/// `transform::png::layer_ops` map the PNG entry point uses,
/// and `bare` (when True) elides the four decoration layers
/// (`floor_detail`, `thematic_detail`, `terrain_detail`,
/// `surface_features`) for the web `/admin?bare=1` debug route.
/// Wraps `crate::transform::svg::floor_ir_to_svg`; the Python
/// `nhc/rendering/ir_to_svg.py` legacy emitter retired in Phase
/// 2.19, so this is the only SVG entry point on the wire.
#[pyfunction]
#[pyo3(signature = (ir_bytes, scale = 1.0, layer = None, bare = false))]
fn ir_to_svg(
    ir_bytes: &[u8],
    scale: f32,
    layer: Option<&str>,
    bare: bool,
) -> PyResult<String> {
    transform_svg::floor_ir_to_svg(ir_bytes, scale, layer, bare)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// PyO3 module entry point. The function name MUST match the
/// `[lib] name` in Cargo.toml (`nhc_render`) so Python's
/// import machinery finds it.
#[pymodule]
fn nhc_render(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(splitmix64_next, m)?)?;
    m.add_function(wrap_pyfunction!(perlin2, m)?)?;
    m.add_function(wrap_pyfunction!(ir_to_png, m)?)?;
    m.add_function(wrap_pyfunction!(svg_to_png, m)?)?;
    m.add_function(wrap_pyfunction!(ir_to_svg, m)?)?;
    Ok(())
}
