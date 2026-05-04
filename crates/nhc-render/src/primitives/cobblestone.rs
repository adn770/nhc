//! Cobblestone decorator — Phase 4, sub-step 6 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13a of
//! `plans/nhc_pure_ir_plan.md` (the **first decorator port**;
//! brick / flagstone / opus_romano / field_stone / cart_tracks /
//! ore_deposit follow as 2.13b–g).
//!
//! Reproduces ``COBBLESTONE`` (3×3 jittered grid per tile) plus
//! ``COBBLE_STONE`` (decorative stone with 12 % per-tile chance)
//! from ``nhc/rendering/_floor_detail.py``. Both decorators fire
//! on the same predicate (``surface_type ∈ {STREET, PAVED}``)
//! but use independent RNGs (legacy ``_seeded_rng`` derives them
//! from the decorator name).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. The Rust port uses
//! ``Pcg64Mcg`` for both sub-decorators (independent streams
//! from the input seed); under-test fixtures only contain dungeon
//! / cave levels, so cobble emission is exercised via synthetic
//! tile lists in the cargo / Python integration tests.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_cobblestone` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until 2.17
//!   ships the `SvgPainter`-based PyO3 export and 2.19 retires
//!   the Python `ir_to_svg` path).
//! - The new `paint_cobblestone` Painter-based emitter (used by
//!   the Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `cobblestone_shapes` shape-stream
//! generator — the per-tile geometry is RNG-driven and the Painter
//! / SVG outputs MUST consume the RNG streams in lock-step so
//! they stay stamp-for-stamp aligned.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps the grid bucket in
//! `<g opacity="0.35" fill="none" stroke="…" stroke-width="0.4">`
//! and the stones bucket in `<g opacity="0.5">`. The pre-2.13a
//! PNG handler dispatched to `paint_fragments`, which already
//! routes each `<g opacity>` envelope through
//! `paint_offscreen_group` (Phase 5.10's offscreen-buffer
//! composite). The Painter port replaces the SVG-string round-trip
//! with native `begin_group(opacity)` / `end_group()` calls so the
//! Painter trait owns the offscreen-buffer mechanism end-to-end.
//! PNG output should be pixel-equal with the pre-port PNG
//! references — only the intermediate SVG-string emission
//! disappears.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

const CELL: f64 = 32.0;
const COBBLE_STROKE: &str = "#8A7A6A";
const STONE_FILL: &str = "#C8BEB0";
const STONE_STROKE: &str = "#9A8A7A";

/// Group-opacity envelope for the cobble-grid bucket. Lifts the
/// `<g opacity="0.35" …>` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const GRID_OPACITY: f32 = 0.35;
/// Group-opacity envelope for the decorative-stones bucket. Lifts
/// the `<g opacity="0.5">` wrapper.
pub const STONES_OPACITY: f32 = 0.5;

/// Per-shape record — backend-agnostic. The shape stream is the
/// single source of truth: the legacy `draw_cobblestone` formats
/// each shape as an SVG fragment string, `paint_cobblestone`
/// dispatches each shape through the Painter trait. Both paths
/// consume the same RNG sequence in lock-step, so the Painter and
/// SVG output stay stamp-for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
enum CobblestoneShape {
    /// One jittered 3×3 grid cell — emitted as `<rect rx="1">`
    /// inside the grid `<g opacity="0.35">` envelope. The legacy
    /// SVG path strokes only (no fill); the rounded corners
    /// (`rx="1"`) are dropped by the PNG path because `paint_rect`
    /// in `transform/png/fragment.rs` ignores the `rx` attribute.
    /// The Painter port matches that behaviour by going through
    /// `stroke_rect` (axis-aligned, sharp corners).
    GridRect { x: f64, y: f64, w: f64, h: f64 },
    /// One decorative stone — emitted as a rotated `<ellipse>`
    /// with both fill and stroke inside the stones `<g
    /// opacity="0.5">` envelope. Rotation bakes into the path so
    /// the Painter trait can stroke + fill it without an explicit
    /// transform.
    Stone {
        cx: f64,
        cy: f64,
        rx: f64,
        ry: f64,
        angle_deg: f64,
    },
}

/// Per-side shape buckets in legacy emission order:
/// `(grid, stones)`.
type Buckets = (Vec<CobblestoneShape>, Vec<CobblestoneShape>);

/// Walk every tile once and build the `(grid, stones)` buckets.
/// Mirrors the legacy per-tile `cobblestone_tile` + 12 % stone
/// roll. Two independent `Pcg64Mcg` streams: one for the grid
/// jitter, one (XOR'd off `seed`) for the stone roll + ellipse
/// parameters. The RNG consumption order is the parity contract
/// shared between the SVG and Painter paths.
fn cobblestone_shapes(tiles: &[(i32, i32)], seed: u64) -> Buckets {
    let mut grid_rng = Pcg64Mcg::seed_from_u64(seed);
    let mut stone_rng = Pcg64Mcg::seed_from_u64(seed ^ 0x_C0BB_1E57_01E_u64);

    let mut grid: Vec<CobblestoneShape> = Vec::new();
    let mut stones: Vec<CobblestoneShape> = Vec::new();

    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        push_grid_cells(&mut grid_rng, px, py, &mut grid);
        if stone_rng.gen::<f64>() < 0.12 {
            push_stone(&mut stone_rng, px, py, &mut stones);
        }
    }

    (grid, stones)
}

/// Mirrors `_cobblestone_tile`: a 3×3 grid of jittered rounded
/// rectangles, one tile. Pushes one `GridRect` per surviving
/// cell (cells with `sw <= 2.0 || sh <= 2.0` are dropped — same
/// guard as the legacy SVG path).
fn push_grid_cells(
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
    out: &mut Vec<CobblestoneShape>,
) {
    let cols = 3.0_f64;
    let rows = 3.0_f64;
    let cw = CELL / cols;
    let ch = CELL / rows;
    for row in 0..3 {
        for col in 0..3 {
            let jx = rng.gen_range((-cw * 0.1)..(cw * 0.1));
            let jy = rng.gen_range((-ch * 0.1)..(ch * 0.1));
            let jw = rng.gen_range((-cw * 0.08)..(cw * 0.08));
            let jh = rng.gen_range((-ch * 0.08)..(ch * 0.08));
            let cx = px + f64::from(col) * cw + jx + 0.5;
            let cy = py + f64::from(row) * ch + jy + 0.5;
            let sw = cw + jw - 1.0;
            let sh = ch + jh - 1.0;
            if sw > 2.0 && sh > 2.0 {
                out.push(CobblestoneShape::GridRect {
                    x: cx,
                    y: cy,
                    w: sw,
                    h: sh,
                });
            }
        }
    }
}

/// Mirrors `_cobble_stone`: an ellipse with random size and
/// rotation. Caller has already gated on the 12 % probability —
/// this function always emits one shape and consumes 5 RNG values
/// (cx offset, cy offset, rx, ry, angle).
fn push_stone(
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
    out: &mut Vec<CobblestoneShape>,
) {
    let cx = px + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
    let cy = py + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
    let rx: f64 = rng.gen_range(1.5..3.0);
    let ry: f64 = rng.gen_range(1.0..2.5);
    let angle: f64 = rng.gen_range(0.0..180.0);
    out.push(CobblestoneShape::Stone {
        cx,
        cy,
        rx,
        ry,
        angle_deg: angle,
    });
}
/// Painter-trait entry point — Phase 2.13a port.
///
/// Walks the same shape stream as `draw_cobblestone` and dispatches
/// each non-empty bucket through `begin_group(opacity) / end_group()`
/// to match the legacy SVG `<g opacity="…">` envelopes. PNG output
/// stays pixel-equal with the pre-port `paint_fragments` path —
/// only the intermediate SVG-string round-trip disappears.
pub fn paint_cobblestone(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let (grid, stones) = cobblestone_shapes(tiles, seed);

    if !grid.is_empty() {
        painter.begin_group(GRID_OPACITY);
        let stroke_paint = paint_for_hex(COBBLE_STROKE);
        let stroke = Stroke {
            width: round_legacy(0.4),
            line_cap: LineCap::Butt,
            line_join: LineJoin::Miter,
        };
        for shape in &grid {
            if let CobblestoneShape::GridRect { x, y, w, h } = *shape {
                // Legacy SVG emits `<rect>` with `rx="1"` rounded
                // corners, but `transform/png/fragment.rs::paint_rect`
                // ignores `rx`, so the PNG path strokes sharp axis-
                // aligned rects. Match that behaviour via
                // `stroke_rect` (no rounded-corner Painter primitive).
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
        }
        painter.end_group();
    }

    if !stones.is_empty() {
        painter.begin_group(STONES_OPACITY);
        let fill_paint = paint_for_hex(STONE_FILL);
        let stroke_paint = paint_for_hex(STONE_STROKE);
        let stroke = Stroke {
            width: round_legacy(0.5),
            line_cap: LineCap::Butt,
            line_join: LineJoin::Miter,
        };
        for shape in &stones {
            if let CobblestoneShape::Stone {
                cx, cy, rx, ry, angle_deg,
            } = *shape
            {
                let path = rotated_ellipse_path(
                    round_legacy(cx),
                    round_legacy(cy),
                    round_legacy(rx),
                    round_legacy(ry),
                    angle_deg,
                );
                painter.fill_path(
                    &path,
                    &fill_paint,
                    crate::painter::FillRule::Winding,
                );
                painter.stroke_path(&path, &stroke_paint, &stroke);
            }
        }
        painter.end_group();
    }
}

// ── SVG-string formatter (legacy path) ────────────────────────
// ── Painter helpers ───────────────────────────────────────────

/// Build a closed cubic-Bezier ellipse path centred at `(cx, cy)`
/// with radii `(rx, ry)`, rotated by `angle_deg` around `(cx, cy)`.
/// Mirrors the rotated-ellipse helper in `primitives::floor_detail`
/// (same KAPPA approximation) — the rotation bakes into the
/// control-point coords so the path is backend-agnostic. The
/// Painter trait's `fill_ellipse` is axis-aligned, so the rotated
/// stones go through `fill_path` / `stroke_path` instead.
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
/// `format` → `parse_path_d`. Duplicated locally for the 5th time
/// (also lives in floor_grid / floor_detail / thematic_detail /
/// terrain_detail); a shared crate-level helper would cut diff
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
        StrokeRect,
        FillPath,
        StrokePath,
        BeginGroup(u32),
        EndGroup,
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {}
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {
            self.calls.push(Call::StrokeRect);
        }
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
    }

    fn grid(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

    #[test]
    fn paint_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_cobblestone(&mut painter, &[], 333);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// Two non-nested groups (grid then stones), each balanced.
    #[test]
    fn paint_emits_balanced_groups() {
        let mut painter = CaptureCalls::default();
        paint_cobblestone(&mut painter, &grid(8), 333);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert!(begins >= 1, "expected at least the grid group");
        assert!(begins <= 2, "expected at most grid + stones groups");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacities — grid 0.35, stones 0.5.
    #[test]
    fn paint_uses_documented_opacities() {
        let mut painter = CaptureCalls::default();
        paint_cobblestone(&mut painter, &grid(20), 333);
        let opacities = painter.opacities();
        // Grid is the first group (always when tiles produce rects).
        assert_eq!(
            opacities[0],
            (GRID_OPACITY * 100.0).round() as u32,
            "first group should be grid at {GRID_OPACITY}",
        );
        // If a stones group fired, its opacity must be STONES_OPACITY.
        if opacities.len() > 1 {
            assert_eq!(
                opacities[1],
                (STONES_OPACITY * 100.0).round() as u32,
                "second group should be stones at {STONES_OPACITY}",
            );
        }
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside a group envelope.
    #[test]
    fn paints_only_inside_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_cobblestone(&mut painter, &grid(8), 333);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Grid bucket emits stroke_rect (axis-aligned, sharp
    /// corners); stones emit a fill_path + stroke_path pair per
    /// rotated ellipse.
    #[test]
    fn paint_emits_expected_call_kinds() {
        let mut painter = CaptureCalls::default();
        paint_cobblestone(&mut painter, &grid(20), 333);
        // Grid: 9 stroke_rects per tile × ~400 tiles → many.
        assert!(painter.count(&Call::StrokeRect) > 0);
        // Stones: each emits one fill + one stroke (path).
        let fills = painter.count(&Call::FillPath);
        let strokes = painter.count(&Call::StrokePath);
        // Stones are 12% per-tile probabilistic; over 400 tiles
        // we expect dozens. The fill/stroke pair must balance.
        assert_eq!(
            fills, strokes,
            "each stone emits one fill_path + one stroke_path",
        );
    }
    /// Different seeds drive different RNG streams — the captured
    /// call sequence must differ.
    #[test]
    fn paint_different_seeds_diverge() {
        let tiles = grid(15);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_cobblestone(&mut a, &tiles, 333);
        paint_cobblestone(&mut b, &tiles, 7);
        assert_ne!(
            a.calls, b.calls,
            "different seeds must produce different Painter call sequences",
        );
    }
}
