//! Shadow primitive — Phase 4.2, second deterministic port.
//!
//! Reproduces `_render_corridor_shadows` (per-tile offset rects)
//! and `_room_shadow_svg` (per-shape room shadows) from
//! `nhc/rendering/_shadows.py`. No RNG, no Perlin. Cave room
//! shadows go through `crate::geometry::smooth_closed_path`
//! (centripetal Catmull-Rom → cubic Bézier) — that helper's
//! cross-language gate covers the FP arithmetic byte-equality
//! contract this primitive depends on.
//!
//! Design constants (`+3` offset, `0.08` opacity, `#000000`
//! ink) are baked in here. The schema's `dx` / `dy` / `opacity`
//! fields on `ShadowOp` are intentionally ignored to dodge the
//! float32 round-trip on `0.08` (which would surface as
//! `"0.07999999821186066"`); the legacy renderer used hardcoded
//! literals and the Phase 4 port preserves that contract.

use crate::geometry::smooth_closed_path;

const CELL: i32 = 32;
const INK: &str = "#000000";
const OPACITY: &str = "0.08";

/// Per-tile corridor shadow rects.
///
/// `tiles` is a list of `(x, y)` tile coords already filtered by
/// the IR emitter to corridor / door tiles. The Python handler at
/// `ir_to_svg.py:_draw_shadow_from_ir` walks the IR's `op.tiles`
/// and crosses the FFI boundary with a flat list.
pub fn draw_corridor_shadows(tiles: &[(i32, i32)]) -> Vec<String> {
    let mut out = Vec::with_capacity(tiles.len());
    for &(x, y) in tiles {
        let px = x * CELL + 3;
        let py = y * CELL + 3;
        out.push(format!(
            "<rect x=\"{px}\" y=\"{py}\" width=\"{CELL}\" \
             height=\"{CELL}\" fill=\"{INK}\" opacity=\"{OPACITY}\"/>"
        ));
    }
    out
}

/// Rect-shape room shadow — single `<rect>` with bbox baked in
/// and the `+3` offset folded into the x / y attributes.
///
/// Coords are integer-valued in pixel space (CELL × tile-int)
/// from `_room_region_data`; truncating to `i32` matches Python's
/// `int(x)` semantics for non-negative inputs.
pub fn draw_room_shadow_rect(coords: &[(f64, f64)]) -> String {
    let mut min_x = i32::MAX;
    let mut max_x = i32::MIN;
    let mut min_y = i32::MAX;
    let mut max_y = i32::MIN;
    for &(x, y) in coords {
        let xi = x as i32;
        let yi = y as i32;
        if xi < min_x {
            min_x = xi;
        }
        if xi > max_x {
            max_x = xi;
        }
        if yi < min_y {
            min_y = yi;
        }
        if yi > max_y {
            max_y = yi;
        }
    }
    let px = min_x + 3;
    let py = min_y + 3;
    let pw = max_x - min_x;
    let ph = max_y - min_y;
    format!(
        "<rect x=\"{px}\" y=\"{py}\" width=\"{pw}\" height=\"{ph}\" \
         fill=\"{INK}\" opacity=\"{OPACITY}\"/>"
    )
}

/// Octagon-shape room shadow — `<polygon>` element wrapped in
/// `<g transform="translate(3,3)">`. Points format with `{:.1}`
/// to match the legacy `f"{x:.1f}"`.
pub fn draw_room_shadow_octagon(coords: &[(f64, f64)]) -> String {
    let points: Vec<String> = coords
        .iter()
        .map(|(x, y)| format!("{x:.1},{y:.1}"))
        .collect();
    let outline = format!("<polygon points=\"{}\"/>", points.join(" "));
    wrap_outline(&outline)
}

/// Cave-shape room shadow — Catmull-Rom-smoothed `<path>`
/// wrapped in `<g transform="translate(3,3)">`. The smoothing
/// helper lives in `crate::geometry` so other cave-themed
/// primitives can reuse it.
pub fn draw_room_shadow_cave(coords: &[(f64, f64)]) -> String {
    let outline = smooth_closed_path(coords);
    wrap_outline(&outline)
}

/// Mirror `_shadows._room_shadow_svg`'s outline wrap: inject
/// fill + opacity on the trailing `/>` of the outline element,
/// then wrap with a translate-by-(3,3) group.
fn wrap_outline(outline: &str) -> String {
    let injected =
        outline.replace("/>", &format!(" fill=\"{INK}\" opacity=\"{OPACITY}\"/>"));
    format!("<g transform=\"translate(3,3)\">{injected}</g>")
}

#[cfg(test)]
mod tests {
    use super::{
        draw_corridor_shadows, draw_room_shadow_octagon,
        draw_room_shadow_rect,
    };

    #[test]
    fn empty_corridor_tiles_returns_empty_vec() {
        assert!(draw_corridor_shadows(&[]).is_empty());
    }

    #[test]
    fn corridor_tile_at_origin_has_plus_three_offset() {
        let out = draw_corridor_shadows(&[(0, 0)]);
        assert_eq!(
            out[0],
            "<rect x=\"3\" y=\"3\" width=\"32\" height=\"32\" \
             fill=\"#000000\" opacity=\"0.08\"/>"
        );
    }

    #[test]
    fn corridor_tile_at_offset_uses_pixel_coords() {
        // (x=2, y=3) → pixel (64, 96), then +3 offset → (67, 99).
        let out = draw_corridor_shadows(&[(2, 3)]);
        assert_eq!(
            out[0],
            "<rect x=\"67\" y=\"99\" width=\"32\" height=\"32\" \
             fill=\"#000000\" opacity=\"0.08\"/>"
        );
    }

    #[test]
    fn room_rect_shadow_uses_bbox_and_plus_three_offset() {
        // 64×96 rect at origin (0,0) → x=3, y=3, width=64, height=96.
        let coords = [(0.0, 0.0), (64.0, 0.0), (64.0, 96.0), (0.0, 96.0)];
        assert_eq!(
            draw_room_shadow_rect(&coords),
            "<rect x=\"3\" y=\"3\" width=\"64\" height=\"96\" \
             fill=\"#000000\" opacity=\"0.08\"/>"
        );
    }

    #[test]
    fn room_octagon_shadow_wraps_polygon_in_translate() {
        let coords = [
            (10.0, 0.0),
            (20.0, 0.0),
            (30.0, 10.0),
            (30.0, 20.0),
            (20.0, 30.0),
            (10.0, 30.0),
            (0.0, 20.0),
            (0.0, 10.0),
        ];
        let out = draw_room_shadow_octagon(&coords);
        assert!(out.starts_with("<g transform=\"translate(3,3)\"><polygon points=\""));
        assert!(out.ends_with(" fill=\"#000000\" opacity=\"0.08\"/></g>"));
        assert!(out.contains("10.0,0.0 20.0,0.0"));
    }
}
