//! `CanvasPainter` — `Painter` impl that emits Canvas2D calls.
//!
//! Phase 5.2 of `plans/nhc_pure_ir_v5_migration_plan.md`. Drives
//! the browser-side canvas rendering path. Every trait method
//! translates into a sequence of Canvas2D operations on a
//! [`Canvas2DCtx`] — an abstract surface that mirrors the subset
//! of the Canvas2D API the painter needs.
//!
//! The trait abstraction keeps `web-sys` out of `nhc-render`:
//! the production impl wrapping
//! `web_sys::CanvasRenderingContext2d` lives in
//! `nhc-render-wasm` (Phase 5.3 wires the op handlers), and the
//! native test pass exercises a recording mock that captures
//! the call sequence per surface.
//!
//! `begin_group` / `end_group` allocate an offscreen surface via
//! [`Canvas2DCtx::create_offscreen`] so nested paints composite
//! at the group's opacity envelope without the per-element
//! over-darken bug Phase 5.10 of the parent migration plan
//! flagged. Stack discipline matches `SkiaPainter`: each
//! `begin_*` / `push_*` must close before [`is_balanced`] returns
//! `true`.

use super::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOp, PathOps, Rect,
    SpriteCacheKey, Stroke, Transform, Vec2,
};
use std::cell::RefCell;
use std::collections::HashMap;

/// Abstract Canvas2D surface — the subset of the
/// `CanvasRenderingContext2d` API the painter dispatches to.
///
/// Implementations are expected to mirror Canvas2D semantics:
///
/// - `save` / `restore` push and pop the full draw state stack
///   (fill style, stroke style, line width / cap / join, miter
///   limit, global alpha, transform, clip region). The painter
///   relies on this for `push_clip` / `pop_clip` and
///   `push_transform` / `pop_transform`.
/// - `transform(a, b, c, d, e, f)` post-multiplies the active
///   transform by the matrix
///
///   ```text
///   [a c e]
///   [b d f]
///   [0 0 1]
///   ```
///
///   which maps `(x, y)` to `(a*x + c*y + e, b*x + d*y + f)`.
///   The painter converts a [`Transform`] (tiny-skia row order
///   `sx, kx, tx, ky, sy, ty`) by passing
///   `(sx, ky, kx, sy, tx, ty)`.
///
/// All coordinate, dimension, and parameter values are `f64`
/// because the JS Canvas2D ABI is `Number` (IEEE-754 double); no
/// other adapter / shim is needed beyond the painter's own
/// `f32 → f64` cast at the call site.
///
/// Methods take `&self` because every Canvas2D operation in the
/// browser ABI mutates the underlying JS object via interior
/// mutability — `web_sys` exposes the methods on `&self`. The
/// trait matches that shape so the wasm impl is a one-line
/// delegation per method.
pub trait Canvas2DCtx: Sized {
    /// Push the current draw state onto the Canvas2D state stack.
    fn save(&self);
    /// Pop the most recently pushed draw state.
    fn restore(&self);

    /// Fill the axis-aligned rectangle at `(x, y)` with the
    /// current fill style.
    fn fill_rect(&self, x: f64, y: f64, w: f64, h: f64);
    /// Stroke the axis-aligned rectangle at `(x, y)` with the
    /// current stroke style.
    fn stroke_rect(&self, x: f64, y: f64, w: f64, h: f64);

    /// Begin a new path. Subsequent `move_to` / `line_to` /
    /// curve / arc calls accumulate into the current path until
    /// `fill` / `stroke` / `clip` consume it.
    fn begin_path(&self);
    /// Close the current sub-path with a straight line back to
    /// the most recent `move_to` target.
    fn close_path(&self);
    fn move_to(&self, x: f64, y: f64);
    fn line_to(&self, x: f64, y: f64);
    fn quadratic_curve_to(&self, cx: f64, cy: f64, x: f64, y: f64);
    fn bezier_curve_to(
        &self,
        c1x: f64,
        c1y: f64,
        c2x: f64,
        c2y: f64,
        x: f64,
        y: f64,
    );
    /// Append an arc centred at `(x, y)`, radius `r`, sweeping
    /// from `start_angle` to `end_angle` (radians, CCW).
    fn arc(&self, x: f64, y: f64, r: f64, start_angle: f64, end_angle: f64);
    /// Append an axis-aligned ellipse centred at `(x, y)`,
    /// radii `(rx, ry)`, sweeping from `start_angle` to
    /// `end_angle`. `rotation` is the ellipse's own rotation
    /// (radians); the painter passes `0.0`.
    fn ellipse(
        &self,
        x: f64,
        y: f64,
        rx: f64,
        ry: f64,
        rotation: f64,
        start_angle: f64,
        end_angle: f64,
    );

    /// Fill the current path under the non-zero winding rule.
    fn fill(&self);
    /// Fill the current path under the even-odd rule.
    fn fill_even_odd(&self);
    /// Stroke the current path with the current stroke style.
    fn stroke(&self);
    /// Intersect the current clip region with the current path
    /// under the non-zero winding rule.
    fn clip(&self);
    /// Intersect the current clip region with the current path
    /// under the even-odd rule.
    fn clip_even_odd(&self);

    /// Post-multiply the current transform by the matrix
    /// `[a c e ; b d f ; 0 0 1]`. See trait docs for the
    /// per-component mapping.
    fn transform(&self, a: f64, b: f64, c: f64, d: f64, e: f64, f: f64);
    /// Replace the current transform with the matrix
    /// `[a c e ; b d f ; 0 0 1]` (absolute set, not post-
    /// multiply). Used by `end_group` to drop down to identity
    /// for the 1:1 offscreen blit, then `restore()` brings the
    /// previous transform back. Mirrors Canvas2D `setTransform`.
    fn set_transform(&self, a: f64, b: f64, c: f64, d: f64, e: f64, f: f64);

    fn set_fill_style(&self, css_color: &str);
    fn set_stroke_style(&self, css_color: &str);
    fn set_line_width(&self, w: f64);
    fn set_line_cap(&self, cap: CanvasLineCap);
    fn set_line_join(&self, join: CanvasLineJoin);
    fn set_miter_limit(&self, limit: f64);
    /// Set the surface's compositing alpha. Applies to the next
    /// `drawImage` blit and any subsequent fill / stroke
    /// operations until reset by `restore` (or another
    /// `set_global_alpha`).
    fn set_global_alpha(&self, alpha: f64);

    /// Allocate an offscreen Canvas2D surface of `(width,
    /// height)` pixels. The painter uses one offscreen per open
    /// `begin_group` so nested paints accumulate at the group's
    /// opacity envelope without per-element over-darken.
    fn create_offscreen(&self, width: u32, height: u32) -> Self;
    /// Blit `src` onto `self` at `(x, y)`. The wasm impl
    /// dispatches to Canvas2D's `drawImage` overload that takes
    /// an `OffscreenCanvas` source.
    fn draw_image_at(&self, src: &Self, x: f64, y: f64);
    /// Clear the rectangle `(x, y, w, h)` to fully-transparent
    /// black. Mirrors Canvas2D's native `clearRect` — the operation
    /// runs through the current transform, so callers that want a
    /// pixel-space clear must `set_transform(identity)` first.
    /// Used by `CanvasPainter`'s offscreen pool to recycle
    /// `begin_group` surfaces without paying a fresh
    /// `create_offscreen` allocation.
    fn clear_rect(&self, x: f64, y: f64, w: f64, h: f64);
}

/// Canvas2D `lineCap` enumeration. The wasm impl maps each to
/// its `&'static str` equivalent for the JS setter; the
/// recording mock stores the variant directly.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CanvasLineCap {
    Butt,
    Round,
    Square,
}

/// Canvas2D `lineJoin` enumeration.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CanvasLineJoin {
    Miter,
    Round,
    Bevel,
}

impl From<LineCap> for CanvasLineCap {
    fn from(c: LineCap) -> Self {
        match c {
            LineCap::Butt => CanvasLineCap::Butt,
            LineCap::Round => CanvasLineCap::Round,
            LineCap::Square => CanvasLineCap::Square,
        }
    }
}

impl From<LineJoin> for CanvasLineJoin {
    fn from(j: LineJoin) -> Self {
        match j {
            LineJoin::Miter => CanvasLineJoin::Miter,
            LineJoin::Round => CanvasLineJoin::Round,
            LineJoin::Bevel => CanvasLineJoin::Bevel,
        }
    }
}

/// Render `Color` as a Canvas2D-compatible CSS colour string.
/// Uses `rgba(...)` when the alpha is sub-unit so the JS side
/// can respect non-binary opacity without a separate
/// `globalAlpha` round-trip.
fn color_to_css(c: Color) -> String {
    if c.a >= 1.0 {
        format!("rgb({}, {}, {})", c.r, c.g, c.b)
    } else if c.a <= 0.0 {
        format!("rgba({}, {}, {}, 0)", c.r, c.g, c.b)
    } else {
        format!("rgba({}, {}, {}, {})", c.r, c.g, c.b, c.a)
    }
}

fn walk_path<C: Canvas2DCtx>(path: &PathOps, ctx: &C) {
    for op in &path.ops {
        match *op {
            PathOp::MoveTo(p) => ctx.move_to(p.x as f64, p.y as f64),
            PathOp::LineTo(p) => ctx.line_to(p.x as f64, p.y as f64),
            PathOp::QuadTo(c, p) => ctx.quadratic_curve_to(
                c.x as f64,
                c.y as f64,
                p.x as f64,
                p.y as f64,
            ),
            PathOp::CubicTo(c1, c2, p) => ctx.bezier_curve_to(
                c1.x as f64,
                c1.y as f64,
                c2.x as f64,
                c2.y as f64,
                p.x as f64,
                p.y as f64,
            ),
            PathOp::Close => ctx.close_path(),
        }
    }
}

fn walk_polygon<C: Canvas2DCtx>(vertices: &[Vec2], ctx: &C) {
    if vertices.is_empty() {
        return;
    }
    ctx.move_to(vertices[0].x as f64, vertices[0].y as f64);
    for v in &vertices[1..] {
        ctx.line_to(v.x as f64, v.y as f64);
    }
    ctx.close_path();
}

fn walk_polyline<C: Canvas2DCtx>(vertices: &[Vec2], ctx: &C) {
    if vertices.is_empty() {
        return;
    }
    ctx.move_to(vertices[0].x as f64, vertices[0].y as f64);
    for v in &vertices[1..] {
        ctx.line_to(v.x as f64, v.y as f64);
    }
}

/// Paints onto a [`Canvas2DCtx`] via the [`Painter`] trait.
///
/// The painter borrows the base Canvas2D surface for its
/// lifetime and allocates one offscreen surface per open
/// `begin_group` scope (popped + composited on `end_group`).
/// `push_clip` / `pop_clip` and `push_transform` /
/// `pop_transform` ride on Canvas2D's native `save` / `restore`
/// stack so the painter doesn't need its own clip mask Vec.
pub struct CanvasPainter<'a, C: Canvas2DCtx> {
    base: &'a C,
    width: u32,
    height: u32,
    group_stack: Vec<GroupFrame<C>>,
    clip_depth: u32,
    /// Cumulative transforms pushed via `push_transform`. Each
    /// entry is the composed transform from the painter's base
    /// surface down to that stack level. `begin_group` reads
    /// `transform_stack.last()` and replays it onto the freshly
    /// allocated offscreen so paints inside the group land at
    /// the same canvas-pixel coordinates as on the base.
    transform_stack: Vec<Transform>,
    /// Pool of reusable offscreen surfaces. `begin_group` prefers
    /// to pop a cleared entry from this pool over allocating a new
    /// one via `create_offscreen`; `end_group` returns the surface
    /// to the pool. The pool grows to the maximum concurrent group
    /// nesting depth observed during a render and then holds
    /// steady. `OFFSCREEN_POOL_CAP` bounds growth in pathological
    /// cases.
    offscreen_pool: Vec<C>,
    /// Per-render sprite cache. `stamp_cached_sprite` allocates an
    /// offscreen on the first call per `SpriteCacheKey` and blits
    /// it via `draw_image_at` for subsequent calls — Tree / Bush
    /// primitives bucket per-anchor variation into a small
    /// (≤ 256 entries per kind) variant space so the cache holds
    /// steady at a few MB even across thousands of anchors. Cache
    /// lifetime matches the painter (per-render); hoisting to
    /// session scope is a future refactor.
    sprite_cache: RefCell<HashMap<SpriteCacheKey, C>>,
}

/// Maximum number of offscreen surfaces retained in
/// `CanvasPainter::offscreen_pool` across a render. Typical nesting
/// depth observed in production is ≤ 3-4; 8 is conservative.
const OFFSCREEN_POOL_CAP: usize = 8;

struct GroupFrame<C: Canvas2DCtx> {
    offscreen: C,
    opacity: f32,
}

impl<'a, C: Canvas2DCtx> CanvasPainter<'a, C> {
    /// Construct a painter that writes onto `base`. `width` /
    /// `height` describe the active surface in CSS pixels and
    /// drive the offscreen sizes for `begin_group`.
    pub fn new(base: &'a C, width: u32, height: u32) -> Self {
        Self {
            base,
            width,
            height,
            group_stack: Vec::new(),
            clip_depth: 0,
            transform_stack: Vec::new(),
            offscreen_pool: Vec::new(),
            sprite_cache: RefCell::new(HashMap::new()),
        }
    }

    /// `true` when no `begin_group` / `push_clip` /
    /// `push_transform` is currently open. Used by the trait-
    /// conformance tests in `crate::painter::tests`.
    pub fn is_balanced(&self) -> bool {
        self.group_stack.is_empty()
            && self.clip_depth == 0
            && self.transform_stack.is_empty()
    }

    fn active_ctx(&self) -> &C {
        match self.group_stack.last() {
            Some(frame) => &frame.offscreen,
            None => self.base,
        }
    }

    fn apply_paint(ctx: &C, paint: &Paint) {
        ctx.set_fill_style(&color_to_css(paint.color));
    }

    fn apply_stroke(ctx: &C, paint: &Paint, stroke: &Stroke) {
        ctx.set_stroke_style(&color_to_css(paint.color));
        ctx.set_line_width(stroke.width as f64);
        ctx.set_line_cap(stroke.line_cap.into());
        ctx.set_line_join(stroke.line_join.into());
    }
}

impl<C: Canvas2DCtx> Painter for CanvasPainter<'_, C> {
    fn fill_rect(&mut self, rect: Rect, paint: &Paint) {
        let ctx = self.active_ctx();
        Self::apply_paint(ctx, paint);
        ctx.fill_rect(
            rect.x as f64,
            rect.y as f64,
            rect.w as f64,
            rect.h as f64,
        );
    }

    fn stroke_rect(&mut self, rect: Rect, paint: &Paint, stroke: &Stroke) {
        let ctx = self.active_ctx();
        Self::apply_stroke(ctx, paint, stroke);
        ctx.stroke_rect(
            rect.x as f64,
            rect.y as f64,
            rect.w as f64,
            rect.h as f64,
        );
    }

    fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint) {
        let ctx = self.active_ctx();
        Self::apply_paint(ctx, paint);
        ctx.begin_path();
        ctx.arc(
            cx as f64,
            cy as f64,
            r as f64,
            0.0,
            std::f64::consts::TAU,
        );
        ctx.fill();
    }

    fn fill_ellipse(
        &mut self,
        cx: f32,
        cy: f32,
        rx: f32,
        ry: f32,
        paint: &Paint,
    ) {
        let ctx = self.active_ctx();
        Self::apply_paint(ctx, paint);
        ctx.begin_path();
        ctx.ellipse(
            cx as f64,
            cy as f64,
            rx as f64,
            ry as f64,
            0.0,
            0.0,
            std::f64::consts::TAU,
        );
        ctx.fill();
    }

    fn fill_polygon(
        &mut self,
        vertices: &[Vec2],
        paint: &Paint,
        fill_rule: FillRule,
    ) {
        if vertices.is_empty() {
            return;
        }
        let ctx = self.active_ctx();
        Self::apply_paint(ctx, paint);
        ctx.begin_path();
        walk_polygon(vertices, ctx);
        match fill_rule {
            FillRule::Winding => ctx.fill(),
            FillRule::EvenOdd => ctx.fill_even_odd(),
        }
    }

    fn stroke_polyline(
        &mut self,
        vertices: &[Vec2],
        paint: &Paint,
        stroke: &Stroke,
    ) {
        if vertices.is_empty() {
            return;
        }
        let ctx = self.active_ctx();
        Self::apply_stroke(ctx, paint, stroke);
        ctx.begin_path();
        walk_polyline(vertices, ctx);
        ctx.stroke();
    }

    fn fill_path(
        &mut self,
        path: &PathOps,
        paint: &Paint,
        fill_rule: FillRule,
    ) {
        let ctx = self.active_ctx();
        Self::apply_paint(ctx, paint);
        ctx.begin_path();
        walk_path(path, ctx);
        match fill_rule {
            FillRule::Winding => ctx.fill(),
            FillRule::EvenOdd => ctx.fill_even_odd(),
        }
    }

    fn stroke_path(
        &mut self,
        path: &PathOps,
        paint: &Paint,
        stroke: &Stroke,
    ) {
        let ctx = self.active_ctx();
        Self::apply_stroke(ctx, paint, stroke);
        ctx.begin_path();
        walk_path(path, ctx);
        ctx.stroke();
    }

    // Each `begin_group` allocates a full-canvas-sized offscreen
    // (~40 MB at 3456×2880) plus an end_group `draw_image_at` blit.
    // Call sites whose fills are pairwise disjoint can pre-multiply
    // the group opacity into the fill colour and drop the wrapper
    // entirely without pixel drift — see
    // `design/begin_group_audit.md` for the classified site list
    // and `// audit: <verdict>` annotations adjacent to every
    // call site in `primitives/**` and `painter/families/**`.
    //
    // For the begin_group sites that remain (overlapping fills),
    // surface allocation is recycled through `offscreen_pool`:
    // end_group returns its surface to the pool; the next
    // begin_group pops a pre-reset surface from the pool instead
    // of allocating a fresh one. clearRect + setTransform(identity)
    // costs ~1-2 ms vs ~5-10 ms for create_offscreen at 3456×2880.
    fn begin_group(&mut self, opacity: f32) {
        let offscreen = if let Some(reused) = self.offscreen_pool.pop() {
            // Reset state: pool entries carry leftover transform
            // from the prior begin_group's `.transform()` delta;
            // identity-set before the new delta so paints inside
            // the next group land at the right canvas pixels.
            // Clear pixels to fully-transparent black to match a
            // fresh Pixmap (the painter's baseline assumption).
            reused.set_transform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0);
            reused.clear_rect(
                0.0,
                0.0,
                f64::from(self.width),
                f64::from(self.height),
            );
            reused
        } else {
            let active = self.active_ctx();
            active.create_offscreen(self.width, self.height)
        };
        // Replay the painter's cumulative transform onto the
        // offscreen so paints inside the group land at the same
        // canvas-pixel coordinates as they would on the base
        // surface. Without this the offscreen sits at identity
        // while the base still has the active push_transforms
        // applied, and paints inside the group render at IR
        // coords on the offscreen but blit back at the base's
        // transformed origin — visible as a misaligned overlay.
        if let Some(t) = self.transform_stack.last() {
            offscreen.transform(
                t.sx as f64,
                t.ky as f64,
                t.kx as f64,
                t.sy as f64,
                t.tx as f64,
                t.ty as f64,
            );
        }
        self.group_stack.push(GroupFrame { offscreen, opacity });
    }

    fn end_group(&mut self) {
        let frame = self
            .group_stack
            .pop()
            .expect("end_group without matching begin_group");
        let dst = self.active_ctx();
        dst.save();
        // Drop down to identity for the offscreen blit so the
        // source image lands 1:1 at canvas pixel (0, 0)
        // regardless of any push_transform currently active on
        // the destination. The matching `restore` below brings
        // the active transform back for subsequent paints.
        dst.set_transform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0);
        dst.set_global_alpha(frame.opacity as f64);
        dst.draw_image_at(&frame.offscreen, 0.0, 0.0);
        dst.restore();
        // Return the surface to the pool for reuse by the next
        // begin_group. The cap bounds growth in pathological
        // nesting scenarios; the typical render holds steady at
        // a few entries (the maximum concurrent nesting depth).
        if self.offscreen_pool.len() < OFFSCREEN_POOL_CAP {
            self.offscreen_pool.push(frame.offscreen);
        }
    }

    fn push_clip(&mut self, path: &PathOps, fill_rule: FillRule) {
        let ctx = self.active_ctx();
        ctx.save();
        ctx.begin_path();
        walk_path(path, ctx);
        match fill_rule {
            FillRule::Winding => ctx.clip(),
            FillRule::EvenOdd => ctx.clip_even_odd(),
        }
        self.clip_depth += 1;
    }

    fn pop_clip(&mut self) {
        let ctx = self.active_ctx();
        ctx.restore();
        self.clip_depth -= 1;
    }

    fn push_transform(&mut self, t: Transform) {
        let cumulative = match self.transform_stack.last() {
            Some(top) => top.pre_concat(t),
            None => t,
        };
        let ctx = self.active_ctx();
        ctx.save();
        // Canvas2D `transform(a, b, c, d, e, f)` post-multiplies
        // by `[a c e ; b d f ; 0 0 1]`. Our `Transform` is the
        // tiny-skia row layout `[sx kx tx ; ky sy ty]`, so the
        // arg order is `(sx, ky, kx, sy, tx, ty)`.
        ctx.transform(
            t.sx as f64,
            t.ky as f64,
            t.kx as f64,
            t.sy as f64,
            t.tx as f64,
            t.ty as f64,
        );
        self.transform_stack.push(cumulative);
    }

    fn pop_transform(&mut self) {
        let ctx = self.active_ctx();
        ctx.restore();
        self.transform_stack
            .pop()
            .expect("pop_transform without matching push_transform");
    }

    fn stamp_cached_sprite(
        &mut self,
        key: SpriteCacheKey,
        bbox: Rect,
        anchor_x: f32,
        anchor_y: f32,
        builder: &mut dyn FnMut(&mut dyn Painter),
    ) {
        let w = bbox.w as u32;
        let h = bbox.h as u32;
        if w == 0 || h == 0 {
            return;
        }
        // Cache miss → build the sprite once on a fresh offscreen
        // sized to the bbox. We split the contains_key check from
        // the insert so the &mut RefCell borrow drops before
        // builder runs (the sub-painter might re-enter the cache).
        let needs_build = !self.sprite_cache.borrow().contains_key(&key);
        if needs_build {
            let off = self.base.create_offscreen(w, h);
            {
                let mut sub = CanvasPainter::new(&off, w, h);
                builder(&mut sub);
            }
            self.sprite_cache.borrow_mut().insert(key, off);
        }
        // Cache hit → blit the cached sprite. Anchor positions the
        // bbox CENTER at (anchor_x, anchor_y); blit coords snap to
        // integer pixels to keep Canvas2D's bilinear resampler out
        // of the per-stamp hot path.
        let cache = self.sprite_cache.borrow();
        let sprite = cache.get(&key).expect("just inserted");
        let dst_x = f64::from((anchor_x - bbox.w / 2.0).round());
        let dst_y = f64::from((anchor_y - bbox.h / 2.0).round());
        self.active_ctx().draw_image_at(sprite, dst_x, dst_y);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    /// Per-context Canvas2D operation, recorded in the order the
    /// painter emits it.
    #[derive(Clone, Debug, PartialEq)]
    enum Op {
        Save,
        Restore,
        FillRect(f64, f64, f64, f64),
        StrokeRect(f64, f64, f64, f64),
        ClearRect(f64, f64, f64, f64),
        BeginPath,
        ClosePath,
        MoveTo(f64, f64),
        LineTo(f64, f64),
        QuadTo(f64, f64, f64, f64),
        CubicTo(f64, f64, f64, f64, f64, f64),
        Arc(f64, f64, f64, f64, f64),
        Ellipse(f64, f64, f64, f64, f64, f64, f64),
        Fill,
        FillEvenOdd,
        Stroke,
        Clip,
        ClipEvenOdd,
        Transform(f64, f64, f64, f64, f64, f64),
        SetTransform(f64, f64, f64, f64, f64, f64),
        SetFillStyle(String),
        SetStrokeStyle(String),
        SetLineWidth(f64),
        SetLineCap(CanvasLineCap),
        SetLineJoin(CanvasLineJoin),
        SetMiterLimit(f64),
        SetGlobalAlpha(f64),
        DrawImage(usize, f64, f64),
    }

    /// Recording mock for `Canvas2DCtx`. All instances created by
    /// `create_offscreen` share the same call log so tests can
    /// inspect the cross-context ordering (for group-opacity
    /// blits) by filtering on `(ctx_id, op)` tuples.
    #[derive(Debug)]
    struct RecCtx {
        id: usize,
        next_id: Rc<RefCell<usize>>,
        log: Rc<RefCell<Vec<(usize, Op)>>>,
    }

    impl RecCtx {
        fn new() -> Self {
            Self {
                id: 0,
                next_id: Rc::new(RefCell::new(1)),
                log: Rc::new(RefCell::new(Vec::new())),
            }
        }

        fn record(&self, op: Op) {
            self.log.borrow_mut().push((self.id, op));
        }

        fn ops(&self) -> Vec<(usize, Op)> {
            self.log.borrow().clone()
        }

        fn ops_for(&self, id: usize) -> Vec<Op> {
            self.log
                .borrow()
                .iter()
                .filter(|(ctx_id, _)| *ctx_id == id)
                .map(|(_, op)| op.clone())
                .collect()
        }
    }

    impl Canvas2DCtx for RecCtx {
        fn save(&self) {
            self.record(Op::Save);
        }
        fn restore(&self) {
            self.record(Op::Restore);
        }
        fn fill_rect(&self, x: f64, y: f64, w: f64, h: f64) {
            self.record(Op::FillRect(x, y, w, h));
        }
        fn stroke_rect(&self, x: f64, y: f64, w: f64, h: f64) {
            self.record(Op::StrokeRect(x, y, w, h));
        }
        fn begin_path(&self) {
            self.record(Op::BeginPath);
        }
        fn close_path(&self) {
            self.record(Op::ClosePath);
        }
        fn move_to(&self, x: f64, y: f64) {
            self.record(Op::MoveTo(x, y));
        }
        fn line_to(&self, x: f64, y: f64) {
            self.record(Op::LineTo(x, y));
        }
        fn quadratic_curve_to(&self, cx: f64, cy: f64, x: f64, y: f64) {
            self.record(Op::QuadTo(cx, cy, x, y));
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
            self.record(Op::CubicTo(c1x, c1y, c2x, c2y, x, y));
        }
        fn arc(&self, x: f64, y: f64, r: f64, s: f64, e: f64) {
            self.record(Op::Arc(x, y, r, s, e));
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
            self.record(Op::Ellipse(x, y, rx, ry, rot, s, e));
        }
        fn fill(&self) {
            self.record(Op::Fill);
        }
        fn fill_even_odd(&self) {
            self.record(Op::FillEvenOdd);
        }
        fn stroke(&self) {
            self.record(Op::Stroke);
        }
        fn clip(&self) {
            self.record(Op::Clip);
        }
        fn clip_even_odd(&self) {
            self.record(Op::ClipEvenOdd);
        }
        fn transform(&self, a: f64, b: f64, c: f64, d: f64, e: f64, f: f64) {
            self.record(Op::Transform(a, b, c, d, e, f));
        }
        fn set_transform(&self, a: f64, b: f64, c: f64, d: f64, e: f64, f: f64) {
            self.record(Op::SetTransform(a, b, c, d, e, f));
        }
        fn set_fill_style(&self, css: &str) {
            self.record(Op::SetFillStyle(css.to_string()));
        }
        fn set_stroke_style(&self, css: &str) {
            self.record(Op::SetStrokeStyle(css.to_string()));
        }
        fn set_line_width(&self, w: f64) {
            self.record(Op::SetLineWidth(w));
        }
        fn set_line_cap(&self, cap: CanvasLineCap) {
            self.record(Op::SetLineCap(cap));
        }
        fn set_line_join(&self, join: CanvasLineJoin) {
            self.record(Op::SetLineJoin(join));
        }
        fn set_miter_limit(&self, limit: f64) {
            self.record(Op::SetMiterLimit(limit));
        }
        fn set_global_alpha(&self, alpha: f64) {
            self.record(Op::SetGlobalAlpha(alpha));
        }
        fn create_offscreen(&self, _w: u32, _h: u32) -> Self {
            let mut next = self.next_id.borrow_mut();
            let id = *next;
            *next += 1;
            Self {
                id,
                next_id: Rc::clone(&self.next_id),
                log: Rc::clone(&self.log),
            }
        }
        fn draw_image_at(&self, src: &Self, x: f64, y: f64) {
            self.record(Op::DrawImage(src.id, x, y));
        }
        fn clear_rect(&self, x: f64, y: f64, w: f64, h: f64) {
            self.record(Op::ClearRect(x, y, w, h));
        }
    }

    fn red() -> Paint {
        Paint::solid(Color::rgb(255, 0, 0))
    }

    #[test]
    fn fill_rect_sets_style_then_fills() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 100, 100);
        p.fill_rect(Rect::new(1.0, 2.0, 3.0, 4.0), &red());
        assert_eq!(
            ctx.ops_for(0),
            vec![
                Op::SetFillStyle("rgb(255, 0, 0)".to_string()),
                Op::FillRect(1.0, 2.0, 3.0, 4.0),
            ]
        );
    }

    #[test]
    fn fill_rect_emits_rgba_for_translucent_paint() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 100, 100);
        p.fill_rect(
            Rect::new(0.0, 0.0, 1.0, 1.0),
            &Paint::solid(Color::rgba(10, 20, 30, 0.5)),
        );
        assert!(matches!(
            ctx.ops_for(0).first(),
            Some(Op::SetFillStyle(s)) if s == "rgba(10, 20, 30, 0.5)"
        ));
    }

    #[test]
    fn stroke_rect_applies_full_stroke_state() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        let stroke = Stroke {
            width: 2.5,
            line_cap: LineCap::Round,
            line_join: LineJoin::Bevel,
        };
        p.stroke_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red(), &stroke);
        assert_eq!(
            ctx.ops_for(0),
            vec![
                Op::SetStrokeStyle("rgb(255, 0, 0)".to_string()),
                Op::SetLineWidth(2.5),
                Op::SetLineCap(CanvasLineCap::Round),
                Op::SetLineJoin(CanvasLineJoin::Bevel),
                Op::StrokeRect(0.0, 0.0, 1.0, 1.0),
            ]
        );
    }

    #[test]
    fn fill_circle_emits_arc_path() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        p.fill_circle(5.0, 5.0, 3.0, &red());
        let ops = ctx.ops_for(0);
        assert_eq!(ops[0], Op::SetFillStyle("rgb(255, 0, 0)".to_string()));
        assert_eq!(ops[1], Op::BeginPath);
        match ops[2] {
            Op::Arc(x, y, r, s, e) => {
                assert_eq!((x, y, r, s), (5.0, 5.0, 3.0, 0.0));
                assert!((e - std::f64::consts::TAU).abs() < 1e-9);
            }
            ref other => panic!("expected Arc, got {other:?}"),
        }
        assert_eq!(ops[3], Op::Fill);
    }

    #[test]
    fn fill_polygon_winding_emits_fill() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        let pts = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(1.0, 0.0),
            Vec2::new(1.0, 1.0),
        ];
        p.fill_polygon(&pts, &red(), FillRule::Winding);
        assert_eq!(
            ctx.ops_for(0),
            vec![
                Op::SetFillStyle("rgb(255, 0, 0)".to_string()),
                Op::BeginPath,
                Op::MoveTo(0.0, 0.0),
                Op::LineTo(1.0, 0.0),
                Op::LineTo(1.0, 1.0),
                Op::ClosePath,
                Op::Fill,
            ]
        );
    }

    #[test]
    fn fill_polygon_even_odd_uses_evenodd_fill() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        let pts = vec![Vec2::new(0.0, 0.0), Vec2::new(1.0, 1.0)];
        p.fill_polygon(&pts, &red(), FillRule::EvenOdd);
        assert!(ctx.ops_for(0).contains(&Op::FillEvenOdd));
    }

    #[test]
    fn fill_path_walks_every_pathop_variant() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(1.0, 0.0))
            .quad_to(Vec2::new(2.0, 0.0), Vec2::new(2.0, 1.0))
            .cubic_to(
                Vec2::new(3.0, 0.0),
                Vec2::new(3.0, 1.0),
                Vec2::new(4.0, 1.0),
            )
            .close();
        p.fill_path(&path, &red(), FillRule::Winding);
        let ops = ctx.ops_for(0);
        assert_eq!(
            &ops[1..],
            &[
                Op::BeginPath,
                Op::MoveTo(0.0, 0.0),
                Op::LineTo(1.0, 0.0),
                Op::QuadTo(2.0, 0.0, 2.0, 1.0),
                Op::CubicTo(3.0, 0.0, 3.0, 1.0, 4.0, 1.0),
                Op::ClosePath,
                Op::Fill,
            ]
        );
    }

    #[test]
    fn stroke_path_emits_stroke_after_walk() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(5.0, 0.0));
        p.stroke_path(&path, &red(), &Stroke::solid(1.0));
        assert!(ctx.ops_for(0).last() == Some(&Op::Stroke));
    }

    #[test]
    fn begin_group_routes_paints_to_offscreen() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 50, 50);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.begin_group(0.5);
        p.fill_rect(Rect::new(2.0, 2.0, 1.0, 1.0), &red());
        p.end_group();
        // Fill before begin_group hits ctx 0; fill inside the
        // group hits the offscreen ctx 1; end_group blits ctx 1
        // back onto ctx 0 inside a save / set_transform-identity
        // / set_global_alpha / drawImage / restore envelope so
        // the blit lands 1:1 regardless of any push_transform
        // currently active on the destination.
        assert_eq!(
            ctx.ops_for(0),
            vec![
                Op::SetFillStyle("rgb(255, 0, 0)".to_string()),
                Op::FillRect(0.0, 0.0, 1.0, 1.0),
                Op::Save,
                Op::SetTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                Op::SetGlobalAlpha(0.5),
                Op::DrawImage(1, 0.0, 0.0),
                Op::Restore,
            ]
        );
        assert_eq!(
            ctx.ops_for(1),
            vec![
                Op::SetFillStyle("rgb(255, 0, 0)".to_string()),
                Op::FillRect(2.0, 2.0, 1.0, 1.0),
            ]
        );
    }

    #[test]
    fn nested_groups_allocate_one_offscreen_each() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 8, 8);
        p.begin_group(0.5);
        p.begin_group(0.5);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.end_group();
        p.end_group();
        // ctx 0 = base, ctx 1 = outer group, ctx 2 = inner
        // group. The inner fill lands on ctx 2; end_group #2
        // blits 2 → 1; end_group #1 blits 1 → 0.
        assert!(ctx
            .ops_for(2)
            .contains(&Op::FillRect(0.0, 0.0, 1.0, 1.0)));
        assert!(ctx.ops_for(1).contains(&Op::DrawImage(2, 0.0, 0.0)));
        assert!(ctx.ops_for(0).contains(&Op::DrawImage(1, 0.0, 0.0)));
    }

    #[test]
    fn end_group_balances_group_stack() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 4, 4);
        assert!(p.is_balanced());
        p.begin_group(0.7);
        assert!(!p.is_balanced());
        p.end_group();
        assert!(p.is_balanced());
    }

    #[test]
    #[should_panic(expected = "end_group without matching begin_group")]
    fn end_group_without_begin_panics() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 4, 4);
        p.end_group();
    }

    #[test]
    fn push_clip_uses_save_path_clip() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(5.0, 0.0))
            .line_to(Vec2::new(5.0, 5.0))
            .close();
        p.push_clip(&path, FillRule::Winding);
        assert_eq!(
            ctx.ops_for(0),
            vec![
                Op::Save,
                Op::BeginPath,
                Op::MoveTo(0.0, 0.0),
                Op::LineTo(5.0, 0.0),
                Op::LineTo(5.0, 5.0),
                Op::ClosePath,
                Op::Clip,
            ]
        );
    }

    #[test]
    fn pop_clip_emits_restore_and_decrements_depth() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0));
        p.push_clip(&path, FillRule::EvenOdd);
        p.pop_clip();
        assert!(p.is_balanced());
        let ops = ctx.ops_for(0);
        assert_eq!(ops.first(), Some(&Op::Save));
        assert!(ops.contains(&Op::ClipEvenOdd));
        assert_eq!(ops.last(), Some(&Op::Restore));
    }

    #[test]
    fn push_transform_emits_canvas2d_matrix_in_correct_order() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 10, 10);
        // tiny-skia row order: (sx, kx, tx, ky, sy, ty).
        // Canvas2D arg order: (a, b, c, d, e, f) =
        // (sx, ky, kx, sy, tx, ty).
        let t = Transform {
            sx: 2.0,
            kx: 3.0,
            tx: 4.0,
            ky: 5.0,
            sy: 6.0,
            ty: 7.0,
        };
        p.push_transform(t);
        assert_eq!(
            ctx.ops_for(0),
            vec![
                Op::Save,
                Op::Transform(2.0, 5.0, 3.0, 6.0, 4.0, 7.0),
            ]
        );
    }

    #[test]
    fn pop_transform_balances_stack() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 4, 4);
        p.push_transform(Transform::translate(2.0, 3.0));
        assert!(!p.is_balanced());
        p.pop_transform();
        assert!(p.is_balanced());
    }

    #[test]
    fn paints_inside_clip_inside_group_route_to_offscreen() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 16, 16);
        p.begin_group(0.5);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(8.0, 0.0));
        p.push_clip(&path, FillRule::Winding);
        p.fill_rect(Rect::new(0.0, 0.0, 4.0, 4.0), &red());
        p.pop_clip();
        p.end_group();
        // Clip + fill happened on ctx 1 (the group's offscreen).
        let inner = ctx.ops_for(1);
        assert!(inner.contains(&Op::Save));
        assert!(inner.contains(&Op::Clip));
        assert!(inner.contains(&Op::FillRect(0.0, 0.0, 4.0, 4.0)));
        assert!(inner.contains(&Op::Restore));
        // ctx 0 only sees the final composite.
        let outer = ctx.ops_for(0);
        assert!(outer.contains(&Op::DrawImage(1, 0.0, 0.0)));
    }

    #[test]
    fn group_opacity_records_envelope_alpha_not_per_element() {
        // Phase 5.10 invariant: two overlapping black rects under
        // begin_group(0.5) composite at one envelope blit with
        // global_alpha 0.5, NOT two per-element 0.5 fills (which
        // would over-darken the overlap toward grey 64 instead of
        // the SVG-spec grey 128).
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 16, 16);
        let black = Paint::solid(Color::rgb(0, 0, 0));
        p.begin_group(0.5);
        p.fill_rect(Rect::new(0.0, 0.0, 8.0, 8.0), &black);
        p.fill_rect(Rect::new(4.0, 4.0, 8.0, 8.0), &black);
        p.end_group();
        // Both fills carry full-alpha black on the offscreen.
        // The envelope (ctx 0) sees one blit with alpha 0.5.
        let inner = ctx.ops_for(1);
        let fill_styles: Vec<_> = inner
            .iter()
            .filter_map(|op| match op {
                Op::SetFillStyle(s) => Some(s.as_str()),
                _ => None,
            })
            .collect();
        assert_eq!(fill_styles, vec!["rgb(0, 0, 0)", "rgb(0, 0, 0)"]);
        let outer = ctx.ops_for(0);
        let alphas: Vec<_> = outer
            .iter()
            .filter_map(|op| match op {
                Op::SetGlobalAlpha(a) => Some(*a),
                _ => None,
            })
            .collect();
        assert_eq!(alphas, vec![0.5]);
        assert!(outer.contains(&Op::DrawImage(1, 0.0, 0.0)));
    }

    #[test]
    fn nested_groups_compose_alpha_via_two_envelope_blits() {
        // Two nested 0.5 groups composite as 0.5 * 0.5 = 0.25
        // effective opacity: each end_group blits at 0.5, and
        // since the outer envelope already darkened to 0.5, the
        // outer blit at 0.5 lands at 0.25 effective. Verified by
        // checking that the recorded global_alpha values are
        // both 0.5 (one per end_group), not 0.25 (which would
        // require a single combined blit).
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 8, 8);
        p.begin_group(0.5);
        p.begin_group(0.5);
        p.fill_rect(
            Rect::new(0.0, 0.0, 1.0, 1.0),
            &Paint::solid(Color::rgb(0, 0, 0)),
        );
        p.end_group();
        p.end_group();
        let outer_alphas: Vec<_> = ctx
            .ops_for(0)
            .into_iter()
            .filter_map(|op| match op {
                Op::SetGlobalAlpha(a) => Some(a),
                _ => None,
            })
            .collect();
        let inner_alphas: Vec<_> = ctx
            .ops_for(1)
            .into_iter()
            .filter_map(|op| match op {
                Op::SetGlobalAlpha(a) => Some(a),
                _ => None,
            })
            .collect();
        assert_eq!(outer_alphas, vec![0.5]);
        assert_eq!(inner_alphas, vec![0.5]);
    }

    #[test]
    fn unique_offscreen_ids_per_create_call() {
        // Sanity check on the test mock: every create_offscreen
        // hands out a fresh id so DrawImage records remain
        // unambiguous across nested groups.
        let ctx = RecCtx::new();
        let a = ctx.create_offscreen(4, 4);
        let b = ctx.create_offscreen(4, 4);
        let c = a.create_offscreen(4, 4);
        assert_ne!(a.id, b.id);
        assert_ne!(a.id, c.id);
        assert_ne!(b.id, c.id);
        // All share the same log + counter.
        assert!(Rc::ptr_eq(&a.log, &b.log));
        assert!(Rc::ptr_eq(&a.next_id, &c.next_id));
    }

    #[test]
    fn empty_polygon_is_noop() {
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 4, 4);
        p.fill_polygon(&[], &red(), FillRule::Winding);
        p.stroke_polyline(&[], &red(), &Stroke::solid(1.0));
        assert!(ctx.ops().is_empty());
    }

    #[test]
    fn begin_group_propagates_active_transform_to_offscreen() {
        // After push_transform, begin_group must replay the
        // cumulative transform onto the new offscreen so paints
        // inside the group land at the same canvas-pixel
        // coordinates as paints on the base. Without this the
        // offscreen sits at identity, paints inside the group
        // render at IR coords, and the end_group blit lands at
        // the wrong base position.
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 32, 32);
        p.push_transform(Transform::translate(10.0, 20.0));
        p.begin_group(0.5);
        p.end_group();
        p.pop_transform();
        // ctx 1 (the offscreen) should have received a Transform
        // call mirroring the active push_transform — args
        // formatted in Canvas2D order (sx, ky, kx, sy, tx, ty)
        // for a pure translate(10, 20).
        let inner = ctx.ops_for(1);
        assert!(
            inner.contains(&Op::Transform(1.0, 0.0, 0.0, 1.0, 10.0, 20.0)),
            "expected offscreen to receive replayed transform, got {inner:?}",
        );
    }

    #[test]
    fn nested_push_transform_composes_cumulative_for_offscreen() {
        // With two stacked push_transforms (translate(5, 0)
        // outer + translate(0, 7) inner), a begin_group inside
        // the inner scope should propagate the COMPOSED
        // transform translate(5, 7) — not just the inner local
        // — to the new offscreen. The painter tracks cumulative
        // transforms in its stack; this test pins the composition.
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 32, 32);
        p.push_transform(Transform::translate(5.0, 0.0));
        p.push_transform(Transform::translate(0.0, 7.0));
        p.begin_group(1.0);
        p.end_group();
        p.pop_transform();
        p.pop_transform();
        let inner = ctx.ops_for(1);
        assert!(
            inner.contains(&Op::Transform(1.0, 0.0, 0.0, 1.0, 5.0, 7.0)),
            "expected composed transform translate(5, 7), got {inner:?}",
        );
    }

    #[test]
    fn begin_group_without_active_transform_does_not_call_transform_on_offscreen() {
        // Without any push_transform, begin_group should NOT
        // emit a Transform call on the new offscreen — the
        // offscreen starts at identity which already matches the
        // base. Avoids paying for a no-op canvas state mutation
        // on every group.
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 32, 32);
        p.begin_group(1.0);
        p.end_group();
        let inner = ctx.ops_for(1);
        assert!(
            !inner.iter().any(|op| matches!(op, Op::Transform(..))),
            "expected no Transform call on offscreen, got {inner:?}",
        );
    }

    #[test]
    fn stamp_cached_sprite_caches_offscreen_per_key() {
        // Phase 3 sprite-cache gate. First stamp with a given key
        // allocates an offscreen and invokes builder; second stamp
        // with the same key reuses the cached offscreen (no new
        // create_offscreen, no second builder invocation), just
        // a fresh draw_image_at on the parent.
        use crate::painter::SpriteCacheKey;
        use std::cell::Cell;
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 32, 32);
        let key = SpriteCacheKey { kind: 1, variant: 42, size_class: 16 };
        let bbox = Rect::new(0.0, 0.0, 8.0, 8.0);
        let build_count = Cell::new(0_u32);
        let mut builder = |sub: &mut dyn Painter| {
            build_count.set(build_count.get() + 1);
            sub.fill_rect(Rect::new(0.0, 0.0, 8.0, 8.0), &red());
        };
        // First stamp — cache miss → 1 create_offscreen + 1
        // builder invocation + 1 draw_image_at on parent.
        p.stamp_cached_sprite(key, bbox, 16.0, 16.0, &mut builder);
        assert_eq!(build_count.get(), 1);
        // Second stamp at a different anchor — cache hit → no
        // additional create_offscreen, no builder invocation, just
        // a new draw_image_at on parent at the new anchor.
        p.stamp_cached_sprite(key, bbox, 20.0, 24.0, &mut builder);
        assert_eq!(build_count.get(), 1, "builder must not re-run on cache hit");

        // Exactly one offscreen allocated across both stamps.
        let offscreen_ids: std::collections::BTreeSet<usize> = ctx
            .ops()
            .iter()
            .map(|(id, _)| *id)
            .filter(|id| *id != 0)
            .collect();
        assert_eq!(offscreen_ids.len(), 1, "one sprite offscreen, got {offscreen_ids:?}");
        // Two blits on the parent, one per stamp, at the anchor-
        // centred positions: (16-4, 16-4)=(12, 12) and (20-4, 24-4)=(16, 20).
        let blits: Vec<(f64, f64)> = ctx
            .ops_for(0)
            .into_iter()
            .filter_map(|op| match op {
                Op::DrawImage(_, x, y) => Some((x, y)),
                _ => None,
            })
            .collect();
        assert_eq!(blits, vec![(12.0, 12.0), (16.0, 20.0)]);
    }

    #[test]
    fn stamp_cached_sprite_distinct_keys_allocate_separate_offscreens() {
        use crate::painter::SpriteCacheKey;
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 32, 32);
        let bbox = Rect::new(0.0, 0.0, 4.0, 4.0);
        let mut paint_once = |sub: &mut dyn Painter| {
            sub.fill_rect(Rect::new(0.0, 0.0, 4.0, 4.0), &red());
        };
        let k1 = SpriteCacheKey { kind: 1, variant: 0, size_class: 16 };
        let k2 = SpriteCacheKey { kind: 1, variant: 1, size_class: 16 };
        p.stamp_cached_sprite(k1, bbox, 10.0, 10.0, &mut paint_once);
        p.stamp_cached_sprite(k2, bbox, 10.0, 10.0, &mut paint_once);
        // Two distinct keys → two distinct offscreens.
        let offscreen_ids: std::collections::BTreeSet<usize> = ctx
            .ops()
            .iter()
            .map(|(id, _)| *id)
            .filter(|id| *id != 0)
            .collect();
        assert_eq!(offscreen_ids.len(), 2);
    }

    #[test]
    fn sequential_begin_groups_reuse_pooled_offscreen() {
        // Phase B pool gate. First begin_group allocates ctx 1
        // (pool was empty). end_group pushes ctx 1 onto the pool.
        // Second begin_group pops ctx 1, set_transform(identity)
        // + clear_rect to reset, then re-uses it. The second
        // end_group blits ctx 1 again and re-pushes onto the pool.
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 16, 16);
        p.begin_group(0.5);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.end_group();
        p.begin_group(0.5);
        p.fill_rect(Rect::new(2.0, 2.0, 1.0, 1.0), &red());
        p.end_group();
        // Exactly one offscreen ever allocated.
        let all_ids: Vec<usize> =
            ctx.ops().iter().map(|(id, _)| *id).collect();
        let unique: std::collections::BTreeSet<_> =
            all_ids.iter().copied().collect();
        assert_eq!(unique, [0, 1].into_iter().collect::<std::collections::BTreeSet<_>>());
        // Ctx 1 received the reset sequence between the two groups.
        let inner = ctx.ops_for(1);
        let reset_seq_count = inner
            .windows(2)
            .filter(|w| {
                matches!(w[0], Op::SetTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
                    && matches!(w[1], Op::ClearRect(0.0, 0.0, 16.0, 16.0))
            })
            .count();
        assert_eq!(
            reset_seq_count, 1,
            "exactly one pool-reset sequence between the two groups, got {inner:?}"
        );
        // Two blits on the parent, one per end_group.
        let blits = ctx
            .ops_for(0)
            .into_iter()
            .filter(|op| matches!(op, Op::DrawImage(1, 0.0, 0.0)))
            .count();
        assert_eq!(blits, 2);
    }

    #[test]
    fn nested_begin_groups_still_allocate_per_level() {
        // Pool reuse only kicks in for sequential groups; nested
        // groups need one offscreen per concurrent level. Two
        // nested begin_groups starting from an empty pool must
        // allocate two distinct ctx ids.
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 8, 8);
        p.begin_group(0.5);
        p.begin_group(0.5);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.end_group();
        p.end_group();
        // Three distinct ctx ids visible — base (0), outer (1),
        // inner (2). No reuse possible during the nest because
        // the outer offscreen wasn't returned to the pool yet
        // when the inner begin_group fired.
        let unique: std::collections::BTreeSet<usize> =
            ctx.ops().iter().map(|(id, _)| *id).collect();
        assert_eq!(
            unique,
            [0_usize, 1, 2].into_iter().collect::<std::collections::BTreeSet<_>>()
        );
    }

    #[test]
    fn clear_rect_records_via_rec_ctx() {
        // Phase B scaffold gate — Canvas2DCtx::clear_rect is the
        // contract the offscreen pool will rely on for recycling
        // begin_group surfaces. Confirm the recording mock captures
        // it correctly so the pool tests have something to assert
        // against in the next commit.
        let ctx = RecCtx::new();
        ctx.clear_rect(1.0, 2.0, 3.0, 4.0);
        assert_eq!(ctx.ops_for(0), vec![Op::ClearRect(1.0, 2.0, 3.0, 4.0)]);
    }

    #[test]
    fn fully_transparent_color_emits_zero_alpha_css() {
        // `Color { a: 0 }` → `rgba(_, _, _, 0)` (not "rgb(...)"):
        // matches Canvas2D's expectation that fully-transparent
        // fills render as no-ops without falling back to opaque.
        let ctx = RecCtx::new();
        let mut p = CanvasPainter::new(&ctx, 4, 4);
        p.fill_rect(
            Rect::new(0.0, 0.0, 1.0, 1.0),
            &Paint::solid(Color::rgba(255, 255, 255, 0.0)),
        );
        assert_eq!(
            ctx.ops_for(0).first(),
            Some(&Op::SetFillStyle("rgba(255, 255, 255, 0)".to_string()))
        );
    }
}
