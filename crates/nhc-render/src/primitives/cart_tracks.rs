//! Cart-tracks decorator — Phase 4, sub-step 11 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13f of
//! `plans/nhc_pure_ir_plan.md` (the **sixth decorator port**;
//! ore_deposit follows as 2.13g).
//!
//! Reproduces ``CART_TRACK_RAILS`` (two parallel rails per
//! TRACK tile) and ``CART_TRACK_TIES`` (single cross-tie per
//! TRACK tile) from ``nhc/rendering/_floor_detail.py``. Both
//! decorators share the same predicate; orientation per tile
//! comes from the IR's pre-resolved
//! ``CartTracksVariant.is_horizontal[]`` parallel array
//! (legacy ``_track_horizontal_at`` looks at the east / west
//! neighbours for TRACK adjacency — the emitter lifts that
//! check so the consumer doesn't need level access).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. RNG-free painters
//! (geometry is fully determined by tile + orientation), so the
//! Painter and SVG paths emit identical stamp counts without
//! needing lock-step RNG.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_cart_tracks` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until
//!   2.17 ships the `SvgPainter`-based PyO3 export and 2.19
//!   retires the Python `ir_to_svg` path).
//! - The new `paint_cart_tracks` Painter-based emitter (used by
//!   the Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `cart_tracks_shapes` shape-stream
//! generator. RNG-free, so consumption order doesn't carry a
//! lock-step contract — but keeping the single source of truth
//! mirrors the pattern from cobblestone / brick / flagstone /
//! opus_romano / field_stone.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps its output in TWO sibling groups:
//! `<g id="cart-tracks" opacity="0.55">` for rails and
//! `<g id="cart-track-ties" opacity="0.5">` for ties. The pre-
//! 2.13f PNG handler dispatched to `paint_fragments`, which
//! routed each `<g opacity>` envelope through
//! `paint_offscreen_group` (Phase 5.10's offscreen-buffer
//! composite). The Painter port replaces the SVG-string round-
//! trip with two native `begin_group(opacity) / end_group()`
//! pairs (one per bucket) so the Painter trait owns the
//! offscreen-buffer mechanism end-to-end. PNG output should be
//! pixel-equal with the pre-port PNG references — only the
//! intermediate SVG-string emission disappears.

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, Stroke, Vec2,
};

const CELL: f64 = 32.0;
const TRACK_RAIL: &str = "#6A5A4A";
const TRACK_TIE: &str = "#8A7A5A";

/// Group-opacity envelope for the rails bucket. Lifts the
/// `<g id="cart-tracks" opacity="0.55">` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const RAIL_OPACITY: f32 = 0.55;
/// Group-opacity envelope for the ties bucket. Lifts the
/// `<g id="cart-track-ties" opacity="0.5">` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const TIE_OPACITY: f32 = 0.5;

const RAIL_WIDTH: f32 = 0.9;
const TIE_WIDTH: f32 = 1.4;

/// Per-tile geometry record — backend-agnostic. Two rail lines
/// + one tie line per tile, with start / end coords resolved
/// from `(x, y, horizontal)`. The legacy `draw_cart_tracks`
/// formats each line as an SVG `<line>` fragment;
/// `paint_cart_tracks` dispatches each line through the Painter
/// trait's `stroke_polyline`. Both paths derive coords from the
/// same generator so the SVG and Painter outputs stay stamp-
/// for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
struct CartTrackShape {
    /// Rail 1 endpoints (x1, y1, x2, y2).
    rail_a: (f64, f64, f64, f64),
    /// Rail 2 endpoints (x1, y1, x2, y2).
    rail_b: (f64, f64, f64, f64),
    /// Tie endpoints (x1, y1, x2, y2).
    tie: (f64, f64, f64, f64),
}

/// Walk every tile once and resolve rail / tie endpoints. Mirrors
/// the legacy per-tile geometry exactly: rails sit at 0.35 / 0.65
/// of the perpendicular axis (full-cell length along the rail
/// axis), and the tie spans both rails plus a 1 px overshoot on
/// each end.
fn cart_tracks_shapes(tiles: &[(i32, i32, bool)]) -> Vec<CartTrackShape> {
    let mut out: Vec<CartTrackShape> = Vec::with_capacity(tiles.len());
    for &(x, y, horizontal) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let cx = px + CELL / 2.0;
        let cy = py + CELL / 2.0;
        let shape = if horizontal {
            let y1 = py + CELL * 0.35;
            let y2 = py + CELL * 0.65;
            CartTrackShape {
                rail_a: (px, y1, px + CELL, y1),
                rail_b: (px, y2, px + CELL, y2),
                tie: (cx, y1 - 1.0, cx, y2 + 1.0),
            }
        } else {
            let x1 = px + CELL * 0.35;
            let x2 = px + CELL * 0.65;
            CartTrackShape {
                rail_a: (x1, py, x1, py + CELL),
                rail_b: (x2, py, x2, py + CELL),
                tie: (x1 - 1.0, cy, x2 + 1.0, cy),
            }
        };
        out.push(shape);
    }
    out
}
/// Painter-trait entry point — Phase 2.13f port.
///
/// Walks the same shape stream as `draw_cart_tracks` and dispatches
/// each tile's two rail lines plus one tie line through the Painter
/// trait. Two `begin_group` / `end_group` pairs wrap the buckets to
/// match the legacy SVG envelopes:
///
/// - Rails group at `RAIL_OPACITY` (0.55), `RAIL_WIDTH` (0.9).
/// - Ties group at `TIE_OPACITY` (0.5), `TIE_WIDTH` (1.4).
///
/// Both buckets use `LineCap::Round` to match the legacy
/// `stroke-linecap="round"`. PNG output stays pixel-equal with the
/// pre-port `paint_fragments` path — only the intermediate SVG-
/// string round-trip disappears.
pub fn paint_cart_tracks(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32, bool)],
    _seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let shapes = cart_tracks_shapes(tiles);
    if shapes.is_empty() {
        return;
    }

    let rail_paint = paint_for_hex(TRACK_RAIL);
    let rail_stroke = Stroke {
        width: round_legacy(RAIL_WIDTH as f64),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    painter.begin_group(RAIL_OPACITY);
    for s in &shapes {
        painter.stroke_polyline(
            &line_verts(s.rail_a),
            &rail_paint,
            &rail_stroke,
        );
        painter.stroke_polyline(
            &line_verts(s.rail_b),
            &rail_paint,
            &rail_stroke,
        );
    }
    painter.end_group();

    let tie_paint = paint_for_hex(TRACK_TIE);
    let tie_stroke = Stroke {
        width: round_legacy(TIE_WIDTH as f64),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    painter.begin_group(TIE_OPACITY);
    for s in &shapes {
        painter.stroke_polyline(
            &line_verts(s.tie),
            &tie_paint,
            &tie_stroke,
        );
    }
    painter.end_group();
}

// ── Painter helpers ───────────────────────────────────────────

/// Build a 2-vertex polyline from a `(x1, y1, x2, y2)` tuple,
/// rounding each coord through `round_legacy` so the Painter
/// path lands on the same f32 values the SVG-string path would
/// have arrived at via `format!("{:.1}")` → `parse_path_d`.
fn line_verts(line: (f64, f64, f64, f64)) -> [Vec2; 2] {
    [
        Vec2::new(round_legacy(line.0), round_legacy(line.1)),
        Vec2::new(round_legacy(line.2), round_legacy(line.3)),
    ]
}

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`. Duplicated locally for the 10th
/// time (also lives in floor_grid / floor_detail / thematic_detail
/// / terrain_detail / cobblestone / brick / flagstone /
/// opus_romano / field_stone); a shared crate-level helper would
/// cut diff noise but bloat this commit, so leave it for a
/// follow-up.
fn round_legacy(v: f64) -> f32 {
    let s = format!("{:.1}", v);
    s.parse::<f64>().unwrap_or(v) as f32
}

fn parse_hex_rgb(s: &str) -> (u8, u8, u8) {
    s.strip_prefix('#')
        .filter(|t| t.len() == 6)
        .and_then(|t| {
            let r = u8::from_str_radix(&t[0..2], 16).ok()?;
            let g = u8::from_str_radix(&t[2..4], 16).ok()?;
            let b = u8::from_str_radix(&t[4..6], 16).ok()?;
            Some((r, g, b))
        })
        .unwrap_or((0, 0, 0))
}

fn paint_for_hex(hex: &str) -> Paint {
    let (r, g, b) = parse_hex_rgb(hex);
    Paint::solid(Color::rgb(r, g, b))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::{
        FillRule, Paint, Painter, PathOps, Rect, Stroke, Vec2,
    };
    // ── Painter-path tests ─────────────────────────────────────

    /// Records every Painter call. Mirrors the trait-level
    /// `MockPainter` in `painter::tests` but lives in this module
    /// so the assertions stay close to the primitive.
    #[derive(Debug, Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
        group_depth: i32,
        max_group_depth: i32,
    }

    #[derive(Debug, Clone, PartialEq)]
    enum Call {
        StrokePolyline(usize, u32),
        BeginGroup(u32),
        EndGroup,
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {}
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {}
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_ellipse(
            &mut self, _: f32, _: f32, _: f32, _: f32, _: &Paint,
        ) {
        }
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {}
        fn stroke_polyline(
            &mut self,
            vertices: &[Vec2],
            _: &Paint,
            stroke: &Stroke,
        ) {
            self.calls.push(Call::StrokePolyline(
                vertices.len(),
                (stroke.width * 100.0).round() as u32,
            ));
        }
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {}
        fn stroke_path(&mut self, _: &PathOps, _: &Paint, _: &Stroke) {}
        fn begin_group(&mut self, opacity: f32) {
            self.group_depth += 1;
            if self.group_depth > self.max_group_depth {
                self.max_group_depth = self.group_depth;
            }
            self.calls.push(Call::BeginGroup(
                (opacity * 100.0).round() as u32,
            ));
        }
        fn end_group(&mut self) {
            self.group_depth -= 1;
            self.calls.push(Call::EndGroup);
        }
        fn push_clip(&mut self, _: &PathOps, _: FillRule) {}
        fn pop_clip(&mut self) {}
        fn push_transform(&mut self, _: crate::painter::Transform) {}
        fn pop_transform(&mut self) {}
    }

    impl CaptureCalls {
        fn polyline_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::StrokePolyline(_, _)))
                .count()
        }
        fn begin_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::BeginGroup(_)))
                .count()
        }
        fn end_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::EndGroup))
                .count()
        }
        fn opacities(&self) -> Vec<u32> {
            self.calls
                .iter()
                .filter_map(|c| match c {
                    Call::BeginGroup(op) => Some(*op),
                    _ => None,
                })
                .collect()
        }
        fn stroke_widths(&self) -> Vec<u32> {
            self.calls
                .iter()
                .filter_map(|c| match c {
                    Call::StrokePolyline(_, w) => Some(*w),
                    _ => None,
                })
                .collect()
        }
    }

    fn mixed_tiles(n: i32) -> Vec<(i32, i32, bool)> {
        // Alternate horizontal / vertical to exercise both branches.
        (0..n)
            .flat_map(|y| {
                (0..n).map(move |x| (x, y, (x + y) % 2 == 0))
            })
            .collect()
    }

    #[test]
    fn paint_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &[], 0);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// Two non-nested groups (rails + ties), balanced.
    #[test]
    fn paint_emits_two_balanced_groups() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &mixed_tiles(4), 0);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert_eq!(begins, 2, "expected rails + ties groups");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacities — rails 0.55, ties 0.5 (in that
    /// order, since the legacy SVG emits rails before ties).
    #[test]
    fn paint_uses_documented_opacities() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &mixed_tiles(4), 0);
        let opacities = painter.opacities();
        assert_eq!(opacities.len(), 2);
        assert_eq!(
            opacities[0],
            (RAIL_OPACITY * 100.0).round() as u32,
            "rails group should be at {RAIL_OPACITY}",
        );
        assert_eq!(
            opacities[1],
            (TIE_OPACITY * 100.0).round() as u32,
            "ties group should be at {TIE_OPACITY}",
        );
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelopes.
    #[test]
    fn paints_only_inside_group_envelopes() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &mixed_tiles(4), 0);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Each tile emits two rail polylines + one tie polyline =
    /// 3 strokes total. All polylines have exactly 2 vertices.
    #[test]
    fn paint_emits_three_polylines_per_tile() {
        let tiles = mixed_tiles(4);
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &tiles, 0);
        assert_eq!(
            painter.polyline_count(),
            tiles.len() * 3,
            "expected 2 rails + 1 tie per tile",
        );
        for c in &painter.calls {
            if let Call::StrokePolyline(n, _) = c {
                assert_eq!(*n, 2, "every cart-track line is 2-vertex");
            }
        }
    }

    /// Rails use stroke-width 0.9; ties use stroke-width 1.4.
    /// Per-tile pattern: rail, rail, … (× n_tiles) then tie, tie, …
    /// (× n_tiles), since the rails group emits before the ties
    /// group.
    #[test]
    fn paint_uses_documented_stroke_widths() {
        let tiles = mixed_tiles(3);
        let n = tiles.len();
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &tiles, 0);
        let widths = painter.stroke_widths();
        assert_eq!(widths.len(), n * 3);
        let rail_w = (RAIL_WIDTH * 100.0).round() as u32;
        let tie_w = (TIE_WIDTH * 100.0).round() as u32;
        for w in &widths[..n * 2] {
            assert_eq!(*w, rail_w, "rails group uses rail width");
        }
        for w in &widths[n * 2..] {
            assert_eq!(*w, tie_w, "ties group uses tie width");
        }
    }
    /// Painter-path determinism: same input → same call sequence.
    #[test]
    fn paint_deterministic_for_same_input() {
        let tiles = mixed_tiles(3);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_cart_tracks(&mut a, &tiles, 0);
        paint_cart_tracks(&mut b, &tiles, 0);
        assert_eq!(
            a.calls, b.calls,
            "same tiles must produce identical Painter calls",
        );
    }

    /// Orientation sensitivity: flipping every tile's orientation
    /// must change the polyline geometry (so the sequence of
    /// recorded calls differs even though stamp counts match).
    #[test]
    fn paint_orientation_changes_geometry() {
        let h_tiles: Vec<_> =
            (0..3).map(|x| (x, 0_i32, true)).collect();
        let v_tiles: Vec<_> =
            (0..3).map(|x| (x, 0_i32, false)).collect();
        // Geometry differs between horizontal and vertical, so the
        // shape stream itself must differ.
        let h_shapes = cart_tracks_shapes(&h_tiles);
        let v_shapes = cart_tracks_shapes(&v_tiles);
        assert_ne!(h_shapes, v_shapes);
    }
}
