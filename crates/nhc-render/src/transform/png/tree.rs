//! Tree surface feature — Phase 5.4.10 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_tree_from_ir`: walks `op.tiles` (free trees)
//! plus `op.grove_tiles` + `op.grove_sizes` (groves of size ≥ 3
//! flattened across both arrays) and delegates to
//! `primitives::tree::draw_tree`. The fragment helper handles
//! the resulting per-tree + per-grove SVG fragments.

use crate::ir::{FloorIR, OpEntry};
use crate::primitives;

use super::fragment::paint_fragments;
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

    let frags = primitives::tree::draw_tree(&free_trees, &groves);
    paint_fragments(&frags, 1.0, None, ctx);
}
