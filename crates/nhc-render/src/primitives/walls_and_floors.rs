//! Walls + floors primitive — Phase 4.4, fourth deterministic
//! port. Partial per the migration plan: structural geometry
//! (smooth-room outlines, cave region paths, wall extension
//! computations) stays Python-side and travels into Rust as
//! pre-rendered SVG fragment strings; only the stroke-emission
//! envelope (rect emission, the `</>`-replacement injection of
//! fill/stroke attributes) moves here.
//!
//! No RNG, no Perlin. The byte-equal contract is mostly string
//! passthrough — the only real work is the corridor / rect-room
//! emission and the two `replace("/>"...)` wraps around the cave
//! region path.
//!
//! `WALL_WIDTH = "5.0"` is encoded as `&str` (same trap as the
//! stairs primitive — Python's bare `{}` formatter on `5.0_f64`
//! emits `"5.0"`, Rust's `{}` strips the trailing zero). Coords
//! are integer-valued (i32 × CELL) so they round-trip cleanly
//! with default integer formatting.

const CELL: i32 = 32;
const INK: &str = "#000000";
const FLOOR_COLOR: &str = "#FFFFFF";
const CAVE_FLOOR_COLOR: &str = "#F5EBD8";
const WALL_WIDTH: &str = "5.0";

/// Compose the walls-and-floors layer SVG fragment list.
///
/// Inputs map onto the IR's `WallsAndFloorsOp` table:
///
/// - `corridor_tiles`: `(x, y)` triples for the corridor / door
///   cells. Each emits one `<rect>` with `FLOOR_COLOR`.
/// - `rect_rooms`: `(x, y, w, h)` tuples for the rectangular
///   rooms. Each emits one `<rect>`; w/h are tile counts.
/// - `smooth_fills`: pre-rendered `<path>` / `<polygon>`
///   fragments for non-rect rooms (octagon, smooth-rect with
///   gaps, …). Pass through unchanged.
/// - `cave_region`: pre-rendered `<path d="..."/>` for the cave
///   wall outline. Wrapped twice: once with the brown fill +
///   evenodd rule (the cave floor), once with the black stroke
///   (the cave wall outline). Empty string skips both.
/// - `smooth_walls`: pre-rendered wall fragments for non-cave
///   smooth rooms. Pass through unchanged.
/// - `wall_extensions_d`: pre-rendered `d=` attribute for the
///   tile-edge wall extensions. Wrapped in `<path>` with the
///   black stroke style. Empty string skips.
/// - `wall_segments`: pre-rendered segment strings (one per
///   tile edge). Joined with spaces and wrapped in a single
///   `<path>` with the black stroke style. Empty list skips.
///
/// Returns the layer's element list in the legacy emit order
/// (corridor → rect-rooms → smooth-fills → cave fill → cave
/// stroke → smooth-walls → extensions → segments).
#[allow(clippy::too_many_arguments)]
pub fn draw_walls_and_floors(
    corridor_tiles: &[(i32, i32)],
    rect_rooms: &[(i32, i32, i32, i32)],
    smooth_fills: &[String],
    cave_region: &str,
    smooth_walls: &[String],
    wall_extensions_d: &str,
    wall_segments: &[String],
) -> Vec<String> {
    let mut out: Vec<String> = Vec::with_capacity(
        corridor_tiles.len()
            + rect_rooms.len()
            + smooth_fills.len()
            + smooth_walls.len()
            + 4,
    );

    for &(x, y) in corridor_tiles {
        out.push(format!(
            "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" \
             fill=\"{FLOOR_COLOR}\" stroke=\"none\"/>",
            x * CELL,
            y * CELL,
            CELL,
            CELL,
        ));
    }

    for &(x, y, w, h) in rect_rooms {
        out.push(format!(
            "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" \
             fill=\"{FLOOR_COLOR}\" stroke=\"none\"/>",
            x * CELL,
            y * CELL,
            w * CELL,
            h * CELL,
        ));
    }

    for fill in smooth_fills {
        out.push(fill.clone());
    }

    if !cave_region.is_empty() {
        out.push(cave_region.replace(
            "/>",
            &format!(
                " fill=\"{CAVE_FLOOR_COLOR}\" stroke=\"none\" \
                 fill-rule=\"evenodd\"/>"
            ),
        ));
        out.push(cave_region.replace(
            "/>",
            &format!(
                " fill=\"none\" stroke=\"{INK}\" \
                 stroke-width=\"{WALL_WIDTH}\" \
                 stroke-linecap=\"round\" \
                 stroke-linejoin=\"round\"/>"
            ),
        ));
    }

    for wall in smooth_walls {
        out.push(wall.clone());
    }

    if !wall_extensions_d.is_empty() {
        out.push(format!(
            "<path d=\"{wall_extensions_d}\" fill=\"none\" \
             stroke=\"{INK}\" stroke-width=\"{WALL_WIDTH}\" \
             stroke-linecap=\"round\" stroke-linejoin=\"round\"/>"
        ));
    }

    if !wall_segments.is_empty() {
        let joined = wall_segments
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>()
            .join(" ");
        out.push(format!(
            "<path d=\"{joined}\" fill=\"none\" stroke=\"{INK}\" \
             stroke-width=\"{WALL_WIDTH}\" \
             stroke-linecap=\"round\" stroke-linejoin=\"round\"/>"
        ));
    }

    out
}

#[cfg(test)]
mod tests {
    use super::draw_walls_and_floors;

    #[test]
    fn empty_inputs_return_empty_vec() {
        let out = draw_walls_and_floors(
            &[], &[], &[], "", &[], "", &[],
        );
        assert!(out.is_empty());
    }

    #[test]
    fn corridor_tile_emits_floor_rect_at_origin() {
        let out = draw_walls_and_floors(
            &[(0, 0)], &[], &[], "", &[], "", &[],
        );
        assert_eq!(
            out[0],
            "<rect x=\"0\" y=\"0\" width=\"32\" height=\"32\" \
             fill=\"#FFFFFF\" stroke=\"none\"/>"
        );
    }

    #[test]
    fn rect_room_uses_w_h_in_pixel_space() {
        // 5×3 room at (1, 2) → (32, 64) origin, 160×96 size.
        let out = draw_walls_and_floors(
            &[], &[(1, 2, 5, 3)], &[], "", &[], "", &[],
        );
        assert_eq!(
            out[0],
            "<rect x=\"32\" y=\"64\" width=\"160\" height=\"96\" \
             fill=\"#FFFFFF\" stroke=\"none\"/>"
        );
    }

    #[test]
    fn cave_region_wraps_twice_with_fill_and_stroke() {
        // Pre-rendered cave path: input has trailing `/>` which
        // gets replaced — fill on first emission, stroke on second.
        let out = draw_walls_and_floors(
            &[], &[], &[],
            "<path d=\"M0,0 L10,0 L10,10 Z\"/>",
            &[], "", &[],
        );
        assert_eq!(out.len(), 2);
        assert!(out[0].contains("fill=\"#F5EBD8\""));
        assert!(out[0].contains("fill-rule=\"evenodd\""));
        assert!(out[1].contains("fill=\"none\""));
        assert!(out[1].contains("stroke-width=\"5.0\""));
    }

    #[test]
    fn wall_segments_join_into_single_path() {
        let out = draw_walls_and_floors(
            &[], &[], &[], "", &[], "",
            &["M0,0 L10,0".to_string(), "M0,10 L10,10".to_string()],
        );
        assert_eq!(out.len(), 1);
        assert!(out[0].contains("d=\"M0,0 L10,0 M0,10 L10,10\""));
        assert!(out[0].contains("stroke-width=\"5.0\""));
    }

    #[test]
    fn smooth_passthrough_preserves_strings_byte_for_byte() {
        let fill = "<polygon points=\"0,0 32,0 32,32\"/>".to_string();
        let wall = "<path d=\"M0,0 L32,32\"/>".to_string();
        let out = draw_walls_and_floors(
            &[], &[], &[fill.clone()], "", &[wall.clone()], "", &[],
        );
        assert_eq!(out, vec![fill, wall]);
    }
}
