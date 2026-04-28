//! Stairs op rasterisation — Phase 5.2.5 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_stairs_from_ir`: per-stair tapering wedge +
//! parallel step lines + (cave theme only) a fill polygon.
//! Geometry constants match `primitives::stairs` so a future
//! audit hits one source of truth, but we don't share helpers
//! across the FFI boundary — the SVG path constructs strings,
//! the PNG path constructs `tiny-skia::Path`s, and the parity
//! gate keeps both honest.

use tiny_skia::{
    Color, FillRule, LineCap, LineJoin, Paint, PathBuilder, Stroke,
};

use crate::ir::{FloorIR, OpEntry, StairDirection, StairsOp};

use super::RasterCtx;

const CELL: f32 = 32.0;
const N_STEPS: i32 = 5;
const WIDE_H: f32 = CELL * 0.4;
const NARROW_H: f32 = CELL * 0.1;
const M: f32 = CELL * 0.1; // tile margin
const RAIL_WIDTH: f32 = 1.5;
const STEP_WIDTH: f32 = 1.0;

fn ink_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(0, 0, 0, 0xFF));
    p.anti_alias = true;
    p
}

fn rail_stroke() -> Stroke {
    Stroke {
        width: RAIL_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
        ..Stroke::default()
    }
}

fn step_stroke() -> Stroke {
    Stroke {
        width: STEP_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
        ..Stroke::default()
    }
}

fn parse_hex_rgb(s: &str) -> Option<(u8, u8, u8)> {
    let s = s.strip_prefix('#')?;
    if s.len() != 6 {
        return None;
    }
    let r = u8::from_str_radix(&s[0..2], 16).ok()?;
    let g = u8::from_str_radix(&s[2..4], 16).ok()?;
    let b = u8::from_str_radix(&s[4..6], 16).ok()?;
    Some((r, g, b))
}

fn fill_paint(hex: &str) -> Paint<'static> {
    let mut p = Paint::default();
    let (r, g, b) = parse_hex_rgb(hex).unwrap_or((0, 0, 0));
    p.set_color(Color::from_rgba8(r, g, b, 0xFF));
    p.anti_alias = true;
    p
}

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_stairs_op() {
        Some(o) => o,
        None => return,
    };
    let stairs = match op.stairs() {
        Some(s) => s,
        None => return,
    };
    let theme = op.theme().unwrap_or("");
    let fill_color = op.fill_color().unwrap_or("#000000");
    let is_cave = theme == "cave";

    let cave_fill = fill_paint(fill_color);
    let ink = ink_paint();
    let rail = rail_stroke();
    let step = step_stroke();

    for stair in stairs.iter() {
        draw_stair(
            &op,
            stair.x(),
            stair.y(),
            stair.direction(),
            is_cave,
            &cave_fill,
            &ink,
            &rail,
            &step,
            ctx,
        );
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_stair(
    _op: &StairsOp<'_>,
    x: i32,
    y: i32,
    direction: StairDirection,
    is_cave: bool,
    cave_fill: &Paint<'_>,
    ink: &Paint<'_>,
    rail: &Stroke,
    step: &Stroke,
    ctx: &mut RasterCtx<'_>,
) {
    let down = direction == StairDirection::Down;
    let px = x as f32 * CELL;
    let py = y as f32 * CELL;
    let cy = py + CELL / 2.0;
    let left_x = px + M;
    let right_x = px + CELL - M;

    if is_cave {
        let mut pb = PathBuilder::new();
        if down {
            pb.move_to(left_x, cy - WIDE_H);
            pb.line_to(right_x, cy - NARROW_H);
            pb.line_to(right_x, cy + NARROW_H);
            pb.line_to(left_x, cy + WIDE_H);
        } else {
            pb.move_to(left_x, cy - NARROW_H);
            pb.line_to(right_x, cy - WIDE_H);
            pb.line_to(right_x, cy + WIDE_H);
            pb.line_to(left_x, cy + NARROW_H);
        }
        pb.close();
        if let Some(path) = pb.finish() {
            ctx.pixmap.fill_path(
                &path,
                cave_fill,
                FillRule::Winding,
                ctx.transform,
                None,
            );
        }
    }

    let (top_y0, top_y1, bot_y0, bot_y1, wide_start, narrow_end) = if down {
        (cy - WIDE_H, cy - NARROW_H, cy + WIDE_H, cy + NARROW_H, WIDE_H, NARROW_H)
    } else {
        (cy - NARROW_H, cy - WIDE_H, cy + NARROW_H, cy + WIDE_H, NARROW_H, WIDE_H)
    };

    stroke_line(left_x, top_y0, right_x, top_y1, ink, rail, ctx);
    stroke_line(left_x, bot_y0, right_x, bot_y1, ink, rail, ctx);

    let span = right_x - left_x;
    for i in 0..=N_STEPS {
        let t = i as f32 / N_STEPS as f32;
        let sx = left_x + span * t;
        let half = wide_start + (narrow_end - wide_start) * t;
        stroke_line(sx, cy - half, sx, cy + half, ink, step, ctx);
    }
}

fn stroke_line(
    x1: f32,
    y1: f32,
    x2: f32,
    y2: f32,
    paint: &Paint<'_>,
    stroke: &Stroke,
    ctx: &mut RasterCtx<'_>,
) {
    let mut pb = PathBuilder::new();
    pb.move_to(x1, y1);
    pb.line_to(x2, y2);
    if let Some(path) = pb.finish() {
        ctx.pixmap
            .stroke_path(&path, paint, stroke, ctx.transform, None);
    }
}
