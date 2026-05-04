//! Terrain tints — Phase 4.1, first deterministic primitive port,
//! ported to the Painter trait in Phase 2.8 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Reproduces the per-tile WATER / GRASS / LAVA / CHASM tint rect
//! emission and the per-room hint washes that
//! `_render_terrain_tints` produces. No RNG, no Perlin, no Shapely
//! — pure data-driven emission keyed on the IR's palette-resolved
//! tint colour + opacity and the room-wash list.
//!
//! The Python caller resolves the per-floor palette from the
//! theme string and passes a discriminant-keyed map across the
//! FFI boundary; the palette table itself stays Python-side
//! because it's display data (a static lookup), not procedural
//! logic. The dungeon-interior clip envelope also stays
//! Python-side — the IR's region polygon doesn't need to cross
//! the boundary just to be re-formatted.
//!
//! Phase 2.19 retired the legacy `draw_terrain_tints` SVG-string
//! emitter; the only remaining surface is the Painter-friendly
//! `paint_terrain_tints`, used by both `transform/png` (via
//! `SkiaPainter`) and `transform/svg` (via `SvgPainter`).

use std::collections::HashMap;

use crate::painter::{Color, Paint, Painter, Rect};

const CELL: i32 = 32;

/// Painter-path emitter. Issues one
/// `fill_rect` per tile tint and one per room wash, in document
/// order: tile tints first (the Python handler wraps these in a
/// dungeon-interior clip envelope; the PNG Painter handler does
/// the same via `push_clip` / `pop_clip` around the call), then
/// the unclipped washes layered on top.
///
/// Tiles whose discriminant has no palette entry are silently
/// skipped — mirrors the legacy `style is None` short-circuit so
/// a future schema addition (e.g. a fifth terrain) doesn't break
/// older rendering paths.
///
/// Hex parsing happens inline (palette is ≤ 5 entries — cheap).
/// Malformed hexes fall back to transparent black, matching the
/// legacy PNG handler's `parse_hex_rgb` `unwrap_or((0, 0, 0))`
/// behaviour.
pub fn paint_terrain_tints(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32, u8)],
    palette: &HashMap<u8, (String, f64)>,
    washes: &[(i32, i32, i32, i32, String, f64)],
) {
    for &(x, y, kind) in tiles {
        let Some((tint, opacity)) = palette.get(&kind) else {
            continue;
        };
        let paint = build_paint(tint, *opacity);
        let rect = Rect::new(
            (x * CELL) as f32,
            (y * CELL) as f32,
            CELL as f32,
            CELL as f32,
        );
        painter.fill_rect(rect, &paint);
    }
    for (x, y, w, h, color, opacity) in washes {
        let paint = build_paint(color, *opacity);
        let rect = Rect::new(
            (x * CELL) as f32,
            (y * CELL) as f32,
            (w * CELL) as f32,
            (h * CELL) as f32,
        );
        painter.fill_rect(rect, &paint);
    }
}

fn parse_hex_rgb(s: &str) -> Option<(u8, u8, u8)> {
    let s = s.strip_prefix('#')?;
    if s.len() != 6 {
        return None;
    }
    let r = u8::from_str_radix(&s[0..2], 16).ok()?;
    let g = u8::from_str_radix(&s[2..4], 16).ok()?;
    let b = u8::from_str_radix(&s[4..6], 16).ok()?;
    Some((r, g, b))
}

fn build_paint(hex: &str, opacity: f64) -> Paint {
    let (r, g, b) = parse_hex_rgb(hex).unwrap_or((0, 0, 0));
    let a = (opacity as f32).clamp(0.0, 1.0);
    Paint::solid(Color::rgba(r, g, b, a))
}

#[cfg(test)]
mod tests {
    use super::paint_terrain_tints;
    use crate::painter::{Color, FillRule, Paint, Painter, PathOps, Rect, Stroke, Vec2};

    use std::collections::HashMap;

    /// Records every Painter call. Mirrors the trait-level
    /// `MockPainter` in `painter::tests` but lives in this module
    /// so the assertions stay close to the primitive.
    #[derive(Debug, Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
    }

    #[derive(Debug, PartialEq)]
    enum Call {
        FillRect(Rect, Paint),
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, rect: Rect, paint: &Paint) {
            self.calls.push(Call::FillRect(rect, *paint));
        }
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {}
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_ellipse(&mut self, _: f32, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {}
        fn stroke_polyline(&mut self, _: &[Vec2], _: &Paint, _: &Stroke) {}
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {}
        fn stroke_path(&mut self, _: &PathOps, _: &Paint, _: &Stroke) {}
        fn begin_group(&mut self, _: f32) {}
        fn end_group(&mut self) {}
        fn push_clip(&mut self, _: &PathOps, _: FillRule) {}
        fn pop_clip(&mut self) {}
        fn push_transform(&mut self, _: crate::painter::Transform) {}
        fn pop_transform(&mut self) {}
    }

    fn dungeon_palette() -> HashMap<u8, (String, f64)> {
        // Mirrors `THEME_PALETTES["dungeon"]` in
        // `nhc/rendering/terrain_palette.py`, keyed on the
        // `TerrainKind` discriminants from `floor_ir.fbs`
        // (Water=1, Lava=2, Chasm=3, Grass=4 — None=0 reserved).
        // Kept inline so a Rust-only regression bisects without
        // rebuilding the maturin wheel.
        let mut p = HashMap::new();
        p.insert(1, ("#8BB8D0".to_string(), 0.15)); // Water
        p.insert(2, ("#D4816B".to_string(), 0.18)); // Lava
        p.insert(3, ("#888888".to_string(), 0.10)); // Chasm
        p.insert(4, ("#7BA87B".to_string(), 0.12)); // Grass
        p
    }

    /// No tiles + no washes → zero painter calls. Sanity check
    /// that the layer-level driver doesn't issue spurious paints.
    #[test]
    fn paint_terrain_tints_no_inputs_emits_no_calls() {
        let palette = dungeon_palette();
        let mut painter = CaptureCalls::default();
        paint_terrain_tints(&mut painter, &[], &palette, &[]);
        assert!(painter.calls.is_empty());
    }

    /// One Water tile (kind=1) + dungeon palette → one fill_rect
    /// at (0, 0, 32, 32) with the palette's `#8BB8D0` colour and
    /// 0.15 opacity.
    #[test]
    fn paint_terrain_tints_one_water_tile_fills_palette_color() {
        let palette = dungeon_palette();
        let mut painter = CaptureCalls::default();
        paint_terrain_tints(&mut painter, &[(0, 0, 1)], &palette, &[]);
        assert_eq!(painter.calls.len(), 1);
        let expected_paint = Paint::solid(Color::rgba(0x8B, 0xB8, 0xD0, 0.15));
        assert_eq!(
            painter.calls[0],
            Call::FillRect(Rect::new(0.0, 0.0, 32.0, 32.0), expected_paint)
        );
    }

    /// Lava tile at (2, 3) → fill_rect at pixel (64, 96) with
    /// `#D4816B` / 0.18, mirroring the legacy SVG pixel-coord
    /// arithmetic.
    #[test]
    fn paint_terrain_tints_lava_tile_uses_pixel_coords() {
        let palette = dungeon_palette();
        let mut painter = CaptureCalls::default();
        paint_terrain_tints(&mut painter, &[(2, 3, 2)], &palette, &[]);
        assert_eq!(painter.calls.len(), 1);
        let expected_paint = Paint::solid(Color::rgba(0xD4, 0x81, 0x6B, 0.18));
        assert_eq!(
            painter.calls[0],
            Call::FillRect(Rect::new(64.0, 96.0, 32.0, 32.0), expected_paint)
        );
    }

    /// Tile whose discriminant has no palette entry → no
    /// fill_rect emitted. Mirrors the legacy `style is None`
    /// short-circuit for forward-schema-compat.
    #[test]
    fn paint_terrain_tints_unknown_kind_emits_no_fill_rect() {
        let palette = dungeon_palette();
        let mut painter = CaptureCalls::default();
        paint_terrain_tints(&mut painter, &[(0, 0, 99)], &palette, &[]);
        assert!(painter.calls.is_empty());
    }

    /// One wash → one fill_rect at the bbox in pixel coords with
    /// the wash's colour + opacity. Coords are integer-aligned so
    /// no precision drift; opacity round-trips f64 → f32 cleanly
    /// through `Color::rgba`'s `a: f32` field — same path as the
    /// legacy `paint_for(hex, opacity: f32)`.
    #[test]
    fn paint_terrain_tints_one_wash_fills_bbox() {
        let palette = dungeon_palette();
        let mut painter = CaptureCalls::default();
        paint_terrain_tints(
            &mut painter,
            &[],
            &palette,
            &[(1, 2, 5, 4, "#aabbcc".to_string(), 0.06)],
        );
        assert_eq!(painter.calls.len(), 1);
        let expected_paint = Paint::solid(Color::rgba(0xAA, 0xBB, 0xCC, 0.06));
        assert_eq!(
            painter.calls[0],
            Call::FillRect(Rect::new(32.0, 64.0, 160.0, 128.0), expected_paint)
        );
    }

    /// Tiles emit before washes — mirrors the legacy handler's
    /// document order (tile tints clipped, washes layered on top).
    #[test]
    fn paint_terrain_tints_tiles_precede_washes() {
        let palette = dungeon_palette();
        let mut painter = CaptureCalls::default();
        paint_terrain_tints(
            &mut painter,
            &[(0, 0, 1), (1, 0, 4)],
            &palette,
            &[(0, 1, 2, 1, "#112233".to_string(), 0.10)],
        );
        assert_eq!(painter.calls.len(), 3);
        // First two calls are tiles at (0,0) and (32,0).
        let Call::FillRect(rect0, _) = painter.calls[0];
        assert_eq!(rect0, Rect::new(0.0, 0.0, 32.0, 32.0));
        let Call::FillRect(rect1, _) = painter.calls[1];
        assert_eq!(rect1, Rect::new(32.0, 0.0, 32.0, 32.0));
        // Third call is the wash at (0*32, 1*32, 2*32, 1*32).
        let Call::FillRect(rect2, _) = painter.calls[2];
        assert_eq!(rect2, Rect::new(0.0, 32.0, 64.0, 32.0));
    }
}
