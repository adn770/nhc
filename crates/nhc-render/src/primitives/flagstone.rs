//! Flagstone decorator — Phase 4, sub-step 8 (plan §8 Q2).
//!
//! Reproduces ``FLAGSTONE`` (4 irregular pentagon plates per
//! tile, divided 2×2 with a small mortar inset) from
//! ``nhc/rendering/_floor_detail.py``. Stroke-only group; the
//! wrapping <g> sets opacity / colour.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Existing fixtures don't
//! contain FLAGSTONE tiles; coverage rides on synthetic-level
//! tests.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;
const FLAGSTONE_STROKE: &str = "#6A6055";

pub fn draw_flagstone(tiles: &[(i32, i32)], seed: u64) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed);

    let half = CELL / 2.0;
    let inset = half * 0.08;

    let mut plates: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        for qy in 0..2 {
            for qx in 0..2 {
                let cx = px + f64::from(qx) * half;
                let cy = py + f64::from(qy) * half;
                // Five corner points: TL, T, TR, BR, BL with jitter.
                let j = |rng: &mut Pcg64Mcg| -> f64 {
                    rng.gen_range((-half * 0.07)..(half * 0.07))
                };
                let p0 = (cx + inset + j(&mut rng), cy + inset + j(&mut rng));
                let p1 = (
                    cx + half * 0.5 + j(&mut rng),
                    cy + inset * 0.5 + j(&mut rng),
                );
                let p2 = (
                    cx + half - inset + j(&mut rng),
                    cy + inset + j(&mut rng),
                );
                let p3 = (
                    cx + half - inset + j(&mut rng),
                    cy + half - inset + j(&mut rng),
                );
                let p4 = (
                    cx + inset + j(&mut rng),
                    cy + half - inset + j(&mut rng),
                );
                plates.push(format!(
                    "<polygon points=\"\
                     {:.1},{:.1} {:.1},{:.1} {:.1},{:.1} \
                     {:.1},{:.1} {:.1},{:.1}\"/>",
                    p0.0, p0.1, p1.0, p1.1, p2.0, p2.1,
                    p3.0, p3.1, p4.0, p4.1,
                ));
            }
        }
    }

    if plates.is_empty() {
        return Vec::new();
    }
    vec![format!(
        "<g opacity=\"0.35\" fill=\"none\" stroke=\"{FLAGSTONE_STROKE}\" \
         stroke-width=\"0.4\">{}</g>",
        plates.concat(),
    )]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_flagstone(&[], 333).is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32)> = (0..4)
            .flat_map(|y| (0..4).map(move |x| (x, y)))
            .collect();
        assert_eq!(draw_flagstone(&tiles, 333), draw_flagstone(&tiles, 333));
    }

    #[test]
    fn four_plates_per_tile() {
        let out = draw_flagstone(&[(0, 0)], 42);
        assert_eq!(out.len(), 1);
        let n_polygons = out[0].matches("<polygon").count();
        assert_eq!(n_polygons, 4, "4 quadrants × 1 pentagon each");
    }
}
