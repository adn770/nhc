//! Site enclosure chain helpers shared by the ExteriorWallOp dispatch.
//!
//! Walks a closed polygon, applies per-edge cut spans (gates), and
//! dispatches each open sub-segment to the Palisade circle pass or the
//! Fortification battlement chain. Per-edge palisade RNG is splitmix64
//! seeded with `rng_seed + edge_idx`. Used for ``WallStyle::Palisade``
//! and ``WallStyle::FortificationMerlon`` styles.
//!
//! Phase 2.15h — ported from direct `tiny_skia::Pixmap` access onto the
//! [`Painter`] trait. The Diamond corner's per-shape rotation around
//! `(x, y)` is now expressed via [`Painter::push_transform`] /
//! [`Painter::pop_transform`] using `Transform::rotate_around`.

use std::f32::consts::SQRT_2;

use crate::ir::WallStyle;
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Rect, Stroke,
    Transform, Vec2,
};
use crate::rng::SplitMix64;

/// Discriminator passed to [`render_enclosure_polygon`]: collapses the
/// two enclosure-bearing WallStyle variants into a 2-element enum.
#[derive(Copy, Clone, Eq, PartialEq, Debug)]
pub(super) enum EnclosureKind {
    Palisade,
    Fortification,
}

impl EnclosureKind {
    pub(super) fn from_wall_style(style: WallStyle) -> Option<Self> {
        match style {
            WallStyle::Palisade => Some(Self::Palisade),
            WallStyle::FortificationMerlon => Some(Self::Fortification),
            _ => None,
        }
    }
}


// ── Fortification (battlement) constants ──────────────────────


const FORTIF_STROKE_RGB: (u8, u8, u8) = (0x1A, 0x1A, 0x1A);
const FORTIF_STROKE_WIDTH: f32 = 0.8;
const FORTIF_MERLON_RGB: (u8, u8, u8) = (0xD8, 0xD8, 0xD8);
const FORTIF_CRENEL_RGB: (u8, u8, u8) = (0x00, 0x00, 0x00);
const FORTIF_CORNER_RGB: (u8, u8, u8) = (0x00, 0x00, 0x00);
const FORTIF_SIZE: f32 = 8.0;
const FORTIF_CORNER_SCALE: f32 = 3.0;


// ── Palisade constants ─────────────────────────────────────────


const PALI_FILL_RGB: (u8, u8, u8) = (0x8A, 0x5A, 0x2A);
const PALI_STROKE_RGB: (u8, u8, u8) = (0x4A, 0x2E, 0x1A);
const PALI_STROKE_WIDTH: f32 = 1.5;
const PALI_RADIUS_MIN: f32 = 3.0;
const PALI_RADIUS_MAX: f32 = 4.0;
const PALI_RADIUS_JITTER: f32 = 0.3;
const PALI_CIRCLE_STEP: f32 = 9.0;
const PALI_DOOR_LENGTH_PX: f32 = 64.0;


// ── Splitmix64-uniform helper (mirrors Python _SplitMix64) ─────


struct EncRng {
    inner: SplitMix64,
}

impl EncRng {
    fn new(seed: u64) -> Self {
        Self { inner: SplitMix64::from_seed(seed) }
    }

    fn uniform(&mut self, lo: f32, hi: f32) -> f32 {
        let u = self.inner.next_u64();
        let unit = (u as f64) / 18446744073709551616.0_f64;
        lo + (hi - lo) * (unit as f32)
    }
}


// ── Paint + stroke helpers ─────────────────────────────────────


fn rgb_paint(rgb: (u8, u8, u8), alpha: f32) -> Paint {
    Paint::solid(Color::rgba(rgb.0, rgb.1, rgb.2, alpha))
}

fn thin_stroke(width: f32) -> Stroke {
    Stroke {
        width,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    }
}


// ── Cut merging + sub-segment computation ─────────────────────


fn merge_cuts(mut cuts: Vec<(f32, f32)>) -> Vec<(f32, f32)> {
    if cuts.is_empty() {
        return cuts;
    }
    cuts.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    let mut merged: Vec<(f32, f32)> = vec![cuts[0]];
    for &(lo, hi) in &cuts[1..] {
        let last = merged.last_mut().unwrap();
        if lo <= last.1 {
            last.1 = last.1.max(hi);
        } else {
            merged.push((lo, hi));
        }
    }
    merged
}

fn subsegments(
    a: (f32, f32),
    b: (f32, f32),
    cuts: &[(f32, f32)],
) -> Vec<((f32, f32), (f32, f32))> {
    let at = |t: f32| -> (f32, f32) {
        (a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t)
    };
    if cuts.is_empty() {
        return vec![(a, b)];
    }
    let mut out = Vec::new();
    let mut prev = 0.0_f32;
    for &(lo, hi) in cuts {
        if lo > prev {
            out.push((at(prev), at(lo)));
        }
        prev = hi;
    }
    if prev < 1.0 {
        out.push((at(prev), at(1.0)));
    }
    out
}


// ── Fortification rect (centered) + battlement chain ──────────


/// Rect-stroked fill primitive used by the battlement chain. The
/// fill goes through `fill_rect` and the stroke through `stroke_path`
/// of an explicit closed-path so the join is identical to the legacy
/// `pb.move_to ... close ... stroke_path` rendering (a `stroke_rect`
/// would emit four segments via `tiny_skia`'s `push_rect` which, while
/// equivalent for axis-aligned rectangles, is held off until the SVG
/// painter ships in 2.16 to keep the diff parity-tight).
fn fortif_rect(
    cx: f32, cy: f32, w: f32, h: f32, fill_rgb: (u8, u8, u8),
    painter: &mut dyn Painter,
) {
    if w <= 0.0 || h <= 0.0 {
        return;
    }
    let fill = rgb_paint(fill_rgb, 1.0);
    painter.fill_rect(
        Rect::new(cx - w / 2.0, cy - h / 2.0, w, h),
        &fill,
    );
    let stroke = thin_stroke(FORTIF_STROKE_WIDTH);
    let stroke_paint = rgb_paint(FORTIF_STROKE_RGB, 1.0);
    let mut path = PathOps::new();
    path.move_to(Vec2::new(cx - w / 2.0, cy - h / 2.0));
    path.line_to(Vec2::new(cx + w / 2.0, cy - h / 2.0));
    path.line_to(Vec2::new(cx + w / 2.0, cy + h / 2.0));
    path.line_to(Vec2::new(cx - w / 2.0, cy + h / 2.0));
    path.close();
    painter.stroke_path(&path, &stroke_paint, &stroke);
}

fn centered_fortification_chain(
    a: (f32, f32), b: (f32, f32), painter: &mut dyn Painter,
) {
    let dx = b.0 - a.0;
    let dy = b.1 - a.1;
    let seg_len = (dx * dx + dy * dy).sqrt();
    if seg_len < 1e-6 {
        return;
    }
    let horizontal = dy.abs() < 1e-6 && dx.abs() > 1e-6;
    let vertical = dx.abs() < 1e-6 && dy.abs() > 1e-6;
    if !horizontal && !vertical {
        return;
    }
    let size = FORTIF_SIZE;
    let rect_len = size * SQRT_2;  // FORTIFICATION_RATIO
    let k = ((seg_len + size) / (rect_len + size)) as i32;
    if k < 1 {
        return;
    }
    let used = (k as f32) * rect_len + ((k - 1) as f32) * size;
    let offset = (seg_len - used) / 2.0;
    let ux = dx / seg_len;
    let uy = dy / seg_len;
    let mut pos = offset;
    let mut alternate: i32 = 1;  // start with crenel
    for _ in 0..(2 * k - 1) {
        let length = if alternate == 0 { size } else { rect_len };
        let cx = a.0 + ux * (pos + length / 2.0);
        let cy = a.1 + uy * (pos + length / 2.0);
        let (shape_w, shape_h) = if horizontal {
            (length, size)
        } else {
            (size, length)
        };
        let fill_rgb = if alternate == 0 {
            FORTIF_MERLON_RGB
        } else {
            FORTIF_CRENEL_RGB
        };
        fortif_rect(cx, cy, shape_w, shape_h, fill_rgb, painter);
        pos += length;
        alternate = 1 - alternate;
    }
}


// ── Corner shape (Fortification only) ─────────────────────────


fn corner_shape(
    x: f32, y: f32, corner_style: i8, painter: &mut dyn Painter,
) {
    // CornerStyle: Merlon=0, Diamond=1, Tower=2.
    let size = FORTIF_SIZE * FORTIF_CORNER_SCALE;
    if corner_style == 1 {
        // Diamond — 45° rotated black square. Legacy used
        // `tiny_skia::Transform::from_rotate_at(45.0, x, y)` (degrees);
        // the painter equivalent is `rotate_around(45°→radians, x, y)`.
        let half = size / 2.0;
        if half <= 0.0 {
            return;
        }
        let fill = rgb_paint(FORTIF_CORNER_RGB, 1.0);
        let stroke = thin_stroke(FORTIF_STROKE_WIDTH);
        let stroke_paint = rgb_paint(FORTIF_STROKE_RGB, 1.0);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(x - half, y - half));
        path.line_to(Vec2::new(x + half, y - half));
        path.line_to(Vec2::new(x + half, y + half));
        path.line_to(Vec2::new(x - half, y + half));
        path.close();
        painter.push_transform(Transform::rotate_around(
            45.0_f32.to_radians(),
            x,
            y,
        ));
        painter.fill_rect(
            Rect::new(x - half, y - half, size, size),
            &fill,
        );
        painter.stroke_path(&path, &stroke_paint, &stroke);
        painter.pop_transform();
        return;
    }
    // Merlon / Tower fallback: axis-aligned black square.
    fortif_rect(x, y, size, size, FORTIF_CORNER_RGB, painter);
}


// ── Palisade circles + door rect ──────────────────────────────


fn palisade_circles(
    points: &[(f32, f32)], rng: &mut EncRng, painter: &mut dyn Painter,
) {
    if points.len() < 2 {
        return;
    }
    let fill = rgb_paint(PALI_FILL_RGB, 1.0);
    let stroke = thin_stroke(PALI_STROKE_WIDTH);
    let stroke_paint = rgb_paint(PALI_STROKE_RGB, 1.0);
    let mut carry: f32 = 0.0;
    for i in 0..points.len() - 1 {
        let (ax, ay) = points[i];
        let (bx, by) = points[i + 1];
        let dx = bx - ax;
        let dy = by - ay;
        let seg_len = (dx * dx + dy * dy).sqrt();
        if seg_len < 1e-6 {
            continue;
        }
        let ux = dx / seg_len;
        let uy = dy / seg_len;
        let mut t = carry;
        while t < seg_len {
            let cx = ax + ux * t;
            let cy = ay + uy * t;
            let base_r = rng.uniform(PALI_RADIUS_MIN, PALI_RADIUS_MAX);
            let jitter = rng.uniform(-PALI_RADIUS_JITTER, PALI_RADIUS_JITTER);
            let r = (base_r + jitter).max(0.1);
            painter.fill_circle(cx, cy, r, &fill);
            // Stroke via an explicit circle-as-cubic-Bézier path so
            // the trait surface stays narrow (no `stroke_circle`).
            let circle_path = circle_path_ops(cx, cy, r);
            painter.stroke_path(&circle_path, &stroke_paint, &stroke);
            t += PALI_CIRCLE_STEP;
        }
        carry = (t - seg_len).max(0.0);
    }
}

fn palisade_door_rect(
    a: (f32, f32), b: (f32, f32), t_center: f32,
    painter: &mut dyn Painter,
) {
    let dx = b.0 - a.0;
    let dy = b.1 - a.1;
    let cx = a.0 + dx * t_center;
    let cy = a.1 + dy * t_center;
    let horizontal = dy.abs() < 1e-6;
    let thickness = 2.0 * PALI_RADIUS_MAX;
    let (x, y, w, h) = if horizontal {
        (
            cx - PALI_DOOR_LENGTH_PX / 2.0,
            cy - thickness / 2.0,
            PALI_DOOR_LENGTH_PX,
            thickness,
        )
    } else {
        (
            cx - thickness / 2.0,
            cy - PALI_DOOR_LENGTH_PX / 2.0,
            thickness,
            PALI_DOOR_LENGTH_PX,
        )
    };
    if w <= 0.0 || h <= 0.0 {
        return;
    }
    let fill = rgb_paint(PALI_FILL_RGB, 1.0);
    painter.fill_rect(Rect::new(x, y, w, h), &fill);
    let stroke = thin_stroke(PALI_STROKE_WIDTH);
    let stroke_paint = rgb_paint(PALI_STROKE_RGB, 1.0);
    let mut path = PathOps::new();
    path.move_to(Vec2::new(x, y));
    path.line_to(Vec2::new(x + w, y));
    path.line_to(Vec2::new(x + w, y + h));
    path.line_to(Vec2::new(x, y + h));
    path.close();
    painter.stroke_path(&path, &stroke_paint, &stroke);
}


/// Emit a circle as a 4-cubic-Bezier closed [`PathOps`]. Mirrors the
/// `tiny_skia::PathBuilder::push_circle` shape so the stroked outline
/// of a palisade post matches the pre-port pixel layout.
fn circle_path_ops(cx: f32, cy: f32, r: f32) -> PathOps {
    const KAPPA: f32 = 0.5522847498307933; // 4 * (sqrt(2) - 1) / 3
    let k = r * KAPPA;
    let mut path = PathOps::new();
    path.move_to(Vec2::new(cx + r, cy));
    path.cubic_to(
        Vec2::new(cx + r, cy + k),
        Vec2::new(cx + k, cy + r),
        Vec2::new(cx, cy + r),
    );
    path.cubic_to(
        Vec2::new(cx - k, cy + r),
        Vec2::new(cx - r, cy + k),
        Vec2::new(cx - r, cy),
    );
    path.cubic_to(
        Vec2::new(cx - r, cy - k),
        Vec2::new(cx - k, cy - r),
        Vec2::new(cx, cy - r),
    );
    path.cubic_to(
        Vec2::new(cx + k, cy - r),
        Vec2::new(cx + r, cy - k),
        Vec2::new(cx + r, cy),
    );
    path.close();
    path
}


// ── Render entry ───────────────────────────────────────────────


/// Render a Palisade or Fortification chain along `polygon` edges.
/// Used by the ExteriorWallOp dispatch's Palisade /
/// FortificationMerlon branches.
pub(super) fn render_enclosure_polygon(
    polygon: &[(f32, f32)],
    by_edge: &[Vec<(f32, f32)>],
    midpoints: &[Vec<f32>],
    style: EnclosureKind,
    corner_style: i8,
    rng_seed: u64,
    painter: &mut dyn Painter,
) {
    let n = polygon.len();
    if n < 3 {
        return;
    }
    if style == EnclosureKind::Palisade {
        for i in 0..n {
            let a = polygon[i];
            let b = polygon[(i + 1) % n];
            let cuts = merge_cuts(by_edge[i].clone());
            let subs = subsegments(a, b, &cuts);
            let mut edge_rng = EncRng::new(rng_seed.wrapping_add(i as u64));
            for (sa, sb) in &subs {
                palisade_circles(&[*sa, *sb], &mut edge_rng, painter);
            }
            for &t_center in &midpoints[i] {
                palisade_door_rect(a, b, t_center, painter);
            }
        }
        return;
    }

    // Fortification: inset edges, centered chains, then corner
    // shapes drawn last so they sit on top.
    let inset = FORTIF_SIZE / 2.0;
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        let dx = b.0 - a.0;
        let dy = b.1 - a.1;
        let edge_len = (dx * dx + dy * dy).sqrt();
        if edge_len <= 2.0 * inset + 1e-6 {
            continue;
        }
        let ux = dx / edge_len;
        let uy = dy / edge_len;
        let a_in = (a.0 + ux * inset, a.1 + uy * inset);
        let b_in = (b.0 - ux * inset, b.1 - uy * inset);
        let cuts = merge_cuts(by_edge[i].clone());
        let t_inset = inset / edge_len;
        let denom = 1.0 - 2.0 * t_inset;
        let inset_cuts: Vec<(f32, f32)> = if denom > 1e-9 {
            cuts.into_iter()
                .map(|(lo, hi)| {
                    let new_lo = ((lo - t_inset) / denom).max(0.0);
                    let new_hi = ((hi - t_inset) / denom).min(1.0);
                    (new_lo, new_hi)
                })
                .filter(|(lo, hi)| hi > lo)
                .collect()
        } else {
            Vec::new()
        };
        let subs = subsegments(a_in, b_in, &inset_cuts);
        for (sa, sb) in subs {
            centered_fortification_chain(sa, sb, painter);
        }
    }
    // Wood gate visuals (legacy fortification drew nothing here).
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        for &t_center in &midpoints[i] {
            palisade_door_rect(a, b, t_center, painter);
        }
    }
    for &(x, y) in polygon {
        corner_shape(x, y, corner_style, painter);
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merge_cuts_dedupes_overlapping_spans() {
        let merged = merge_cuts(vec![(0.1, 0.4), (0.3, 0.6), (0.7, 0.9)]);
        assert_eq!(merged, vec![(0.1, 0.6), (0.7, 0.9)]);
    }

    #[test]
    fn subsegments_with_no_cuts_returns_full_segment() {
        let subs = subsegments((0.0, 0.0), (10.0, 0.0), &[]);
        assert_eq!(subs, vec![((0.0, 0.0), (10.0, 0.0))]);
    }

    #[test]
    fn subsegments_splits_around_cut() {
        let subs = subsegments((0.0, 0.0), (10.0, 0.0), &[(0.4, 0.6)]);
        assert_eq!(
            subs,
            vec![
                ((0.0, 0.0), (4.0, 0.0)),
                ((6.0, 0.0), (10.0, 0.0)),
            ]
        );
    }

    #[test]
    fn enc_rng_first_call_matches_python_reference() {
        // Cross-check: SplitMix64::from_seed(1234).next_u64() must
        // equal _SplitMix64(1234).next_u64() on the Python side
        // — both compute mix(1234 + GOLDEN_GAMMA).
        let mut rng = EncRng::new(1234);
        let u = rng.inner.next_u64();
        // Reference value computed via Python:
        //   _SplitMix64(1234).next_u64() == 0xbb0cf61b2f181cdb
        assert_eq!(u, 0xbb0cf61b2f181cdb);
    }
}
