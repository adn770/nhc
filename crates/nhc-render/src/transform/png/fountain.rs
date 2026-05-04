//! Fountain surface feature — Phase 5.4.9 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.14b of `plans/nhc_pure_ir_plan.md` (the second of
//! four fixture ports — well / fountain / tree / bush).
//!
//! Walks `op.tiles` + `op.shape` (5 variants — Round / Square /
//! LargeRound / LargeSquare / Cross) and dispatches each tile
//! through `primitives::fountain::paint_fountain` via a
//! `SkiaPainter` constructed for the dispatch scope. Fixtures are
//! NO group-opacity (plan §2.14), so `paint_fountain` composites
//! stamps directly without a `begin_group` / `end_group`
//! envelope.

use crate::ir::{FloorIR, OpEntry};
use crate::painter::Painter;
use crate::primitives;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    painter: &mut dyn Painter,
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
    primitives::fountain::paint_fountain(painter, &tiles, shape);
}
