//! Walls + floors op rasterisation — Phase 5.2.2 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_walls_and_floors_from_ir` for the structured
//! op fields:
//!
//! - `corridor_tiles` → `FLOOR_COLOR` rects at tile coords.
//! - `rect_rooms` → `FLOOR_COLOR` rects covering each room's
//!   pixel bbox.
//! - `wall_segments` → black 5px-wide stroke around corridor
//!   tile edges. Each entry is a pre-rendered `M{x},{y}
//!   L{x},{y}` 2-point line; we parse them back into
//!   `tiny-skia::Path` move/line ops rather than carrying an
//!   SVG-path parser around.
//!
//! The pre-rendered SVG passthroughs (`smooth_fill_svg` /
//! `smooth_wall_svg` / `cave_region` / `wall_extensions_d`)
//! stay deferred to Phase 5.5; in this commit they paint
//! nothing and the per-fixture parity gate stays XFAIL for any
//! descriptor whose layer carries them.

use tiny_skia::{
    Color, FillRule, LineCap, LineJoin, Paint, PathBuilder, Rect,
    Stroke,
};

use crate::ir::{FloorIR, OpEntry, WallsAndFloorsOp};

use super::RasterCtx;

const CELL: f32 = 32.0;
const FLOOR_R: u8 = 0xFF;
const FLOOR_G: u8 = 0xFF;
const FLOOR_B: u8 = 0xFF;
const INK_R: u8 = 0x00;
const INK_G: u8 = 0x00;
const INK_B: u8 = 0x00;
const WALL_WIDTH: f32 = 5.0;

fn floor_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(FLOOR_R, FLOOR_G, FLOOR_B, 0xFF));
    p.anti_alias = true;
    p
}

fn wall_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(INK_R, INK_G, INK_B, 0xFF));
    p.anti_alias = true;
    p
}

fn wall_stroke() -> Stroke {
    Stroke {
        width: WALL_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
        ..Stroke::default()
    }
}

pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_walls_and_floors_op() {
        Some(o) => o,
        None => return,
    };
    draw_corridor_tiles(&op, ctx);
    draw_rect_rooms(&op, ctx);
    draw_wall_segments(&op, ctx);
}

fn draw_corridor_tiles(op: &WallsAndFloorsOp<'_>, ctx: &mut RasterCtx<'_>) {
    let tiles = match op.corridor_tiles() {
        Some(t) => t,
        None => return,
    };
    let paint = floor_paint();
    for tile in tiles.iter() {
        let px = tile.x() as f32 * CELL;
        let py = tile.y() as f32 * CELL;
        if let Some(rect) = Rect::from_xywh(px, py, CELL, CELL) {
            ctx.pixmap.fill_rect(rect, &paint, ctx.transform, None);
        }
    }
}

fn draw_rect_rooms(op: &WallsAndFloorsOp<'_>, ctx: &mut RasterCtx<'_>) {
    let rooms = match op.rect_rooms() {
        Some(r) => r,
        None => return,
    };
    let paint = floor_paint();
    for room in rooms.iter() {
        let px = room.x() as f32 * CELL;
        let py = room.y() as f32 * CELL;
        let pw = room.w() as f32 * CELL;
        let ph = room.h() as f32 * CELL;
        if let Some(rect) = Rect::from_xywh(px, py, pw, ph) {
            ctx.pixmap.fill_rect(rect, &paint, ctx.transform, None);
        }
    }
}

fn draw_wall_segments(op: &WallsAndFloorsOp<'_>, ctx: &mut RasterCtx<'_>) {
    let segments = match op.wall_segments() {
        Some(s) => s,
        None => return,
    };
    if segments.is_empty() {
        return;
    }
    let mut pb = PathBuilder::new();
    let mut any = false;
    for seg in segments.iter() {
        if let Some(((x1, y1), (x2, y2))) = parse_segment(seg) {
            pb.move_to(x1, y1);
            pb.line_to(x2, y2);
            any = true;
        }
    }
    if !any {
        return;
    }
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = wall_paint();
    let stroke = wall_stroke();
    ctx.pixmap
        .stroke_path(&path, &paint, &stroke, ctx.transform, None);
}

/// Parse `"M{x1},{y1} L{x2},{y2}"`. The legacy emitter writes
/// these one segment at a time; we replay them into tiny-skia
/// move/line ops so the raster shape matches the SVG byte-for-
/// byte stroke trail.
fn parse_segment(s: &str) -> Option<((f32, f32), (f32, f32))> {
    let s = s.trim();
    let s = s.strip_prefix('M')?;
    let mid = s.find(" L")?;
    let p1 = parse_xy(s[..mid].trim())?;
    let p2 = parse_xy(s[mid + 2..].trim())?;
    Some((p1, p2))
}

fn parse_xy(s: &str) -> Option<(f32, f32)> {
    let comma = s.find(',')?;
    let x: f32 = s[..comma].trim().parse().ok()?;
    let y: f32 = s[comma + 1..].trim().parse().ok()?;
    Some((x, y))
}

// Suppress dead-code on the imports that future sub-phases
// (5.5) will use when smooth/cave/extensions land.
#[allow(dead_code)]
const _UNUSED_FILL_RULE: FillRule = FillRule::Winding;

#[cfg(test)]
mod tests {
    use super::{parse_segment, parse_xy};

    #[test]
    fn parse_xy_handles_integer_coords() {
        assert_eq!(parse_xy("32,64"), Some((32.0, 64.0)));
    }

    #[test]
    fn parse_xy_handles_decimal_coords() {
        assert_eq!(parse_xy("12.5,7.25"), Some((12.5, 7.25)));
    }

    #[test]
    fn parse_segment_handles_legacy_format() {
        let got = parse_segment("M0,0 L32,0").unwrap();
        assert_eq!(got, ((0.0, 0.0), (32.0, 0.0)));
    }

    #[test]
    fn parse_segment_handles_whitespace() {
        let got = parse_segment("  M 32,64 L 64,64  ");
        assert_eq!(got, Some(((32.0, 64.0), (64.0, 64.0))));
    }

    #[test]
    fn parse_segment_rejects_garbage() {
        assert!(parse_segment("not a path").is_none());
        assert!(parse_segment("M0,0").is_none());
    }
}
