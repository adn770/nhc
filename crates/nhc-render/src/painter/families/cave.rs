//! `Family::Cave` painter — Phase 1.2 stub.
//!
//! Cave geometry is organic: the painter buffers, jitters, and
//! smooths the outline (per `geometry::cave_path_from_outline`)
//! before filling. Phase 1.2 ships a placeholder palette keyed
//! by `style` (Limestone, Granite, Sandstone, Basalt). Phase 2.2
//! lands the real per-style colour triples and the smoothed
//! outline pipeline.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

/// Per-style placeholder colour. Replaced with the full
/// (base, highlight, shadow) triple in Phase 2.2.
fn stub_color(style: u8) -> Color {
    match style {
        // Limestone — pale buff
        0 => Color::rgba(0xCB, 0xC0, 0x9E, 1.0),
        // Granite — medium grey
        1 => Color::rgba(0x88, 0x82, 0x7A, 1.0),
        // Sandstone — warm tan
        2 => Color::rgba(0xC4, 0x99, 0x65, 1.0),
        // Basalt — dark slate
        3 => Color::rgba(0x4A, 0x46, 0x44, 1.0),
        // Unknown style — sentinel magenta so visual inspection
        // immediately flags missing palette coverage.
        _ => Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    }
}

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    fill_region(painter, region_path, stub_color(material.style));
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::material::Family;
    use crate::painter::test_util::{MockPainter, PainterCall};
    use crate::painter::Vec2;

    fn one_tile_path() -> PathOps {
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(32.0, 0.0))
            .line_to(Vec2::new(32.0, 32.0))
            .line_to(Vec2::new(0.0, 32.0))
            .close();
        p
    }

    #[test]
    fn each_cave_style_picks_a_distinct_stub_color() {
        let path = one_tile_path();
        let mut seen = Vec::new();
        for style in 0..4u8 {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Cave, style, 0, 0, 0);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}: expected 1 call");
            match &p.calls[0] {
                PainterCall::FillPath(_, paint, _) => {
                    let key = (paint.color.r, paint.color.g, paint.color.b);
                    assert!(
                        !seen.contains(&key),
                        "style {style} reuses palette of an earlier style: {key:?}"
                    );
                    seen.push(key);
                }
                other => panic!("expected FillPath, got {other:?}"),
            }
        }
    }
}
