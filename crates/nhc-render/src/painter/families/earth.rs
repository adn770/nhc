//! `Family::Earth` painter — Phase 1.2 stub.
//!
//! Outdoor / surface-site substrate: Dirt, Grass, Sand, Mud.
//! Phase 1.2 ships a sentinel palette keyed by `style`. Phase 2.5
//! lands the seed-driven texture dithering pipeline that replaces
//! today's terrain-tint passes.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

fn stub_color(style: u8) -> Color {
    match style {
        // Dirt
        0 => Color::rgba(0x8B, 0x6F, 0x4F, 1.0),
        // Grass
        1 => Color::rgba(0x6F, 0x8E, 0x4F, 1.0),
        // Sand
        2 => Color::rgba(0xD8, 0xC2, 0x8E, 1.0),
        // Mud
        3 => Color::rgba(0x55, 0x42, 0x2E, 1.0),
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
    fn earth_dispatches_each_of_four_styles() {
        let path = one_tile_path();
        for style in 0..4u8 {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Earth, style, 0, 0, 0);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}: expected 1 call");
        }
    }
}
