//! wasm-bindgen binding stub.
//!
//! Exposes the Rust crate as a WASM module that the Phase 6
//! browser client loads via `nhc_render_wasm.js`. Today the
//! surface is a single stub (`splitmix64_next`) so the build
//! pipeline (wasm-pack → wasm-opt) round-trips end-to-end;
//! `transform/canvas.rs` and the per-primitive emitters fill in
//! the real surface in IR migration plan Phase 6.
//!
//! Only compiled when `wasm` is on AND `pyo3` is off (the two
//! ABIs export overlapping symbol names with different calling
//! conventions and can't share a single library).

use wasm_bindgen::prelude::*;

use crate::rng::SplitMix64;

/// Pull the next splitmix64 output for a given seed. Mirrors the
/// PyO3 stub so the JS client and Python server can share golden
/// vectors during cross-language fuzzing.
#[wasm_bindgen]
pub fn splitmix64_next(seed: u64) -> u64 {
    SplitMix64::from_seed(seed).next_u64()
}
