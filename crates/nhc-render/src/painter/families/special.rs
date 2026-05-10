//! `Family::Special` painter — depth-substrate hazards.
//!
//! Phase 2.7 of `plans/nhc_pure_ir_v5_migration_plan.md`. The
//! Special family covers Chasm, Pit, Abyss, Void substrates: areas
//! where the floor is replaced by depth. Each style picks a darker
//! base than the next so a visual scale of "depth" reads at a
//! glance — Chasm is hazardous-dark, Pit deeper, Abyss almost
//! black, Void is the deepest "cosmic void" tier with a faint
//! indigo cast.
//!
//! Naming caveat: this `Void` style is the thematic cosmic-abyss
//! substrate, not `SurfaceType::VOID` (empty / unrendered tiles).
//! Empty tiles never reach a painter — they are simply not
//! painted. A region only ends up with `Special, style=Void` if a
//! generator deliberately fills it as cosmic-void terrain.
//!
//! Per-style depth gradient / parallax / dark-vignette effects
//! (planned in `design/map_ir_v5.md` §4.7) are deferred until the
//! Painter trait grows a gradient `Paint` variant. The flat base
//! fill is the v5-canonical baseline; the painter applies depth
//! visuals atop the base once the trait extension lands.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct SpecialPalette {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

const CHASM: SpecialPalette = SpecialPalette {
    base: Color::rgba(0x4D, 0x4D, 0x4D, 1.0),
    highlight: Color::rgba(0x66, 0x66, 0x66, 1.0),
    shadow: Color::rgba(0x33, 0x33, 0x33, 1.0),
};

const PIT: SpecialPalette = SpecialPalette {
    base: Color::rgba(0x33, 0x2E, 0x28, 1.0),
    highlight: Color::rgba(0x4A, 0x42, 0x3A, 1.0),
    shadow: Color::rgba(0x1A, 0x14, 0x10, 1.0),
};

const ABYSS: SpecialPalette = SpecialPalette {
    base: Color::rgba(0x10, 0x10, 0x14, 1.0),
    highlight: Color::rgba(0x22, 0x22, 0x2C, 1.0),
    shadow: Color::rgba(0x00, 0x00, 0x00, 1.0),
};

/// Void — the deepest tier of the depth scale: cosmic void below
/// even the Abyss. Faint indigo cast keeps it distinguishable
/// from a flat black Abyss.
const VOID: SpecialPalette = SpecialPalette {
    base: Color::rgba(0x08, 0x05, 0x14, 1.0),
    highlight: Color::rgba(0x18, 0x12, 0x28, 1.0),
    shadow: Color::rgba(0x00, 0x00, 0x06, 1.0),
};

const SENTINEL: SpecialPalette = SpecialPalette {
    base: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    highlight: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    shadow: Color::rgba(0xFF, 0x00, 0xFF, 1.0),
};

pub(crate) fn palette(style: u8) -> SpecialPalette {
    match style {
        0 => CHASM,
        1 => PIT,
        2 => ABYSS,
        3 => VOID,
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

    fn brightness(c: Color) -> u32 {
        c.r as u32 + c.g as u32 + c.b as u32
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

    /// Chasm → Pit → Abyss → Void reads as a depth scale: each
    /// step is darker than the previous. Void is the deepest
    /// "cosmic void" tier, distinct from `SurfaceType::VOID`
    /// (empty / unrendered tiles, which never reach a painter).
    #[test]
    fn depth_scale_descends_from_chasm_to_void() {
        let chasm = brightness(CHASM.base);
        let pit = brightness(PIT.base);
        let abyss = brightness(ABYSS.base);
        let void_ = brightness(VOID.base);
        assert!(chasm > pit, "Chasm ({chasm}) must be brighter than Pit ({pit})");
        assert!(pit > abyss, "Pit ({pit}) must be brighter than Abyss ({abyss})");
        assert!(abyss > void_, "Abyss ({abyss}) must be brighter than Void ({void_})");
    }

    #[test]
    fn paint_fills_with_per_style_base_colour() {
        let path = one_tile_path();
        for (style, expected) in [
            (0u8, CHASM.base),
            (1, PIT.base),
            (2, ABYSS.base),
            (3, VOID.base),
        ] {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Special, style, 0, 0, 0);
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
