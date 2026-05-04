//! Ore-deposit decorator — Phase 4, sub-step 12 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13g of
//! `plans/nhc_pure_ir_plan.md` (the **seventh and LAST decorator
//! port** — after this commit every decorator branch in
//! `transform/png/decorator.rs` runs through the Painter trait).
//!
//! Reproduces ``ORE_DEPOSIT`` from
//! ``nhc/rendering/_floor_detail.py``: a single diamond glint
//! per ore-deposit wall tile. Predicate fires on
//! ``tile.feature == "ore_deposit"`` (not surface_type — ore
//! deposits sit on cave wall tiles).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** RNG-
//! driven (random center jitter + radius); byte-equal-with-
//! legacy is *not* required. The Rust port uses a single
//! ``Pcg64Mcg`` stream from the input seed (3 draws per tile —
//! cx jitter, cy jitter, radius); the Painter and SVG paths
//! MUST consume the RNG stream in lock-step so they stay stamp-
//! for-stamp aligned.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_ore_deposit` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until
//!   2.17 ships the `SvgPainter`-based PyO3 export and 2.19
//!   retires the Python `ir_to_svg` path).
//! - The new `paint_ore_deposit` Painter-based emitter (used by
//!   the Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `ore_deposit_shapes` shape-
//! stream generator. Lock-step RNG keeps the SVG and Painter
//! outputs stamp-for-stamp aligned even though every diamond's
//! geometry depends on three RNG draws.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! Unlike the prior six decorator ports, the legacy SVG envelope
//! for ore_deposit does NOT carry an `opacity` attribute — only
//! `fill`, `stroke`, and `stroke-width`. The pre-2.13g PNG
//! handler dispatched to `paint_fragments` with `1.0` opacity
//! (ore_deposit's call site in `decorator.rs` passes `1.0`
//! explicitly, so `paint_offscreen_group` is bypassed and
//! diamonds composite directly to the pixmap). The Painter port
//! mirrors that by wrapping the diamonds in
//! `begin_group(1.0) / end_group()`. The fully-opaque envelope
//! is a no-op composite — kept only for symmetry with the other
//! six decorators (every Painter-trait decorator now opens and
//! closes a group, so the dispatcher can rely on a uniform
//! contract).

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps,
    Stroke, Vec2,
};

const CELL: f64 = 32.0;
const ORE_FILL: &str = "#D4B14A";
const ORE_STROKE: &str = "#6A4A1A";

/// Group-opacity envelope for the diamonds bucket. The legacy SVG
/// has no `opacity` attribute on the `<g id="ore-deposits">`
/// wrapper — kept at 1.0 for symmetry with the other six
/// Painter-trait decorators (every decorator opens / closes a
/// group). At 1.0 the offscreen-buffer composite is a no-op.
pub const ORE_DEPOSIT_OPACITY: f32 = 1.0;

const ORE_STROKE_WIDTH: f64 = 0.4;

/// Per-shape record — backend-agnostic. The shape stream is the
/// single source of truth: the legacy `draw_ore_deposit` formats
/// each shape as an SVG `<polygon>` fragment, `paint_ore_deposit`
/// dispatches each shape through the Painter trait. Both paths
/// consume the same RNG sequence in lock-step, so the Painter
/// and SVG output stay stamp-for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
struct OreDepositShape {
    /// Diamond centre x (post-jitter).
    cx: f64,
    /// Diamond centre y (post-jitter).
    cy: f64,
    /// Diamond half-extent (point spacing from centre).
    r: f64,
}

/// Walk every tile once and build the diamonds bucket. Mirrors
/// the legacy per-tile RNG schedule exactly: 3 draws per tile
/// (cx jitter in `[-1, 1)`, cy jitter in `[-1, 1)`, radius in
/// `[1.8, 2.6)`). Single `Pcg64Mcg` stream from `seed`. The RNG
/// consumption order is the parity contract shared between the
/// SVG and Painter paths.
fn ore_deposit_shapes(
    tiles: &[(i32, i32)], seed: u64,
) -> Vec<OreDepositShape> {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut diamonds: Vec<OreDepositShape> = Vec::with_capacity(tiles.len());
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let cx = px + CELL / 2.0 + rng.gen_range(-1.0..1.0);
        let cy = py + CELL / 2.0 + rng.gen_range(-1.0..1.0);
        let r: f64 = rng.gen_range(1.8..2.6);
        diamonds.push(OreDepositShape { cx, cy, r });
    }
    diamonds
}
/// Painter-trait entry point — Phase 2.13g port (the seventh and
/// LAST decorator port).
///
/// Walks the same shape stream as `draw_ore_deposit` and dispatches
/// the non-empty bucket through `begin_group(1.0) / end_group()`
/// to mirror the (opacity-free) legacy SVG envelope. Each diamond
/// dispatches through `fill_path` + `stroke_path` with a closed
/// 4-vertex path so tiny-skia renders both the fill and the
/// closing stroke edge between the last and first vertex (which
/// `stroke_polyline` would leave open). PNG output stays pixel-
/// equal with the pre-port `paint_fragments` path — only the
/// intermediate SVG-string round-trip disappears.
pub fn paint_ore_deposit(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let diamonds = ore_deposit_shapes(tiles, seed);
    if diamonds.is_empty() {
        return;
    }

    let fill_paint = paint_for_hex(ORE_FILL);
    let stroke_paint = paint_for_hex(ORE_STROKE);
    let stroke = Stroke {
        width: round_legacy(ORE_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    painter.begin_group(ORE_DEPOSIT_OPACITY);
    for d in &diamonds {
        let path = diamond_path(d.cx, d.cy, d.r);
        painter.fill_path(&path, &fill_paint, FillRule::Winding);
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
    painter.end_group();
}

// ── Painter helpers ───────────────────────────────────────────

/// Build a closed 4-vertex diamond path (top, right, bottom,
/// left) centred at `(cx, cy)` with half-extent `r`. Each coord
/// goes through `round_legacy` so the Painter path lands on the
/// same f32 values the SVG-string path would have arrived at via
/// `format!("{:.1}")` → `parse_path_d`.
fn diamond_path(cx: f64, cy: f64, r: f64) -> PathOps {
    let mut path = PathOps::with_capacity(5);
    path.move_to(Vec2::new(round_legacy(cx), round_legacy(cy - r)))
        .line_to(Vec2::new(round_legacy(cx + r), round_legacy(cy)))
        .line_to(Vec2::new(round_legacy(cx), round_legacy(cy + r)))
        .line_to(Vec2::new(round_legacy(cx - r), round_legacy(cy)))
        .close();
    path
}

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`. Duplicated locally for the 11th
/// time (also lives in floor_grid / floor_detail / thematic_detail
/// / terrain_detail / cobblestone / brick / flagstone /
/// opus_romano / field_stone / cart_tracks); a shared crate-level
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
        /// Records the path-op vertex coordinates so seed-divergence
        /// tests can detect different RNG draws.
        FillPath(Vec<(i32, i32)>),
        StrokePath(Vec<(i32, i32)>),
        BeginGroup(u32),
        EndGroup,
    }

    fn quantise_path(path: &PathOps) -> Vec<(i32, i32)> {
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
        points
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
        fn fill_path(&mut self, path: &PathOps, _: &Paint, _: FillRule) {
            self.calls.push(Call::FillPath(quantise_path(path)));
        }
        fn stroke_path(&mut self, path: &PathOps, _: &Paint, _: &Stroke) {
            self.calls.push(Call::StrokePath(quantise_path(path)));
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
                .filter(|c| matches!(c, Call::FillPath(_)))
                .count()
        }
        fn stroke_path_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::StrokePath(_)))
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

    fn diag(n: i32) -> Vec<(i32, i32)> {
        (0..n).map(|i| (i, i)).collect()
    }

    #[test]
    fn paint_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_ore_deposit(&mut painter, &[], 333);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// One non-nested group, balanced.
    #[test]
    fn paint_emits_balanced_group() {
        let mut painter = CaptureCalls::default();
        paint_ore_deposit(&mut painter, &diag(5), 333);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert_eq!(begins, 1, "expected exactly one diamonds group");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacity — ore_deposit 1.0 (no SVG opacity
    /// attribute, kept at 1.0 for symmetry with the other six
    /// decorators).
    #[test]
    fn paint_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_ore_deposit(&mut painter, &diag(5), 333);
        let opacities = painter.opacities();
        assert_eq!(opacities.len(), 1, "expected exactly one group");
        assert_eq!(
            opacities[0],
            (ORE_DEPOSIT_OPACITY * 100.0).round() as u32,
            "diamonds group should be at {ORE_DEPOSIT_OPACITY}",
        );
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelope.
    #[test]
    fn paints_only_inside_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_ore_deposit(&mut painter, &diag(5), 333);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Each tile emits one fill_path + one stroke_path on the same
    /// 4-vertex closed diamond.
    #[test]
    fn paint_emits_fill_and_stroke_path_per_tile() {
        let tiles = diag(5);
        let mut painter = CaptureCalls::default();
        paint_ore_deposit(&mut painter, &tiles, 333);
        assert_eq!(
            painter.fill_path_count(),
            tiles.len(),
            "one fill_path per tile",
        );
        assert_eq!(
            painter.stroke_path_count(),
            tiles.len(),
            "one stroke_path per tile",
        );
    }
    /// Painter-path determinism: same input → same call sequence.
    #[test]
    fn paint_deterministic_for_same_seed() {
        let tiles = diag(5);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_ore_deposit(&mut a, &tiles, 333);
        paint_ore_deposit(&mut b, &tiles, 333);
        assert_eq!(
            a.calls, b.calls,
            "same seed must produce identical Painter calls",
        );
    }

    /// Different seeds drive different RNG streams — the captured
    /// call sequence must differ (the per-tile center jitter +
    /// radius alone all-but guarantees this on a 5-tile diagonal).
    #[test]
    fn paint_seed_sensitive() {
        let tiles = diag(5);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_ore_deposit(&mut a, &tiles, 333);
        paint_ore_deposit(&mut b, &tiles, 7);
        assert_ne!(
            a.calls, b.calls,
            "different seeds must produce different Painter calls",
        );
    }

    /// Diamond path is exactly 4 vertices (top, right, bottom,
    /// left) plus a close — the SVG `<polygon points="…">` has 4
    /// pairs of coords.
    #[test]
    fn paint_diamond_has_four_vertices() {
        let mut painter = CaptureCalls::default();
        paint_ore_deposit(&mut painter, &[(0, 0)], 333);
        match &painter.calls[1] {
            Call::FillPath(points) => {
                assert_eq!(
                    points.len(),
                    4,
                    "diamond path must have 4 vertices",
                );
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }
}
