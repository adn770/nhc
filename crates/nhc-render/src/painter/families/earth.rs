//! `Family::Earth` painter — outdoor / surface-site substrate.
//!
//! Phase 2.5 of `plans/nhc_pure_ir_v5_migration_plan.md`. Per-style
//! palette holds (base, highlight, shadow) triples for Dirt, Grass,
//! Sand, Mud. Phase 2.5 ships flat per-style base fills; per-tile
//! texture dithering rides Phase 2.9 decorator bits (Cracks /
//! Scratches for Dirt/Mud, fine speckles for Sand, etc.) once the
//! decorator-bit registry lands.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct EarthPalette {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

const DIRT: EarthPalette = EarthPalette {
    base: Color::rgba(0x8B, 0x6F, 0x4F, 1.0),
    highlight: Color::rgba(0xA8, 0x8A, 0x66, 1.0),
    shadow: Color::rgba(0x66, 0x4F, 0x36, 1.0),
};

const GRASS: EarthPalette = EarthPalette {
    base: Color::rgba(0x6F, 0x8E, 0x4F, 1.0),
    highlight: Color::rgba(0x8C, 0xA8, 0x68, 1.0),
    shadow: Color::rgba(0x52, 0x6E, 0x36, 1.0),
};

const SAND: EarthPalette = EarthPalette {
    base: Color::rgba(0xD8, 0xC2, 0x8E, 1.0),
    highlight: Color::rgba(0xE8, 0xD3, 0xA8, 1.0),
    shadow: Color::rgba(0xB8, 0xA0, 0x6C, 1.0),
};

const MUD: EarthPalette = EarthPalette {
    base: Color::rgba(0x55, 0x42, 0x2E, 1.0),
    highlight: Color::rgba(0x72, 0x5A, 0x40, 1.0),
    shadow: Color::rgba(0x36, 0x28, 0x1A, 1.0),
};

const SENTINEL: EarthPalette = EarthPalette {
    base: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    highlight: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    shadow: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
};

pub(crate) fn palette(style: u8) -> EarthPalette {
    match style {
        0 => DIRT,
        1 => GRASS,
        2 => SAND,
        3 => MUD,
        _ => SENTINEL,
    }
}

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    fill_region(painter, region_path, palette(material.style).base);
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
    fn each_style_has_a_distinct_base_colour() {
        let mut seen = Vec::new();
        for style in 0..4u8 {
            let p = palette(style);
            let key = (p.base.r, p.base.g, p.base.b);
            assert!(!seen.contains(&key), "style {style} reuses base {key:?}");
            seen.push(key);
        }
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
    fn paint_fills_with_the_per_style_base_colour() {
        let path = one_tile_path();
        for (style, expected) in [
            (0u8, DIRT.base),
            (1, GRASS.base),
            (2, SAND.base),
            (3, MUD.base),
        ] {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Earth, style, 0, 0, 0);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}: expected 1 call");
            match &p.calls[0] {
                PainterCall::FillPath(_, paint, _) => {
                    assert_eq!(paint.color, expected, "style {style}");
                }
                other => panic!("style {style}: expected FillPath, got {other:?}"),
            }
        }
    }
}
