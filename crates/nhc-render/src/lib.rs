//! `nhc-render` — procedural map rendering primitives.
//!
//! The canonical home of every procedural primitive that the
//! Python rendering pipeline used to drive directly: splitmix64
//! PRNG, Perlin noise, per-tile detail emitters, hatching, and
//! the three transformer back-ends (PNG via `tiny-skia`, Canvas
//! command stream for WASM, optional SVG for parity testing).
//!
//! Each primitive is reachable from both ABIs — Python via PyO3
//! and JavaScript via wasm-bindgen — through thin FFI shims in
//! `ffi::pyo3` and `ffi::wasm`. The shims contain no logic; they
//! deserialise FlatBuffers IR and call into the primitives.
//!
//! See `design/map_ir.md` §8 for the architecture rationale and
//! `plans/nhc_ir_migration_plan.md` Phase 4 for the per-primitive
//! port roadmap.

pub mod ir;
pub mod perlin;
pub mod primitives;
pub mod rng;
pub mod transform;

#[cfg(feature = "pyo3")]
pub mod ffi;

#[cfg(all(feature = "wasm", not(feature = "pyo3")))]
pub mod ffi;
