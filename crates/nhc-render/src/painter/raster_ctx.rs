//! `RasterCtx` — Canvas2D-compatible `tiny_skia::Pixmap` driver.
//!
//! Phase 0 of `plans/wasm-render-caching.md`. The browser-side
//! `WebCanvasCtx` walks Canvas2D ops into a real
//! `CanvasRenderingContext2d`; production renders are gated only
//! by manual browser smoke tests because `cargo test` can't link
//! `web-sys`. `RasterCtx` mirrors the same `Canvas2DCtx` surface
//! against a `tiny_skia::Pixmap`, so the
//! `floor_ir_to_canvas`/`CanvasPainter` codepath can be exercised
//! end-to-end inside `cargo test`. The output is then PSNR-compared
//! to a reference PNG (≥ 30 dB) by
//! `crates/nhc-render/tests/wasm_canvas_parity.rs`.
//!
//! This module is test infrastructure — production never touches
//! it — but it stays `pub` so the integration-test crate (which
//! sees the same surface external consumers do) can construct it.

use std::cell::RefCell;

use tiny_skia::{
    BlendMode, Color as SkColor, FillRule as SkFillRule, FilterQuality,
    LineCap as SkLineCap, LineJoin as SkLineJoin, Mask, Paint as SkPaint,
    Path, PathBuilder, Pixmap, PixmapPaint, Rect as SkRect, Stroke as SkStroke,
    Transform as SkTransform,
};

use super::canvas::{Canvas2DCtx, CanvasLineCap, CanvasLineJoin};

/// Canvas2D-compatible driver backed by a `tiny_skia::Pixmap`.
///
/// All methods take `&self` to match `Canvas2DCtx`'s contract —
/// the browser ABI exposes the methods on a shared reference, and
/// the trait mirrors that shape so the wasm impl is a one-line
/// delegation. Interior mutability lives in `RefCell`s.
pub struct RasterCtx {
    pixmap: RefCell<Pixmap>,
    width: u32,
    height: u32,
    state: RefCell<State>,
}

/// Mutable Canvas2D drawing state. Canvas2D's `save`/`restore`
/// snapshot every field EXCEPT the in-progress path; we mirror
/// that by holding `path` separately from `saves`.
struct State {
    transform: SkTransform,
    clip: Option<Mask>,
    fill_color: SkColor,
    stroke_color: SkColor,
    line_width: f32,
    line_cap: SkLineCap,
    line_join: SkLineJoin,
    miter_limit: f32,
    global_alpha: f32,

    path: Vec<RasterPathOp>,
    /// Snapshots pushed by `save`, popped by `restore`. Mirrors
    /// the Canvas2D state stack.
    saves: Vec<Snapshot>,
}

#[derive(Clone)]
struct Snapshot {
    transform: SkTransform,
    clip: Option<Mask>,
    fill_color: SkColor,
    stroke_color: SkColor,
    line_width: f32,
    line_cap: SkLineCap,
    line_join: SkLineJoin,
    miter_limit: f32,
    global_alpha: f32,
}

/// Canvas2D path commands recorded in source order. The `Vec`
/// is replayed into a `tiny_skia::PathBuilder` on every `fill`,
/// `stroke`, or `clip` call — Canvas2D semantics keep the path
/// alive across consume operations, so we cannot finalise into a
/// `tiny_skia::Path` eagerly (`PathBuilder::finish` consumes
/// `self`).
#[derive(Clone, Copy, Debug)]
enum RasterPathOp {
    MoveTo(f32, f32),
    LineTo(f32, f32),
    QuadTo(f32, f32, f32, f32),
    CubicTo(f32, f32, f32, f32, f32, f32),
    Close,
    /// Full-circle sub-path. Recorded as a primitive because
    /// `PathBuilder::push_circle` is the natural translation of
    /// `arc(cx, cy, r, 0, TAU)` and avoids cubic-approximation
    /// drift on the most common arc shape.
    Circle(f32, f32, f32),
    /// Full-ellipse sub-path. Same rationale as `Circle`.
    Oval(f32, f32, f32, f32),
}

impl RasterCtx {
    /// Construct a fresh raster context for a `width × height`
    /// canvas. The pixmap starts fully transparent (Canvas2D
    /// default).
    pub fn new(width: u32, height: u32) -> Self {
        let pixmap = Pixmap::new(width, height)
            .expect("RasterCtx::new pixmap allocation");
        Self {
            pixmap: RefCell::new(pixmap),
            width,
            height,
            state: RefCell::new(State::initial()),
        }
    }

    /// Borrow the underlying pixmap. Useful for encoding the
    /// final render to PNG bytes for parity comparison.
    pub fn pixmap(&self) -> std::cell::Ref<'_, Pixmap> {
        self.pixmap.borrow()
    }

    /// Take a clone of the underlying pixmap. Consumes nothing on
    /// `self`. Used by the parity harness to compare rendered
    /// output without holding the borrow.
    pub fn pixmap_clone(&self) -> Pixmap {
        self.pixmap.borrow().clone()
    }
}

impl State {
    fn initial() -> Self {
        Self {
            transform: SkTransform::identity(),
            clip: None,
            fill_color: SkColor::BLACK,
            stroke_color: SkColor::BLACK,
            line_width: 1.0,
            line_cap: SkLineCap::Butt,
            line_join: SkLineJoin::Miter,
            miter_limit: 10.0,
            global_alpha: 1.0,
            path: Vec::new(),
            saves: Vec::new(),
        }
    }

    fn snapshot(&self) -> Snapshot {
        Snapshot {
            transform: self.transform,
            clip: self.clip.clone(),
            fill_color: self.fill_color,
            stroke_color: self.stroke_color,
            line_width: self.line_width,
            line_cap: self.line_cap,
            line_join: self.line_join,
            miter_limit: self.miter_limit,
            global_alpha: self.global_alpha,
        }
    }

    fn apply(&mut self, snap: Snapshot) {
        self.transform = snap.transform;
        self.clip = snap.clip;
        self.fill_color = snap.fill_color;
        self.stroke_color = snap.stroke_color;
        self.line_width = snap.line_width;
        self.line_cap = snap.line_cap;
        self.line_join = snap.line_join;
        self.miter_limit = snap.miter_limit;
        self.global_alpha = snap.global_alpha;
    }
}

impl Canvas2DCtx for RasterCtx {
    fn save(&self) {
        let mut s = self.state.borrow_mut();
        let snap = s.snapshot();
        s.saves.push(snap);
    }

    fn restore(&self) {
        let mut s = self.state.borrow_mut();
        if let Some(snap) = s.saves.pop() {
            s.apply(snap);
        }
    }

    fn fill_rect(&self, x: f64, y: f64, w: f64, h: f64) {
        let s = self.state.borrow();
        let Some(rect) =
            SkRect::from_xywh(x as f32, y as f32, w as f32, h as f32)
        else {
            return;
        };
        let paint = build_paint(s.fill_color, s.global_alpha);
        self.pixmap.borrow_mut().fill_rect(
            rect,
            &paint,
            s.transform,
            s.clip.as_ref(),
        );
    }

    fn stroke_rect(&self, x: f64, y: f64, w: f64, h: f64) {
        let s = self.state.borrow();
        let Some(rect) =
            SkRect::from_xywh(x as f32, y as f32, w as f32, h as f32)
        else {
            return;
        };
        let mut pb = PathBuilder::new();
        pb.push_rect(rect);
        let Some(path) = pb.finish() else { return };
        let paint = build_paint(s.stroke_color, s.global_alpha);
        let stroke = build_stroke(&s);
        self.pixmap.borrow_mut().stroke_path(
            &path,
            &paint,
            &stroke,
            s.transform,
            s.clip.as_ref(),
        );
    }

    fn begin_path(&self) {
        let mut s = self.state.borrow_mut();
        s.path.clear();
    }

    fn close_path(&self) {
        self.state.borrow_mut().path.push(RasterPathOp::Close);
    }

    fn move_to(&self, x: f64, y: f64) {
        self.state
            .borrow_mut()
            .path
            .push(RasterPathOp::MoveTo(x as f32, y as f32));
    }

    fn line_to(&self, x: f64, y: f64) {
        self.state
            .borrow_mut()
            .path
            .push(RasterPathOp::LineTo(x as f32, y as f32));
    }

    fn quadratic_curve_to(&self, cx: f64, cy: f64, x: f64, y: f64) {
        self.state.borrow_mut().path.push(RasterPathOp::QuadTo(
            cx as f32, cy as f32, x as f32, y as f32,
        ));
    }

    fn bezier_curve_to(
        &self,
        c1x: f64,
        c1y: f64,
        c2x: f64,
        c2y: f64,
        x: f64,
        y: f64,
    ) {
        self.state.borrow_mut().path.push(RasterPathOp::CubicTo(
            c1x as f32, c1y as f32, c2x as f32, c2y as f32, x as f32, y as f32,
        ));
    }

    fn arc(&self, x: f64, y: f64, r: f64, start_angle: f64, end_angle: f64) {
        let sweep = (end_angle - start_angle).abs();
        if !is_full_sweep(sweep) {
            panic!(
                "RasterCtx::arc only supports full circles (0..TAU); \
                 got start={start_angle} end={end_angle} (sweep={sweep})"
            );
        }
        self.state
            .borrow_mut()
            .path
            .push(RasterPathOp::Circle(x as f32, y as f32, r as f32));
    }

    fn ellipse(
        &self,
        x: f64,
        y: f64,
        rx: f64,
        ry: f64,
        rotation: f64,
        start_angle: f64,
        end_angle: f64,
    ) {
        let sweep = (end_angle - start_angle).abs();
        if rotation.abs() > 1e-6 || !is_full_sweep(sweep) {
            panic!(
                "RasterCtx::ellipse only supports unrotated full sweeps \
                 (rotation=0, sweep=TAU); got rotation={rotation} \
                 start={start_angle} end={end_angle}"
            );
        }
        self.state.borrow_mut().path.push(RasterPathOp::Oval(
            x as f32, y as f32, rx as f32, ry as f32,
        ));
    }

    fn fill(&self) {
        self.fill_with_rule(SkFillRule::Winding);
    }

    fn fill_even_odd(&self) {
        self.fill_with_rule(SkFillRule::EvenOdd);
    }

    fn stroke(&self) {
        let s = self.state.borrow();
        let Some(path) = build_path(&s.path) else { return };
        let paint = build_paint(s.stroke_color, s.global_alpha);
        let stroke = build_stroke(&s);
        self.pixmap.borrow_mut().stroke_path(
            &path,
            &paint,
            &stroke,
            s.transform,
            s.clip.as_ref(),
        );
    }

    fn clip(&self) {
        self.clip_with_rule(SkFillRule::Winding);
    }

    fn clip_even_odd(&self) {
        self.clip_with_rule(SkFillRule::EvenOdd);
    }

    fn transform(&self, a: f64, b: f64, c: f64, d: f64, e: f64, f: f64) {
        let local = SkTransform::from_row(
            a as f32, b as f32, c as f32, d as f32, e as f32, f as f32,
        );
        let mut s = self.state.borrow_mut();
        // Canvas2D `transform(...)` post-multiplies the current
        // matrix on the right. tiny_skia's `pre_concat(t)` computes
        // `self = self * t`, which lands new coords first through
        // `local` and then through the accumulated outer transform
        // — matching Canvas2D semantics.
        s.transform = s.transform.pre_concat(local);
    }

    fn set_transform(&self, a: f64, b: f64, c: f64, d: f64, e: f64, f: f64) {
        self.state.borrow_mut().transform = SkTransform::from_row(
            a as f32, b as f32, c as f32, d as f32, e as f32, f as f32,
        );
    }

    fn set_fill_style(&self, css_color: &str) {
        self.state.borrow_mut().fill_color = parse_css_color(css_color);
    }

    fn set_stroke_style(&self, css_color: &str) {
        self.state.borrow_mut().stroke_color = parse_css_color(css_color);
    }

    fn set_line_width(&self, w: f64) {
        self.state.borrow_mut().line_width = w as f32;
    }

    fn set_line_cap(&self, cap: CanvasLineCap) {
        self.state.borrow_mut().line_cap = match cap {
            CanvasLineCap::Butt => SkLineCap::Butt,
            CanvasLineCap::Round => SkLineCap::Round,
            CanvasLineCap::Square => SkLineCap::Square,
        };
    }

    fn set_line_join(&self, join: CanvasLineJoin) {
        self.state.borrow_mut().line_join = match join {
            CanvasLineJoin::Miter => SkLineJoin::Miter,
            CanvasLineJoin::Round => SkLineJoin::Round,
            CanvasLineJoin::Bevel => SkLineJoin::Bevel,
        };
    }

    fn set_miter_limit(&self, limit: f64) {
        self.state.borrow_mut().miter_limit = limit as f32;
    }

    fn set_global_alpha(&self, alpha: f64) {
        self.state.borrow_mut().global_alpha = (alpha as f32).clamp(0.0, 1.0);
    }

    fn create_offscreen(&self, width: u32, height: u32) -> Self {
        Self::new(width, height)
    }

    fn clear_rect(&self, x: f64, y: f64, w: f64, h: f64) {
        let s = self.state.borrow();
        let Some(rect) =
            SkRect::from_xywh(x as f32, y as f32, w as f32, h as f32)
        else {
            return;
        };
        // BlendMode::Clear forces destination pixels to (0, 0, 0, 0)
        // regardless of the source colour, matching Canvas2D's
        // clearRect semantics within the rectangle.
        let mut paint = SkPaint::default();
        paint.blend_mode = BlendMode::Clear;
        paint.anti_alias = false;
        self.pixmap.borrow_mut().fill_rect(
            rect,
            &paint,
            s.transform,
            s.clip.as_ref(),
        );
    }

    fn draw_image_at(&self, src: &Self, x: f64, y: f64) {
        let s = self.state.borrow();
        let pp = PixmapPaint {
            opacity: s.global_alpha,
            blend_mode: BlendMode::SourceOver,
            // Canvas2D `drawImage` at integer offsets is
            // nearest-equivalent; the painter always blits at
            // `set_transform(identity)` with x = y = 0 (group
            // composite). Nearest matches SkiaPainter's group
            // blit, keeping the test reference closer to the
            // PNG reference if a future commit ever wires PSNR
            // across both.
            quality: FilterQuality::Nearest,
        };
        // Apply the current transform plus the (x, y) offset so
        // sub-pixel positions land via tiny_skia's bilinear
        // sampler. The painter's `end_group` always calls
        // `set_transform(identity)` then `draw_image_at(..., 0, 0)`
        // so this matrix is identity in practice, but matching
        // Canvas2D semantics keeps the implementation honest.
        let offset =
            SkTransform::from_translate(x as f32, y as f32);
        let transform = s.transform.pre_concat(offset);
        self.pixmap.borrow_mut().draw_pixmap(
            0,
            0,
            src.pixmap.borrow().as_ref(),
            &pp,
            transform,
            s.clip.as_ref(),
        );
    }
}

impl RasterCtx {
    fn fill_with_rule(&self, rule: SkFillRule) {
        let s = self.state.borrow();
        let Some(path) = build_path(&s.path) else { return };
        let paint = build_paint(s.fill_color, s.global_alpha);
        self.pixmap.borrow_mut().fill_path(
            &path,
            &paint,
            rule,
            s.transform,
            s.clip.as_ref(),
        );
    }

    fn clip_with_rule(&self, rule: SkFillRule) {
        let mut s = self.state.borrow_mut();
        let Some(path) = build_path(&s.path) else { return };
        let transform = s.transform;
        let new_mask = if let Some(prev) = s.clip.as_ref() {
            let mut m = prev.clone();
            m.intersect_path(&path, rule, true, transform);
            m
        } else {
            let mut m = Mask::new(self.width, self.height)
                .expect("RasterCtx clip mask allocation");
            m.fill_path(&path, rule, true, transform);
            m
        };
        s.clip = Some(new_mask);
    }
}

fn is_full_sweep(sweep: f64) -> bool {
    (sweep - std::f64::consts::TAU).abs() < 1e-4
}

fn build_paint(color: SkColor, global_alpha: f32) -> SkPaint<'static> {
    let mut p = SkPaint::default();
    let multiplied = SkColor::from_rgba(
        color.red(),
        color.green(),
        color.blue(),
        (color.alpha() * global_alpha.clamp(0.0, 1.0)).clamp(0.0, 1.0),
    )
    .unwrap_or(SkColor::TRANSPARENT);
    p.set_color(multiplied);
    p.anti_alias = true;
    p
}

fn build_stroke(s: &State) -> SkStroke {
    SkStroke {
        width: s.line_width,
        line_cap: s.line_cap,
        line_join: s.line_join,
        miter_limit: s.miter_limit,
        ..SkStroke::default()
    }
}

fn build_path(ops: &[RasterPathOp]) -> Option<Path> {
    if ops.is_empty() {
        return None;
    }
    let mut pb = PathBuilder::new();
    for op in ops {
        match *op {
            RasterPathOp::MoveTo(x, y) => pb.move_to(x, y),
            RasterPathOp::LineTo(x, y) => pb.line_to(x, y),
            RasterPathOp::QuadTo(cx, cy, x, y) => pb.quad_to(cx, cy, x, y),
            RasterPathOp::CubicTo(c1x, c1y, c2x, c2y, x, y) => {
                pb.cubic_to(c1x, c1y, c2x, c2y, x, y)
            }
            RasterPathOp::Close => pb.close(),
            RasterPathOp::Circle(cx, cy, r) => pb.push_circle(cx, cy, r),
            RasterPathOp::Oval(cx, cy, rx, ry) => {
                if let Some(r) = SkRect::from_xywh(
                    cx - rx,
                    cy - ry,
                    rx * 2.0,
                    ry * 2.0,
                ) {
                    pb.push_oval(r);
                }
            }
        }
    }
    pb.finish()
}

/// Parse the CSS colour subset CanvasPainter emits:
/// `rgb(R, G, B)` and `rgba(R, G, B, A)` with whitespace tolerant
/// to the painter's `format!` output. Returns transparent black on
/// any unrecognised shape — strict parsing isn't worth the
/// complexity here because the painter is the only caller and its
/// output is well-defined.
fn parse_css_color(css: &str) -> SkColor {
    let trimmed = css.trim();
    if let Some(inner) = strip_prefix_suffix(trimmed, "rgb(", ")") {
        let parts: Vec<&str> = inner.split(',').map(str::trim).collect();
        if parts.len() == 3 {
            if let (Ok(r), Ok(g), Ok(b)) = (
                parts[0].parse::<u8>(),
                parts[1].parse::<u8>(),
                parts[2].parse::<u8>(),
            ) {
                return SkColor::from_rgba8(r, g, b, 255);
            }
        }
    }
    if let Some(inner) = strip_prefix_suffix(trimmed, "rgba(", ")") {
        let parts: Vec<&str> = inner.split(',').map(str::trim).collect();
        if parts.len() == 4 {
            if let (Ok(r), Ok(g), Ok(b), Ok(a)) = (
                parts[0].parse::<u8>(),
                parts[1].parse::<u8>(),
                parts[2].parse::<u8>(),
                parts[3].parse::<f32>(),
            ) {
                let a_u8 = (a.clamp(0.0, 1.0) * 255.0).round() as u8;
                return SkColor::from_rgba8(r, g, b, a_u8);
            }
        }
    }
    SkColor::TRANSPARENT
}

fn strip_prefix_suffix<'a>(
    s: &'a str,
    prefix: &str,
    suffix: &str,
) -> Option<&'a str> {
    let s = s.strip_prefix(prefix)?;
    s.strip_suffix(suffix)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::canvas::CanvasPainter;
    use crate::painter::{Color, Paint, Painter, Rect, Stroke, Transform, Vec2};

    fn rgba(ctx: &RasterCtx, x: u32, y: u32) -> (u8, u8, u8, u8) {
        let p = ctx.pixmap.borrow();
        let px = p.pixel(x, y).unwrap();
        (px.red(), px.green(), px.blue(), px.alpha())
    }

    fn black() -> Paint {
        Paint::solid(Color::rgb(0, 0, 0))
    }

    fn white() -> Paint {
        Paint::solid(Color::rgb(255, 255, 255))
    }

    #[test]
    fn fill_rect_paints_solid_color() {
        let ctx = RasterCtx::new(20, 20);
        let mut p = CanvasPainter::new(&ctx, 20, 20);
        p.fill_rect(Rect::new(2.0, 2.0, 8.0, 8.0), &black());
        // Inside the rect — black.
        assert_eq!(rgba(&ctx, 5, 5), (0, 0, 0, 255));
        // Outside — transparent black (canvas default).
        assert_eq!(rgba(&ctx, 15, 15), (0, 0, 0, 0));
    }

    #[test]
    fn fill_circle_paints_inside_radius() {
        let ctx = RasterCtx::new(20, 20);
        let mut p = CanvasPainter::new(&ctx, 20, 20);
        p.fill_circle(10.0, 10.0, 5.0, &black());
        // Center — solid black.
        assert_eq!(rgba(&ctx, 10, 10), (0, 0, 0, 255));
        // Far corner — untouched.
        assert_eq!(rgba(&ctx, 0, 0), (0, 0, 0, 0));
    }

    #[test]
    fn stroke_rect_paints_outline_only() {
        let ctx = RasterCtx::new(20, 20);
        // Pre-fill background white so we can detect "stroke
        // happened" without depending on the transparent-zero
        // default.
        ctx.set_fill_style("rgb(255, 255, 255)");
        ctx.fill_rect(0.0, 0.0, 20.0, 20.0);
        let mut p = CanvasPainter::new(&ctx, 20, 20);
        p.stroke_rect(
            Rect::new(2.0, 2.0, 16.0, 16.0),
            &black(),
            &Stroke::solid(2.0),
        );
        // Edge pixel — dark.
        let (r, _, _, _) = rgba(&ctx, 2, 10);
        assert!(r < 128, "stroke edge should darken, got r={r}");
        // Center pixel — still white.
        assert_eq!(rgba(&ctx, 10, 10), (255, 255, 255, 255));
    }

    #[test]
    fn push_clip_masks_subsequent_paints() {
        let ctx = RasterCtx::new(20, 20);
        ctx.set_fill_style("rgb(255, 255, 255)");
        ctx.fill_rect(0.0, 0.0, 20.0, 20.0);
        let mut p = CanvasPainter::new(&ctx, 20, 20);
        let mut clip = crate::painter::PathOps::new();
        clip.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(10.0, 0.0))
            .line_to(Vec2::new(10.0, 20.0))
            .line_to(Vec2::new(0.0, 20.0))
            .close();
        p.push_clip(&clip, crate::painter::FillRule::Winding);
        p.fill_rect(Rect::new(0.0, 0.0, 20.0, 20.0), &black());
        p.pop_clip();
        // Inside the clip — black.
        assert_eq!(rgba(&ctx, 5, 10), (0, 0, 0, 255));
        // Outside the clip — preserved white.
        assert_eq!(rgba(&ctx, 15, 10), (255, 255, 255, 255));
    }

    #[test]
    fn push_transform_translates_paints() {
        let ctx = RasterCtx::new(20, 20);
        let mut p = CanvasPainter::new(&ctx, 20, 20);
        p.push_transform(Transform::translate(10.0, 0.0));
        p.fill_rect(Rect::new(0.0, 0.0, 5.0, 5.0), &black());
        p.pop_transform();
        // Translated rect lands at (10..15, 0..5).
        assert_eq!(rgba(&ctx, 12, 2), (0, 0, 0, 255));
        // Origin untouched.
        assert_eq!(rgba(&ctx, 2, 2), (0, 0, 0, 0));
    }

    #[test]
    fn group_opacity_does_not_over_darken_overlap() {
        // Phase 5.10 invariant on RasterCtx. Two overlapping black
        // rects under begin_group(0.5) composite at white * 0.5
        // + black * 0.5 ≈ 128 — not the over-darkened ~64 a per-
        // element alpha would produce.
        let ctx = RasterCtx::new(20, 20);
        ctx.set_fill_style("rgb(255, 255, 255)");
        ctx.fill_rect(0.0, 0.0, 20.0, 20.0);
        let mut p = CanvasPainter::new(&ctx, 20, 20);
        p.begin_group(0.5);
        p.fill_rect(Rect::new(0.0, 0.0, 10.0, 10.0), &black());
        p.fill_rect(Rect::new(5.0, 5.0, 10.0, 10.0), &black());
        p.end_group();
        let overlap = rgba(&ctx, 7, 7);
        assert!(
            (overlap.0 as i32 - 128).abs() <= 2,
            "overlap red = {}, expected ≈ 128",
            overlap.0
        );
        let non_overlap = rgba(&ctx, 2, 2);
        assert_eq!(
            non_overlap.0, overlap.0,
            "non-overlap and overlap must match under group opacity",
        );
    }

    #[test]
    fn css_color_parse_handles_rgb_and_rgba() {
        let opaque = parse_css_color("rgb(10, 20, 30)").to_color_u8();
        assert_eq!(
            (opaque.red(), opaque.green(), opaque.blue(), opaque.alpha()),
            (10, 20, 30, 255),
        );

        let translucent = parse_css_color("rgba(10, 20, 30, 0.5)").to_color_u8();
        assert_eq!(translucent.red(), 10);
        assert_eq!(
            translucent.alpha(),
            128,
            "rgba 0.5 maps to ~128",
        );

        let zero = parse_css_color("rgba(10, 20, 30, 0)").to_color_u8();
        assert_eq!(zero.alpha(), 0);
    }

    #[test]
    fn fully_transparent_paint_is_a_noop() {
        let ctx = RasterCtx::new(8, 8);
        let mut p = CanvasPainter::new(&ctx, 8, 8);
        p.fill_rect(
            Rect::new(0.0, 0.0, 8.0, 8.0),
            &Paint::solid(Color::rgba(255, 255, 255, 0.0)),
        );
        assert_eq!(rgba(&ctx, 4, 4), (0, 0, 0, 0));
    }

    #[test]
    fn create_offscreen_returns_independent_pixmap() {
        let ctx = RasterCtx::new(8, 8);
        let off = ctx.create_offscreen(4, 4);
        // Sanity: paint into the offscreen, parent stays clean.
        {
            let mut p = CanvasPainter::new(&off, 4, 4);
            p.fill_rect(Rect::new(0.0, 0.0, 4.0, 4.0), &white());
        }
        assert_eq!(rgba(&off, 0, 0), (255, 255, 255, 255));
        assert_eq!(rgba(&ctx, 0, 0), (0, 0, 0, 0));
    }

    #[test]
    fn clear_rect_resets_pixels_under_identity() {
        let ctx = RasterCtx::new(8, 8);
        // Fill with red, then clear a region back to transparent.
        ctx.set_fill_style("rgb(255, 0, 0)");
        ctx.fill_rect(0.0, 0.0, 8.0, 8.0);
        assert_eq!(rgba(&ctx, 4, 4), (255, 0, 0, 255));
        ctx.clear_rect(0.0, 0.0, 4.0, 4.0);
        // Cleared region transparent.
        assert_eq!(rgba(&ctx, 1, 1), (0, 0, 0, 0));
        // Untouched region preserved.
        assert_eq!(rgba(&ctx, 6, 6), (255, 0, 0, 255));
    }

    #[test]
    fn nested_save_restore_round_trips_state() {
        let ctx = RasterCtx::new(8, 8);
        ctx.set_global_alpha(1.0);
        ctx.save();
        ctx.set_global_alpha(0.25);
        assert_eq!(ctx.state.borrow().global_alpha, 0.25);
        ctx.restore();
        assert_eq!(ctx.state.borrow().global_alpha, 1.0);
    }
}
