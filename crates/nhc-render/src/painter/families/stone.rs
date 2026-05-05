//! `Family::Stone` painter — Phase 1.2 stub.
//!
//! Nine styles (Cobblestone, Brick, Flagstone, OpusRomano,
//! FieldStone, Pinwheel, Hopscotch, CrazyPaving, Ashlar). Per-
//! style sub-pattern axes (Cobblestone × 4, Brick × 3, Ashlar × 2;
//! the rest none). Phase 2.4 lands per-style painters one commit
//! at a time; Phase 1.2 ships sentinel palette colours keyed by
//! `style` so the dispatcher can fan out cleanly.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

fn stub_color(style: u8) -> Color {
    match style {
        // Cobblestone
        0 => Color::rgba(0x9A, 0x95, 0x8E, 1.0),
        // Brick
        1 => Color::rgba(0xB1, 0x55, 0x39, 1.0),
        // Flagstone
        2 => Color::rgba(0xA8, 0xA0, 0x91, 1.0),
        // OpusRomano
        3 => Color::rgba(0x95, 0x8B, 0x77, 1.0),
        // FieldStone
        4 => Color::rgba(0x88, 0x80, 0x6F, 1.0),
        // Pinwheel
        5 => Color::rgba(0x9C, 0x90, 0x80, 1.0),
        // Hopscotch
        6 => Color::rgba(0xA1, 0x95, 0x82, 1.0),
        // CrazyPaving
        7 => Color::rgba(0x8E, 0x84, 0x73, 1.0),
        // Ashlar
        8 => Color::rgba(0xB4, 0xAA, 0x95, 1.0),
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
    fn each_stone_style_picks_a_distinct_stub_color() {
        let path = one_tile_path();
        let mut seen = Vec::new();
        for style in 0..9u8 {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Stone, style, 0, 0, 0);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}: expected 1 call");
        }
        // re-check by inspecting the colour table directly
        for style in 0..9u8 {
            let key = stub_color(style);
            assert!(
                !seen.contains(&(key.r, key.g, key.b)),
                "style {style} duplicates an earlier stub colour"
            );
            seen.push((key.r, key.g, key.b));
        }
    }
}
