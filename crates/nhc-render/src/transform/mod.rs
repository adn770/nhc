//! Transformer back-ends — IR → output.
//!
//! - `png/` — `tiny-skia`-driven rasteriser. Each op handler
//!   writes through the `Painter` trait against the
//!   `SkiaPainter` impl that `floor_ir_to_png` constructs.
//! - `svg/` — IR → SVG document. Re-uses the same op handlers
//!   driving an `SvgPainter` (Phase 2.16 of
//!   `plans/nhc_pure_ir_plan.md`). Also houses the resvg-based
//!   `svg_to_png` cross-rasteriser used by the parity harness.
//! - `canvas/` — IR → Canvas2D draw stream. Phase 5.3 of
//!   `plans/nhc_pure_ir_v5_migration_plan.md`. Generic over the
//!   ``painter::canvas::Canvas2DCtx`` trait so the entry point
//!   compiles without ``web-sys``; the browser-side binding
//!   lives in the ``nhc-render-wasm`` workspace member.

pub mod canvas;
pub mod png;
pub mod svg;
