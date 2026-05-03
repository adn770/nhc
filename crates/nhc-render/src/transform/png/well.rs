//! Well surface feature — Phase 5.4.8 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.14a of `plans/nhc_pure_ir_plan.md` (the first of
//! four fixture ports — well / fountain / tree / bush).
//!
//! Walks `op.tiles` + `op.shape`, then dispatches each tile
//! through `primitives::well::paint_well` via a `SkiaPainter`
//! constructed for the dispatch scope. Fixtures are NO group-
//! opacity (plan §2.14), so `paint_well` composites stamps
//! directly without a `begin_group` / `end_group` envelope.

use crate::ir::{FloorIR, OpEntry};
use crate::painter::SkiaPainter;
use crate::primitives;

use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_well_feature_op() {
        Some(o) => o,
        None => return,
    };
    let tiles: Vec<(i32, i32)> = match op.tiles() {
        Some(t) => t.iter().map(|c| (c.x(), c.y())).collect(),
        None => return,
    };
    if tiles.is_empty() {
        return;
    }
    let shape = op.shape().0 as u8;
    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    primitives::well::paint_well(&mut painter, &tiles, shape);
}
