//! Generic SVG fragment rasteriser — covers the
//! `<g opacity="X">…</g>` envelopes the legacy primitives emit
//! plus their inner `<rect>` / `<line>` / `<ellipse>` /
//! `<polygon>` / `<path>` children. Used by `floor_detail`,
//! `thematic_detail`, the seven decorator handlers, and the
//! surface-feature handlers in 5.4.
//!
//! Intentionally narrow — supports only the shape every Phase 4
//! primitive uses (single self-closing inner elements, no nesting
//! beyond `<g>`). Curve commands inside `<path>` are limited to
//! the M / L vocabulary `path_parser` covers; if a future
//! primitive needs cubic Bézier d= strings, extend
//! `path_parser` first.

use tiny_skia::{
    Color, FillRule, LineCap, LineJoin, Mask, Paint, PathBuilder,
    Rect, Stroke,
};

use super::path_parser::parse_path_d;
use super::svg_attr::{extract_attr, extract_f32};
use super::RasterCtx;

/// Rasterise one fragment string. The fragment is either:
///
/// - a `<g [class="…"] opacity="X">…</g>` wrapper, in which case
///   the group's opacity multiplies into `base_opacity` and the
///   inner element list iterates; or
/// - a single self-closing element (`<rect/>`, `<line/>`, …),
///   handled directly.
pub fn paint_fragment(
    frag: &str,
    base_opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let frag = frag.trim();
    if let Some((inner, group_opacity)) = strip_g_wrapper(frag) {
        let total = base_opacity * group_opacity;
        for elem in elements(inner) {
            paint_element(elem, total, mask, ctx);
        }
    } else {
        paint_element(frag, base_opacity, mask, ctx);
    }
}

/// Convenience: walk a list of fragments.
pub fn paint_fragments(
    fragments: &[String],
    base_opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    for frag in fragments {
        paint_fragment(frag, base_opacity, mask, ctx);
    }
}

/// `<g opacity="X">inner</g>` → `(inner, X)`. Returns `None`
/// when the wrapper isn't present; non-`<g>` openings are
/// left to the per-element dispatch.
fn strip_g_wrapper(s: &str) -> Option<(&str, f32)> {
    if !s.starts_with("<g") {
        return None;
    }
    let header_end = s.find('>')? + 1;
    let inner_end = s.rfind("</g>")?;
    if inner_end < header_end {
        return None;
    }
    let header = &s[..header_end];
    let inner = &s[header_end..inner_end];
    let opacity = extract_f32(header, "opacity").unwrap_or(1.0);
    Some((inner, opacity))
}

/// Iterate self-closing elements inside `s` — split on `/>`.
fn elements(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0usize;
    for (i, _) in s.match_indices("/>") {
        let candidate = s[start..i + 2].trim();
        if !candidate.is_empty() && candidate.starts_with('<') {
            out.push(candidate);
        }
        start = i + 2;
    }
    out
}

fn paint_element(
    elem: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    if elem.starts_with("<rect") {
        paint_rect(elem, opacity, mask, ctx);
    } else if elem.starts_with("<line") {
        paint_line(elem, opacity, mask, ctx);
    } else if elem.starts_with("<ellipse") {
        paint_ellipse(elem, opacity, mask, ctx);
    } else if elem.starts_with("<polygon") {
        paint_polygon(elem, opacity, mask, ctx);
    } else if elem.starts_with("<path") {
        paint_path(elem, opacity, mask, ctx);
    }
}

fn paint_rect(
    elem: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let x = extract_f32(elem, "x").unwrap_or(0.0);
    let y = extract_f32(elem, "y").unwrap_or(0.0);
    let w = extract_f32(elem, "width").unwrap_or(0.0);
    let h = extract_f32(elem, "height").unwrap_or(0.0);
    let rect = match Rect::from_xywh(x, y, w, h) {
        Some(r) => r,
        None => return,
    };
    if let Some(fill) = extract_attr(elem, "fill") {
        if fill != "none" {
            let paint = paint_for(fill, opacity);
            ctx.pixmap.fill_rect(rect, &paint, ctx.transform, mask);
        }
    }
    paint_rect_stroke(elem, rect, opacity, mask, ctx);
}

fn paint_rect_stroke(
    elem: &str,
    rect: Rect,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let stroke = match extract_attr(elem, "stroke") {
        Some(s) if s != "none" => s,
        _ => return,
    };
    let sw = extract_f32(elem, "stroke-width").unwrap_or(1.0);
    let mut pb = PathBuilder::new();
    pb.push_rect(rect);
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = paint_for(stroke, opacity);
    let stroke_def = stroke_for(elem, sw);
    ctx.pixmap
        .stroke_path(&path, &paint, &stroke_def, ctx.transform, mask);
}

fn paint_line(
    elem: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let x1 = extract_f32(elem, "x1").unwrap_or(0.0);
    let y1 = extract_f32(elem, "y1").unwrap_or(0.0);
    let x2 = extract_f32(elem, "x2").unwrap_or(0.0);
    let y2 = extract_f32(elem, "y2").unwrap_or(0.0);
    let stroke = extract_attr(elem, "stroke").unwrap_or("#000000");
    let sw = extract_f32(elem, "stroke-width").unwrap_or(1.0);
    let mut pb = PathBuilder::new();
    pb.move_to(x1, y1);
    pb.line_to(x2, y2);
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = paint_for(stroke, opacity);
    let stroke_def = stroke_for(elem, sw);
    ctx.pixmap
        .stroke_path(&path, &paint, &stroke_def, ctx.transform, mask);
}

fn paint_ellipse(
    elem: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let cx = extract_f32(elem, "cx").unwrap_or(0.0);
    let cy = extract_f32(elem, "cy").unwrap_or(0.0);
    let rx = extract_f32(elem, "rx").unwrap_or(0.0);
    let ry = extract_f32(elem, "ry").unwrap_or(0.0);
    if rx <= 0.0 || ry <= 0.0 {
        return;
    }
    let path = ellipse_path(cx, cy, rx, ry);
    let xform = ctx
        .transform
        .pre_translate(cx, cy)
        .pre_rotate(rotate_angle(elem))
        .pre_translate(-cx, -cy);

    if let Some(fill) = extract_attr(elem, "fill") {
        if fill != "none" {
            let fill_paint = paint_for(fill, opacity);
            ctx.pixmap.fill_path(
                &path,
                &fill_paint,
                FillRule::Winding,
                xform,
                mask,
            );
        }
    }
    if let Some(stroke) = extract_attr(elem, "stroke") {
        if stroke != "none" {
            let sw = extract_f32(elem, "stroke-width").unwrap_or(1.0);
            let stroke_paint = paint_for(stroke, opacity);
            let stroke_def = stroke_for(elem, sw);
            ctx.pixmap.stroke_path(
                &path,
                &stroke_paint,
                &stroke_def,
                xform,
                mask,
            );
        }
    }
}

fn paint_polygon(
    elem: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let points = match extract_attr(elem, "points") {
        Some(p) => p,
        None => return,
    };
    let mut pb = PathBuilder::new();
    let mut started = false;
    for tok in points.split_whitespace() {
        if let Some((x, y)) = parse_xy(tok) {
            if started {
                pb.line_to(x, y);
            } else {
                pb.move_to(x, y);
                started = true;
            }
        }
    }
    if !started {
        return;
    }
    pb.close();
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    if let Some(fill) = extract_attr(elem, "fill") {
        if fill != "none" {
            let fill_paint = paint_for(fill, opacity);
            ctx.pixmap.fill_path(
                &path,
                &fill_paint,
                FillRule::Winding,
                ctx.transform,
                mask,
            );
        }
    }
    if let Some(stroke) = extract_attr(elem, "stroke") {
        if stroke != "none" {
            let sw = extract_f32(elem, "stroke-width").unwrap_or(1.0);
            let stroke_paint = paint_for(stroke, opacity);
            let stroke_def = stroke_for(elem, sw);
            ctx.pixmap.stroke_path(
                &path,
                &stroke_paint,
                &stroke_def,
                ctx.transform,
                mask,
            );
        }
    }
}

fn paint_path(
    elem: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let d = match extract_attr(elem, "d") {
        Some(d) => d,
        None => return,
    };
    let path = match parse_path_d(d) {
        Some(p) => p,
        None => return,
    };
    if let Some(fill) = extract_attr(elem, "fill") {
        if fill != "none" {
            let fill_paint = paint_for(fill, opacity);
            ctx.pixmap.fill_path(
                &path,
                &fill_paint,
                FillRule::Winding,
                ctx.transform,
                mask,
            );
        }
    }
    if let Some(stroke) = extract_attr(elem, "stroke") {
        if stroke != "none" {
            let sw = extract_f32(elem, "stroke-width").unwrap_or(1.0);
            let stroke_paint = paint_for(stroke, opacity);
            let stroke_def = stroke_for(elem, sw);
            ctx.pixmap.stroke_path(
                &path,
                &stroke_paint,
                &stroke_def,
                ctx.transform,
                mask,
            );
        }
    }
}

fn parse_xy(s: &str) -> Option<(f32, f32)> {
    let comma = s.find(',')?;
    let x: f32 = s[..comma].parse().ok()?;
    let y: f32 = s[comma + 1..].parse().ok()?;
    Some((x, y))
}

fn rotate_angle(elem: &str) -> f32 {
    extract_attr(elem, "transform")
        .and_then(|s| {
            s.trim()
                .strip_prefix("rotate(")?
                .strip_suffix(')')?
                .split(',')
                .next()
                .and_then(|s| s.trim().parse::<f32>().ok())
        })
        .unwrap_or(0.0)
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

fn paint_for(hex: &str, opacity: f32) -> Paint<'static> {
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

fn stroke_for(elem: &str, width: f32) -> Stroke {
    let cap = match extract_attr(elem, "stroke-linecap") {
        Some("round") => LineCap::Round,
        Some("square") => LineCap::Square,
        _ => LineCap::Butt,
    };
    let join = match extract_attr(elem, "stroke-linejoin") {
        Some("round") => LineJoin::Round,
        Some("bevel") => LineJoin::Bevel,
        _ => LineJoin::Miter,
    };
    Stroke {
        width,
        line_cap: cap,
        line_join: join,
        ..Stroke::default()
    }
}

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

#[cfg(test)]
mod tests {
    use super::{elements, strip_g_wrapper};

    #[test]
    fn strip_g_wrapper_extracts_opacity() {
        let s = "<g opacity=\"0.3\"><rect/></g>";
        let (inner, op) = strip_g_wrapper(s).unwrap();
        assert_eq!(inner, "<rect/>");
        assert!((op - 0.3).abs() < 1e-6);
    }

    #[test]
    fn strip_g_wrapper_handles_class_attr() {
        let s = "<g class=\"y-scratch\" opacity=\"0.45\"><path/></g>";
        let (inner, op) = strip_g_wrapper(s).unwrap();
        assert_eq!(inner, "<path/>");
        assert!((op - 0.45).abs() < 1e-6);
    }

    #[test]
    fn strip_g_wrapper_returns_none_for_non_g() {
        assert!(strip_g_wrapper("<rect/>").is_none());
    }

    #[test]
    fn elements_walks_self_closing_children() {
        let inner = "<rect x=\"0\"/><line x1=\"0\"/><ellipse cx=\"0\"/>";
        let got = elements(inner);
        assert_eq!(got.len(), 3);
        assert!(got[0].starts_with("<rect"));
        assert!(got[1].starts_with("<line"));
        assert!(got[2].starts_with("<ellipse"));
    }
}
