//! PyO3 binding stub.
//!
//! Exposes the Rust crate as a Python extension module named
//! `nhc_render`. Module surface grows primitive-by-primitive per
//! `plans/nhc_ir_migration_plan.md` Phase 3+. Today: `splitmix64_next`
//! (Phase 0.3 sentinel) and `perlin2` (Phase 3 cross-language gate).
//!
//! Only compiled when the `pyo3` feature is on — disabled for
//! WASM builds and for `cargo test`-without-features.

use pyo3::prelude::*;

use crate::perlin;
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

/// PyO3 module entry point. The function name MUST match the
/// `[lib] name` in Cargo.toml (`nhc_render`) so Python's
/// import machinery finds it.
#[pymodule]
fn nhc_render(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(splitmix64_next, m)?)?;
    m.add_function(wrap_pyfunction!(perlin2, m)?)?;
    Ok(())
}
