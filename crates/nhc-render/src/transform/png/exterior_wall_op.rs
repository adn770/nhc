//! ExteriorWallOp rasterisation — Phase 1.18 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Reads `ExteriorWallOp.outline` + `ExteriorWallOp.style` and paints
//! the wall stroke via tiny-skia native primitives.
//!
//! Handled styles (Rust-native, mirroring Python 1.16b consumers):
//! - `DungeonInk` (0): 5px black stroke, outline with cuts. Polygon
//!   outlines emit a stroked path with Cut gaps. Circle descriptor emits
//!   an arc. Pill descriptor emits a rounded-rect stroke.
//! - `CaveInk` (1): cave pipeline — `buffer+simplify+densify+jitter
//!   +smooth` from `outline.vertices`; seed = `base_seed + 0x5A17E5`.
//!
//! Other styles (Masonry, Palisade, Fortification) are left to the
//! legacy `BuildingExteriorWallOp` / `EnclosureOp` Rust handlers.
//! This handler silently skips any style it does not own.
//!
//! Cut handling: doors (DoorWood/Iron/Stone/Secret) do NOT create gaps
//! in the stroke — they are separate overlay layers. Only `CutStyle::None`
//! (doorless corridor openings) creates a visible gap. Rect polygon
//! outlines (4-vertex) apply all cuts; smooth outlines (> 4 vertices)
//! apply only None_ cuts.

use std::f32::consts::PI as PI32;

use tiny_skia::{Color, LineCap, LineJoin, Paint, PathBuilder, Rect, Stroke};

use crate::geometry::cave_path_from_outline;
use crate::ir::{
    Cut, CutStyle, EnclosureStyle, FloorIR, OpEntry, Outline, OutlineKind,
    WallMaterial, WallStyle,
};
use crate::transform::png::path_parser::parse_path_d;

use super::building_exterior_wall::render_masonry_polygon;
use super::enclosure::render_enclosure_polygon;
use super::RasterCtx;

const INK_R: u8 = 0x00;
const INK_G: u8 = 0x00;
const INK_B: u8 = 0x00;
const WALL_WIDTH: f32 = 5.0;

fn ink_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(INK_R, INK_G, INK_B, 0xFF));
    p.anti_alias = true;
    p
}

fn wall_stroke() -> Stroke {
    Stroke {
        width: WALL_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
        ..Stroke::default()
    }
}

/// `OpHandler` dispatch entry — registered against `Op::ExteriorWallOp`
/// in `super::op_handlers`.
///
/// Phase 1.24 — region-keyed dispatch + op-level cuts preference.
/// When ``op.region_ref`` is non-empty AND resolves to a Region with a
/// populated outline, the geometry comes from ``region.outline()``.
/// When ``op.cuts`` is populated, those entries supersede the legacy
/// ``outline.cuts`` for stroke break intervals. Both fields default
/// empty; empty refs / cuts fall through to the legacy paths so 3.x
/// cached buffers still render.
pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_exterior_wall_op() {
        Some(o) => o,
        None => return,
    };
    let outline = resolve_outline(&op, fir);
    let outline = match outline {
        Some(o) => o,
        None => return,
    };
    let cuts: Vec<Cut<'_>> = resolve_cuts(&op, &outline);
    let style = op.style();

    match style {
        WallStyle::DungeonInk => {
            draw_dungeon_ink(&outline, &cuts, ctx);
        }
        WallStyle::CaveInk => {
            draw_cave_ink(&outline, fir, ctx);
        }
        WallStyle::MasonryBrick | WallStyle::MasonryStone => {
            // Phase 1.20 — Masonry coverage moved here from the legacy
            // `BuildingExteriorWallOp` handler. Reuses the polygon
            // chain helper so the byte-equal contract holds.
            let material = if style == WallStyle::MasonryBrick {
                WallMaterial::Brick
            } else {
                WallMaterial::Stone
            };
            let polygon = polygon_from_outline(&outline);
            render_masonry_polygon(&polygon, material, op.rng_seed(), ctx);
        }
        WallStyle::Palisade | WallStyle::FortificationMerlon => {
            // Phase 1.20 — Palisade / Fortification coverage moved here
            // from the legacy `EnclosureOp` handler. The new outline
            // carries gates as `Cut` entries with absolute-pixel
            // start/end; reconstruct the per-edge (lo, hi) span buckets
            // the chain renderer expects.
            let polygon = polygon_from_outline(&outline);
            let (by_edge, midpoints) =
                gate_spans_per_edge_from_cuts(&polygon, &cuts);
            let enc_style = if style == WallStyle::Palisade {
                EnclosureStyle::Palisade
            } else {
                EnclosureStyle::Fortification
            };
            render_enclosure_polygon(
                &polygon,
                &by_edge,
                &midpoints,
                enc_style,
                op.corner_style().0,
                op.rng_seed(),
                ctx,
            );
        }
        _ => {}
    }
}

/// Resolve the wall geometry — prefer the Region's outline when
/// ``op.region_ref`` resolves; otherwise fall back to ``op.outline``.
/// Mirrors the FloorOp.region_ref dispatch in `floor_op.rs`.
fn resolve_outline<'a>(
    op: &crate::ir::ExteriorWallOp<'a>,
    fir: &FloorIR<'a>,
) -> Option<Outline<'a>> {
    if let Some(rr) = op.region_ref() {
        if !rr.is_empty() {
            if let Some(region) = find_region(fir, rr) {
                if let Some(o) = region.outline() {
                    return Some(o);
                }
            }
        }
    }
    op.outline()
}

/// Resolve the wall cuts — prefer ``op.cuts`` when populated; fall
/// back to ``outline.cuts`` for 3.x cached buffers. Returns a Vec
/// rather than a Vector borrow so subroutines have a stable
/// `&[Cut]` slice regardless of which source resolved.
fn resolve_cuts<'a>(
    op: &crate::ir::ExteriorWallOp<'a>,
    outline: &Outline<'a>,
) -> Vec<Cut<'a>> {
    if let Some(cv) = op.cuts() {
        if cv.len() > 0 {
            return cv.iter().collect();
        }
    }
    outline
        .cuts()
        .map(|cv| cv.iter().collect())
        .unwrap_or_default()
}

/// Linear scan of `fir.regions()` for the Region with id matching
/// `region_ref`. Mirrors the helper in `floor_op.rs`.
fn find_region<'a>(
    fir: &FloorIR<'a>,
    needle: &str,
) -> Option<crate::ir::Region<'a>> {
    if needle.is_empty() {
        return None;
    }
    let regions = fir.regions()?;
    for i in 0..regions.len() {
        let r = regions.get(i);
        if r.id() == needle {
            return Some(r);
        }
    }
    None
}


/// Convert an `Outline` polygon descriptor into a flat
/// `Vec<(f32, f32)>` of edge vertices. Returns empty for
/// non-polygon outlines (Circle / Pill descriptors).
fn polygon_from_outline(outline: &Outline<'_>) -> Vec<(f32, f32)> {
    if outline.descriptor_kind() != OutlineKind::Polygon {
        return Vec::new();
    }
    let verts = match outline.vertices() {
        Some(v) => v,
        None => return Vec::new(),
    };
    verts.iter().map(|v| (v.x(), v.y())).collect()
}


/// Reconstruct per-edge (lo, hi) gate span buckets and per-edge
/// `t_center` midpoint buckets from `Cut` entries with absolute-pixel
/// start/end coordinates. Mirrors `gate_spans_per_edge` in
/// `enclosure.rs` (which takes Gate triples) — Phase 1.20 adds this
/// Cut-driven variant so the new ExteriorWallOp dispatch can feed
/// the shared `render_enclosure_polygon` renderer.
fn gate_spans_per_edge_from_cuts(
    polygon: &[(f32, f32)],
    cuts: &[Cut<'_>],
) -> (Vec<Vec<(f32, f32)>>, Vec<Vec<f32>>) {
    let n = polygon.len();
    let mut by_edge: Vec<Vec<(f32, f32)>> = vec![Vec::new(); n];
    let mut midpoints: Vec<Vec<f32>> = vec![Vec::new(); n];
    if n < 2 {
        return (by_edge, midpoints);
    }
    for cut in cuts.iter() {
        let s = match cut.start() {
            Some(p) => p,
            None => continue,
        };
        let e = match cut.end() {
            Some(p) => p,
            None => continue,
        };
        let mx = (s.x() + e.x()) / 2.0;
        let my = (s.y() + e.y()) / 2.0;
        // Find the closest polygon edge to the midpoint.
        let mut best_edge: Option<usize> = None;
        let mut best_dist = f32::INFINITY;
        let mut best_t = 0.5_f32;
        let mut best_half_t = 0.0_f32;
        for i in 0..n {
            let a = polygon[i];
            let b = polygon[(i + 1) % n];
            let dx = b.0 - a.0;
            let dy = b.1 - a.1;
            let edge_len_sq = dx * dx + dy * dy;
            if edge_len_sq < 1e-12 {
                continue;
            }
            let t = ((mx - a.0) * dx + (my - a.1) * dy) / edge_len_sq;
            if !(0.0..=1.0).contains(&t) {
                continue;
            }
            let projx = a.0 + t * dx;
            let projy = a.1 + t * dy;
            let dist_sq =
                (mx - projx).powi(2) + (my - projy).powi(2);
            if dist_sq < best_dist {
                best_dist = dist_sq;
                best_edge = Some(i);
                best_t = t;
                let edge_len = edge_len_sq.sqrt();
                let half_px = (
                    (s.x() - mx).powi(2) + (s.y() - my).powi(2)
                ).sqrt();
                best_half_t = half_px / edge_len;
            }
        }
        if let Some(edge_idx) = best_edge {
            let lo = (best_t - best_half_t).max(0.0);
            let hi = (best_t + best_half_t).min(1.0);
            if hi > lo {
                by_edge[edge_idx].push((lo, hi));
                midpoints[edge_idx].push(best_t);
            }
        }
    }
    (by_edge, midpoints)
}

/// DungeonInk exterior wall — stroke the outline with optional Cut gaps.
fn draw_dungeon_ink(
    outline: &Outline<'_>,
    cuts: &[Cut<'_>],
    ctx: &mut RasterCtx<'_>,
) {
    match outline.descriptor_kind() {
        OutlineKind::Circle => draw_dungeon_ink_circle(outline, cuts, ctx),
        OutlineKind::Pill => draw_dungeon_ink_pill(outline, ctx),
        OutlineKind::Polygon | _ => draw_dungeon_ink_polygon(outline, cuts, ctx),
    }
}

/// Polygon DungeonInk — walk outline vertices with Cut gaps.
///
/// Mirrors `_draw_exterior_wall_op_from_ir` DungeonInk Polygon branch:
/// - 4-vertex (rect room): apply ALL cuts.
/// - > 4 vertices (smooth room): apply only `CutStyle::None` cuts.
fn draw_dungeon_ink_polygon(
    outline: &Outline<'_>,
    cuts: &[Cut<'_>],
    ctx: &mut RasterCtx<'_>,
) {
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 2 => v,
        _ => return,
    };

    let coords: Vec<(f32, f32)> = verts
        .iter()
        .map(|v| (v.x(), v.y()))
        .collect();
    let n = coords.len();

    // For smooth (> 4 vertex) polygons, only None_ cuts create gaps.
    let active_cuts: Vec<_> = if n > 4 {
        cuts.iter()
            .filter(|c| c.style() == CutStyle::None)
            .cloned()
            .collect()
    } else {
        cuts.to_vec()
    };

    let d = walk_polygon_with_cuts(&coords, &active_cuts);
    if d.is_empty() {
        return;
    }
    // Build path from "M{x},{y} L{x},{y}" style d-string.
    if let Some(path) = build_path_from_ml_segments(&d) {
        ctx.pixmap
            .stroke_path(&path, &ink_paint(), &wall_stroke(), ctx.transform, None);
    }
}

/// Circle DungeonInk — parametric arc with Cut gaps.
fn draw_dungeon_ink_circle(
    outline: &Outline<'_>,
    cuts: &[Cut<'_>],
    ctx: &mut RasterCtx<'_>,
) {
    let cx = outline.cx();
    let cy = outline.cy();
    let r = outline.rx();
    if r <= 0.0 {
        return;
    }

    let none_cuts: Vec<_> = cuts
        .iter()
        .filter(|c| c.style() == CutStyle::None)
        .cloned()
        .collect();

    if none_cuts.is_empty() {
        // Closed circle — draw via oval.
        let rect = match Rect::from_xywh(cx - r, cy - r, r * 2.0, r * 2.0) {
            Some(rect) => rect,
            None => return,
        };
        let mut pb = PathBuilder::new();
        pb.push_oval(rect);
        let path = match pb.finish() {
            Some(p) => p,
            None => return,
        };
        ctx.pixmap
            .stroke_path(&path, &ink_paint(), &wall_stroke(), ctx.transform, None);
        return;
    }

    // Gapped circle: arc segments with None_ cuts removed.
    let two_pi = 2.0 * PI32;
    let mut gap_intervals: Vec<(f32, f32)> = Vec::new();

    for cut in &none_cuts {
        let (ax, ay, bx, by) = match cut_endpoints(cut) {
            Some(ep) => ep,
            None => continue,
        };
        let a1 = (ay - cy).atan2(ax - cx).rem_euclid(two_pi);
        let a2 = (by - cy).atan2(bx - cx).rem_euclid(two_pi);
        let (a1, a2) = if a1 <= a2 { (a1, a2) } else { (a2, a1) };
        let span = a2 - a1;
        if span > PI32 {
            gap_intervals.push((a2, a1 + two_pi));
        } else {
            gap_intervals.push((a1, a2));
        }
    }
    gap_intervals.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    let n_gi = gap_intervals.len();
    let mut pb = PathBuilder::new();

    for gi_idx in 0..n_gi {
        let gap_end = gap_intervals[gi_idx].1;
        let next_start = if gi_idx == n_gi - 1 {
            gap_intervals[0].0 + two_pi
        } else {
            gap_intervals[gi_idx + 1].0
        };
        if next_start <= gap_end {
            continue;
        }
        let sx = cx + r * gap_end.cos();
        let sy = cy + r * gap_end.sin();
        let ex = cx + r * next_start.cos();
        let ey = cy + r * next_start.sin();
        let sweep = (next_start - gap_end).rem_euclid(two_pi);
        pb.move_to(sx, sy);
        // Approximate arc with cubic Bézier segments.
        push_arc(&mut pb, cx, cy, r, gap_end, gap_end + sweep);
        let _ = (ex, ey); // ex/ey come from the arc endpoint
    }

    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    ctx.pixmap
        .stroke_path(&path, &ink_paint(), &wall_stroke(), ctx.transform, None);
}

/// Pill DungeonInk — stroked rounded-rect matching `<rect rx ry>` SVG.
fn draw_dungeon_ink_pill(
    outline: &Outline<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let cx = outline.cx();
    let cy = outline.cy();
    let rx = outline.rx();
    let ry = outline.ry();
    if rx <= 0.0 || ry <= 0.0 {
        return;
    }
    let r = rx.min(ry);
    let x0 = cx - rx;
    let y0 = cy - ry;
    let x1 = cx + rx;
    let y1 = cy + ry;
    const KAPPA: f32 = 0.5523;
    let k = r * KAPPA;
    let mut pb = PathBuilder::new();
    pb.move_to(x0 + r, y0);
    pb.line_to(x1 - r, y0);
    pb.cubic_to(x1 - r + k, y0, x1, y0 + r - k, x1, y0 + r);
    pb.line_to(x1, y1 - r);
    pb.cubic_to(x1, y1 - r + k, x1 - r + k, y1, x1 - r, y1);
    pb.line_to(x0 + r, y1);
    pb.cubic_to(x0 + r - k, y1, x0, y1 - r + k, x0, y1 - r);
    pb.line_to(x0, y0 + r);
    pb.cubic_to(x0, y0 + r - k, x0 + r - k, y0, x0 + r, y0);
    pb.close();
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    ctx.pixmap
        .stroke_path(&path, &ink_paint(), &wall_stroke(), ctx.transform, None);
}

/// CaveInk exterior wall — run the cave pipeline and stroke the result.
fn draw_cave_ink(
    outline: &Outline<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 4 => v,
        _ => return,
    };
    let coords: Vec<(f64, f64)> = verts
        .iter()
        .map(|v| (v.x() as f64, v.y() as f64))
        .collect();

    let path_svg = cave_path_from_outline(&coords, fir.base_seed());
    // Extract d=... from <path d="..."/>.
    let d = match extract_d_from_path_svg(&path_svg) {
        Some(d) if !d.is_empty() => d,
        _ => return,
    };
    let path = match parse_path_d(d) {
        Some(p) => p,
        None => return,
    };
    ctx.pixmap
        .stroke_path(&path, &ink_paint(), &wall_stroke(), ctx.transform, None);
}

// ── Cut handling ────────────────────────────────────────────────────────

/// Extract (ax, ay, bx, by) from a Cut's start/end Vec2 fields.
fn cut_endpoints(cut: &Cut<'_>) -> Option<(f32, f32, f32, f32)> {
    let s = cut.start()?;
    let e = cut.end()?;
    Some((s.x(), s.y(), e.x(), e.y()))
}

/// Walk a closed polygon, emitting `M{x} {y} L{x} {y}` segments for
/// the portions outside any cut interval.
///
/// Returns a space-separated path string. Mirrors `_walk_polygon_with_cuts`
/// in `ir_to_svg.py`. Coordinates formatted with `.1f` precision.
#[allow(unused_assignments)]
fn walk_polygon_with_cuts(
    polygon: &[(f32, f32)],
    cuts: &[Cut<'_>],
) -> String {
    let n = polygon.len();
    if n < 2 {
        return String::new();
    }

    let mut d_parts: Vec<String> = Vec::new();
    let mut in_stroke = false;
    let mut current_x = 0.0_f32;
    let mut current_y = 0.0_f32;

    for i in 0..n {
        let (ax, ay) = polygon[i];
        let (bx, by) = polygon[(i + 1) % n];
        let dx = bx - ax;
        let dy = by - ay;
        let edge_len = dx.hypot(dy);
        if edge_len < 1e-6 {
            continue;
        }

        // Compute cut intervals for this edge.
        let edge_cuts = cuts_for_edge(ax, ay, bx, by, cuts);
        let mut merged: Vec<(f32, f32)> = Vec::new();
        for (lo, hi) in edge_cuts {
            if let Some(last) = merged.last_mut() {
                if lo <= last.1 + 1e-6 {
                    last.1 = last.1.max(hi);
                    continue;
                }
            }
            merged.push((lo, hi));
        }

        let mut t = 0.0_f32;
        for (lo_t, hi_t) in &merged {
            if lo_t > &(t + 1e-6) {
                let x0 = ax + t * dx;
                let y0 = ay + t * dy;
                let x1 = ax + lo_t * dx;
                let y1 = ay + lo_t * dy;
                if !in_stroke
                    || (x0 - current_x).abs() > 1e-4
                    || (y0 - current_y).abs() > 1e-4
                {
                    d_parts.push(format!("M{x0:.1},{y0:.1}"));
                }
                d_parts.push(format!("L{x1:.1},{y1:.1}"));
                current_x = x1;
                current_y = y1;
                in_stroke = true;
            }
            t = *hi_t;
            in_stroke = false;
        }

        if t < 1.0 - 1e-6 {
            let x0 = ax + t * dx;
            let y0 = ay + t * dy;
            if !in_stroke
                || (x0 - current_x).abs() > 1e-4
                || (y0 - current_y).abs() > 1e-4
            {
                d_parts.push(format!("M{x0:.1},{y0:.1}"));
            }
            d_parts.push(format!("L{bx:.1},{by:.1}"));
            current_x = bx;
            current_y = by;
            in_stroke = true;
        } else {
            in_stroke = false;
        }
    }

    d_parts.join(" ")
}

/// Project each Cut onto edge (a→b) and return parametric `(lo_t, hi_t)`
/// intervals. Mirrors `_cuts_for_edge` in `ir_to_svg.py`.
fn cuts_for_edge(
    ax: f32,
    ay: f32,
    bx: f32,
    by: f32,
    cuts: &[Cut<'_>],
) -> Vec<(f32, f32)> {
    let dx = bx - ax;
    let dy = by - ay;
    let edge_len = dx.hypot(dy);
    if edge_len < 1e-6 {
        return Vec::new();
    }
    let ux = dx / edge_len;
    let uy = dy / edge_len;
    // Perpendicular unit vector.
    let px = -uy;
    let py = ux;

    let mut result = Vec::new();
    for cut in cuts {
        let (sx, sy, ex, ey) = match cut_endpoints(cut) {
            Some(ep) => ep,
            None => continue,
        };
        let mx = (sx + ex) / 2.0;
        let my = (sy + ey) / 2.0;
        let perp_dist = ((mx - ax) * px + (my - ay) * py).abs();
        if perp_dist > 4.0 {
            continue;
        }
        let ts = ((sx - ax) * ux + (sy - ay) * uy) / edge_len;
        let te = ((ex - ax) * ux + (ey - ay) * uy) / edge_len;
        let lo_t = ts.min(te);
        let hi_t = ts.max(te);
        const TOL: f32 = 0.05;
        if hi_t < -TOL || lo_t > 1.0 + TOL {
            continue;
        }
        let lo_t = lo_t.max(0.0);
        let hi_t = hi_t.min(1.0);
        if hi_t > lo_t {
            result.push((lo_t, hi_t));
        }
    }
    result.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    result
}

/// Build a tiny-skia `Path` from a space-separated `M{x},{y} L{x},{y}...`
/// string (the format produced by `walk_polygon_with_cuts`).
fn build_path_from_ml_segments(d: &str) -> Option<tiny_skia::Path> {
    let mut pb = PathBuilder::new();
    let mut any = false;
    // Parse tokens: alternating M and L commands.
    let mut iter = d.split_whitespace();
    while let Some(tok) = iter.next() {
        if tok.starts_with('M') {
            let rest = &tok[1..];
            if let Some((x, y)) = parse_xy_f32(rest) {
                pb.move_to(x, y);
            }
        } else if tok.starts_with('L') {
            let rest = &tok[1..];
            if let Some((x, y)) = parse_xy_f32(rest) {
                pb.line_to(x, y);
                any = true;
            }
        }
    }
    if !any {
        return None;
    }
    pb.finish()
}

fn parse_xy_f32(s: &str) -> Option<(f32, f32)> {
    let comma = s.find(',')?;
    let x: f32 = s[..comma].parse().ok()?;
    let y: f32 = s[comma + 1..].parse().ok()?;
    Some((x, y))
}

/// Push an arc approximated with cubic Béziers from `angle_start` to
/// `angle_end` (in radians, CCW). The arc is split into segments of at
/// most π/2 each.
fn push_arc(pb: &mut PathBuilder, cx: f32, cy: f32, r: f32, start: f32, end: f32) {
    let two_pi = 2.0 * PI32;
    let mut remaining = end - start;
    // Normalise to (0, 2π].
    while remaining > two_pi + 1e-6 {
        remaining -= two_pi;
    }
    let n_segs = (remaining / (PI32 / 2.0)).ceil() as usize;
    let n_segs = n_segs.max(1);
    let seg_angle = remaining / n_segs as f32;
    // Bézier kappa for a circular arc of angle θ: k = (4/3)*tan(θ/4).
    let kappa = (4.0 / 3.0) * (seg_angle / 4.0).tan();
    let mut angle = start;
    for _ in 0..n_segs {
        let cos_a = angle.cos();
        let sin_a = angle.sin();
        let cos_b = (angle + seg_angle).cos();
        let sin_b = (angle + seg_angle).sin();
        let ex = cx + r * cos_b;
        let ey = cy + r * sin_b;
        pb.cubic_to(
            cx + r * (cos_a - kappa * sin_a),
            cy + r * (sin_a + kappa * cos_a),
            cx + r * (cos_b + kappa * sin_b),
            cy + r * (sin_b - kappa * cos_b),
            ex,
            ey,
        );
        angle += seg_angle;
    }
}

/// `<path d="..."/>` → the inner `d=...` string.
fn extract_d_from_path_svg(s: &str) -> Option<&str> {
    let needle = "d=\"";
    let start = s.find(needle)? + needle.len();
    let rest = &s[start..];
    let end = rest.find('"')?;
    Some(&rest[..end])
}

// ── Gating helper ───────────────────────────────────────────────────────

/// Return `true` if the IR has both a `CorridorWallOp` and at least one
/// `DungeonInk` `ExteriorWallOp` — i.e. the DungeonInk consumer is
/// active for this floor. When `true`, `walls_and_floors.rs` suppresses
/// `wall_segments` / `smooth_walls` / `wall_extensions_d`.
pub(super) fn has_dungeon_ink_wall_ops(fir: &FloorIR<'_>) -> bool {
    let ops = match fir.ops() {
        Some(o) => o,
        None => return false,
    };
    let mut has_corridor = false;
    let mut has_dungeon_ink_ext = false;
    for entry in ops.iter() {
        use crate::ir::Op;
        if entry.op_type() == Op::CorridorWallOp {
            has_corridor = true;
        } else if entry.op_type() == Op::ExteriorWallOp {
            if let Some(op) = entry.op_as_exterior_wall_op() {
                if op.style() == WallStyle::DungeonInk {
                    has_dungeon_ink_ext = true;
                }
            }
        }
    }
    has_corridor && has_dungeon_ink_ext
}

/// Return `true` if the IR has any CaveInk `ExteriorWallOp`.
#[allow(dead_code)]
pub(super) fn has_cave_ink_wall_op(fir: &FloorIR<'_>) -> bool {
    let ops = match fir.ops() {
        Some(o) => o,
        None => return false,
    };
    use crate::ir::Op;
    ops.iter().any(|entry| {
        if entry.op_type() != Op::ExteriorWallOp {
            return false;
        }
        entry
            .op_as_exterior_wall_op()
            .map(|op| op.style() == WallStyle::CaveInk)
            .unwrap_or(false)
    })
}

/// Return `true` if the IR has any `InteriorWallOp` with an in-scope
/// style. When `true`, the legacy `BuildingInteriorWallOp` handler
/// suppresses itself.
#[allow(dead_code)]
pub(super) fn has_interior_wall_ops(fir: &FloorIR<'_>) -> bool {
    let ops = match fir.ops() {
        Some(o) => o,
        None => return false,
    };
    use crate::ir::Op;
    ops.iter().any(|entry| entry.op_type() == Op::InteriorWallOp)
}

#[cfg(test)]
mod tests {
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, Cut, CutArgs, CutStyle, ExteriorWallOp,
        ExteriorWallOpArgs, FloorIR, FloorIRArgs, Op, OpEntry, OpEntryArgs,
        Outline, OutlineArgs, OutlineKind, Vec2, WallStyle,
    };
    use crate::test_util::{decode, pixel_at};
    use crate::transform::png::{floor_ir_to_png, BG_B, BG_G, BG_R};

    /// Build an IR with a single DungeonInk ExteriorWallOp covering a
    /// 4-vertex (rect) polygon outline in tile-pixel space.
    fn build_dungeon_ink_rect_buf(
        tile_x: i32, tile_y: i32, tile_w: i32, tile_h: i32,
    ) -> Vec<u8> {
        let cell = 32.0_f32;
        let x0 = tile_x as f32 * cell;
        let y0 = tile_y as f32 * cell;
        let x1 = (tile_x + tile_w) as f32 * cell;
        let y1 = (tile_y + tile_h) as f32 * cell;

        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&[
            Vec2::new(x0, y0),
            Vec2::new(x1, y0),
            Vec2::new(x1, y1),
            Vec2::new(x0, y1),
        ]);
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let wall_op = ExteriorWallOp::create(
            &mut fbb,
            &ExteriorWallOpArgs {
                outline: Some(outline),
                style: WallStyle::DungeonInk,
                ..Default::default()
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::ExteriorWallOp,
                op: Some(wall_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// Build an IR with a single DungeonInk ExteriorWallOp using a
    /// Circle descriptor.
    fn build_dungeon_ink_circle_buf(cx: f32, cy: f32, r: f32) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                descriptor_kind: OutlineKind::Circle,
                cx,
                cy,
                rx: r,
                ry: r,
                closed: true,
                ..Default::default()
            },
        );
        let wall_op = ExteriorWallOp::create(
            &mut fbb,
            &ExteriorWallOpArgs {
                outline: Some(outline),
                style: WallStyle::DungeonInk,
                ..Default::default()
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::ExteriorWallOp,
                op: Some(wall_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// Build a DungeonInk Pill ExteriorWallOp.
    fn build_dungeon_ink_pill_buf(
        cx: f32, cy: f32, rx: f32, ry: f32,
    ) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                descriptor_kind: OutlineKind::Pill,
                cx,
                cy,
                rx,
                ry,
                closed: true,
                ..Default::default()
            },
        );
        let wall_op = ExteriorWallOp::create(
            &mut fbb,
            &ExteriorWallOpArgs {
                outline: Some(outline),
                style: WallStyle::DungeonInk,
                ..Default::default()
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::ExteriorWallOp,
                op: Some(wall_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    // ── DungeonInk polygon (full outline, no cuts) ──────────────────────

    #[test]
    fn wall_op_paints_full_outline_when_no_cuts_dungeon_ink_polygon() {
        // 4×4 tile rect — border should be black, interior BG.
        let buf = build_dungeon_ink_rect_buf(1, 1, 4, 4);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // Top edge midpoint: canvas y = 32 + 1*32 = 64, x = 32 + 3*32 = 128.
        let (r, g, b) = pixel_at(&pixmap, 128, 64);
        assert_ne!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "wall stroke should paint over background at top-edge midpoint"
        );
    }

    // ── DungeonInk polygon with cut (gap in stroke) ─────────────────────

    #[test]
    fn wall_op_skips_stroke_in_cut_interval() {
        // Build a 4-vertex rect with one Cut gap on the top edge.
        // The top edge runs from (1*32, 1*32) to (5*32, 1*32).
        // Cut: top edge from x=2*32 to x=3*32 (one tile gap).
        let cell = 32.0_f32;
        let x0 = cell;
        let y0 = cell;
        let x1 = 5.0 * cell;
        let y1 = 5.0 * cell;
        let cut_x0 = 2.0 * cell;
        let cut_x1 = 3.0 * cell;

        let mut fbb = FlatBufferBuilder::new();
        let cut = Cut::create(
            &mut fbb,
            &CutArgs {
                start: Some(&Vec2::new(cut_x0, y0)),
                end: Some(&Vec2::new(cut_x1, y0)),
                style: CutStyle::None, // corridor opening gap
            },
        );
        let cuts = fbb.create_vector(&[cut]);
        let verts = fbb.create_vector(&[
            Vec2::new(x0, y0),
            Vec2::new(x1, y0),
            Vec2::new(x1, y1),
            Vec2::new(x0, y1),
        ]);
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(verts),
                cuts: Some(cuts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let wall_op = ExteriorWallOp::create(
            &mut fbb,
            &ExteriorWallOpArgs {
                outline: Some(outline),
                style: WallStyle::DungeonInk,
                ..Default::default()
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::ExteriorWallOp,
                op: Some(wall_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        let buf = fbb.finished_data().to_vec();
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);

        // At cut midpoint: (2.5*32, 1*32) in tile space → (32+80, 32+32)
        // = (112, 64) canvas. Should remain background (gap in stroke).
        let (r, g, b) = pixel_at(&pixmap, 112, 64);
        assert_eq!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "pixel inside cut gap should remain background"
        );

        // Outside the cut: (1.5*32, 1*32) tile → (80, 64) canvas.
        // Should be inked.
        let (r2, g2, b2) = pixel_at(&pixmap, 80, 64);
        assert_ne!(
            (r2, g2, b2),
            (BG_R, BG_G, BG_B),
            "pixel outside cut should be painted by wall stroke"
        );
    }

    // ── DungeonInk Circle descriptor ────────────────────────────────────

    #[test]
    fn wall_op_circle_descriptor_renders_via_arc() {
        // Circle in tile-pixel space, centred at tile (4,4).
        let cell = 32.0_f32;
        let cx = 4.0 * cell + cell / 2.0;
        let cy = 4.0 * cell + cell / 2.0;
        let r = 1.5 * cell;
        let buf = build_dungeon_ink_circle_buf(cx, cy, r);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // The stroke lands on the circle perimeter. Sample a point on the
        // right side: canvas x = 32 + cx + r, y = 32 + cy.
        // x = 32 + 144 + 48 = 224; y = 32 + 144 = 176.
        let (r_px, g, b) = pixel_at(&pixmap, 224, 176);
        assert_ne!(
            (r_px, g, b),
            (BG_R, BG_G, BG_B),
            "pixel on circle stroke should not be background"
        );
    }

    // ── DungeonInk Pill descriptor ───────────────────────────────────────

    #[test]
    fn wall_op_pill_descriptor_renders_via_arc_pair() {
        let cell = 32.0_f32;
        let cx = 4.0 * cell + cell / 2.0;
        let cy = 4.0 * cell + cell / 2.0;
        let rx = 2.0 * cell;
        let ry = 1.0 * cell;
        let buf = build_dungeon_ink_pill_buf(cx, cy, rx, ry);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // Right edge of pill at canvas x = 32 + cx + rx = 32+144+64 = 240.
        // y = 32 + cy = 32 + 144 = 176.
        let (r, g, b) = pixel_at(&pixmap, 240, 176);
        assert_ne!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "pixel on pill stroke should not be background"
        );
    }

    // ── CaveInk — cave pipeline via outline.vertices ────────────────────

    /// CaveInk ExteriorWallOp strokes the cave pipeline output.
    /// Uses a square input polygon; asserts the stroke paints something
    /// non-BG near the perimeter.
    #[test]
    fn wall_op_paints_full_outline_when_no_cuts_cave_ink() {
        let cell = 32.0_f32;
        // Simple 4×4 tile square as the "cave outline" input.
        let x0 = 2.0 * cell;
        let y0 = 2.0 * cell;
        let x1 = 6.0 * cell;
        let y1 = 6.0 * cell;

        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&[
            Vec2::new(x0, y0),
            Vec2::new(x1, y0),
            Vec2::new(x1, y1),
            Vec2::new(x0, y1),
        ]);
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let wall_op = ExteriorWallOp::create(
            &mut fbb,
            &ExteriorWallOpArgs {
                outline: Some(outline),
                style: WallStyle::CaveInk,
                ..Default::default()
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::ExteriorWallOp,
                op: Some(wall_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("cave");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 10,
                height_tiles: 10,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                base_seed: 42,
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        let buf = fbb.finished_data().to_vec();
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);

        // The cave pipeline expands and jitters the outline — at least some
        // pixels near the original perimeter should be non-background.
        let mut any_inked = false;
        for py in 50..150u32 {
            for px in 50..150u32 {
                let (r, g, b) = pixel_at(&pixmap, px, py);
                if (r, g, b) != (BG_R, BG_G, BG_B) {
                    any_inked = true;
                    break;
                }
            }
            if any_inked {
                break;
            }
        }
        assert!(any_inked, "CaveInk ExteriorWallOp should produce at least one non-background pixel");
    }

    // ── Cave pipeline seed offset ────────────────────────────────────────

    #[test]
    fn cave_pipeline_seed_offset_is_0x5a17e5() {
        use crate::geometry::CAVE_SEED_OFFSET;
        assert_eq!(CAVE_SEED_OFFSET, 0x5A17E5,
            "cave seed offset must be 0x5A17E5 to match _render_context.py:117");
    }
}
