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

const WOOD_SEAM_WIDTH: f64 = 0.8;
const WOOD_PLANK_WIDTH_PX: f64 = CELL / 4.0;
const WOOD_PLANK_LENGTH_MIN: f64 = CELL * 0.5;
const WOOD_PLANK_LENGTH_MAX: f64 = CELL * 2.5;
const WOOD_GRAIN_STROKE_WIDTH: f64 = 0.4;
const WOOD_GRAIN_OPACITY: f64 = 0.35;
const WOOD_GRAIN_LINES_PER_STRIP: u32 = 2;

/// Per-tone palette: (fill, grain_light, grain_dark, seam).
type WoodTone = (&'static str, &'static str, &'static str, &'static str);
/// Per-species palette: (light, medium, dark) tones.
type WoodSpecies = [WoodTone; 3];

/// 5 wood species × 3 tones each. Mirrors the
/// ``_WOOD_SPECIES`` table in
/// ``nhc/rendering/_floor_detail.py`` byte-for-byte so a building's
/// tone choice is identical between Python and Rust renders.
const WOOD_SPECIES: [WoodSpecies; 5] = [
    // Oak — warm tan, the species closest to the legacy palette.
    [
        ("#C4A076", "#D4B690", "#A88058", "#8A5A2A"),
        ("#B58B5A", "#C4A076", "#8F6540", "#8A5A2A"),
        ("#9B7548", "#AC8A60", "#7A5530", "#683E1E"),
    ],
    // Walnut — deep cocoa, redder hue.
    [
        ("#8C6440", "#A07A55", "#684A2C", "#553820"),
        ("#6E4F32", "#8B6446", "#523820", "#3F2818"),
        ("#553820", "#6E4F32", "#3F2818", "#2A1A10"),
    ],
    // Cherry — reddish brown, slight orange.
    [
        ("#B07A55", "#C49075", "#8E5C3A", "#683C20"),
        ("#9B6442", "#B07A55", "#7A4D2E", "#553820"),
        ("#7E4F32", "#955F44", "#5F3820", "#42261A"),
    ],
    // Pine — pale honey, the lightest species.
    [
        ("#D8B888", "#E6CDA8", "#B8966C", "#9A7A50"),
        ("#C4A176", "#D8B888", "#A48458", "#856A40"),
        ("#A88556", "#BFA070", "#88683C", "#6A5028"),
    ],
    // Weathered grey — silvered teak / driftwood.
    [
        ("#8A8478", "#A09A8E", "#6E695F", "#544F46"),
        ("#6E695F", "#8A8478", "#544F46", "#3D3932"),
        ("#544F46", "#6E695F", "#3D3932", "#2A2723"),
    ],
];

/// FNV-1a 32-bit hash of a UTF-8 byte string. Must match the
/// Python implementation in ``_wood_palette_for_room`` so the
/// species + tone pick stays in sync across rasterisers.
fn fnv1a_32(bytes: &[u8]) -> u32 {
    let mut h: u32 = 2_166_136_261;
    for b in bytes {
        h ^= u32::from(*b);
        h = h.wrapping_mul(16_777_619);
    }
    h
}

/// Resolve ``(fill, grain_light, grain_dark, seam)`` for one wood
/// room. ``building_seed`` picks the species; ``region_ref`` (the
/// room id) picks the tone within that species. Mirror of the
/// Python ``_wood_palette_for_room``.
fn wood_palette_for_room(
    building_seed: u64, region_ref: &str,
) -> WoodTone {
    let species_idx = (building_seed as usize) % WOOD_SPECIES.len();
    let species = &WOOD_SPECIES[species_idx];
    if region_ref.is_empty() {
        return species[1]; // medium
    }
    let h = fnv1a_32(region_ref.as_bytes());
    species[(h as usize) % 3]
}

/// One room's parquet rect in tile coordinates (matches the
/// `RectRoom` FB struct shape). ``region_ref`` is the room id;
/// it picks the tone variant within the building's species.
#[derive(Clone, Debug)]
pub struct WoodRoom {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    pub region_ref: String,
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
/// Per design/map_ir.md §6.1, the wood **base fill** is now
/// emitted by `WallsAndFloorsOp` (structural layer), so the
/// per-tile / per-polygon fill rect that used to live here is
/// gone. This handler only emits the per-room grain streaks and
/// parquet plank seams (floor_detail layer, paints on top of
/// the structural fill + walls).
///
/// `tiles` and `polygon` are kept on the FFI for backwards
/// compatibility; `polygon` still drives the per-room grain/
/// seam clip mask in the PNG handler.
///
/// `rooms`: per-room rects driving the grain streak generator and
/// the parquet seam grid.
pub fn draw_wood_floor(
    _tiles: &[(i32, i32)],
    _polygon: &[PolyVertex],
    rooms: &[WoodRoom],
    seed: u64,
) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();

    if rooms.is_empty() {
        return out;
    }

    let mut rng = Pcg64Mcg::seed_from_u64(seed);

    // Resolve each room's palette ONCE, then route the per-room
    // overlay rect, the grain streaks, and the seam strokes
    // through the matching palette colours. Mirror of the Python
    // ``_draw_wood_floor_from_ir`` Phase 1.26h refactor.
    let palettes: Vec<WoodTone> = rooms
        .iter()
        .map(|r| wood_palette_for_room(seed, &r.region_ref))
        .collect();

    // Per-room overlay rects in a single ``<g>``. The species'
    // tone fill paints over the building-wide WoodFloor base.
    let mut overlay = String::new();
    for (room, palette) in rooms.iter().zip(palettes.iter()) {
        let fill = palette.0;
        let rx = f64::from(room.x) * CELL;
        let ry = f64::from(room.y) * CELL;
        let rw = f64::from(room.w) * CELL;
        let rh = f64::from(room.h) * CELL;
        overlay.push_str(&format!(
            "<rect x=\"{rx:.1}\" y=\"{ry:.1}\" \
             width=\"{rw:.1}\" height=\"{rh:.1}\" \
             fill=\"{fill}\" stroke=\"none\"/>",
        ));
    }
    if !overlay.is_empty() {
        out.push(format!("<g>{overlay}</g>"));
    }

    // Grain — bucket per (light, dark) palette pair.
    type GrainBucket = (String, String);
    let mut grain_buckets: Vec<((&str, &str), GrainBucket)> = Vec::new();
    for (room, palette) in rooms.iter().zip(palettes.iter()) {
        let key = (palette.1, palette.2);
        let bucket = match grain_buckets.iter_mut().find(|(k, _)| *k == key) {
            Some((_, b)) => b,
            None => {
                grain_buckets.push((key, (String::new(), String::new())));
                &mut grain_buckets.last_mut().unwrap().1
            }
        };
        emit_room_grain(room, &mut rng, &mut bucket.0, &mut bucket.1);
    }
    for ((light, dark), (light_lines, dark_lines)) in &grain_buckets {
        if !light_lines.is_empty() {
            out.push(format!(
                "<g fill=\"none\" stroke=\"{light}\" \
                 stroke-width=\"{WOOD_GRAIN_STROKE_WIDTH}\" \
                 opacity=\"{WOOD_GRAIN_OPACITY}\">{light_lines}</g>",
            ));
        }
        if !dark_lines.is_empty() {
            out.push(format!(
                "<g fill=\"none\" stroke=\"{dark}\" \
                 stroke-width=\"{WOOD_GRAIN_STROKE_WIDTH}\" \
                 opacity=\"{WOOD_GRAIN_OPACITY}\">{dark_lines}</g>",
            ));
        }
    }

    // Seams — bucket per palette seam colour.
    let mut seam_buckets: Vec<(&str, String)> = Vec::new();
    for (room, palette) in rooms.iter().zip(palettes.iter()) {
        let seam = palette.3;
        let bucket = match seam_buckets.iter_mut().find(|(k, _)| *k == seam) {
            Some((_, b)) => b,
            None => {
                seam_buckets.push((seam, String::new()));
                &mut seam_buckets.last_mut().unwrap().1
            }
        };
        emit_room_seams(room, &mut rng, bucket);
    }
    for (seam, seam_lines) in &seam_buckets {
        if !seam_lines.is_empty() {
            out.push(format!(
                "<g fill=\"none\" stroke=\"{seam}\" \
                 stroke-width=\"{WOOD_SEAM_WIDTH}\">{seam_lines}</g>",
            ));
        }
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
        rs.iter()
            .enumerate()
            .map(|(i, &(x, y, w, h))| WoodRoom {
                x, y, w, h,
                region_ref: format!("r{i}"),
            })
            .collect()
    }

    fn tiles(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

    #[test]
    fn empty_inputs_returns_empty() {
        assert!(draw_wood_floor(&[], &[], &[], 99).is_empty());
    }

    #[test]
    fn polygon_passthrough_emits_no_polygon_fill() {
        // The base building polygon fill is emitted by FloorOp
        // (WoodFloor) in the structural layer — not by this
        // primitive. The only ``<rect>`` this primitive emits is
        // the per-room overlay rect carrying the species' tone.
        let poly: Vec<PolyVertex> = [
            (32.0, 0.0), (96.0, 0.0), (128.0, 32.0),
            (128.0, 96.0), (96.0, 128.0), (32.0, 128.0),
            (0.0, 96.0), (0.0, 32.0),
        ].iter().map(|&(x, y)| PolyVertex { x, y }).collect();
        let r = rooms(&[(0, 0, 4, 4)]);
        let out = draw_wood_floor(&[], &poly, &r, 99);
        // Per-room overlay rect counts as 1 ``<rect>`` per room.
        let n_rects = out.iter().filter(|f| f.contains("<rect")).count();
        assert_eq!(n_rects, 1);
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
    fn grain_groups_carry_species_palette_colours() {
        // Verify that the rendered output carries colours from the
        // selected species' palette. seed=99 picks species_idx
        // 99 % 5 == 4 (weathered grey).
        let t = tiles(5);
        let r = rooms(&[(0, 0, 5, 5)]);
        let out = draw_wood_floor(&t, &[], &r, 99);
        let joined = out.join("");
        let species = &WOOD_SPECIES[99 % WOOD_SPECIES.len()];
        let mut found_grain_light = false;
        let mut found_grain_dark = false;
        let mut found_seam = false;
        for tone in species {
            if joined.contains(&format!("stroke=\"{}\"", tone.1)) {
                found_grain_light = true;
            }
            if joined.contains(&format!("stroke=\"{}\"", tone.2)) {
                found_grain_dark = true;
            }
            if joined.contains(&format!("stroke=\"{}\"", tone.3)) {
                found_seam = true;
            }
        }
        assert!(found_grain_light);
        assert!(found_grain_dark);
        assert!(found_seam);
    }

    #[test]
    fn fnv1a_matches_python_implementation() {
        // Spot-check the FNV-1a hash against a couple of known
        // Python outputs (computed via the reference function).
        // Stability across implementations is the contract.
        assert_eq!(fnv1a_32(b""), 2_166_136_261);
        assert_eq!(fnv1a_32(b"r1"), 0x0C53FDAC);
        assert_eq!(fnv1a_32(b"room.0"), 0x4D7D60E4);
    }
}
