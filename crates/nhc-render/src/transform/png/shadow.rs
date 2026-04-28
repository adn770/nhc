//! Shadow op rasterisation — Phase 5.2.1 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_shadow_from_ir` in `nhc/rendering/ir_to_svg.py`
//! pixel-for-pixel: per-tile corridor rects (32×32 black at 0.08
//! alpha, +3 offset) for `ShadowKind::Corridor`, per-shape room
//! shadows for `ShadowKind::Room`. The room dispatch resolves
//! `op.region_ref` against `fir.regions[]` and routes by the
//! region's `shape_tag` (`rect` / `octagon` / `cave`); the
//! cave path replays the same centripetal Catmull-Rom →
//! cubic Bézier conversion `geometry::smooth_closed_path` uses
//! for its SVG output.

use tiny_skia::{Color, FillRule, Paint, PathBuilder, Rect, Transform};

use crate::geometry::centripetal_bezier_cps;
use crate::ir::{FloorIR, OpEntry, ShadowKind, ShadowOp};

use super::RasterCtx;

const CELL: f32 = 32.0;
const SHADOW_OFFSET: f32 = 3.0;
/// SVG `opacity="0.08"` lifted into the paint alpha. Both
/// resvg-py and tiny-skia composite with the same float; we keep
/// it in `f32` to dodge the int-rounding the legacy 0.08 → 20.4
/// → u8 path would introduce.
const SHADOW_ALPHA: f32 = 0.08;

fn shadow_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba(0.0, 0.0, 0.0, SHADOW_ALPHA).unwrap());
    p.anti_alias = true;
    p
}

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
    match op.kind() {
        ShadowKind::Corridor => draw_corridor(&op, ctx),
        ShadowKind::Room => draw_room(&op, fir, ctx),
        _ => {}
    }
}

fn draw_corridor(op: &ShadowOp<'_>, ctx: &mut RasterCtx<'_>) {
    let tiles = match op.tiles() {
        Some(t) => t,
        None => return,
    };
    let paint = shadow_paint();
    for tile in tiles.iter() {
        let px = tile.x() as f32 * CELL + SHADOW_OFFSET;
        let py = tile.y() as f32 * CELL + SHADOW_OFFSET;
        let rect = match Rect::from_xywh(px, py, CELL, CELL) {
            Some(r) => r,
            None => continue,
        };
        ctx.pixmap
            .fill_rect(rect, &paint, ctx.transform, None);
    }
}

fn draw_room(
    op: &ShadowOp<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
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
        "rect" => draw_room_rect(&coords, ctx),
        "octagon" => draw_room_octagon(&coords, ctx),
        "cave" => draw_room_cave(&coords, ctx),
        _ => {}
    }
}

fn draw_room_rect(coords: &[(f64, f64)], ctx: &mut RasterCtx<'_>) {
    let mut min_x = i32::MAX;
    let mut max_x = i32::MIN;
    let mut min_y = i32::MAX;
    let mut max_y = i32::MIN;
    for &(x, y) in coords {
        let xi = x as i32;
        let yi = y as i32;
        if xi < min_x {
            min_x = xi;
        }
        if xi > max_x {
            max_x = xi;
        }
        if yi < min_y {
            min_y = yi;
        }
        if yi > max_y {
            max_y = yi;
        }
    }
    let px = (min_x + 3) as f32;
    let py = (min_y + 3) as f32;
    let pw = (max_x - min_x) as f32;
    let ph = (max_y - min_y) as f32;
    let rect = match Rect::from_xywh(px, py, pw, ph) {
        Some(r) => r,
        None => return,
    };
    let paint = shadow_paint();
    ctx.pixmap
        .fill_rect(rect, &paint, ctx.transform, None);
}

fn draw_room_octagon(coords: &[(f64, f64)], ctx: &mut RasterCtx<'_>) {
    let mut pb = PathBuilder::new();
    let mut iter = coords.iter();
    if let Some(&(x, y)) = iter.next() {
        pb.move_to(x as f32, y as f32);
    }
    for &(x, y) in iter {
        pb.line_to(x as f32, y as f32);
    }
    pb.close();
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = shadow_paint();
    ctx.pixmap.fill_path(
        &path,
        &paint,
        FillRule::Winding,
        room_shadow_transform(ctx.transform),
        None,
    );
}

fn draw_room_cave(coords: &[(f64, f64)], ctx: &mut RasterCtx<'_>) {
    let n = coords.len();
    if n < 3 {
        return;
    }
    let mut pb = PathBuilder::new();
    pb.move_to(coords[0].0 as f32, coords[0].1 as f32);
    for i in 0..n {
        let p0 = coords[(i + n - 1) % n];
        let p1 = coords[i];
        let p2 = coords[(i + 1) % n];
        let p3 = coords[(i + 2) % n];
        let (c1x, c1y, c2x, c2y) =
            centripetal_bezier_cps(p0, p1, p2, p3);
        pb.cubic_to(
            c1x as f32,
            c1y as f32,
            c2x as f32,
            c2y as f32,
            p2.0 as f32,
            p2.1 as f32,
        );
    }
    pb.close();
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = shadow_paint();
    ctx.pixmap.fill_path(
        &path,
        &paint,
        FillRule::Winding,
        room_shadow_transform(ctx.transform),
        None,
    );
}

/// SVG `<g transform="translate(3,3)">` composed with the
/// outer `translate(padding,padding)` + scale transform.
fn room_shadow_transform(outer: Transform) -> Transform {
    outer.pre_translate(SHADOW_OFFSET, SHADOW_OFFSET)
}

fn find_region<'a>(
    fir: &FloorIR<'a>,
    region_ref: &str,
) -> Option<crate::ir::Region<'a>> {
    let regions = fir.regions()?;
    regions.iter().find(|r| r.id() == region_ref)
}

fn polygon_coords(region: &crate::ir::Region<'_>) -> Vec<(f64, f64)> {
    let polygon = match region.polygon() {
        Some(p) => p,
        None => return Vec::new(),
    };
    let paths = match polygon.paths() {
        Some(p) => p,
        None => return Vec::new(),
    };
    paths
        .iter()
        .map(|v| (v.x() as f64, v.y() as f64))
        .collect()
}
