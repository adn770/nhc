//! Terrain-detail per-tile painters — Phase 9.1c port of
//! `nhc/rendering/_terrain_detail.py`.
//!
//! Reproduces the per-tile water ripples (`_water_detail`), lava
//! cracks + embers (`_lava_detail`) and chasm hatches
//! (`_chasm_detail`) as Rust primitives that ship `<g>` envelope
//! strings into `paint_fragments`.
//!
//! **Parity contract (relaxed gate, plan §9.1):** byte-equal-with-
//! legacy is *not* required. The Rust port uses `Pcg64Mcg` per
//! decorator (independent streams XOR'd off the input seed); the
//! reference PNG fixtures gate on `PSNR > 35 dB` per
//! `design/map_ir.md` §9.4.
//!
//! Group-open colours come from the *dungeon* theme palette
//! because the legacy `_terrain_group_open` hard-codes that
//! palette; the per-tile lava ember `fill` reads the running
//! theme's `lava.detail_ink`, exposed through `lava_ink` on the
//! caller side.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;

const WATER_INK: &str = "#4A7888";
const WATER_OPACITY: f64 = 0.35;
const CHASM_INK: &str = "#444444";
const CHASM_OPACITY: f64 = 0.35;
const LAVA_INK: &str = "#A04030";
const LAVA_OPACITY: f64 = 0.40;

const WATER_SEED_SALT: u64 = 0x_77AA_2E22_7E2E_7A77;
const LAVA_SEED_SALT: u64 = 0x_1A7A_BEEF_DEAD_F1AA;
const CHASM_SEED_SALT: u64 = 0x_C4A5_D00D_FACE_B0BA;

fn water_tile(
    rng: &mut Pcg64Mcg, px: f64, py: f64, out: &mut Vec<String>,
) {
    let n_waves = rng.gen_range(2..=3);
    for i in 0..n_waves {
        let t = f64::from(i + 1) / f64::from(n_waves + 1);
        let y0 = py + CELL * t;
        let mut segs: Vec<String> = Vec::with_capacity(6);
        segs.push(format!("M{:.1},{:.1}", px + CELL * 0.1, y0));
        let steps = 5_i32;
        for s in 1..=steps {
            let sx = px + CELL * 0.1 + (CELL * 0.8) * f64::from(s) / f64::from(steps);
            let sy = y0 + rng.gen_range((-CELL * 0.06)..(CELL * 0.06));
            segs.push(format!("L{sx:.1},{sy:.1}"));
        }
        let sw: f64 = rng.gen_range(0.4..0.8);
        out.push(format!(
            "<path d=\"{}\" fill=\"none\" stroke-width=\"{:.1}\"/>",
            segs.join(" "), sw,
        ));
    }
    if rng.gen::<f64>() < 0.10 {
        let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let r: f64 = rng.gen_range((CELL * 0.06)..(CELL * 0.12));
        out.push(format!(
            "<circle cx=\"{cx:.1}\" cy=\"{cy:.1}\" r=\"{r:.1}\" \
             fill=\"none\" stroke-width=\"0.4\"/>",
        ));
    }
}

fn lava_tile(
    rng: &mut Pcg64Mcg, px: f64, py: f64, ember_ink: &str,
    out: &mut Vec<String>,
) {
    let n_cracks = rng.gen_range(1..=2);
    for _ in 0..n_cracks {
        let x0 = px + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let y0 = py + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let x1 = px + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let y1 = py + rng.gen_range((CELL * 0.1)..(CELL * 0.9));
        let sw: f64 = rng.gen_range(0.5..1.0);
        out.push(format!(
            "<line x1=\"{x0:.1}\" y1=\"{y0:.1}\" \
             x2=\"{x1:.1}\" y2=\"{y1:.1}\" \
             stroke-width=\"{sw:.1}\"/>",
        ));
    }
    if rng.gen::<f64>() < 0.20 {
        let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let r: f64 = rng.gen_range((CELL * 0.04)..(CELL * 0.08));
        out.push(format!(
            "<circle cx=\"{cx:.1}\" cy=\"{cy:.1}\" r=\"{r:.1}\" \
             fill=\"{ember_ink}\" stroke=\"none\" opacity=\"0.4\"/>",
        ));
    }
}

fn chasm_tile(
    rng: &mut Pcg64Mcg, px: f64, py: f64, out: &mut Vec<String>,
) {
    let n_lines = rng.gen_range(2..=3);
    for i in 0..n_lines {
        let t = f64::from(i + 1) / f64::from(n_lines + 1);
        let offset = CELL * t;
        let sw: f64 = rng.gen_range(0.4..0.8);
        let x0 = px + offset + rng.gen_range(-2.0..2.0);
        let y0 = py + rng.gen_range(0.0..(CELL * 0.15));
        let x1 = px + offset + rng.gen_range(-2.0..2.0);
        let y1 = py + CELL - rng.gen_range(0.0..(CELL * 0.15));
        out.push(format!(
            "<line x1=\"{x0:.1}\" y1=\"{y0:.1}\" \
             x2=\"{x1:.1}\" y2=\"{y1:.1}\" \
             stroke-width=\"{sw:.1}\"/>",
        ));
    }
}

/// Water-ripple painter. Returns a single-element `Vec` with the
/// `<g class="terrain-water">` envelope, or an empty vec when
/// `tiles` is empty.
pub fn draw_water(tiles: &[(i32, i32)], seed: u64) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ WATER_SEED_SALT);
    let mut elements: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        water_tile(
            &mut rng,
            f64::from(x) * CELL,
            f64::from(y) * CELL,
            &mut elements,
        );
    }
    if elements.is_empty() {
        return Vec::new();
    }
    vec![format!(
        "<g class=\"terrain-water\" opacity=\"{WATER_OPACITY}\" \
         stroke=\"{WATER_INK}\" stroke-linecap=\"round\">{}</g>",
        elements.concat(),
    )]
}

/// Lava-detail painter. `ember_ink` is the running theme's
/// `lava.detail_ink` — used as the ember-dot fill colour.
pub fn draw_lava(
    tiles: &[(i32, i32)], seed: u64, ember_ink: &str,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ LAVA_SEED_SALT);
    let mut elements: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        lava_tile(
            &mut rng,
            f64::from(x) * CELL,
            f64::from(y) * CELL,
            ember_ink,
            &mut elements,
        );
    }
    if elements.is_empty() {
        return Vec::new();
    }
    vec![format!(
        "<g class=\"terrain-lava\" opacity=\"{LAVA_OPACITY}\" \
         stroke=\"{LAVA_INK}\" stroke-linecap=\"round\">{}</g>",
        elements.concat(),
    )]
}

/// Chasm hatch-line painter.
pub fn draw_chasm(tiles: &[(i32, i32)], seed: u64) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ CHASM_SEED_SALT);
    let mut elements: Vec<String> = Vec::new();
    for &(x, y) in tiles {
        chasm_tile(
            &mut rng,
            f64::from(x) * CELL,
            f64::from(y) * CELL,
            &mut elements,
        );
    }
    if elements.is_empty() {
        return Vec::new();
    }
    vec![format!(
        "<g class=\"terrain-chasm\" opacity=\"{CHASM_OPACITY}\" \
         stroke=\"{CHASM_INK}\" stroke-linecap=\"round\">{}</g>",
        elements.concat(),
    )]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn grid(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_water(&[], 200).is_empty());
        assert!(draw_lava(&[], 200, "#A04030").is_empty());
        assert!(draw_chasm(&[], 200).is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let t = grid(8);
        assert_eq!(draw_water(&t, 200), draw_water(&t, 200));
        assert_eq!(
            draw_lava(&t, 200, "#A04030"),
            draw_lava(&t, 200, "#A04030"),
        );
        assert_eq!(draw_chasm(&t, 200), draw_chasm(&t, 200));
    }

    #[test]
    fn different_seeds_diverge() {
        let t = grid(8);
        assert_ne!(draw_water(&t, 200), draw_water(&t, 7));
        assert_ne!(
            draw_lava(&t, 200, "#A04030"),
            draw_lava(&t, 7, "#A04030"),
        );
        assert_ne!(draw_chasm(&t, 200), draw_chasm(&t, 7));
    }

    #[test]
    fn streams_independent_across_kinds() {
        // Water/lava/chasm at the same seed must not share an
        // RNG stream; the per-kind salt buys independence.
        let t = grid(4);
        let w = draw_water(&t, 200);
        let l = draw_lava(&t, 200, "#A04030");
        let c = draw_chasm(&t, 200);
        assert_ne!(w, l);
        assert_ne!(l, c);
        assert_ne!(w, c);
    }

    #[test]
    fn water_envelope_carries_class_and_stroke() {
        let out = draw_water(&[(0, 0), (1, 0)], 200);
        assert_eq!(out.len(), 1);
        let g = &out[0];
        assert!(g.contains("class=\"terrain-water\""));
        assert!(g.contains(&format!("stroke=\"{WATER_INK}\"")));
        assert!(g.contains("stroke-linecap=\"round\""));
        // 2..=3 wave paths per tile, plus optional ripple, over 2 tiles.
        let n_paths = g.matches("<path").count();
        assert!((4..=6).contains(&n_paths));
    }

    #[test]
    fn lava_envelope_uses_passed_ember_ink() {
        // Force a tile count high enough to almost certainly
        // roll an ember (20 % per tile × 50 tiles ≈ 10 expected).
        let t = grid(8);
        let crypt_ink = "#903828";
        let out = draw_lava(&t, 99, crypt_ink);
        assert_eq!(out.len(), 1);
        let g = &out[0];
        assert!(g.contains(&format!("fill=\"{crypt_ink}\"")));
    }

    #[test]
    fn chasm_envelope_emits_only_lines() {
        let out = draw_chasm(&[(0, 0)], 200);
        assert_eq!(out.len(), 1);
        let g = &out[0];
        assert!(g.contains("<line"));
        assert!(!g.contains("<path"));
        assert!(!g.contains("<circle"));
    }
}
