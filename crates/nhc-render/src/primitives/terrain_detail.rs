//! Terrain-detail per-tile painters — Phase 9.1c port of
//! `nhc/rendering/_terrain_detail.py`, ported to the Painter trait
//! in Phase 2.12 of `plans/nhc_pure_ir_plan.md`.
//!
//! Reproduces the per-tile water ripples (`_water_detail`), lava
//! cracks + embers (`_lava_detail`) and chasm hatches
//! (`_chasm_detail`) as Painter-trait emitters consumed only by
//! `transform/png/terrain_detail.rs`. There is **no FFI export**
//! for these primitives — the Python side has its own
//! `nhc.rendering._terrain_detail` module for SVG output. So
//! Phase 2.12 REPLACES the legacy `draw_*` SVG-string emitters
//! with `paint_*` Painter calls outright, no dual path needed.
//!
//! **Parity contract (relaxed gate, plan §9.1):** byte-equal-with-
//! legacy is *not* required. The Rust port uses `Pcg64Mcg` per
//! decorator (independent streams XOR'd off the input seed); the
//! reference PNG fixtures gate on `PSNR > 35 dB` per
//! `design/map_ir.md` §9.4.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! Each per-kind layer wraps its tile elements in a single
//! `<g opacity="…">` envelope (water `0.35`, lava `0.40`, chasm
//! `0.35`). The pre-2.12 PNG handler dispatched to `paint_fragments`,
//! which already routed each `<g opacity>` envelope through
//! `paint_offscreen_group` (Phase 5.10's offscreen-buffer composite).
//! The Painter port replaces the SVG-string round-trip with native
//! `begin_group(opacity)` / `end_group()` calls so the Painter trait
//! owns the offscreen-buffer mechanism end-to-end. PNG output should
//! be pixel-equal with the pre-port PNG references — only the
//! intermediate SVG-string emission disappears.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

const CELL: f64 = 32.0;

const WATER_INK: &str = "#4A7888";
const WATER_OPACITY: f32 = 0.35;
const CHASM_INK: &str = "#444444";
const CHASM_OPACITY: f32 = 0.35;
const LAVA_INK: &str = "#A04030";
const LAVA_OPACITY: f32 = 0.40;

/// Per-element ember alpha — the legacy SVG circle carries
/// `opacity="0.4"`. Inside the lava `<g opacity="0.4">` envelope,
/// the effective alpha is 0.4 × 0.4 = 0.16. The Painter port
/// folds the per-element alpha into the Paint's Color.a channel;
/// the group composite handles the outer 0.4 envelope.
const EMBER_ALPHA: f32 = 0.4;

const WATER_SEED_SALT: u64 = 0x_77AA_2E22_7E2E_7A77;
const LAVA_SEED_SALT: u64 = 0x_1A7A_BEEF_DEAD_F1AA;
const CHASM_SEED_SALT: u64 = 0x_C4A5_D00D_FACE_B0BA;

fn paint_water_tile(
    painter: &mut dyn Painter,
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
) {
    let n_waves = rng.gen_range(2..=3);
    for i in 0..n_waves {
        let t = f64::from(i + 1) / f64::from(n_waves + 1);
        let y0 = py + CELL * t;
        // Build the wobble polyline in lock-step with the legacy
        // RNG sequence (`(-CELL*0.06)..(CELL*0.06)` per step).
        let mut path = PathOps::new();
        path.move_to(Vec2::new(
            round_legacy(px + CELL * 0.1),
            round_legacy(y0),
        ));
        let steps = 5_i32;
        for s in 1..=steps {
            let sx = px + CELL * 0.1 + (CELL * 0.8) * f64::from(s) / f64::from(steps);
            let sy = y0 + rng.gen_range((-CELL * 0.06)..(CELL * 0.06));
            path.line_to(Vec2::new(round_legacy(sx), round_legacy(sy)));
        }
        let sw: f64 = rng.gen_range(0.4..0.8);
        painter.stroke_path(
            &path,
            &paint_for_hex(WATER_INK),
            &Stroke {
                width: round_legacy(sw),
                line_cap: LineCap::Round,
                line_join: LineJoin::Miter,
            },
        );
    }
    if rng.gen::<f64>() < 0.10 {
        let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let r: f64 = rng.gen_range((CELL * 0.06)..(CELL * 0.12));
        // Stroke-only circle (no fill in the legacy SVG).
        let path = circle_path(round_legacy(cx), round_legacy(cy), round_legacy(r));
        painter.stroke_path(
            &path,
            &paint_for_hex(WATER_INK),
            &Stroke {
                width: round_legacy(0.4),
                line_cap: LineCap::Round,
                line_join: LineJoin::Miter,
            },
        );
    }
}

fn paint_lava_tile(
    painter: &mut dyn Painter,
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
    ember_ink: &str,
) {
    let n_cracks = rng.gen_range(1..=2);
    for _ in 0..n_cracks {
        let x0 = px + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let y0 = py + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let x1 = px + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let y1 = py + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let sw: f64 = rng.gen_range(0.5..1.0);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(round_legacy(x0), round_legacy(y0)));
        path.line_to(Vec2::new(round_legacy(x1), round_legacy(y1)));
        painter.stroke_path(
            &path,
            &paint_for_hex(LAVA_INK),
            &Stroke {
                width: round_legacy(sw),
                line_cap: LineCap::Round,
                line_join: LineJoin::Miter,
            },
        );
    }
    if rng.gen::<f64>() < 0.20 {
        let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let r: f64 = rng.gen_range((CELL * 0.04)..(CELL * 0.08));
        // Filled ember with per-element alpha 0.4 — see
        // EMBER_ALPHA constant doc above.
        painter.fill_circle(
            round_legacy(cx),
            round_legacy(cy),
            round_legacy(r),
            &paint_for_hex_alpha(ember_ink, EMBER_ALPHA),
        );
    }
}

fn paint_chasm_tile(
    painter: &mut dyn Painter,
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
) {
    let n_lines = rng.gen_range(2..=3);
    for i in 0..n_lines {
        let t = f64::from(i + 1) / f64::from(n_lines + 1);
        let offset = CELL * t;
        let sw: f64 = rng.gen_range(0.4..0.8);
        let x0 = px + offset + rng.gen_range(-2.0..2.0);
        let y0 = py + rng.gen_range(0.0..(CELL * 0.15));
        let x1 = px + offset + rng.gen_range(-2.0..2.0);
        let y1 = py + CELL - rng.gen_range(0.0..(CELL * 0.15));
        let mut path = PathOps::new();
        path.move_to(Vec2::new(round_legacy(x0), round_legacy(y0)));
        path.line_to(Vec2::new(round_legacy(x1), round_legacy(y1)));
        painter.stroke_path(
            &path,
            &paint_for_hex(CHASM_INK),
            &Stroke {
                width: round_legacy(sw),
                line_cap: LineCap::Round,
                line_join: LineJoin::Miter,
            },
        );
    }
}

/// Paint the water-ripple layer for one bucket of tiles. Wraps the
/// whole layer in a single `begin_group(WATER_OPACITY) / end_group()`
/// pair, matching the legacy `<g class="terrain-water" opacity="0.35">`
/// envelope. Empty tile sets emit zero painter calls (no spurious
/// group).
pub fn paint_water(painter: &mut dyn Painter, tiles: &[(i32, i32)], seed: u64) {
    if tiles.is_empty() {
        return;
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ WATER_SEED_SALT);
    painter.begin_group(WATER_OPACITY);
    for &(x, y) in tiles {
        paint_water_tile(
            painter,
            &mut rng,
            f64::from(x) * CELL,
            f64::from(y) * CELL,
        );
    }
    painter.end_group();
}

/// Paint the lava-detail layer for one bucket of tiles. `ember_ink`
/// is the running theme's `lava.detail_ink` — used as the ember-dot
/// fill colour. Wraps the layer in `begin_group(LAVA_OPACITY)`
/// matching the legacy `<g class="terrain-lava" opacity="0.40">`
/// envelope.
pub fn paint_lava(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    seed: u64,
    ember_ink: &str,
) {
    if tiles.is_empty() {
        return;
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ LAVA_SEED_SALT);
    painter.begin_group(LAVA_OPACITY);
    for &(x, y) in tiles {
        paint_lava_tile(
            painter,
            &mut rng,
            f64::from(x) * CELL,
            f64::from(y) * CELL,
            ember_ink,
        );
    }
    painter.end_group();
}

/// Paint the chasm hatch-line layer for one bucket of tiles. Wraps
/// the layer in `begin_group(CHASM_OPACITY)` matching the legacy
/// `<g class="terrain-chasm" opacity="0.35">` envelope.
pub fn paint_chasm(painter: &mut dyn Painter, tiles: &[(i32, i32)], seed: u64) {
    if tiles.is_empty() {
        return;
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ CHASM_SEED_SALT);
    painter.begin_group(CHASM_OPACITY);
    for &(x, y) in tiles {
        paint_chasm_tile(
            painter,
            &mut rng,
            f64::from(x) * CELL,
            f64::from(y) * CELL,
        );
    }
    painter.end_group();
}

/// Build a closed cubic-Bezier circle path centred at `(cx, cy)`
/// with radius `r`. Used by the water-ripple stroke-only circles.
/// `SkiaPainter::stroke_path` is the natural target since the
/// `fill_circle` Painter primitive only fills (no stroke variant);
/// going through PathOps keeps the stroke parameters explicit.
fn circle_path(cx: f32, cy: f32, r: f32) -> PathOps {
    const KAPPA: f32 = 0.552_284_8;
    let ox = r * KAPPA;
    let mut path = PathOps::new();
    path.move_to(Vec2::new(cx + r, cy));
    path.cubic_to(
        Vec2::new(cx + r, cy + ox),
        Vec2::new(cx + ox, cy + r),
        Vec2::new(cx, cy + r),
    );
    path.cubic_to(
        Vec2::new(cx - ox, cy + r),
        Vec2::new(cx - r, cy + ox),
        Vec2::new(cx - r, cy),
    );
    path.cubic_to(
        Vec2::new(cx - r, cy - ox),
        Vec2::new(cx - ox, cy - r),
        Vec2::new(cx, cy - r),
    );
    path.cubic_to(
        Vec2::new(cx + ox, cy - r),
        Vec2::new(cx + r, cy - ox),
        Vec2::new(cx + r, cy),
    );
    path.close();
    path
}

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`.
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

fn paint_for_hex_alpha(hex: &str, alpha: f32) -> Paint {
    let (r, g, b) = parse_hex_rgb(hex);
    Paint::solid(Color::rgba(r, g, b, alpha))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::{
        FillRule, Paint, Painter, PathOps, Rect, Stroke, Vec2,
    };

    fn grid(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

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
        FillCircle(f32, f32, f32, Paint),
        FillPath,
        StrokePath,
        BeginGroup(u32),
        EndGroup,
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {}
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {}
        fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint) {
            self.calls.push(Call::FillCircle(cx, cy, r, *paint));
        }
        fn fill_ellipse(
            &mut self, _: f32, _: f32, _: f32, _: f32, _: &Paint,
        ) {
        }
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {}
        fn stroke_polyline(&mut self, _: &[Vec2], _: &Paint, _: &Stroke) {}
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {
            self.calls.push(Call::FillPath);
        }
        fn stroke_path(&mut self, _: &PathOps, _: &Paint, _: &Stroke) {
            self.calls.push(Call::StrokePath);
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
        fn count(&self, target: &Call) -> usize {
            self.calls.iter().filter(|c| *c == target).count()
        }
        fn begin_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::BeginGroup(_)))
                .count()
        }
        fn end_group_count(&self) -> usize {
            self.count(&Call::EndGroup)
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
        fn ember_fills(&self) -> Vec<Paint> {
            self.calls
                .iter()
                .filter_map(|c| match c {
                    Call::FillCircle(_, _, _, p) => Some(*p),
                    _ => None,
                })
                .collect()
        }
    }

    // ── Empty-input contract ──────────────────────────────────

    #[test]
    fn empty_tiles_emit_no_painter_calls() {
        let mut painter = CaptureCalls::default();
        paint_water(&mut painter, &[], 200);
        paint_lava(&mut painter, &[], 200, "#A04030");
        paint_chasm(&mut painter, &[], 200);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    // ── Group balance ─────────────────────────────────────────

    #[test]
    fn each_paint_fn_emits_balanced_single_group() {
        let tiles = grid(4);
        for kind in 0..3 {
            let mut painter = CaptureCalls::default();
            match kind {
                0 => paint_water(&mut painter, &tiles, 200),
                1 => paint_lava(&mut painter, &tiles, 200, "#A04030"),
                _ => paint_chasm(&mut painter, &tiles, 200),
            }
            assert_eq!(painter.begin_group_count(), 1, "kind={kind}");
            assert_eq!(painter.end_group_count(), 1, "kind={kind}");
            assert_eq!(painter.group_depth, 0, "kind={kind}");
            assert_eq!(painter.max_group_depth, 1, "kind={kind}");
        }
    }

    // ── Documented bucket opacities ───────────────────────────

    #[test]
    fn paint_water_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_water(&mut painter, &grid(2), 200);
        assert_eq!(
            painter.opacities(),
            vec![(WATER_OPACITY * 100.0).round() as u32],
        );
    }

    #[test]
    fn paint_lava_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_lava(&mut painter, &grid(2), 200, "#A04030");
        assert_eq!(
            painter.opacities(),
            vec![(LAVA_OPACITY * 100.0).round() as u32],
        );
    }

    #[test]
    fn paint_chasm_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_chasm(&mut painter, &grid(2), 200);
        assert_eq!(
            painter.opacities(),
            vec![(CHASM_OPACITY * 100.0).round() as u32],
        );
    }

    // ── Stamp shapes / counts ─────────────────────────────────

    #[test]
    fn paint_water_emits_strokes_only() {
        // Water is wave polylines + optional ripple circles —
        // both stroke-only. There must be no fill_path calls.
        let mut painter = CaptureCalls::default();
        paint_water(&mut painter, &grid(8), 200);
        assert_eq!(painter.count(&Call::FillPath), 0);
        assert!(painter.count(&Call::StrokePath) > 0);
    }

    #[test]
    fn paint_chasm_emits_strokes_only() {
        let mut painter = CaptureCalls::default();
        paint_chasm(&mut painter, &grid(8), 200);
        assert_eq!(painter.count(&Call::FillPath), 0);
        assert!(painter.count(&Call::StrokePath) > 0);
    }

    /// Lava emits crack lines (stroke) plus optional ember fills
    /// (fill_circle). Over a large enough tile set we expect at
    /// least one ember hit (20 % per tile × 64 tiles ≈ 13).
    #[test]
    fn paint_lava_emits_cracks_and_embers() {
        let mut painter = CaptureCalls::default();
        paint_lava(&mut painter, &grid(8), 99, "#A04030");
        assert!(painter.count(&Call::StrokePath) > 0, "expected lava cracks");
        let embers: usize = painter
            .calls
            .iter()
            .filter(|c| matches!(c, Call::FillCircle(_, _, _, _)))
            .count();
        assert!(embers > 0, "expected at least one ember fill");
    }

    /// Embers carry the passed `ember_ink` colour folded into the
    /// Paint. Over a large tile set we should observe the crypt
    /// ink (#903828) on at least one ember.
    #[test]
    fn paint_lava_ember_carries_passed_ink() {
        let mut painter = CaptureCalls::default();
        let crypt_ink = "#903828";
        paint_lava(&mut painter, &grid(8), 99, crypt_ink);
        let fills = painter.ember_fills();
        assert!(!fills.is_empty(), "expected at least one ember fill");
        // 0x90 = 144, 0x38 = 56, 0x28 = 40
        for paint in fills {
            assert_eq!(paint.color.r, 0x90);
            assert_eq!(paint.color.g, 0x38);
            assert_eq!(paint.color.b, 0x28);
            assert!(
                (paint.color.a - EMBER_ALPHA).abs() < 1e-6,
                "ember alpha = {}, expected {EMBER_ALPHA}", paint.color.a,
            );
        }
    }

    // ── Determinism / divergence ──────────────────────────────

    #[test]
    fn deterministic_for_same_seed() {
        // Two independent painters, same input → identical call
        // sequences (same StrokePath / FillCircle counts).
        let tiles = grid(6);
        for kind in 0..3 {
            let mut a = CaptureCalls::default();
            let mut b = CaptureCalls::default();
            match kind {
                0 => {
                    paint_water(&mut a, &tiles, 200);
                    paint_water(&mut b, &tiles, 200);
                }
                1 => {
                    paint_lava(&mut a, &tiles, 200, "#A04030");
                    paint_lava(&mut b, &tiles, 200, "#A04030");
                }
                _ => {
                    paint_chasm(&mut a, &tiles, 200);
                    paint_chasm(&mut b, &tiles, 200);
                }
            }
            assert_eq!(
                a.count(&Call::StrokePath),
                b.count(&Call::StrokePath),
                "kind {kind} stroke counts must match",
            );
            assert_eq!(
                a.calls.len(),
                b.calls.len(),
                "kind {kind} total call counts must match",
            );
        }
    }

    #[test]
    fn different_seeds_diverge() {
        // Different seeds drive a different RNG stream, so the
        // captured call sequence must differ. We can't compare
        // the full Call enum (FillCircle carries f32 coords that
        // implement PartialEq fine, but StrokePath drops args),
        // so compare the projected `Call` discriminants AND the
        // ember fill coords — at least one of them will differ
        // for any non-trivial tile set.
        let tiles = grid(8);
        for kind in 0..3 {
            let mut a = CaptureCalls::default();
            let mut b = CaptureCalls::default();
            match kind {
                0 => {
                    paint_water(&mut a, &tiles, 200);
                    paint_water(&mut b, &tiles, 7);
                }
                1 => {
                    paint_lava(&mut a, &tiles, 200, "#A04030");
                    paint_lava(&mut b, &tiles, 7, "#A04030");
                }
                _ => {
                    paint_chasm(&mut a, &tiles, 200);
                    paint_chasm(&mut b, &tiles, 7);
                }
            }
            // Compare full call sequences — coord-bearing
            // FillCircle calls (lava embers) make the sequences
            // distinct even when total call counts coincide.
            assert_ne!(
                a.calls, b.calls,
                "kind {kind} call sequences must diverge across seeds",
            );
        }
    }

    /// Water / lava / chasm at the same seed must not share an
    /// RNG stream; the per-kind salt buys independence. Compare
    /// total stamp counts for the same input — they should differ
    /// across kinds (each rolls its own stamp count distribution).
    #[test]
    fn streams_independent_across_kinds() {
        let tiles = grid(6);
        let mut w = CaptureCalls::default();
        let mut l = CaptureCalls::default();
        let mut c = CaptureCalls::default();
        paint_water(&mut w, &tiles, 200);
        paint_lava(&mut l, &tiles, 200, "#A04030");
        paint_chasm(&mut c, &tiles, 200);
        // All three kinds emit at least one stamp.
        assert!(w.count(&Call::StrokePath) > 0);
        assert!(l.count(&Call::StrokePath) > 0);
        assert!(c.count(&Call::StrokePath) > 0);
        // The three kinds run independent RNG streams — the
        // per-kind stamp distributions diverge.
        assert_ne!(w.calls.len(), l.calls.len());
        assert_ne!(l.calls.len(), c.calls.len());
    }

    // ── Painter contract ──────────────────────────────────────

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelope.
    #[test]
    fn paints_only_inside_group_envelope() {
        let tiles = grid(4);
        for kind in 0..3 {
            let mut painter = CaptureCalls::default();
            match kind {
                0 => paint_water(&mut painter, &tiles, 200),
                1 => paint_lava(&mut painter, &tiles, 200, "#A04030"),
                _ => paint_chasm(&mut painter, &tiles, 200),
            }
            assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
            assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
        }
    }
}
