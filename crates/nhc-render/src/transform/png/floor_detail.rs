//! Floor-detail op rasterisation — Phase 5.3.2 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_floor_detail_from_ir`. The structured branch
//! (`tiles` + `is_corridor` + `seed` + `theme` + `macabre`)
//! flows through `primitives::floor_detail::draw_floor_detail`
//! to get the cracks / scratches / stones group bundles; the
//! room-side bundles paint inside a dungeon-interior clip mask
//! while the corridor side paints unclipped.
//!
//! `wood_floor_groups` defers to Phase 5.5 — the wood-floor
//! short-circuit owns its own clipPath envelope and sits inside
//! the SVG passthrough surface that 5.5 covers.
//!
//! Thematic passthrough (`room_groups` / `corridor_groups`) is
//! a Phase 1 transitional artifact. As of schema 2.0 the
//! ThematicDetailOp owns thematic detail and these vectors
//! should be empty for the starter fixtures; if they aren't,
//! the fragment rasteriser still walks them so the parity gate
//! catches any drift.

use tiny_skia::{FillRule, Mask};

use crate::ir::{FloorDetailOp, FloorIR, OpEntry};
use crate::primitives::floor_detail::draw_floor_detail;

use super::fragment::paint_fragments;
use super::polygon_path::build_polygon_path;
use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_floor_detail_op() {
        Some(o) => o,
        None => return,
    };

    // Wood-floor short-circuit — the legacy emitter ships its
    // own clipPath envelope alongside the per-tile plank
    // fragments. Phase 5.5 wires the passthrough through the
    // shared fragment helper; the wood-floor Rust port (Phase 7
    // cleanup) retires this branch once the walk_and_paint
    // pipeline is gone.
    let wood: Vec<String> = op
        .wood_floor_groups()
        .map(|v| v.iter().map(String::from).collect())
        .unwrap_or_default();
    if !wood.is_empty() {
        paint_fragments(&wood, 1.0, None, ctx);
        return;
    }

    let theme = op.theme().unwrap_or("");
    let macabre = fir
        .flags()
        .map(|f| f.macabre_detail())
        .unwrap_or(true);
    let tiles: Vec<(i32, i32, bool)> = match (op.tiles(), op.is_corridor()) {
        (Some(t), Some(c)) => t
            .iter()
            .enumerate()
            .map(|(i, coord)| (coord.x(), coord.y(), c.get(i)))
            .collect(),
        _ => Vec::new(),
    };

    let (rust_room, rust_corridor) = if tiles.is_empty() {
        (Vec::new(), Vec::new())
    } else {
        draw_floor_detail(&tiles, op.seed(), theme, macabre)
    };

    let thematic_room: Vec<String> = op
        .room_groups()
        .map(|v| v.iter().map(String::from).collect())
        .unwrap_or_default();
    let thematic_corridor: Vec<String> = op
        .corridor_groups()
        .map(|v| v.iter().map(String::from).collect())
        .unwrap_or_default();

    let clip_mask = build_clip_mask(&op, fir, ctx);

    paint_fragments(&rust_room, 1.0, clip_mask.as_ref(), ctx);
    paint_fragments(&thematic_room, 1.0, clip_mask.as_ref(), ctx);
    paint_fragments(&rust_corridor, 1.0, None, ctx);
    paint_fragments(&thematic_corridor, 1.0, None, ctx);
}

fn build_clip_mask(
    op: &FloorDetailOp<'_>,
    fir: &FloorIR<'_>,
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let region_id = op.clip_region()?;
    if region_id.is_empty() {
        return None;
    }
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let polygon = region.polygon()?;
    let path = build_polygon_path(&polygon)?;
    let mut mask = Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&path, FillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}
