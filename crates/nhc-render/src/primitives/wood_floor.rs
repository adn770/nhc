//! Wood-floor parquet painter — Phase 9.2c port of
//! `nhc/rendering/_floor_detail._render_wood_floor`.
//!
//! Reproduces the per-tile rect fill (or whole-footprint rect for
//! octagon / circle building polygons), the per-room grain streaks
//! (light + dark), and the per-room parquet seam grid as Rust SVG
//! fragments. The handler at `transform/png/floor_detail.rs`
//! routes the fragments through `paint_fragments` under the
//! dungeon-poly clip mask.
//!
//! **Parity contract (relaxed gate, plan §9.2):** byte-equal-with-
//! legacy is *not* required. The Rust port uses one `Pcg64Mcg`
//! stream over (rooms × strips × grain lines) followed by
//! (rooms × strips × plank lengths) — the same draw-order shape
//! as the legacy `random.Random(seed + 99)` walk, with a different
//! algorithm that produces PSNR-equivalent pixels.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;

const WOOD_FLOOR_FILL: &str = "#B58B5A";
const WOOD_SEAM_STROKE: &str = "#8A5A2A";
const WOOD_SEAM_WIDTH: f64 = 0.8;
const WOOD_PLANK_WIDTH_PX: f64 = CELL / 4.0;
const WOOD_PLANK_LENGTH_MIN: f64 = CELL * 0.5;
const WOOD_PLANK_LENGTH_MAX: f64 = CELL * 2.5;
const WOOD_GRAIN_LIGHT: &str = "#C4A076";
const WOOD_GRAIN_DARK: &str = "#8F6540";
const WOOD_GRAIN_STROKE_WIDTH: f64 = 0.4;
const WOOD_GRAIN_OPACITY: f64 = 0.35;
const WOOD_GRAIN_LINES_PER_STRIP: u32 = 2;

/// One room's parquet rect in tile coordinates (matches the
/// `RectRoom` FB struct shape).
#[derive(Clone, Copy, Debug)]
pub struct WoodRoom {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

/// Building-polygon outer outline in pixel coordinates (matches
/// the `Vec2` FB struct shape).
#[derive(Clone, Copy, Debug)]
pub struct PolyVertex {
    pub x: f64,
    pub y: f64,
}

/// Wood-floor painter entry point.
///
/// `tiles`: FLOOR tiles in row-major order. Drives the per-tile
/// rect fill when `polygon` is empty.
///
/// `polygon`: octagon / circle building outline. When non-empty,
/// the rect fill collapses to a single bounding-box rect that
/// would clip against the polygon in SVG; here it just paints the
/// box (the handler's mask + the bounding rect together cover
/// the same visible area).
///
/// `rooms`: per-room rects driving the grain streak generator and
/// the parquet seam grid.
///
/// Returns a flat list of SVG fragments (`<rect>` + `<g>`
/// envelopes) that `paint_fragments` rasterises with the dungeon-
/// poly clip mask applied.
pub fn draw_wood_floor(
    tiles: &[(i32, i32)],
    polygon: &[PolyVertex],
    rooms: &[WoodRoom],
    seed: u64,
) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();

    if !polygon.is_empty() {
        let xs: Vec<f64> = polygon.iter().map(|p| p.x).collect();
        let ys: Vec<f64> = polygon.iter().map(|p| p.y).collect();
        let bx = xs.iter().copied().fold(f64::INFINITY, f64::min);
        let by = ys.iter().copied().fold(f64::INFINITY, f64::min);
        let bw =
            xs.iter().copied().fold(f64::NEG_INFINITY, f64::max) - bx;
        let bh =
            ys.iter().copied().fold(f64::NEG_INFINITY, f64::max) - by;
        out.push(format!(
            "<rect x=\"{bx:.1}\" y=\"{by:.1}\" \
             width=\"{bw:.1}\" height=\"{bh:.1}\" \
             fill=\"{WOOD_FLOOR_FILL}\"/>",
        ));
    } else {
        for &(x, y) in tiles {
            let px = f64::from(x) * CELL;
            let py = f64::from(y) * CELL;
            out.push(format!(
                "<rect x=\"{px:.0}\" y=\"{py:.0}\" \
                 width=\"{CELL}\" height=\"{CELL}\" \
                 fill=\"{WOOD_FLOOR_FILL}\"/>",
            ));
        }
    }

    if rooms.is_empty() {
        return out;
    }

    let mut rng = Pcg64Mcg::seed_from_u64(seed);

    let mut grain_light = String::new();
    let mut grain_dark = String::new();
    for room in rooms {
        emit_room_grain(room, &mut rng, &mut grain_light, &mut grain_dark);
    }
    if !grain_light.is_empty() {
        out.push(format!(
            "<g fill=\"none\" stroke=\"{WOOD_GRAIN_LIGHT}\" \
             stroke-width=\"{WOOD_GRAIN_STROKE_WIDTH}\" \
             opacity=\"{WOOD_GRAIN_OPACITY}\">{grain_light}</g>",
        ));
    }
    if !grain_dark.is_empty() {
        out.push(format!(
            "<g fill=\"none\" stroke=\"{WOOD_GRAIN_DARK}\" \
             stroke-width=\"{WOOD_GRAIN_STROKE_WIDTH}\" \
             opacity=\"{WOOD_GRAIN_OPACITY}\">{grain_dark}</g>",
        ));
    }

    let mut seams = String::new();
    for room in rooms {
        emit_room_seams(room, &mut rng, &mut seams);
    }
    if !seams.is_empty() {
        out.push(format!(
            "<g fill=\"none\" stroke=\"{WOOD_SEAM_STROKE}\" \
             stroke-width=\"{WOOD_SEAM_WIDTH}\">{seams}</g>",
        ));
    }
    out
}

fn emit_room_grain(
    room: &WoodRoom, rng: &mut Pcg64Mcg,
    light: &mut String, dark: &mut String,
) {
    let x0 = f64::from(room.x) * CELL;
    let y0 = f64::from(room.y) * CELL;
    let x1 = f64::from(room.x + room.w) * CELL;
    let y1 = f64::from(room.y + room.h) * CELL;
    let horizontal = room.w >= room.h;
    let width = WOOD_PLANK_WIDTH_PX;

    if horizontal {
        let mut y = y0;
        while y < y1 {
            let strip_bot = (y + width).min(y1);
            let span = strip_bot - y;
            if span <= 0.5 {
                y += width;
                continue;
            }
            for i in 0..WOOD_GRAIN_LINES_PER_STRIP {
                let gy = rng.gen_range((y + span * 0.15)..(strip_bot - span * 0.15));
                let dest = if i % 2 == 0 { &mut *light } else { &mut *dark };
                dest.push_str(&format!(
                    "<line x1=\"{x0:.1}\" y1=\"{gy:.1}\" \
                     x2=\"{x1:.1}\" y2=\"{gy:.1}\"/>",
                ));
            }
            y += width;
        }
    } else {
        let mut x = x0;
        while x < x1 {
            let strip_right = (x + width).min(x1);
            let span = strip_right - x;
            if span <= 0.5 {
                x += width;
                continue;
            }
            for i in 0..WOOD_GRAIN_LINES_PER_STRIP {
                let gx = rng.gen_range((x + span * 0.15)..(strip_right - span * 0.15));
                let dest = if i % 2 == 0 { &mut *light } else { &mut *dark };
                dest.push_str(&format!(
                    "<line x1=\"{gx:.1}\" y1=\"{y0:.1}\" \
                     x2=\"{gx:.1}\" y2=\"{y1:.1}\"/>",
                ));
            }
            x += width;
        }
    }
}

fn emit_room_seams(
    room: &WoodRoom, rng: &mut Pcg64Mcg, seams: &mut String,
) {
    let x0 = f64::from(room.x) * CELL;
    let y0 = f64::from(room.y) * CELL;
    let x1 = f64::from(room.x + room.w) * CELL;
    let y1 = f64::from(room.y + room.h) * CELL;
    let horizontal = room.w >= room.h;
    let width = WOOD_PLANK_WIDTH_PX;

    if horizontal {
        let mut y = y0;
        while y < y1 {
            let strip_bot = (y + width).min(y1);
            let mut x_end = x0
                + rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            while x_end < x1 {
                seams.push_str(&format!(
                    "<line x1=\"{x_end:.1}\" y1=\"{y:.1}\" \
                     x2=\"{x_end:.1}\" y2=\"{strip_bot:.1}\"/>",
                ));
                x_end +=
                    rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            }
            y += width;
            if y < y1 {
                seams.push_str(&format!(
                    "<line x1=\"{x0:.1}\" y1=\"{y:.1}\" \
                     x2=\"{x1:.1}\" y2=\"{y:.1}\"/>",
                ));
            }
        }
    } else {
        let mut x = x0;
        while x < x1 {
            let strip_right = (x + width).min(x1);
            let mut y_end = y0
                + rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            while y_end < y1 {
                seams.push_str(&format!(
                    "<line x1=\"{x:.1}\" y1=\"{y_end:.1}\" \
                     x2=\"{strip_right:.1}\" y2=\"{y_end:.1}\"/>",
                ));
                y_end +=
                    rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            }
            x += width;
            if x < x1 {
                seams.push_str(&format!(
                    "<line x1=\"{x:.1}\" y1=\"{y0:.1}\" \
                     x2=\"{x:.1}\" y2=\"{y1:.1}\"/>",
                ));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rooms(rs: &[(i32, i32, i32, i32)]) -> Vec<WoodRoom> {
        rs.iter().map(|&(x, y, w, h)| WoodRoom { x, y, w, h }).collect()
    }

    fn tiles(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

    #[test]
    fn empty_inputs_returns_empty() {
        assert!(draw_wood_floor(&[], &[], &[], 99).is_empty());
    }

    #[test]
    fn rect_floor_emits_per_tile_fill() {
        let t = tiles(3);
        let r = rooms(&[(0, 0, 3, 3)]);
        let out = draw_wood_floor(&t, &[], &r, 99);
        let n_rects = out.iter().filter(|f| f.starts_with("<rect")).count();
        assert_eq!(n_rects, 9);
        assert!(out[0].contains(WOOD_FLOOR_FILL));
    }

    #[test]
    fn polygon_floor_emits_single_bounding_rect() {
        let poly: Vec<PolyVertex> = [
            (32.0, 0.0), (96.0, 0.0), (128.0, 32.0),
            (128.0, 96.0), (96.0, 128.0), (32.0, 128.0),
            (0.0, 96.0), (0.0, 32.0),
        ].iter().map(|&(x, y)| PolyVertex { x, y }).collect();
        let r = rooms(&[(0, 0, 4, 4)]);
        let out = draw_wood_floor(&[], &poly, &r, 99);
        // Exactly one rect (the bounding box) — per-tile rects
        // skip when the polygon path is taken.
        let n_rects = out.iter().filter(|f| f.starts_with("<rect")).count();
        assert_eq!(n_rects, 1);
        assert!(out[0].contains("width=\"128.0\""));
        assert!(out[0].contains("height=\"128.0\""));
    }

    #[test]
    fn deterministic_for_same_seed() {
        let t = tiles(5);
        let r = rooms(&[(0, 0, 5, 5)]);
        assert_eq!(
            draw_wood_floor(&t, &[], &r, 99),
            draw_wood_floor(&t, &[], &r, 99),
        );
    }

    #[test]
    fn different_seeds_diverge() {
        let t = tiles(5);
        let r = rooms(&[(0, 0, 5, 5)]);
        assert_ne!(
            draw_wood_floor(&t, &[], &r, 99),
            draw_wood_floor(&t, &[], &r, 7),
        );
    }

    #[test]
    fn grain_groups_carry_palette_colours() {
        let t = tiles(5);
        let r = rooms(&[(0, 0, 5, 5)]);
        let out = draw_wood_floor(&t, &[], &r, 99);
        let joined = out.join("");
        assert!(joined.contains(&format!("stroke=\"{WOOD_GRAIN_LIGHT}\"")));
        assert!(joined.contains(&format!("stroke=\"{WOOD_GRAIN_DARK}\"")));
        assert!(joined.contains(&format!("stroke=\"{WOOD_SEAM_STROKE}\"")));
    }
}
