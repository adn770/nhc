//! Brick decorator — Phase 4, sub-step 7 (plan §8 Q2).
//!
//! Reproduces ``BRICK`` (4×2 running-bond brick layout per tile)
//! from ``nhc/rendering/_floor_detail.py``. Each row is two
//! full bricks; odd rows shift by half a brick so courses
//! interlock. Per-brick jitter gives a hand-drawn look.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Existing fixtures
//! contain no BRICK tiles; coverage rides on synthetic-level
//! Python integration tests plus cargo unit tests.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;
const BRICK_STROKE: &str = "#A05530";

/// Brick decorator entry point — Phase 4 sub-step 7.
///
/// `tiles` is the BRICK-surface tile list. `seed` already
/// includes the legacy `+333` decorator-pipeline offset.
/// Returns one `<g>` envelope (running-bond rects) or empty.
pub fn draw_brick(tiles: &[(i32, i32)], seed: u64) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed);

    let bw = CELL / 2.0;
    let bh = CELL / 4.0;

    let mut bricks: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        for row in 0..4 {
            let offset = if row % 2 == 1 { bw / 2.0 } else { 0.0 };
            let cols = if offset > 0.0 { 3 } else { 2 };
            for col in 0..cols {
                let x0 = px + f64::from(col) * bw - offset;
                let y0 = py + f64::from(row) * bh;
                let jx = rng.gen_range((-bw * 0.06)..(bw * 0.06));
                let jy = rng.gen_range((-bh * 0.06)..(bh * 0.06));
                let jw = rng.gen_range((-bw * 0.06)..(bw * 0.06));
                let jh = rng.gen_range((-bh * 0.06)..(bh * 0.06));
                let mut bx = x0 + jx + 0.5;
                let by = y0 + jy + 0.5;
                let mut bw_jit = bw + jw - 1.0;
                let bh_jit = bh + jh - 1.0;
                if bx < px {
                    bw_jit -= px - bx;
                    bx = px;
                }
                if bx + bw_jit > px + CELL {
                    bw_jit = px + CELL - bx;
                }
                if bw_jit > 1.5 && bh_jit > 1.5 {
                    bricks.push(format!(
                        "<rect x=\"{bx:.1}\" y=\"{by:.1}\" \
                         width=\"{bw_jit:.1}\" \
                         height=\"{bh_jit:.1}\" rx=\"0.5\"/>",
                    ));
                }
            }
        }
    }

    if bricks.is_empty() {
        return Vec::new();
    }
    vec![format!(
        "<g opacity=\"0.35\" fill=\"none\" stroke=\"{BRICK_STROKE}\" \
         stroke-width=\"0.4\">{}</g>",
        bricks.concat(),
    )]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_brick(&[], 333).is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32)> = (0..6)
            .flat_map(|y| (0..6).map(move |x| (x, y)))
            .collect();
        assert_eq!(draw_brick(&tiles, 333), draw_brick(&tiles, 333));
    }

    #[test]
    fn brick_stroke_present() {
        let out = draw_brick(&[(0, 0)], 42);
        assert!(!out.is_empty());
        assert!(out[0].contains("#A05530"));
    }
}
