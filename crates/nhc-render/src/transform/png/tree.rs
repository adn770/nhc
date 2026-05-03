//! Tree surface feature — Phase 5.4.10 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.14c of `plans/nhc_pure_ir_plan.md` (the third of
//! four fixture ports — well / fountain / tree / bush).
//!
//! Walks `op.tiles` (free trees) plus `op.grove_tiles` +
//! `op.grove_sizes` (groves of size ≥ 3 flattened across both
//! arrays) and dispatches the per-tree + per-grove geometry
//! through `primitives::tree::paint_tree` via a `SkiaPainter`
//! constructed for the dispatch scope. Fixtures are NO group-
//! opacity (plan §2.14), so `paint_tree` composites stamps
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
    let op = match entry.op_as_tree_feature_op() {
        Some(o) => o,
        None => return,
    };
    let free_trees: Vec<(i32, i32)> = op
        .tiles()
        .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
        .unwrap_or_default();
    let grove_flat: Vec<(i32, i32)> = op
        .grove_tiles()
        .map(|t| t.iter().map(|c| (c.x(), c.y())).collect())
        .unwrap_or_default();
    let grove_sizes: Vec<u32> = op
        .grove_sizes()
        .map(|v| v.iter().collect())
        .unwrap_or_default();

    if free_trees.is_empty() && grove_flat.is_empty() {
        return;
    }

    let mut groves: Vec<Vec<(i32, i32)>> = Vec::with_capacity(grove_sizes.len());
    let mut cursor = 0usize;
    for size in grove_sizes {
        let n = size as usize;
        if cursor + n > grove_flat.len() {
            break;
        }
        groves.push(grove_flat[cursor..cursor + n].to_vec());
        cursor += n;
    }

    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    primitives::tree::paint_tree(&mut painter, &free_trees, &groves);
}
