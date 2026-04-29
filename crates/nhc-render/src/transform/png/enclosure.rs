//! EnclosureOp rasterisation — Phase 8.2c of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_enclosure_from_ir` in `nhc/rendering/ir_to_svg.py`
//! constant-for-constant. Walks the closed polygon, applies
//! per-edge gate cuts, and dispatches each open sub-segment on
//! `EnclosureStyle` (Palisade circles or Fortification battlement
//! chain). Per-edge palisade RNG is splitmix64 seeded with
//! `rng_seed + edge_idx`; both rasterisers consume the same
//! sequence so PSNR > 40 dB on the synthetic-IR gate.

use std::f32::consts::SQRT_2;

use tiny_skia::{
    Color, FillRule, LineCap, Paint, PathBuilder, Rect, Stroke, Transform,
};

use crate::ir::{EnclosureOp, EnclosureStyle, FloorIR, OpEntry};
use crate::rng::SplitMix64;

use super::RasterCtx;


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


fn rgb_paint(rgb: (u8, u8, u8), alpha: f32) -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(rgb.0, rgb.1, rgb.2, (alpha * 255.0) as u8));
    p.anti_alias = true;
    p
}

fn thin_stroke(width: f32) -> Stroke {
    let mut s = Stroke::default();
    s.width = width;
    s.line_cap = LineCap::Butt;
    s
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


fn fortif_rect(
    cx: f32, cy: f32, w: f32, h: f32, fill_rgb: (u8, u8, u8),
    ctx: &mut RasterCtx<'_>,
) {
    let rect = match Rect::from_xywh(cx - w / 2.0, cy - h / 2.0, w, h) {
        Some(r) => r,
        None => return,
    };
    let fill = rgb_paint(fill_rgb, 1.0);
    ctx.pixmap.fill_rect(rect, &fill, ctx.transform, None);
    let stroke = thin_stroke(FORTIF_STROKE_WIDTH);
    let stroke_paint = rgb_paint(FORTIF_STROKE_RGB, 1.0);
    let mut pb = PathBuilder::new();
    pb.move_to(cx - w / 2.0, cy - h / 2.0);
    pb.line_to(cx + w / 2.0, cy - h / 2.0);
    pb.line_to(cx + w / 2.0, cy + h / 2.0);
    pb.line_to(cx - w / 2.0, cy + h / 2.0);
    pb.close();
    if let Some(path) = pb.finish() {
        ctx.pixmap.stroke_path(
            &path, &stroke_paint, &stroke, ctx.transform, None,
        );
    }
}

fn centered_fortification_chain(
    a: (f32, f32), b: (f32, f32), ctx: &mut RasterCtx<'_>,
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
        fortif_rect(cx, cy, shape_w, shape_h, fill_rgb, ctx);
        pos += length;
        alternate = 1 - alternate;
    }
}


// ── Corner shape (Fortification only) ─────────────────────────


fn corner_shape(
    x: f32, y: f32, corner_style: i8, ctx: &mut RasterCtx<'_>,
) {
    // CornerStyle: Merlon=0, Diamond=1, Tower=2.
    let size = FORTIF_SIZE * FORTIF_CORNER_SCALE;
    if corner_style == 1 {
        // Diamond — 45° rotated black square.
        let half = size / 2.0;
        let rect = match Rect::from_xywh(x - half, y - half, size, size) {
            Some(r) => r,
            None => return,
        };
        let fill = rgb_paint(FORTIF_CORNER_RGB, 1.0);
        let rotated = ctx.transform.pre_concat(
            Transform::from_rotate_at(45.0, x, y),
        );
        ctx.pixmap.fill_rect(rect, &fill, rotated, None);
        let stroke = thin_stroke(FORTIF_STROKE_WIDTH);
        let stroke_paint = rgb_paint(FORTIF_STROKE_RGB, 1.0);
        let mut pb = PathBuilder::new();
        pb.move_to(x - half, y - half);
        pb.line_to(x + half, y - half);
        pb.line_to(x + half, y + half);
        pb.line_to(x - half, y + half);
        pb.close();
        if let Some(path) = pb.finish() {
            ctx.pixmap.stroke_path(
                &path, &stroke_paint, &stroke, rotated, None,
            );
        }
        return;
    }
    // Merlon / Tower fallback: axis-aligned black square.
    fortif_rect(x, y, size, size, FORTIF_CORNER_RGB, ctx);
}


// ── Palisade circles + door rect ──────────────────────────────


fn palisade_circles(
    points: &[(f32, f32)], rng: &mut EncRng, ctx: &mut RasterCtx<'_>,
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
            let mut pb = PathBuilder::new();
            pb.push_circle(cx, cy, r);
            if let Some(path) = pb.finish() {
                ctx.pixmap.fill_path(
                    &path, &fill, FillRule::Winding, ctx.transform, None,
                );
                ctx.pixmap.stroke_path(
                    &path, &stroke_paint, &stroke, ctx.transform, None,
                );
            }
            t += PALI_CIRCLE_STEP;
        }
        carry = (t - seg_len).max(0.0);
    }
}

fn palisade_door_rect(
    a: (f32, f32), b: (f32, f32), t_center: f32,
    ctx: &mut RasterCtx<'_>,
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
    let rect = match Rect::from_xywh(x, y, w, h) {
        Some(r) => r,
        None => return,
    };
    let fill = rgb_paint(PALI_FILL_RGB, 1.0);
    ctx.pixmap.fill_rect(rect, &fill, ctx.transform, None);
    let stroke = thin_stroke(PALI_STROKE_WIDTH);
    let stroke_paint = rgb_paint(PALI_STROKE_RGB, 1.0);
    let mut pb = PathBuilder::new();
    pb.move_to(x, y);
    pb.line_to(x + w, y);
    pb.line_to(x + w, y + h);
    pb.line_to(x, y + h);
    pb.close();
    if let Some(path) = pb.finish() {
        ctx.pixmap.stroke_path(
            &path, &stroke_paint, &stroke, ctx.transform, None,
        );
    }
}


// ── Dispatch entry ─────────────────────────────────────────────


fn polygon_coords(op: &EnclosureOp<'_>) -> Vec<(f32, f32)> {
    let polygon = match op.polygon() {
        Some(p) => p,
        None => return Vec::new(),
    };
    let paths = match polygon.paths() {
        Some(p) => p,
        None => return Vec::new(),
    };
    paths.iter().map(|v| (v.x(), v.y())).collect()
}

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op: EnclosureOp = match entry.op_as_enclosure_op() {
        Some(o) => o,
        None => return,
    };
    let polygon = polygon_coords(&op);
    let n = polygon.len();
    if n < 3 {
        return;
    }

    // Group gates by edge and merge into per-edge cut spans.
    let mut by_edge: Vec<Vec<(f32, f32)>> = vec![Vec::new(); n];
    let mut midpoints: Vec<Vec<f32>> = vec![Vec::new(); n];
    if let Some(gates) = op.gates() {
        for g in gates.iter() {
            let edge_idx = g.edge_idx() as usize;
            if edge_idx >= n {
                continue;
            }
            let a = polygon[edge_idx];
            let b = polygon[(edge_idx + 1) % n];
            let dx = b.0 - a.0;
            let dy = b.1 - a.1;
            let edge_len = (dx * dx + dy * dy).sqrt();
            if edge_len < 1e-6 {
                continue;
            }
            let half_t = g.half_px() / edge_len;
            let lo = (g.t_center() - half_t).max(0.0);
            let hi = (g.t_center() + half_t).min(1.0);
            if hi > lo {
                by_edge[edge_idx].push((lo, hi));
                midpoints[edge_idx].push(g.t_center());
            }
        }
    }

    let style = op.style();
    let rng_seed = op.rng_seed();

    if style == EnclosureStyle::Palisade {
        for i in 0..n {
            let a = polygon[i];
            let b = polygon[(i + 1) % n];
            let cuts = merge_cuts(by_edge[i].clone());
            let subs = subsegments(a, b, &cuts);
            let mut edge_rng = EncRng::new(rng_seed.wrapping_add(i as u64));
            for (sa, sb) in &subs {
                palisade_circles(&[*sa, *sb], &mut edge_rng, ctx);
            }
            for &t_center in &midpoints[i] {
                palisade_door_rect(a, b, t_center, ctx);
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
            centered_fortification_chain(sa, sb, ctx);
        }
    }
    // Wood gate visuals (legacy fortification drew nothing here).
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        for &t_center in &midpoints[i] {
            palisade_door_rect(a, b, t_center, ctx);
        }
    }
    let corner_style = op.corner_style().0;
    for &(x, y) in &polygon {
        corner_shape(x, y, corner_style, ctx);
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
