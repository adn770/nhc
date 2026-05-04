//! Shadow primitive — Phase 4.2, second deterministic port.
//!
//! Reproduces `_render_corridor_shadows` (per-tile offset rects)
//! and `_room_shadow_svg` (per-shape room shadows) from
//! `nhc/rendering/_shadows.py`. No RNG, no Perlin. Cave room
//! shadows go through `crate::geometry::smooth_closed_path`
//! (centripetal Catmull-Rom → cubic Bézier) — that helper's
//! cross-language gate covers the FP arithmetic byte-equality
//! contract this primitive depends on.
//!
//! Design constants (`+3` offset, `0.08` opacity, `#000000`
//! ink) are baked in here. The schema's `dx` / `dy` / `opacity`
//! fields on `ShadowOp` are intentionally ignored to dodge the
//! float32 round-trip on `0.08` (which would surface as
//! `"0.07999999821186066"`); the legacy renderer used hardcoded
//! literals and the Phase 4 port preserves that contract.
//!
//! Phase 2.19 retired the legacy `draw_*` SVG-string emitters;
//! the only remaining surface is the Painter-based `paint_*`
//! family, used by both `transform/png` (via `SkiaPainter`) and
//! `transform/svg` (via `SvgPainter`).

use crate::geometry::centripetal_bezier_cps;
use crate::painter::{Color, FillRule, Paint, Painter, PathOps, Rect, Vec2};

const CELL: i32 = 32;
const CELL_F: f32 = CELL as f32;
const SHADOW_OFFSET: f32 = 3.0;

const SHADOW_PAINT: Paint = Paint {
    color: Color { r: 0, g: 0, b: 0, a: 0.08 },
};

// ── Painter-based emitters (Phase 2.4) ──────────────────────────

/// Paint per-tile corridor shadow rects via the Painter trait.
///
/// Mirrors `draw_corridor_shadows`'s geometry: each tile becomes
/// a `CELL × CELL` rect at pixel coords `(x*CELL+3, y*CELL+3)`
/// painted in `SHADOW_PAINT` (black at f32 alpha 0.08). The +3
/// offset is folded into the rect coords; no group transform.
pub fn paint_corridor_shadows(painter: &mut dyn Painter, tiles: &[(i32, i32)]) {
    for &(x, y) in tiles {
        let px = (x * CELL) as f32 + SHADOW_OFFSET;
        let py = (y * CELL) as f32 + SHADOW_OFFSET;
        painter.fill_rect(Rect::new(px, py, CELL_F, CELL_F), &SHADOW_PAINT);
    }
}

/// Paint a rect-shape room shadow via the Painter trait. Mirrors
/// `draw_room_shadow_rect`: bbox of `coords`, +3 offset folded
/// into x/y, single `fill_rect` call.
pub fn paint_room_shadow_rect(painter: &mut dyn Painter, coords: &[(f64, f64)]) {
    if coords.is_empty() {
        return;
    }
    let mut min_x = i32::MAX;
    let mut max_x = i32::MIN;
    let mut min_y = i32::MAX;
    let mut max_y = i32::MIN;
    for &(x, y) in coords {
        let xi = x as i32;
        let yi = y as i32;
        if xi < min_x {
            min_x = xi;
        }
        if xi > max_x {
            max_x = xi;
        }
        if yi < min_y {
            min_y = yi;
        }
        if yi > max_y {
            max_y = yi;
        }
    }
    let px = (min_x + 3) as f32;
    let py = (min_y + 3) as f32;
    let pw = (max_x - min_x) as f32;
    let ph = (max_y - min_y) as f32;
    painter.fill_rect(Rect::new(px, py, pw, ph), &SHADOW_PAINT);
}

/// Paint an octagon-shape room shadow via the Painter trait.
/// Mirrors `draw_room_shadow_octagon`'s `<g translate(3,3)>` →
/// `<polygon>` shape via `fill_polygon` against `coords` shifted
/// by `+SHADOW_OFFSET` on both axes.
pub fn paint_room_shadow_octagon(painter: &mut dyn Painter, coords: &[(f64, f64)]) {
    if coords.len() < 3 {
        return;
    }
    let verts: Vec<Vec2> = coords
        .iter()
        .map(|&(x, y)| Vec2::new(x as f32 + SHADOW_OFFSET, y as f32 + SHADOW_OFFSET))
        .collect();
    painter.fill_polygon(&verts, &SHADOW_PAINT, FillRule::Winding);
}

/// Paint a cave-shape room shadow via the Painter trait. Mirrors
/// `draw_room_shadow_cave`'s `<g translate(3,3)>` →
/// Catmull-Rom-smoothed `<path>` via `fill_path` against a
/// PathOps stream of cubic Béziers, with the `+SHADOW_OFFSET`
/// folded into every control point.
pub fn paint_room_shadow_cave(painter: &mut dyn Painter, coords: &[(f64, f64)]) {
    let n = coords.len();
    if n < 3 {
        return;
    }
    let off = SHADOW_OFFSET as f64;
    let mut path = PathOps::with_capacity(n + 2);
    let p0 = coords[0];
    path.move_to(Vec2::new((p0.0 + off) as f32, (p0.1 + off) as f32));
    for i in 0..n {
        let p0 = coords[(i + n - 1) % n];
        let p1 = coords[i];
        let p2 = coords[(i + 1) % n];
        let p3 = coords[(i + 2) % n];
        let (c1x, c1y, c2x, c2y) = centripetal_bezier_cps(p0, p1, p2, p3);
        path.cubic_to(
            Vec2::new((c1x + off) as f32, (c1y + off) as f32),
            Vec2::new((c2x + off) as f32, (c2y + off) as f32),
            Vec2::new((p2.0 + off) as f32, (p2.1 + off) as f32),
        );
    }
    path.close();
    painter.fill_path(&path, &SHADOW_PAINT, FillRule::Winding);
}

#[cfg(test)]
mod tests {
    use super::{paint_corridor_shadows, paint_room_shadow_cave, paint_room_shadow_octagon, paint_room_shadow_rect, SHADOW_OFFSET};
    use crate::painter::{FillRule, PathOp, Rect, Vec2};

    /// Records every Painter call for the paint_* unit tests so
    /// we can assert call counts and per-call geometry without
    /// rasterising. Mirrors the painter::tests::MockPainter.
    #[derive(Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
    }

    #[derive(Debug)]
    enum Call {
        FillRect(Rect),
        FillPolygon(Vec<Vec2>, FillRule),
        FillPath(Vec<PathOp>, FillRule),
    }

    impl crate::painter::Painter for CaptureCalls {
        fn fill_rect(&mut self, rect: Rect, _: &crate::painter::Paint) {
            self.calls.push(Call::FillRect(rect));
        }
        fn stroke_rect(
            &mut self,
            _: Rect,
            _: &crate::painter::Paint,
            _: &crate::painter::Stroke,
        ) {
            unreachable!("shadow primitive never strokes");
        }
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &crate::painter::Paint) {
            unreachable!("shadow primitive never paints circles");
        }
        fn fill_ellipse(
            &mut self,
            _: f32,
            _: f32,
            _: f32,
            _: f32,
            _: &crate::painter::Paint,
        ) {
            unreachable!("shadow primitive never paints ellipses");
        }
        fn fill_polygon(
            &mut self,
            vertices: &[Vec2],
            _: &crate::painter::Paint,
            rule: FillRule,
        ) {
            self.calls.push(Call::FillPolygon(vertices.to_vec(), rule));
        }
        fn stroke_polyline(
            &mut self,
            _: &[Vec2],
            _: &crate::painter::Paint,
            _: &crate::painter::Stroke,
        ) {
            unreachable!("shadow primitive never strokes");
        }
        fn fill_path(
            &mut self,
            path: &crate::painter::PathOps,
            _: &crate::painter::Paint,
            rule: FillRule,
        ) {
            self.calls.push(Call::FillPath(path.ops.clone(), rule));
        }
        fn stroke_path(
            &mut self,
            _: &crate::painter::PathOps,
            _: &crate::painter::Paint,
            _: &crate::painter::Stroke,
        ) {
            unreachable!("shadow primitive never strokes");
        }
        fn begin_group(&mut self, _: f32) {
            unreachable!("shadow primitive never opens a group");
        }
        fn end_group(&mut self) {
            unreachable!("shadow primitive never closes a group");
        }
        fn push_clip(&mut self, _: &crate::painter::PathOps, _: FillRule) {
            unreachable!("shadow primitive never pushes a clip");
        }
        fn pop_clip(&mut self) {
            unreachable!("shadow primitive never pops a clip");
        }
        fn push_transform(&mut self, _: crate::painter::Transform) {
            unreachable!("shadow primitive never pushes a transform");
        }
        fn pop_transform(&mut self) {
            unreachable!("shadow primitive never pops a transform");
        }
    }

    #[test]
    fn paint_corridor_shadows_emits_one_fill_rect_per_tile() {
        let mut p = CaptureCalls::default();
        paint_corridor_shadows(&mut p, &[(0, 0), (2, 3)]);
        assert_eq!(p.calls.len(), 2);
        // First tile at origin: (0+3, 0+3, 32, 32).
        match p.calls[0] {
            Call::FillRect(r) => {
                assert_eq!((r.x, r.y, r.w, r.h), (3.0, 3.0, 32.0, 32.0));
            }
            _ => panic!("expected FillRect, got {:?}", p.calls[0]),
        }
        // Second tile at (2,3): (2*32+3, 3*32+3, 32, 32) = (67, 99, 32, 32).
        match p.calls[1] {
            Call::FillRect(r) => {
                assert_eq!((r.x, r.y, r.w, r.h), (67.0, 99.0, 32.0, 32.0));
            }
            _ => panic!("expected FillRect, got {:?}", p.calls[1]),
        }
    }

    #[test]
    fn paint_corridor_shadows_skips_when_no_tiles() {
        let mut p = CaptureCalls::default();
        paint_corridor_shadows(&mut p, &[]);
        assert!(p.calls.is_empty());
    }

    #[test]
    fn paint_room_shadow_rect_uses_bbox_with_plus_three_offset() {
        let mut p = CaptureCalls::default();
        // 64×96 rect at origin (0,0) → x=3, y=3, w=64, h=96.
        let coords = [(0.0, 0.0), (64.0, 0.0), (64.0, 96.0), (0.0, 96.0)];
        paint_room_shadow_rect(&mut p, &coords);
        assert_eq!(p.calls.len(), 1);
        match p.calls[0] {
            Call::FillRect(r) => {
                assert_eq!((r.x, r.y, r.w, r.h), (3.0, 3.0, 64.0, 96.0));
            }
            _ => panic!("expected FillRect, got {:?}", p.calls[0]),
        }
    }

    #[test]
    fn paint_room_shadow_octagon_folds_offset_into_vertices() {
        let mut p = CaptureCalls::default();
        let coords = [
            (10.0, 0.0),
            (20.0, 0.0),
            (30.0, 10.0),
            (30.0, 20.0),
            (20.0, 30.0),
            (10.0, 30.0),
            (0.0, 20.0),
            (0.0, 10.0),
        ];
        paint_room_shadow_octagon(&mut p, &coords);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            Call::FillPolygon(verts, rule) => {
                assert_eq!(*rule, FillRule::Winding);
                assert_eq!(verts.len(), 8);
                // Every vertex must be shifted by SHADOW_OFFSET on
                // both axes — the legacy <g translate(3,3)> equivalent.
                for (i, v) in verts.iter().enumerate() {
                    assert_eq!(v.x, coords[i].0 as f32 + SHADOW_OFFSET);
                    assert_eq!(v.y, coords[i].1 as f32 + SHADOW_OFFSET);
                }
            }
            _ => panic!("expected FillPolygon, got {:?}", p.calls[0]),
        }
    }

    #[test]
    fn paint_room_shadow_cave_emits_cubic_bezier_path() {
        let mut p = CaptureCalls::default();
        // Minimum-vertex cave triangle.
        let coords = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.66)];
        paint_room_shadow_cave(&mut p, &coords);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            Call::FillPath(ops, rule) => {
                assert_eq!(*rule, FillRule::Winding);
                // MoveTo + 3 CubicTo + Close = 5 ops.
                assert_eq!(ops.len(), 5);
                match ops[0] {
                    PathOp::MoveTo(v) => {
                        assert_eq!(v.x, 0.0 + SHADOW_OFFSET);
                        assert_eq!(v.y, 0.0 + SHADOW_OFFSET);
                    }
                    _ => panic!("first op must be MoveTo, got {:?}", ops[0]),
                }
                assert!(matches!(ops[1], PathOp::CubicTo(..)));
                assert!(matches!(ops[2], PathOp::CubicTo(..)));
                assert!(matches!(ops[3], PathOp::CubicTo(..)));
                assert_eq!(ops[4], PathOp::Close);
            }
            _ => panic!("expected FillPath, got {:?}", p.calls[0]),
        }
    }

    #[test]
    fn paint_room_shadow_cave_skips_below_three_vertices() {
        let mut p = CaptureCalls::default();
        paint_room_shadow_cave(&mut p, &[(0.0, 0.0), (10.0, 10.0)]);
        assert!(p.calls.is_empty());
    }

}
