//! Floor-grid op rasterisation — Phase 5.2.4 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_floor_grid_from_ir`: the per-edge wobbly grid
//! segment generator stays in `primitives::floor_grid` (it owns
//! the `PyRandom` + Perlin parity contract); the PNG handler
//! parses the resulting `(room_d, corridor_d)` pair into
//! `tiny-skia::Path` move/line ops and strokes them with the
//! GRID_WIDTH=0.3 / opacity=0.7 black ink the SVG envelope
//! carries.

use tiny_skia::{
    Color, FillRule, LineCap, LineJoin, Mask, Paint, Stroke,
};

use crate::ir::{FloorIR, FloorGridOp, OpEntry};
use crate::primitives::floor_grid::draw_floor_grid;

use super::path_parser::parse_path_d;
use super::polygon_path::build_polygon_path;
use super::RasterCtx;

const GRID_WIDTH: f32 = 0.3;
const GRID_OPACITY: f32 = 0.7;
const INK_R: u8 = 0x00;
const INK_G: u8 = 0x00;
const INK_B: u8 = 0x00;

fn grid_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(
        Color::from_rgba(
            INK_R as f32 / 255.0,
            INK_G as f32 / 255.0,
            INK_B as f32 / 255.0,
            GRID_OPACITY,
        )
        .unwrap_or(Color::TRANSPARENT),
    );
    p.anti_alias = true;
    p
}

fn grid_stroke() -> Stroke {
    Stroke {
        width: GRID_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
        ..Stroke::default()
    }
}

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_floor_grid_op() {
        Some(o) => o,
        None => return,
    };
    let tiles: Vec<(i32, i32, bool)> = op
        .tiles()
        .map(|v| {
            v.iter()
                .map(|t| (t.x(), t.y(), t.is_corridor()))
                .collect()
        })
        .unwrap_or_default();
    let (room_d, corridor_d) = draw_floor_grid(
        fir.width_tiles() as i32,
        fir.height_tiles() as i32,
        &tiles,
        op.seed(),
    );
    let paint = grid_paint();
    let stroke = grid_stroke();
    let clip_mask = build_clip_mask(&op, fir, ctx);

    if !room_d.is_empty() {
        if let Some(path) = parse_path_d(&room_d) {
            ctx.pixmap.stroke_path(
                &path,
                &paint,
                &stroke,
                ctx.transform,
                clip_mask.as_ref(),
            );
        }
    }
    if !corridor_d.is_empty() {
        if let Some(path) = parse_path_d(&corridor_d) {
            ctx.pixmap.stroke_path(
                &path,
                &paint,
                &stroke,
                ctx.transform,
                None,
            );
        }
    }
}

fn build_clip_mask(
    op: &FloorGridOp<'_>,
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
    let mut mask =
        Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&path, FillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}
