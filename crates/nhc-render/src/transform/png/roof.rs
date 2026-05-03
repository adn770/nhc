//! RoofOp rasterisation — Phase 8.1c.2 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors the Python reference at `_draw_roof_from_ir` in
//! `nhc/rendering/ir_to_svg.py`. Both rasterisers walk the same
//! splitmix64 stream seeded with `RoofOp.rng_seed` so shingle
//! widths and shade picks agree value-for-value; the SVG path
//! emits clip-path-bounded fragments and the tiny-skia path uses
//! a polygon `Mask` for the same clipping. The synthetic-IR PSNR
//! gate at `tests/unit/test_ir_png_parity.py` exercises both paths
//! against a tiny-skia-rendered `reference.png` at PSNR > 40 dB.

use tiny_skia::{
    Color, FillRule, LineCap, Mask, Paint, PathBuilder, Rect, Stroke,
};

use crate::ir::{FloorIR, OpEntry, Region, RoofOp};
use crate::rng::SplitMix64;

use super::polygon_path::build_polygon_path;
use super::RasterCtx;


// ── Constants ───────────────────────────────────────────────────
// Mirror nhc/rendering/ir_to_svg.py's _ROOF_* constants
// value-for-value. A drift here would visibly skew the synthetic-
// IR PSNR gate; values are pinned by the parity test.

const SHADOW_FACTOR: f32 = 0.5;
const SHINGLE_WIDTH: f32 = 14.0;
const SHINGLE_HEIGHT: f32 = 5.0;
const SHINGLE_JITTER: f32 = 2.0;
const RIDGE_WIDTH: f32 = 1.5;
const SHINGLE_STROKE_OPACITY: f32 = 0.2;
const SHINGLE_STROKE_WIDTH: f32 = 0.3;


// ── Splitmix64 helper layer matching the Python RNG surface ────


struct RoofRng {
    inner: SplitMix64,
}

impl RoofRng {
    fn new(seed: u64) -> Self {
        Self { inner: SplitMix64::from_seed(seed) }
    }

    fn uniform(&mut self, lo: f32, hi: f32) -> f32 {
        // Match Python's `next_u64() / 2**64` → [0, 1) mapping
        // exactly: 64-bit u64 cast to f64 (lossy at the top end,
        // but the Python side has the same loss), divide by 2^64.
        let u = self.inner.next_u64();
        let unit = (u as f64) / 18446744073709551616.0_f64;
        lo + (hi - lo) * (unit as f32)
    }

    fn choice<'a, T>(&mut self, seq: &'a [T]) -> &'a T {
        let u = self.inner.next_u64();
        &seq[(u as usize) % seq.len()]
    }
}


// ── Hex parsing + shade palette ────────────────────────────────


fn parse_hex(hx: &str) -> Option<(u8, u8, u8)> {
    let s = hx.strip_prefix('#').unwrap_or(hx);
    if s.len() < 6 {
        return None;
    }
    let r = u8::from_str_radix(&s[0..2], 16).ok()?;
    let g = u8::from_str_radix(&s[2..4], 16).ok()?;
    let b = u8::from_str_radix(&s[4..6], 16).ok()?;
    Some((r, g, b))
}

fn scale_rgb(rgb: (u8, u8, u8), factor: f32) -> (u8, u8, u8) {
    let s = |c: u8| -> u8 {
        (c as f32 * factor).clamp(0.0, 255.0) as u8
    };
    (s(rgb.0), s(rgb.1), s(rgb.2))
}

fn shade_palette(tint: &str, sunlit: bool) -> [(u8, u8, u8); 3] {
    let base = parse_hex(tint).unwrap_or((0x8A, 0x7A, 0x5A));
    let factors: [f32; 3] = if sunlit {
        [1.15, 1.00, 0.88]
    } else {
        let c = SHADOW_FACTOR;
        [c * 1.15, c, c * 0.88]
    };
    [
        scale_rgb(base, factors[0]),
        scale_rgb(base, factors[1]),
        scale_rgb(base, factors[2]),
    ]
}


// ── Geometry mode picker ───────────────────────────────────────


enum Mode {
    Gable,
    Pyramid,
}

fn geometry_mode(shape_tag: &str, polygon: &[(f32, f32)]) -> Mode {
    if shape_tag.starts_with("l_shape") {
        return Mode::Gable;
    }
    if shape_tag == "rect" {
        let (mut min_x, mut max_x) = (f32::INFINITY, f32::NEG_INFINITY);
        let (mut min_y, mut max_y) = (f32::INFINITY, f32::NEG_INFINITY);
        for &(x, y) in polygon {
            if x < min_x { min_x = x; }
            if x > max_x { max_x = x; }
            if y < min_y { min_y = y; }
            if y > max_y { max_y = y; }
        }
        let w = max_x - min_x;
        let h = max_y - min_y;
        return if (w - h).abs() < 1e-6 {
            Mode::Pyramid
        } else {
            Mode::Gable
        };
    }
    Mode::Pyramid // octagon / circle / unknown
}


// ── Paint helpers ──────────────────────────────────────────────


fn rgb_paint(rgb: (u8, u8, u8), alpha: f32) -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(rgb.0, rgb.1, rgb.2, (alpha * 255.0) as u8));
    p.anti_alias = true;
    p
}

fn ridge_stroke() -> Stroke {
    let mut s = Stroke::default();
    s.width = RIDGE_WIDTH;
    s.line_cap = LineCap::Butt;
    s
}

fn shingle_stroke() -> Stroke {
    let mut s = Stroke::default();
    s.width = SHINGLE_STROKE_WIDTH;
    s.line_cap = LineCap::Butt;
    s
}


// ── Shingle running-bond + gable + pyramid ─────────────────────


fn draw_shingle_region(
    x: f32, y: f32, w: f32, h: f32,
    shades: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
    vertical_courses: bool,
) {
    let stroke = shingle_stroke();
    let stroke_paint = rgb_paint((0, 0, 0), SHINGLE_STROKE_OPACITY);
    if vertical_courses {
        // Transposed layout — columns instead of rows; long axis
        // vertical. Used for horizontal-ridge gables so the
        // courses run perpendicular to the ridge. Mirror of the
        // Python ``_roof_shingle_region(vertical_courses=True)``
        // branch.
        let mut col = 0;
        let mut cx = x;
        while cx < x + w {
            let mut sy = if col % 2 == 1 { y - SHINGLE_WIDTH / 2.0 } else { y };
            while sy < y + h {
                let sw_j = SHINGLE_WIDTH + rng.uniform(-SHINGLE_JITTER, SHINGLE_JITTER);
                let shade = *rng.choice(shades);
                let vy = sy.max(y);
                let vb = (sy + sw_j).min(y + h);
                let vh = vb - vy;
                if vh > 0.0 {
                    if let Some(rect) = Rect::from_xywh(cx, vy, SHINGLE_HEIGHT, vh) {
                        let fill = rgb_paint(shade, 1.0);
                        ctx.pixmap.fill_rect(rect, &fill, ctx.transform, mask);
                        let mut pb = PathBuilder::new();
                        pb.move_to(cx, vy);
                        pb.line_to(cx + SHINGLE_HEIGHT, vy);
                        pb.line_to(cx + SHINGLE_HEIGHT, vy + vh);
                        pb.line_to(cx, vy + vh);
                        pb.close();
                        if let Some(path) = pb.finish() {
                            ctx.pixmap.stroke_path(
                                &path, &stroke_paint, &stroke,
                                ctx.transform, mask,
                            );
                        }
                    }
                }
                sy += sw_j;
            }
            cx += SHINGLE_HEIGHT;
            col += 1;
        }
        return;
    }
    let mut row = 0;
    let mut cy = y;
    while cy < y + h {
        let mut sx = if row % 2 == 1 { x - SHINGLE_WIDTH / 2.0 } else { x };
        while sx < x + w {
            let sw_j = SHINGLE_WIDTH + rng.uniform(-SHINGLE_JITTER, SHINGLE_JITTER);
            let shade = *rng.choice(shades);
            // Clamp the shingle's drawn rect to the region bbox so
            // it never bleeds past a vertical ridge into the
            // opposite-shaded side of a gable. Mirror of the
            // Python ``_roof_shingle_region`` clamp.
            let vx = sx.max(x);
            let vr = (sx + sw_j).min(x + w);
            let vw = vr - vx;
            if vw > 0.0 {
                if let Some(rect) = Rect::from_xywh(vx, cy, vw, SHINGLE_HEIGHT) {
                    let fill = rgb_paint(shade, 1.0);
                    ctx.pixmap.fill_rect(rect, &fill, ctx.transform, mask);
                    let mut pb = PathBuilder::new();
                    pb.move_to(vx, cy);
                    pb.line_to(vx + vw, cy);
                    pb.line_to(vx + vw, cy + SHINGLE_HEIGHT);
                    pb.line_to(vx, cy + SHINGLE_HEIGHT);
                    pb.close();
                    if let Some(path) = pb.finish() {
                        ctx.pixmap.stroke_path(
                            &path, &stroke_paint, &stroke,
                            ctx.transform, mask,
                        );
                    }
                }
            }
            sx += sw_j;
        }
        cy += SHINGLE_HEIGHT;
        row += 1;
    }
}

fn draw_gable_sides(
    px: f32, py: f32, pw: f32, ph: f32,
    horizontal: bool,
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let ridge_paint = rgb_paint((0, 0, 0), 1.0);
    let stroke = ridge_stroke();
    if horizontal {
        // Horizontal ridge — vertical courses (long axis runs
        // perpendicular to the ridge).
        draw_shingle_region(px, py, pw, ph / 2.0, shadow, rng, mask, ctx, true);
        draw_shingle_region(
            px, py + ph / 2.0, pw, ph / 2.0, sunlit, rng, mask, ctx, true,
        );
        let mut pb = PathBuilder::new();
        pb.move_to(px, py + ph / 2.0);
        pb.line_to(px + pw, py + ph / 2.0);
        if let Some(path) = pb.finish() {
            ctx.pixmap.stroke_path(
                &path, &ridge_paint, &stroke, ctx.transform, mask,
            );
        }
    } else {
        // Vertical ridge — horizontal courses (default).
        draw_shingle_region(px, py, pw / 2.0, ph, shadow, rng, mask, ctx, false);
        draw_shingle_region(
            px + pw / 2.0, py, pw / 2.0, ph, sunlit, rng, mask, ctx, false,
        );
        let mut pb = PathBuilder::new();
        pb.move_to(px + pw / 2.0, py);
        pb.line_to(px + pw / 2.0, py + ph);
        if let Some(path) = pb.finish() {
            ctx.pixmap.stroke_path(
                &path, &ridge_paint, &stroke, ctx.transform, mask,
            );
        }
    }
}

fn draw_pyramid_sides(
    polygon: &[(f32, f32)],
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let n = polygon.len();
    if n == 0 {
        return;
    }
    let cx = polygon.iter().map(|p| p.0).sum::<f32>() / n as f32;
    let cy = polygon.iter().map(|p| p.1).sum::<f32>() / n as f32;
    let stroke_paint = rgb_paint((0, 0, 0), SHINGLE_STROKE_OPACITY);
    let stroke = shingle_stroke();
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        let mx = (a.0 + b.0) / 2.0;
        let my = (a.1 + b.1) / 2.0;
        let is_shadow = my < cy - 1e-3 || (mx < cx - 1e-3 && my < cy + 1e-3);
        let palette = if is_shadow { shadow } else { sunlit };
        let fill_rgb = *rng.choice(palette);
        let mut pb = PathBuilder::new();
        pb.move_to(a.0, a.1);
        pb.line_to(b.0, b.1);
        pb.line_to(cx, cy);
        pb.close();
        if let Some(path) = pb.finish() {
            let fill = rgb_paint(fill_rgb, 1.0);
            ctx.pixmap.fill_path(
                &path, &fill, FillRule::Winding, ctx.transform, mask,
            );
            ctx.pixmap.stroke_path(
                &path, &stroke_paint, &stroke, ctx.transform, mask,
            );
        }
    }
    // Ridge spokes from centre to each polygon vertex.
    let ridge_paint = rgb_paint((0, 0, 0), 1.0);
    let ridge_stroke_def = ridge_stroke();
    let mut pb = PathBuilder::new();
    for &(vx, vy) in polygon {
        pb.move_to(cx, cy);
        pb.line_to(vx, vy);
    }
    if let Some(path) = pb.finish() {
        ctx.pixmap.stroke_path(
            &path, &ridge_paint, &ridge_stroke_def, ctx.transform, mask,
        );
    }
}


// ── Region lookup + dispatch entry ─────────────────────────────


fn find_region<'a>(
    fir: &FloorIR<'a>,
    region_ref: &str,
) -> Option<Region<'a>> {
    let regions = fir.regions()?;
    regions.iter().find(|r| r.id() == region_ref)
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

fn build_clip_mask(
    region: &Region<'_>,
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let polygon = region.polygon()?;
    let path = build_polygon_path(&polygon)?;
    let mut mask = Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&path, FillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}

/// Public dispatch entry. Registered against `Op::RoofOp` in
/// `super::op_handlers`.
pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op: RoofOp = match entry.op_as_roof_op() {
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
    if polygon.len() < 3 {
        return;
    }
    let shape_tag = region.shape_tag().unwrap_or("");
    let tint = op.tint().unwrap_or("#8A7A5A");
    let mut rng = RoofRng::new(op.rng_seed());
    let sunlit = shade_palette(tint, true);
    let shadow = shade_palette(tint, false);
    let mask = build_clip_mask(&region, ctx);
    let mode = geometry_mode(shape_tag, &polygon);
    let (mut min_x, mut max_x) = (f32::INFINITY, f32::NEG_INFINITY);
    let (mut min_y, mut max_y) = (f32::INFINITY, f32::NEG_INFINITY);
    for &(x, y) in &polygon {
        if x < min_x { min_x = x; }
        if x > max_x { max_x = x; }
        if y < min_y { min_y = y; }
        if y > max_y { max_y = y; }
    }
    let pw = max_x - min_x;
    let ph = max_y - min_y;
    match mode {
        Mode::Gable => draw_gable_sides(
            min_x, min_y, pw, ph, pw >= ph,
            &sunlit, &shadow, &mut rng, mask.as_ref(), ctx,
        ),
        Mode::Pyramid => draw_pyramid_sides(
            &polygon, &sunlit, &shadow, &mut rng, mask.as_ref(), ctx,
        ),
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_hex_handles_short_strings() {
        assert_eq!(parse_hex("#8A7A5A"), Some((0x8A, 0x7A, 0x5A)));
        assert_eq!(parse_hex("8A7A5A"), Some((0x8A, 0x7A, 0x5A)));
        assert_eq!(parse_hex("#"), None);
    }

    #[test]
    fn shade_palette_brackets_tint() {
        let p = shade_palette("#808080", true);
        // Sunlit factors are 1.15, 1.00, 0.88 — middle entry is
        // exactly the input tint.
        assert_eq!(p[1], (0x80, 0x80, 0x80));
        // Shadow side is darker — middle entry maps to 50% of input.
        let s = shade_palette("#808080", false);
        assert_eq!(s[1], (0x40, 0x40, 0x40));
    }

    #[test]
    fn geometry_mode_dispatches_by_shape_tag() {
        let square = vec![(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)];
        let wide = vec![(0.0, 0.0), (20.0, 0.0), (20.0, 5.0), (0.0, 5.0)];
        assert!(matches!(geometry_mode("rect", &square), Mode::Pyramid));
        assert!(matches!(geometry_mode("rect", &wide), Mode::Gable));
        assert!(matches!(geometry_mode("octagon", &square), Mode::Pyramid));
        assert!(matches!(geometry_mode("circle", &wide), Mode::Pyramid));
        assert!(matches!(geometry_mode("l_shape_nw", &square), Mode::Gable));
        assert!(matches!(geometry_mode("unknown", &square), Mode::Pyramid));
    }

    #[test]
    fn roof_rng_matches_python_first_call() {
        // Sentinel: SplitMix64::from_seed(123).next_u64() must
        // match Python's _SplitMix64(123).next_u64() in
        // ir_to_svg.py — both compute mix(123 + GOLDEN_GAMMA).
        let mut rng = RoofRng::new(123);
        let u = rng.inner.next_u64();
        // Reference value cross-checked against the Python helper.
        assert_eq!(u, 0xb4dc9bd462de412b);
    }
}
