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
    let cuts = match cuts {
        Some(c) => c,
        None => return (
            vec![Vec::new(); polygon.len()],
            vec![Vec::new(); polygon.len()],
        ),
    };
    let cuts_iter: Vec<((f32, f32), (f32, f32), bool)> = (0..cuts.len())
        .filter_map(|ci| {
            let cut = cuts.get(ci);
            let (cs, ce) = match (cut.start(), cut.end()) {
                (Some(s), Some(e)) => ((s.x(), s.y()), (e.x(), e.y())),
                _ => return None,
            };
            let bears_gate = cut.style() != CutStyle::None;
            Some((cs, ce, bears_gate))
        })
        .collect();
    project_cuts_onto_polygon_pure(polygon, &cuts_iter)
}

/// Cut projection contract. Each cut is ``(cs, ce, bears_gate)``:
/// the pixel-space endpoints plus a flag for whether the cut
/// hosts a gate visual (CutStyle != None). Returns
/// ``(by_edge, midpoints)``:
/// - ``by_edge[i]`` is the merged list of ``(t_lo, t_hi)`` cut
///   intervals along polygon edge ``i``.
/// - ``midpoints[i]`` collects the per-cut centre ``t`` values
///   for gate-bearing cuts (used by the door-rect overlay).
///
/// Two paths feed the result:
/// 1. **Single-edge fast path** (legacy logic). A cut whose
///    endpoints both project onto the same polygon edge with low
///    perpendicular error contributes one ``(t_lo, t_hi)`` to
///    that edge. Preserves byte-identical output for the
///    rect / octagon cases the legacy parity gates lock.
/// 2. **Multi-edge fallback**. When no single edge fits (e.g. a
///    cut spanning the top of a polygonised circle, where the
///    endpoints land on different short edges), find the edge
///    nearest each endpoint and stamp partial cuts along the
///    arc of edges between them. The gate-visual midpoint then
///    lands on whichever edge is closest to the cut's pixel-
///    space centre.
fn project_cuts_onto_polygon_pure(
    polygon: &[(f32, f32)],
    cuts: &[((f32, f32), (f32, f32), bool)],
) -> (Vec<Vec<(f32, f32)>>, Vec<Vec<f32>>) {
    let n = polygon.len();
    let mut by_edge: Vec<Vec<(f32, f32)>> = vec![Vec::new(); n];
    let mut midpoints: Vec<Vec<f32>> = vec![Vec::new(); n];
    const PERP_TOLERANCE: f32 = 4.0;
    const T_TOLERANCE: f32 = 1e-3;
    for &(cs, ce, bears_gate) in cuts {
        // Single-edge fast path: same logic as the legacy
        // implementation. Find the best-fit edge where both
        // endpoints project inside [0, 1] with a small
        // perpendicular error budget.
        let mut best_single_edge: Option<usize> = None;
        let mut best_single_err = f32::INFINITY;
        let mut best_single_lo = 0.0_f32;
        let mut best_single_hi = 0.0_f32;
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
            let proj_s = (ax + dx * t_s, ay + dy * t_s);
            let proj_e = (ax + dx * t_e, ay + dy * t_e);
            let perp_s = ((cs.0 - proj_s.0).powi(2)
                + (cs.1 - proj_s.1).powi(2)).sqrt();
            let perp_e = ((ce.0 - proj_e.0).powi(2)
                + (ce.1 - proj_e.1).powi(2)).sqrt();
            let perp_err = perp_s + perp_e;
            if perp_err > PERP_TOLERANCE {
                continue;
            }
            if t_s < -T_TOLERANCE || t_s > 1.0 + T_TOLERANCE {
                continue;
            }
            if t_e < -T_TOLERANCE || t_e > 1.0 + T_TOLERANCE {
                continue;
            }
            if perp_err < best_single_err {
                best_single_err = perp_err;
                best_single_edge = Some(i);
                best_single_lo = t_s.min(t_e).clamp(0.0, 1.0);
                best_single_hi = t_s.max(t_e).clamp(0.0, 1.0);
            }
        }
        if let Some(i) = best_single_edge {
            if best_single_hi > best_single_lo {
                by_edge[i].push((best_single_lo, best_single_hi));
                if bears_gate {
                    midpoints[i].push(
                        (best_single_lo + best_single_hi) * 0.5,
                    );
                }
            }
            continue;
        }
        // Multi-edge fallback: no single edge took the cut.
        // Stamp partial intervals along the arc spanning the
        // edges nearest each endpoint.
        let (i_s, t_on_s) = match nearest_edge(polygon, cs, PERP_TOLERANCE) {
            Some(x) => x,
            None => continue,
        };
        let (i_e, t_on_e) = match nearest_edge(polygon, ce, PERP_TOLERANCE) {
            Some(x) => x,
            None => continue,
        };
        if i_s == i_e {
            // Degenerate — both endpoints land on the same edge
            // but failed the single-edge perp budget. Skip
            // rather than smear the cut over the entire polygon.
            continue;
        }
        // Pick the shorter arc by edge count.
        let fwd_len = (i_e + n - i_s) % n;
        let bwd_len = (i_s + n - i_e) % n;
        let (start_edge, start_t, end_edge, end_t) = if fwd_len <= bwd_len {
            (i_s, t_on_s, i_e, t_on_e)
        } else {
            (i_e, t_on_e, i_s, t_on_s)
        };
        // First edge: partial cut from the endpoint projection
        // to the edge's end.
        by_edge[start_edge].push((start_t, 1.0));
        // Intermediate edges (if any): full coverage.
        let mut idx = (start_edge + 1) % n;
        while idx != end_edge {
            by_edge[idx].push((0.0, 1.0));
            idx = (idx + 1) % n;
        }
        // Last edge: partial cut from edge start to the
        // endpoint projection.
        by_edge[end_edge].push((0.0, end_t));
        // Gate midpoint: place the door-rect overlay on the
        // edge nearest the cut's geometric centre.
        if bears_gate {
            let mid_px = ((cs.0 + ce.0) * 0.5, (cs.1 + ce.1) * 0.5);
            if let Some((mid_edge, mid_t)) =
                nearest_edge(polygon, mid_px, PERP_TOLERANCE * 4.0)
            {
                midpoints[mid_edge].push(mid_t);
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

/// Find the polygon edge nearest to a pixel-space point.
/// Returns ``(edge_index, t_along_edge)`` when the perpendicular
/// distance is within ``tolerance``, otherwise ``None``. The
/// returned ``t`` is clamped to ``[0, 1]`` so the caller can
/// stamp it as an interval bound without further clipping.
fn nearest_edge(
    polygon: &[(f32, f32)],
    point: (f32, f32),
    tolerance: f32,
) -> Option<(usize, f32)> {
    let n = polygon.len();
    let mut best: Option<(usize, f32, f32)> = None;
    for i in 0..n {
        let (ax, ay) = polygon[i];
        let (bx, by) = polygon[(i + 1) % n];
        let dx = bx - ax;
        let dy = by - ay;
        let len_sq = dx * dx + dy * dy;
        if len_sq < 1e-9 {
            continue;
        }
        let t = (((point.0 - ax) * dx + (point.1 - ay) * dy)
            / len_sq).clamp(0.0, 1.0);
        let proj = (ax + dx * t, ay + dy * t);
        let perp = ((point.0 - proj.0).powi(2)
            + (point.1 - proj.1).powi(2)).sqrt();
        match best {
            None => best = Some((i, t, perp)),
            Some((_, _, e)) if perp < e => best = Some((i, t, perp)),
            _ => {}
        }
    }
    best.and_then(|(i, t, perp)| {
        if perp <= tolerance { Some((i, t)) } else { None }
    })
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
    if corner_style == CornerStyle::Round {
        // Round — a single filled circle with a thin outline so
        // the corner reads as a tower bartizan instead of a
        // flat patch.
        let radius = size / 2.0;
        if radius <= 0.0 {
            return;
        }
        let fill = rgb_paint(FORTIF_CORNER_RGB);
        let stroke = thin_stroke(FORTIF_STROKE_WIDTH);
        let stroke_paint = rgb_paint(FORTIF_STROKE_RGB);
        painter.fill_circle(x, y, radius, &fill);
        // Circumference outline — sample 24 segments around the
        // circle for a smooth ring at FORTIF_SIZE without
        // pulling in the painter's bezier-arc stroke API.
        let mut path = PathOps::new();
        let n = 24;
        for i in 0..n {
            let theta = (i as f32) * std::f32::consts::TAU / (n as f32);
            let px = x + radius * theta.cos();
            let py = y + radius * theta.sin();
            if i == 0 {
                path.move_to(Vec2::new(px, py));
            } else {
                path.line_to(Vec2::new(px, py));
            }
        }
        path.close();
        painter.stroke_path(&path, &stroke_paint, &stroke);
        return;
    }
    if corner_style == CornerStyle::Crow {
        // Crow — crow-step gable. Three stacked squares of
        // shrinking size, each offset toward the wall corner so
        // the silhouette reads as a stair-step ascending toward
        // the peak. ``CornerStyle::Crow`` ignores wall direction
        // — the steps point ``(+, +)`` (down-right) since the
        // fortification renderer issues corner_shape calls
        // unaware of which corner of the polygon they're on.
        let half = size / 2.0;
        if half <= 0.0 {
            return;
        }
        let step = size / 3.0;
        for i in 0..3 {
            let off = (i as f32) * step * 0.5;
            let s = size - (i as f32) * step * 0.6;
            if s <= 0.0 {
                break;
            }
            fortif_rect(
                x + off,
                y + off,
                s,
                s,
                FORTIF_CORNER_RGB,
                painter,
            );
        }
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

    /// Single-edge fast path — a cut sitting cleanly on one edge
    /// of a square contributes one interval to that edge. Pins
    /// the legacy behavior the parity gate locks.
    fn approx_eq(a: f32, b: f32, eps: f32) -> bool {
        (a - b).abs() < eps
    }

    #[test]
    fn cut_projects_onto_single_top_edge_of_square() {
        let square: Vec<(f32, f32)> = vec![
            (0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0),
        ];
        let cuts = vec![((30.0, 0.0), (60.0, 0.0), true)];
        let (by_edge, mids) =
            project_cuts_onto_polygon_pure(&square, &cuts);
        assert_eq!(by_edge[0].len(), 1);
        let (lo, hi) = by_edge[0][0];
        assert!(approx_eq(lo, 0.30, 1e-4), "lo was {lo}");
        assert!(approx_eq(hi, 0.60, 1e-4), "hi was {hi}");
        assert!(by_edge[1].is_empty());
        assert!(by_edge[2].is_empty());
        assert!(by_edge[3].is_empty());
        assert_eq!(mids[0].len(), 1);
        assert!(approx_eq(mids[0][0], 0.45, 1e-4));
    }

    /// Multi-edge fallback — a cut spanning the topmost vertex
    /// of a polygonised circle splits the interval across the
    /// two short edges adjacent to that vertex. Pins the
    /// `synthetic/walls/cuts-single-gate_seed7.png` fix: before
    /// the change the cut was silently dropped because no
    /// single edge accepted both endpoints within the perp
    /// budget.
    #[test]
    fn cut_spanning_two_edges_at_polygon_vertex_lands_on_both() {
        // A 32-gon approximating a circle of radius 32 centred
        // at (50, 50). Vertex 0 sits at the topmost point
        // (50, 18); vertex 1 is to the right of it, vertex 31
        // to the left.
        let n: usize = 32;
        let cx = 50.0_f32;
        let cy = 50.0_f32;
        let r = 32.0_f32;
        let polygon: Vec<(f32, f32)> = (0..n)
            .map(|i| {
                let angle = -std::f32::consts::FRAC_PI_2
                    + (i as f32) * std::f32::consts::TAU
                    / (n as f32);
                (cx + r * angle.cos(), cy + r * angle.sin())
            })
            .collect();
        // Cut along the bbox top (y = cy - r = 18.0), from
        // x = 46 to x = 54 — symmetric around the topmost
        // vertex (50, 18). Vertex 31 sits at (43.76, 18.61)
        // and vertex 1 at (56.24, 18.61), so cs / ce land on
        // edge 31 (vertex 31 → vertex 0) and edge 0 (vertex 0
        // → vertex 1) respectively.
        let cs = (46.0_f32, 18.0_f32);
        let ce = (54.0_f32, 18.0_f32);
        let (by_edge, mids) = project_cuts_onto_polygon_pure(
            &polygon, &[(cs, ce, true)],
        );
        // edge 31 (vertex 31 → vertex 0) and edge 0 (vertex 0 →
        // vertex 1) must both receive a partial cut. No other
        // edge should — the legacy fallback would smear the cut
        // across the whole polygon otherwise.
        assert!(
            !by_edge[31].is_empty(),
            "edge 31 (top-left) should receive a cut interval"
        );
        assert!(
            !by_edge[0].is_empty(),
            "edge 0 (top-right) should receive a cut interval"
        );
        // edge 31 partial goes from some t_lo to 1.0 (ends at
        // the topmost vertex). edge 0 partial goes from 0.0 to
        // some t_hi (starts at the topmost vertex).
        assert_eq!(by_edge[31][0].1, 1.0, "edge 31 cut should run to its end");
        assert_eq!(by_edge[0][0].0, 0.0, "edge 0 cut should start at its beginning");
        // No other edge should have received the cut.
        for i in 1..31 {
            assert!(
                by_edge[i].is_empty(),
                "edge {i} should be untouched (cut shouldn't span here)"
            );
        }
        // Gate midpoint lands on one of the two affected edges.
        let total_mids: usize = mids.iter().map(|v| v.len()).sum();
        assert_eq!(total_mids, 1, "exactly one midpoint for one gate cut");
    }

    /// Wider cuts spanning more than two edges fill the
    /// intermediate edges with full-coverage intervals (0..1).
    /// Exercises the inner-arc loop of the multi-edge fallback.
    /// Geometry matches the production catalog circle (radius
    /// 64, 32 segments) so the perp budget is comfortably met
    /// even at the wider cut endpoints.
    #[test]
    fn wide_cut_spanning_three_edges_marks_middle_edge_fully() {
        let n: usize = 32;
        let cx = 88.0_f32;
        let cy = 384.0_f32;
        let r = 64.0_f32;
        let polygon: Vec<(f32, f32)> = (0..n)
            .map(|i| {
                let angle = -std::f32::consts::FRAC_PI_2
                    + (i as f32) * std::f32::consts::TAU
                    / (n as f32);
                (cx + r * angle.cos(), cy + r * angle.sin())
            })
            .collect();
        // Cut from (70, 320) to (106, 320) — extends past
        // vertex 31 (75.52, 321.22) on the left and vertex 1
        // (100.48, 321.22) on the right of the topmost vertex,
        // so it must span ≥3 edges: edge 30 (partial), 31
        // (full), and edge 0 (partial — or further).
        let cs = (70.0_f32, 320.0_f32);
        let ce = (106.0_f32, 320.0_f32);
        let (by_edge, _mids) = project_cuts_onto_polygon_pure(
            &polygon, &[(cs, ce, true)],
        );
        let touched: Vec<usize> = (0..n)
            .filter(|&i| !by_edge[i].is_empty())
            .collect();
        assert!(
            touched.len() >= 3,
            "wide top-spanning cut should touch ≥3 edges, got {touched:?}"
        );
        // At least one middle edge should be fully covered.
        let full_count = (0..n)
            .filter(|&i| by_edge[i].iter().any(|&(lo, hi)| lo == 0.0 && hi == 1.0))
            .count();
        assert!(
            full_count >= 1,
            "wide cut should fully cover at least one intermediate edge"
        );
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

    /// Round corner emits a single fill_circle stamp plus its
    /// circumference outline; Merlon would emit a fill_rect
    /// instead, and Diamond a transformed fill_rect. Pin the
    /// shape so a future change to corner geometry surfaces as
    /// a clear failure.
    #[test]
    fn round_corner_emits_filled_circle_with_outline() {
        let mut painter = crate::painter::test_util::MockPainter::default();
        corner_shape(50.0, 60.0, CornerStyle::Round, &mut painter);
        let circles = painter
            .calls
            .iter()
            .filter(|c| matches!(
                c,
                crate::painter::test_util::PainterCall::FillCircle(_, _, _, _),
            ))
            .count();
        let strokes = painter
            .calls
            .iter()
            .filter(|c| matches!(
                c,
                crate::painter::test_util::PainterCall::StrokePath(_, _, _),
            ))
            .count();
        let rects = painter
            .calls
            .iter()
            .filter(|c| matches!(
                c,
                crate::painter::test_util::PainterCall::FillRect(_, _),
            ))
            .count();
        assert_eq!(circles, 1, "Round corner should emit one fill_circle");
        assert_eq!(strokes, 1, "Round corner should emit one outline stroke");
        assert_eq!(rects, 0, "Round corner should not emit fill_rect");
    }

    /// Crow corner emits 3 stacked rectangles for the crow-step
    /// gable silhouette; Merlon emits 1, Diamond emits 1
    /// (transformed). Pin the multi-step count so a future tweak
    /// to step depth surfaces as a clear failure.
    #[test]
    fn crow_corner_emits_three_stair_step_rects() {
        let mut painter = crate::painter::test_util::MockPainter::default();
        corner_shape(50.0, 60.0, CornerStyle::Crow, &mut painter);
        let rects = painter
            .calls
            .iter()
            .filter(|c| matches!(
                c,
                crate::painter::test_util::PainterCall::FillRect(_, _),
            ))
            .count();
        assert_eq!(rects, 3, "Crow corner should emit 3 stair-step fill_rects");
    }

    /// Merlon (default) stays at one fill_rect per corner — pins
    /// the post-#3 / #4 additions don't accidentally regress the
    /// existing default behaviour.
    #[test]
    fn merlon_corner_emits_single_fill_rect() {
        let mut painter = crate::painter::test_util::MockPainter::default();
        corner_shape(50.0, 60.0, CornerStyle::Merlon, &mut painter);
        let rects = painter
            .calls
            .iter()
            .filter(|c| matches!(
                c,
                crate::painter::test_util::PainterCall::FillRect(_, _),
            ))
            .count();
        let circles = painter
            .calls
            .iter()
            .filter(|c| matches!(
                c,
                crate::painter::test_util::PainterCall::FillCircle(_, _, _, _),
            ))
            .count();
        assert_eq!(rects, 1, "Merlon corner should emit 1 fill_rect");
        assert_eq!(circles, 0, "Merlon corner should not emit fill_circle");
    }
}
