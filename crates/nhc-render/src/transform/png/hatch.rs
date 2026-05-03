//! Hatch op rasterisation — Phase 5.3.1 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.9 of `plans/nhc_pure_ir_plan.md` (the **first
//! group-opacity port**).
//!
//! Mirrors `_draw_hatch_from_ir`. Per kind:
//!
//! - **Corridor:** delegate to `primitives::hatch::paint_hatch_corridor`.
//! - **Room:** delegate to `primitives::hatch::paint_hatch_room`.
//!
//! Phase 1.21a: the room-halo clip mask (outer rect XOR dungeon
//! polygon under EvenOdd) is dropped. The stamp model relies on
//! paint order to cover any tile-bbox bleed at smooth-room corners
//! — `HatchOp` runs before `emit_walls_and_floors` in `IR_STAGES`,
//! so floor / wall ops paint OVER the hatch and naturally clip
//! its bleed inside the dungeon polygon.
//!
//! Bucket compositing: the legacy SVG output wraps each non-empty
//! bucket in `<g opacity="…">` (`0.3` for `tile_fills`, `0.5` for
//! `hatch_lines`, bare `<g>` for `hatch_stones`). Pre-2.9 the PNG
//! handler approximated this with per-element alpha — that
//! over-darkens overlapping stamps relative to the SVG-spec
//! offscreen-buffer composite. Phase 2.9 routes through
//! `SkiaPainter::begin_group` / `end_group` (Phase 5.10's
//! `paint_offscreen_group` lifted into the trait) so overlapping
//! hatch stamps composite correctly. Slight pixel drift is
//! expected at hatch-overlap regions vs the pre-port references —
//! the corrected pixels are lighter (the over-darken bug is
//! fixed), not darker.

use crate::ir::{FloorIR, HatchKind, HatchOp, OpEntry};
use crate::painter::SkiaPainter;
use crate::primitives::hatch::{paint_hatch_corridor, paint_hatch_room};

use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_hatch_op() {
        Some(o) => o,
        None => return,
    };
    match op.kind() {
        HatchKind::Corridor => draw_corridor(&op, ctx),
        HatchKind::Room => draw_room(&op, ctx),
        _ => {}
    }
}

fn draw_corridor(op: &HatchOp<'_>, ctx: &mut RasterCtx<'_>) {
    let tiles: Vec<(i32, i32)> = match op.tiles() {
        Some(t) => t.iter().map(|c| (c.x(), c.y())).collect(),
        None => return,
    };
    if tiles.is_empty() {
        return;
    }
    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    paint_hatch_corridor(&mut painter, &tiles, op.seed());
}

fn draw_room(op: &HatchOp<'_>, ctx: &mut RasterCtx<'_>) {
    let tiles: Vec<(i32, i32)> = match op.tiles() {
        Some(t) => t.iter().map(|c| (c.x(), c.y())).collect(),
        None => return,
    };
    if tiles.is_empty() {
        return;
    }
    let is_outer: Vec<bool> = op
        .is_outer()
        .map(|v| v.iter().collect())
        .unwrap_or_else(|| vec![false; tiles.len()]);
    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    paint_hatch_room(&mut painter, &tiles, &is_outer, op.seed());
}
