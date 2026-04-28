//! Opus romano decorator — Phase 4, sub-step 9 (plan §8 Q2).
//!
//! Reproduces ``OPUS_ROMANO`` from
//! ``nhc/rendering/_floor_detail.py``: classical Roman /
//! Versailles 4-stone tiling. Each tile is a 6×6 subsquare grid
//! partitioned into one 4×4 square, one 2×4 vertical rectangle,
//! one 2×2 small square, and one 4×2 horizontal rectangle. The
//! arrangement rotates 90° per quarter-turn picked
//! deterministically from the tile coordinates so adjacent tiles
//! don't read as a stripe.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** RNG-
//! free per-tile painter (rotation is coordinate-derived, not
//! random). Existing fixtures don't contain OPUS_ROMANO tiles;
//! coverage rides on synthetic-level tests.

const CELL: f64 = 32.0;
const OPUS_ROMANO_STROKE: &str = "#7A5A3A";
const SUBDIVISIONS: i32 = 6;
const MORTAR_INSET: f64 = 0.5;

/// Base 4-stone arrangement on the 6×6 subsquare grid:
/// (sub_x, sub_y, sub_w, sub_h).
const STONES: [(i32, i32, i32, i32); 4] = [
    (0, 0, 4, 4),
    (4, 0, 2, 4),
    (0, 4, 2, 2),
    (2, 4, 4, 2),
];

fn rotate_stone_in_grid(
    sx: i32, sy: i32, sw: i32, sh: i32, n_quarter: i32,
) -> (i32, i32, i32, i32) {
    let mut s = (sx, sy, sw, sh);
    let n = ((n_quarter % 4) + 4) % 4;
    for _ in 0..n {
        s = (SUBDIVISIONS - s.1 - s.3, s.0, s.3, s.2);
    }
    s
}

/// Opus-romano decorator entry point — Phase 4 sub-step 9.
///
/// `tiles` is the OPUS_ROMANO-surface tile list; `seed` is
/// unused (rotation is per-tile coordinate-derived, not RNG-
/// driven) but kept for API symmetry with the other decorators.
pub fn draw_opus_romano(
    tiles: &[(i32, i32)], _seed: u64,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let sub = CELL / f64::from(SUBDIVISIONS);
    let mut rects: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let rotation = (x * 7 + y * 13).rem_euclid(4);
        for &(sx, sy, sw, sh) in &STONES {
            let (sx, sy, sw, sh) =
                rotate_stone_in_grid(sx, sy, sw, sh, rotation);
            let xx = px + f64::from(sx) * sub + MORTAR_INSET;
            let yy = py + f64::from(sy) * sub + MORTAR_INSET;
            let w = f64::from(sw) * sub - 2.0 * MORTAR_INSET;
            let h = f64::from(sh) * sub - 2.0 * MORTAR_INSET;
            rects.push(format!(
                "<rect x=\"{xx:.2}\" y=\"{yy:.2}\" \
                 width=\"{w:.2}\" height=\"{h:.2}\" rx=\"0.4\"/>",
            ));
        }
    }
    if rects.is_empty() {
        return Vec::new();
    }
    vec![format!(
        "<g opacity=\"0.45\" fill=\"none\" stroke=\"{OPUS_ROMANO_STROKE}\" \
         stroke-width=\"0.5\">{}</g>",
        rects.concat(),
    )]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_opus_romano(&[], 0).is_empty());
    }

    #[test]
    fn four_rects_per_tile() {
        let out = draw_opus_romano(&[(0, 0)], 0);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].matches("<rect").count(), 4);
    }

    #[test]
    fn rotation_independent_of_seed() {
        // The painter is RNG-free; same input produces same
        // output regardless of seed.
        let tiles: Vec<(i32, i32)> = (0..4)
            .flat_map(|y| (0..4).map(move |x| (x, y)))
            .collect();
        assert_eq!(
            draw_opus_romano(&tiles, 0),
            draw_opus_romano(&tiles, 999),
        );
    }
}
