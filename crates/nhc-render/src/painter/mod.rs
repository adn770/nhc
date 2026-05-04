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

pub mod skia;
pub mod svg;

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
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Records every `Painter` call for assertion in unit tests.
    /// Used as a behavioural fixture for trait-conformance checks
    /// before the SkiaPainter / SvgPainter impls land.
    #[derive(Debug, Default)]
    struct MockPainter {
        calls: Vec<Call>,
        group_depth: i32,
        clip_depth: i32,
        transform_depth: i32,
        max_group_depth: i32,
        max_clip_depth: i32,
        max_transform_depth: i32,
    }

    #[derive(Debug, PartialEq)]
    enum Call {
        FillRect(Rect, Paint),
        StrokeRect(Rect, Paint, Stroke),
        FillCircle(f32, f32, f32, Paint),
        FillEllipse(f32, f32, f32, f32, Paint),
        FillPolygon(Vec<Vec2>, Paint, FillRule),
        StrokePolyline(Vec<Vec2>, Paint, Stroke),
        FillPath(PathOps, Paint, FillRule),
        StrokePath(PathOps, Paint, Stroke),
        BeginGroup(f32),
        EndGroup,
        PushClip(PathOps, FillRule),
        PopClip,
        PushTransform(Transform),
        PopTransform,
    }

    impl Painter for MockPainter {
        fn fill_rect(&mut self, rect: Rect, paint: &Paint) {
            self.calls.push(Call::FillRect(rect, *paint));
        }
        fn stroke_rect(&mut self, rect: Rect, paint: &Paint, stroke: &Stroke) {
            self.calls.push(Call::StrokeRect(rect, *paint, *stroke));
        }
        fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint) {
            self.calls.push(Call::FillCircle(cx, cy, r, *paint));
        }
        fn fill_ellipse(&mut self, cx: f32, cy: f32, rx: f32, ry: f32, paint: &Paint) {
            self.calls.push(Call::FillEllipse(cx, cy, rx, ry, *paint));
        }
        fn fill_polygon(&mut self, vertices: &[Vec2], paint: &Paint, fill_rule: FillRule) {
            self.calls.push(Call::FillPolygon(vertices.to_vec(), *paint, fill_rule));
        }
        fn stroke_polyline(&mut self, vertices: &[Vec2], paint: &Paint, stroke: &Stroke) {
            self.calls.push(Call::StrokePolyline(vertices.to_vec(), *paint, *stroke));
        }
        fn fill_path(&mut self, path: &PathOps, paint: &Paint, fill_rule: FillRule) {
            self.calls.push(Call::FillPath(path.clone(), *paint, fill_rule));
        }
        fn stroke_path(&mut self, path: &PathOps, paint: &Paint, stroke: &Stroke) {
            self.calls.push(Call::StrokePath(path.clone(), *paint, *stroke));
        }
        fn begin_group(&mut self, opacity: f32) {
            self.group_depth += 1;
            if self.group_depth > self.max_group_depth {
                self.max_group_depth = self.group_depth;
            }
            self.calls.push(Call::BeginGroup(opacity));
        }
        fn end_group(&mut self) {
            self.group_depth -= 1;
            self.calls.push(Call::EndGroup);
        }
        fn push_clip(&mut self, path: &PathOps, fill_rule: FillRule) {
            self.clip_depth += 1;
            if self.clip_depth > self.max_clip_depth {
                self.max_clip_depth = self.clip_depth;
            }
            self.calls.push(Call::PushClip(path.clone(), fill_rule));
        }
        fn pop_clip(&mut self) {
            self.clip_depth -= 1;
            self.calls.push(Call::PopClip);
        }
        fn push_transform(&mut self, transform: Transform) {
            self.transform_depth += 1;
            if self.transform_depth > self.max_transform_depth {
                self.max_transform_depth = self.transform_depth;
            }
            self.calls.push(Call::PushTransform(transform));
        }
        fn pop_transform(&mut self) {
            self.transform_depth -= 1;
            self.calls.push(Call::PopTransform);
        }
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
