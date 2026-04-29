//! GenericProceduralOp rasterisation — Phase 5.5 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! GenericProceduralOp is the Phase 1 transitional escape hatch
//! for layers that haven't earned a dedicated table yet. It
//! carries pre-rendered `<g>` envelopes via `op.groups`; the
//! PNG handler walks them through the shared fragment helper.
//!
//! The schema-2.0 status comment kept this op as a deliberate
//! escape hatch (see design/map_ir.md §5); the surface-features
//! layer is the only live consumer today, fed by the
//! walk_and_paint surface-feature passthrough that has not yet
//! ported to Rust.

use crate::ir::{FloorIR, OpEntry};

use super::fragment::paint_fragments;
use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_generic_procedural_op() {
        Some(o) => o,
        None => return,
    };
    let groups: Vec<String> = op
        .groups()
        .map(|v| v.iter().map(String::from).collect())
        .unwrap_or_default();
    if groups.is_empty() {
        return;
    }
    paint_fragments(&groups, 1.0, None, ctx);
}
