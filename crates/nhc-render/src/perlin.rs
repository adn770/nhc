//! Perlin noise — 2D port of `nhc/rendering/_perlin.py`.
//!
//! **Skeleton only.** The byte-equal port is IR migration plan
//! Phase 3, gated on the parity vectors generated in Phase 0.6
//! (`tests/fixtures/perlin/pnoise2_vectors.json`). The plan ships
//! the port as one focused commit so a regression bisects cleanly
//! to a single primitive.
//!
//! The Python reference is the vendored pure-Python `pnoise2`
//! that replaced the unmaintained C `noise` package — see commit
//! `de7cca6` for the deps drop. The Rust port reproduces its
//! permutation table, gradient hashing, and fade curve verbatim.

/// 2D Perlin noise with explicit `base` (the integer "seed" that
/// the legacy `noise.pnoise2(x, y, base=N)` API exposed). Returns
/// a value in roughly `[-1.0, 1.0]`.
///
/// **Not yet implemented.** Calling this in production code is a
/// programming error during Phase 0–2; the function exists so
/// downstream FFI shims can be authored against a stable
/// signature before Phase 3 fills it in.
pub fn pnoise2(_x: f32, _y: f32, _base: i32) -> f32 {
    unimplemented!(
        "perlin port lands in IR migration plan Phase 3; until \
         then, the Python `_perlin.py` shim is canonical"
    )
}
