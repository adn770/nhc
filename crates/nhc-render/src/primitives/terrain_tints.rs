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
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_terrain_tints` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until 2.17
//!   ships the `SvgPainter`-based PyO3 export and 2.19 retires
//!   the Python `ir_to_svg` path).
//! - The new `paint_terrain_tints` Painter-friendly emitter that
//!   issues `fill_rect` calls. Used by the Rust `transform/png`
//!   path via `SkiaPainter` and, after 2.17, by the Rust
//!   `ir_to_svg` path via `SvgPainter`.

use std::collections::HashMap;

use crate::painter::{Color, Paint, Painter, Rect};

const CELL: i32 = 32;

/// Emit the layer's two SVG fragment lists.
///
/// - `tiles`: `(x, y, kind)` triples — `kind` is the
///   `TerrainKind` discriminant from `floor_ir.fbs`
///   (`Water=1`, `Lava=2`, `Chasm=3`, `Grass=4`; `None=0` is the
///   schema's reserved sentinel and never reaches this function).
///   Tiles whose `kind` has no palette entry are silently
///   skipped — mirrors the Python handler's `style is None`
///   short-circuit so a future schema addition (e.g. a fifth
///   terrain) doesn't break older rendering paths.
/// - `palette`: discriminant-keyed map of
///   `(tint_color, tint_opacity)`. The opacity is formatted with
///   Rust's `{}` (shortest-roundtrip) — matches Python's
///   `f"{x}"` for the values the palette table uses (`0.06` to
///   `0.25`, all clean two-digit decimals).
/// - `washes`: `(x, y, w, h, color, opacity)` tuples for the
///   `ROOM_TYPE_TINTS`-driven hints. Opacity is formatted with
///   `{:.2}` — the IR's `RoomWash.opacity` is a float and the
///   legacy `f"{w.opacity:.2f}"` dodges the float32 round-trip
///   on values like `0.06`.
///
/// Returns `(tint_rects, wash_rects)`. The Python handler stitches
/// these into the final layer fragment, wrapping `tint_rects` in
/// the dungeon-interior clip envelope when the IR carries one.
pub fn draw_terrain_tints(
    tiles: &[(i32, i32, u8)],
    palette: &HashMap<u8, (String, f64)>,
    washes: &[(i32, i32, i32, i32, String, f64)],
) -> (Vec<String>, Vec<String>) {
    let mut tint_rects = Vec::with_capacity(tiles.len());
    for &(x, y, kind) in tiles {
        let Some((tint, opacity)) = palette.get(&kind) else {
            continue;
        };
        tint_rects.push(format!(
            "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" \
             fill=\"{}\" opacity=\"{}\"/>",
            x * CELL,
            y * CELL,
            CELL,
            CELL,
            tint,
            opacity,
        ));
    }
    let mut wash_rects = Vec::with_capacity(washes.len());
    for (x, y, w, h, color, opacity) in washes {
        wash_rects.push(format!(
            "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" \
             fill=\"{}\" opacity=\"{:.2}\"/>",
            x * CELL,
            y * CELL,
            w * CELL,
            h * CELL,
            color,
            opacity,
        ));
    }
    (tint_rects, wash_rects)
}

/// Painter-path twin of `draw_terrain_tints`. Issues one
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
/// Hex parsing happens inline (palette is ≤ 5 entries — cheap)
/// to keep the API surface symmetrical with `draw_terrain_tints`.
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
    use super::{draw_terrain_tints, paint_terrain_tints};
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

    #[test]
    fn empty_inputs_return_empty_buckets() {
        let palette = dungeon_palette();
        let (tints, washes) = draw_terrain_tints(&[], &palette, &[]);
        assert!(tints.is_empty());
        assert!(washes.is_empty());
    }

    #[test]
    fn water_tile_at_origin_matches_legacy_format() {
        let palette = dungeon_palette();
        let (tints, _) = draw_terrain_tints(
            &[(0, 0, 1)], // discriminant 1 → Water
            &palette,
            &[],
        );
        assert_eq!(
            tints[0],
            "<rect x=\"0\" y=\"0\" width=\"32\" height=\"32\" \
             fill=\"#8BB8D0\" opacity=\"0.15\"/>"
        );
    }

    #[test]
    fn lava_tile_offset_uses_pixel_coords() {
        // (x=2, y=3) should land at (64, 96) in pixel space.
        let palette = dungeon_palette();
        let (tints, _) = draw_terrain_tints(
            &[(2, 3, 2)], // discriminant 2 → Lava
            &palette,
            &[],
        );
        assert_eq!(
            tints[0],
            "<rect x=\"64\" y=\"96\" width=\"32\" height=\"32\" \
             fill=\"#D4816B\" opacity=\"0.18\"/>"
        );
    }

    #[test]
    fn unknown_kind_is_skipped() {
        // Discriminant 99 has no palette entry — handler skips
        // it. Mirrors the Python `style is None` short-circuit.
        let palette = dungeon_palette();
        let (tints, _) = draw_terrain_tints(
            &[(0, 0, 99)],
            &palette,
            &[],
        );
        assert!(tints.is_empty());
    }

    #[test]
    fn none_discriminant_is_skipped() {
        // Schema reserves discriminant 0 for `None`; it never
        // appears in valid IR but the function should still
        // skip it cleanly if it does.
        let palette = dungeon_palette();
        let (tints, _) = draw_terrain_tints(
            &[(0, 0, 0)],
            &palette,
            &[],
        );
        assert!(tints.is_empty());
    }

    #[test]
    fn room_wash_opacity_uses_two_decimal_format() {
        // 0.06 surfaces as "0.05999999..." under default float
        // repr if it round-trips through f32 — the `:.2` width is
        // what dodges that. The IR's RoomWash.opacity stays f64
        // here, but the contract is the format spec.
        let palette = dungeon_palette();
        let (_, washes) = draw_terrain_tints(
            &[],
            &palette,
            &[(1, 2, 5, 4, "#aabbcc".to_string(), 0.06)],
        );
        assert_eq!(
            washes[0],
            "<rect x=\"32\" y=\"64\" width=\"160\" height=\"128\" \
             fill=\"#aabbcc\" opacity=\"0.06\"/>"
        );
    }

    // ── Painter-path tests ─────────────────────────────────────

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
