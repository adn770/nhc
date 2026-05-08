//! `nhc-render` — procedural map rendering primitives.
//!
//! The canonical home of every procedural primitive that the
//! Python rendering pipeline used to drive directly: splitmix64
//! PRNG, Perlin noise, per-tile detail emitters, hatching, and
//! the three transformer back-ends (PNG via `tiny-skia`, Canvas
//! command stream for WASM, optional SVG for parity testing).
//!
//! Server-side Python consumes the primitives via the PyO3 FFI
//! shim in `ffi::pyo3`; browser-side JavaScript consumes them
//! via `wasm-bindgen` exports in the standalone
//! `nhc-render-wasm` workspace member, which depends on this
//! crate with `default-features = false`.
//!
//! See `design/map_ir.md` §8 for the architecture rationale and
//! `plans/nhc_ir_migration_plan.md` Phase 4 for the per-primitive
//! port roadmap.

pub mod geometry;
pub mod ir;
pub mod painter;
pub mod perlin;
pub mod primitives;
pub mod python_random;
pub mod rng;
pub mod transform;

#[cfg(test)]
mod test_util;

#[cfg(feature = "pyo3")]
pub mod ffi;
