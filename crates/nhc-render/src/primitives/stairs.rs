//! Stairs primitive — Phase 4.3, third deterministic port.
//!
//! Reproduces `_render_stairs` from `nhc/rendering/_stairs_svg.py`
//! per the schema's `StairsOp` shape: each stair surfaces as
//! optional cave-theme fill polygon (when the floor's theme is
//! "cave") followed by 2 rail lines and 6 step lines, in legacy
//! emit order.
//!
//! No RNG, no Perlin, no Shapely. Pure trigonometry-free FP
//! arithmetic on `i32` × cell sizes — stair tile coords are
//! integers, derived geometry is `f64` formatted with `{:.1}`.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_stairs` SVG-string emitter (used by the FFI
//!   / `nhc/rendering/ir_to_svg.py` Python path until 2.17 ships
//!   the `SvgPainter`-based PyO3 export and 2.19 retires the
//!   Python `ir_to_svg` path).
//! - The new `paint_stairs` Painter-based emitter (used by the
//!   Rust `transform/png` path via `SkiaPainter` and, after 2.17,
//!   by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share `CELL` / `N_STEPS` / `WIDE_H` / `NARROW_H` /
//! `M` so the byte-equality contract holds.

use std::fmt::Write;

use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

const CELL: f64 = 32.0;
const INK: &str = "#000000";
// Python's `f"{1.0}"` produces "1.0", but Rust's `format!("{}", 1.0_f64)`
// strips the trailing zero. The legacy stair renderer formats stroke-
// widths with bare `{}` (no `:.1f`), so the byte-equal contract requires
// hardcoded string constants here. Coordinates inside the elements all
// use `{:.1}` in both legacy and Rust, so they round-trip cleanly.
const RAIL_SW: &str = "1.5";
const STEP_SW: &str = "1.0";
const N_STEPS: i32 = 5;
const WIDE_H: f64 = CELL * 0.4;
const NARROW_H: f64 = CELL * 0.1;
const M: f64 = CELL * 0.1; // tile margin

// Painter-path mirrors of the SVG-string constants, kept as f32
// because the Painter trait expresses geometry in f32 pixel space
// (matching `tiny_skia` and the SVG number formatter).
const CELL_F: f32 = 32.0;
const WIDE_H_F: f32 = CELL_F * 0.4;
const NARROW_H_F: f32 = CELL_F * 0.1;
const M_F: f32 = CELL_F * 0.1;
const RAIL_WIDTH: f32 = 1.5;
const STEP_WIDTH: f32 = 1.0;

/// Discriminant matching `StairDirection` in `floor_ir.fbs`.
const DIR_DOWN: u8 = 1;

const INK_PAINT: Paint = Paint {
    color: Color { r: 0, g: 0, b: 0, a: 1.0 },
};

fn round_stroke(width: f32) -> Stroke {
    Stroke {
        width,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    }
}

/// Parse a `#RRGGBB` hex string into an opaque `Paint`. Falls back
/// to opaque black on malformed input — the legacy PNG handler
/// did the same.
fn parse_hex_paint(hex: &str) -> Paint {
    let parsed = hex
        .strip_prefix('#')
        .filter(|s| s.len() == 6)
        .and_then(|s| {
            let r = u8::from_str_radix(&s[0..2], 16).ok()?;
            let g = u8::from_str_radix(&s[2..4], 16).ok()?;
            let b = u8::from_str_radix(&s[4..6], 16).ok()?;
            Some((r, g, b))
        });
    let (r, g, b) = parsed.unwrap_or((0, 0, 0));
    Paint::solid(Color::rgb(r, g, b))
}

/// Emit the stairs-layer SVG fragment.
///
/// `stairs` is `[(x, y, direction)]` with `direction` matching the
/// schema's `StairDirection` enum (`Up=0`, `Down=1`).
/// `theme` and `fill_color` come from the IR's `StairsOp` —
/// `theme == "cave"` toggles the per-stair cave fill polygon,
/// `fill_color` is the resolved cave-fill colour.
///
/// Returns a list of SVG element strings (one per polygon /
/// line). Per stair the output is:
///
/// - (cave only) one `<polygon>` cave fill
/// - 2 `<line>` rails (top + bottom)
/// - 6 `<line>` step lines (`N_STEPS + 1` for the closed range)
///
/// Total: 8 or 9 elements per stair, depending on theme.
pub fn draw_stairs(
    stairs: &[(i32, i32, u8)],
    theme: &str,
    fill_color: &str,
) -> Vec<String> {
    let mut out: Vec<String> = Vec::with_capacity(stairs.len() * 9);
    let is_cave = theme == "cave";
    for &(x, y, direction) in stairs {
        let down = direction == DIR_DOWN;
        let px = x as f64 * CELL;
        let py = y as f64 * CELL;
        let cy = py + CELL / 2.0;
        let left_x = px + M;
        let right_x = px + CELL - M;

        if is_cave {
            let pts = if down {
                format!(
                    "{:.1},{:.1} {:.1},{:.1} {:.1},{:.1} {:.1},{:.1}",
                    left_x, cy - WIDE_H,
                    right_x, cy - NARROW_H,
                    right_x, cy + NARROW_H,
                    left_x, cy + WIDE_H,
                )
            } else {
                format!(
                    "{:.1},{:.1} {:.1},{:.1} {:.1},{:.1} {:.1},{:.1}",
                    left_x, cy - NARROW_H,
                    right_x, cy - WIDE_H,
                    right_x, cy + WIDE_H,
                    left_x, cy + NARROW_H,
                )
            };
            out.push(format!(
                "<polygon points=\"{pts}\" fill=\"{fill_color}\" stroke=\"none\"/>"
            ));
        }

        let (top_y0, top_y1, bot_y0, bot_y1, wide_start, narrow_end);
        if down {
            top_y0 = cy - WIDE_H;
            top_y1 = cy - NARROW_H;
            bot_y0 = cy + WIDE_H;
            bot_y1 = cy + NARROW_H;
            wide_start = WIDE_H;
            narrow_end = NARROW_H;
        } else {
            top_y0 = cy - NARROW_H;
            top_y1 = cy - WIDE_H;
            bot_y0 = cy + NARROW_H;
            bot_y1 = cy + WIDE_H;
            wide_start = NARROW_H;
            narrow_end = WIDE_H;
        }

        out.push(format!(
            "<line x1=\"{:.1}\" y1=\"{:.1}\" x2=\"{:.1}\" y2=\"{:.1}\" \
             stroke=\"{INK}\" stroke-width=\"{RAIL_SW}\" \
             stroke-linecap=\"round\"/>",
            left_x, top_y0, right_x, top_y1,
        ));
        out.push(format!(
            "<line x1=\"{:.1}\" y1=\"{:.1}\" x2=\"{:.1}\" y2=\"{:.1}\" \
             stroke=\"{INK}\" stroke-width=\"{RAIL_SW}\" \
             stroke-linecap=\"round\"/>",
            left_x, bot_y0, right_x, bot_y1,
        ));

        let span = right_x - left_x;
        for i in 0..=N_STEPS {
            let t = i as f64 / N_STEPS as f64;
            let sx = left_x + span * t;
            let half = wide_start + (narrow_end - wide_start) * t;
            let mut s = String::with_capacity(120);
            write!(
                &mut s,
                "<line x1=\"{sx:.1}\" y1=\"{:.1}\" x2=\"{sx:.1}\" y2=\"{:.1}\" \
                 stroke=\"{INK}\" stroke-width=\"{STEP_SW}\" \
                 stroke-linecap=\"round\"/>",
                cy - half,
                cy + half,
            )
            .unwrap();
            out.push(s);
        }
    }
    out
}

// ── Painter-based emitter (Phase 2.6) ───────────────────────────

/// Paint stairs via the `Painter` trait.
///
/// Mirrors `draw_stairs`'s geometry pixel-for-pixel: per stair,
/// optional cave-theme tapering trapezoid fill (when
/// `theme == "cave"`), then the two rail strokes, then
/// `N_STEPS + 1 == 6` step strokes. All ink uses opaque black at
/// the trait-level Paint; cave fill uses the `#RRGGBB` colour
/// passed in `fill_color` (falling back to opaque black on
/// malformed input). Stroke caps and joins are both `Round` for
/// rails and steps, matching the SVG `stroke-linecap="round"` and
/// the legacy PNG handler's `LineCap::Round` / `LineJoin::Round`.
pub fn paint_stairs(
    painter: &mut dyn Painter,
    stairs: &[(i32, i32, u8)],
    theme: &str,
    fill_color: &str,
) {
    let is_cave = theme == "cave";
    let cave_fill = parse_hex_paint(fill_color);
    let rail = round_stroke(RAIL_WIDTH);
    let step = round_stroke(STEP_WIDTH);

    for &(x, y, direction) in stairs {
        let down = direction == DIR_DOWN;
        let px = x as f32 * CELL_F;
        let py = y as f32 * CELL_F;
        let cy = py + CELL_F / 2.0;
        let left_x = px + M_F;
        let right_x = px + CELL_F - M_F;

        if is_cave {
            let mut path = PathOps::with_capacity(5);
            if down {
                path.move_to(Vec2::new(left_x, cy - WIDE_H_F));
                path.line_to(Vec2::new(right_x, cy - NARROW_H_F));
                path.line_to(Vec2::new(right_x, cy + NARROW_H_F));
                path.line_to(Vec2::new(left_x, cy + WIDE_H_F));
            } else {
                path.move_to(Vec2::new(left_x, cy - NARROW_H_F));
                path.line_to(Vec2::new(right_x, cy - WIDE_H_F));
                path.line_to(Vec2::new(right_x, cy + WIDE_H_F));
                path.line_to(Vec2::new(left_x, cy + NARROW_H_F));
            }
            path.close();
            painter.fill_path(&path, &cave_fill, FillRule::Winding);
        }

        let (top_y0, top_y1, bot_y0, bot_y1, wide_start, narrow_end) = if down {
            (
                cy - WIDE_H_F,
                cy - NARROW_H_F,
                cy + WIDE_H_F,
                cy + NARROW_H_F,
                WIDE_H_F,
                NARROW_H_F,
            )
        } else {
            (
                cy - NARROW_H_F,
                cy - WIDE_H_F,
                cy + NARROW_H_F,
                cy + WIDE_H_F,
                NARROW_H_F,
                WIDE_H_F,
            )
        };

        stroke_segment(painter, left_x, top_y0, right_x, top_y1, &rail);
        stroke_segment(painter, left_x, bot_y0, right_x, bot_y1, &rail);

        let span = right_x - left_x;
        for i in 0..=N_STEPS {
            let t = i as f32 / N_STEPS as f32;
            let sx = left_x + span * t;
            let half = wide_start + (narrow_end - wide_start) * t;
            stroke_segment(painter, sx, cy - half, sx, cy + half, &step);
        }
    }
}

fn stroke_segment(
    painter: &mut dyn Painter,
    x1: f32,
    y1: f32,
    x2: f32,
    y2: f32,
    stroke: &Stroke,
) {
    let mut path = PathOps::with_capacity(2);
    path.move_to(Vec2::new(x1, y1));
    path.line_to(Vec2::new(x2, y2));
    painter.stroke_path(&path, &INK_PAINT, stroke);
}

#[cfg(test)]
mod tests {
    use super::{
        draw_stairs, paint_stairs, NARROW_H_F, RAIL_WIDTH, STEP_WIDTH, WIDE_H_F,
    };
    use crate::painter::{
        Color, FillRule, LineCap, LineJoin, Paint, PathOp, PathOps, Stroke, Vec2,
    };

    /// Records every Painter call for the paint_* unit tests so
    /// we can assert call counts and per-call geometry without
    /// rasterising. Mirrors `primitives::shadow::tests::CaptureCalls`
    /// — only the methods stairs actually uses are non-unreachable.
    #[derive(Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
    }

    #[derive(Debug)]
    enum Call {
        FillPath(Vec<PathOp>, Paint, FillRule),
        StrokePath(Vec<PathOp>, Paint, Stroke),
    }

    impl crate::painter::Painter for CaptureCalls {
        fn fill_rect(&mut self, _: crate::painter::Rect, _: &Paint) {
            unreachable!("stairs primitive never fills rects");
        }
        fn stroke_rect(
            &mut self,
            _: crate::painter::Rect,
            _: &Paint,
            _: &Stroke,
        ) {
            unreachable!("stairs primitive never strokes rects");
        }
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {
            unreachable!("stairs primitive never paints circles");
        }
        fn fill_ellipse(
            &mut self,
            _: f32,
            _: f32,
            _: f32,
            _: f32,
            _: &Paint,
        ) {
            unreachable!("stairs primitive never paints ellipses");
        }
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {
            unreachable!("stairs primitive never paints polygons");
        }
        fn stroke_polyline(&mut self, _: &[Vec2], _: &Paint, _: &Stroke) {
            unreachable!("stairs primitive never strokes polylines");
        }
        fn fill_path(&mut self, path: &PathOps, paint: &Paint, rule: FillRule) {
            self.calls.push(Call::FillPath(path.ops.clone(), *paint, rule));
        }
        fn stroke_path(&mut self, path: &PathOps, paint: &Paint, stroke: &Stroke) {
            self.calls.push(Call::StrokePath(path.ops.clone(), *paint, *stroke));
        }
        fn begin_group(&mut self, _: f32) {
            unreachable!("stairs primitive never opens a group");
        }
        fn end_group(&mut self) {
            unreachable!("stairs primitive never closes a group");
        }
        fn push_clip(&mut self, _: &PathOps, _: FillRule) {
            unreachable!("stairs primitive never pushes a clip");
        }
        fn pop_clip(&mut self) {
            unreachable!("stairs primitive never pops a clip");
        }
        fn push_transform(&mut self, _: crate::painter::Transform) {
            unreachable!("stairs primitive never pushes a transform");
        }
        fn pop_transform(&mut self) {
            unreachable!("stairs primitive never pops a transform");
        }
    }

    #[test]
    fn empty_stairs_returns_empty_vec() {
        assert!(draw_stairs(&[], "dungeon", "#fff").is_empty());
    }

    #[test]
    fn dungeon_stairs_emits_eight_elements_per_stair() {
        // Non-cave theme: no cave fill polygon → 2 rails + 6
        // step lines = 8 elements per stair.
        let out = draw_stairs(&[(0, 0, 0)], "dungeon", "#aaa");
        assert_eq!(out.len(), 8);
        // First two are the rails, rest are step lines.
        assert!(out[0].starts_with("<line"));
        assert!(out[1].starts_with("<line"));
        for i in 2..8 {
            assert!(out[i].starts_with("<line x1="));
        }
    }

    #[test]
    fn cave_stairs_emits_nine_elements_per_stair() {
        // Cave theme: 1 polygon + 2 rails + 6 step lines = 9.
        let out = draw_stairs(&[(0, 0, 0)], "cave", "#F5EBD8");
        assert_eq!(out.len(), 9);
        assert!(out[0].starts_with("<polygon points="));
        assert!(out[0].contains("fill=\"#F5EBD8\""));
    }

    #[test]
    fn down_stair_emits_inverted_rail_pattern() {
        // Up stairs: top rail goes (narrow → wide), bottom (narrow → wide).
        // Down stairs: top rail goes (wide → narrow), bottom (wide → narrow).
        // The y1 of the top rail tells the story:
        //   Up:   y1 = cy - NARROW_H = 16 - 3.2 = 12.8
        //   Down: y1 = cy - WIDE_H   = 16 - 12.8 = 3.2
        let up = draw_stairs(&[(0, 0, 0)], "dungeon", "#fff");
        let dn = draw_stairs(&[(0, 0, 1)], "dungeon", "#fff");
        assert!(up[0].contains("y1=\"12.8\""), "up rail top: {}", up[0]);
        assert!(dn[0].contains("y1=\"3.2\""), "down rail top: {}", dn[0]);
    }

    #[test]
    fn stair_at_offset_uses_pixel_coords() {
        // (x=2, y=3) → pixel (64, 96). cy = 96 + 16 = 112.
        // left_x = 64 + 3.2 = 67.2.
        let out = draw_stairs(&[(2, 3, 0)], "dungeon", "#fff");
        assert!(out[0].contains("x1=\"67.2\""), "{}", out[0]);
        assert!(out[0].contains("y1=\"108.8\""), "{}", out[0]); // cy - NARROW_H
    }

    fn round_endpoints(call: &Call) -> Option<((f32, f32), (f32, f32))> {
        match call {
            Call::StrokePath(ops, _, _) => match (ops.first(), ops.get(1)) {
                (Some(PathOp::MoveTo(a)), Some(PathOp::LineTo(b))) => {
                    Some(((a.x, a.y), (b.x, b.y)))
                }
                _ => None,
            },
            _ => None,
        }
    }

    fn stroke_of(call: &Call) -> Stroke {
        match call {
            Call::StrokePath(_, _, s) => *s,
            _ => panic!("expected StrokePath, got {:?}", call),
        }
    }

    fn stroke_paint(call: &Call) -> Paint {
        match call {
            Call::StrokePath(_, p, _) => *p,
            _ => panic!("expected StrokePath, got {:?}", call),
        }
    }

    #[test]
    fn paint_stairs_dungeon_emits_two_rails_plus_six_steps() {
        // Non-cave theme → no fill_path call; 2 rail strokes
        // followed by 6 step strokes = 8 stroke_path calls.
        let mut p = CaptureCalls::default();
        paint_stairs(&mut p, &[(0, 0, 0)], "dungeon", "#aaaaaa");

        assert_eq!(p.calls.len(), 8, "8 stroke calls, no fills");
        for call in &p.calls {
            assert!(
                matches!(call, Call::StrokePath(..)),
                "non-cave path emits no fills: got {:?}",
                call
            );
        }

        // First two are rails (RAIL_WIDTH); remaining six are
        // steps (STEP_WIDTH). Both use Round caps and joins, and
        // both ink with opaque black (ignoring fill_color, which
        // only feeds the cave-theme polygon).
        let black = Paint::solid(Color::rgb(0, 0, 0));
        for rail_idx in 0..2 {
            let s = stroke_of(&p.calls[rail_idx]);
            assert_eq!(s.width, RAIL_WIDTH, "rail width @ {rail_idx}");
            assert_eq!(s.line_cap, LineCap::Round);
            assert_eq!(s.line_join, LineJoin::Round);
            assert_eq!(stroke_paint(&p.calls[rail_idx]), black);
        }
        for step_idx in 2..8 {
            let s = stroke_of(&p.calls[step_idx]);
            assert_eq!(s.width, STEP_WIDTH, "step width @ {step_idx}");
            assert_eq!(s.line_cap, LineCap::Round);
            assert_eq!(s.line_join, LineJoin::Round);
            assert_eq!(stroke_paint(&p.calls[step_idx]), black);
        }
    }

    #[test]
    fn paint_stairs_cave_emits_fill_then_rails_then_steps() {
        // Cave theme → 1 fill_path (cave trapezoid) + 2 rails +
        // 6 steps = 9 calls in that order.
        let mut p = CaptureCalls::default();
        paint_stairs(&mut p, &[(0, 0, 1)], "cave", "#F5EBD8");

        assert_eq!(p.calls.len(), 9);
        match &p.calls[0] {
            Call::FillPath(ops, paint, rule) => {
                assert_eq!(*rule, FillRule::Winding);
                // Cave fill paint must be the parsed #F5EBD8 at
                // full alpha. 0xF5=245, 0xEB=235, 0xD8=216.
                assert_eq!(paint.color, Color::rgb(0xF5, 0xEB, 0xD8));
                // MoveTo + 3 LineTo + Close = 5 ops.
                assert_eq!(ops.len(), 5);
                assert!(matches!(ops[0], PathOp::MoveTo(_)));
                assert!(matches!(ops[1], PathOp::LineTo(_)));
                assert!(matches!(ops[2], PathOp::LineTo(_)));
                assert!(matches!(ops[3], PathOp::LineTo(_)));
                assert_eq!(ops[4], PathOp::Close);
            }
            other => panic!("first call must be FillPath, got {:?}", other),
        }
        // Remaining 8 are stroke calls (rails then steps).
        for call in &p.calls[1..] {
            assert!(matches!(call, Call::StrokePath(..)), "got {:?}", call);
        }
        // Same width contract as the dungeon path.
        for rail_idx in 1..3 {
            assert_eq!(stroke_of(&p.calls[rail_idx]).width, RAIL_WIDTH);
        }
        for step_idx in 3..9 {
            assert_eq!(stroke_of(&p.calls[step_idx]).width, STEP_WIDTH);
        }
    }

    #[test]
    fn paint_stairs_up_vs_down_invert_rail_orientation() {
        // Up stair @ (0,0): top rail starts at left_x, cy-NARROW
        // (3.2, 12.8) and ends at right_x, cy-WIDE (28.8, 3.2).
        // Down stair @ (0,0): top rail starts at left_x, cy-WIDE
        // (3.2, 3.2) and ends at right_x, cy-NARROW (28.8, 12.8).
        // The y of the start of the top rail flips between them.
        let mut up = CaptureCalls::default();
        paint_stairs(&mut up, &[(0, 0, 0)], "dungeon", "#fff");
        let mut dn = CaptureCalls::default();
        paint_stairs(&mut dn, &[(0, 0, 1)], "dungeon", "#fff");

        let up_rail0 = round_endpoints(&up.calls[0]).expect("up rail 0");
        let dn_rail0 = round_endpoints(&dn.calls[0]).expect("dn rail 0");

        // Both top rails start at the same x (left_x = 3.2).
        assert_eq!(up_rail0.0 .0, 3.2);
        assert_eq!(dn_rail0.0 .0, 3.2);
        // But the start y flips: Up = cy - NARROW (12.8), Down = cy - WIDE (3.2).
        let cy = 16.0_f32;
        assert!((up_rail0.0 .1 - (cy - NARROW_H_F)).abs() < 1e-4);
        assert!((dn_rail0.0 .1 - (cy - WIDE_H_F)).abs() < 1e-4);
    }

    #[test]
    fn paint_stairs_empty_input_emits_nothing() {
        let mut p = CaptureCalls::default();
        paint_stairs(&mut p, &[], "dungeon", "#fff");
        assert!(p.calls.is_empty());
    }
}
