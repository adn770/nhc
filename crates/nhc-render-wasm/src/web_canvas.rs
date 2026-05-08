//! Browser-side `Canvas2DCtx` impl.
//!
//! Wraps `web_sys::CanvasRenderingContext2d` plus the
//! `HtmlCanvasElement` that owns it (the latter doubles as the
//! `drawImage` source for `end_group`'s offscreen blit). Phase
//! 5.3 of `plans/nhc_pure_ir_v5_migration_plan.md` — the
//! production binding for [`nhc_render::transform::canvas::floor_ir_to_canvas`].
//!
//! Compiled only when targeting `wasm32-unknown-unknown`. Native
//! cargo test builds skip the module entirely so the rest of
//! the wasm crate's surface stays runnable on the host arch.

use nhc_render::painter::canvas::{
    Canvas2DCtx, CanvasLineCap, CanvasLineJoin,
};
use wasm_bindgen::{JsCast, JsValue};
use web_sys::{
    CanvasRenderingContext2d, CanvasWindingRule, HtmlCanvasElement,
};

/// `Canvas2DCtx` impl backed by a real browser canvas.
///
/// Each instance carries:
///
/// - `ctx`: the `CanvasRenderingContext2d` the painter's
///   [`Canvas2DCtx`] methods dispatch to.
/// - `canvas`: the owning `HtmlCanvasElement`, retained so the
///   instance can be passed as a `drawImage` source when a
///   parent surface composites this canvas's contents during
///   `end_group`.
pub struct WebCanvasCtx {
    ctx: CanvasRenderingContext2d,
    canvas: HtmlCanvasElement,
}

impl WebCanvasCtx {
    /// Wrap a caller-supplied `CanvasRenderingContext2d`. Fails
    /// when the context has no associated canvas (the only
    /// observable failure mode is contexts derived from
    /// `OffscreenCanvas`, which return `None` from
    /// [`CanvasRenderingContext2d::canvas`] — callers using
    /// those should construct `WebCanvasCtx` directly via
    /// [`WebCanvasCtx::from_parts`]).
    pub fn from_ctx(
        ctx: CanvasRenderingContext2d,
    ) -> Result<Self, JsValue> {
        let canvas = ctx.canvas().ok_or_else(|| {
            JsValue::from_str(
                "CanvasRenderingContext2d has no associated canvas",
            )
        })?;
        Ok(Self { ctx, canvas })
    }

    /// Wrap pre-fetched `(ctx, canvas)` halves. Used by
    /// [`Canvas2DCtx::create_offscreen`] which pairs both
    /// together at allocation time.
    pub fn from_parts(
        ctx: CanvasRenderingContext2d,
        canvas: HtmlCanvasElement,
    ) -> Self {
        Self { ctx, canvas }
    }

    /// Allocate a fresh `(canvas, ctx)` pair sized
    /// `width × height` CSS pixels. Used by `begin_group` to
    /// route paints into a hidden surface without touching the
    /// DOM tree (the canvas isn't attached anywhere).
    fn allocate(width: u32, height: u32) -> Result<Self, JsValue> {
        let document = web_sys::window()
            .ok_or_else(|| JsValue::from_str("no global window"))?
            .document()
            .ok_or_else(|| JsValue::from_str("no document"))?;
        let canvas = document
            .create_element("canvas")?
            .dyn_into::<HtmlCanvasElement>()
            .map_err(|_| {
                JsValue::from_str("failed to cast canvas element")
            })?;
        canvas.set_width(width);
        canvas.set_height(height);
        let ctx = canvas
            .get_context("2d")?
            .ok_or_else(|| {
                JsValue::from_str("getContext('2d') returned null")
            })?
            .dyn_into::<CanvasRenderingContext2d>()
            .map_err(|_| {
                JsValue::from_str("failed to cast 2d context")
            })?;
        Ok(Self::from_parts(ctx, canvas))
    }
}

fn line_cap_str(cap: CanvasLineCap) -> &'static str {
    match cap {
        CanvasLineCap::Butt => "butt",
        CanvasLineCap::Round => "round",
        CanvasLineCap::Square => "square",
    }
}

fn line_join_str(join: CanvasLineJoin) -> &'static str {
    match join {
        CanvasLineJoin::Miter => "miter",
        CanvasLineJoin::Round => "round",
        CanvasLineJoin::Bevel => "bevel",
    }
}

impl Canvas2DCtx for WebCanvasCtx {
    fn save(&self) {
        self.ctx.save();
    }
    fn restore(&self) {
        self.ctx.restore();
    }
    fn fill_rect(&self, x: f64, y: f64, w: f64, h: f64) {
        self.ctx.fill_rect(x, y, w, h);
    }
    fn stroke_rect(&self, x: f64, y: f64, w: f64, h: f64) {
        self.ctx.stroke_rect(x, y, w, h);
    }
    fn begin_path(&self) {
        self.ctx.begin_path();
    }
    fn close_path(&self) {
        self.ctx.close_path();
    }
    fn move_to(&self, x: f64, y: f64) {
        self.ctx.move_to(x, y);
    }
    fn line_to(&self, x: f64, y: f64) {
        self.ctx.line_to(x, y);
    }
    fn quadratic_curve_to(&self, cx: f64, cy: f64, x: f64, y: f64) {
        self.ctx.quadratic_curve_to(cx, cy, x, y);
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
        self.ctx.bezier_curve_to(c1x, c1y, c2x, c2y, x, y);
    }
    fn arc(&self, x: f64, y: f64, r: f64, s: f64, e: f64) {
        // Canvas2D ``arc`` returns ``Result`` for invalid args
        // (negative radius, NaN). The painter never emits these
        // — primitives clamp before dispatching — so we discard
        // the result rather than propagating up to the wasm
        // boundary.
        let _ = self.ctx.arc(x, y, r, s, e);
    }
    fn ellipse(
        &self,
        x: f64,
        y: f64,
        rx: f64,
        ry: f64,
        rot: f64,
        s: f64,
        e: f64,
    ) {
        let _ = self.ctx.ellipse(x, y, rx, ry, rot, s, e);
    }
    fn fill(&self) {
        self.ctx.fill();
    }
    fn fill_even_odd(&self) {
        self.ctx
            .fill_with_canvas_winding_rule(CanvasWindingRule::Evenodd);
    }
    fn stroke(&self) {
        self.ctx.stroke();
    }
    fn clip(&self) {
        self.ctx.clip();
    }
    fn clip_even_odd(&self) {
        self.ctx
            .clip_with_canvas_winding_rule(CanvasWindingRule::Evenodd);
    }
    fn transform(
        &self,
        a: f64,
        b: f64,
        c: f64,
        d: f64,
        e: f64,
        f: f64,
    ) {
        let _ = self.ctx.transform(a, b, c, d, e, f);
    }
    fn set_transform(
        &self,
        a: f64,
        b: f64,
        c: f64,
        d: f64,
        e: f64,
        f: f64,
    ) {
        let _ = self.ctx.set_transform(a, b, c, d, e, f);
    }
    fn set_fill_style(&self, css: &str) {
        // ``set_fill_style_str`` lands the CSS colour through the
        // string-typed setter in web-sys 0.3.94+; the JsValue
        // setter is deprecated.
        self.ctx.set_fill_style_str(css);
    }
    fn set_stroke_style(&self, css: &str) {
        self.ctx.set_stroke_style_str(css);
    }
    fn set_line_width(&self, w: f64) {
        self.ctx.set_line_width(w);
    }
    fn set_line_cap(&self, cap: CanvasLineCap) {
        self.ctx.set_line_cap(line_cap_str(cap));
    }
    fn set_line_join(&self, join: CanvasLineJoin) {
        self.ctx.set_line_join(line_join_str(join));
    }
    fn set_miter_limit(&self, limit: f64) {
        self.ctx.set_miter_limit(limit);
    }
    fn set_global_alpha(&self, alpha: f64) {
        self.ctx.set_global_alpha(alpha);
    }
    fn create_offscreen(&self, width: u32, height: u32) -> Self {
        // The painter expects infallible offscreen allocation —
        // a failure here is unrecoverable (no DOM, OOM). The JS
        // dispatcher catches the panic via wasm-bindgen's
        // `console_error_panic_hook` (Phase 5.5) so the user
        // sees a stack trace rather than a silent miss-render.
        Self::allocate(width, height)
            .expect("WebCanvasCtx::create_offscreen failed")
    }
    fn draw_image_at(&self, src: &Self, x: f64, y: f64) {
        let _ = self
            .ctx
            .draw_image_with_html_canvas_element(&src.canvas, x, y);
    }
}
