//! `Family::Wood` painter — species / tone / sub-pattern dispatch.
//!
//! 5 species (Oak, Walnut, Cherry, Pine, Weathered) × 4 tones
//! (Light, Medium, Dark, Charred) × 4 sub-patterns (Plank,
//! BasketWeave, Parquet, Herringbone) = 80 wood combinations. The
//! palette holds 60 colour entries (5 species × 4 tones × 3 roles
//! [base, highlight, shadow]); sub-patterns are algorithm-side, not
//! palette-side.
//!
//! Phase 2.3 of `plans/nhc_pure_ir_v5_migration_plan.md`. This
//! commit lifts the full (species × tone) palette out of the v4
//! ``wood_floor`` primitive (`crates/nhc-render/src/primitives/
//! wood_floor.rs::WOOD_SPECIES`), adds the Charred tone for each
//! species, and ships flat (species, tone) base fills. The per-
//! sub-pattern seam-grid layouts (Plank vertical seams, BasketWeave
//! alternating cells, Parquet 4×4 quadrants, Herringbone 45° lines)
//! and the per-plank grain-noise pass ship as additive Phase 2.3
//! follow-on commits. Phase 3.1's PSNR gate at the wood-floor
//! fixtures drives which seam / grain detail comes first.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct WoodToneEntry {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

const fn entry(base: u32, highlight: u32, shadow: u32) -> WoodToneEntry {
    WoodToneEntry {
        base: hex_to_color(base),
        highlight: hex_to_color(highlight),
        shadow: hex_to_color(shadow),
    }
}

const fn hex_to_color(rgb: u32) -> Color {
    let r = ((rgb >> 16) & 0xFF) as u8;
    let g = ((rgb >> 8) & 0xFF) as u8;
    let b = (rgb & 0xFF) as u8;
    Color::rgba(r, g, b, 1.0)
}

const N_SPECIES: usize = 5;
const N_TONES: usize = 4;

/// 5 species × 4 tones × 3 roles. Light / Medium / Dark are lifted
/// directly from the v4 ``WOOD_SPECIES`` table in
/// ``crates/nhc-render/src/primitives/wood_floor.rs``: the
/// ``(fill, grain_light, grain_dark)`` triple maps to ``(base,
/// highlight, shadow)``. Charred (the new 4th tone) is hand-picked
/// per species so the four tones read as a darkening progression.
const WOOD_PALETTE: [[WoodToneEntry; N_TONES]; N_SPECIES] = [
    // Oak — warm tan.
    [
        entry(0xC4A076, 0xD4B690, 0xA88058), // Light
        entry(0xB58B5A, 0xC4A076, 0x8F6540), // Medium
        entry(0x9B7548, 0xAC8A60, 0x7A5530), // Dark
        entry(0x402A18, 0x5A3E26, 0x281810), // Charred
    ],
    // Walnut — deep cocoa, redder hue.
    [
        entry(0x8C6440, 0xA07A55, 0x684A2C),
        entry(0x6E4F32, 0x8B6446, 0x523820),
        entry(0x553820, 0x6E4F32, 0x3F2818),
        entry(0x221810, 0x382A1C, 0x140C08),
    ],
    // Cherry — reddish brown, slight orange.
    [
        entry(0xB07A55, 0xC49075, 0x8E5C3A),
        entry(0x9B6442, 0xB07A55, 0x7A4D2E),
        entry(0x7E4F32, 0x955F44, 0x5F3820),
        entry(0x362018, 0x4C2E22, 0x1E120C),
    ],
    // Pine — pale honey, the lightest species.
    [
        entry(0xD8B888, 0xE6CDA8, 0xB8966C),
        entry(0xC4A176, 0xD8B888, 0xA48458),
        entry(0xA88556, 0xBFA070, 0x88683C),
        entry(0x443620, 0x5A4A30, 0x2A1F12),
    ],
    // Weathered grey — silvered teak / driftwood.
    [
        entry(0x8A8478, 0xA09A8E, 0x6E695F),
        entry(0x6E695F, 0x8A8478, 0x544F46),
        entry(0x544F46, 0x6E695F, 0x3D3932),
        entry(0x201C18, 0x322E28, 0x100C0A),
    ],
];

const SENTINEL: WoodToneEntry = WoodToneEntry {
    base: hex_to_color(0xFF00FF),
    highlight: hex_to_color(0xFF00FF),
    shadow: hex_to_color(0xFF00FF),
};

pub(crate) fn palette(style: u8, tone: u8) -> WoodToneEntry {
    let s = style as usize;
    let t = tone as usize;
    if s >= N_SPECIES || t >= N_TONES {
        return SENTINEL;
    }
    WOOD_PALETTE[s][t]
}

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    let entry = palette(material.style, material.tone);
    fill_region(painter, region_path, entry.base);
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
    fn palette_holds_sixty_distinct_colour_entries() {
        // 5 species × 4 tones × 3 roles = 60 colour entries; the
        // (base, highlight, shadow) within one (species, tone)
        // entry must all be distinct, and each entry's base must
        // differ from every other entry's base across the matrix.
        let mut bases = Vec::with_capacity(N_SPECIES * N_TONES);
        for s in 0..N_SPECIES as u8 {
            for t in 0..N_TONES as u8 {
                let entry = palette(s, t);
                assert_ne!(entry.base, entry.highlight, "(s={s}, t={t}) base==highlight");
                assert_ne!(entry.base, entry.shadow, "(s={s}, t={t}) base==shadow");
                let key = (entry.base.r, entry.base.g, entry.base.b);
                assert!(
                    !bases.contains(&key),
                    "duplicate base colour at (s={s}, t={t}): {key:?}"
                );
                bases.push(key);
            }
        }
        assert_eq!(bases.len(), N_SPECIES * N_TONES);
    }

    /// Within a species, the 4 tones must be a darkening progression:
    /// Light > Medium > Dark > Charred (sum of channels). Pins the
    /// "tone is a darkening axis" contract from §4.3 of map_ir_v5.md.
    #[test]
    fn tones_within_each_species_decrease_in_brightness() {
        for s in 0..N_SPECIES as u8 {
            let brightness = |t: u8| {
                let c = palette(s, t).base;
                c.r as u32 + c.g as u32 + c.b as u32
            };
            let light = brightness(0);
            let medium = brightness(1);
            let dark = brightness(2);
            let charred = brightness(3);
            assert!(light > medium, "species {s}: Light ({light}) <= Medium ({medium})");
            assert!(medium > dark, "species {s}: Medium ({medium}) <= Dark ({dark})");
            assert!(dark > charred, "species {s}: Dark ({dark}) <= Charred ({charred})");
        }
    }

    #[test]
    fn paint_fills_with_species_tone_base_colour() {
        let path = one_tile_path();
        for (style, tone) in [(0u8, 0u8), (1, 2), (4, 3), (3, 1)] {
            let expected = palette(style, tone).base;
            let mut p = MockPainter::default();
            let m = Material::new(Family::Wood, style, 0, tone, 0xCAFE);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "(s={style}, t={tone}): expected 1 call");
            match &p.calls[0] {
                PainterCall::FillPath(_, paint, _) => {
                    assert_eq!(paint.color, expected, "(s={style}, t={tone})");
                }
                other => panic!("expected FillPath, got {other:?}"),
            }
        }
    }

    #[test]
    fn out_of_range_indices_resolve_to_sentinel() {
        let entry = palette(99, 99);
        assert_eq!(entry, SENTINEL);
    }
}
