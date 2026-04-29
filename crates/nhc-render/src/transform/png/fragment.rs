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
    BlendMode, Color, FillRule, FilterQuality, LineCap, LineJoin, Mask,
    Paint, PathBuilder, PixmapPaint, Rect, Stroke, Transform,
};

use super::path_parser::parse_path_d;
use super::svg_attr::{extract_attr, extract_f32};
use super::RasterCtx;

/// `1.0 - GROUP_OPAQUE_THRESHOLD` is the cutoff below which the
/// offscreen-buffer pass kicks in. Group wrappers with opacity
/// at or above this value composite identically to the direct
/// per-element render, so we skip the alloc + blit overhead.
const GROUP_OPAQUE_THRESHOLD: f32 = 1.0e-6;

/// SVG attributes that follow the inheritance rules from
/// [SVG 1.1 §6.2](https://www.w3.org/TR/SVG11/styling.html). The
/// fragment helper applies these to children when the parent
/// `<g>` open tag declares them and the child does not — needed
/// for the terrain-detail walk_and_paint passthrough, whose
/// open-tag attributes set the stroke colour for hundreds of
/// per-tile `<path>` children that themselves carry only
/// `fill="none" stroke-width="…"`.
const INHERITABLE_ATTRS: &[&str] = &[
    "stroke",
    "fill",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
];

/// Rasterise one fragment string. The fragment is either:
///
/// - a `<g [class="…"] opacity="X">…</g>` wrapper, in which
///   case the group's children render into the `RasterCtx`'s
///   scratch pixmap at full alpha, then the scratch blits onto
///   the main pixmap with `PixmapPaint::opacity = X *
///   base_opacity`. Phase 5.10 made this the default — earlier
///   commits multiplied opacity into per-element alpha, which
///   over-darkened overlapping children vs the SVG spec; the
///   offscreen pass matches the SVG group-opacity composition
///   exactly. Fully-opaque (`X >= 1.0`) groups skip the alloc
///   + blit and render direct.
/// - a single self-closing element (`<rect/>`, `<line/>`, …),
///   handled directly.
///
/// In both branches inheritable attributes (`stroke`, `fill`,
/// stroke caps / joins / width) declared on the parent `<g>`
/// open tag flow into children that don't override them.
pub fn paint_fragment(
    frag: &str,
    base_opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let frag = frag.trim();
    let Some((inner, group_opacity, header)) = strip_g_wrapper(frag)
    else {
        paint_element(frag, base_opacity, mask, ctx);
        return;
    };
    if group_opacity >= 1.0 - GROUP_OPAQUE_THRESHOLD {
        // Fully opaque group — direct render is equivalent.
        for elem in elements(inner) {
            let inherited = inherit_attrs(elem, header);
            paint_element(&inherited, base_opacity, mask, ctx);
        }
        return;
    }
    paint_offscreen_group(inner, header, base_opacity, group_opacity, mask, ctx);
}

/// Offscreen-buffer group composition.
///
/// 1. Clear the scratch pixmap.
/// 2. Swap pixmap ↔ scratch so per-element fills land in the
///    scratch — children at full alpha.
/// 3. Render every inner element with no clip mask (clip applies
///    to the group's RESULT, not to children).
/// 4. Swap back.
/// 5. Blit scratch onto pixmap with the composed opacity and
///    the inherited clip mask.
///
/// Inheritable attributes from the parent open tag flow into
/// children that don't override them — same shape as the
/// fully-opaque branch above.
///
/// Nested `<g opacity>` wrappers are NOT supported — the legacy
/// emitters never nest groups, so the simple non-stacked design
/// covers every Phase 5 primitive.
fn paint_offscreen_group(
    inner: &str,
    header: &str,
    base_opacity: f32,
    group_opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    ctx.scratch.fill(Color::TRANSPARENT);
    std::mem::swap(ctx.pixmap, ctx.scratch);
    for elem in elements(inner) {
        let inherited = inherit_attrs(elem, header);
        paint_element(&inherited, 1.0, None, ctx);
    }
    std::mem::swap(ctx.pixmap, ctx.scratch);

    let pp = PixmapPaint {
        opacity: (base_opacity * group_opacity).clamp(0.0, 1.0),
        blend_mode: BlendMode::SourceOver,
        quality: FilterQuality::Nearest,
    };
    ctx.pixmap
        .draw_pixmap(0, 0, ctx.scratch.as_ref(), &pp, Transform::identity(), mask);
}

/// Walk a list of fragments. Some emit paths (the terrain-detail
/// walk_and_paint passthrough is the load-bearing case) ship
/// `<g>` open tags, child elements, and `</g>` close tags as
/// separate vector entries rather than a single self-contained
/// string — we accumulate them into a synthetic group string
/// before dispatching to `paint_fragment` so the same
/// inheritance + offscreen-buffer paths apply.
pub fn paint_fragments(
    fragments: &[String],
    base_opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let mut buffered: Option<String> = None;
    for frag in fragments {
        let trimmed = frag.trim();
        if let Some(buf) = buffered.as_mut() {
            buf.push_str(frag);
            if trimmed == "</g>" {
                let group = buffered.take().unwrap();
                paint_fragment(&group, base_opacity, mask, ctx);
            }
            continue;
        }
        if trimmed.starts_with("<g") && !trimmed.contains("</g>") {
            buffered = Some(frag.clone());
            continue;
        }
        paint_fragment(frag, base_opacity, mask, ctx);
    }
    // Unmatched open-g (shouldn't happen in valid IR, but guard
    // against a truncated emit). Pass through as-is so the
    // single-element dispatch still tries to render whatever
    // self-closing children the buffer collected.
    if let Some(buf) = buffered.take() {
        paint_fragment(&buf, base_opacity, mask, ctx);
    }
}

/// Inject parent-tag attributes into a child element string when
/// the child doesn't declare them. Returns the child unchanged
/// when no inheritance applies (the common case for self-
/// contained `<g>` envelopes from the structured primitives).
fn inherit_attrs(child: &str, parent_header: &str) -> String {
    let close_pos = match child.rfind("/>") {
        Some(p) => p,
        None => return child.to_string(),
    };
    let mut additions = String::new();
    for attr in INHERITABLE_ATTRS {
        if extract_attr(child, attr).is_some() {
            continue;
        }
        if let Some(value) = extract_attr(parent_header, attr) {
            additions.push_str(&format!(" {attr}=\"{value}\""));
        }
    }
    if additions.is_empty() {
        return child.to_string();
    }
    let mut result = String::with_capacity(child.len() + additions.len());
    result.push_str(&child[..close_pos]);
    result.push_str(&additions);
    result.push_str(&child[close_pos..]);
    result
}

/// `<g attrs>inner</g>` → `(inner, opacity, open_tag)`. Returns
/// `None` when the wrapper isn't self-contained; non-`<g>`
/// openings are left to the per-element dispatch.
fn strip_g_wrapper(s: &str) -> Option<(&str, f32, &str)> {
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
    Some((inner, opacity, header))
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
    } else if elem.starts_with("<circle") {
        paint_circle(elem, opacity, mask, ctx);
    } else if elem.starts_with("<polygon") {
        paint_polygon(elem, opacity, mask, ctx);
    } else if elem.starts_with("<path") {
        paint_path(elem, opacity, mask, ctx);
    }
}

fn paint_circle(
    elem: &str,
    opacity: f32,
    mask: Option<&Mask>,
    ctx: &mut RasterCtx<'_>,
) {
    let cx = extract_f32(elem, "cx").unwrap_or(0.0);
    let cy = extract_f32(elem, "cy").unwrap_or(0.0);
    let r = extract_f32(elem, "r").unwrap_or(0.0);
    if r <= 0.0 {
        return;
    }
    let path = ellipse_path(cx, cy, r, r);
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
    use super::{elements, paint_fragment, strip_g_wrapper, RasterCtx};
    use tiny_skia::{Pixmap, Transform};

    #[test]
    fn strip_g_wrapper_extracts_opacity() {
        let s = "<g opacity=\"0.3\"><rect/></g>";
        let (inner, op, header) = strip_g_wrapper(s).unwrap();
        assert_eq!(inner, "<rect/>");
        assert!((op - 0.3).abs() < 1e-6);
        assert_eq!(header, "<g opacity=\"0.3\">");
    }

    #[test]
    fn strip_g_wrapper_handles_class_attr() {
        let s = "<g class=\"y-scratch\" opacity=\"0.45\"><path/></g>";
        let (inner, op, header) = strip_g_wrapper(s).unwrap();
        assert_eq!(inner, "<path/>");
        assert!((op - 0.45).abs() < 1e-6);
        assert!(header.contains("class=\"y-scratch\""));
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

    /// Two overlapping black rects in a `<g opacity="0.5">`
    /// wrapper. Per-element-alpha (the pre-5.10 behaviour) would
    /// over-darken the overlap — that pixel would composite as
    /// `bg * 0.25 + black * 0.75` (each rect lands at 0.5 alpha
    /// against the running buffer). Offscreen-buffer composition
    /// (the 5.10 contract) lands each rect into the scratch at
    /// full alpha (so they overlap with no extra blending), then
    /// the scratch blits at 0.5 alpha — every pixel of the group
    /// sees `bg * 0.5 + black * 0.5`.
    #[test]
    fn group_opacity_does_not_over_darken_overlap() {
        let mut pixmap = Pixmap::new(20, 20).unwrap();
        let mut scratch = Pixmap::new(20, 20).unwrap();
        // Fill the main pixmap with white (the BG analogue).
        pixmap.fill(tiny_skia::Color::WHITE);
        let mut ctx = RasterCtx {
            pixmap: &mut pixmap,
            scratch: &mut scratch,
            transform: Transform::identity(),
            scale: 1.0,
        };
        // Two overlapping black rects under a 0.5-opacity wrapper.
        let frag = "<g opacity=\"0.5\">\
            <rect x=\"0\" y=\"0\" width=\"10\" height=\"10\" \
             fill=\"#000000\"/>\
            <rect x=\"5\" y=\"5\" width=\"10\" height=\"10\" \
             fill=\"#000000\"/>\
            </g>";
        paint_fragment(frag, 1.0, None, &mut ctx);

        // (7, 7) sits inside both rects (overlap region).
        let pixel = ctx.pixmap.pixel(7, 7).unwrap();
        // Expected:  white * 0.5 + black * 0.5 = (127.5, ...).
        // Tolerate +/- 2 levels of antialiasing rounding noise.
        assert!(
            (pixel.red() as i32 - 128).abs() <= 2,
            "overlap red = {}", pixel.red()
        );
        assert!(
            (pixel.green() as i32 - 128).abs() <= 2,
            "overlap green = {}", pixel.green()
        );
        assert!(
            (pixel.blue() as i32 - 128).abs() <= 2,
            "overlap blue = {}", pixel.blue()
        );
    }

    /// Children inherit `stroke` from the parent `<g>` open
    /// tag. Mirrors the terrain-detail walk_and_paint
    /// passthrough shape — the open tag carries the colour, the
    /// children carry only `fill="none" stroke-width="…"`.
    #[test]
    fn child_inherits_stroke_from_parent_g() {
        use super::inherit_attrs;
        let parent = "<g opacity=\"0.5\" stroke=\"#FF0000\" \
                     stroke-linecap=\"round\">";
        let child = "<line x1=\"0\" y1=\"0\" x2=\"10\" y2=\"0\" \
                     stroke-width=\"1\"/>";
        let inherited = inherit_attrs(child, parent);
        assert!(
            inherited.contains("stroke=\"#FF0000\""),
            "inherited stroke missing: {inherited}"
        );
        assert!(
            inherited.contains("stroke-linecap=\"round\""),
            "inherited stroke-linecap missing: {inherited}"
        );
    }

    /// Inheritance does NOT clobber attrs the child declares.
    #[test]
    fn child_attr_overrides_parent() {
        use super::inherit_attrs;
        let parent = "<g stroke=\"#FF0000\">";
        let child = "<line stroke=\"#00FF00\"/>";
        let inherited = inherit_attrs(child, parent);
        assert!(
            inherited.contains("stroke=\"#00FF00\""),
            "child stroke clobbered: {inherited}"
        );
        assert!(
            !inherited.contains("stroke=\"#FF0000\""),
            "parent stroke leaked: {inherited}"
        );
    }

    /// `paint_fragments` accumulates the multi-entry group
    /// shape from terrain-detail's walk_and_paint passthrough
    /// (open-tag fragment, child fragments, close-tag fragment)
    /// into a single self-contained group, then dispatches
    /// through the inheritance + offscreen-buffer path.
    #[test]
    fn paint_fragments_accumulates_multi_entry_group() {
        let mut pixmap = Pixmap::new(20, 20).unwrap();
        let mut scratch = Pixmap::new(20, 20).unwrap();
        pixmap.fill(tiny_skia::Color::WHITE);
        let mut ctx = RasterCtx {
            pixmap: &mut pixmap,
            scratch: &mut scratch,
            transform: Transform::identity(),
            scale: 1.0,
        };
        // Terrain-detail walk_and_paint shape: open-g (no
        // close), several child paths inheriting stroke +
        // stroke-linecap, then a close-g.
        let fragments: Vec<String> = vec![
            "<g opacity=\"0.5\" stroke=\"#000000\" stroke-linecap=\"round\">"
                .to_string(),
            "<rect x=\"0\" y=\"0\" width=\"10\" height=\"10\" fill=\"#000000\"/>"
                .to_string(),
            "</g>".to_string(),
        ];
        super::paint_fragments(&fragments, 1.0, None, &mut ctx);

        let pixel = ctx.pixmap.pixel(5, 5).unwrap();
        // White * 0.5 + black * 0.5 ≈ 128.
        assert!(
            (pixel.red() as i32 - 128).abs() <= 2,
            "multi-entry group: red = {}",
            pixel.red()
        );
    }

    /// (2, 2) sits inside only the first rect — non-overlap.
    /// Same expected colour as the overlap pixel: `white * 0.5
    /// + black * 0.5`. Per-element-alpha would have produced
    /// the same value here, so the test is a control: when the
    /// implementation is correct, both pixels land at 128.
    #[test]
    fn group_opacity_non_overlap_pixel_matches_overlap() {
        let mut pixmap = Pixmap::new(20, 20).unwrap();
        let mut scratch = Pixmap::new(20, 20).unwrap();
        pixmap.fill(tiny_skia::Color::WHITE);
        let mut ctx = RasterCtx {
            pixmap: &mut pixmap,
            scratch: &mut scratch,
            transform: Transform::identity(),
            scale: 1.0,
        };
        let frag = "<g opacity=\"0.5\">\
            <rect x=\"0\" y=\"0\" width=\"10\" height=\"10\" \
             fill=\"#000000\"/>\
            <rect x=\"5\" y=\"5\" width=\"10\" height=\"10\" \
             fill=\"#000000\"/>\
            </g>";
        paint_fragment(frag, 1.0, None, &mut ctx);

        let non_overlap = ctx.pixmap.pixel(2, 2).unwrap();
        let overlap = ctx.pixmap.pixel(7, 7).unwrap();
        assert_eq!(non_overlap.red(), overlap.red());
        assert_eq!(non_overlap.green(), overlap.green());
        assert_eq!(non_overlap.blue(), overlap.blue());
    }
}
