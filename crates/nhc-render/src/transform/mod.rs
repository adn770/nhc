//! Transformer back-ends — IR → output.
//!
//! - `png/` — `tiny-skia`-driven rasteriser. Each op handler
//!   writes through the `Painter` trait against the
//!   `SkiaPainter` impl that `floor_ir_to_png` constructs.
//! - `svg/` — IR → SVG document. Re-uses the same op handlers
//!   driving an `SvgPainter` (Phase 2.16 of
//!   `plans/nhc_pure_ir_plan.md`). Also houses the resvg-based
//!   `svg_to_png` cross-rasteriser used by the parity harness.

pub mod png;
pub mod svg;
