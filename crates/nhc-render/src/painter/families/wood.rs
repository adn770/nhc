//! `Family::Wood` painter — Phase 1.2 stub.
//!
//! 5 species (Oak, Walnut, Cherry, Pine, Weathered) × 4 sub-
//! patterns (Plank, BasketWeave, Parquet, Herringbone) × 4 tones
//! (Light, Medium, Dark, Charred). Phase 1.2 ships a sentinel
//! palette keyed by `(style, tone)`; layout sub-patterns are stubs.
//! Phase 2.3 lifts today's wood-floor pipeline (per-region species
//! / tone resolution from regionRef hash, per-plank grain noise
//! from seed) into this dispatcher.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

/// Stub palette keyed by tone. Phase 2.3 widens this to a full
/// (species, tone) → (base, highlight, shadow) table.
fn stub_color(tone: u8) -> Color {
    match tone {
        // Light
        0 => Color::rgba(0xCC, 0xA8, 0x73, 1.0),
        // Medium
        1 => Color::rgba(0xB5, 0x8B, 0x5A, 1.0),
        // Dark
        2 => Color::rgba(0x7A, 0x57, 0x33, 1.0),
        // Charred
        3 => Color::rgba(0x35, 0x29, 0x1B, 1.0),
        _ => Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    }
}

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    fill_region(painter, region_path, stub_color(material.tone));
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
    fn medium_tone_paints_brown_baseline() {
        let mut p = MockPainter::default();
        let path = one_tile_path();
        let m = Material::new(Family::Wood, 0, 0, 1, 0);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            PainterCall::FillPath(_, paint, _) => {
                assert_eq!(paint.color.r, 0xB5);
                assert_eq!(paint.color.g, 0x8B);
                assert_eq!(paint.color.b, 0x5A);
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }
}
