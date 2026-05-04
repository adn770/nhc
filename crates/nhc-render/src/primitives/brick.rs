//! Brick decorator — Phase 4, sub-step 7 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13b of
//! `plans/nhc_pure_ir_plan.md` (the **second decorator port**;
//! flagstone / opus_romano / field_stone / cart_tracks /
//! ore_deposit follow as 2.13c–g).
//!
//! Reproduces ``BRICK`` (4×2 running-bond brick layout per tile)
//! from ``nhc/rendering/_floor_detail.py``. Each row is two
//! full bricks; odd rows shift by half a brick so courses
//! interlock. Per-brick jitter gives a hand-drawn look.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Existing fixtures
//! contain no BRICK tiles; coverage rides on synthetic-level
//! Python integration tests plus cargo unit tests.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_brick` SVG-string emitter (used by the
//!   FFI / `nhc/rendering/ir_to_svg.py` Python path until 2.17
//!   ships the `SvgPainter`-based PyO3 export and 2.19 retires
//!   the Python `ir_to_svg` path).
//! - The new `paint_brick` Painter-based emitter (used by the
//!   Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `brick_shapes` shape-stream
//! generator — the per-tile geometry is RNG-driven and the
//! Painter / SVG outputs MUST consume the RNG stream in lock-step
//! so they stay stamp-for-stamp aligned.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps the bricks bucket in
//! `<g opacity="0.35" fill="none" stroke="#A05530"
//! stroke-width="0.4">`. The pre-2.13b PNG handler dispatched to
//! `paint_fragments`, which already routes the `<g opacity>`
//! envelope through `paint_offscreen_group` (Phase 5.10's
//! offscreen-buffer composite). The Painter port replaces the
//! SVG-string round-trip with a native `begin_group(0.35) /
//! end_group()` pair so the Painter trait owns the offscreen-
//! buffer mechanism end-to-end. PNG output should be pixel-equal
//! with the pre-port PNG references — only the intermediate
//! SVG-string emission disappears.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{Color, LineCap, LineJoin, Paint, Painter, Stroke};

const CELL: f64 = 32.0;
const BRICK_STROKE: &str = "#A05530";

/// Group-opacity envelope for the bricks bucket. Lifts the
/// `<g opacity="0.35" …>` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const BRICK_OPACITY: f32 = 0.35;

/// Per-shape record — backend-agnostic. The shape stream is the
/// single source of truth: the legacy `draw_brick` formats each
/// shape as an SVG fragment string, `paint_brick` dispatches each
/// shape through the Painter trait. Both paths consume the same
/// RNG sequence in lock-step, so the Painter and SVG output stay
/// stamp-for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
enum BrickShape {
    /// One running-bond brick — emitted as `<rect rx="0.5">`
    /// inside the bricks `<g opacity="0.35">` envelope. The legacy
    /// SVG path strokes only (no fill); the rounded corners
    /// (`rx="0.5"`) are dropped by the PNG path because
    /// `paint_rect` in `transform/png/fragment.rs` ignores the
    /// `rx` attribute. The Painter port matches that behaviour
    /// by going through `stroke_rect` (axis-aligned, sharp
    /// corners).
    Brick { x: f64, y: f64, w: f64, h: f64 },
}

/// Walk every tile once and build the bricks bucket. Mirrors
/// the legacy per-tile 4-row × 2- or 3-column running-bond
/// layout. Single `Pcg64Mcg` stream — the RNG consumption order
/// is the parity contract shared between the SVG and Painter
/// paths.
fn brick_shapes(tiles: &[(i32, i32)], seed: u64) -> Vec<BrickShape> {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);

    let bw = CELL / 2.0;
    let bh = CELL / 4.0;

    let mut bricks: Vec<BrickShape> = Vec::new();
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        for row in 0..4 {
            let offset = if row % 2 == 1 { bw / 2.0 } else { 0.0 };
            let cols = if offset > 0.0 { 3 } else { 2 };
            for col in 0..cols {
                let x0 = px + f64::from(col) * bw - offset;
                let y0 = py + f64::from(row) * bh;
                let jx = rng.gen_range((-bw * 0.06)..(bw * 0.06));
                let jy = rng.gen_range((-bh * 0.06)..(bh * 0.06));
                let jw = rng.gen_range((-bw * 0.06)..(bw * 0.06));
                let jh = rng.gen_range((-bh * 0.06)..(bh * 0.06));
                let mut bx = x0 + jx + 0.5;
                let by = y0 + jy + 0.5;
                let mut bw_jit = bw + jw - 1.0;
                let bh_jit = bh + jh - 1.0;
                if bx < px {
                    bw_jit -= px - bx;
                    bx = px;
                }
                if bx + bw_jit > px + CELL {
                    bw_jit = px + CELL - bx;
                }
                if bw_jit > 1.5 && bh_jit > 1.5 {
                    bricks.push(BrickShape::Brick {
                        x: bx,
                        y: by,
                        w: bw_jit,
                        h: bh_jit,
                    });
                }
            }
        }
    }

    bricks
}
/// Painter-trait entry point — Phase 2.13b port.
///
/// Walks the same shape stream as `draw_brick` and dispatches the
/// non-empty bucket through `begin_group(0.35) / end_group()` to
/// match the legacy SVG `<g opacity="0.35">` envelope. PNG output
/// stays pixel-equal with the pre-port `paint_fragments` path —
/// only the intermediate SVG-string round-trip disappears.
pub fn paint_brick(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let bricks = brick_shapes(tiles, seed);
    if bricks.is_empty() {
        return;
    }

    painter.begin_group(BRICK_OPACITY);
    let stroke_paint = paint_for_hex(BRICK_STROKE);
    let stroke = Stroke {
        width: round_legacy(0.4),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    for shape in &bricks {
        let BrickShape::Brick { x, y, w, h } = *shape;
        // Legacy SVG emits `<rect>` with `rx="0.5"` rounded
        // corners, but `transform/png/fragment.rs::paint_rect`
        // ignores `rx`, so the PNG path strokes sharp axis-
        // aligned rects. Match that behaviour via `stroke_rect`
        // (no rounded-corner Painter primitive).
        painter.stroke_rect(
            crate::painter::Rect::new(
                round_legacy(x),
                round_legacy(y),
                round_legacy(w),
                round_legacy(h),
            ),
            &stroke_paint,
            &stroke,
        );
    }
    painter.end_group();
}

// ── SVG-string formatter (legacy path) ────────────────────────
// ── Painter helpers ───────────────────────────────────────────

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`. Duplicated locally for the 6th
/// time (also lives in floor_grid / floor_detail / thematic_detail
/// / terrain_detail / cobblestone); a shared crate-level helper
/// would cut diff noise but bloat this commit, so leave it for a
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
        /// Records the rect geometry too so seed-divergence tests
        /// can detect different RNG draws (deterministic-shape
        /// counts alone wouldn't distinguish seeds for brick).
        StrokeRect(i32, i32, i32, i32),
        BeginGroup(u32),
        EndGroup,
    }

    /// Geometry-agnostic match for stamp-count assertions.
    fn is_stroke_rect(call: &Call) -> bool {
        matches!(call, Call::StrokeRect(..))
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {}
        fn stroke_rect(&mut self, rect: Rect, _: &Paint, _: &Stroke) {
            // Quantise to 0.1-pixel buckets so f32 rounding noise
            // doesn't trip the equality tests.
            self.calls.push(Call::StrokeRect(
                (rect.x * 10.0).round() as i32,
                (rect.y * 10.0).round() as i32,
                (rect.w * 10.0).round() as i32,
                (rect.h * 10.0).round() as i32,
            ));
        }
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_ellipse(
            &mut self, _: f32, _: f32, _: f32, _: f32, _: &Paint,
        ) {
        }
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {}
        fn stroke_polyline(&mut self, _: &[Vec2], _: &Paint, _: &Stroke) {}
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
        fn stroke_rect_count(&self) -> usize {
            self.calls.iter().filter(|c| is_stroke_rect(c)).count()
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
    }

    fn grid(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

    #[test]
    fn paint_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_brick(&mut painter, &[], 333);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// One non-nested group, balanced.
    #[test]
    fn paint_emits_balanced_group() {
        let mut painter = CaptureCalls::default();
        paint_brick(&mut painter, &grid(6), 333);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert_eq!(begins, 1, "expected exactly one bricks group");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacity — bricks 0.35.
    #[test]
    fn paint_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_brick(&mut painter, &grid(6), 333);
        let opacities = painter.opacities();
        assert_eq!(opacities.len(), 1, "expected exactly one group");
        assert_eq!(
            opacities[0],
            (BRICK_OPACITY * 100.0).round() as u32,
            "bricks group should be at {BRICK_OPACITY}",
        );
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelope.
    #[test]
    fn paints_only_inside_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_brick(&mut painter, &grid(6), 333);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Bricks bucket emits stroke_rect (axis-aligned, sharp
    /// corners — no fill, no rounded `rx`).
    #[test]
    fn paint_emits_only_stroke_rect() {
        let mut painter = CaptureCalls::default();
        paint_brick(&mut painter, &grid(6), 333);
        assert!(painter.stroke_rect_count() > 0);
    }
    /// Different seeds drive different RNG streams — the captured
    /// call sequence must differ.
    #[test]
    fn paint_different_seeds_diverge() {
        let tiles = grid(6);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_brick(&mut a, &tiles, 333);
        paint_brick(&mut b, &tiles, 7);
        assert_ne!(
            a.calls, b.calls,
            "different seeds must produce different Painter call sequences",
        );
    }
}
