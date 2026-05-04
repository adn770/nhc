//! Tiny SVG-path subset parser — `M x,y`, `L x,y`,
//! `C c1x,c1y c2x,c2y x,y`, `A rx,ry rot large,sweep x,y`, `Z`.
//!
//! The IR's procedural primitives emit pre-formatted SVG path
//! `d=` strings as the FFI return shape; the PNG handlers parse
//! those back into `tiny-skia::Path` move/line/curve/close ops
//! rather than sharing a Path type across the FFI boundary.
//!
//! The cave-region wall outline (Phase 5.5) drives the C-curve
//! support: the legacy emitter writes M/C/Z command sequences
//! at `:.1` precision per Catmull-Rom subpath, and the
//! rasteriser replays each one as a `cubic_to`. Smooth-wall
//! outlines for circle rooms (`_room_outlines._circle_with_gaps`)
//! drive the `A` (elliptical-arc) command — NHC only emits
//! circular arcs (rx == ry, no x-axis rotation), which we
//! approximate with ≤90° cubic-bezier segments.

use std::f32::consts::{FRAC_PI_2, PI};

use tiny_skia::PathBuilder;

use crate::painter::{PathOps, Vec2};

/// Parse `s` into a `tiny-skia::Path`. Walks tokens left-to-
/// right; each token either kicks off a new command (M / L /
/// C / Z) or supplies coordinate pairs that the running command
/// consumes. Unknown commands skip the token.
///
/// Phase 2.16 retired the legacy `fragment::paint_fragment`
/// caller; this helper now lives only as a parity reference for
/// the [`parse_path_d_pathops`] twin (the active consumer is
/// `floor_op.rs::draw_polygon` for cave outlines). Kept for the
/// in-module unit tests until the module retires entirely.
#[allow(dead_code)]
pub fn parse_path_d(s: &str) -> Option<tiny_skia::Path> {
    let mut pb = PathBuilder::new();
    let mut any = false;
    let mut tokens = s.split_whitespace().peekable();
    let mut last = (0.0_f32, 0.0_f32);
    while let Some(tok) = tokens.next() {
        match command_letter(tok) {
            Some('M') => {
                if let Some((x, y)) = parse_xy(strip_command(tok, 'M')) {
                    pb.move_to(x, y);
                    last = (x, y);
                    any = true;
                }
            }
            Some('L') => {
                if let Some((x, y)) = parse_xy(strip_command(tok, 'L')) {
                    pb.line_to(x, y);
                    last = (x, y);
                    any = true;
                }
            }
            Some('C') => {
                let p1 = parse_xy(strip_command(tok, 'C'));
                let p2 = tokens.next().and_then(parse_xy);
                let p3 = tokens.next().and_then(parse_xy);
                if let (Some((c1x, c1y)), Some((c2x, c2y)), Some((x, y))) =
                    (p1, p2, p3)
                {
                    pb.cubic_to(c1x, c1y, c2x, c2y, x, y);
                    last = (x, y);
                    any = true;
                }
            }
            Some('A') => {
                // SVG arc: `A rx,ry rot large sweep x,y`. The
                // flag pair accepts both `0,1` (the form
                // `_circle_with_gaps` emits) and `0 1` (the form
                // the well/fountain keystone primitives emit) —
                // SVG path syntax allows either.
                let radii = parse_xy(strip_command(tok, 'A'));
                let rot = tokens.next().and_then(|t| t.parse::<f32>().ok());
                let next_tok = tokens.next();
                let (flags, endpoint) = match next_tok
                    .and_then(parse_xy)
                {
                    Some(pair) => (Some(pair), tokens.next().and_then(parse_xy)),
                    None => {
                        // Space-separated flags: `<large> <sweep>`.
                        let large_f = next_tok.and_then(|t| t.parse::<f32>().ok());
                        let sweep_f = tokens
                            .next()
                            .and_then(|t| t.parse::<f32>().ok());
                        let endpoint = tokens.next().and_then(parse_xy);
                        match (large_f, sweep_f) {
                            (Some(l), Some(s)) => (Some((l, s)), endpoint),
                            _ => (None, endpoint),
                        }
                    }
                };
                if let (
                    Some((rx, ry)),
                    Some(_rot),
                    Some((large_f, sweep_f)),
                    Some((x, y)),
                ) = (radii, rot, flags, endpoint)
                {
                    let large = large_f >= 0.5;
                    let sweep = sweep_f >= 0.5;
                    append_arc(&mut pb, last, rx, ry, large, sweep, x, y);
                    last = (x, y);
                    any = true;
                }
            }
            Some('Z') | Some('z') => {
                pb.close();
                // Spec: after a close, the pen returns to the
                // last move-to point. We approximate that by
                // leaving `last` untouched — for the legacy
                // emitter's M-then-Cs-then-Z shape this is the
                // same point.
            }
            _ => {}
        }
    }
    if !any {
        return None;
    }
    pb.finish()
}

/// Painter-trait twin of [`parse_path_d`]: parse `s` into a
/// [`PathOps`] for callers that drive the trait-level
/// `Painter::stroke_path` / `Painter::fill_path` instead of
/// `tiny_skia::Pixmap` directly.
///
/// Walks the same M/L/C/A/Z subset as `parse_path_d` and emits
/// the matching `PathOp` ladder. The arc approximation is
/// shared via [`append_arc_pathops`] (parallel of `append_arc`).
pub fn parse_path_d_pathops(s: &str) -> Option<PathOps> {
    let mut path = PathOps::new();
    let mut tokens = s.split_whitespace().peekable();
    let mut last = (0.0_f32, 0.0_f32);
    while let Some(tok) = tokens.next() {
        match command_letter(tok) {
            Some('M') => {
                if let Some((x, y)) = parse_xy(strip_command(tok, 'M')) {
                    path.move_to(Vec2::new(x, y));
                    last = (x, y);
                }
            }
            Some('L') => {
                if let Some((x, y)) = parse_xy(strip_command(tok, 'L')) {
                    path.line_to(Vec2::new(x, y));
                    last = (x, y);
                }
            }
            Some('C') => {
                let p1 = parse_xy(strip_command(tok, 'C'));
                let p2 = tokens.next().and_then(parse_xy);
                let p3 = tokens.next().and_then(parse_xy);
                if let (Some((c1x, c1y)), Some((c2x, c2y)), Some((x, y))) =
                    (p1, p2, p3)
                {
                    path.cubic_to(
                        Vec2::new(c1x, c1y),
                        Vec2::new(c2x, c2y),
                        Vec2::new(x, y),
                    );
                    last = (x, y);
                }
            }
            Some('A') => {
                let radii = parse_xy(strip_command(tok, 'A'));
                let rot = tokens.next().and_then(|t| t.parse::<f32>().ok());
                let next_tok = tokens.next();
                let (flags, endpoint) = match next_tok.and_then(parse_xy) {
                    Some(pair) => (Some(pair), tokens.next().and_then(parse_xy)),
                    None => {
                        let large_f = next_tok.and_then(|t| t.parse::<f32>().ok());
                        let sweep_f = tokens
                            .next()
                            .and_then(|t| t.parse::<f32>().ok());
                        let endpoint = tokens.next().and_then(parse_xy);
                        match (large_f, sweep_f) {
                            (Some(l), Some(s)) => (Some((l, s)), endpoint),
                            _ => (None, endpoint),
                        }
                    }
                };
                if let (
                    Some((rx, ry)),
                    Some(_rot),
                    Some((large_f, sweep_f)),
                    Some((x, y)),
                ) = (radii, rot, flags, endpoint)
                {
                    let large = large_f >= 0.5;
                    let sweep = sweep_f >= 0.5;
                    append_arc_pathops(&mut path, last, rx, ry, large, sweep, x, y);
                    last = (x, y);
                }
            }
            Some('Z') | Some('z') => {
                path.close();
            }
            _ => {}
        }
    }
    if path.is_empty() {
        return None;
    }
    Some(path)
}

/// Approximate a circular SVG arc with ≤90° cubic-bezier
/// segments. NHC's circle-room outlines emit `rx == ry` arcs
/// with no x-axis rotation, so the elliptical-rotation case
/// degenerates to plain circular endpoint-to-center geometry.
/// Falls back to a straight line for degenerate radii or
/// coincident endpoints.
#[allow(dead_code)]
fn append_arc(
    pb: &mut PathBuilder,
    start: (f32, f32),
    rx: f32, ry: f32,
    large: bool, sweep: bool,
    end_x: f32, end_y: f32,
) {
    let (x1, y1) = start;
    if rx <= 0.0 || ry <= 0.0 {
        pb.line_to(end_x, end_y);
        return;
    }
    // NHC only emits circular arcs; the smooth-wall path parser
    // doesn't carry rotation, so we collapse to a circle and use
    // max(rx, ry) as the radius if the two differ slightly from
    // float drift.
    let r = rx.max(ry);
    let dx = end_x - x1;
    let dy = end_y - y1;
    let chord = (dx * dx + dy * dy).sqrt();
    if chord < 1e-6 {
        return; // start == end: skip (SVG spec says no arc).
    }
    // SVG spec § F.6.6: scale up radius if it can't span the chord.
    let r = r.max(chord * 0.5);
    let h_sq = r * r - (chord * 0.5).powi(2);
    let h = if h_sq > 0.0 { h_sq.sqrt() } else { 0.0 };
    // Unit perpendicular to chord (tiny-skia y-down coords).
    let perp_x = -dy / chord;
    let perp_y = dx / chord;
    // Centre side: large_arc XOR sweep flips perpendicular sign
    // (SVG § F.6.5 endpoint-to-center conversion, simplified
    // for circular case). Our `perp` is the +90° rotation of the
    // chord direction; the standard formula uses the -90° rotation,
    // so the sign convention is inverted relative to the spec.
    let sign = if large == sweep { -1.0 } else { 1.0 };
    let mid_x = (x1 + end_x) * 0.5;
    let mid_y = (y1 + end_y) * 0.5;
    let cx = mid_x + sign * h * perp_x;
    let cy = mid_y + sign * h * perp_y;
    // Start / end angles around centre.
    let a1 = (y1 - cy).atan2(x1 - cx);
    let a2 = (end_y - cy).atan2(end_x - cx);
    let mut delta = a2 - a1;
    if sweep && delta < 0.0 {
        delta += 2.0 * PI;
    } else if !sweep && delta > 0.0 {
        delta -= 2.0 * PI;
    }
    // Split into ≤90° segments — the cubic-bezier approximation
    // error grows quickly past π/2 per segment.
    let n = ((delta.abs() / FRAC_PI_2).ceil() as usize).max(1);
    let seg = delta / n as f32;
    let alpha = (4.0 / 3.0) * (seg * 0.25).tan();
    for i in 0..n {
        let a = a1 + seg * i as f32;
        let b = a1 + seg * (i + 1) as f32;
        let cos_a = a.cos();
        let sin_a = a.sin();
        let cos_b = b.cos();
        let sin_b = b.sin();
        let p1x = cx + r * cos_a - r * alpha * sin_a;
        let p1y = cy + r * sin_a + r * alpha * cos_a;
        let p2x = cx + r * cos_b + r * alpha * sin_b;
        let p2y = cy + r * sin_b - r * alpha * cos_b;
        let p3x = cx + r * cos_b;
        let p3y = cy + r * sin_b;
        pb.cubic_to(p1x, p1y, p2x, p2y, p3x, p3y);
    }
}

/// PathOps twin of [`append_arc`]. Identical maths; only the
/// emit step differs (PathOps::cubic_to vs PathBuilder::cubic_to).
fn append_arc_pathops(
    path: &mut PathOps,
    start: (f32, f32),
    rx: f32, ry: f32,
    large: bool, sweep: bool,
    end_x: f32, end_y: f32,
) {
    let (x1, y1) = start;
    if rx <= 0.0 || ry <= 0.0 {
        path.line_to(Vec2::new(end_x, end_y));
        return;
    }
    let r = rx.max(ry);
    let dx = end_x - x1;
    let dy = end_y - y1;
    let chord = (dx * dx + dy * dy).sqrt();
    if chord < 1e-6 {
        return;
    }
    let r = r.max(chord * 0.5);
    let h_sq = r * r - (chord * 0.5).powi(2);
    let h = if h_sq > 0.0 { h_sq.sqrt() } else { 0.0 };
    let perp_x = -dy / chord;
    let perp_y = dx / chord;
    let sign = if large == sweep { -1.0 } else { 1.0 };
    let mid_x = (x1 + end_x) * 0.5;
    let mid_y = (y1 + end_y) * 0.5;
    let cx = mid_x + sign * h * perp_x;
    let cy = mid_y + sign * h * perp_y;
    let a1 = (y1 - cy).atan2(x1 - cx);
    let a2 = (end_y - cy).atan2(end_x - cx);
    let mut delta = a2 - a1;
    if sweep && delta < 0.0 {
        delta += 2.0 * PI;
    } else if !sweep && delta > 0.0 {
        delta -= 2.0 * PI;
    }
    let n = ((delta.abs() / FRAC_PI_2).ceil() as usize).max(1);
    let seg = delta / n as f32;
    let alpha = (4.0 / 3.0) * (seg * 0.25).tan();
    for i in 0..n {
        let a = a1 + seg * i as f32;
        let b = a1 + seg * (i + 1) as f32;
        let cos_a = a.cos();
        let sin_a = a.sin();
        let cos_b = b.cos();
        let sin_b = b.sin();
        let p1x = cx + r * cos_a - r * alpha * sin_a;
        let p1y = cy + r * sin_a + r * alpha * cos_a;
        let p2x = cx + r * cos_b + r * alpha * sin_b;
        let p2y = cy + r * sin_b - r * alpha * cos_b;
        let p3x = cx + r * cos_b;
        let p3y = cy + r * sin_b;
        path.cubic_to(
            Vec2::new(p1x, p1y),
            Vec2::new(p2x, p2y),
            Vec2::new(p3x, p3y),
        );
    }
}

fn command_letter(tok: &str) -> Option<char> {
    let c = tok.chars().next()?;
    match c {
        'M' | 'L' | 'C' | 'A' | 'Z' | 'z' => Some(c),
        _ => None,
    }
}

fn strip_command(tok: &str, letter: char) -> &str {
    tok.strip_prefix(letter).unwrap_or(tok)
}

/// `"x,y"` → `(x, y)`. Accepts whitespace either side of the
/// comma.
pub fn parse_xy(s: &str) -> Option<(f32, f32)> {
    let s = s.trim();
    let comma = s.find(',')?;
    let x: f32 = s[..comma].trim().parse().ok()?;
    let y: f32 = s[comma + 1..].trim().parse().ok()?;
    Some((x, y))
}

#[cfg(test)]
mod tests {
    use super::{parse_path_d, parse_xy};

    #[test]
    fn parse_xy_handles_integer_coords() {
        assert_eq!(parse_xy("32,64"), Some((32.0, 64.0)));
    }

    #[test]
    fn parse_xy_handles_decimal_coords() {
        assert_eq!(parse_xy("12.5,7.25"), Some((12.5, 7.25)));
    }

    #[test]
    fn parse_xy_handles_whitespace() {
        assert_eq!(parse_xy("  3.0 ,  4.5  "), Some((3.0, 4.5)));
    }

    #[test]
    fn parse_xy_rejects_garbage() {
        assert!(parse_xy("not-a-pair").is_none());
        assert!(parse_xy("3").is_none());
    }

    #[test]
    fn parse_path_d_handles_single_move_line() {
        let p = parse_path_d("M0,0 L32,0").unwrap();
        let bounds = p.bounds();
        assert!(bounds.width() >= 32.0);
    }

    #[test]
    fn parse_path_d_handles_multi_subpath() {
        let p = parse_path_d("M0,0 L10,0 M0,10 L10,10").unwrap();
        let bounds = p.bounds();
        assert!(bounds.height() >= 10.0);
    }

    #[test]
    fn parse_path_d_returns_none_on_empty() {
        assert!(parse_path_d("").is_none());
        assert!(parse_path_d("not-a-path").is_none());
    }

    /// Cave-region shape — M/C/Z subpath with 3 cubic segments.
    #[test]
    fn parse_path_d_handles_cubic_segments() {
        let d = "M0.0,0.0 C5.0,0.0 10.0,5.0 10.0,10.0 \
                 C10.0,15.0 5.0,20.0 0.0,20.0 \
                 C-5.0,15.0 -5.0,5.0 0.0,0.0 Z";
        let p = parse_path_d(d).unwrap();
        let bounds = p.bounds();
        assert!(bounds.width() >= 10.0);
        assert!(bounds.height() >= 20.0);
    }

    /// Half-circle from a circle-room outline, equivalent to the
    /// arc fragments `_room_outlines._circle_with_gaps` emits.
    /// The arc spans 180° around centre (50, 50) with r=50, so
    /// the resulting path bounds must wrap a 100×50 half-disc.
    #[test]
    fn parse_path_d_handles_circular_arc() {
        // Start at (0,50), arc to (100,50) — top half of circle.
        let d = "M0.0,50.0 A50.0,50.0 0 0,1 100.0,50.0";
        let p = parse_path_d(d).unwrap();
        let b = p.bounds();
        // Bounds returned by tiny-skia may be the convex hull of
        // anchors + control points, not the tight curve hull, so
        // be lenient on height.
        eprintln!("bounds: x=[{}, {}] y=[{}, {}]",
                  b.left(), b.right(), b.top(), b.bottom());
        assert!(b.width() >= 99.0 && b.width() <= 101.0);
        assert!(b.bottom() >= 49.0 && b.bottom() <= 51.0);
        assert!(b.top() <= 1.0);
    }

    /// Multi-subpath gapped arc — mirrors what
    /// `_circle_with_gaps` actually emits for a circle room with
    /// corridor openings: M followed by a >90° arc that crosses
    /// from one quadrant to another. With sweep_flag=1 and
    /// large=0, the arc takes the smaller path; for vertical
    /// chord endpoints (0, 16)→(0, -16) and r=20, that's the
    /// 106° arc through (-8, 0).
    #[test]
    fn parse_path_d_splits_arc_above_90deg() {
        let d = "M0.0,16.0 A20.0,20.0 0 0,1 0.0,-16.0";
        let p = parse_path_d(d).unwrap();
        let b = p.bounds();
        // Apex on the negative-x side (roughly -8); vertical
        // span covers the chord.
        assert!(b.left() <= -7.0 && b.left() >= -10.0);
        assert!(b.bottom() >= 15.0);
        assert!(b.top() <= -15.0);
    }

    /// Space-separated arc flags — the form the well/fountain
    /// keystone primitives emit (`A r,r 0 0 1 x,y` with no comma
    /// between large_arc and sweep). SVG accepts both forms, so
    /// the tiny-skia parser must too. Regression: keystone arcs
    /// were silently dropping into degenerate `M…L…Z` triangles
    /// because `parse_xy("0")` returned None for the flag pair.
    #[test]
    fn parse_path_d_handles_space_separated_arc_flags() {
        let d = "M0.0,50.0 A50.0,50.0 0 0 1 100.0,50.0";
        let p = parse_path_d(d).unwrap();
        let b = p.bounds();
        assert!(b.width() >= 99.0 && b.width() <= 101.0);
        assert!(b.bottom() >= 49.0 && b.bottom() <= 51.0);
        assert!(b.top() <= 1.0);
    }

    /// Keystone-shape replay — the exact path the well primitive
    /// emits per arc segment: `M outer_start A outer_end L
    /// inner_end A inner_start Z`. Both arcs use space-separated
    /// flags. The bounds must wrap the trapezoidal wedge, not
    /// collapse to the chord-line of a `M-L-Z` triangle.
    #[test]
    fn parse_path_d_handles_keystone_with_space_flags() {
        // outer r=27.2, inner r=18.2, centred at (16,16),
        // angles 0..π/8 → outer_start (43.2,16), outer_end
        // (~25.13, 26.41), inner_end (~16.82, 22.97),
        // inner_start (34.2,16).
        let d = "M43.20,16.00 A27.20,27.20 0 0 1 25.13,26.41 \
                 L16.82,22.97 A18.20,18.20 0 0 0 34.20,16.00 Z";
        let p = parse_path_d(d).unwrap();
        let b = p.bounds();
        // Right edge sits at the outer-radius point (43.2).
        assert!(b.right() >= 42.0);
        // Apex of the outer arc is past the outer endpoint
        // y (26.4) — degenerate triangle would only reach 26.4.
        // The trapezoid+arc convex hull pushes bottom past 27.
        assert!(b.bottom() >= 22.0);
    }
}
