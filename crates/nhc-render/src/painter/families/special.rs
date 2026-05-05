//! `Family::Special` painter — Phase 1.2 stub.
//!
//! Substrate materials for hazards and absent floor: Chasm, Pit,
//! Abyss, Void. Phase 2.7 lands the depth / parallax / dark-
//! vignette painters per style; Phase 1.2 paints flat dark fills
//! so structural rendering works while the visual pipeline is
//! built out.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

fn stub_color(style: u8) -> Color {
    match style {
        // Chasm — near-black
        0 => Color::rgba(0x10, 0x10, 0x14, 1.0),
        // Pit — slightly warmer
        1 => Color::rgba(0x1A, 0x16, 0x14, 1.0),
        // Abyss — pure black
        2 => Color::rgba(0x00, 0x00, 0x00, 1.0),
        // Void — parchment-toned to read as "no floor"
        3 => Color::rgba(0xF7, 0xEE, 0xD8, 1.0),
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
    use crate::painter::test_util::MockPainter;
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
    fn special_dispatches_each_of_four_styles() {
        let path = one_tile_path();
        for style in 0..4u8 {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Special, style, 0, 0, 0);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}: expected 1 call");
        }
    }
}
