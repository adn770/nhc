//! Well surface feature — Phase 5.4.8 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_well_from_ir`: walks `op.tiles` + `op.shape`,
//! delegates to `primitives::well::draw_well` for the fragment
//! list (round / square keystone arcs + pool), then rasterises
//! via the shared fragment helper.

use crate::ir::{FloorIR, OpEntry};
use crate::primitives;

use super::fragment::paint_fragments;
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
    let frags = primitives::well::draw_well(&tiles, shape);
    paint_fragments(&frags, 1.0, None, ctx);
}
