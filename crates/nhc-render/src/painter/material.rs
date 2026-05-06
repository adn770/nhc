//! Per-family Material painter dispatch — Phase 1.2 of
//! `plans/nhc_pure_ir_v5_migration_plan.md`.
//!
//! v5 ships floors / surfaces / liquid substrates as a single
//! `(family, style, sub_pattern, tone, seed)` tuple. The painter
//! dispatches on `Family` to seven per-family pipelines. At
//! Phase 1.2 each family is a stub: it paints the region with a
//! placeholder colour so the dispatcher contract compiles and
//! the test surface is in place. Full per-style / per-tone
//! palettes land family-by-family in Phase 2.
//!
//! `Material` and `Family` here are backend-agnostic Rust mirrors
//! of the `V5Material` / `MaterialFamily` FlatBuffers types.
//! Op handlers (Phase 1.3) bridge from the FB reader types into
//! these PODs before calling `paint_material`. Keeping the painter
//! input as POD lets per-backend tests construct fixtures without
//! a FlatBuffers builder.

use crate::painter::{Color, FillRule, Paint, Painter, PathOps};

/// Per-family stable identifier. Mirrors
/// `nhc.rendering.ir._fb.MaterialFamily` value-for-value
/// (Plain=0, Cave=1, Wood=2, Stone=3, Earth=4, Liquid=5,
/// Special=6). The atomic cut at Phase 1.8 renames the FB enum
/// to `MaterialFamily`; this Rust mirror's name stays as `Family`
/// to read fluently inside the painter module.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Family {
    Plain,
    Cave,
    Wood,
    Stone,
    Earth,
    Liquid,
    Special,
}

/// Backend-agnostic Material POD.
///
/// `style`, `sub_pattern`, and `tone` are family-specific indices.
/// Per-family interpretation is documented in
/// `design/map_ir_v5.md` §4.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Material {
    pub family: Family,
    pub style: u8,
    pub sub_pattern: u8,
    pub tone: u8,
    pub seed: u64,
}

impl Material {
    pub const fn new(family: Family, style: u8, sub_pattern: u8, tone: u8, seed: u64) -> Self {
        Self {
            family,
            style,
            sub_pattern,
            tone,
            seed,
        }
    }
}

/// Stub-period fallback colour. Each family stub paints with this
/// when its palette table is empty (Phase 1.2 — every family stub
/// resolves to a sentinel hue keyed by family ordinal so visual
/// inspection during scaffold work flags un-implemented coverage).
/// Phase 2 commits replace per-family stubs with real palettes.
pub const V5_MATERIAL_FALLBACK_COLOR: Color = Color::rgba(0xFF, 0x00, 0xFF, 1.0);

/// Dispatch into the correct family pipeline.
///
/// Takes a region path (already resolved by the caller — typically
/// the v5 `PaintOp` handler in Phase 1.3) plus the Material, and
/// fills with the family-specific algorithm. The dispatcher itself
/// is dead-simple: a match on `material.family` that fans out into
/// the per-family `paint` function. Adding a new family is one
/// arm here plus a new module under `painter/families/`.
pub fn paint_material<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    material: &Material,
) {
    match material.family {
        Family::Plain => super::families::plain::paint(painter, region_path, material),
        Family::Cave => super::families::cave::paint(painter, region_path, material),
        Family::Wood => super::families::wood::paint(painter, region_path, material),
        Family::Stone => super::families::stone::paint(painter, region_path, material),
        Family::Earth => super::families::earth::paint(painter, region_path, material),
        Family::Liquid => super::families::liquid::paint(painter, region_path, material),
        Family::Special => super::families::special::paint(painter, region_path, material),
    }
}

/// Convenience helper consumed by per-family stubs: paint the
/// region path with a single solid colour. Phase 2 painters
/// replace this with per-style algorithms; the helper stays for
/// the simple `Plain` family that always paints a flat fill.
pub(crate) fn fill_region<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    color: Color,
) {
    let paint = Paint::solid(color);
    painter.fill_path(region_path, &paint, FillRule::Winding);
}

/// Per-family palette role. Wall strokes typically pull `Shadow`
/// (the substance's seam / mortar colour); decorator overlays may
/// pull `Highlight`. Phase 2.8 uses this from the v5 StrokeOp
/// dispatcher to derive substance-aware ink from the wall material.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PaletteRole {
    Base,
    Highlight,
    Shadow,
}

/// Resolve a substance palette colour from `(family, style, tone)`
/// and the requested role. Bridges the per-family palette tables
/// (defined module-locally in `families/<family>.rs`) into a
/// single dispatch surface that the v5 op handlers can call without
/// knowing about per-family colour types.
///
/// `style` and `tone` are family-specific indices; out-of-range
/// values fall back to the per-family sentinel palette (magenta) so
/// painter coverage gaps surface visually rather than silently.
pub fn substance_color(
    family: Family,
    style: u8,
    tone: u8,
    role: PaletteRole,
) -> Color {
    use super::families::{cave, earth, liquid, plain, special, stone, wood};
    match family {
        Family::Plain => match role {
            PaletteRole::Base => plain::PLAIN_FILL,
            PaletteRole::Highlight => plain::PLAIN_HIGHLIGHT,
            PaletteRole::Shadow => plain::PLAIN_SHADOW,
        },
        Family::Cave => {
            let p = cave::palette(style);
            match role {
                PaletteRole::Base => p.base,
                PaletteRole::Highlight => p.highlight,
                PaletteRole::Shadow => p.shadow,
            }
        }
        Family::Wood => {
            let p = wood::palette(style, tone);
            match role {
                PaletteRole::Base => p.base,
                PaletteRole::Highlight => p.highlight,
                PaletteRole::Shadow => p.shadow,
            }
        }
        Family::Stone => {
            let p = stone::palette(style);
            match role {
                PaletteRole::Base => p.base,
                PaletteRole::Highlight => p.highlight,
                PaletteRole::Shadow => p.shadow,
            }
        }
        Family::Earth => {
            let p = earth::palette(style);
            match role {
                PaletteRole::Base => p.base,
                PaletteRole::Highlight => p.highlight,
                PaletteRole::Shadow => p.shadow,
            }
        }
        Family::Liquid => {
            let p = liquid::palette(style);
            match role {
                PaletteRole::Base => p.base,
                PaletteRole::Highlight => p.highlight,
                PaletteRole::Shadow => p.shadow,
            }
        }
        Family::Special => {
            let p = special::palette(style);
            match role {
                PaletteRole::Base => p.base,
                PaletteRole::Highlight => p.highlight,
                PaletteRole::Shadow => p.shadow,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::test_util::{MockPainter, PainterCall};
    use crate::painter::Vec2;

    fn unit_square_path() -> PathOps {
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(1.0, 0.0))
            .line_to(Vec2::new(1.0, 1.0))
            .line_to(Vec2::new(0.0, 1.0))
            .close();
        p
    }

    /// Each family dispatcher must emit at least one fill_path call
    /// for the region. Stubs at Phase 1.2 emit exactly one; future
    /// per-family painters may emit more (per-tile decorators,
    /// stamping passes) but the smoke test pins "fan-out works".
    #[test]
    fn every_family_emits_at_least_one_paint_call() {
        let path = unit_square_path();
        for family in [
            Family::Plain,
            Family::Cave,
            Family::Wood,
            Family::Stone,
            Family::Earth,
            Family::Liquid,
            Family::Special,
        ] {
            let mut p = MockPainter::default();
            let m = Material::new(family, 0, 0, 0, 0);
            paint_material(&mut p, &path, &m);
            assert!(
                !p.calls.is_empty(),
                "family {family:?} dispatcher emitted no painter calls"
            );
        }
    }

    /// Per-family stubs at Phase 1.2 paint a single fill_path. Pin
    /// the call shape so a future regression that drops the path
    /// (and instead, say, pushes a clip and forgets to draw) gets
    /// caught. The exact colour is family-specific (each stub picks
    /// a sentinel hue) and pinned in per-family unit tests.
    #[test]
    fn plain_family_emits_one_fill_path_call() {
        let path = unit_square_path();
        let mut p = MockPainter::default();
        let m = Material::new(Family::Plain, 0, 0, 0, 0);
        paint_material(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        assert!(matches!(p.calls[0], PainterCall::FillPath(_, _, _)));
    }

    /// Smoke test that every (family, style, sub_pattern, tone)
    /// quadruple in the *core* axis space (the smallest cross-product
    /// each family supports) dispatches without panicking. Phase 2
    /// will widen each family's axis space; this test grows alongside.
    #[test]
    fn dispatcher_does_not_panic_on_axis_corners() {
        let path = unit_square_path();
        let cases: &[(Family, u8, u8, u8)] = &[
            (Family::Plain, 0, 0, 0),
            (Family::Cave, 0, 0, 0),
            (Family::Cave, 3, 0, 0),
            (Family::Wood, 0, 0, 0),
            (Family::Wood, 4, 3, 3),
            (Family::Stone, 0, 0, 0),
            (Family::Stone, 8, 1, 2),
            (Family::Earth, 3, 0, 0),
            (Family::Liquid, 0, 0, 0),
            (Family::Liquid, 1, 0, 0),
            (Family::Special, 3, 0, 0),
        ];
        for (fam, st, sp, tn) in cases {
            let mut p = MockPainter::default();
            let m = Material::new(*fam, *st, *sp, *tn, 0xCAFE);
            paint_material(&mut p, &path, &m);
            assert!(
                !p.calls.is_empty(),
                "({fam:?}, {st}, {sp}, {tn}) emitted no calls"
            );
        }
    }
}
