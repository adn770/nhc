//! `SkiaPainter` — `Painter` impl on top of `tiny_skia::Pixmap`.
//!
//! Phase 2.2 of `plans/nhc_pure_ir_plan.md`. Drives the
//! `ir_to_png` rasteriser path. The per-primitive ports in
//! 2.4 – 2.15 will switch each `transform/png/<op>.rs` handler
//! to construct a `SkiaPainter` over the active `Pixmap` and
//! call into the trait instead of `Pixmap::fill_*` directly.
//!
//! `begin_group` / `end_group` lift the offscreen-buffer mechanism
//! from `transform/png/fragment.rs::paint_offscreen_group` and
//! generalise it to nesting via a `Vec<GroupFrame>` stack — the
//! legacy `paint_fragment` was non-nested. Each `begin_group`
//! allocates a same-sized scratch pixmap and pushes it; the
//! "active surface" is the top of the stack (or the borrowed
//! target when the stack is empty). `end_group` pops the top
//! scratch and `draw_pixmap`s it onto the new active surface
//! with `PixmapPaint::opacity = group_opacity`.
//!
//! `push_clip` / `pop_clip` build a stack of `tiny_skia::Mask`s.
//! Nested `push_clip` calls intersect via `Mask::intersect_path`.
//! The current clip mask (if any) is passed to every `Pixmap`
//! draw call as `Some(&mask)`.

use tiny_skia::{
    BlendMode, Color as SkColor, FillRule as SkFillRule,
    FilterQuality, LineCap as SkLineCap, LineJoin as SkLineJoin, Mask,
    Paint as SkPaint, PathBuilder, Pixmap, PixmapPaint, Rect as SkRect,
    Stroke as SkStroke, Transform,
};

use super::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOp, PathOps, Rect, Stroke, Vec2,
};

/// Paints onto a `tiny_skia::Pixmap` via the `Painter` trait.
///
/// The painter holds a mutable borrow of the destination pixmap
/// for its lifetime. Group / clip stacks live inside the painter
/// and unwind cleanly when the painter is dropped, but unbalanced
/// `begin_group` / `push_clip` calls without their matching close
/// pair are a programming error and will be caught by the
/// trait-level conformance tests in 2.5+.
pub struct SkiaPainter<'a> {
    target: &'a mut Pixmap,
    transform: Transform,
    group_stack: Vec<GroupFrame>,
    clip_stack: Vec<Mask>,
    width: u32,
    height: u32,
}

struct GroupFrame {
    scratch: Pixmap,
    opacity: f32,
}

impl<'a> SkiaPainter<'a> {
    /// Construct a painter that writes to `target` with the
    /// identity transform.
    pub fn new(target: &'a mut Pixmap) -> Self {
        let (width, height) = (target.width(), target.height());
        Self {
            target,
            transform: Transform::identity(),
            group_stack: Vec::new(),
            clip_stack: Vec::new(),
            width,
            height,
        }
    }

    /// Construct a painter with a non-identity transform applied
    /// to every paint call. Used by op handlers that pre-compose
    /// translate + scale (the legacy `RasterCtx::transform`).
    pub fn with_transform(target: &'a mut Pixmap, transform: Transform) -> Self {
        let mut this = Self::new(target);
        this.transform = transform;
        this
    }

    /// `true` if no `begin_group` / `push_clip` is currently
    /// open. Used by the 2.5+ port tests to assert that primitives
    /// balance their scopes.
    pub fn is_balanced(&self) -> bool {
        self.group_stack.is_empty() && self.clip_stack.is_empty()
    }
}

impl<'a> Painter for SkiaPainter<'a> {
    fn fill_rect(&mut self, rect: Rect, paint: &Paint) {
        let Some(rect) = SkRect::from_xywh(rect.x, rect.y, rect.w, rect.h)
        else {
            return;
        };
        let p = build_paint(paint);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.fill_rect(rect, &p, transform, mask);
    }

    fn stroke_rect(&mut self, rect: Rect, paint: &Paint, stroke: &Stroke) {
        let Some(rect) = SkRect::from_xywh(rect.x, rect.y, rect.w, rect.h)
        else {
            return;
        };
        let mut pb = PathBuilder::new();
        pb.push_rect(rect);
        let Some(path) = pb.finish() else {
            return;
        };
        let p = build_paint(paint);
        let s = build_stroke(stroke);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.stroke_path(&path, &p, &s, transform, mask);
    }

    fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint) {
        if r <= 0.0 {
            return;
        }
        let mut pb = PathBuilder::new();
        pb.push_circle(cx, cy, r);
        let Some(path) = pb.finish() else {
            return;
        };
        let p = build_paint(paint);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.fill_path(&path, &p, SkFillRule::Winding, transform, mask);
    }

    fn fill_ellipse(&mut self, cx: f32, cy: f32, rx: f32, ry: f32, paint: &Paint) {
        if rx <= 0.0 || ry <= 0.0 {
            return;
        }
        let Some(rect) = SkRect::from_xywh(cx - rx, cy - ry, rx * 2.0, ry * 2.0)
        else {
            return;
        };
        let mut pb = PathBuilder::new();
        pb.push_oval(rect);
        let Some(path) = pb.finish() else {
            return;
        };
        let p = build_paint(paint);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.fill_path(&path, &p, SkFillRule::Winding, transform, mask);
    }

    fn fill_polygon(&mut self, vertices: &[Vec2], paint: &Paint, fill_rule: FillRule) {
        if vertices.len() < 3 {
            return;
        }
        let Some(path) = polyline_path(vertices, true) else {
            return;
        };
        let p = build_paint(paint);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.fill_path(&path, &p, to_skia_fill_rule(fill_rule), transform, mask);
    }

    fn stroke_polyline(&mut self, vertices: &[Vec2], paint: &Paint, stroke: &Stroke) {
        if vertices.len() < 2 {
            return;
        }
        let Some(path) = polyline_path(vertices, false) else {
            return;
        };
        let p = build_paint(paint);
        let s = build_stroke(stroke);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.stroke_path(&path, &p, &s, transform, mask);
    }

    fn fill_path(&mut self, path: &PathOps, paint: &Paint, fill_rule: FillRule) {
        let Some(path) = path_to_tiny_skia(path) else {
            return;
        };
        let p = build_paint(paint);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.fill_path(&path, &p, to_skia_fill_rule(fill_rule), transform, mask);
    }

    fn stroke_path(&mut self, path: &PathOps, paint: &Paint, stroke: &Stroke) {
        let Some(path) = path_to_tiny_skia(path) else {
            return;
        };
        let p = build_paint(paint);
        let s = build_stroke(stroke);
        let transform = self.transform;
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.stroke_path(&path, &p, &s, transform, mask);
    }

    fn begin_group(&mut self, opacity: f32) {
        let mut scratch = Pixmap::new(self.width, self.height)
            .expect("scratch pixmap allocation");
        scratch.fill(SkColor::TRANSPARENT);
        self.group_stack.push(GroupFrame { scratch, opacity });
    }

    fn end_group(&mut self) {
        let frame = self
            .group_stack
            .pop()
            .expect("end_group without matching begin_group");
        let pp = PixmapPaint {
            opacity: frame.opacity.clamp(0.0, 1.0),
            blend_mode: BlendMode::SourceOver,
            quality: FilterQuality::Nearest,
        };
        let mask = self.clip_stack.last();
        let surface = active_surface(&mut self.target, &mut self.group_stack);
        surface.draw_pixmap(0, 0, frame.scratch.as_ref(), &pp, Transform::identity(), mask);
    }

    fn push_clip(&mut self, path: &PathOps, fill_rule: FillRule) {
        let Some(skia_path) = path_to_tiny_skia(path) else {
            // Empty / degenerate path → push a clone of the
            // current top so pop_clip stays balanced; the empty
            // intersection means nothing else paints either way.
            if let Some(prev) = self.clip_stack.last() {
                let clone = prev.clone();
                self.clip_stack.push(clone);
            } else if let Some(mask) = Mask::new(self.width, self.height) {
                self.clip_stack.push(mask);
            }
            return;
        };
        let rule = to_skia_fill_rule(fill_rule);
        let new_mask = if let Some(prev) = self.clip_stack.last() {
            let mut mask = prev.clone();
            mask.intersect_path(&skia_path, rule, true, self.transform);
            mask
        } else {
            let mut mask = Mask::new(self.width, self.height)
                .expect("clip mask allocation");
            mask.fill_path(&skia_path, rule, true, self.transform);
            mask
        };
        self.clip_stack.push(new_mask);
    }

    fn pop_clip(&mut self) {
        self.clip_stack
            .pop()
            .expect("pop_clip without matching push_clip");
    }
}

/// Returns the active drawing surface — the top scratch pixmap
/// when a group is open, or the borrowed `target` otherwise.
///
/// Standalone helper (rather than `&mut self` method) to keep the
/// borrow split clean: the caller can simultaneously hold an
/// immutable borrow of `self.clip_stack` for the mask argument.
fn active_surface<'p>(
    target: &'p mut &mut Pixmap,
    group_stack: &'p mut [GroupFrame],
) -> &'p mut Pixmap {
    match group_stack.last_mut() {
        Some(frame) => &mut frame.scratch,
        None => &mut **target,
    }
}

fn build_paint(paint: &Paint) -> SkPaint<'static> {
    let mut p = SkPaint::default();
    let Color { r, g, b, a } = paint.color;
    p.set_color(SkColor::from_rgba8(r, g, b, a));
    p.anti_alias = true;
    p
}

fn build_stroke(stroke: &Stroke) -> SkStroke {
    SkStroke {
        width: stroke.width,
        line_cap: to_skia_line_cap(stroke.line_cap),
        line_join: to_skia_line_join(stroke.line_join),
        ..SkStroke::default()
    }
}

fn to_skia_line_cap(cap: LineCap) -> SkLineCap {
    match cap {
        LineCap::Butt => SkLineCap::Butt,
        LineCap::Round => SkLineCap::Round,
        LineCap::Square => SkLineCap::Square,
    }
}

fn to_skia_line_join(join: LineJoin) -> SkLineJoin {
    match join {
        LineJoin::Miter => SkLineJoin::Miter,
        LineJoin::Round => SkLineJoin::Round,
        LineJoin::Bevel => SkLineJoin::Bevel,
    }
}

fn to_skia_fill_rule(rule: FillRule) -> SkFillRule {
    match rule {
        FillRule::Winding => SkFillRule::Winding,
        FillRule::EvenOdd => SkFillRule::EvenOdd,
    }
}

fn polyline_path(vertices: &[Vec2], close: bool) -> Option<tiny_skia::Path> {
    let mut pb = PathBuilder::new();
    let first = vertices[0];
    pb.move_to(first.x, first.y);
    for v in &vertices[1..] {
        pb.line_to(v.x, v.y);
    }
    if close {
        pb.close();
    }
    pb.finish()
}

fn path_to_tiny_skia(path: &PathOps) -> Option<tiny_skia::Path> {
    if path.is_empty() {
        return None;
    }
    let mut pb = PathBuilder::new();
    for op in &path.ops {
        match *op {
            PathOp::MoveTo(p) => pb.move_to(p.x, p.y),
            PathOp::LineTo(p) => pb.line_to(p.x, p.y),
            PathOp::QuadTo(c, p) => pb.quad_to(c.x, c.y, p.x, p.y),
            PathOp::CubicTo(c1, c2, p) => pb.cubic_to(c1.x, c1.y, c2.x, c2.y, p.x, p.y),
            PathOp::Close => pb.close(),
        }
    }
    pb.finish()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::{Color as PColor, Paint as PPaint, Stroke as PStroke};

    fn black() -> PPaint {
        PPaint::solid(PColor::rgb(0, 0, 0))
    }

    fn white_canvas(w: u32, h: u32) -> Pixmap {
        let mut p = Pixmap::new(w, h).unwrap();
        p.fill(SkColor::WHITE);
        p
    }

    fn pixel_rgba(p: &Pixmap, x: u32, y: u32) -> (u8, u8, u8, u8) {
        let pix = p.pixel(x, y).unwrap();
        (pix.red(), pix.green(), pix.blue(), pix.alpha())
    }

    #[test]
    fn fill_rect_paints_solid_colour() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            painter.fill_rect(Rect::new(2.0, 2.0, 8.0, 8.0), &black());
        }
        // Inside the rect — black.
        let (r, g, b, _) = pixel_rgba(&canvas, 5, 5);
        assert_eq!((r, g, b), (0, 0, 0));
        // Outside the rect — still white.
        let (r, g, b, _) = pixel_rgba(&canvas, 15, 15);
        assert_eq!((r, g, b), (255, 255, 255));
    }

    #[test]
    fn stroke_rect_paints_outline_only() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            painter.stroke_rect(
                Rect::new(2.0, 2.0, 16.0, 16.0),
                &black(),
                &PStroke::solid(2.0),
            );
        }
        // Edge pixel — dark.
        let (r, _, _, _) = pixel_rgba(&canvas, 2, 10);
        assert!(r < 128, "edge red = {r}");
        // Centre pixel — still white (fill is hollow).
        let (r, g, b, _) = pixel_rgba(&canvas, 10, 10);
        assert_eq!((r, g, b), (255, 255, 255));
    }

    #[test]
    fn fill_circle_paints_inside_radius() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            painter.fill_circle(10.0, 10.0, 5.0, &black());
        }
        // Centre — solid black.
        let (r, g, b, _) = pixel_rgba(&canvas, 10, 10);
        assert_eq!((r, g, b), (0, 0, 0));
        // Far outside circle — white.
        let (r, g, b, _) = pixel_rgba(&canvas, 0, 0);
        assert_eq!((r, g, b), (255, 255, 255));
    }

    #[test]
    fn fill_ellipse_extends_along_major_axis() {
        let mut canvas = white_canvas(40, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            painter.fill_ellipse(20.0, 10.0, 15.0, 5.0, &black());
        }
        // (15, 10) lies inside the rx=15 horizontal radius.
        let (r, g, b, _) = pixel_rgba(&canvas, 15, 10);
        assert_eq!((r, g, b), (0, 0, 0));
        // (20, 4) lies above the ry=5 vertical radius (5px from centre).
        let (r, _, _, _) = pixel_rgba(&canvas, 20, 4);
        assert!(r > 200, "above ellipse should be near-white, got {r}");
    }

    #[test]
    fn fill_polygon_paints_triangle() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            let verts = [
                Vec2::new(2.0, 18.0),
                Vec2::new(18.0, 18.0),
                Vec2::new(10.0, 2.0),
            ];
            painter.fill_polygon(&verts, &black(), FillRule::Winding);
        }
        // Inside the triangle (centroid-ish) — black.
        let (r, g, b, _) = pixel_rgba(&canvas, 10, 12);
        assert_eq!((r, g, b), (0, 0, 0));
        // Top corner — white (above the triangle apex).
        let (r, g, b, _) = pixel_rgba(&canvas, 10, 0);
        assert_eq!((r, g, b), (255, 255, 255));
    }

    #[test]
    fn stroke_polyline_paints_line() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            let verts = [Vec2::new(2.0, 10.0), Vec2::new(18.0, 10.0)];
            painter.stroke_polyline(&verts, &black(), &PStroke::solid(2.0));
        }
        // Pixel on the line — dark.
        let (r, _, _, _) = pixel_rgba(&canvas, 10, 10);
        assert!(r < 128, "line red = {r}");
        // Pixel away from line — white.
        let (r, g, b, _) = pixel_rgba(&canvas, 10, 0);
        assert_eq!((r, g, b), (255, 255, 255));
    }

    #[test]
    fn fill_path_paints_closed_quad() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            let mut path = PathOps::new();
            path.move_to(Vec2::new(2.0, 2.0))
                .line_to(Vec2::new(18.0, 2.0))
                .line_to(Vec2::new(18.0, 18.0))
                .line_to(Vec2::new(2.0, 18.0))
                .close();
            painter.fill_path(&path, &black(), FillRule::Winding);
        }
        let (r, g, b, _) = pixel_rgba(&canvas, 10, 10);
        assert_eq!((r, g, b), (0, 0, 0));
    }

    /// Mirrors `transform/png/fragment.rs::group_opacity_does_not_
    /// over_darken_overlap`. Two overlapping black rects under a
    /// 0.5-opacity group must composite at white * 0.5 + black *
    /// 0.5 ≈ 128 in the overlap region. Per-element-alpha (the
    /// pre-Phase-5.10 behaviour) would have over-darkened the
    /// overlap to ~64.
    #[test]
    fn group_opacity_does_not_over_darken_overlap() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            painter.begin_group(0.5);
            painter.fill_rect(Rect::new(0.0, 0.0, 10.0, 10.0), &black());
            painter.fill_rect(Rect::new(5.0, 5.0, 10.0, 10.0), &black());
            painter.end_group();
        }
        let overlap = pixel_rgba(&canvas, 7, 7);
        assert!(
            (overlap.0 as i32 - 128).abs() <= 2,
            "overlap red = {}, expected ≈ 128",
            overlap.0
        );
        let non_overlap = pixel_rgba(&canvas, 2, 2);
        assert_eq!(
            non_overlap.0, overlap.0,
            "non-overlap and overlap pixels must match under group opacity"
        );
    }

    /// Nested groups composite at the product of their opacities.
    /// Two `begin_group(0.5)` nests around a black rect on white →
    /// effective opacity 0.25 → pixel ≈ white * 0.75 + black *
    /// 0.25 = 191.
    #[test]
    fn nested_groups_compose_opacities() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            painter.begin_group(0.5);
            painter.begin_group(0.5);
            painter.fill_rect(Rect::new(2.0, 2.0, 16.0, 16.0), &black());
            painter.end_group();
            painter.end_group();
        }
        let pixel = pixel_rgba(&canvas, 10, 10);
        assert!(
            (pixel.0 as i32 - 191).abs() <= 2,
            "nested 0.5×0.5 red = {}, expected ≈ 191",
            pixel.0
        );
    }

    #[test]
    fn balanced_painter_after_paired_group_calls() {
        let mut canvas = white_canvas(20, 20);
        let mut painter = SkiaPainter::new(&mut canvas);
        painter.begin_group(0.5);
        painter.fill_rect(Rect::new(0.0, 0.0, 5.0, 5.0), &black());
        painter.end_group();
        assert!(painter.is_balanced());
    }

    #[test]
    fn push_clip_masks_subsequent_paints() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            // Clip to the left half.
            let mut clip = PathOps::new();
            clip.move_to(Vec2::new(0.0, 0.0))
                .line_to(Vec2::new(10.0, 0.0))
                .line_to(Vec2::new(10.0, 20.0))
                .line_to(Vec2::new(0.0, 20.0))
                .close();
            painter.push_clip(&clip, FillRule::Winding);
            // Try to fill the entire canvas.
            painter.fill_rect(Rect::new(0.0, 0.0, 20.0, 20.0), &black());
            painter.pop_clip();
        }
        // Inside the clip (left half) — black.
        let (r, g, b, _) = pixel_rgba(&canvas, 5, 10);
        assert_eq!((r, g, b), (0, 0, 0));
        // Outside the clip (right half) — still white.
        let (r, g, b, _) = pixel_rgba(&canvas, 15, 10);
        assert_eq!((r, g, b), (255, 255, 255));
    }

    #[test]
    fn nested_clips_intersect() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            // Outer clip: left half.
            let mut outer = PathOps::new();
            outer.move_to(Vec2::new(0.0, 0.0))
                .line_to(Vec2::new(10.0, 0.0))
                .line_to(Vec2::new(10.0, 20.0))
                .line_to(Vec2::new(0.0, 20.0))
                .close();
            painter.push_clip(&outer, FillRule::Winding);
            // Inner clip: top half.
            let mut inner = PathOps::new();
            inner.move_to(Vec2::new(0.0, 0.0))
                .line_to(Vec2::new(20.0, 0.0))
                .line_to(Vec2::new(20.0, 10.0))
                .line_to(Vec2::new(0.0, 10.0))
                .close();
            painter.push_clip(&inner, FillRule::Winding);
            painter.fill_rect(Rect::new(0.0, 0.0, 20.0, 20.0), &black());
            painter.pop_clip();
            painter.pop_clip();
        }
        // Top-left quadrant (in both clips) — black.
        let (r, g, b, _) = pixel_rgba(&canvas, 5, 5);
        assert_eq!((r, g, b), (0, 0, 0));
        // Top-right quadrant (outside outer clip) — white.
        let (r, g, b, _) = pixel_rgba(&canvas, 15, 5);
        assert_eq!((r, g, b), (255, 255, 255));
        // Bottom-left quadrant (outside inner clip) — white.
        let (r, g, b, _) = pixel_rgba(&canvas, 5, 15);
        assert_eq!((r, g, b), (255, 255, 255));
    }

    #[test]
    fn pop_clip_restores_previous_paint_extent() {
        let mut canvas = white_canvas(20, 20);
        {
            let mut painter = SkiaPainter::new(&mut canvas);
            let mut clip = PathOps::new();
            clip.move_to(Vec2::new(0.0, 0.0))
                .line_to(Vec2::new(10.0, 0.0))
                .line_to(Vec2::new(10.0, 20.0))
                .line_to(Vec2::new(0.0, 20.0))
                .close();
            painter.push_clip(&clip, FillRule::Winding);
            painter.pop_clip();
            // After pop_clip, the right half should be paintable.
            painter.fill_rect(Rect::new(0.0, 0.0, 20.0, 20.0), &black());
        }
        let (r, g, b, _) = pixel_rgba(&canvas, 15, 10);
        assert_eq!((r, g, b), (0, 0, 0));
    }
}
