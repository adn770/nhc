//! Thematic-detail op rasterisation — Phase 5.3.3 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_thematic_detail_from_ir`: webs / bones /
//! skulls per theme, gated by `macabre_detail`. The structured
//! input lives on `ThematicDetailOp` (tiles, is_corridor,
//! wall_corners); `primitives::thematic_detail::draw_thematic_detail`
//! returns the same `(room_groups, corridor_groups)` tuple
//! shape `floor_detail` does. Room-side fragments paint inside
//! the dungeon-interior clip mask; corridor-side fragments
//! paint unclipped.

use tiny_skia::{FillRule, Mask};

use crate::ir::{FloorIR, OpEntry, ThematicDetailOp};
use crate::primitives::thematic_detail::draw_thematic_detail;

use super::fragment::paint_fragments;
use super::polygon_path::build_polygon_path;
use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_thematic_detail_op() {
        Some(o) => o,
        None => return,
    };
    let tiles = op.tiles();
    let is_corridor = op.is_corridor();
    let wall_corners = op.wall_corners();
    let tiles = match (tiles, is_corridor) {
        (Some(t), Some(c)) => t
            .iter()
            .enumerate()
            .map(|(i, coord)| {
                let wc = wall_corners
                    .as_ref()
                    .map(|v| v.get(i))
                    .unwrap_or(0);
                (coord.x(), coord.y(), c.get(i), wc)
            })
            .collect::<Vec<_>>(),
        _ => return,
    };
    if tiles.is_empty() {
        return;
    }

    let theme = op.theme().unwrap_or("");
    let macabre = fir
        .flags()
        .map(|f| f.macabre_detail())
        .unwrap_or(true);
    let (room_groups, corridor_groups) =
        draw_thematic_detail(&tiles, op.seed(), theme, macabre);

    let clip_mask = build_clip_mask(&op, fir, ctx);
    paint_fragments(&room_groups, 1.0, clip_mask.as_ref(), ctx);
    paint_fragments(&corridor_groups, 1.0, None, ctx);
}

fn build_clip_mask(
    op: &ThematicDetailOp<'_>,
    fir: &FloorIR<'_>,
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    // Phase 1.25 — prefer op.region_ref; fall back to clip_region.
    let region_id = op
        .region_ref()
        .filter(|r| !r.is_empty())
        .or_else(|| op.clip_region())?;
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
