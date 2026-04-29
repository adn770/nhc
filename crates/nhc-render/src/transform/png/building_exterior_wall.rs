//! BuildingExteriorWallOp rasterisation — Phase 8.3c of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_building_exterior_wall_from_ir` in
//! `nhc/rendering/ir_to_svg.py` constant-for-constant. Walks the
//! Building region polygon, applies the half-thickness vertex-
//! extension trick so adjacent edges overlap at corners, and
//! renders a 2-strip running-bond chain per edge using splitmix64
//! seeded `rng_seed + edge_idx`.

use std::f32::consts::PI;

use tiny_skia::{
    Color, FillRule, LineCap, Paint, PathBuilder, Stroke, Transform,
};

use crate::ir::{BuildingExteriorWallOp, FloorIR, OpEntry, Region, WallMaterial};
use crate::rng::SplitMix64;

use super::RasterCtx;


// Constants mirror nhc/rendering/_building_walls.py.

const STRIP_COUNT: i32 = 2;
const MEAN_WIDTH: f32 = 12.0;
const WIDTH_LOW: f32 = 0.9;
const WIDTH_HIGH: f32 = 1.1;
const CORNER_RADIUS: f32 = 1.2;
const STROKE_WIDTH: f32 = 1.0;
const WALL_THICKNESS: f32 = 8.0;

const STRIP_OFFSETS: [f32; 2] = [0.0, MEAN_WIDTH / 2.0];

const BRICK_FILL_RGB: (u8, u8, u8) = (0xB4, 0x69, 0x5A);
const BRICK_SEAM_RGB: (u8, u8, u8) = (0x6A, 0x3A, 0x2A);
const STONE_FILL_RGB: (u8, u8, u8) = (0x9A, 0x8E, 0x80);
const STONE_SEAM_RGB: (u8, u8, u8) = (0x4A, 0x3E, 0x35);


struct WallRng {
    inner: SplitMix64,
}

impl WallRng {
    fn new(seed: u64) -> Self {
        Self { inner: SplitMix64::from_seed(seed) }
    }

    fn uniform(&mut self, lo: f32, hi: f32) -> f32 {
        let u = self.inner.next_u64();
        let unit = (u as f64) / 18446744073709551616.0_f64;
        lo + (hi - lo) * (unit as f32)
    }
}


fn rgb_paint(rgb: (u8, u8, u8)) -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(rgb.0, rgb.1, rgb.2, 255));
    p.anti_alias = true;
    p
}

fn thin_stroke() -> Stroke {
    let mut s = Stroke::default();
    s.width = STROKE_WIDTH;
    s.line_cap = LineCap::Butt;
    s
}


fn material_palette(material: WallMaterial) -> ((u8, u8, u8), (u8, u8, u8)) {
    if material == WallMaterial::Brick {
        (BRICK_FILL_RGB, BRICK_SEAM_RGB)
    } else {
        (STONE_FILL_RGB, STONE_SEAM_RGB)
    }
}


/// Build a rounded-rect path with corner radius `r`. Mirrors the
/// SVG `<rect rx="r" ry="r">` shape resvg renders; cubic-bezier
/// quarter-circles use the standard control distance c ≈ 0.5523r.
fn rounded_rect_path(
    x: f32, y: f32, w: f32, h: f32, r: f32,
) -> Option<tiny_skia::Path> {
    let r = r.min(w / 2.0).min(h / 2.0).max(0.0);
    let c = r * 0.5522847498307933; // 4 * (sqrt(2) - 1) / 3
    let mut pb = PathBuilder::new();
    if r < 1e-3 {
        pb.move_to(x, y);
        pb.line_to(x + w, y);
        pb.line_to(x + w, y + h);
        pb.line_to(x, y + h);
        pb.close();
    } else {
        pb.move_to(x + r, y);
        pb.line_to(x + w - r, y);
        pb.cubic_to(
            x + w - r + c, y,
            x + w, y + r - c,
            x + w, y + r,
        );
        pb.line_to(x + w, y + h - r);
        pb.cubic_to(
            x + w, y + h - r + c,
            x + w - r + c, y + h,
            x + w - r, y + h,
        );
        pb.line_to(x + r, y + h);
        pb.cubic_to(
            x + r - c, y + h,
            x, y + h - r + c,
            x, y + h - r,
        );
        pb.line_to(x, y + r);
        pb.cubic_to(
            x, y + r - c,
            x + r - c, y,
            x + r, y,
        );
        pb.close();
    }
    pb.finish()
}


fn paint_rounded_rect(
    x: f32, y: f32, w: f32, h: f32,
    fill_rgb: (u8, u8, u8), seam_rgb: (u8, u8, u8),
    transform: Transform,
    ctx: &mut RasterCtx<'_>,
) {
    let path = match rounded_rect_path(x, y, w, h, CORNER_RADIUS) {
        Some(p) => p,
        None => return,
    };
    let fill = rgb_paint(fill_rgb);
    let seam = rgb_paint(seam_rgb);
    let stroke = thin_stroke();
    ctx.pixmap.fill_path(
        &path, &fill, FillRule::Winding, transform, None,
    );
    ctx.pixmap.stroke_path(
        &path, &seam, &stroke, transform, None,
    );
}


fn render_ortho_run(
    x0: f32, y0: f32, x1: f32, y1: f32,
    horizontal: bool,
    fill_rgb: (u8, u8, u8), seam_rgb: (u8, u8, u8),
    rng: &mut WallRng,
    ctx: &mut RasterCtx<'_>,
) {
    let run_len = if horizontal { (x1 - x0).abs() } else { (y1 - y0).abs() };
    let run_start = if horizontal { x0.min(x1) } else { y0.min(y1) };
    let perp_start = if horizontal { y0 } else { x0 } - WALL_THICKNESS / 2.0;
    let strip_thick = WALL_THICKNESS / (STRIP_COUNT as f32);
    for idx in 0..STRIP_COUNT {
        let perp = perp_start + (idx as f32) * strip_thick;
        let mut pos = STRIP_OFFSETS[idx as usize].max(0.0);
        while pos < run_len {
            let mut width = MEAN_WIDTH * rng.uniform(WIDTH_LOW, WIDTH_HIGH);
            width = width.min(run_len - pos);
            let (rx, ry, rw, rh) = if horizontal {
                (run_start + pos, perp, width, strip_thick)
            } else {
                (perp, run_start + pos, strip_thick, width)
            };
            paint_rounded_rect(
                rx, ry, rw, rh,
                fill_rgb, seam_rgb, ctx.transform, ctx,
            );
            pos += width;
        }
    }
}

fn render_diagonal_run(
    x0: f32, y0: f32, x1: f32, y1: f32,
    fill_rgb: (u8, u8, u8), seam_rgb: (u8, u8, u8),
    rng: &mut WallRng,
    ctx: &mut RasterCtx<'_>,
) {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let run_len = (dx * dx + dy * dy).sqrt();
    let angle_deg = dy.atan2(dx).to_degrees();
    let strip_thick = WALL_THICKNESS / (STRIP_COUNT as f32);
    // `transform = outer * translate(x0, y0) * rotate(angle)` so
    // the canonical horizontal canvas units land at the run start
    // rotated to match the edge direction.
    let local = Transform::from_translate(x0, y0)
        .pre_concat(Transform::from_rotate(angle_deg));
    let local_transform = ctx.transform.pre_concat(local);
    for idx in 0..STRIP_COUNT {
        let perp = -WALL_THICKNESS / 2.0 + (idx as f32) * strip_thick;
        let mut pos = STRIP_OFFSETS[idx as usize].max(0.0);
        while pos < run_len {
            let mut width = MEAN_WIDTH * rng.uniform(WIDTH_LOW, WIDTH_HIGH);
            width = width.min(run_len - pos);
            paint_rounded_rect(
                pos, perp, width, strip_thick,
                fill_rgb, seam_rgb, local_transform, ctx,
            );
            pos += width;
        }
    }
}


fn polygon_coords(region: &Region<'_>) -> Vec<(f32, f32)> {
    let polygon = match region.polygon() {
        Some(p) => p,
        None => return Vec::new(),
    };
    let paths = match polygon.paths() {
        Some(p) => p,
        None => return Vec::new(),
    };
    paths.iter().map(|v| (v.x(), v.y())).collect()
}

fn find_region<'a>(
    fir: &FloorIR<'a>, region_ref: &str,
) -> Option<Region<'a>> {
    let regions = fir.regions()?;
    regions.iter().find(|r| r.id() == region_ref)
}


pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let _ = PI;  // keep import (stays used when atan2 lands).
    let op: BuildingExteriorWallOp = match entry.op_as_building_exterior_wall_op() {
        Some(o) => o,
        None => return,
    };
    let region_ref = match op.region_ref() {
        Some(r) => r,
        None => return,
    };
    let region = match find_region(fir, region_ref) {
        Some(r) => r,
        None => return,
    };
    let polygon = polygon_coords(&region);
    let n = polygon.len();
    if n < 3 {
        return;
    }
    let (fill_rgb, seam_rgb) = material_palette(op.material());
    let rng_seed = op.rng_seed();
    let ext = WALL_THICKNESS / 2.0;
    for i in 0..n {
        let (ax, ay) = polygon[i];
        let (bx, by) = polygon[(i + 1) % n];
        let dx = bx - ax;
        let dy = by - ay;
        let length = (dx * dx + dy * dy).sqrt();
        if length < 1e-6 {
            continue;
        }
        let ux = dx / length;
        let uy = dy / length;
        let ax_ext = ax - ux * ext;
        let ay_ext = ay - uy * ext;
        let bx_ext = bx + ux * ext;
        let by_ext = by + uy * ext;
        let mut rng = WallRng::new(rng_seed.wrapping_add(i as u64));
        let horizontal = (by_ext - ay_ext).abs() < 1e-6
            && (bx_ext - ax_ext).abs() > 1e-6;
        let vertical = (bx_ext - ax_ext).abs() < 1e-6
            && (by_ext - ay_ext).abs() > 1e-6;
        if horizontal || vertical {
            render_ortho_run(
                ax_ext, ay_ext, bx_ext, by_ext, horizontal,
                fill_rgb, seam_rgb, &mut rng, ctx,
            );
        } else {
            render_diagonal_run(
                ax_ext, ay_ext, bx_ext, by_ext,
                fill_rgb, seam_rgb, &mut rng, ctx,
            );
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rounded_rect_path_finishes_for_normal_dimensions() {
        let p = rounded_rect_path(0.0, 0.0, 12.0, 4.0, 1.2);
        assert!(p.is_some());
    }

    #[test]
    fn rounded_rect_path_collapses_to_square_on_zero_radius() {
        let p = rounded_rect_path(0.0, 0.0, 4.0, 4.0, 0.0);
        assert!(p.is_some());
    }

    #[test]
    fn material_palette_brick_vs_stone() {
        let (b_fill, b_seam) = material_palette(WallMaterial::Brick);
        assert_eq!(b_fill, BRICK_FILL_RGB);
        assert_eq!(b_seam, BRICK_SEAM_RGB);
        let (s_fill, _) = material_palette(WallMaterial::Stone);
        assert_eq!(s_fill, STONE_FILL_RGB);
    }
}
