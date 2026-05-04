//! `SvgPainter` — `Painter` impl emitting semantic SVG elements.
//!
//! Phase 2.3 of `plans/nhc_pure_ir_plan.md`. Drives the
//! `nhc_render.ir_to_svg` PyO3 export added in 2.17 and replaces
//! `nhc/rendering/ir_to_svg.py` once 2.18 / 2.19 land.
//!
//! Each `Painter` call appends one element to a body buffer. The
//! caller (`transform/svg/mod.rs` in 2.16) wraps the body in an
//! outer `<svg width="…" height="…">…</svg>` envelope and prepends
//! the `<defs>` block (clipPath defs accumulated by `push_clip`).
//!
//! `push_clip` deduplicates clipPath defs by hashing the path's
//! `d` attribute string — the same shape pushed twice (e.g. the
//! same dungeon outline used for multiple per-tile op clips)
//! reuses the existing `<clipPath id="auto-N">`. `pop_clip`
//! closes the matching `</g>`.
//!
//! Numeric formatting uses Rust's default `f32::to_string`, which
//! strips trailing zeros (`1.0` → `"1"`, `0.5` → `"0.5"`). Phase
//! 2.21 relaxes the SVG parity gate from byte-equal-against-Python
//! to PSNR + structural sanity, so this painter doesn't need to
//! match the legacy formatter byte-for-byte.

use std::collections::HashMap;
use std::fmt::Write as _;

use super::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOp, PathOps, Rect, Stroke, Transform,
    Vec2,
};

/// Paints into a `String` buffer of SVG elements + a `<defs>`
/// block of `<clipPath>` defs.
#[derive(Debug, Default)]
pub struct SvgPainter {
    body: String,
    defs: String,
    clip_id_for_path: HashMap<String, u32>,
    next_clip_id: u32,
}

impl SvgPainter {
    pub fn new() -> Self {
        Self::default()
    }

    /// The SVG element stream painted so far. Does not include
    /// the outer `<svg>` envelope or the `<defs>` block.
    pub fn body(&self) -> &str {
        &self.body
    }

    /// Accumulated `<clipPath>` defs. Each entry has the shape
    /// `<clipPath id="auto-N"><path d="…"/></clipPath>`.
    pub fn defs(&self) -> &str {
        &self.defs
    }

    /// Consume the painter and return `(defs, body)`.
    pub fn into_parts(self) -> (String, String) {
        (self.defs, self.body)
    }

    fn alloc_clip_id(&mut self, d: String) -> (u32, bool) {
        if let Some(&id) = self.clip_id_for_path.get(&d) {
            return (id, false);
        }
        let id = self.next_clip_id;
        self.next_clip_id += 1;
        self.clip_id_for_path.insert(d, id);
        (id, true)
    }
}

impl Painter for SvgPainter {
    fn fill_rect(&mut self, rect: Rect, paint: &Paint) {
        let _ = write!(
            self.body,
            "<rect x=\"{x}\" y=\"{y}\" width=\"{w}\" height=\"{h}\" fill=\"{fill}\"{op}/>",
            x = fmt_num(rect.x),
            y = fmt_num(rect.y),
            w = fmt_num(rect.w),
            h = fmt_num(rect.h),
            fill = fmt_hex(paint.color),
            op = fmt_fill_opacity(paint.color),
        );
    }

    fn stroke_rect(&mut self, rect: Rect, paint: &Paint, stroke: &Stroke) {
        let _ = write!(
            self.body,
            "<rect x=\"{x}\" y=\"{y}\" width=\"{w}\" height=\"{h}\" fill=\"none\" \
             stroke=\"{stroke_hex}\"{stroke_op} stroke-width=\"{sw}\"{caps}/>",
            x = fmt_num(rect.x),
            y = fmt_num(rect.y),
            w = fmt_num(rect.w),
            h = fmt_num(rect.h),
            stroke_hex = fmt_hex(paint.color),
            stroke_op = fmt_stroke_opacity(paint.color),
            sw = fmt_num(stroke.width),
            caps = fmt_stroke_caps(stroke),
        );
    }

    fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint) {
        let _ = write!(
            self.body,
            "<circle cx=\"{cx}\" cy=\"{cy}\" r=\"{r}\" fill=\"{fill}\"{op}/>",
            cx = fmt_num(cx),
            cy = fmt_num(cy),
            r = fmt_num(r),
            fill = fmt_hex(paint.color),
            op = fmt_fill_opacity(paint.color),
        );
    }

    fn fill_ellipse(&mut self, cx: f32, cy: f32, rx: f32, ry: f32, paint: &Paint) {
        let _ = write!(
            self.body,
            "<ellipse cx=\"{cx}\" cy=\"{cy}\" rx=\"{rx}\" ry=\"{ry}\" fill=\"{fill}\"{op}/>",
            cx = fmt_num(cx),
            cy = fmt_num(cy),
            rx = fmt_num(rx),
            ry = fmt_num(ry),
            fill = fmt_hex(paint.color),
            op = fmt_fill_opacity(paint.color),
        );
    }

    fn fill_polygon(&mut self, vertices: &[Vec2], paint: &Paint, fill_rule: FillRule) {
        if vertices.is_empty() {
            return;
        }
        let _ = write!(
            self.body,
            "<polygon points=\"{points}\" fill=\"{fill}\"{op}{rule}/>",
            points = fmt_points(vertices),
            fill = fmt_hex(paint.color),
            op = fmt_fill_opacity(paint.color),
            rule = fmt_fill_rule(fill_rule),
        );
    }

    fn stroke_polyline(&mut self, vertices: &[Vec2], paint: &Paint, stroke: &Stroke) {
        if vertices.is_empty() {
            return;
        }
        let _ = write!(
            self.body,
            "<polyline points=\"{points}\" fill=\"none\" stroke=\"{stroke_hex}\"{stroke_op} \
             stroke-width=\"{sw}\"{caps}/>",
            points = fmt_points(vertices),
            stroke_hex = fmt_hex(paint.color),
            stroke_op = fmt_stroke_opacity(paint.color),
            sw = fmt_num(stroke.width),
            caps = fmt_stroke_caps(stroke),
        );
    }

    fn fill_path(&mut self, path: &PathOps, paint: &Paint, fill_rule: FillRule) {
        if path.is_empty() {
            return;
        }
        let _ = write!(
            self.body,
            "<path d=\"{d}\" fill=\"{fill}\"{op}{rule}/>",
            d = fmt_path_d(path),
            fill = fmt_hex(paint.color),
            op = fmt_fill_opacity(paint.color),
            rule = fmt_fill_rule(fill_rule),
        );
    }

    fn stroke_path(&mut self, path: &PathOps, paint: &Paint, stroke: &Stroke) {
        if path.is_empty() {
            return;
        }
        let _ = write!(
            self.body,
            "<path d=\"{d}\" fill=\"none\" stroke=\"{stroke_hex}\"{stroke_op} \
             stroke-width=\"{sw}\"{caps}/>",
            d = fmt_path_d(path),
            stroke_hex = fmt_hex(paint.color),
            stroke_op = fmt_stroke_opacity(paint.color),
            sw = fmt_num(stroke.width),
            caps = fmt_stroke_caps(stroke),
        );
    }

    fn begin_group(&mut self, opacity: f32) {
        let _ = write!(self.body, "<g opacity=\"{}\">", fmt_num(opacity.clamp(0.0, 1.0)));
    }

    fn end_group(&mut self) {
        self.body.push_str("</g>");
    }

    fn push_clip(&mut self, path: &PathOps, fill_rule: FillRule) {
        let d = fmt_path_d(path);
        let rule_attr = fmt_fill_rule(fill_rule);
        let (id, fresh) = self.alloc_clip_id(d.clone());
        if fresh {
            let _ = write!(
                self.defs,
                "<clipPath id=\"auto-{id}\"><path d=\"{d}\"{rule}/></clipPath>",
                id = id,
                d = d,
                rule = rule_attr,
            );
        }
        let _ = write!(self.body, "<g clip-path=\"url(#auto-{id})\">", id = id);
    }

    fn pop_clip(&mut self) {
        self.body.push_str("</g>");
    }

    fn push_transform(&mut self, t: Transform) {
        // SVG `matrix(a b c d e f)` encodes the column-major
        // 3x3 [[a c e][b d f][0 0 1]]. The painter trait's
        // Transform mirrors tiny-skia's row layout
        // [[sx kx tx][ky sy ty][0 0 1]], so the SVG-order
        // arguments are (sx ky kx sy tx ty).
        let _ = write!(
            self.body,
            "<g transform=\"matrix({} {} {} {} {} {})\">",
            fmt_num(t.sx),
            fmt_num(t.ky),
            fmt_num(t.kx),
            fmt_num(t.sy),
            fmt_num(t.tx),
            fmt_num(t.ty),
        );
    }

    fn pop_transform(&mut self) {
        self.body.push_str("</g>");
    }
}

fn fmt_num(v: f32) -> String {
    if v.is_finite() && v == v.trunc() {
        format!("{}", v as i64)
    } else {
        format!("{v}")
    }
}

fn fmt_hex(color: Color) -> String {
    format!("#{:02X}{:02X}{:02X}", color.r, color.g, color.b)
}

fn fmt_fill_opacity(color: Color) -> String {
    if color.a >= 1.0 {
        String::new()
    } else {
        format!(" fill-opacity=\"{}\"", fmt_num(color.a))
    }
}

fn fmt_stroke_opacity(color: Color) -> String {
    if color.a >= 1.0 {
        String::new()
    } else {
        format!(" stroke-opacity=\"{}\"", fmt_num(color.a))
    }
}

fn fmt_fill_rule(rule: FillRule) -> &'static str {
    match rule {
        FillRule::Winding => "",
        FillRule::EvenOdd => " fill-rule=\"evenodd\"",
    }
}

fn fmt_stroke_caps(stroke: &Stroke) -> String {
    let mut out = String::new();
    match stroke.line_cap {
        LineCap::Butt => {}
        LineCap::Round => out.push_str(" stroke-linecap=\"round\""),
        LineCap::Square => out.push_str(" stroke-linecap=\"square\""),
    }
    match stroke.line_join {
        LineJoin::Miter => {}
        LineJoin::Round => out.push_str(" stroke-linejoin=\"round\""),
        LineJoin::Bevel => out.push_str(" stroke-linejoin=\"bevel\""),
    }
    out
}

fn fmt_points(vertices: &[Vec2]) -> String {
    let mut out = String::with_capacity(vertices.len() * 12);
    for (i, v) in vertices.iter().enumerate() {
        if i > 0 {
            out.push(' ');
        }
        let _ = write!(out, "{},{}", fmt_num(v.x), fmt_num(v.y));
    }
    out
}

fn fmt_path_d(path: &PathOps) -> String {
    let mut out = String::with_capacity(path.len() * 12);
    for (i, op) in path.ops.iter().enumerate() {
        if i > 0 {
            out.push(' ');
        }
        match *op {
            PathOp::MoveTo(p) => {
                let _ = write!(out, "M {} {}", fmt_num(p.x), fmt_num(p.y));
            }
            PathOp::LineTo(p) => {
                let _ = write!(out, "L {} {}", fmt_num(p.x), fmt_num(p.y));
            }
            PathOp::QuadTo(c, p) => {
                let _ = write!(
                    out,
                    "Q {} {} {} {}",
                    fmt_num(c.x),
                    fmt_num(c.y),
                    fmt_num(p.x),
                    fmt_num(p.y)
                );
            }
            PathOp::CubicTo(c1, c2, p) => {
                let _ = write!(
                    out,
                    "C {} {} {} {} {} {}",
                    fmt_num(c1.x),
                    fmt_num(c1.y),
                    fmt_num(c2.x),
                    fmt_num(c2.y),
                    fmt_num(p.x),
                    fmt_num(p.y)
                );
            }
            PathOp::Close => out.push('Z'),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::{Color as PColor, Paint as PPaint, Stroke as PStroke, Transform as PTransform};

    fn red() -> PPaint {
        PPaint::solid(PColor::rgb(255, 0, 0))
    }

    fn translucent_blue() -> PPaint {
        PPaint::solid(PColor::rgba(0, 0, 255, 0.5))
    }

    #[test]
    fn fill_rect_emits_rect_element() {
        let mut p = SvgPainter::new();
        p.fill_rect(Rect::new(1.0, 2.0, 3.0, 4.0), &red());
        assert_eq!(
            p.body(),
            "<rect x=\"1\" y=\"2\" width=\"3\" height=\"4\" fill=\"#FF0000\"/>"
        );
    }

    #[test]
    fn fill_rect_emits_fill_opacity_for_translucent_paint() {
        let mut p = SvgPainter::new();
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &translucent_blue());
        assert!(
            p.body().contains("fill=\"#0000FF\""),
            "missing hex fill: {}", p.body()
        );
        assert!(
            p.body().contains("fill-opacity="),
            "missing fill-opacity: {}", p.body()
        );
    }

    #[test]
    fn stroke_rect_emits_fill_none_and_stroke_attrs() {
        let mut p = SvgPainter::new();
        p.stroke_rect(Rect::new(0.0, 0.0, 10.0, 10.0), &red(), &PStroke::solid(2.0));
        assert!(
            p.body().contains("fill=\"none\""),
            "missing fill=none: {}", p.body()
        );
        assert!(
            p.body().contains("stroke=\"#FF0000\""),
            "missing stroke colour: {}", p.body()
        );
        assert!(
            p.body().contains("stroke-width=\"2\""),
            "missing stroke-width: {}", p.body()
        );
    }

    #[test]
    fn stroke_rect_emits_line_caps_and_joins() {
        let mut p = SvgPainter::new();
        let stroke = PStroke {
            width: 1.0,
            line_cap: LineCap::Round,
            line_join: LineJoin::Bevel,
        };
        p.stroke_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red(), &stroke);
        assert!(p.body().contains("stroke-linecap=\"round\""));
        assert!(p.body().contains("stroke-linejoin=\"bevel\""));
    }

    #[test]
    fn fill_circle_and_ellipse_emit_native_elements() {
        let mut p = SvgPainter::new();
        p.fill_circle(5.0, 6.0, 3.0, &red());
        p.fill_ellipse(7.0, 8.0, 4.0, 2.0, &red());
        assert!(p.body().contains(
            "<circle cx=\"5\" cy=\"6\" r=\"3\" fill=\"#FF0000\"/>"
        ));
        assert!(p.body().contains(
            "<ellipse cx=\"7\" cy=\"8\" rx=\"4\" ry=\"2\" fill=\"#FF0000\"/>"
        ));
    }

    #[test]
    fn fill_polygon_emits_points_and_fill_rule_for_evenodd() {
        let mut p = SvgPainter::new();
        let verts = [
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(0.0, 10.0),
        ];
        p.fill_polygon(&verts, &red(), FillRule::EvenOdd);
        assert!(
            p.body().contains("points=\"0,0 10,0 0,10\""),
            "polygon points: {}", p.body()
        );
        assert!(p.body().contains("fill-rule=\"evenodd\""));
    }

    #[test]
    fn fill_polygon_winding_omits_fill_rule() {
        let mut p = SvgPainter::new();
        let verts = [Vec2::new(0.0, 0.0), Vec2::new(1.0, 0.0), Vec2::new(0.0, 1.0)];
        p.fill_polygon(&verts, &red(), FillRule::Winding);
        assert!(!p.body().contains("fill-rule"));
    }

    #[test]
    fn stroke_polyline_emits_polyline_element() {
        let mut p = SvgPainter::new();
        let verts = [Vec2::new(0.0, 0.0), Vec2::new(10.0, 0.0)];
        p.stroke_polyline(&verts, &red(), &PStroke::solid(1.5));
        assert!(p.body().starts_with("<polyline"));
        assert!(p.body().contains("points=\"0,0 10,0\""));
        assert!(p.body().contains("fill=\"none\""));
        assert!(p.body().contains("stroke-width=\"1.5\""));
    }

    #[test]
    fn fill_path_emits_d_string() {
        let mut p = SvgPainter::new();
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(10.0, 0.0))
            .quad_to(Vec2::new(10.0, 10.0), Vec2::new(0.0, 10.0))
            .cubic_to(Vec2::new(0.0, 5.0), Vec2::new(0.0, 2.0), Vec2::new(0.0, 0.0))
            .close();
        p.fill_path(&path, &red(), FillRule::Winding);
        assert!(p.body().contains("d=\"M 0 0 L 10 0 Q 10 10 0 10 C 0 5 0 2 0 0 Z\""));
        assert!(p.body().contains("fill=\"#FF0000\""));
    }

    #[test]
    fn stroke_path_emits_fill_none_path() {
        let mut p = SvgPainter::new();
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(1.0, 1.0));
        p.stroke_path(&path, &red(), &PStroke::solid(1.0));
        assert!(p.body().starts_with("<path"));
        assert!(p.body().contains("fill=\"none\""));
        assert!(p.body().contains("stroke=\"#FF0000\""));
    }

    #[test]
    fn begin_and_end_group_emit_balanced_tags() {
        let mut p = SvgPainter::new();
        p.begin_group(0.5);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.end_group();
        assert!(p.body().starts_with("<g opacity=\"0.5\">"));
        assert!(p.body().ends_with("</g>"));
    }

    #[test]
    fn nested_groups_produce_nested_tags() {
        let mut p = SvgPainter::new();
        p.begin_group(0.5);
        p.begin_group(0.25);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.end_group();
        p.end_group();
        let body = p.body();
        let outer = body.find("<g opacity=\"0.5\">").expect("outer group");
        let inner = body.find("<g opacity=\"0.25\">").expect("inner group");
        assert!(outer < inner, "outer group must precede inner: {body}");
        assert!(body.matches("</g>").count() == 2);
    }

    #[test]
    fn push_clip_emits_def_and_g_envelope() {
        let mut p = SvgPainter::new();
        let mut clip = PathOps::new();
        clip.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(10.0, 0.0))
            .line_to(Vec2::new(10.0, 10.0))
            .close();
        p.push_clip(&clip, FillRule::Winding);
        p.fill_rect(Rect::new(0.0, 0.0, 10.0, 10.0), &red());
        p.pop_clip();
        let body = p.body();
        let defs = p.defs();
        assert!(
            defs.contains("<clipPath id=\"auto-0\">"),
            "missing clipPath def: {defs}"
        );
        assert!(
            body.contains("<g clip-path=\"url(#auto-0)\">"),
            "missing clip-path g: {body}"
        );
        assert!(body.ends_with("</g>"));
    }

    #[test]
    fn push_clip_dedups_identical_paths() {
        let mut p = SvgPainter::new();
        let mut clip = PathOps::new();
        clip.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(10.0, 0.0))
            .line_to(Vec2::new(10.0, 10.0))
            .close();
        p.push_clip(&clip, FillRule::Winding);
        p.pop_clip();
        p.push_clip(&clip, FillRule::Winding);
        p.pop_clip();
        let defs = p.defs();
        assert_eq!(
            defs.matches("<clipPath").count(),
            1,
            "identical clip paths must dedup: {defs}"
        );
        let body = p.body();
        assert_eq!(body.matches("url(#auto-0)").count(), 2);
    }

    #[test]
    fn push_clip_assigns_fresh_id_for_distinct_paths() {
        let mut p = SvgPainter::new();
        let mut clip_a = PathOps::new();
        clip_a.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(10.0, 0.0)).close();
        let mut clip_b = PathOps::new();
        clip_b.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(20.0, 0.0)).close();
        p.push_clip(&clip_a, FillRule::Winding);
        p.pop_clip();
        p.push_clip(&clip_b, FillRule::Winding);
        p.pop_clip();
        let defs = p.defs();
        assert!(defs.contains("auto-0"), "first id missing: {defs}");
        assert!(defs.contains("auto-1"), "second id missing: {defs}");
    }

    #[test]
    fn into_parts_returns_defs_and_body() {
        let mut p = SvgPainter::new();
        let mut clip = PathOps::new();
        clip.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(1.0, 0.0)).close();
        p.push_clip(&clip, FillRule::EvenOdd);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.pop_clip();
        let (defs, body) = p.into_parts();
        assert!(defs.contains("<clipPath"));
        assert!(body.contains("<g clip-path"));
    }

    #[test]
    fn push_transform_emits_g_matrix() {
        let mut p = SvgPainter::new();
        p.push_transform(PTransform::translate(3.0, 4.0));
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.pop_transform();
        let body = p.body();
        assert!(
            body.starts_with("<g transform=\"matrix(1 0 0 1 3 4)\">"),
            "missing matrix g envelope: {body}"
        );
        assert!(body.ends_with("</g>"), "missing closing g: {body}");
        assert_eq!(body.matches("</g>").count(), 1);
    }

    #[test]
    fn nested_push_transform_emits_two_g_matrix() {
        let mut p = SvgPainter::new();
        p.push_transform(PTransform::translate(3.0, 0.0));
        p.push_transform(PTransform::translate(0.0, 4.0));
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.pop_transform();
        p.pop_transform();
        let body = p.body();
        assert_eq!(body.matches("<g transform=").count(), 2);
        assert_eq!(body.matches("</g>").count(), 2);
    }

    #[test]
    fn fmt_num_strips_trailing_zero() {
        assert_eq!(fmt_num(1.0), "1");
        assert_eq!(fmt_num(1.5), "1.5");
        assert_eq!(fmt_num(-0.25), "-0.25");
    }

    #[test]
    fn fmt_hex_uppercases_and_zero_pads() {
        assert_eq!(fmt_hex(Color::rgb(0, 0, 0)), "#000000");
        assert_eq!(fmt_hex(Color::rgb(255, 16, 1)), "#FF1001");
    }

    #[test]
    fn fully_transparent_paint_still_emits_attrs() {
        // The painter does not skip alpha=0 paints; that's the
        // primitive's call, not the painter's.
        let mut p = SvgPainter::new();
        let paint = PPaint::solid(PColor::rgba(0, 0, 0, 0.0));
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &paint);
        assert!(p.body().contains("fill-opacity=\"0\""));
    }

    #[test]
    fn fill_opacity_emits_for_subpercent_alpha() {
        // Shadow's 0.08 must round-trip through SvgPainter as
        // fill-opacity="0.08", not 0.0784 (which a u8-alpha
        // round-trip would have produced).
        let mut p = SvgPainter::new();
        let paint = PPaint::solid(PColor::rgba(0, 0, 0, 0.08));
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &paint);
        assert!(
            p.body().contains("fill-opacity=\"0.08\""),
            "subpercent alpha must round-trip exactly: {}",
            p.body()
        );
    }
}
