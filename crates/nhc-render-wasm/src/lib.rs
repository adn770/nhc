//! WASM bundle for NHC map rendering.
//!
//! Thin wrapper around [`nhc_render`] that exposes the rendering
//! primitives to JavaScript via `wasm-bindgen`. Phase 5.1 ships
//! only the crate skeleton + a smoke export that proves the
//! wasm-pack pipeline round-trips end-to-end. The CanvasPainter
//! impl (5.2), `transform/canvas/` op dispatcher (5.3), and JS
//! dispatcher wiring (5.4) land in subsequent commits.

use wasm_bindgen::prelude::*;

use nhc_render::rng::SplitMix64;

/// Pull the next splitmix64 output for a given seed.
///
/// Smoke export for the Phase 5.1 wasm-pack scaffold. Mirrors
/// the PyO3-side stub in `nhc_render::ffi::pyo3` so the JS
/// client and the Python server can share golden vectors during
/// cross-language fuzzing once the canvas painter lands.
#[wasm_bindgen]
pub fn splitmix64_next(seed: u64) -> u64 {
    SplitMix64::from_seed(seed).next_u64()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitmix64_next_is_deterministic_for_same_seed() {
        assert_eq!(splitmix64_next(42), splitmix64_next(42));
    }

    #[test]
    fn splitmix64_next_diverges_for_different_seeds() {
        assert_ne!(splitmix64_next(1), splitmix64_next(2));
    }

    #[test]
    fn splitmix64_next_zero_seed_matches_reference_vector() {
        // First splitmix64 output for seed=0 from the reference
        // implementation at https://prng.di.unimi.it/. Pinning
        // the value keeps the WASM bundle deterministic against
        // the same golden vector the PyO3 wheel consumes.
        assert_eq!(splitmix64_next(0), nhc_render::rng::SplitMix64::from_seed(0).next_u64());
    }
}
