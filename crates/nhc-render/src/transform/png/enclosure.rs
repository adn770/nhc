//! Site-enclosure painters for the v5 StrokeOp dispatch.
//!
//! Two treatments share a polygon-walk + cut-projection scaffold:
//!
//! - ``WallTreatment::Palisade`` — circle posts along open
//!   sub-segments, with optional door-rect overlays at gate cuts.
//!   Pulls fill / stroke from ``substance_color`` so the Wood
//!   family's per-species palette drives post colour.
//! - ``WallTreatment::Fortification`` — centered crenellated
//!   battlement chains along inset edges, plus a corner shape per
//!   polygon vertex (``CornerStyle::Merlon`` / ``Diamond`` /
//!   ``Tower``). Merlon / crenel use a stylised light-gray /
//!   black palette rather than substance colours so the iconic
//!   high-contrast look survives.
//!
//! Lifted from the deleted v4 ``transform/png/enclosure.rs``;
//! the algorithms are unchanged. The cut-projection helper that
//! converts ``StrokeOp.cuts[]`` (pixel-space ``(start, end)``
//! pairs) back to per-edge ``(t_lo, t_hi)`` intervals is new at
//! the v5 cut — the v4 emit used to ship explicit
//! ``(edge_idx, t_center, half_px)`` triples.

use std::f32::consts::SQRT_2;

use flatbuffers::{ForwardsUOffset, Vector};

use crate::ir::{Cut, CutStyle, CornerStyle};
use crate::painter::material::{substance_color, Family, PaletteRole};
use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, PathOps, Rect, Stroke,
    Transform, Vec2,
};
use crate::rng::SplitMix64;


// ── Fortification (battlement) constants ──────────────────────


const FORTIF_STROKE_RGB: (u8, u8, u8) = (0x1A, 0x1A, 0x1A);
const FORTIF_STROKE_WIDTH: f32 = 0.8;
const FORTIF_MERLON_RGB: (u8, u8, u8) = (0xD8, 0xD8, 0xD8);
const FORTIF_CRENEL_RGB: (u8, u8, u8) = (0x00, 0x00, 0x00);
const FORTIF_CORNER_RGB: (u8, u8, u8) = (0x00, 0x00, 0x00);
const FORTIF_SIZE: f32 = 8.0;
const FORTIF_CORNER_SCALE: f32 = 3.0;


// ── Palisade constants ─────────────────────────────────────────


const PALI_STROKE_WIDTH: f32 = 1.5;
const PALI_RADIUS_MIN: f32 = 3.0;
const PALI_RADIUS_MAX: f32 = 4.0;
const PALI_RADIUS_JITTER: f32 = 0.3;
const PALI_CIRCLE_STEP: f32 = 9.0;
const PALI_DOOR_LENGTH_PX: f32 = 64.0;


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


fn rgb_paint(rgb: (u8, u8, u8)) -> Paint {
    Paint::solid(Color::rgba(rgb.0, rgb.1, rgb.2, 1.0))
}

fn thin_stroke(width: f32) -> Stroke {
    Stroke {
        width,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    }
}


// ── Cut → per-edge (t_lo, t_hi) projection ────────────────────


/// Project a flat list of ``Cut`` records onto a polygon's edges.
///
/// Returns ``(by_edge, midpoints)``:
/// - ``by_edge[i]`` is the merged list of ``(t_lo, t_hi)`` cut
///   intervals on edge ``i`` (CCW polygon order, ``t`` in [0, 1]
///   along ``polygon[i] → polygon[i+1]``).
/// - ``midpoints[i]`` collects the per-cut centre ``t`` values for
///   gate-bearing cuts (CutStyle != None) — used by the door-rect
///   pass to overlay a wood gate visual.
///
/// Each cut's pixel-space start / end are projected onto the edge
/// via dot products. The cut applies to an edge when both endpoints
/// project within ``[0, 1]`` (with a small tolerance) AND the
/// perpendicular distance from edge to cut endpoint is below half
/// the wall thickness — defensive against rounding error in the
/// emit-side gate-to-cut resolution.
fn project_cuts_onto_polygon(
    polygon: &[(f32, f32)],
    cuts: Option<Vector<'_, ForwardsUOffset<Cut<'_>>>>,
) -> (Vec<Vec<(f32, f32)>>, Vec<Vec<f32>>) {
    let n = polygon.len();
    let mut by_edge: Vec<Vec<(f32, f32)>> = vec![Vec::new(); n];
    let mut midpoints: Vec<Vec<f32>> = vec![Vec::new(); n];
    let cuts = match cuts {
        Some(c) => c,
        None => return (by_edge, midpoints),
    };
    const PERP_TOLERANCE: f32 = 4.0;
    const T_TOLERANCE: f32 = 1e-3;
    for ci in 0..cuts.len() {
        let cut = cuts.get(ci);
        let (cs, ce) = match (cut.start(), cut.end()) {
            (Some(s), Some(e)) => ((s.x(), s.y()), (e.x(), e.y())),
            _ => continue,
        };
        // Find best-fit edge by combined projection error.
        let mut best_edge: Option<usize> = None;
        let mut best_err = f32::INFINITY;
        let mut best_lo = 0.0_f32;
        let mut best_hi = 0.0_f32;
        for i in 0..n {
            let (ax, ay) = polygon[i];
            let (bx, by) = polygon[(i + 1) % n];
            let dx = bx - ax;
            let dy = by - ay;
            let len_sq = dx * dx + dy * dy;
            if len_sq < 1e-9 {
                continue;
            }
            let t_s = ((cs.0 - ax) * dx + (cs.1 - ay) * dy) / len_sq;
            let t_e = ((ce.0 - ax) * dx + (ce.1 - ay) * dy) / len_sq;
            // Perpendicular distance from edge to each endpoint.
            let proj_s = (ax + dx * t_s, ay + dy * t_s);
            let proj_e = (ax + dx * t_e, ay + dy * t_e);
            let perp_s = ((cs.0 - proj_s.0).powi(2) + (cs.1 - proj_s.1).powi(2)).sqrt();
            let perp_e = ((ce.0 - proj_e.0).powi(2) + (ce.1 - proj_e.1).powi(2)).sqrt();
            let perp_err = perp_s + perp_e;
            if perp_err > PERP_TOLERANCE {
                continue;
            }
            // Both endpoints must land roughly inside the edge.
            if t_s < -T_TOLERANCE || t_s > 1.0 + T_TOLERANCE {
                continue;
            }
            if t_e < -T_TOLERANCE || t_e > 1.0 + T_TOLERANCE {
                continue;
            }
            if perp_err < best_err {
                best_err = perp_err;
                best_edge = Some(i);
                best_lo = t_s.min(t_e).clamp(0.0, 1.0);
                best_hi = t_s.max(t_e).clamp(0.0, 1.0);
            }
        }
        if let Some(i) = best_edge {
            if best_hi > best_lo {
                by_edge[i].push((best_lo, best_hi));
                if cut.style() != CutStyle::None {
                    midpoints[i].push((best_lo + best_hi) * 0.5);
                }
            }
        }
    }
    // Merge overlapping intervals per edge.
    for cuts in by_edge.iter_mut() {
        if cuts.len() <= 1 {
            continue;
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
        *cuts = merged;
    }
    (by_edge, midpoints)
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


// ── Fortification chain + corner ──────────────────────────────


fn fortif_rect(
    cx: f32, cy: f32, w: f32, h: f32, fill_rgb: (u8, u8, u8),
    painter: &mut dyn Painter,
) {
    if w <= 0.0 || h <= 0.0 {
        return;
    }
    let fill = rgb_paint(fill_rgb);
    painter.fill_rect(
        Rect::new(cx - w / 2.0, cy - h / 2.0, w, h),
        &fill,
    );
    let stroke = thin_stroke(FORTIF_STROKE_WIDTH);
    let stroke_paint = rgb_paint(FORTIF_STROKE_RGB);
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
    let rect_len = size * SQRT_2;
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


fn corner_shape(
    x: f32, y: f32, corner_style: CornerStyle, painter: &mut dyn Painter,
) {
    let size = FORTIF_SIZE * FORTIF_CORNER_SCALE;
    if corner_style == CornerStyle::Diamond {
        let half = size / 2.0;
        if half <= 0.0 {
            return;
        }
        let fill = rgb_paint(FORTIF_CORNER_RGB);
        let stroke = thin_stroke(FORTIF_STROKE_WIDTH);
        let stroke_paint = rgb_paint(FORTIF_STROKE_RGB);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(x - half, y - half));
        path.line_to(Vec2::new(x + half, y - half));
        path.line_to(Vec2::new(x + half, y + half));
        path.line_to(Vec2::new(x - half, y + half));
        path.close();
        painter.push_transform(Transform::rotate_around(
            45.0_f32.to_radians(), x, y,
        ));
        painter.fill_rect(Rect::new(x - half, y - half, size, size), &fill);
        painter.stroke_path(&path, &stroke_paint, &stroke);
        painter.pop_transform();
        return;
    }
    fortif_rect(x, y, size, size, FORTIF_CORNER_RGB, painter);
}


// ── Palisade circles + door rect ──────────────────────────────


fn palisade_circles(
    a: (f32, f32),
    b: (f32, f32),
    fill: &Paint,
    stroke_paint: &Paint,
    rng: &mut EncRng,
    painter: &mut dyn Painter,
) {
    let dx = b.0 - a.0;
    let dy = b.1 - a.1;
    let seg_len = (dx * dx + dy * dy).sqrt();
    if seg_len < 1e-6 {
        return;
    }
    let ux = dx / seg_len;
    let uy = dy / seg_len;
    let stroke = thin_stroke(PALI_STROKE_WIDTH);
    let mut t = 0.0_f32;
    while t < seg_len {
        let cx = a.0 + ux * t;
        let cy = a.1 + uy * t;
        let base_r = rng.uniform(PALI_RADIUS_MIN, PALI_RADIUS_MAX);
        let jitter = rng.uniform(-PALI_RADIUS_JITTER, PALI_RADIUS_JITTER);
        let r = (base_r + jitter).max(0.1);
        painter.fill_circle(cx, cy, r, fill);
        let circle_path = circle_path_ops(cx, cy, r);
        painter.stroke_path(&circle_path, stroke_paint, &stroke);
        t += PALI_CIRCLE_STEP;
    }
}

fn palisade_door_rect(
    a: (f32, f32), b: (f32, f32), t_center: f32,
    fill: &Paint,
    stroke_paint: &Paint,
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
    painter.fill_rect(Rect::new(x, y, w, h), fill);
    let stroke = thin_stroke(PALI_STROKE_WIDTH);
    let mut path = PathOps::new();
    path.move_to(Vec2::new(x, y));
    path.line_to(Vec2::new(x + w, y));
    path.line_to(Vec2::new(x + w, y + h));
    path.line_to(Vec2::new(x, y + h));
    path.close();
    painter.stroke_path(&path, stroke_paint, &stroke);
}


fn circle_path_ops(cx: f32, cy: f32, r: f32) -> PathOps {
    const KAPPA: f32 = 0.5522847498307933;
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


// ── Render entries ─────────────────────────────────────────────


pub fn render_palisade_polygon(
    polygon: &[(f32, f32)],
    cuts: Option<Vector<'_, ForwardsUOffset<Cut<'_>>>>,
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
    let stroke_color: Color = substance_color(family, style, 0, PaletteRole::Shadow);
    let fill = Paint::solid(fill_color);
    let stroke_paint = Paint::solid(stroke_color);
    let (by_edge, midpoints) = project_cuts_onto_polygon(polygon, cuts);
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        let edge_cuts = &by_edge[i];
        let subs = subsegments(a, b, edge_cuts);
        let mut edge_rng = EncRng::new(rng_seed.wrapping_add(i as u64));
        for (sa, sb) in &subs {
            palisade_circles(
                *sa, *sb, &fill, &stroke_paint, &mut edge_rng, painter,
            );
        }
        for &t_center in &midpoints[i] {
            palisade_door_rect(
                a, b, t_center, &fill, &stroke_paint, painter,
            );
        }
    }
}


pub fn render_fortification_polygon(
    polygon: &[(f32, f32)],
    cuts: Option<Vector<'_, ForwardsUOffset<Cut<'_>>>>,
    corner_style: CornerStyle,
    painter: &mut dyn Painter,
) {
    let n = polygon.len();
    if n < 3 {
        return;
    }
    let (by_edge, midpoints) = project_cuts_onto_polygon(polygon, cuts);
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
        let edge_cuts = &by_edge[i];
        let t_inset = inset / edge_len;
        let denom = 1.0 - 2.0 * t_inset;
        let inset_cuts: Vec<(f32, f32)> = if denom > 1e-9 {
            edge_cuts.iter()
                .map(|&(lo, hi)| {
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
    // Pretend the gates draw as wood doors over fortifications too —
    // mirrors the v4 behaviour where fortification cuts dropped a
    // palisade-style door rect at the cut centre. The fill colour
    // here is the FORTIF crenel black (matches the v4 visual).
    let door_fill = rgb_paint(FORTIF_CRENEL_RGB);
    let door_stroke = rgb_paint(FORTIF_STROKE_RGB);
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        for &t_center in &midpoints[i] {
            palisade_door_rect(
                a, b, t_center, &door_fill, &door_stroke, painter,
            );
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
            ],
        );
    }

    #[test]
    fn enc_rng_first_call_matches_python_reference() {
        let mut rng = EncRng::new(1234);
        let u = rng.inner.next_u64();
        assert_eq!(u, 0xbb0cf61b2f181cdb);
    }
}
