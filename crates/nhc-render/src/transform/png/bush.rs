//! Bush surface feature — Phase 5.4.11 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_bush_from_ir`: walks `op.tiles` and delegates
//! to `primitives::bush::draw_bush` for the multi-lobe canopy +
//! shadow with HLS-jittered fill colour.

use crate::ir::{FloorIR, OpEntry};
use crate::primitives;

use super::fragment::paint_fragments;
use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_bush_feature_op() {
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
    let frags = primitives::bush::draw_bush(&tiles);
    paint_fragments(&frags, 1.0, None, ctx);
}
