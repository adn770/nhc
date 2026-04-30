//! Floor-detail op rasterisation — Phase 5.3.2 of
//! `plans/nhc_ir_migration_plan.md`, with the wood-floor short-
//! circuit ported in Phase 9.2c.
//!
//! Mirrors `_draw_floor_detail_from_ir`. Two modes:
//!
//! - Wood-floor short-circuit (`wood_tiles` / `wood_rooms` /
//!   `wood_building_polygon` populated) — dispatch through
//!   `primitives::wood_floor::draw_wood_floor` and paint with the
//!   dungeon-poly clip mask applied uniformly.
//! - Otherwise: floor-detail-proper (`tiles` + `is_corridor` +
//!   `seed` + `theme` + `macabre`) flows through
//!   `primitives::floor_detail::draw_floor_detail` to get the
//!   cracks / scratches / stones bundles; room bundles paint
//!   inside the dungeon-interior clip mask, corridor bundles
//!   paint unclipped.
//!
//! Schema 3.1 (Phase 0.1 of plans/nhc_pure_ir_plan.md) drops the
//! legacy thematic passthrough reads on `room_groups` /
//! `corridor_groups`: ThematicDetailOp has owned thematic detail
//! since schema 2.0 and the fields haven't been populated since
//! 3.0. The schema fields stay declared until the 4.0 cut.

use tiny_skia::{FillRule, Mask, PathBuilder};

use crate::ir::{FloorDetailOp, FloorIR, OpEntry};
use crate::primitives::floor_detail::draw_floor_detail;
use crate::primitives::wood_floor::{
    draw_wood_floor, PolyVertex, WoodRoom,
};

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

    // Wood-floor short-circuit (Phase 9.2c). When any of the
    // structured fields is populated, dispatch through the
    // `wood_floor` primitive and short-circuit the regular
    // floor-detail flow.
    let wood_rooms: Vec<WoodRoom> = op
        .wood_rooms()
        .map(|v| {
            v.iter()
                .map(|r| WoodRoom {
                    x: r.x(),
                    y: r.y(),
                    w: r.w(),
                    h: r.h(),
                })
                .collect()
        })
        .unwrap_or_default();
    let wood_tiles: Vec<(i32, i32)> = op
        .wood_tiles()
        .map(|v| v.iter().map(|t| (t.x(), t.y())).collect())
        .unwrap_or_default();
    let wood_polygon: Vec<PolyVertex> = op
        .wood_building_polygon()
        .map(|v| {
            v.iter()
                .map(|p| PolyVertex {
                    x: f64::from(p.x()),
                    y: f64::from(p.y()),
                })
                .collect()
        })
        .unwrap_or_default();
    if !wood_rooms.is_empty()
        || !wood_tiles.is_empty()
        || !wood_polygon.is_empty()
    {
        let frags = draw_wood_floor(
            &wood_tiles, &wood_polygon, &wood_rooms, op.seed(),
        );
        // The wood base fill now lives in WallsAndFloorsOp
        // (structural layer); this op only paints grain + seam
        // strokes. Clip them to the building polygon so they
        // don't bleed past the chamfered / curved corners of
        // octagon / circle / L-shape buildings, intersected
        // with the dungeon clip when both are present.
        let clip_mask = build_wood_clip_mask(&op, fir, &wood_polygon, ctx);
        paint_fragments(&frags, 1.0, clip_mask.as_ref(), ctx);
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

    let clip_mask = build_clip_mask(&op, fir, ctx);

    paint_fragments(&rust_room, 1.0, clip_mask.as_ref(), ctx);
    paint_fragments(&rust_corridor, 1.0, None, ctx);
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

/// Wood-floor clip mask: building polygon intersected with the
/// dungeon clip when both are present. The grain + seam strokes
/// from `draw_wood_floor` are bbox-aligned to each room rect, so
/// without this mask they bleed past the chamfered corners of
/// octagon / circle / L-shape building footprints.
fn build_wood_clip_mask(
    op: &FloorDetailOp<'_>,
    fir: &FloorIR<'_>,
    polygon: &[PolyVertex],
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let dungeon = build_clip_mask(op, fir, ctx);
    if polygon.len() < 3 {
        return dungeon;
    }
    let mut pb = PathBuilder::new();
    let first = polygon[0];
    pb.move_to(first.x as f32, first.y as f32);
    for v in &polygon[1..] {
        pb.line_to(v.x as f32, v.y as f32);
    }
    pb.close();
    let bldg_path = pb.finish()?;
    if let Some(mut mask) = dungeon {
        // Mask::intersect_path keeps only the pixels inside the
        // building polygon AND the dungeon clip mask.
        mask.intersect_path(
            &bldg_path, FillRule::EvenOdd, true, ctx.transform,
        );
        return Some(mask);
    }
    let mut mask = Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&bldg_path, FillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}
