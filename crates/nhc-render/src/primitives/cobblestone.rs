//! Cobblestone decorator — Phase 4, sub-step 6 (plan §8 Q2).
//!
//! Reproduces ``COBBLESTONE`` (3×3 jittered grid per tile) plus
//! ``COBBLE_STONE`` (decorative stone with 12 % per-tile chance)
//! from ``nhc/rendering/_floor_detail.py``. Both decorators fire
//! on the same predicate (``surface_type ∈ {STREET, PAVED}``)
//! but use independent RNGs (legacy ``_seeded_rng`` derives them
//! from the decorator name).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. The Rust port uses
//! ``Pcg64Mcg`` for both sub-decorators (independent streams
//! from the input seed); under-test fixtures only contain dungeon
//! / cave levels, so cobble emission is exercised via synthetic
//! tile lists in the cargo / Python integration tests.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;
const COBBLE_STROKE: &str = "#8A7A6A";
const STONE_FILL: &str = "#C8BEB0";
const STONE_STROKE: &str = "#9A8A7A";

/// Cobblestone-grid painter. Mirrors ``_cobblestone_tile``: a
/// 3×3 grid of jittered rounded rectangles, one tile.
fn cobblestone_tile(
    rng: &mut Pcg64Mcg, px: f64, py: f64, out: &mut Vec<String>,
) {
    let cols = 3.0_f64;
    let rows = 3.0_f64;
    let cw = CELL / cols;
    let ch = CELL / rows;
    for row in 0..3 {
        for col in 0..3 {
            let jx = rng.gen_range((-cw * 0.1)..(cw * 0.1));
            let jy = rng.gen_range((-ch * 0.1)..(ch * 0.1));
            let jw = rng.gen_range((-cw * 0.08)..(cw * 0.08));
            let jh = rng.gen_range((-ch * 0.08)..(ch * 0.08));
            let cx = px + f64::from(col) * cw + jx + 0.5;
            let cy = py + f64::from(row) * ch + jy + 0.5;
            let sw = cw + jw - 1.0;
            let sh = ch + jh - 1.0;
            if sw > 2.0 && sh > 2.0 {
                out.push(format!(
                    "<rect x=\"{cx:.1}\" y=\"{cy:.1}\" \
                     width=\"{sw:.1}\" height=\"{sh:.1}\" \
                     rx=\"1\"/>",
                ));
            }
        }
    }
}

/// Decorative-stone painter. Mirrors ``_cobble_stone``: an
/// ellipse with random size and rotation. Caller has already
/// gated on the 12 % probability.
fn cobble_stone(
    rng: &mut Pcg64Mcg, px: f64, py: f64, out: &mut Vec<String>,
) {
    let cx = px + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
    let cy = py + rng.gen_range((CELL * 0.2)..(CELL * 0.8));
    let rx: f64 = rng.gen_range(1.5..3.0);
    let ry: f64 = rng.gen_range(1.0..2.5);
    let angle: f64 = rng.gen_range(0.0..180.0);
    out.push(format!(
        "<ellipse cx=\"{cx:.1}\" cy=\"{cy:.1}\" \
         rx=\"{rx:.1}\" ry=\"{ry:.1}\" \
         transform=\"rotate({angle:.0},{cx:.1},{cy:.1})\" \
         fill=\"{STONE_FILL}\" stroke=\"{STONE_STROKE}\" \
         stroke-width=\"0.5\"/>",
    ));
}

/// Cobblestone decorator entry point — Phase 4 sub-step 6.
///
/// `tiles` is the cobble-tile list (post-filter by
/// ``_is_cobble_tile``), in the IR's y-major / x-minor order.
/// `seed` already includes the decorator-pipeline offset
/// (``base_seed + 333``); the two sub-decorators
/// (cobblestone grid, cobble stone) draw their own
/// independent ``Pcg64Mcg`` streams from ``seed`` and
/// ``seed ^ 0xC0BB1E_5701E``.
///
/// Returns up to two ``<g>`` envelope strings in legacy emit
/// order: the cobblestone grid (always, when any tile produces
/// rects) and the cobble-stone group (when at least one stone
/// rolled in). Empty list when ``tiles`` is empty.
pub fn draw_cobblestone(
    tiles: &[(i32, i32)],
    seed: u64,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }

    // Two independent RNGs — mirrors the legacy
    // _seeded_rng(name) per-decorator split.
    let mut grid_rng = Pcg64Mcg::seed_from_u64(seed);
    let mut stone_rng = Pcg64Mcg::seed_from_u64(seed ^ 0x_C0BB_1E57_01E_u64);

    let mut grid: Vec<String> = Vec::new();
    let mut stones: Vec<String> = Vec::new();

    for &(x, y) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        cobblestone_tile(&mut grid_rng, px, py, &mut grid);
        if stone_rng.gen::<f64>() < 0.12 {
            cobble_stone(&mut stone_rng, px, py, &mut stones);
        }
    }

    let mut out: Vec<String> = Vec::new();
    if !grid.is_empty() {
        out.push(format!(
            "<g opacity=\"0.35\" fill=\"none\" \
             stroke=\"{COBBLE_STROKE}\" stroke-width=\"0.4\">{}</g>",
            grid.concat(),
        ));
    }
    if !stones.is_empty() {
        out.push(format!("<g opacity=\"0.5\">{}</g>", stones.concat()));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_cobblestone(&[], 333).is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32)> = (0..10)
            .flat_map(|y| (0..10).map(move |x| (x, y)))
            .collect();
        assert_eq!(
            draw_cobblestone(&tiles, 333),
            draw_cobblestone(&tiles, 333),
        );
    }

    #[test]
    fn different_seeds_diverge() {
        let tiles: Vec<(i32, i32)> = (0..10)
            .flat_map(|y| (0..10).map(move |x| (x, y)))
            .collect();
        let a = draw_cobblestone(&tiles, 333);
        let b = draw_cobblestone(&tiles, 7);
        assert_ne!(a, b, "different seeds should produce different output");
    }

    #[test]
    fn grid_emits_per_tile_rect_count() {
        // Single-tile input: 9 rects unless rare jitter rejects
        // any. Pin the count at the realistic upper bound.
        let (out_seed, count) = (42_u64, 9);
        let out = draw_cobblestone(&[(0, 0)], out_seed);
        assert!(!out.is_empty());
        let grid_group = &out[0];
        let n = grid_group.matches("<rect").count();
        assert!(
            n <= count && n >= count - 2,
            "expected ~{count} rects per tile, got {n}"
        );
    }

    #[test]
    fn stones_appear_with_enough_tiles() {
        // 12 % per tile × 200 tiles → ~24 stones expected.
        let tiles: Vec<(i32, i32)> = (0..20)
            .flat_map(|y| (0..10).map(move |x| (x, y)))
            .collect();
        let out = draw_cobblestone(&tiles, 333);
        let any_stones = out
            .iter()
            .any(|g| g.contains("opacity=\"0.5\"")
                && g.contains("<ellipse"));
        assert!(any_stones, "at 12 % over 200 tiles, expect a stone group");
    }
}
