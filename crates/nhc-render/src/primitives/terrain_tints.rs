//! Terrain tints — Phase 4.1, first deterministic primitive port.
//!
//! Reproduces the per-tile WATER / GRASS / LAVA / CHASM tint rect
//! emission and the per-room hint washes that
//! `_render_terrain_tints` produces. No RNG, no Perlin, no Shapely
//! — pure data-driven SVG string emission keyed on the IR's
//! palette-resolved tint colour + opacity and the room-wash list.
//!
//! The Python caller resolves the per-floor palette from the
//! theme string and passes a discriminant-keyed map across the
//! FFI boundary; the palette table itself stays Python-side
//! because it's display data (a static lookup), not procedural
//! logic. The dungeon-interior clip envelope also stays
//! Python-side — the IR's region polygon doesn't need to cross
//! the boundary just to be re-formatted.

use std::collections::HashMap;

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

#[cfg(test)]
mod tests {
    use super::draw_terrain_tints;

    use std::collections::HashMap;

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
}
