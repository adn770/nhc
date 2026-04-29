//! Terrain-detail op rasterisation — Phase 5.5 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! TerrainDetailOp is a Phase 1 transitional passthrough — the
//! legacy Python `_render_terrain_detail` (grass blades, water
//! ripples, lava splatters, chasm motes) still owns the
//! procedural geometry and ships pre-rendered `<g>` envelopes
//! through `room_groups` / `corridor_groups`. The PNG handler
//! parses those fragments via the shared fragment helper.
//! Phase 7's "remove _decorators.py" milestone retires this
//! passthrough once the terrain-detail painters port to Rust.

use tiny_skia::{FillRule, Mask};

use crate::ir::{FloorIR, OpEntry, TerrainDetailOp};

use super::fragment::paint_fragments;
use super::polygon_path::build_polygon_path;
use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_terrain_detail_op() {
        Some(o) => o,
        None => return,
    };
    let room: Vec<String> = op
        .room_groups()
        .map(|v| v.iter().map(String::from).collect())
        .unwrap_or_default();
    let corridor: Vec<String> = op
        .corridor_groups()
        .map(|v| v.iter().map(String::from).collect())
        .unwrap_or_default();
    if room.is_empty() && corridor.is_empty() {
        return;
    }
    let clip_mask = build_clip_mask(&op, fir, ctx);
    paint_fragments(&room, 1.0, clip_mask.as_ref(), ctx);
    paint_fragments(&corridor, 1.0, None, ctx);
}

fn build_clip_mask(
    op: &TerrainDetailOp<'_>,
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
