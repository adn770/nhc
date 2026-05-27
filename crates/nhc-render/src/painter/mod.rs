//! Painter trait — Phase 2.1 of the v4e migration.
//!
//! Backend-agnostic surface for the per-primitive emitters under
//! `crate::primitives`. Three concrete impls ship in later phases:
//!
//! - `SkiaPainter` (Phase 2.2) — drives `tiny_skia::Pixmap` for
//!   the `ir_to_png` path.
//! - `SvgPainter` (Phase 2.3) — appends semantic SVG elements to
//!   a `String` buffer for the `ir_to_svg` PyO3 export.
//! - `CanvasPainter` (Phase 3.2) — drives an HTML5 Canvas2D
//!   context via wasm-bindgen for the WASM browser path.
//!
//! Phase 2.1 is additive: the trait + supporting types compile
//! and a `MockPainter` test fixture validates the contract. No
//! primitive consumes the trait yet — `primitives::*` still
//! return `Vec<String>` SVG fragments. The per-primitive ports
//! land one at a time in Phases 2.4 – 2.15.
//!
//! Surface authority: `design/map_ir_v4e.md` §7. When the design
//! and this module diverge, the design wins.

pub mod canvas;
pub mod families;
pub mod material;
pub mod raster_ctx;
pub mod skia;
pub mod svg;

#[cfg(test)]
pub(crate) mod test_util;

pub use canvas::{Canvas2DCtx, CanvasLineCap, CanvasLineJoin, CanvasPainter};
pub use material::{paint_material, Family, Material, V5_MATERIAL_FALLBACK_COLOR};
pub use raster_ctx::RasterCtx;
pub use skia::SkiaPainter;
pub use svg::SvgPainter;

/// 2D point or vector in pixel space.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    pub const fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }
}

/// Axis-aligned rectangle in pixel space.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Rect {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}

impl Rect {
    pub const fn new(x: f32, y: f32, w: f32, h: f32) -> Self {
        Self { x, y, w, h }
    }
}

/// Premultiplication-agnostic RGBA colour. RGB are u8; alpha is
/// f32 in `[0.0, 1.0]` so primitives that need sub-percent
/// opacity (shadow's `0.08`, hatch's `0.04`) preserve precision
/// across the SkiaPainter (tiny-skia takes f32 alpha) /
/// SvgPainter (SVG `fill-opacity` is float) backends. A u8 alpha
/// would round 0.08 to 20 → 20/255 = 0.0784, drifting tiny-skia
/// pixel output and the SVG output's opacity attribute.
///
/// `Eq` / `Hash` are not implemented because f32 lacks them.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Color {
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: f32,
}

impl Default for Color {
    fn default() -> Self {
        Self { r: 0, g: 0, b: 0, a: 0.0 }
    }
}

impl Color {
    pub const fn rgb(r: u8, g: u8, b: u8) -> Self {
        Self { r, g, b, a: 1.0 }
    }

    pub const fn rgba(r: u8, g: u8, b: u8, a: f32) -> Self {
        Self { r, g, b, a }
    }

    /// Returns a copy of `self` with the alpha channel replaced by
    /// `a`. Used by patterns whose fills don't overlap inside a
    /// `begin_group(opacity)` envelope — pre-multiplying `opacity`
    /// into the fill's alpha lands the same pixels as the group
    /// composite while eliminating the per-call offscreen
    /// allocation. See `design/begin_group_audit.md` for which
    /// `begin_group` call sites this transformation is safe at.
    pub const fn with_alpha(self, a: f32) -> Self {
        Self { a, ..self }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum LineCap {
    #[default]
    Butt,
    Round,
    Square,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum LineJoin {
    #[default]
    Miter,
    Round,
    Bevel,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum FillRule {
    #[default]
    Winding,
    EvenOdd,
}

/// Solid-colour paint. Future extensions (gradients, patterns)
/// land as additional variants without breaking the existing
/// trait surface.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Paint {
    pub color: Color,
}

impl Paint {
    pub const fn solid(color: Color) -> Self {
        Self { color }
    }
}

/// Stroke parameters. `width` is in pixels.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Stroke {
    pub width: f32,
    pub line_cap: LineCap,
    pub line_join: LineJoin,
}

impl Default for Stroke {
    fn default() -> Self {
        Self { width: 1.0, line_cap: LineCap::default(), line_join: LineJoin::default() }
    }
}

impl Stroke {
    pub const fn solid(width: f32) -> Self {
        Self { width, line_cap: LineCap::Butt, line_join: LineJoin::Miter }
    }
}

/// 2D affine transform, encoded as a 3x2 matrix in tiny-skia's
/// row order. The full 3x3 matrix is
///
/// ```text
/// [sx kx tx]
/// [ky sy ty]
/// [0  0  1 ]
/// ```
///
/// so a point `(x, y)` maps to
/// `(sx*x + kx*y + tx, ky*x + sy*y + ty)`. Field layout matches
/// `tiny_skia::Transform` so the SkiaPainter conversion is a
/// direct field copy.
///
/// `rotate(angle_rad)` takes **radians** (CCW); the SkiaPainter
/// converts to degrees internally for `tiny_skia::Transform`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Transform {
    pub sx: f32,
    pub kx: f32,
    pub tx: f32,
    pub ky: f32,
    pub sy: f32,
    pub ty: f32,
}

impl Default for Transform {
    fn default() -> Self {
        Self::identity()
    }
}

impl Transform {
    pub const fn identity() -> Self {
        Self { sx: 1.0, kx: 0.0, tx: 0.0, ky: 0.0, sy: 1.0, ty: 0.0 }
    }

    pub const fn translate(dx: f32, dy: f32) -> Self {
        Self { sx: 1.0, kx: 0.0, tx: dx, ky: 0.0, sy: 1.0, ty: dy }
    }

    pub const fn scale(sx: f32, sy: f32) -> Self {
        Self { sx, kx: 0.0, tx: 0.0, ky: 0.0, sy, ty: 0.0 }
    }

    /// Rotation by `angle_rad` radians, CCW around the origin.
    pub fn rotate(angle_rad: f32) -> Self {
        let c = angle_rad.cos();
        let s = angle_rad.sin();
        Self { sx: c, kx: -s, tx: 0.0, ky: s, sy: c, ty: 0.0 }
    }

    /// Rotation by `angle_rad` radians, CCW around `(cx, cy)`.
    pub fn rotate_around(angle_rad: f32, cx: f32, cy: f32) -> Self {
        Self::translate(cx, cy)
            .pre_concat(Self::rotate(angle_rad))
            .pre_concat(Self::translate(-cx, -cy))
    }

    /// Matrix product `self * other`. Equivalent to
    /// `tiny_skia::Transform::pre_concat`.
    pub fn pre_concat(self, other: Transform) -> Transform {
        Transform {
            sx: self.sx * other.sx + self.kx * other.ky,
            kx: self.sx * other.kx + self.kx * other.sy,
            tx: self.sx * other.tx + self.kx * other.ty + self.tx,
            ky: self.ky * other.sx + self.sy * other.ky,
            sy: self.ky * other.kx + self.sy * other.sy,
            ty: self.ky * other.tx + self.sy * other.ty + self.ty,
        }
    }
}

/// Atomic path command. Mirrors the SVG `M` / `L` / `Q` / `C`
/// / `Z` repertoire that every backend natively supports.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PathOp {
    MoveTo(Vec2),
    LineTo(Vec2),
    QuadTo(Vec2, Vec2),
    CubicTo(Vec2, Vec2, Vec2),
    Close,
}

/// Backend-agnostic path. Builders push `PathOp`s; backends walk
/// the sequence and emit their native primitive (`tiny_skia::Path`
/// / SVG `<path d="…">` / Canvas2D `lineTo` calls).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PathOps {
    pub ops: Vec<PathOp>,
}

impl PathOps {
    pub fn new() -> Self {
        Self { ops: Vec::new() }
    }

    pub fn with_capacity(cap: usize) -> Self {
        Self { ops: Vec::with_capacity(cap) }
    }

    pub fn move_to(&mut self, p: Vec2) -> &mut Self {
        self.ops.push(PathOp::MoveTo(p));
        self
    }

    pub fn line_to(&mut self, p: Vec2) -> &mut Self {
        self.ops.push(PathOp::LineTo(p));
        self
    }

    pub fn quad_to(&mut self, c: Vec2, p: Vec2) -> &mut Self {
        self.ops.push(PathOp::QuadTo(c, p));
        self
    }

    pub fn cubic_to(&mut self, c1: Vec2, c2: Vec2, p: Vec2) -> &mut Self {
        self.ops.push(PathOp::CubicTo(c1, c2, p));
        self
    }

    pub fn close(&mut self) -> &mut Self {
        self.ops.push(PathOp::Close);
        self
    }

    pub fn is_empty(&self) -> bool {
        self.ops.is_empty()
    }

    pub fn len(&self) -> usize {
        self.ops.len()
    }
}

/// Backend-agnostic raster surface.
///
/// Each method takes `&mut self` and is expected to be called in
/// document (paint) order. `begin_group` / `end_group` pairs and
/// `push_clip` / `pop_clip` pairs are stack-disciplined: each
/// open scope must close before the surface is consumed.
///
/// See `design/map_ir_v4e.md` §7 for the canonical surface and
/// per-backend implementation notes.
pub trait Painter {
    fn fill_rect(&mut self, rect: Rect, paint: &Paint);
    fn stroke_rect(&mut self, rect: Rect, paint: &Paint, stroke: &Stroke);
    fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint);
    fn fill_ellipse(&mut self, cx: f32, cy: f32, rx: f32, ry: f32, paint: &Paint);
    fn fill_polygon(&mut self, vertices: &[Vec2], paint: &Paint, fill_rule: FillRule);
    fn stroke_polyline(&mut self, vertices: &[Vec2], paint: &Paint, stroke: &Stroke);
    fn fill_path(&mut self, path: &PathOps, paint: &Paint, fill_rule: FillRule);
    fn stroke_path(&mut self, path: &PathOps, paint: &Paint, stroke: &Stroke);

    /// Begin a group-opacity scope. Paints rendered between this
    /// and the matching `end_group` composite as one image at
    /// `opacity`, matching SVG `<g opacity="…">` semantics. Lifts
    /// the offscreen-buffer mechanism from
    /// `transform/png/fragment.rs::paint_offscreen_group` (see
    /// Phase 5.10 of the parent migration plan — group opacity is
    /// load-bearing for the twelve overlapping-stamp primitives).
    fn begin_group(&mut self, opacity: f32);
    fn end_group(&mut self);

    /// Push a clip region. Subsequent paints are masked by the
    /// path. Nested `push_clip` calls intersect with the current
    /// clip stack. Used by region-keyed per-tile ops (see v4e §5
    /// "Region-clipped per-tile ops").
    fn push_clip(&mut self, path: &PathOps, fill_rule: FillRule);
    fn pop_clip(&mut self);

    /// Push a transform onto the current transform stack. Subsequent
    /// paint calls render under the cumulative transform (base *
    /// stack product, top-of-stack last applied). Used for rotate-
    /// around-pivot per-edge runs (Masonry, Palisade, Fortification
    /// in `transform/png/building_exterior_wall.rs` +
    /// `transform/png/enclosure.rs`) and any other case where a
    /// sub-block of paint calls shares a non-trivial transform.
    fn push_transform(&mut self, transform: Transform);
    fn pop_transform(&mut self);

    /// Stamp a (cached) sprite at `(anchor_x, anchor_y)`.
    /// `bbox.w x bbox.h` is the sprite's pixel-aligned bounding
    /// box; backends that maintain a per-render sprite cache
    /// (currently only `CanvasPainter`) allocate an offscreen of
    /// those dimensions on the first stamp with a given `key` and
    /// blit it via `draw_image_at` for subsequent stamps —
    /// collapsing N similar emissions (e.g. trees sharing a shape
    /// bucket) to 1 build + N blits.
    ///
    /// `builder` is invoked ONCE per cache miss to paint the
    /// sprite at `(0, 0)` on the offscreen. The blit anchors the
    /// bbox CENTER at `(anchor_x, anchor_y)` on the destination
    /// surface. Backends without a cache (SkiaPainter / SvgPainter
    /// / MockPainter) call `builder` directly at the active
    /// surface, ignoring the cache key — same pixel output as a
    /// per-anchor inline emission.
    ///
    /// No default impl: each Painter type provides its own body
    /// (typically delegating to [`stamp_cached_sprite_default`]).
    /// The closure receives `&mut dyn Painter` so it can route
    /// through the same trait surface; coercing `&mut Self`
    /// (where Self may be unsized via `dyn Painter`) is the
    /// reason this can't carry a trait-default body.
    fn stamp_cached_sprite(
        &mut self,
        key: SpriteCacheKey,
        bbox: Rect,
        anchor_x: f32,
        anchor_y: f32,
        builder: &mut dyn FnMut(&mut dyn Painter),
    );

    /// Push a color filter onto the painter's filter stack.
    /// Subsequent paint operations (fill / stroke / sprite blit)
    /// render with the cumulative filter applied; `pop_filter`
    /// reverts to the prior state. Default impl is a no-op for
    /// backends that don't support filters (e.g. test mocks);
    /// the production backends (SkiaPainter, SvgPainter,
    /// CanvasPainter) override.
    fn push_filter(&mut self, filter: PainterFilter) {
        let _ = filter;
    }

    /// Pop the most recently pushed filter. No-op on backends
    /// that don't support filters.
    fn pop_filter(&mut self) {}
}

/// Color-space filter applied to subsequent paint operations.
///
/// `CanvasPainter` forwards filters to the Canvas2D `filter`
/// CSS string; `SkiaPainter` / `SvgPainter` / `RasterCtx`
/// hand-roll the HSL math and apply to paint colours at draw
/// time. The two paths approximate the same effect within ~1 LSB
/// on the PSNR ≥ 50 dB gate.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PainterFilter {
    /// HSL shift — rotate hue by `h_deg` degrees, multiply
    /// saturation by `s_mul`, multiply lightness by `l_mul`. The
    /// per-anchor tint Tree / Bush use for inter-instance
    /// variation among bucketed shape templates (Phase 3 of
    /// `plans/wasm-render-caching.md`).
    HslShift {
        h_deg: f32,
        s_mul: f32,
        l_mul: f32,
    },
}

impl PainterFilter {
    /// CSS filter string equivalent — matches Canvas2D's
    /// `ctx.filter = "..."` syntax. CSS doesn't have a direct
    /// "HSL shift" filter, so we compose `hue-rotate(deg)
    /// saturate(mul) brightness(mul)`. Matches Canvas2D's
    /// matrix-based hue-rotate within ~1 LSB of HSL-space
    /// rotation on saturated test fixtures.
    pub fn as_css_string(&self) -> String {
        match self {
            PainterFilter::HslShift { h_deg, s_mul, l_mul } => format!(
                "hue-rotate({h_deg}deg) saturate({s_mul:.4}) brightness({l_mul:.4})",
            ),
        }
    }

    /// Apply the filter to a `Color` via hand-rolled HSL math.
    /// Used by every backend except `CanvasPainter` (which
    /// forwards to the JS compositor via [`Self::as_css_string`]).
    pub fn apply_to_color(&self, c: Color) -> Color {
        match self {
            PainterFilter::HslShift { h_deg, s_mul, l_mul } => {
                let (h, s, l) = rgb_to_hsl(c.r, c.g, c.b);
                let new_h =
                    ((h + h_deg / 360.0).fract() + 1.0).fract();
                let new_s = (s * s_mul).clamp(0.0, 1.0);
                let new_l = (l * l_mul).clamp(0.0, 1.0);
                let (r, g, b) = hsl_to_rgb(new_h, new_s, new_l);
                Color { r, g, b, a: c.a }
            }
        }
    }
}

/// Apply a stack of filters to a colour, in push order.
pub fn apply_filter_stack(c: Color, stack: &[PainterFilter]) -> Color {
    stack.iter().fold(c, |acc, f| f.apply_to_color(acc))
}

/// Convert an `(r, g, b)` triple in `[0, 255]` to `(h, s, l)` in
/// `[0, 1]`. Standard HSL formula.
pub fn rgb_to_hsl(r: u8, g: u8, b: u8) -> (f32, f32, f32) {
    let rf = f32::from(r) / 255.0;
    let gf = f32::from(g) / 255.0;
    let bf = f32::from(b) / 255.0;
    let max = rf.max(gf).max(bf);
    let min = rf.min(gf).min(bf);
    let l = (max + min) * 0.5;
    let delta = max - min;
    if delta < 1e-6 {
        return (0.0, 0.0, l);
    }
    let s = if l < 0.5 {
        delta / (max + min)
    } else {
        delta / (2.0 - max - min)
    };
    let h = if max == rf {
        ((gf - bf) / delta + if gf < bf { 6.0 } else { 0.0 }) / 6.0
    } else if max == gf {
        ((bf - rf) / delta + 2.0) / 6.0
    } else {
        ((rf - gf) / delta + 4.0) / 6.0
    };
    (h, s, l)
}

/// Convert `(h, s, l)` in `[0, 1]` back to `(r, g, b)` in
/// `[0, 255]`. Inverse of [`rgb_to_hsl`].
pub fn hsl_to_rgb(h: f32, s: f32, l: f32) -> (u8, u8, u8) {
    if s < 1e-6 {
        let v = (l * 255.0).round().clamp(0.0, 255.0) as u8;
        return (v, v, v);
    }
    let q = if l < 0.5 { l * (1.0 + s) } else { l + s - l * s };
    let p = 2.0 * l - q;
    let r = hue_to_rgb(p, q, h + 1.0 / 3.0);
    let g = hue_to_rgb(p, q, h);
    let b = hue_to_rgb(p, q, h - 1.0 / 3.0);
    let to_u8 = |v: f32| (v * 255.0).round().clamp(0.0, 255.0) as u8;
    (to_u8(r), to_u8(g), to_u8(b))
}

fn hue_to_rgb(p: f32, q: f32, mut t: f32) -> f32 {
    if t < 0.0 {
        t += 1.0;
    }
    if t > 1.0 {
        t -= 1.0;
    }
    if t < 1.0 / 6.0 {
        return p + (q - p) * 6.0 * t;
    }
    if t < 0.5 {
        return q;
    }
    if t < 2.0 / 3.0 {
        return p + (q - p) * (2.0 / 3.0 - t) * 6.0;
    }
    p
}

/// Key into the per-render sprite cache.
///
/// Two `stamp_cached_sprite` calls with the same key share an
/// offscreen; primitive callers bucket per-anchor variations into
/// a fixed `variant` count (e.g. `TREE_SHAPE_BUCKET_COUNT = 256`
/// templates per Tree kind) so the working set stays bounded.
#[derive(Hash, Eq, PartialEq, Clone, Copy, Debug)]
pub struct SpriteCacheKey {
    /// Discriminant of the fixture kind (Tree, Bush, …).
    pub kind: u32,
    /// Within-kind variant id — typically a quantised hash of
    /// per-anchor geometric inputs.
    pub variant: u32,
    /// Cell-aligned size class. Lets the same `kind` carry
    /// multiple sprite atlases (small / medium / large) without
    /// collision-coding.
    pub size_class: u8,
}

/// Default body for `Painter::stamp_cached_sprite`. Backends that
/// don't maintain a sprite cache (SkiaPainter / SvgPainter /
/// MockPainter) delegate here — the helper ignores the key, bbox,
/// and anchor and just hands the painter to `builder`. Free
/// function (not a method) so `&mut dyn Painter` works directly
/// without a `?Sized → Sized` coercion.
pub fn stamp_cached_sprite_default(
    painter: &mut dyn Painter,
    key: SpriteCacheKey,
    bbox: Rect,
    anchor_x: f32,
    anchor_y: f32,
    builder: &mut dyn FnMut(&mut dyn Painter),
) {
    let _ = (key, bbox, anchor_x, anchor_y);
    builder(painter);
}

#[cfg(test)]
mod tests {
    use super::test_util::{MockPainter, PainterCall as Call};
    use super::*;

    #[test]
    fn painter_filter_identity_is_noop() {
        let c = Color::rgb(120, 60, 200);
        let f = PainterFilter::HslShift {
            h_deg: 0.0,
            s_mul: 1.0,
            l_mul: 1.0,
        };
        let result = f.apply_to_color(c);
        // Identity filter — within 1 LSB of the original colour
        // (rgb_to_hsl/hsl_to_rgb round-trips slightly).
        assert!((result.r as i32 - c.r as i32).abs() <= 1);
        assert!((result.g as i32 - c.g as i32).abs() <= 1);
        assert!((result.b as i32 - c.b as i32).abs() <= 1);
    }

    #[test]
    fn painter_filter_180_degree_hue_rotates_to_complement() {
        // Pure red (255, 0, 0) → 180° hue rotation → cyan (0, 255, 255).
        // HSL math is exact at the 180° point.
        let red_c = Color::rgb(255, 0, 0);
        let f = PainterFilter::HslShift {
            h_deg: 180.0,
            s_mul: 1.0,
            l_mul: 1.0,
        };
        let result = f.apply_to_color(red_c);
        assert!((result.r as i32 - 0).abs() <= 1);
        assert!((result.g as i32 - 255).abs() <= 1);
        assert!((result.b as i32 - 255).abs() <= 1);
    }

    #[test]
    fn painter_filter_as_css_string_matches_format() {
        let f = PainterFilter::HslShift {
            h_deg: 15.0,
            s_mul: 1.05,
            l_mul: 0.95,
        };
        let css = f.as_css_string();
        assert!(css.contains("hue-rotate(15deg)"));
        assert!(css.contains("saturate(1.05"));
        assert!(css.contains("brightness(0.95"));
    }

    #[test]
    fn apply_filter_stack_composes_in_order() {
        // Two filters stacked: first rotates 60°, second rotates
        // another 60° → cumulative 120°.
        let c = Color::rgb(255, 0, 0);
        let stack = [
            PainterFilter::HslShift {
                h_deg: 60.0,
                s_mul: 1.0,
                l_mul: 1.0,
            },
            PainterFilter::HslShift {
                h_deg: 60.0,
                s_mul: 1.0,
                l_mul: 1.0,
            },
        ];
        let result = apply_filter_stack(c, &stack);
        // 120° from red → green (0, 255, 0).
        assert!((result.r as i32 - 0).abs() <= 1);
        assert!((result.g as i32 - 255).abs() <= 1);
        assert!((result.b as i32 - 0).abs() <= 1);
    }

    fn red() -> Paint {
        Paint::solid(Color::rgb(255, 0, 0))
    }

    #[test]
    fn fill_rect_records_call() {
        let mut p = MockPainter::default();
        p.fill_rect(Rect::new(1.0, 2.0, 3.0, 4.0), &red());
        assert_eq!(p.calls.len(), 1);
        assert_eq!(p.calls[0], Call::FillRect(Rect::new(1.0, 2.0, 3.0, 4.0), red()));
    }

    #[test]
    fn stroke_rect_records_paint_and_stroke() {
        let mut p = MockPainter::default();
        let stroke = Stroke::solid(2.0);
        p.stroke_rect(Rect::new(0.0, 0.0, 10.0, 10.0), &red(), &stroke);
        assert_eq!(p.calls.len(), 1);
        assert_eq!(p.calls[0], Call::StrokeRect(Rect::new(0.0, 0.0, 10.0, 10.0), red(), stroke));
    }

    #[test]
    fn fill_circle_and_ellipse_record_geometry() {
        let mut p = MockPainter::default();
        p.fill_circle(5.0, 6.0, 3.0, &red());
        p.fill_ellipse(7.0, 8.0, 4.0, 2.0, &red());
        assert_eq!(p.calls.len(), 2);
        assert_eq!(p.calls[0], Call::FillCircle(5.0, 6.0, 3.0, red()));
        assert_eq!(p.calls[1], Call::FillEllipse(7.0, 8.0, 4.0, 2.0, red()));
    }

    #[test]
    fn fill_polygon_clones_vertices() {
        let mut p = MockPainter::default();
        let verts = [Vec2::new(0.0, 0.0), Vec2::new(1.0, 0.0), Vec2::new(0.0, 1.0)];
        p.fill_polygon(&verts, &red(), FillRule::EvenOdd);
        assert_eq!(p.calls.len(), 1);
        assert_eq!(
            p.calls[0],
            Call::FillPolygon(verts.to_vec(), red(), FillRule::EvenOdd)
        );
    }

    #[test]
    fn stroke_polyline_records_stroke() {
        let mut p = MockPainter::default();
        let stroke = Stroke {
            width: 1.5,
            line_cap: LineCap::Round,
            line_join: LineJoin::Bevel,
        };
        let verts = [Vec2::new(0.0, 0.0), Vec2::new(10.0, 10.0)];
        p.stroke_polyline(&verts, &red(), &stroke);
        assert_eq!(p.calls.len(), 1);
        assert_eq!(p.calls[0], Call::StrokePolyline(verts.to_vec(), red(), stroke));
    }

    #[test]
    fn path_ops_builder_pushes_in_order() {
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(10.0, 0.0))
            .cubic_to(Vec2::new(10.0, 5.0), Vec2::new(5.0, 10.0), Vec2::new(0.0, 10.0))
            .quad_to(Vec2::new(0.0, 5.0), Vec2::new(0.0, 0.0))
            .close();
        assert_eq!(path.len(), 5);
        assert_eq!(path.ops[0], PathOp::MoveTo(Vec2::new(0.0, 0.0)));
        assert_eq!(path.ops[1], PathOp::LineTo(Vec2::new(10.0, 0.0)));
        assert_eq!(
            path.ops[2],
            PathOp::CubicTo(Vec2::new(10.0, 5.0), Vec2::new(5.0, 10.0), Vec2::new(0.0, 10.0))
        );
        assert_eq!(
            path.ops[3],
            PathOp::QuadTo(Vec2::new(0.0, 5.0), Vec2::new(0.0, 0.0))
        );
        assert_eq!(path.ops[4], PathOp::Close);
    }

    #[test]
    fn fill_path_and_stroke_path_carry_path_ops() {
        let mut p = MockPainter::default();
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(1.0, 1.0)).close();
        p.fill_path(&path, &red(), FillRule::Winding);
        p.stroke_path(&path, &red(), &Stroke::solid(2.0));
        assert_eq!(p.calls.len(), 2);
        assert_eq!(p.calls[0], Call::FillPath(path.clone(), red(), FillRule::Winding));
        assert_eq!(p.calls[1], Call::StrokePath(path, red(), Stroke::solid(2.0)));
    }

    #[test]
    fn group_calls_balance_and_track_depth() {
        let mut p = MockPainter::default();
        p.begin_group(0.5);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.begin_group(0.5);
        p.fill_rect(Rect::new(1.0, 1.0, 1.0, 1.0), &red());
        p.end_group();
        p.end_group();

        assert_eq!(p.group_depth, 0, "begin/end pairs must balance");
        assert_eq!(p.max_group_depth, 2, "nested begin_group must record max depth");
        assert_eq!(p.calls.len(), 6);
        assert_eq!(p.calls[0], Call::BeginGroup(0.5));
        assert_eq!(p.calls[2], Call::BeginGroup(0.5));
        assert_eq!(p.calls[4], Call::EndGroup);
        assert_eq!(p.calls[5], Call::EndGroup);
    }

    #[test]
    fn clip_calls_balance_and_track_depth() {
        let mut p = MockPainter::default();
        let mut clip_a = PathOps::new();
        clip_a.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(10.0, 0.0))
            .line_to(Vec2::new(10.0, 10.0))
            .close();
        let mut clip_b = PathOps::new();
        clip_b.move_to(Vec2::new(2.0, 2.0))
            .line_to(Vec2::new(8.0, 2.0))
            .line_to(Vec2::new(8.0, 8.0))
            .close();

        p.push_clip(&clip_a, FillRule::EvenOdd);
        p.fill_rect(Rect::new(0.0, 0.0, 10.0, 10.0), &red());
        p.push_clip(&clip_b, FillRule::Winding);
        p.fill_rect(Rect::new(0.0, 0.0, 10.0, 10.0), &red());
        p.pop_clip();
        p.pop_clip();

        assert_eq!(p.clip_depth, 0, "push/pop pairs must balance");
        assert_eq!(p.max_clip_depth, 2, "nested push_clip must record max depth");
        assert_eq!(p.calls.len(), 6);
        assert_eq!(p.calls[0], Call::PushClip(clip_a, FillRule::EvenOdd));
        assert_eq!(p.calls[2], Call::PushClip(clip_b, FillRule::Winding));
        assert_eq!(p.calls[4], Call::PopClip);
        assert_eq!(p.calls[5], Call::PopClip);
    }

    #[test]
    fn group_and_clip_can_interleave() {
        let mut p = MockPainter::default();
        let mut clip = PathOps::new();
        clip.move_to(Vec2::new(0.0, 0.0)).line_to(Vec2::new(1.0, 1.0)).close();

        p.begin_group(0.5);
        p.push_clip(&clip, FillRule::Winding);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.pop_clip();
        p.end_group();

        assert_eq!(p.group_depth, 0);
        assert_eq!(p.clip_depth, 0);
        assert_eq!(p.calls.len(), 5);
        assert!(matches!(p.calls[0], Call::BeginGroup(_)));
        assert!(matches!(p.calls[1], Call::PushClip(_, _)));
        assert!(matches!(p.calls[2], Call::FillRect(_, _)));
        assert!(matches!(p.calls[3], Call::PopClip));
        assert!(matches!(p.calls[4], Call::EndGroup));
    }

    #[test]
    fn push_transform_calls_balance_and_track_depth() {
        let mut p = MockPainter::default();
        let t1 = Transform::translate(10.0, 0.0);
        let t2 = Transform::translate(0.0, 5.0);
        p.push_transform(t1);
        p.fill_rect(Rect::new(0.0, 0.0, 1.0, 1.0), &red());
        p.push_transform(t2);
        p.fill_rect(Rect::new(1.0, 1.0, 1.0, 1.0), &red());
        p.pop_transform();
        p.pop_transform();

        assert_eq!(p.transform_depth, 0, "push/pop pairs must balance");
        assert_eq!(
            p.max_transform_depth, 2,
            "nested push_transform must record max depth"
        );
        assert_eq!(p.calls.len(), 6);
        assert_eq!(p.calls[0], Call::PushTransform(t1));
        assert_eq!(p.calls[2], Call::PushTransform(t2));
        assert_eq!(p.calls[4], Call::PopTransform);
        assert_eq!(p.calls[5], Call::PopTransform);
    }

    #[test]
    fn transform_identity_is_neutral_under_pre_concat() {
        let t = Transform::translate(3.0, 4.0);
        assert_eq!(Transform::identity().pre_concat(t), t);
        assert_eq!(t.pre_concat(Transform::identity()), t);
    }

    #[test]
    fn transform_translate_compose_via_pre_concat() {
        let a = Transform::translate(10.0, 0.0);
        let b = Transform::translate(0.0, 5.0);
        let composed = a.pre_concat(b);
        assert_eq!(composed, Transform::translate(10.0, 5.0));
    }

    #[test]
    fn transform_rotate_around_pivot_keeps_pivot_fixed() {
        // Rotating 90 deg CCW around (10, 10) maps (10, 10) -> (10, 10).
        let t = Transform::rotate_around(std::f32::consts::FRAC_PI_2, 10.0, 10.0);
        let (x, y) = (10.0_f32, 10.0_f32);
        let mx = t.sx * x + t.kx * y + t.tx;
        let my = t.ky * x + t.sy * y + t.ty;
        assert!((mx - 10.0).abs() < 1e-4, "pivot x drifted: {mx}");
        assert!((my - 10.0).abs() < 1e-4, "pivot y drifted: {my}");
    }

    #[test]
    fn paint_constructors_set_color_and_alpha() {
        let opaque = Paint::solid(Color::rgb(10, 20, 30));
        assert_eq!(opaque.color, Color { r: 10, g: 20, b: 30, a: 1.0 });
        let translucent = Paint::solid(Color::rgba(10, 20, 30, 0.25));
        assert_eq!(translucent.color, Color { r: 10, g: 20, b: 30, a: 0.25 });
    }

    #[test]
    fn stroke_default_is_one_pixel_butt_miter() {
        let s = Stroke::default();
        assert_eq!(s.width, 1.0);
        assert_eq!(s.line_cap, LineCap::Butt);
        assert_eq!(s.line_join, LineJoin::Miter);
    }
}
