//! Shadow op rasterisation — Phase 5.2.1 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.4 of `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors `_draw_shadow_from_ir` in `nhc/rendering/ir_to_svg.py`
//! pixel-for-pixel: per-tile corridor rects (32×32 black at 0.08
//! alpha, +3 offset) for `ShadowKind::Corridor`, per-shape room
//! shadows for `ShadowKind::Room`. The room dispatch resolves
//! `op.region_ref` against `fir.regions[]` and routes by the
//! region's `shape_tag` (`rect` / `octagon` / `cave`). Per-shape
//! geometry construction lives in `crate::primitives::shadow`;
//! this handler wraps the active `tiny_skia::Pixmap` in a
//! `SkiaPainter` and calls `paint_*` against it.

use crate::ir::{FloorIR, OpEntry, ShadowKind, ShadowOp};
use crate::painter::SkiaPainter;
use crate::primitives::shadow as shadow_prim;

use super::RasterCtx;

/// `OpHandler` dispatch entry. Registered against
/// `Op::ShadowOp` in `super::op_handlers`.
pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_shadow_op() {
        Some(o) => o,
        None => return,
    };
    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    match op.kind() {
        ShadowKind::Corridor => paint_corridor(&op, &mut painter),
        ShadowKind::Room => paint_room(&op, fir, &mut painter),
        _ => {}
    }
}

fn paint_corridor(op: &ShadowOp<'_>, painter: &mut SkiaPainter<'_>) {
    let tiles = match op.tiles() {
        Some(t) => t,
        None => return,
    };
    let tile_pairs: Vec<(i32, i32)> = tiles
        .iter()
        .map(|t| (t.x() as i32, t.y() as i32))
        .collect();
    shadow_prim::paint_corridor_shadows(painter, &tile_pairs);
}

fn paint_room(
    op: &ShadowOp<'_>,
    fir: &FloorIR<'_>,
    painter: &mut SkiaPainter<'_>,
) {
    let region_ref = match op.region_ref() {
        Some(r) => r,
        None => return,
    };
    let region = match find_region(fir, region_ref) {
        Some(r) => r,
        None => return,
    };
    let coords = polygon_coords(&region);
    if coords.is_empty() {
        return;
    }
    let shape_tag = region.shape_tag().unwrap_or("");
    match shape_tag {
        "rect" => shadow_prim::paint_room_shadow_rect(painter, &coords),
        "octagon" => shadow_prim::paint_room_shadow_octagon(painter, &coords),
        "cave" => shadow_prim::paint_room_shadow_cave(painter, &coords),
        _ => {}
    }
}

fn find_region<'a>(
    fir: &FloorIR<'a>,
    region_ref: &str,
) -> Option<crate::ir::Region<'a>> {
    let regions = fir.regions()?;
    regions.iter().find(|r| r.id() == region_ref)
}

fn polygon_coords(region: &crate::ir::Region<'_>) -> Vec<(f64, f64)> {
    let outline = match region.outline() {
        Some(o) => o,
        None => return Vec::new(),
    };
    let verts = match outline.vertices() {
        Some(v) => v,
        None => return Vec::new(),
    };
    verts
        .iter()
        .map(|v| (v.x() as f64, v.y() as f64))
        .collect()
}
