//! Flagstone decorator — Phase 4, sub-step 8 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13c of
//! `plans/nhc_pure_ir_plan.md` (the **third decorator port**;
//! opus_romano / field_stone / cart_tracks / ore_deposit follow
//! as 2.13d–g).
//!
//! Reproduces ``FLAGSTONE`` (4 irregular pentagon plates per
//! tile, divided 2×2 with a small mortar inset) from
//! ``nhc/rendering/_floor_detail.py``. Stroke-only group; the
//! wrapping <g> sets opacity / colour.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Existing fixtures don't
//! contain FLAGSTONE tiles; coverage rides on synthetic-level
//! tests.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_flagstone` SVG-string emitter (used by the
//!   FFI / `nhc/rendering/ir_to_svg.py` Python path until 2.17
//!   ships the `SvgPainter`-based PyO3 export and 2.19 retires
//!   the Python `ir_to_svg` path).
//! - The new `paint_flagstone` Painter-based emitter (used by the
//!   Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `flagstone_shapes` shape-stream
//! generator — the per-tile geometry is RNG-driven and the
//! Painter / SVG outputs MUST consume the RNG stream in lock-step
//! so they stay stamp-for-stamp aligned.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps the plates bucket in
//! `<g opacity="0.35" fill="none" stroke="#6A6055"
//! stroke-width="0.4">`. The pre-2.13c PNG handler dispatched to
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

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

const CELL: f64 = 32.0;
const FLAGSTONE_STROKE: &str = "#6A6055";

/// Group-opacity envelope for the plates bucket. Lifts the
/// `<g opacity="0.35" …>` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const FLAGSTONE_OPACITY: f32 = 0.35;

/// Per-shape record — backend-agnostic. The shape stream is the
/// single source of truth: the legacy `draw_flagstone` formats
/// each shape as an SVG `<polygon>` fragment, `paint_flagstone`
/// dispatches each shape through the Painter trait. Both paths
/// consume the same RNG sequence in lock-step, so the Painter and
/// SVG output stay stamp-for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
enum FlagstoneShape {
    /// One irregular pentagon plate — emitted as `<polygon>`
    /// inside the plates `<g opacity="0.35">` envelope. The legacy
    /// SVG path strokes only (no fill); the PNG path matches that
    /// behaviour by closing the path explicitly via PathOps and
    /// dispatching through `stroke_path`.
    Plate {
        p0: (f64, f64),
        p1: (f64, f64),
        p2: (f64, f64),
        p3: (f64, f64),
        p4: (f64, f64),
    },
}

/// Walk every tile once and build the plates bucket. Mirrors the
/// legacy per-tile 2×2 quadrant pentagon layout. Single
/// `Pcg64Mcg` stream — the RNG consumption order is the parity
/// contract shared between the SVG and Painter paths.
fn flagstone_shapes(tiles: &[(i32, i32)], seed: u64) -> Vec<FlagstoneShape> {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);

    let half = CELL / 2.0;
    let inset = half * 0.08;

    let mut plates: Vec<FlagstoneShape> = Vec::new();
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        for qy in 0..2 {
            for qx in 0..2 {
                let cx = px + f64::from(qx) * half;
                let cy = py + f64::from(qy) * half;
                // Five corner points: TL, T, TR, BR, BL with jitter.
                let j = |rng: &mut Pcg64Mcg| -> f64 {
                    rng.gen_range((-half * 0.07)..(half * 0.07))
                };
                let p0 = (cx + inset + j(&mut rng), cy + inset + j(&mut rng));
                let p1 = (
                    cx + half * 0.5 + j(&mut rng),
                    cy + inset * 0.5 + j(&mut rng),
                );
                let p2 = (
                    cx + half - inset + j(&mut rng),
                    cy + inset + j(&mut rng),
                );
                let p3 = (
                    cx + half - inset + j(&mut rng),
                    cy + half - inset + j(&mut rng),
                );
                let p4 = (
                    cx + inset + j(&mut rng),
                    cy + half - inset + j(&mut rng),
                );
                plates.push(FlagstoneShape::Plate { p0, p1, p2, p3, p4 });
            }
        }
    }

    plates
}

pub fn draw_flagstone(tiles: &[(i32, i32)], seed: u64) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let plates = flagstone_shapes(tiles, seed);
    if plates.is_empty() {
        return Vec::new();
    }

    let mut frags: Vec<String> = Vec::with_capacity(plates.len());
    for shape in &plates {
        frags.push(format_plate_svg(shape));
    }
    vec![format!(
        "<g opacity=\"0.35\" fill=\"none\" stroke=\"{FLAGSTONE_STROKE}\" \
         stroke-width=\"0.4\">{}</g>",
        frags.concat(),
    )]
}

/// Painter-trait entry point — Phase 2.13c port.
///
/// Walks the same shape stream as `draw_flagstone` and dispatches
/// the non-empty bucket through `begin_group(0.35) / end_group()`
/// to match the legacy SVG `<g opacity="0.35">` envelope. PNG
/// output stays pixel-equal with the pre-port `paint_fragments`
/// path — only the intermediate SVG-string round-trip disappears.
pub fn paint_flagstone(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let plates = flagstone_shapes(tiles, seed);
    if plates.is_empty() {
        return;
    }

    painter.begin_group(FLAGSTONE_OPACITY);
    let stroke_paint = paint_for_hex(FLAGSTONE_STROKE);
    let stroke = Stroke {
        width: round_legacy(0.4),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    for shape in &plates {
        let FlagstoneShape::Plate { p0, p1, p2, p3, p4 } = *shape;
        // Legacy SVG emits `<polygon>` (implicitly closed); match
        // that via `stroke_path` with an explicit `.close()` so the
        // tiny-skia stroke renders the closing edge between p4 and
        // p0. (The Painter trait's `stroke_polyline` would leave
        // that edge open.)
        let mut path = PathOps::with_capacity(6);
        path.move_to(Vec2::new(round_legacy(p0.0), round_legacy(p0.1)))
            .line_to(Vec2::new(round_legacy(p1.0), round_legacy(p1.1)))
            .line_to(Vec2::new(round_legacy(p2.0), round_legacy(p2.1)))
            .line_to(Vec2::new(round_legacy(p3.0), round_legacy(p3.1)))
            .line_to(Vec2::new(round_legacy(p4.0), round_legacy(p4.1)))
            .close();
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
    painter.end_group();
}

// ── SVG-string formatter (legacy path) ────────────────────────

fn format_plate_svg(shape: &FlagstoneShape) -> String {
    let FlagstoneShape::Plate { p0, p1, p2, p3, p4 } = *shape;
    format!(
        "<polygon points=\"\
         {:.1},{:.1} {:.1},{:.1} {:.1},{:.1} \
         {:.1},{:.1} {:.1},{:.1}\"/>",
        p0.0, p0.1, p1.0, p1.1, p2.0, p2.1,
        p3.0, p3.1, p4.0, p4.1,
    )
}

// ── Painter helpers ───────────────────────────────────────────

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`. Duplicated locally for the 7th
/// time (also lives in floor_grid / floor_detail / thematic_detail
/// / terrain_detail / cobblestone / brick); a shared crate-level
/// helper would cut diff noise but bloat this commit, so leave it
/// for a follow-up.
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

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_flagstone(&[], 333).is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32)> = (0..4)
            .flat_map(|y| (0..4).map(move |x| (x, y)))
            .collect();
        assert_eq!(draw_flagstone(&tiles, 333), draw_flagstone(&tiles, 333));
    }

    #[test]
    fn four_plates_per_tile() {
        let out = draw_flagstone(&[(0, 0)], 42);
        assert_eq!(out.len(), 1);
        let n_polygons = out[0].matches("<polygon").count();
        assert_eq!(n_polygons, 4, "4 quadrants × 1 pentagon each");
    }

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
        /// Records the path-op count too so seed-divergence tests
        /// can detect different RNG draws (deterministic-shape
        /// counts alone wouldn't distinguish seeds for flagstone).
        StrokePath(Vec<(i32, i32)>),
        BeginGroup(u32),
        EndGroup,
    }

    fn is_stroke_path(call: &Call) -> bool {
        matches!(call, Call::StrokePath(_))
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
        fn stroke_polyline(&mut self, _: &[Vec2], _: &Paint, _: &Stroke) {}
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {}
        fn stroke_path(&mut self, path: &PathOps, _: &Paint, _: &Stroke) {
            // Quantise vertex coordinates to 0.1-pixel buckets so
            // f32 rounding noise doesn't trip the equality tests.
            let mut points = Vec::with_capacity(path.ops.len());
            for op in &path.ops {
                match op {
                    crate::painter::PathOp::MoveTo(v)
                    | crate::painter::PathOp::LineTo(v) => {
                        points.push((
                            (v.x * 10.0).round() as i32,
                            (v.y * 10.0).round() as i32,
                        ));
                    }
                    _ => {}
                }
            }
            self.calls.push(Call::StrokePath(points));
        }
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
    }

    impl CaptureCalls {
        fn stroke_path_count(&self) -> usize {
            self.calls.iter().filter(|c| is_stroke_path(c)).count()
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
        paint_flagstone(&mut painter, &[], 333);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// One non-nested group, balanced.
    #[test]
    fn paint_emits_balanced_group() {
        let mut painter = CaptureCalls::default();
        paint_flagstone(&mut painter, &grid(4), 333);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert_eq!(begins, 1, "expected exactly one plates group");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacity — flagstone 0.35.
    #[test]
    fn paint_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_flagstone(&mut painter, &grid(4), 333);
        let opacities = painter.opacities();
        assert_eq!(opacities.len(), 1, "expected exactly one group");
        assert_eq!(
            opacities[0],
            (FLAGSTONE_OPACITY * 100.0).round() as u32,
            "plates group should be at {FLAGSTONE_OPACITY}",
        );
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelope.
    #[test]
    fn paints_only_inside_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_flagstone(&mut painter, &grid(4), 333);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Plates bucket emits stroke_path (closed pentagon polylines).
    #[test]
    fn paint_emits_only_stroke_path() {
        let mut painter = CaptureCalls::default();
        paint_flagstone(&mut painter, &grid(4), 333);
        assert!(painter.stroke_path_count() > 0);
    }

    /// 4 plates per tile — one pentagon per quadrant.
    #[test]
    fn paint_emits_four_stroke_paths_per_tile() {
        let mut painter = CaptureCalls::default();
        paint_flagstone(&mut painter, &[(0, 0)], 42);
        assert_eq!(
            painter.stroke_path_count(),
            4,
            "4 quadrants × 1 pentagon each",
        );
    }

    /// Painter and SVG paths consume the RNG in lock-step — the
    /// stamp counts (polygons on the SVG side, stroke_path on the
    /// Painter side) must match.
    #[test]
    fn paint_and_draw_emit_same_stamp_counts() {
        let tiles = grid(4);
        let mut painter = CaptureCalls::default();
        paint_flagstone(&mut painter, &tiles, 333);
        let svg = draw_flagstone(&tiles, 333);
        let svg_polygons: usize =
            svg.iter().map(|g| g.matches("<polygon").count()).sum();
        assert_eq!(
            painter.stroke_path_count(),
            svg_polygons,
            "flagstone stamp counts must match between SVG and Painter paths",
        );
    }

    /// Different seeds drive different RNG streams — the captured
    /// call sequence must differ.
    #[test]
    fn paint_different_seeds_diverge() {
        let tiles = grid(4);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_flagstone(&mut a, &tiles, 333);
        paint_flagstone(&mut b, &tiles, 7);
        assert_ne!(
            a.calls, b.calls,
            "different seeds must produce different Painter call sequences",
        );
    }
}
