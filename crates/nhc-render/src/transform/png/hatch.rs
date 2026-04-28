//! Hatch op rasterisation — Phase 5.3.1 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_hatch_from_ir`. Per kind:
//!
//! - **Corridor:** delegate to `primitives::hatch::draw_hatch_corridor`
//!   for the three SVG fragment buckets (tile fills, hatch lines,
//!   hatch stones), then rasterise each fragment into the pixmap.
//!   No clip envelope.
//! - **Room:** same delegate, plus a clip mask built from the
//!   outer rect + dungeon polygon under `FillRule::EvenOdd` so
//!   the hatch only paints in the void area outside the dungeon
//!   (matches the SVG `clip-rule="evenodd"` envelope).
//!
//! Bucket alphas mirror the SVG `<g opacity="...">` wrappers:
//! `tile_fills` 0.3, `hatch_lines` 0.5, `hatch_stones` 1.0.

use tiny_skia::{
    Color, FillRule, LineCap, LineJoin, Mask, Paint, PathBuilder,
    Rect, Stroke, Transform,
};

use crate::ir::{FloorIR, HatchKind, HatchOp, OpEntry};
use crate::primitives::hatch::{draw_hatch_corridor, draw_hatch_room};

use super::polygon_path::build_polygon_path;
use super::svg_attr::{extract_attr, extract_f32};
use super::RasterCtx;

const TILE_FILLS_OPACITY: f32 = 0.3;
const HATCH_LINES_OPACITY: f32 = 0.5;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_hatch_op() {
        Some(o) => o,
        None => return,
    };
    match op.kind() {
        HatchKind::Corridor => draw_corridor(&op, ctx),
        HatchKind::Room => draw_room(&op, fir, ctx),
        _ => {}
    }
}

fn draw_corridor(op: &HatchOp<'_>, ctx: &mut RasterCtx<'_>) {
    let tiles: Vec<(i32, i32)> = match op.tiles() {
        Some(t) => t.iter().map(|c| (c.x(), c.y())).collect(),
        None => return,
    };
    if tiles.is_empty() {
        return;
    }
    let (tile_fills, hatch_lines, hatch_stones) =
        draw_hatch_corridor(&tiles, op.seed());
    paint_buckets(
        &tile_fills,
        &hatch_lines,
        &hatch_stones,
        None,
        ctx,
    );
}

fn draw_room(
    op: &HatchOp<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let region_id = match op.region_out() {
        Some(r) => r,
        None => return,
    };
    let tiles: Vec<(i32, i32)> = match op.tiles() {
        Some(t) => t.iter().map(|c| (c.x(), c.y())).collect(),
        None => return,
    };
    if tiles.is_empty() {
        return;
    }
    let is_outer: Vec<bool> = op
        .is_outer()
        .map(|v| v.iter().collect())
        .unwrap_or_else(|| vec![false; tiles.len()]);
    let (tile_fills, hatch_lines, hatch_stones) =
        draw_hatch_room(&tiles, &is_outer, op.seed());
    if tile_fills.is_empty()
        && hatch_lines.is_empty()
        && hatch_stones.is_empty()
    {
        return;
    }
    let mask = build_room_clip_mask(fir, region_id, ctx);
    paint_buckets(
        &tile_fills,
        &hatch_lines,
        &hatch_stones,
        mask.as_ref(),
        ctx,
    );
}

fn paint_buckets(
    tile_fills: &[String],
    hatch_lines: &[String],
    hatch_stones: &[String],
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    for frag in tile_fills {
        paint_rect(frag, TILE_FILLS_OPACITY, mask, ctx);
    }
    for frag in hatch_lines {
        paint_line(frag, HATCH_LINES_OPACITY, mask, ctx);
    }
    for frag in hatch_stones {
        paint_ellipse(frag, mask, ctx);
    }
}

fn paint_rect(
    frag: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let x = extract_f32(frag, "x").unwrap_or(0.0);
    let y = extract_f32(frag, "y").unwrap_or(0.0);
    let w = extract_f32(frag, "width").unwrap_or(0.0);
    let h = extract_f32(frag, "height").unwrap_or(0.0);
    let fill = extract_attr(frag, "fill").unwrap_or("#000000");
    let rect = match Rect::from_xywh(x, y, w, h) {
        Some(r) => r,
        None => return,
    };
    let paint = paint_for_fill(fill, opacity);
    ctx.pixmap.fill_rect(rect, &paint, ctx.transform, mask);
}

fn paint_line(
    frag: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let x1 = extract_f32(frag, "x1").unwrap_or(0.0);
    let y1 = extract_f32(frag, "y1").unwrap_or(0.0);
    let x2 = extract_f32(frag, "x2").unwrap_or(0.0);
    let y2 = extract_f32(frag, "y2").unwrap_or(0.0);
    let stroke = extract_attr(frag, "stroke").unwrap_or("#000000");
    let sw = extract_f32(frag, "stroke-width").unwrap_or(1.0);
    let mut pb = PathBuilder::new();
    pb.move_to(x1, y1);
    pb.line_to(x2, y2);
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = paint_for_fill(stroke, opacity);
    let stroke_def = Stroke {
        width: sw,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
        ..Stroke::default()
    };
    ctx.pixmap
        .stroke_path(&path, &paint, &stroke_def, ctx.transform, mask);
}

fn paint_ellipse(
    frag: &str,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let cx = extract_f32(frag, "cx").unwrap_or(0.0);
    let cy = extract_f32(frag, "cy").unwrap_or(0.0);
    let rx = extract_f32(frag, "rx").unwrap_or(0.0);
    let ry = extract_f32(frag, "ry").unwrap_or(0.0);
    if rx <= 0.0 || ry <= 0.0 {
        return;
    }
    let fill = extract_attr(frag, "fill").unwrap_or("#000000");
    let stroke = extract_attr(frag, "stroke").unwrap_or("none");
    let sw = extract_f32(frag, "stroke-width").unwrap_or(1.0);
    let angle_deg = extract_attr(frag, "transform")
        .and_then(parse_rotate_angle)
        .unwrap_or(0.0);

    let path = ellipse_path(cx, cy, rx, ry);
    let local_xform = ctx
        .transform
        .pre_translate(cx, cy)
        .pre_rotate(angle_deg)
        .pre_translate(-cx, -cy);

    let fill_paint = paint_for_fill(fill, 1.0);
    ctx.pixmap.fill_path(
        &path,
        &fill_paint,
        FillRule::Winding,
        local_xform,
        mask,
    );
    if stroke != "none" {
        let stroke_paint = paint_for_fill(stroke, 1.0);
        let stroke_def = Stroke {
            width: sw,
            ..Stroke::default()
        };
        ctx.pixmap.stroke_path(
            &path,
            &stroke_paint,
            &stroke_def,
            local_xform,
            mask,
        );
    }
}

/// Build an axis-aligned ellipse path centred at (cx, cy) using
/// the standard cubic-Bézier 4-arc approximation (kappa = 0.5523).
/// Caller composes any rotation transform externally.
fn ellipse_path(cx: f32, cy: f32, rx: f32, ry: f32) -> tiny_skia::Path {
    const KAPPA: f32 = 0.552_284_8;
    let ox = rx * KAPPA;
    let oy = ry * KAPPA;
    let mut pb = PathBuilder::new();
    pb.move_to(cx + rx, cy);
    pb.cubic_to(cx + rx, cy + oy, cx + ox, cy + ry, cx, cy + ry);
    pb.cubic_to(cx - ox, cy + ry, cx - rx, cy + oy, cx - rx, cy);
    pb.cubic_to(cx - rx, cy - oy, cx - ox, cy - ry, cx, cy - ry);
    pb.cubic_to(cx + ox, cy - ry, cx + rx, cy - oy, cx + rx, cy);
    pb.close();
    pb.finish().expect("ellipse path is non-empty")
}

/// Pull the angle (degrees) out of `transform="rotate(a, x, y)"`.
fn parse_rotate_angle(s: &str) -> Option<f32> {
    let inner = s
        .trim()
        .strip_prefix("rotate(")?
        .strip_suffix(')')?;
    let first = inner.split(',').next()?.trim();
    first.parse().ok()
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

fn paint_for_fill(hex: &str, opacity: f32) -> Paint<'static> {
    let mut p = Paint::default();
    let (r, g, b) = parse_hex_rgb(hex).unwrap_or((0, 0, 0));
    let color = Color::from_rgba(
        r as f32 / 255.0,
        g as f32 / 255.0,
        b as f32 / 255.0,
        opacity.clamp(0.0, 1.0),
    )
    .unwrap_or(Color::TRANSPARENT);
    p.set_color(color);
    p.anti_alias = true;
    p
}

/// Outer-rect XOR dungeon polygon under EvenOdd → mask is white
/// in the void area outside the dungeon, black inside. Mirrors
/// the SVG `clipPath` from `_draw_hatch_room`.
fn build_room_clip_mask(
    fir: &FloorIR<'_>,
    region_id: &str,
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let polygon = region.polygon()?;

    let cell = fir.cell() as f32;
    let map_w = fir.width_tiles() as f32 * cell;
    let map_h = fir.height_tiles() as f32 * cell;
    let margin = cell * 2.0;

    let mut pb = PathBuilder::new();
    pb.move_to(-margin, -margin);
    pb.line_to(map_w + margin, -margin);
    pb.line_to(map_w + margin, map_h + margin);
    pb.line_to(-margin, map_h + margin);
    pb.close();
    if let Some(poly_path) = build_polygon_path(&polygon) {
        // Append the dungeon rings as additional subpaths so the
        // EvenOdd fill carves them out of the outer rect.
        pb.push_path(&poly_path);
    }
    let path = pb.finish()?;
    let mut mask = Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&path, FillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}

// Suppress dead-code on Transform — used implicitly via ctx.
#[allow(dead_code)]
const _UNUSED: Option<Transform> = None;

#[cfg(test)]
mod tests {
    use super::parse_rotate_angle;

    #[test]
    fn parse_rotate_angle_handles_legacy_format() {
        assert_eq!(
            parse_rotate_angle("rotate(45,12.5,7.0)"),
            Some(45.0)
        );
    }

    #[test]
    fn parse_rotate_angle_handles_decimal() {
        assert_eq!(
            parse_rotate_angle("rotate(132.5,0.0,0.0)"),
            Some(132.5)
        );
    }

    #[test]
    fn parse_rotate_angle_rejects_garbage() {
        assert!(parse_rotate_angle("scale(2)").is_none());
        assert!(parse_rotate_angle("not a transform").is_none());
    }
}
