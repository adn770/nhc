//! PyO3 binding stub.
//!
//! Exposes the Rust crate as a Python extension module named
//! `nhc_render`. Module surface grows primitive-by-primitive per
//! `plans/nhc_ir_migration_plan.md` Phase 3+. Today:
//! `splitmix64_next` (Phase 0.3 sentinel), `perlin2` (Phase 3
//! cross-language gate), `draw_floor_grid` (Phase 3 canary
//! primitive), and `draw_terrain_tints` (Phase 4.1 first
//! deterministic primitive).
//!
//! Only compiled when the `pyo3` feature is on — disabled for
//! WASM builds and for `cargo test`-without-features.

use std::collections::HashMap;

use pyo3::prelude::*;

use crate::perlin;
use crate::primitives;
use crate::rng::SplitMix64;

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

/// Floor-grid layer — Phase 3 canary primitive.
///
/// Returns `(room_d, corridor_d)`: the joined `d=` attribute
/// strings for the two `<path>` buckets. The Python handler at
/// `nhc/rendering/ir_to_svg.py:_draw_floor_grid_from_ir` wraps
/// these in `<path>` elements and adds the dungeon-interior clip
/// envelope when the IR's `clip_region` resolves.
///
/// `tiles` is a list of `(x, y, is_corridor)` triples in the IR's
/// y-major iteration order. The byte-equal parity gate lives at
/// `tests/unit/test_emit_floor_grid_parity.py` — drift on either
/// the Rust or Python side fails it before any SVG fixture
/// notices.
#[pyfunction]
fn draw_floor_grid(
    width_tiles: i32,
    height_tiles: i32,
    tiles: Vec<(i32, i32, bool)>,
    seed: u64,
) -> (String, String) {
    primitives::floor_grid::draw_floor_grid(
        width_tiles,
        height_tiles,
        &tiles,
        seed,
    )
}

/// Terrain-tints layer — Phase 4.1, first deterministic Phase 4
/// port.
///
/// Returns `(tint_rects, wash_rects)`: two lists of formatted
/// `<rect>` strings. The Python handler at
/// `ir_to_svg.py:_draw_terrain_tint_from_ir` stitches them into
/// the layer fragment, wrapping `tint_rects` in the dungeon-
/// interior clip envelope when the IR carries one.
///
/// The palette is resolved Python-side (the colour table at
/// `nhc/rendering/terrain_palette.py` is display data, not
/// procedural logic) and crossed via the four `(tint, opacity)`
/// pairs in the schema's enum order (`Water`, `Grass`, `Lava`,
/// `Chasm`). The byte-equal parity gate lives at
/// `tests/unit/test_emit_terrain_tints_parity.py`.
#[pyfunction]
fn draw_terrain_tints(
    tiles: Vec<(i32, i32, u8)>,
    palette: HashMap<u8, (String, f64)>,
    washes: Vec<(i32, i32, i32, i32, String, f64)>,
) -> (Vec<String>, Vec<String>) {
    primitives::terrain_tints::draw_terrain_tints(
        &tiles, &palette, &washes,
    )
}

/// PyO3 module entry point. The function name MUST match the
/// `[lib] name` in Cargo.toml (`nhc_render`) so Python's
/// import machinery finds it.
#[pymodule]
fn nhc_render(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(splitmix64_next, m)?)?;
    m.add_function(wrap_pyfunction!(perlin2, m)?)?;
    m.add_function(wrap_pyfunction!(draw_floor_grid, m)?)?;
    m.add_function(wrap_pyfunction!(draw_terrain_tints, m)?)?;
    Ok(())
}
