//! Thematic-detail primitive — Phase 4, sub-step 4.d (plan §8 Q3).
//!
//! Reproduces ``_tile_thematic_detail`` from
//! ``nhc/rendering/_floor_detail.py`` together with its three
//! per-fragment painters: ``_web_detail`` (spider-web with
//! 3-4 radials and 2 cross-thread rings), ``_bone_detail``
//! (2-3 crossed bones with bulbous epiphyses), and
//! ``_skull_detail`` (hand-drawn skull with cranium, eye
//! sockets, nasal cavity, tooth line, and mandible).
//!
//! Per-tile probabilities and the macabre-detail gate are
//! resolved Rust-side; the per-tile wall-corner bitmap (web
//! placement) and the corridor / room routing flag travel in
//! through the IR (see :func:`_emit_thematic_detail_ir`).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Output is gated by
//! structural invariants
//! (``tests/unit/test_emit_thematic_detail_invariants.py``)
//! plus a snapshot lock against the new Rust output (lands at
//! sub-step 4.f). The RNG is ``Pcg64Mcg::seed_from_u64(seed)``
//! (seed already carries the ``+199`` offset from the emitter).

use std::f64::consts::PI;

use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

const CELL: f64 = 32.0;
const INK: &str = "#000000";

#[derive(Clone, Copy, Default)]
struct ThemeProbs {
    web: f64,
    bones: f64,
    skull: f64,
}

/// Per-theme probabilities — mirrors ``_THEMATIC_DETAIL_PROBS``
/// from ``nhc/rendering/_floor_detail.py``. Default falls back
/// to the dungeon row.
fn theme_probs(theme: &str) -> ThemeProbs {
    match theme {
        "crypt" => ThemeProbs { web: 0.08, bones: 0.10, skull: 0.06 },
        "cave" => ThemeProbs { web: 0.12, bones: 0.04, skull: 0.02 },
        "sewer" => ThemeProbs { web: 0.06, bones: 0.03, skull: 0.01 },
        "castle" => ThemeProbs { web: 0.02, bones: 0.01, skull: 0.005 },
        "forest" => ThemeProbs { web: 0.04, bones: 0.01, skull: 0.005 },
        "abyss" => ThemeProbs { web: 0.05, bones: 0.08, skull: 0.10 },
        _ => ThemeProbs { web: 0.03, bones: 0.02, skull: 0.01 }, // dungeon
    }
}

struct Buckets {
    webs: Vec<String>,
    bones: Vec<String>,
    skulls: Vec<String>,
}

impl Buckets {
    fn new() -> Self {
        Self {
            webs: Vec::new(),
            bones: Vec::new(),
            skulls: Vec::new(),
        }
    }

    fn is_empty(&self) -> bool {
        self.webs.is_empty()
            && self.bones.is_empty()
            && self.skulls.is_empty()
    }
}

fn wrap_buckets(b: Buckets) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    if !b.webs.is_empty() {
        out.push(format!(
            "<g class=\"detail-webs\">{}</g>",
            b.webs.join(""),
        ));
    }
    if !b.bones.is_empty() {
        out.push(format!(
            "<g class=\"detail-bones\">{}</g>",
            b.bones.join(""),
        ));
    }
    if !b.skulls.is_empty() {
        out.push(format!(
            "<g class=\"detail-skulls\">{}</g>",
            b.skulls.join(""),
        ));
    }
    out
}

/// Spider-web fragment — mirrors ``_web_detail``. ``corner``:
/// 0=TL, 1=TR, 2=BL, 3=BR. Anchored at the wall corner of the
/// tile, radiating into the interior.
fn web_detail(rng: &mut Pcg64Mcg, px: f64, py: f64, corner: i32) -> String {
    let cx = if corner == 0 || corner == 2 { px } else { px + CELL };
    let cy = if corner == 0 || corner == 1 { py } else { py + CELL };
    let sx: f64 = if corner == 0 || corner == 2 { 1.0 } else { -1.0 };
    let sy: f64 = if corner == 0 || corner == 1 { 1.0 } else { -1.0 };

    let n_radials: i32 = rng.gen_range(3..=4);
    let radial_len: f64 =
        rng.gen_range((CELL * 0.5)..(CELL * 0.85));
    let mut angles: Vec<f64> = (0..n_radials)
        .map(|_| rng.gen_range(0.0..(PI / 2.0)))
        .collect();
    angles.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let mut parts: Vec<String> = Vec::new();

    // For each radial, emit the radial M-L plus two ring-points
    // for the cross-thread loops.
    let mut ring_pts: Vec<[(f64, f64); 2]> = Vec::new();
    for &a in &angles {
        let dx = sx * a.cos() * radial_len;
        let dy = sy * a.sin() * radial_len;
        let ex = cx + dx;
        let ey = cy + dy;
        parts.push(format!(
            "M{cx:.1},{cy:.1} L{ex:.1},{ey:.1}",
        ));
        ring_pts.push([
            (cx + dx * 0.4, cy + dy * 0.4),
            (cx + dx * 0.7, cy + dy * 0.7),
        ]);
    }

    // Cross-threads connecting consecutive radials at each ring.
    for ring_idx in 0..2 {
        for i in 0..(ring_pts.len().saturating_sub(1)) {
            let p1 = ring_pts[i][ring_idx];
            let p2 = ring_pts[i + 1][ring_idx];
            let mx = (p1.0 + p2.0) / 2.0 + rng.gen_range(-1.5..1.5);
            let my = (p1.1 + p2.1) / 2.0 + rng.gen_range(-1.5..1.5);
            parts.push(format!(
                "M{:.1},{:.1} Q{mx:.1},{my:.1} {:.1},{:.1}",
                p1.0, p1.1, p2.0, p2.1,
            ));
        }
    }

    let sw: f64 = rng.gen_range(0.3..0.6);
    format!(
        "<path d=\"{}\" fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{sw:.1}\" stroke-linecap=\"round\" \
         opacity=\"0.35\"/>",
        parts.join(" "),
    )
}

/// Pile of 2-3 crossed bones — mirrors ``_bone_detail``. Each
/// bone is a stroke + two filled epiphyses.
fn bone_detail(rng: &mut Pcg64Mcg, px: f64, py: f64) -> String {
    let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let n_bones: i32 = rng.gen_range(2..=3);

    let mut parts: Vec<String> = Vec::new();
    for _ in 0..n_bones {
        let angle: f64 = rng.gen_range(0.0..PI);
        let length: f64 =
            rng.gen_range((CELL * 0.2)..(CELL * 0.35));
        let dx = angle.cos() * length / 2.0;
        let dy = angle.sin() * length / 2.0;
        let bx = cx + rng.gen_range((-CELL * 0.08)..(CELL * 0.08));
        let by = cy + rng.gen_range((-CELL * 0.08)..(CELL * 0.08));
        let x1 = bx - dx;
        let y1 = by - dy;
        let x2 = bx + dx;
        let y2 = by + dy;
        parts.push(format!(
            "<line x1=\"{x1:.1}\" y1=\"{y1:.1}\" \
             x2=\"{x2:.1}\" y2=\"{y2:.1}\" \
             stroke=\"{INK}\" stroke-width=\"1.2\" \
             stroke-linecap=\"round\"/>",
        ));
        let er: f64 = rng.gen_range(1.2..1.8);
        for (ex, ey) in [(x1, y1), (x2, y2)] {
            parts.push(format!(
                "<ellipse cx=\"{ex:.1}\" cy=\"{ey:.1}\" \
                 rx=\"{er:.1}\" ry=\"{er:.1}\" fill=\"{INK}\"/>",
            ));
        }
    }
    format!("<g opacity=\"0.4\">{}</g>", parts.concat())
}

/// Hand-drawn skull — mirrors ``_skull_detail``. Composed of
/// cranium, eye sockets, nasal cavity, tooth line, and mandible
/// rendered in a translate+rotate group.
fn skull_detail(rng: &mut Pcg64Mcg, px: f64, py: f64) -> String {
    let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let s: f64 = rng.gen_range(0.8..1.2);
    let rot: f64 = rng.gen_range(-20.0..20.0);
    let sw = 0.7_f64;

    let cw = 4.5 * s;
    let ch = 5.0 * s;
    let zw = cw * 0.85;
    let mw = cw * 0.55;

    let top_y = -ch;
    let zyg_y = ch * 0.35;
    let max_y = ch * 0.55;

    let mut parts: Vec<String> = Vec::new();

    // Cranium
    parts.push(format!(
        "<path d=\"M{:.1},{zyg_y:.1} C{:.1},{:.1} {:.1},{top_y:.1} \
         0,{top_y:.1} C{:.1},{top_y:.1} {cw:.1},{:.1} {zw:.1},{zyg_y:.1} \
         L{mw:.1},{max_y:.1} L{:.1},{max_y:.1} Z\" \
         fill=\"none\" stroke=\"{INK}\" stroke-width=\"{sw}\"/>",
        -zw, -cw, -ch * 0.2, -cw * 0.6, cw * 0.6, -ch * 0.2, -mw,
    ));

    // Eye sockets
    let eye_y = -ch * 0.05;
    let eye_sep = cw * 0.42;
    let eye_rx = cw * 0.26;
    let eye_ry = ch * 0.16;
    for ex in [-eye_sep, eye_sep] {
        parts.push(format!(
            "<ellipse cx=\"{ex:.1}\" cy=\"{eye_y:.1}\" \
             rx=\"{eye_rx:.1}\" ry=\"{eye_ry:.1}\" fill=\"{INK}\"/>",
        ));
    }

    // Nasal cavity
    let nose_y = ch * 0.2;
    let nose_w = cw * 0.18;
    let nose_h = ch * 0.2;
    parts.push(format!(
        "<path d=\"M0,{nose_y:.1} L{:.1},{:.1} L{nose_w:.1},{:.1} Z\" \
         fill=\"{INK}\"/>",
        -nose_w,
        nose_y + nose_h,
        nose_y + nose_h,
    ));

    // Tooth line
    let tooth_y = max_y + s * 0.8;
    let tooth_w = mw * 0.75;
    parts.push(format!(
        "<line x1=\"{:.1}\" y1=\"{tooth_y:.1}\" \
         x2=\"{tooth_w:.1}\" y2=\"{tooth_y:.1}\" \
         stroke=\"{INK}\" stroke-width=\"0.4\" \
         stroke-dasharray=\"1.2,0.8\"/>",
        -tooth_w,
    ));

    // Mandible
    let jaw_top = max_y + s * 0.4;
    let chin_y = max_y + ch * 0.55;
    let ramus_w = mw * 1.05;
    let chin_w = mw * 0.35;
    parts.push(format!(
        "<path d=\"M{:.1},{jaw_top:.1} C{:.1},{:.1} {:.1},{chin_y:.1} \
         0,{chin_y:.1} C{chin_w:.1},{chin_y:.1} {ramus_w:.1},{:.1} \
         {ramus_w:.1},{jaw_top:.1}\" \
         fill=\"none\" stroke=\"{INK}\" stroke-width=\"{sw}\"/>",
        -ramus_w,
        -ramus_w,
        chin_y - s,
        -chin_w,
        chin_y - s,
    ));

    format!(
        "<g transform=\"translate({cx:.1},{cy:.1}) rotate({rot:.0})\" \
         opacity=\"0.45\">{}</g>",
        parts.concat(),
    )
}

/// Per-tile thematic painter — mirrors
/// ``_tile_thematic_detail`` from
/// ``nhc/rendering/_floor_detail.py``. The probability gates
/// fire in legacy order (web → bones → skull) so the RNG-stream
/// alignment matches the legacy interleaved walk.
fn tile_thematic_detail(
    rng: &mut Pcg64Mcg,
    x: i32,
    y: i32,
    wall_bits: u8,
    probs: &ThemeProbs,
    buckets: &mut Buckets,
) {
    let px = f64::from(x) * CELL;
    let py = f64::from(y) * CELL;

    if rng.gen::<f64>() < probs.web {
        let mut available: Vec<i32> = Vec::with_capacity(4);
        if wall_bits & 0x01 != 0 {
            available.push(0);
        }
        if wall_bits & 0x02 != 0 {
            available.push(1);
        }
        if wall_bits & 0x04 != 0 {
            available.push(2);
        }
        if wall_bits & 0x08 != 0 {
            available.push(3);
        }
        if !available.is_empty() {
            // Random pick mirrors `random.choice`.
            let &corner = available.choose(rng).unwrap();
            buckets.webs.push(web_detail(rng, px, py, corner));
        }
    }

    if rng.gen::<f64>() < probs.bones {
        buckets.bones.push(bone_detail(rng, px, py));
    }

    if rng.gen::<f64>() < probs.skull {
        buckets.skulls.push(skull_detail(rng, px, py));
    }
}

/// Thematic-detail layer entry point — Phase 4 sub-step 4.d.
///
/// `tiles` is the IR's candidate set (post-filter floor tiles
/// in y-major / x-minor order); each entry is `(x, y,
/// is_corridor, wall_corners)` where `wall_corners` is the
/// 4-bit TL/TR/BL/BR bitmap from the emitter. `seed` already
/// carries the `+199` legacy offset.
///
/// Returns `(room_groups, corridor_groups)`: two lists of `<g>`
/// envelope strings (`detail-webs` / `detail-bones` /
/// `detail-skulls` in legacy emit order). When `macabre` is
/// `false` the bones / skulls buckets are dropped (legacy
/// post-pass `if not macabre_detail: room_bones, room_skulls
/// = [], []`).
pub fn draw_thematic_detail(
    tiles: &[(i32, i32, bool, u8)],
    seed: u64,
    theme: &str,
    macabre: bool,
) -> (Vec<String>, Vec<String>) {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let probs = theme_probs(theme);

    let mut room = Buckets::new();
    let mut corridor = Buckets::new();

    for &(x, y, is_corridor, wall_bits) in tiles {
        let target = if is_corridor { &mut corridor } else { &mut room };
        tile_thematic_detail(&mut rng, x, y, wall_bits, &probs, target);
    }

    if !macabre {
        room.bones.clear();
        room.skulls.clear();
        corridor.bones.clear();
        corridor.skulls.clear();
    }

    let room_groups = if room.is_empty() {
        Vec::new()
    } else {
        wrap_buckets(room)
    };
    let corridor_groups = if corridor.is_empty() {
        Vec::new()
    } else {
        wrap_buckets(corridor)
    };
    (room_groups, corridor_groups)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty_groups() {
        let (r, c) = draw_thematic_detail(&[], 199, "crypt", true);
        assert!(r.is_empty());
        assert!(c.is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32, bool, u8)> = (0..30)
            .flat_map(|y| {
                (0..30).map(move |x| (x, y, x % 3 == 0, 0x05_u8))
            })
            .collect();
        let a = draw_thematic_detail(&tiles, 199, "crypt", true);
        let b = draw_thematic_detail(&tiles, 199, "crypt", true);
        assert_eq!(a, b);
    }

    #[test]
    fn macabre_off_drops_bones_and_skulls() {
        let tiles: Vec<(i32, i32, bool, u8)> = (0..40)
            .flat_map(|y| {
                (0..40).map(move |x| (x, y, false, 0x0_u8))
            })
            .collect();
        let (with, _) = draw_thematic_detail(&tiles, 41, "abyss", true);
        let (without, _) = draw_thematic_detail(&tiles, 41, "abyss", false);
        let bones_in = with
            .iter()
            .any(|g| g.contains("class=\"detail-bones\""));
        let skulls_in = with
            .iter()
            .any(|g| g.contains("class=\"detail-skulls\""));
        assert!(bones_in && skulls_in);
        let bones_out = without
            .iter()
            .any(|g| g.contains("class=\"detail-bones\""));
        let skulls_out = without
            .iter()
            .any(|g| g.contains("class=\"detail-skulls\""));
        assert!(!bones_out, "macabre=false must drop bone groups");
        assert!(!skulls_out, "macabre=false must drop skull groups");
    }

    #[test]
    fn webs_only_emit_when_wall_corners_available() {
        let tiles: Vec<(i32, i32, bool, u8)> = (0..40)
            .flat_map(|y| {
                (0..40).map(move |x| (x, y, false, 0x00_u8))
            })
            .collect();
        // High-web theme with NO wall corners → no webs.
        let (room, _) = draw_thematic_detail(&tiles, 7, "cave", true);
        assert!(
            !room.iter().any(|g| g.contains("class=\"detail-webs\"")),
            "no wall corners → no web groups"
        );
    }

    #[test]
    fn cave_theme_emits_more_webs_than_castle() {
        // Same wall-corner availability for both runs.
        let tiles: Vec<(i32, i32, bool, u8)> = (0..40)
            .flat_map(|y| {
                (0..40).map(move |x| (x, y, false, 0x0F_u8))
            })
            .collect();
        let (cave, _) = draw_thematic_detail(&tiles, 11, "cave", true);
        let (castle, _) = draw_thematic_detail(&tiles, 11, "castle", true);
        let cave_size: usize = cave.iter().map(|s| s.len()).sum();
        let castle_size: usize = castle.iter().map(|s| s.len()).sum();
        assert!(
            cave_size > castle_size,
            "cave envelope ({cave_size}) should exceed castle \
             envelope ({castle_size})"
        );
    }
}
