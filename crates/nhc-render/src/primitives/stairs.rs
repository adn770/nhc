//! Stairs primitive — Phase 4.3, third deterministic port.
//!
//! Reproduces `_render_stairs` from `nhc/rendering/_stairs_svg.py`
//! per the schema's `StairsOp` shape: each stair surfaces as
//! optional cave-theme fill polygon (when the floor's theme is
//! "cave") followed by 2 rail lines and 6 step lines, in legacy
//! emit order.
//!
//! No RNG, no Perlin, no Shapely. Pure trigonometry-free FP
//! arithmetic on `i32` × cell sizes — stair tile coords are
//! integers, derived geometry is `f64` formatted with `{:.1}`.

use std::fmt::Write;

const CELL: f64 = 32.0;
const INK: &str = "#000000";
// Python's `f"{1.0}"` produces "1.0", but Rust's `format!("{}", 1.0_f64)`
// strips the trailing zero. The legacy stair renderer formats stroke-
// widths with bare `{}` (no `:.1f`), so the byte-equal contract requires
// hardcoded string constants here. Coordinates inside the elements all
// use `{:.1}` in both legacy and Rust, so they round-trip cleanly.
const RAIL_SW: &str = "1.5";
const STEP_SW: &str = "1.0";
const N_STEPS: i32 = 5;
const WIDE_H: f64 = CELL * 0.4;
const NARROW_H: f64 = CELL * 0.1;
const M: f64 = CELL * 0.1; // tile margin

/// Discriminant matching `StairDirection` in `floor_ir.fbs`.
const DIR_DOWN: u8 = 1;

/// Emit the stairs-layer SVG fragment.
///
/// `stairs` is `[(x, y, direction)]` with `direction` matching the
/// schema's `StairDirection` enum (`Up=0`, `Down=1`).
/// `theme` and `fill_color` come from the IR's `StairsOp` —
/// `theme == "cave"` toggles the per-stair cave fill polygon,
/// `fill_color` is the resolved cave-fill colour.
///
/// Returns a list of SVG element strings (one per polygon /
/// line). Per stair the output is:
///
/// - (cave only) one `<polygon>` cave fill
/// - 2 `<line>` rails (top + bottom)
/// - 6 `<line>` step lines (`N_STEPS + 1` for the closed range)
///
/// Total: 8 or 9 elements per stair, depending on theme.
pub fn draw_stairs(
    stairs: &[(i32, i32, u8)],
    theme: &str,
    fill_color: &str,
) -> Vec<String> {
    let mut out: Vec<String> = Vec::with_capacity(stairs.len() * 9);
    let is_cave = theme == "cave";
    for &(x, y, direction) in stairs {
        let down = direction == DIR_DOWN;
        let px = x as f64 * CELL;
        let py = y as f64 * CELL;
        let cy = py + CELL / 2.0;
        let left_x = px + M;
        let right_x = px + CELL - M;

        if is_cave {
            let pts = if down {
                format!(
                    "{:.1},{:.1} {:.1},{:.1} {:.1},{:.1} {:.1},{:.1}",
                    left_x, cy - WIDE_H,
                    right_x, cy - NARROW_H,
                    right_x, cy + NARROW_H,
                    left_x, cy + WIDE_H,
                )
            } else {
                format!(
                    "{:.1},{:.1} {:.1},{:.1} {:.1},{:.1} {:.1},{:.1}",
                    left_x, cy - NARROW_H,
                    right_x, cy - WIDE_H,
                    right_x, cy + WIDE_H,
                    left_x, cy + NARROW_H,
                )
            };
            out.push(format!(
                "<polygon points=\"{pts}\" fill=\"{fill_color}\" stroke=\"none\"/>"
            ));
        }

        let (top_y0, top_y1, bot_y0, bot_y1, wide_start, narrow_end);
        if down {
            top_y0 = cy - WIDE_H;
            top_y1 = cy - NARROW_H;
            bot_y0 = cy + WIDE_H;
            bot_y1 = cy + NARROW_H;
            wide_start = WIDE_H;
            narrow_end = NARROW_H;
        } else {
            top_y0 = cy - NARROW_H;
            top_y1 = cy - WIDE_H;
            bot_y0 = cy + NARROW_H;
            bot_y1 = cy + WIDE_H;
            wide_start = NARROW_H;
            narrow_end = WIDE_H;
        }

        out.push(format!(
            "<line x1=\"{:.1}\" y1=\"{:.1}\" x2=\"{:.1}\" y2=\"{:.1}\" \
             stroke=\"{INK}\" stroke-width=\"{RAIL_SW}\" \
             stroke-linecap=\"round\"/>",
            left_x, top_y0, right_x, top_y1,
        ));
        out.push(format!(
            "<line x1=\"{:.1}\" y1=\"{:.1}\" x2=\"{:.1}\" y2=\"{:.1}\" \
             stroke=\"{INK}\" stroke-width=\"{RAIL_SW}\" \
             stroke-linecap=\"round\"/>",
            left_x, bot_y0, right_x, bot_y1,
        ));

        let span = right_x - left_x;
        for i in 0..=N_STEPS {
            let t = i as f64 / N_STEPS as f64;
            let sx = left_x + span * t;
            let half = wide_start + (narrow_end - wide_start) * t;
            let mut s = String::with_capacity(120);
            write!(
                &mut s,
                "<line x1=\"{sx:.1}\" y1=\"{:.1}\" x2=\"{sx:.1}\" y2=\"{:.1}\" \
                 stroke=\"{INK}\" stroke-width=\"{STEP_SW}\" \
                 stroke-linecap=\"round\"/>",
                cy - half,
                cy + half,
            )
            .unwrap();
            out.push(s);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::draw_stairs;

    #[test]
    fn empty_stairs_returns_empty_vec() {
        assert!(draw_stairs(&[], "dungeon", "#fff").is_empty());
    }

    #[test]
    fn dungeon_stairs_emits_eight_elements_per_stair() {
        // Non-cave theme: no cave fill polygon → 2 rails + 6
        // step lines = 8 elements per stair.
        let out = draw_stairs(&[(0, 0, 0)], "dungeon", "#aaa");
        assert_eq!(out.len(), 8);
        // First two are the rails, rest are step lines.
        assert!(out[0].starts_with("<line"));
        assert!(out[1].starts_with("<line"));
        for i in 2..8 {
            assert!(out[i].starts_with("<line x1="));
        }
    }

    #[test]
    fn cave_stairs_emits_nine_elements_per_stair() {
        // Cave theme: 1 polygon + 2 rails + 6 step lines = 9.
        let out = draw_stairs(&[(0, 0, 0)], "cave", "#F5EBD8");
        assert_eq!(out.len(), 9);
        assert!(out[0].starts_with("<polygon points="));
        assert!(out[0].contains("fill=\"#F5EBD8\""));
    }

    #[test]
    fn down_stair_emits_inverted_rail_pattern() {
        // Up stairs: top rail goes (narrow → wide), bottom (narrow → wide).
        // Down stairs: top rail goes (wide → narrow), bottom (wide → narrow).
        // The y1 of the top rail tells the story:
        //   Up:   y1 = cy - NARROW_H = 16 - 3.2 = 12.8
        //   Down: y1 = cy - WIDE_H   = 16 - 12.8 = 3.2
        let up = draw_stairs(&[(0, 0, 0)], "dungeon", "#fff");
        let dn = draw_stairs(&[(0, 0, 1)], "dungeon", "#fff");
        assert!(up[0].contains("y1=\"12.8\""), "up rail top: {}", up[0]);
        assert!(dn[0].contains("y1=\"3.2\""), "down rail top: {}", dn[0]);
    }

    #[test]
    fn stair_at_offset_uses_pixel_coords() {
        // (x=2, y=3) → pixel (64, 96). cy = 96 + 16 = 112.
        // left_x = 64 + 3.2 = 67.2.
        let out = draw_stairs(&[(2, 3, 0)], "dungeon", "#fff");
        assert!(out[0].contains("x1=\"67.2\""), "{}", out[0]);
        assert!(out[0].contains("y1=\"108.8\""), "{}", out[0]); // cy - NARROW_H
    }
}
