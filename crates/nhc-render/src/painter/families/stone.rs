//! `Family::Stone` painter — masonry / paving substrate.
//!
//! 9 styles (Cobblestone, Brick, Flagstone, OpusRomano, FieldStone,
//! Pinwheel, Hopscotch, CrazyPaving, Ashlar). Per-style sub-pattern
//! axes (Cobblestone × 4, Brick × 3, Ashlar × 2; the rest none).
//! Per-style optional tone axis (typically Light / Medium / Dark).
//!
//! Phase 2.4 of `plans/nhc_pure_ir_v5_migration_plan.md`. This
//! commit lifts the per-style palette out of the v4 stone
//! primitives (`crates/nhc-render/src/primitives/{cobblestone,
//! brick, flagstone, opus_romano, field_stone}.rs`) — base /
//! highlight / shadow per style — and ships flat base fills. The
//! per-(style, sub_pattern) layout algorithms (Cobblestone
//! herringbone / stack / rubble / mosaic, Brick running-bond /
//! English bond / Flemish bond, Ashlar even-joint / staggered-joint,
//! the remaining six styles' generators) ride additive Phase 2.4
//! follow-on commits, sequenced one style per commit per the
//! migration plan §2.4 ladder. Phase 3.1's PSNR gate at the stone-
//! floor fixtures drives which seam pattern comes first.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct StonePalette {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

const fn entry(base: u32, highlight: u32, shadow: u32) -> StonePalette {
    StonePalette {
        base: hex(base),
        highlight: hex(highlight),
        shadow: hex(shadow),
    }
}

const fn hex(rgb: u32) -> Color {
    Color::rgba(
        ((rgb >> 16) & 0xFF) as u8,
        ((rgb >> 8) & 0xFF) as u8,
        (rgb & 0xFF) as u8,
        1.0,
    )
}

/// Cobblestone — rounded stone fill ``#C8BEB0`` over mortar
/// ``#9A8A7A`` (lifted from primitives/cobblestone.rs's
/// ``STONE_FILL`` / ``STONE_STROKE`` / ``COBBLE_STROKE``).
const COBBLESTONE: StonePalette = entry(0xC8BEB0, 0xD8D0C2, 0x9A8A7A);

/// Brick — terracotta brick over mortar (lifted from
/// primitives/brick.rs's ``BRICK_STROKE``; base is the visible
/// brick face, shadow is the mortar joint).
const BRICK: StonePalette = entry(0xB8553F, 0xD8826B, 0xA05530);

/// Flagstone — large irregular stones with deep mortar joints.
/// Base is the v4 ``DungeonFloor`` white (the floor paint shows
/// between the joints); shadow is the joint stroke
/// (``FLAGSTONE_STROKE`` from primitives/flagstone.rs).
const FLAGSTONE: StonePalette = entry(0xE8E0D2, 0xF5F0E8, 0x6A6055);

/// OpusRomano — irregular polygonal pavers with a brown mortar
/// (``OPUS_ROMANO_STROKE`` from primitives/opus_romano.rs).
const OPUS_ROMANO: StonePalette = entry(0xE8DCC4, 0xF5ECE0, 0x7A5A3A);

/// FieldStone — natural fieldstone with greenish patina (lifted
/// from primitives/field_stone.rs's ``FIELD_STONE_FILL`` /
/// ``FIELD_STONE_STROKE``).
const FIELD_STONE: StonePalette = entry(0x8A9A6A, 0xA8B888, 0x4A5A3A);

/// Pinwheel — geometric pinwheel paving; sandy beige stones over
/// dark mortar.
const PINWHEEL: StonePalette = entry(0xCFC2A6, 0xE0D6BC, 0x88775E);

/// Hopscotch — square + rectangle alternation; warm beige.
const HOPSCOTCH: StonePalette = entry(0xD8C9A8, 0xE8DCC4, 0x9A8460);

/// CrazyPaving — irregular randomised stones; grey-green tone.
const CRAZY_PAVING: StonePalette = entry(0xBFB6A6, 0xD0C8B8, 0x807358);

/// Ashlar — dressed cut stone with thin even joints.
const ASHLAR: StonePalette = entry(0xD0C7B6, 0xE2DBCB, 0x988D7A);

const SENTINEL: StonePalette = entry(0xFF00FF, 0xFF00FF, 0xFF00FF);

pub(crate) fn palette(style: u8) -> StonePalette {
    match style {
        0 => COBBLESTONE,
        1 => BRICK,
        2 => FLAGSTONE,
        3 => OPUS_ROMANO,
        4 => FIELD_STONE,
        5 => PINWHEEL,
        6 => HOPSCOTCH,
        7 => CRAZY_PAVING,
        8 => ASHLAR,
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
        let mut bases = Vec::new();
        for style in 0..9u8 {
            let p = palette(style);
            let key = (p.base.r, p.base.g, p.base.b);
            assert!(!bases.contains(&key), "style {style} reuses base {key:?}");
            bases.push(key);
        }
    }

    #[test]
    fn each_style_has_distinct_highlight_and_shadow_from_base() {
        for style in 0..9u8 {
            let p = palette(style);
            assert_ne!(p.base, p.highlight, "style {style}: highlight==base");
            assert_ne!(p.base, p.shadow, "style {style}: shadow==base");
        }
    }

    /// Highlight must be brighter than base and shadow darker. Pins
    /// the visual semantics of the role names so future palette
    /// edits stay coherent.
    #[test]
    fn highlight_is_brighter_and_shadow_is_darker_than_base() {
        let brightness = |c: Color| c.r as u32 + c.g as u32 + c.b as u32;
        for style in 0..9u8 {
            let p = palette(style);
            let b = brightness(p.base);
            let h = brightness(p.highlight);
            let s = brightness(p.shadow);
            assert!(h >= b, "style {style}: highlight ({h}) must be >= base ({b})");
            assert!(s <= b, "style {style}: shadow ({s}) must be <= base ({b})");
        }
    }

    #[test]
    fn paint_fills_with_per_style_base_colour() {
        let path = one_tile_path();
        for style in 0..9u8 {
            let expected = palette(style).base;
            let mut p = MockPainter::default();
            let m = Material::new(Family::Stone, style, 0, 0, 0xCAFE);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}: expected 1 call");
            match &p.calls[0] {
                PainterCall::FillPath(_, paint, _) => {
                    assert_eq!(paint.color, expected, "style {style}");
                }
                other => panic!("expected FillPath, got {other:?}"),
            }
        }
    }
}
