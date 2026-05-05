//! `Family::Liquid` painter — water and lava substrates.
//!
//! Phase 2.6 of `plans/nhc_pure_ir_v5_migration_plan.md`. The
//! Liquid family ships opaque substrate fills for Water and Lava;
//! surface motion (Ripples for Water, LavaCracks for Lava) lives on
//! StampOp decorator bits (Phase 2.9), painted as static texture on
//! top of the substrate. v5 has no animations.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct LiquidPalette {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

/// Water — clean blue substrate. Highlight / shadow are reserved
/// for Phase 2.9 ``Ripples`` decorator (concentric ring stamps).
const WATER: LiquidPalette = LiquidPalette {
    base: Color::rgba(0x7B, 0xA8, 0xC8, 1.0),
    highlight: Color::rgba(0xA8, 0xC8, 0xDC, 1.0),
    shadow: Color::rgba(0x4A, 0x78, 0x88, 1.0),
};

/// Lava — molten orange-red substrate. Highlight / shadow are
/// reserved for Phase 2.9 ``LavaCracks`` decorator (bright crack
/// network with embers).
const LAVA: LiquidPalette = LiquidPalette {
    base: Color::rgba(0xD8, 0x58, 0x38, 1.0),
    highlight: Color::rgba(0xF0, 0x90, 0x40, 1.0),
    shadow: Color::rgba(0xA0, 0x40, 0x30, 1.0),
};

const SENTINEL: LiquidPalette = LiquidPalette {
    base: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    highlight: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    shadow: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
};

pub(crate) fn palette(style: u8) -> LiquidPalette {
    match style {
        0 => WATER,
        1 => LAVA,
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
    fn water_and_lava_have_distinct_palettes() {
        assert_ne!(WATER.base, LAVA.base);
        assert_ne!(WATER.highlight, LAVA.highlight);
        assert_ne!(WATER.shadow, LAVA.shadow);
    }

    #[test]
    fn each_style_has_distinct_highlight_and_shadow_from_base() {
        for style in 0..2u8 {
            let p = palette(style);
            assert_ne!(p.base, p.highlight, "style {style}: highlight==base");
            assert_ne!(p.base, p.shadow, "style {style}: shadow==base");
        }
    }

    #[test]
    fn paint_fills_water_with_blue_substrate() {
        let mut p = MockPainter::default();
        let path = one_tile_path();
        let m = Material::new(Family::Liquid, 0, 0, 0, 0);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            PainterCall::FillPath(_, paint, _) => {
                assert_eq!(paint.color, WATER.base);
                assert!(paint.color.b > paint.color.r);
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }

    #[test]
    fn paint_fills_lava_with_red_orange_substrate() {
        let mut p = MockPainter::default();
        let path = one_tile_path();
        let m = Material::new(Family::Liquid, 1, 0, 0, 0);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            PainterCall::FillPath(_, paint, _) => {
                assert_eq!(paint.color, LAVA.base);
                assert!(paint.color.r > paint.color.b);
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }
}
