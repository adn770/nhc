//! `Family::Liquid` painter — Phase 1.2 stub.
//!
//! Static substrate fills: Water, Lava. Surface motion (ripples,
//! lava cracks) lives on `StampOp` decorator bits, not here. Phase
//! 2.6 lands the per-style palettes; Phase 1.2 paints flat fills.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

fn stub_color(style: u8) -> Color {
    match style {
        // Water — deep blue
        0 => Color::rgba(0x32, 0x5A, 0x9C, 1.0),
        // Lava — molten orange
        1 => Color::rgba(0xC9, 0x4A, 0x18, 1.0),
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
    fn water_paints_blue_and_lava_paints_orange() {
        let path = one_tile_path();

        let mut p = MockPainter::default();
        let water = Material::new(Family::Liquid, 0, 0, 0, 0);
        paint(&mut p, &path, &water);
        match &p.calls[0] {
            PainterCall::FillPath(_, paint, _) => {
                assert!(paint.color.b > paint.color.r, "water should be more blue than red");
            }
            other => panic!("expected FillPath, got {other:?}"),
        }

        let mut p = MockPainter::default();
        let lava = Material::new(Family::Liquid, 1, 0, 0, 0);
        paint(&mut p, &path, &lava);
        match &p.calls[0] {
            PainterCall::FillPath(_, paint, _) => {
                assert!(paint.color.r > paint.color.b, "lava should be more red than blue");
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }
}
