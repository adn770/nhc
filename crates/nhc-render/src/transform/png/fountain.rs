//! Fountain surface feature — Phase 5.4.9 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_fountain_from_ir`: walks `op.tiles` +
//! `op.shape` (5 variants — Round / Square / LargeRound /
//! LargeSquare / Cross) and delegates to
//! `primitives::fountain::draw_fountain`.

use crate::ir::{FloorIR, OpEntry};
use crate::primitives;

use super::fragment::paint_fragments;
use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_fountain_feature_op() {
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
    let frags = primitives::fountain::draw_fountain(&tiles, shape);
    paint_fragments(&frags, 1.0, None, ctx);
}
