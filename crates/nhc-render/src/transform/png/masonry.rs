//! Masonry running-bond chain painter for the v5 StrokeOp dispatch.
//!
//! Walks a wall outline polygon, applies the half-thickness vertex-
//! extension trick so adjacent edges overlap at corners, and renders
//! a 2-strip running-bond chain per edge with per-stone splitmix64
//! seeded width jitter. Used for ``WallTreatment::Masonry`` strokes
//! across the Stone family (Brick / Ashlar styles drive the palette
//! pick via :func:`substance_color`).
//!
//! Lifted from the deleted v4 ``transform/png/building_exterior_wall.rs``;
//! the algorithm is unchanged. The palette dispatch swap (v4
//! ``MasonryMaterial`` enum → v5 ``(family, style)`` via
//! ``substance_color``) is the only behavioural delta.

use crate::painter::material::{substance_color, Family, PaletteRole};
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke,
    Transform, Vec2,
};
use crate::rng::SplitMix64;

// Mirrors ``materials::STONE_BRICK`` — kept as a public constant so
// tests can pin a known palette without importing the emit-side
// constants module.
pub const STONE_BRICK_STYLE: u8 = 1;

const STRIP_COUNT: i32 = 2;
const MEAN_WIDTH: f32 = 12.0;
const WIDTH_LOW: f32 = 0.9;
const WIDTH_HIGH: f32 = 1.1;
const CORNER_RADIUS: f32 = 1.2;
const STROKE_WIDTH: f32 = 1.0;
const WALL_THICKNESS: f32 = 8.0;
const STRIP_OFFSETS: [f32; 2] = [0.0, MEAN_WIDTH / 2.0];


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


fn thin_stroke() -> Stroke {
    Stroke {
        width: STROKE_WIDTH,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    }
}


/// Build a rounded-rect path with corner radius `r`. Mirrors the
/// SVG ``<rect rx="r" ry="r">`` shape; cubic-bezier quarter-circles
/// use the standard control distance c ≈ 0.5523r.
fn rounded_rect_path(
    x: f32, y: f32, w: f32, h: f32, r: f32,
) -> Option<PathOps> {
    if w <= 0.0 || h <= 0.0 {
        return None;
    }
    let r = r.min(w / 2.0).min(h / 2.0).max(0.0);
    let c = r * 0.5522847498307933;
    let mut path = PathOps::new();
    if r < 1e-3 {
        path.move_to(Vec2::new(x, y));
        path.line_to(Vec2::new(x + w, y));
        path.line_to(Vec2::new(x + w, y + h));
        path.line_to(Vec2::new(x, y + h));
        path.close();
    } else {
        path.move_to(Vec2::new(x + r, y));
        path.line_to(Vec2::new(x + w - r, y));
        path.cubic_to(
            Vec2::new(x + w - r + c, y),
            Vec2::new(x + w, y + r - c),
            Vec2::new(x + w, y + r),
        );
        path.line_to(Vec2::new(x + w, y + h - r));
        path.cubic_to(
            Vec2::new(x + w, y + h - r + c),
            Vec2::new(x + w - r + c, y + h),
            Vec2::new(x + w - r, y + h),
        );
        path.line_to(Vec2::new(x + r, y + h));
        path.cubic_to(
            Vec2::new(x + r - c, y + h),
            Vec2::new(x, y + h - r + c),
            Vec2::new(x, y + h - r),
        );
        path.line_to(Vec2::new(x, y + r));
        path.cubic_to(
            Vec2::new(x, y + r - c),
            Vec2::new(x + r - c, y),
            Vec2::new(x + r, y),
        );
        path.close();
    }
    Some(path)
}


fn paint_rounded_rect(
    x: f32, y: f32, w: f32, h: f32,
    fill: &Paint, seam: &Paint,
    painter: &mut dyn Painter,
) {
    let path = match rounded_rect_path(x, y, w, h, CORNER_RADIUS) {
        Some(p) => p,
        None => return,
    };
    let stroke = thin_stroke();
    painter.fill_path(&path, fill, FillRule::Winding);
    painter.stroke_path(&path, seam, &stroke);
}


fn render_ortho_run(
    x0: f32, y0: f32, x1: f32, y1: f32,
    horizontal: bool,
    fill: &Paint, seam: &Paint,
    rng: &mut WallRng,
    painter: &mut dyn Painter,
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
            paint_rounded_rect(rx, ry, rw, rh, fill, seam, painter);
            pos += width;
        }
    }
}

fn render_diagonal_run(
    x0: f32, y0: f32, x1: f32, y1: f32,
    fill: &Paint, seam: &Paint,
    rng: &mut WallRng,
    painter: &mut dyn Painter,
) {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let run_len = (dx * dx + dy * dy).sqrt();
    let angle_rad = dy.atan2(dx);
    let strip_thick = WALL_THICKNESS / (STRIP_COUNT as f32);
    painter.push_transform(Transform::translate(x0, y0));
    painter.push_transform(Transform::rotate(angle_rad));
    for idx in 0..STRIP_COUNT {
        let perp = -WALL_THICKNESS / 2.0 + (idx as f32) * strip_thick;
        let mut pos = STRIP_OFFSETS[idx as usize].max(0.0);
        while pos < run_len {
            let mut width = MEAN_WIDTH * rng.uniform(WIDTH_LOW, WIDTH_HIGH);
            width = width.min(run_len - pos);
            paint_rounded_rect(pos, perp, width, strip_thick, fill, seam, painter);
            pos += width;
        }
    }
    painter.pop_transform();
    painter.pop_transform();
}


/// Render a Masonry running-bond chain along each edge of `polygon`.
///
/// Adjacent edges overlap by half the wall thickness at each vertex
/// so corner stones paint fully. Per-edge RNG is splitmix64 seeded
/// with ``rng_seed + edge_idx``. ``family`` / ``style`` drive the
/// stone palette via ``substance_color`` (Base for fill, Shadow for
/// seam).
pub fn render_masonry_polygon(
    polygon: &[(f32, f32)],
    family: Family,
    style: u8,
    rng_seed: u64,
    painter: &mut dyn Painter,
) {
    let n = polygon.len();
    if n < 3 {
        return;
    }
    let fill_color: Color = substance_color(family, style, 0, PaletteRole::Base);
    let seam_color: Color = substance_color(family, style, 0, PaletteRole::Shadow);
    let fill = Paint::solid(fill_color);
    let seam = Paint::solid(seam_color);
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
                &fill, &seam, &mut rng, painter,
            );
        } else {
            render_diagonal_run(
                ax_ext, ay_ext, bx_ext, by_ext,
                &fill, &seam, &mut rng, painter,
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
    fn rounded_rect_path_rejects_zero_size() {
        assert!(rounded_rect_path(0.0, 0.0, 0.0, 4.0, 0.5).is_none());
        assert!(rounded_rect_path(0.0, 0.0, 4.0, 0.0, 0.5).is_none());
    }
}
