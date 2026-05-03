//! Opus romano decorator — Phase 4, sub-step 9 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13d of
//! `plans/nhc_pure_ir_plan.md` (the **fourth decorator port**;
//! field_stone / cart_tracks / ore_deposit follow as 2.13e–g).
//!
//! Reproduces ``OPUS_ROMANO`` from
//! ``nhc/rendering/_floor_detail.py``: classical Roman /
//! Versailles 4-stone tiling. Each tile is a 6×6 subsquare grid
//! partitioned into one 4×4 square, one 2×4 vertical rectangle,
//! one 2×2 small square, and one 4×2 horizontal rectangle. The
//! arrangement rotates 90° per quarter-turn picked
//! deterministically from the tile coordinates so adjacent tiles
//! don't read as a stripe.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** RNG-
//! free per-tile painter (rotation is coordinate-derived, not
//! random). Existing fixtures don't contain OPUS_ROMANO tiles;
//! coverage rides on synthetic-level tests.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_opus_romano` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until
//!   2.17 ships the `SvgPainter`-based PyO3 export and 2.19
//!   retires the Python `ir_to_svg` path).
//! - The new `paint_opus_romano` Painter-based emitter (used by
//!   the Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `opus_romano_shapes` shape-stream
//! generator. The geometry is RNG-free — it depends only on the
//! tile coordinates — so lock-step concerns are reduced compared
//! to flagstone / cobblestone / brick. The shape-stream split is
//! still kept so the SVG and Painter paths can't drift on the
//! per-tile rotation derivation.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps the stones bucket in
//! `<g opacity="0.45" fill="none" stroke="#7A5A3A"
//! stroke-width="0.5">`. The pre-2.13d PNG handler dispatched to
//! `paint_fragments`, which already routes the `<g opacity>`
//! envelope through `paint_offscreen_group` (Phase 5.10's
//! offscreen-buffer composite). The Painter port replaces the
//! SVG-string round-trip with a native `begin_group(0.45) /
//! end_group()` pair so the Painter trait owns the offscreen-
//! buffer mechanism end-to-end. PNG output should be pixel-equal
//! with the pre-port PNG references — only the intermediate
//! SVG-string emission disappears.
//!
//! ## Rounded-corner note
//!
//! The legacy SVG emits `<rect>` with `rx="0.4"` rounded corners.
//! The PNG path's `paint_rect` in `transform/png/fragment.rs`
//! ignores the `rx` attribute (no rounded-rect renderer), so the
//! pre-port PNG output already had sharp corners. The Painter
//! port mirrors that by dispatching through `stroke_rect` (axis-
//! aligned, sharp corners) — pixel-equal with the pre-port PNG.

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, Rect, Stroke,
};

const CELL: f64 = 32.0;
const OPUS_ROMANO_STROKE: &str = "#7A5A3A";
const SUBDIVISIONS: i32 = 6;
const MORTAR_INSET: f64 = 0.5;

/// Group-opacity envelope for the stones bucket. Lifts the
/// `<g opacity="0.45" …>` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const OPUS_ROMANO_OPACITY: f32 = 0.45;

/// Base 4-stone arrangement on the 6×6 subsquare grid:
/// (sub_x, sub_y, sub_w, sub_h).
const STONES: [(i32, i32, i32, i32); 4] = [
    (0, 0, 4, 4),
    (4, 0, 2, 4),
    (0, 4, 2, 2),
    (2, 4, 4, 2),
];

fn rotate_stone_in_grid(
    sx: i32, sy: i32, sw: i32, sh: i32, n_quarter: i32,
) -> (i32, i32, i32, i32) {
    let mut s = (sx, sy, sw, sh);
    let n = ((n_quarter % 4) + 4) % 4;
    for _ in 0..n {
        s = (SUBDIVISIONS - s.1 - s.3, s.0, s.3, s.2);
    }
    s
}

/// Per-shape record — backend-agnostic. The shape stream is the
/// single source of truth: the legacy `draw_opus_romano` formats
/// each shape as an SVG `<rect>` fragment, `paint_opus_romano`
/// dispatches each shape through the Painter trait. Both paths
/// derive geometry from the same tile-coordinate-driven rotation
/// so the SVG and Painter outputs stay stamp-for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
struct OpusRomanoStone {
    x: f64,
    y: f64,
    w: f64,
    h: f64,
}

/// Walk every tile once and build the stones bucket. Mirrors the
/// legacy per-tile 4-stone Versailles layout. RNG-free: rotation
/// is derived from `(x, y)` via `(x * 7 + y * 13) % 4`.
fn opus_romano_shapes(tiles: &[(i32, i32)]) -> Vec<OpusRomanoStone> {
    let sub = CELL / f64::from(SUBDIVISIONS);
    let mut stones: Vec<OpusRomanoStone> = Vec::with_capacity(tiles.len() * 4);
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let rotation = (x * 7 + y * 13).rem_euclid(4);
        for &(sx, sy, sw, sh) in &STONES {
            let (sx, sy, sw, sh) =
                rotate_stone_in_grid(sx, sy, sw, sh, rotation);
            let xx = px + f64::from(sx) * sub + MORTAR_INSET;
            let yy = py + f64::from(sy) * sub + MORTAR_INSET;
            let w = f64::from(sw) * sub - 2.0 * MORTAR_INSET;
            let h = f64::from(sh) * sub - 2.0 * MORTAR_INSET;
            stones.push(OpusRomanoStone { x: xx, y: yy, w, h });
        }
    }
    stones
}

/// Opus-romano decorator entry point — Phase 4 sub-step 9.
///
/// `tiles` is the OPUS_ROMANO-surface tile list; `seed` is
/// unused (rotation is per-tile coordinate-derived, not RNG-
/// driven) but kept for API symmetry with the other decorators.
pub fn draw_opus_romano(
    tiles: &[(i32, i32)], _seed: u64,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let stones = opus_romano_shapes(tiles);
    if stones.is_empty() {
        return Vec::new();
    }
    let mut rects: Vec<String> = Vec::with_capacity(stones.len());
    for s in &stones {
        rects.push(format!(
            "<rect x=\"{:.2}\" y=\"{:.2}\" \
             width=\"{:.2}\" height=\"{:.2}\" rx=\"0.4\"/>",
            s.x, s.y, s.w, s.h,
        ));
    }
    vec![format!(
        "<g opacity=\"0.45\" fill=\"none\" stroke=\"{OPUS_ROMANO_STROKE}\" \
         stroke-width=\"0.5\">{}</g>",
        rects.concat(),
    )]
}

/// Painter-trait entry point — Phase 2.13d port.
///
/// Walks the same shape stream as `draw_opus_romano` and
/// dispatches the non-empty bucket through `begin_group(0.45) /
/// end_group()` to match the legacy SVG `<g opacity="0.45">`
/// envelope. PNG output stays pixel-equal with the pre-port
/// `paint_fragments` path — only the intermediate SVG-string
/// round-trip disappears.
///
/// Each stone dispatches through `stroke_rect` (axis-aligned,
/// sharp corners) — matching the pre-port PNG behaviour where
/// `paint_rect` in `transform/png/fragment.rs` ignored the
/// legacy `rx="0.4"` attribute.
pub fn paint_opus_romano(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    _seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let stones = opus_romano_shapes(tiles);
    if stones.is_empty() {
        return;
    }

    painter.begin_group(OPUS_ROMANO_OPACITY);
    let stroke_paint = paint_for_hex(OPUS_ROMANO_STROKE);
    let stroke = Stroke {
        width: round_legacy(0.5),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    for s in &stones {
        painter.stroke_rect(
            Rect::new(
                round_legacy(s.x),
                round_legacy(s.y),
                round_legacy(s.w),
                round_legacy(s.h),
            ),
            &stroke_paint,
            &stroke,
        );
    }
    painter.end_group();
}

// ── Painter helpers ───────────────────────────────────────────

/// Mirror the legacy SVG-string path's `{:.2}` truncation +
/// reparse. Rust's `{:.2}` uses banker's rounding, matching
/// Python's `f"{v:.2f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`. Duplicated locally for the 8th
/// time (also lives in floor_grid / floor_detail / thematic_detail
/// / terrain_detail / cobblestone / brick / flagstone); a shared
/// crate-level helper would cut diff noise but bloat this commit,
/// so leave it for a follow-up. Note: opus_romano uses 2 decimals
/// of precision (legacy `{:.2}`) where flagstone et al. use 1.
fn round_legacy(v: f64) -> f32 {
    let s = format!("{:.2}", v);
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
        assert!(draw_opus_romano(&[], 0).is_empty());
    }

    #[test]
    fn four_rects_per_tile() {
        let out = draw_opus_romano(&[(0, 0)], 0);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].matches("<rect").count(), 4);
    }

    #[test]
    fn rotation_independent_of_seed() {
        // The painter is RNG-free; same input produces same
        // output regardless of seed.
        let tiles: Vec<(i32, i32)> = (0..4)
            .flat_map(|y| (0..4).map(move |x| (x, y)))
            .collect();
        assert_eq!(
            draw_opus_romano(&tiles, 0),
            draw_opus_romano(&tiles, 999),
        );
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
        /// Records the rect coordinates so divergence tests can
        /// distinguish per-tile rotations.
        StrokeRect(i32, i32, i32, i32),
        BeginGroup(u32),
        EndGroup,
    }

    fn is_stroke_rect(call: &Call) -> bool {
        matches!(call, Call::StrokeRect(..))
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {}
        fn stroke_rect(&mut self, rect: Rect, _: &Paint, _: &Stroke) {
            // Quantise to 0.01-pixel buckets so f32 rounding noise
            // doesn't trip equality tests (legacy uses {:.2}).
            self.calls.push(Call::StrokeRect(
                (rect.x * 100.0).round() as i32,
                (rect.y * 100.0).round() as i32,
                (rect.w * 100.0).round() as i32,
                (rect.h * 100.0).round() as i32,
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
        paint_opus_romano(&mut painter, &[], 0);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// One non-nested group, balanced.
    #[test]
    fn paint_emits_balanced_group() {
        let mut painter = CaptureCalls::default();
        paint_opus_romano(&mut painter, &grid(4), 0);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert_eq!(begins, 1, "expected exactly one stones group");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacity — opus_romano 0.45.
    #[test]
    fn paint_uses_documented_opacity() {
        let mut painter = CaptureCalls::default();
        paint_opus_romano(&mut painter, &grid(4), 0);
        let opacities = painter.opacities();
        assert_eq!(opacities.len(), 1, "expected exactly one group");
        assert_eq!(
            opacities[0],
            (OPUS_ROMANO_OPACITY * 100.0).round() as u32,
            "stones group should be at {OPUS_ROMANO_OPACITY}",
        );
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelope.
    #[test]
    fn paints_only_inside_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_opus_romano(&mut painter, &grid(4), 0);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Stones bucket emits stroke_rect (axis-aligned rectangles).
    #[test]
    fn paint_emits_only_stroke_rect() {
        let mut painter = CaptureCalls::default();
        paint_opus_romano(&mut painter, &grid(4), 0);
        assert!(painter.stroke_rect_count() > 0);
    }

    /// 4 stones per tile.
    #[test]
    fn paint_emits_four_stroke_rects_per_tile() {
        let mut painter = CaptureCalls::default();
        paint_opus_romano(&mut painter, &[(0, 0)], 0);
        assert_eq!(
            painter.stroke_rect_count(),
            4,
            "4 stones per tile (Versailles 4-stone)",
        );
    }

    /// Painter and SVG paths derive geometry from the same shape
    /// stream — the stamp counts (rects on the SVG side, stroke_rect
    /// on the Painter side) must match.
    #[test]
    fn paint_and_draw_emit_same_stamp_counts() {
        let tiles = grid(4);
        let mut painter = CaptureCalls::default();
        paint_opus_romano(&mut painter, &tiles, 0);
        let svg = draw_opus_romano(&tiles, 0);
        let svg_rects: usize =
            svg.iter().map(|g| g.matches("<rect").count()).sum();
        assert_eq!(
            painter.stroke_rect_count(),
            svg_rects,
            "opus_romano stamp counts must match between SVG and \
             Painter paths",
        );
    }

    /// RNG-free primitive: same tiles must produce identical
    /// Painter call sequences regardless of seed.
    #[test]
    fn paint_seed_independent() {
        let tiles = grid(4);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_opus_romano(&mut a, &tiles, 0);
        paint_opus_romano(&mut b, &tiles, 999);
        assert_eq!(
            a.calls, b.calls,
            "RNG-free primitive: seed must not affect Painter calls",
        );
    }
}
