//! Stairs op rasterisation — Phase 5.2.5 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.6 of `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors `_draw_stairs_from_ir`: per-stair tapering wedge +
//! parallel step lines + (cave theme only) a fill polygon. The
//! per-stair geometry construction lives in
//! `crate::primitives::stairs::paint_stairs`; this handler wraps
//! the active `tiny_skia::Pixmap` in a `SkiaPainter` and forwards
//! to it. The byte-equality contract with the legacy direct
//! `tiny_skia::Pixmap::fill_path` / `stroke_path` calls is held
//! by the PNG parity gate.
//!
//! `StairDirection` is normalised to the legacy `u8` discriminant
//! (`Up=0`, `Down=1`) at the boundary so the primitive's
//! signature stays free of FlatBuffers types — both emit paths
//! (legacy SVG-string `draw_stairs` and the new `paint_stairs`)
//! consume the same `(x, y, direction)` tuple shape.

use crate::ir::{FloorIR, OpEntry, StairDirection};
use crate::painter::SkiaPainter;
use crate::primitives::stairs as stairs_prim;

use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_stairs_op() {
        Some(o) => o,
        None => return,
    };
    let stairs = match op.stairs() {
        Some(s) => s,
        None => return,
    };
    let theme = op.theme().unwrap_or("");
    let fill_color = op.fill_color().unwrap_or("#000000");

    let stair_tuples: Vec<(i32, i32, u8)> = stairs
        .iter()
        .map(|s| {
            let dir = if s.direction() == StairDirection::Down { 1 } else { 0 };
            (s.x(), s.y(), dir)
        })
        .collect();

    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    stairs_prim::paint_stairs(&mut painter, &stair_tuples, theme, fill_color);
}
