//! Walls + floors op rasterisation — Phase 5.2.2 + 5.5 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_walls_and_floors_from_ir`:
//!
//! - `corridor_tiles` → `FLOOR_COLOR` rects at tile coords.
//! - `rect_rooms` → `FLOOR_COLOR` rects covering each room's
//!   pixel bbox.
//! - `wall_segments` → black 5px-wide stroke around corridor
//!   tile edges. Each entry is a pre-rendered `M{x},{y}
//!   L{x},{y}` 2-point line.
//! - `smooth_fill_svg` → pre-rendered `<polygon>` / `<path>`
//!   fragments for non-rect rooms (octagon / smooth-rect with
//!   gaps / …). Each carries `fill="#FFFFFF" stroke="none"`;
//!   the fragment helper rasterises them as filled shapes.
//! - `smooth_wall_svg` → same shape, but `fill="none"` +
//!   `stroke="#000000" stroke-width="5.0" stroke-linecap=round
//!   stroke-linejoin=round`. The fragment helper handles the
//!   stroke pass.
//! - `cave_region` → a single `<path d="..."/>` element wrapping
//!   the smoothed cave-wall outline (M / C / Z subpaths). The
//!   legacy emitter wraps it twice — once filled with the cave
//!   floor colour under `evenodd`, once stroked black with the
//!   wall width. We replay both passes here.
//! - `wall_extensions_d` → a bare `d=` string with M / L
//!   commands. Wrapped in the same black 5px stroke style as
//!   `smooth_wall_svg`.

use tiny_skia::{
    Color, FillRule, LineCap, LineJoin, Paint, PathBuilder, Rect,
    Stroke,
};

use crate::ir::{FloorIR, OpEntry, WallsAndFloorsOp};

use super::exterior_wall_op::has_dungeon_ink_wall_ops;
use super::floor_op::{has_cave_floor_op, has_floor_ops};
use super::fragment::paint_fragment;
use super::path_parser::{parse_path_d, parse_xy};
use super::RasterCtx;

const CELL: f32 = 32.0;
const FLOOR_R: u8 = 0xFF;
const FLOOR_G: u8 = 0xFF;
const FLOOR_B: u8 = 0xFF;
const INK_R: u8 = 0x00;
const INK_G: u8 = 0x00;
const INK_B: u8 = 0x00;
const WALL_WIDTH: f32 = 5.0;
// Cave floor colour — matches `CAVE_FLOOR_COLOR` in
// `nhc/rendering/_svg_helpers.py` (#F5EBD8).
const CAVE_FLOOR_R: u8 = 0xF5;
const CAVE_FLOOR_G: u8 = 0xEB;
const CAVE_FLOOR_B: u8 = 0xD8;

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
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_walls_and_floors_op() {
        Some(o) => o,
        None => return,
    };
    // Phase 1.17: when FloorOps are present in the IR, the new
    // `floor_op::draw` handler owns the floor surface for rect rooms,
    // corridors, and smooth polygon fills. Gate those legacy passes off
    // so floor pixels are not painted twice.
    //
    // The cave region is gated separately because a CaveFloor FloorOp
    // may be absent even when non-cave FloorOps are present (e.g. a
    // floor with rect rooms only). The gate is conservative: if ANY
    // CaveFloor FloorOp exists, skip `draw_cave_region`.
    //
    // Wall primitives (draw_wall_segments, draw_smooth_wall_fragments,
    // draw_wall_extensions) keep running regardless — wall ops are not
    // yet consumed (Phase 1.18).
    //
    // Building wood-floor (`smooth_fill_svg` brown rects) caveat: in IR
    // op-order it paints here BEFORE the white DungeonFloor FloorOps
    // dispatched at the next op slot, so the brown gets covered. Python
    // sidesteps this by intercepting the WallsAndFloorsOp dispatch and
    // emitting FloorOps inline so the legacy fields paint last (per
    // `_draw_walls_and_floors_from_ir`). Rust would need an analogous
    // re-order to match. Phase 1.20 retires `smoothFillSvg` entirely
    // (replaces with a building FloorOp), so leaving this as-is until
    // 1.20 lands. Building parity drift is xfailed in the meantime.
    let floor_ops_present = has_floor_ops(fir);
    let cave_floor_present = floor_ops_present && has_cave_floor_op(fir);
    // Phase 1.18: gate legacy wall passes when wall ops are consumed.
    // `has_dungeon_ink_wall_ops` requires both a CorridorWallOp and a
    // DungeonInk ExteriorWallOp — the same condition Python uses to
    // suppress `wall_segments` / `smooth_walls` / `wall_extensions_d`.
    let dungeon_ink_wall_ops = has_dungeon_ink_wall_ops(fir);

    if !floor_ops_present {
        // Legacy emit order for 3.x cached buffers without FloorOps.
        draw_corridor_tiles(&op, ctx);
        draw_rect_rooms(&op, ctx);
        draw_smooth_fragments(&op, ctx);
    }
    // `draw_cave_region` runs both fill and stroke passes. Suppress it when
    // a CaveFloor FloorOp is present (Phase 1.17+): the new handlers cover
    // both the fill (floor_op.rs) and the stroke (exterior_wall_op.rs).
    if !cave_floor_present {
        draw_cave_region(&op, ctx);
    }
    if !dungeon_ink_wall_ops {
        draw_smooth_wall_fragments(&op, ctx);
        draw_wall_extensions(&op, ctx);
        draw_wall_segments(&op, ctx);
    }
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

fn draw_smooth_fragments(
    op: &WallsAndFloorsOp<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let frags = match op.smooth_fill_svg() {
        Some(v) => v,
        None => return,
    };
    for frag in frags.iter() {
        paint_fragment(frag, 1.0, None, ctx);
    }
}

fn draw_smooth_wall_fragments(
    op: &WallsAndFloorsOp<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let frags = match op.smooth_wall_svg() {
        Some(v) => v,
        None => return,
    };
    for frag in frags.iter() {
        paint_fragment(frag, 1.0, None, ctx);
    }
}

fn draw_cave_region(
    op: &WallsAndFloorsOp<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let region = match op.cave_region() {
        Some(s) if !s.is_empty() => s,
        _ => return,
    };
    let d = match extract_d_from_path(region) {
        Some(d) => d,
        None => return,
    };
    let path = match parse_path_d(d) {
        Some(p) => p,
        None => return,
    };
    // Pass 1 — cave-floor fill under EvenOdd (holes carve through).
    let mut fill = Paint::default();
    fill.set_color(Color::from_rgba8(
        CAVE_FLOOR_R,
        CAVE_FLOOR_G,
        CAVE_FLOOR_B,
        0xFF,
    ));
    fill.anti_alias = true;
    ctx.pixmap.fill_path(
        &path,
        &fill,
        FillRule::EvenOdd,
        ctx.transform,
        None,
    );
    // Pass 2 — black 5px stroke for the wall outline.
    ctx.pixmap.stroke_path(
        &path,
        &wall_paint(),
        &wall_stroke(),
        ctx.transform,
        None,
    );
}

fn draw_wall_extensions(
    op: &WallsAndFloorsOp<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let d = match op.wall_extensions_d() {
        Some(s) if !s.is_empty() => s,
        _ => return,
    };
    let path = match parse_path_d(d) {
        Some(p) => p,
        None => return,
    };
    ctx.pixmap.stroke_path(
        &path,
        &wall_paint(),
        &wall_stroke(),
        ctx.transform,
        None,
    );
}

/// `<path d="..."/>` → the inner d= string. The legacy
/// `cave_region` rides as a single self-closing `<path>` with
/// no other attributes; the helper finds the first `d="..."`
/// pair and returns the contents.
fn extract_d_from_path(s: &str) -> Option<&str> {
    let needle = "d=\"";
    let start = s.find(needle)? + needle.len();
    let rest = &s[start..];
    let end = rest.find('"')?;
    Some(&rest[..end])
}

/// Parse `"M{x1},{y1} L{x2},{y2}"`. The legacy emitter writes
/// these one segment at a time; we replay them into tiny-skia
/// move/line ops so the raster shape matches the SVG byte-for-
/// byte stroke trail.
fn parse_segment(s: &str) -> Option<((f32, f32), (f32, f32))> {
    let s = s.trim().strip_prefix('M')?;
    let mid = s.find(" L")?;
    let p1 = parse_xy(s[..mid].trim())?;
    let p2 = parse_xy(s[mid + 2..].trim())?;
    Some((p1, p2))
}

#[cfg(test)]
mod tests {
    use super::{extract_d_from_path, parse_segment};

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

    #[test]
    fn extract_d_pulls_attribute() {
        let s = "<path d=\"M0,0 L10,10 Z\"/>";
        assert_eq!(extract_d_from_path(s), Some("M0,0 L10,10 Z"));
    }

    #[test]
    fn extract_d_handles_curve_commands() {
        let s = "<path d=\"M0,0 C5,0 10,5 10,10 Z\"/>";
        assert_eq!(extract_d_from_path(s), Some("M0,0 C5,0 10,5 10,10 Z"));
    }
}
