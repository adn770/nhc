//! Field-stone decorator — Phase 4, sub-step 10 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13e of
//! `plans/nhc_pure_ir_plan.md` (the **fifth decorator port**;
//! cart_tracks / ore_deposit follow as 2.13f–g).
//!
//! Reproduces ``FIELD_STONE`` from
//! ``nhc/rendering/_floor_detail.py``: a probabilistic
//! scattered stone (10 % per tile) for FIELD-surface GRASS
//! tiles. Single ellipse per fired tile, in a green-stone
//! palette.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. The Rust port uses
//! a single ``Pcg64Mcg`` stream from the input seed (one draw
//! per tile for the 10 % gate, plus 5 draws per fired tile for
//! the ellipse parameters); the Painter and SVG paths MUST
//! consume the RNG stream in lock-step so they stay stamp-for-
//! stamp aligned.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_field_stone` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until
//!   2.17 ships the `SvgPainter`-based PyO3 export and 2.19
//!   retires the Python `ir_to_svg` path).
//! - The new `paint_field_stone` Painter-based emitter (used by
//!   the Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `field_stone_shapes` shape-stream
//! generator. Lock-step RNG is critical here because the 10 %
//! probabilistic skip means any divergence in RNG consumption
//! between the SVG and Painter paths would cascade across every
//! subsequent tile.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps the stones bucket in
//! `<g opacity="0.8">`. The pre-2.13e PNG handler dispatched to
//! `paint_fragments`, which already routes the `<g opacity>`
//! envelope through `paint_offscreen_group` (Phase 5.10's
//! offscreen-buffer composite). The Painter port replaces the
//! SVG-string round-trip with a native `begin_group(0.8) /
//! end_group()` pair so the Painter trait owns the offscreen-
//! buffer mechanism end-to-end. PNG output should be pixel-equal
//! with the pre-port PNG references — only the intermediate
//! SVG-string emission disappears.
//!
//! ## Rotated-ellipse note
//!
//! The legacy SVG emits `<ellipse>` with a
//! `transform="rotate(angle, cx, cy)"` attribute. The Painter
//! trait's `fill_ellipse` is axis-aligned, so each rotated
//! stone goes through `fill_path` / `stroke_path` instead —
//! same KAPPA cubic-Bezier approximation cobblestone uses, with
//! the rotation baked into the control-point coordinates.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

const CELL: f64 = 32.0;
const FIELD_STONE_FILL: &str = "#8A9A6A";
const FIELD_STONE_STROKE: &str = "#4A5A3A";
const PROBABILITY: f64 = 0.10;

/// Group-opacity envelope for the stones bucket. Lifts the
/// `<g opacity="0.8">` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const FIELD_STONE_OPACITY: f32 = 0.8;

/// Per-shape record — backend-agnostic. The shape stream is the
/// single source of truth: the legacy `draw_field_stone` formats
/// each shape as an SVG `<ellipse>` fragment, `paint_field_stone`
/// dispatches each shape through the Painter trait. Both paths
/// consume the same RNG sequence in lock-step, so the Painter and
/// SVG output stay stamp-for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
struct FieldStoneShape {
    cx: f64,
    cy: f64,
    rx: f64,
    ry: f64,
    angle_deg: f64,
}

/// Walk every tile once and build the stones bucket. Mirrors the
/// legacy per-tile 10 % probabilistic gate and ellipse parameter
/// rolls. Single `Pcg64Mcg` stream from `seed`: one draw per tile
/// for the gate, plus 5 draws per fired tile (cx offset, cy offset,
/// rx, ry, angle). The RNG consumption order is the parity contract
/// shared between the SVG and Painter paths.
fn field_stone_shapes(tiles: &[(i32, i32)], seed: u64) -> Vec<FieldStoneShape> {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut stones: Vec<FieldStoneShape> = Vec::new();
    for &(x, y) in tiles {
        if rng.gen::<f64>() >= PROBABILITY {
            continue;
        }
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let cx = px + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
        let cy = py + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
        let rx: f64 = rng.gen_range(1.5..2.8);
        let ry: f64 = rng.gen_range(1.2..2.2);
        let angle: f64 = rng.gen_range(0.0..180.0);
        stones.push(FieldStoneShape {
            cx,
            cy,
            rx,
            ry,
            angle_deg: angle,
        });
    }
    stones
}
/// Painter-trait entry point — Phase 2.13e port.
///
/// Walks the same shape stream as `draw_field_stone` and dispatches
/// the non-empty bucket through `begin_group(0.8) / end_group()`
/// to match the legacy SVG `<g opacity="0.8">` envelope. PNG output
/// stays pixel-equal with the pre-port `paint_fragments` path —
/// only the intermediate SVG-string round-trip disappears.
///
/// Each stone dispatches through `fill_path` + `stroke_path` with
/// a rotated cubic-Bezier ellipse path (KAPPA approximation, same
/// as cobblestone), since the Painter trait's `fill_ellipse` is
/// axis-aligned.
pub fn paint_field_stone(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let stones = field_stone_shapes(tiles, seed);
    if stones.is_empty() {
        return;
    }

    painter.begin_group(FIELD_STONE_OPACITY);
    let fill_paint = paint_for_hex(FIELD_STONE_FILL);
    let stroke_paint = paint_for_hex(FIELD_STONE_STROKE);
    let stroke = Stroke {
        width: round_legacy(0.5),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    for s in &stones {
        let path = rotated_ellipse_path(
            round_legacy(s.cx),
            round_legacy(s.cy),
            round_legacy(s.rx),
            round_legacy(s.ry),
            s.angle_deg,
        );
        painter.fill_path(
            &path,
            &fill_paint,
            crate::painter::FillRule::Winding,
        );
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
    painter.end_group();
}

// ── Painter helpers ───────────────────────────────────────────

/// Build a closed cubic-Bezier ellipse path centred at `(cx, cy)`
/// with radii `(rx, ry)`, rotated by `angle_deg` around `(cx, cy)`.
/// Mirrors the rotated-ellipse helper in
/// `primitives::cobblestone` (same KAPPA approximation) — the
/// rotation bakes into the control-point coords so the path is
/// backend-agnostic. The Painter trait's `fill_ellipse` is axis-
/// aligned, so the rotated stones go through `fill_path` /
/// `stroke_path` instead.
fn rotated_ellipse_path(
    cx: f32,
    cy: f32,
    rx: f32,
    ry: f32,
    angle_deg: f64,
) -> PathOps {
    const KAPPA: f64 = 0.552_284_8;
    let cx = cx as f64;
    let cy = cy as f64;
    let rx = rx as f64;
    let ry = ry as f64;
    let ox = rx * KAPPA;
    let oy = ry * KAPPA;
    let theta = angle_deg.to_radians();
    let cos_t = theta.cos();
    let sin_t = theta.sin();
    let xform = |dx: f64, dy: f64| -> Vec2 {
        let rxv = dx * cos_t - dy * sin_t;
        let ryv = dx * sin_t + dy * cos_t;
        Vec2::new((cx + rxv) as f32, (cy + ryv) as f32)
    };
    let mut path = PathOps::new();
    path.move_to(xform(rx, 0.0));
    path.cubic_to(xform(rx, oy), xform(ox, ry), xform(0.0, ry));
    path.cubic_to(xform(-ox, ry), xform(-rx, oy), xform(-rx, 0.0));
    path.cubic_to(xform(-rx, -oy), xform(-ox, -ry), xform(0.0, -ry));
    path.cubic_to(xform(ox, -ry), xform(rx, -oy), xform(rx, 0.0));
    path.close();
    path
}

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`. Duplicated locally for the 9th
/// time (also lives in floor_grid / floor_detail / thematic_detail
/// / terrain_detail / cobblestone / brick / flagstone /
/// opus_romano); a shared crate-level helper would cut diff
/// noise but bloat this commit, so leave it for a follow-up.
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
        FillPath,
        StrokePath,
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
        fn push_transform(&mut self, _: crate::painter::Transform) {}
        fn pop_transform(&mut self) {}
    }

    impl CaptureCalls {
        fn fill_path_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::FillPath))
                .count()
        }
        fn stroke_path_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::StrokePath))
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
    }

    fn grid(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

    #[test]
    fn paint_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_field_stone(&mut painter, &[], 333);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// One non-nested group, balanced.
    #[test]
    fn paint_emits_balanced_group() {
        let mut painter = CaptureCalls::default();
        paint_field_stone(&mut painter, &grid(20), 333);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert_eq!(begins, 1, "expected exactly one stones group");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacity — field_stone 0.8.
    #[test]
    fn paint_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_field_stone(&mut painter, &grid(20), 333);
        let opacities = painter.opacities();
        assert_eq!(opacities.len(), 1, "expected exactly one group");
        assert_eq!(
            opacities[0],
            (FIELD_STONE_OPACITY * 100.0).round() as u32,
            "stones group should be at {FIELD_STONE_OPACITY}",
        );
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelope.
    #[test]
    fn paints_only_inside_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_field_stone(&mut painter, &grid(20), 333);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Each stone emits exactly one fill_path + one stroke_path.
    #[test]
    fn paint_emits_fill_and_stroke_path_per_stone() {
        let mut painter = CaptureCalls::default();
        paint_field_stone(&mut painter, &grid(20), 333);
        let fills = painter.fill_path_count();
        let strokes = painter.stroke_path_count();
        assert!(fills > 0, "expected at least one stone to fire");
        assert_eq!(
            fills, strokes,
            "each stone emits one fill_path + one stroke_path",
        );
    }
    /// Painter-path determinism: same input → same call sequence.
    #[test]
    fn paint_deterministic_for_same_seed() {
        let tiles = grid(10);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_field_stone(&mut a, &tiles, 333);
        paint_field_stone(&mut b, &tiles, 333);
        assert_eq!(
            a.calls, b.calls,
            "same seed must produce identical Painter calls",
        );
    }

    /// Painter-path seed sensitivity: different seeds must produce
    /// different call sequences (the 10 % gate alone all-but
    /// guarantees this on a 100-tile grid).
    #[test]
    fn paint_seed_sensitive() {
        let tiles = grid(10);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_field_stone(&mut a, &tiles, 333);
        paint_field_stone(&mut b, &tiles, 7);
        assert_ne!(
            a.calls, b.calls,
            "different seeds must produce different Painter calls",
        );
    }
}
