//! Field-stone decorator — Phase 4, sub-step 10 (plan §8 Q2).
//!
//! Reproduces ``FIELD_STONE`` from
//! ``nhc/rendering/_floor_detail.py``: a probabilistic
//! scattered stone (10 % per tile) for FIELD-surface GRASS
//! tiles. Single ellipse per fired tile, in a green-stone
//! palette.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;
const FIELD_STONE_FILL: &str = "#8A9A6A";
const FIELD_STONE_STROKE: &str = "#4A5A3A";
const PROBABILITY: f64 = 0.10;

pub fn draw_field_stone(
    tiles: &[(i32, i32)], seed: u64,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut stones: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        if rng.gen::<f64>() >= PROBABILITY {
            continue;
        }
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let cx = px + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
        let cy = py + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
        let rx: f64 = rng.gen_range(1.5..2.8);
        let ry: f64 = rng.gen_range(1.2..2.2);
        let angle: f64 = rng.gen_range(0.0..180.0);
        stones.push(format!(
            "<ellipse cx=\"{cx:.1}\" cy=\"{cy:.1}\" \
             rx=\"{rx:.1}\" ry=\"{ry:.1}\" \
             transform=\"rotate({angle:.0},{cx:.1},{cy:.1})\" \
             fill=\"{FIELD_STONE_FILL}\" stroke=\"{FIELD_STONE_STROKE}\" \
             stroke-width=\"0.5\"/>",
        ));
    }
    if stones.is_empty() {
        return Vec::new();
    }
    vec![format!("<g opacity=\"0.8\">{}</g>", stones.concat())]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_field_stone(&[], 333).is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32)> = (0..10)
            .flat_map(|y| (0..10).map(move |x| (x, y)))
            .collect();
        assert_eq!(
            draw_field_stone(&tiles, 333),
            draw_field_stone(&tiles, 333),
        );
    }

    #[test]
    fn around_10_percent_fire_rate() {
        // 200 tiles × 10 % → ~20 stones expected.
        let tiles: Vec<(i32, i32)> = (0..20)
            .flat_map(|y| (0..10).map(move |x| (x, y)))
            .collect();
        let out = draw_field_stone(&tiles, 333);
        assert_eq!(out.len(), 1);
        let n = out[0].matches("<ellipse").count();
        assert!(
            5 <= n && n <= 50,
            "expected ~20 fires (10 %), got {n}"
        );
    }
}
