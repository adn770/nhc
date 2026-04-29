//! Transformer back-ends — IR → output.
//!
//! Three submodules, each shipped in its own phase of
//! `plans/nhc_ir_migration_plan.md`:
//!
//! - `svg.rs` — optional Rust SVG emitter for Phase 1 parity
//!   testing (the Python emitter remains canonical there).
//! - `png.rs` — `tiny-skia`-driven rasteriser, Phase 5. Replaces
//!   the resvg-py stepping stone and runs entirely in Rust.
//! - `canvas.rs` — emits a typed-array stream of canvas2d
//!   opcodes for the WASM Phase 6 client renderer.
//!
//! Phase 5.1 lands the `png` submodule with a stub that resolves
//! the canvas dimensions and returns an empty PNG; later sub-
//! phases populate the pixmap primitive-by-primitive.

pub mod png;
pub mod svg;
