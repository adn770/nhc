//! Ore-deposit decorator — Phase 4, sub-step 12 (plan §8 Q2).
//!
//! Reproduces ``ORE_DEPOSIT`` from
//! ``nhc/rendering/_floor_detail.py``: a single diamond glint
//! per ore-deposit wall tile. Predicate fires on
//! ``tile.feature == "ore_deposit"`` (not surface_type — ore
//! deposits sit on cave wall tiles).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** RNG-
//! driven (random offset + radius); byte-equal-with-legacy is
//! not required.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;
const ORE_FILL: &str = "#D4B14A";
const ORE_STROKE: &str = "#6A4A1A";

pub fn draw_ore_deposit(
    tiles: &[(i32, i32)], seed: u64,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut diamonds: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        let cx = px + CELL / 2.0 + rng.gen_range(-1.0..1.0);
        let cy = py + CELL / 2.0 + rng.gen_range(-1.0..1.0);
        let r: f64 = rng.gen_range(1.8..2.6);
        diamonds.push(format!(
            "<polygon points=\"\
             {cx:.1},{:.1} {:.1},{cy:.1} \
             {cx:.1},{:.1} {:.1},{cy:.1}\"/>",
            cy - r,
            cx + r,
            cy + r,
            cx - r,
        ));
    }
    if diamonds.is_empty() {
        return Vec::new();
    }
    vec![format!(
        "<g id=\"ore-deposits\" fill=\"{ORE_FILL}\" \
         stroke=\"{ORE_STROKE}\" stroke-width=\"0.4\">{}</g>",
        diamonds.concat(),
    )]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_ore_deposit(&[], 333).is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles = vec![(0, 0), (1, 1), (2, 2)];
        assert_eq!(
            draw_ore_deposit(&tiles, 333),
            draw_ore_deposit(&tiles, 333),
        );
    }

    #[test]
    fn one_diamond_per_tile() {
        let out = draw_ore_deposit(&[(0, 0), (1, 0), (2, 0)], 42);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].matches("<polygon").count(), 3);
    }
}
