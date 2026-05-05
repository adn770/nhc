//! `Family::Cave` painter — buffered-jittered-smoothed organic fills.
//!
//! Cave geometry is organic: the painter recovers polygon vertices
//! from the supplied region path, runs them through
//! [`crate::geometry::cave_path_from_outline`] (buffer → simplify →
//! orient CCW → densify → jitter → smooth), and fills with the
//! per-style base colour. Non-polygonal outlines (Circle / Pill)
//! and degenerate inputs fall back to a flat fill of the original
//! region path.
//!
//! Phase 2.2 of `plans/nhc_pure_ir_v5_migration_plan.md`. Per-style
//! palette holds (base, highlight, shadow) triples for Limestone,
//! Granite, Sandstone, Basalt; highlight / shadow are reserved for
//! Phase 2.9 decorator-bit surface texture and unused for the
//! base-colour fill in this phase.

use crate::geometry::cave_path_from_outline;
use crate::painter::material::Material;
use crate::painter::{Color, FillRule, Paint, Painter, PathOp, PathOps, Vec2};

/// Per-style palette: base, highlight, shadow. Highlight / shadow
/// are reserved for decorator-bit surface texture (Phase 2.9) and
/// not consumed by the base-colour fill in Phase 2.2.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct CavePalette {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

/// Limestone — base matches the v4 ``CaveFloor`` reference colour
/// ``#F5EBD8`` so the v5-vs-v4 PSNR gate (Phase 3.1) at all cave
/// fixtures stays ≥ 50 dB.
const LIMESTONE: CavePalette = CavePalette {
    base: Color::rgba(0xF5, 0xEB, 0xD8, 1.0),
    highlight: Color::rgba(0xFB, 0xF5, 0xE8, 1.0),
    shadow: Color::rgba(0xD9, 0xCF, 0xB8, 1.0),
};

const GRANITE: CavePalette = CavePalette {
    base: Color::rgba(0xA8, 0xA8, 0xA8, 1.0),
    highlight: Color::rgba(0xC8, 0xC8, 0xC8, 1.0),
    shadow: Color::rgba(0x7A, 0x7A, 0x7A, 1.0),
};

const SANDSTONE: CavePalette = CavePalette {
    base: Color::rgba(0xD4, 0xB0, 0x84, 1.0),
    highlight: Color::rgba(0xE8, 0xC8, 0xA0, 1.0),
    shadow: Color::rgba(0xA8, 0x86, 0x60, 1.0),
};

const BASALT: CavePalette = CavePalette {
    base: Color::rgba(0x5C, 0x54, 0x4D, 1.0),
    highlight: Color::rgba(0x7A, 0x6F, 0x66, 1.0),
    shadow: Color::rgba(0x3C, 0x36, 0x33, 1.0),
};

/// Sentinel magenta — flags un-implemented styles in visual review.
const SENTINEL: CavePalette = CavePalette {
    base: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    highlight: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    shadow: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
};

pub(crate) fn palette(style: u8) -> CavePalette {
    match style {
        0 => LIMESTONE,
        1 => GRANITE,
        2 => SANDSTONE,
        3 => BASALT,
        _ => SENTINEL,
    }
}

/// Recover single-ring polygon vertices from a path. Returns
/// `None` for empty paths, multi-ring polygons (multiple `MoveTo`s),
/// or paths containing curves — the cave-geometry pipeline only
/// operates on simple polygonal outlines.
fn polygon_vertices(path: &PathOps) -> Option<Vec<Vec2>> {
    if path.is_empty() {
        return None;
    }
    let mut verts = Vec::with_capacity(path.ops.len());
    let mut seen_move = false;
    for op in &path.ops {
        match *op {
            PathOp::MoveTo(p) => {
                if seen_move {
                    return None;
                }
                seen_move = true;
                verts.push(p);
            }
            PathOp::LineTo(p) => verts.push(p),
            PathOp::Close => {}
            _ => return None,
        }
    }
    if verts.len() < 4 {
        return None;
    }
    Some(verts)
}

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    let pal = palette(material.style);
    let paint = Paint::solid(pal.base);
    if let Some(verts) = polygon_vertices(region_path) {
        let coords: Vec<(f64, f64)> = verts.iter().map(|v| (v.x as f64, v.y as f64)).collect();
        let cave = cave_path_from_outline(&coords, material.seed);
        if !cave.is_empty() {
            painter.fill_path(&cave, &paint, FillRule::EvenOdd);
            return;
        }
    }
    painter.fill_path(region_path, &paint, FillRule::Winding);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::material::Family;
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn square_path(size: f32) -> PathOps {
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(size, 0.0))
            .line_to(Vec2::new(size, size))
            .line_to(Vec2::new(0.0, size))
            .close();
        p
    }

    #[test]
    fn each_style_picks_a_distinct_base_colour() {
        let mut seen = Vec::new();
        for style in 0..4u8 {
            let p = palette(style);
            let key = (p.base.r, p.base.g, p.base.b);
            assert!(
                !seen.contains(&key),
                "style {style} reuses base colour {key:?}"
            );
            seen.push(key);
        }
    }

    #[test]
    fn limestone_base_matches_v4_cave_floor_reference() {
        // v4 CAVE_FLOOR colour is `#F5EBD8`. Phase 3.1's PSNR gate
        // at every cave fixture depends on Limestone owning that
        // exact triple — a regression here breaks v5-vs-v4 parity.
        let p = palette(0);
        assert_eq!(p.base, Color::rgba(0xF5, 0xEB, 0xD8, 1.0));
    }

    #[test]
    fn each_style_has_distinct_highlight_and_shadow_from_base() {
        for style in 0..4u8 {
            let p = palette(style);
            assert_ne!(p.base, p.highlight, "style {style}: highlight==base");
            assert_ne!(p.base, p.shadow, "style {style}: shadow==base");
        }
    }

    #[test]
    fn paint_uses_cave_geometry_pipeline_for_polygon_outline() {
        // Polygon input: the painter recovers vertices, runs them
        // through `cave_path_from_outline`, and emits a fill_path
        // with a path different from the raw rectangle.
        let mut p = MockPainter::default();
        let path = square_path(64.0);
        let m = Material::new(Family::Cave, 0, 0, 0, 0xCAFE);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            PainterCall::FillPath(painted_path, paint, fill_rule) => {
                assert_eq!(*fill_rule, FillRule::EvenOdd, "cave path uses EvenOdd");
                // Cave path differs from raw square: more vertices
                // (densified) and includes Close ops per ring.
                assert!(
                    painted_path.len() > path.len(),
                    "cave path should densify (input ops {}, got {})",
                    path.len(),
                    painted_path.len()
                );
                assert_eq!(paint.color, LIMESTONE.base);
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }

    #[test]
    fn paint_falls_back_to_winding_fill_for_pathops_with_curves() {
        // PathOps containing a cubic curve should fall through to
        // the flat-region fill (no cave-geometry pipeline). The
        // recovery helper rejects curves, so the painter fills the
        // input path directly with FillRule::Winding.
        let mut p = MockPainter::default();
        let mut path = PathOps::new();
        path.move_to(Vec2::new(0.0, 0.0))
            .cubic_to(
                Vec2::new(10.0, 0.0),
                Vec2::new(10.0, 10.0),
                Vec2::new(0.0, 10.0),
            )
            .close();
        let m = Material::new(Family::Cave, 1, 0, 0, 0xCAFE);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            PainterCall::FillPath(painted, paint, rule) => {
                assert_eq!(*rule, FillRule::Winding);
                assert_eq!(painted, &path, "should fill input path verbatim");
                assert_eq!(paint.color, GRANITE.base);
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }

    #[test]
    fn polygon_vertices_returns_none_for_empty_path() {
        let p = PathOps::new();
        assert!(polygon_vertices(&p).is_none());
    }

    #[test]
    fn polygon_vertices_returns_none_for_multi_ring_path() {
        // Two MoveTos = two rings.
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(1.0, 0.0))
            .line_to(Vec2::new(0.0, 1.0))
            .close()
            .move_to(Vec2::new(2.0, 0.0))
            .line_to(Vec2::new(3.0, 0.0))
            .line_to(Vec2::new(2.0, 1.0))
            .close();
        assert!(polygon_vertices(&p).is_none());
    }

    #[test]
    fn polygon_vertices_recovers_simple_quad() {
        let p = square_path(32.0);
        let v = polygon_vertices(&p).expect("recoverable");
        assert_eq!(v.len(), 4);
    }
}
