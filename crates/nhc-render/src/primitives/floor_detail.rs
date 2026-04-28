//! Floor-detail primitive — Phase 4, sub-step 3.d (plan §8 Q3).
//!
//! Reproduces the floor-detail-proper portion of
//! `_render_floor_detail` from `nhc/rendering/_floor_layers.py`:
//! the per-tile painters `_tile_detail` + `_floor_stone` +
//! `_y_scratch` (with its `_wobble_line` / `_edge_point` helpers)
//! produce three SVG fragment buckets (cracks / scratches /
//! stones) per side (room / corridor). The thematic painters
//! (`_tile_thematic_detail`, webs / bones / skulls) port at
//! step 4 into a separate `ThematicDetailOp`.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Output is gated by
//! structural invariants
//! (`tests/unit/test_emit_floor_detail_invariants.py`) plus a
//! snapshot lock that pins the new Rust output (lands at sub-
//! step 3.f). The RNG (`Pcg64Mcg::seed_from_u64(seed)`, where
//! `seed` already carries the legacy `+99` offset from the
//! emitter) is Rust-native; nothing here tracks the legacy
//! CPython `random.Random` MT19937 stream.

use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::perlin::pnoise2;

const CELL: f64 = 32.0;
const INK: &str = "#000000";
const FLOOR_STONE_FILL: &str = "#E8D5B8";
const FLOOR_STONE_STROKE: &str = "#666666";

/// Per-theme detail-density multiplier — pulled from
/// `_floor_detail._DETAIL_SCALE`. Crypts and caves get 2× more
/// detail; castles 0.8×; forests 0.6×; abyss 1.5×; everything
/// else (dungeon, sewer) 1.0×.
fn detail_scale(theme: &str) -> f64 {
    match theme {
        "crypt" | "cave" => 2.0,
        "castle" => 0.8,
        "forest" => 0.6,
        "abyss" => 1.5,
        _ => 1.0,
    }
}

/// Per-theme tile-detail probabilities. Caves take a denser
/// crack rate, fewer scratches, larger stones — same shape as
/// the legacy `_tile_detail` cave / non-cave branches.
struct TileParams {
    crack_prob: f64,
    scratch_prob: f64,
    stone_prob: f64,
    cluster_prob: f64,
    stone_scale: f64,
}

impl TileParams {
    fn for_theme(theme: &str) -> Self {
        if theme == "cave" {
            Self {
                crack_prob: 0.32,
                scratch_prob: 0.01,
                stone_prob: 0.10,
                cluster_prob: 0.06,
                stone_scale: 1.8,
            }
        } else {
            Self {
                crack_prob: 0.08,
                scratch_prob: 0.05,
                stone_prob: 0.06,
                cluster_prob: 0.03,
                stone_scale: 1.0,
            }
        }
    }
}

/// Per-side fragment buckets.
struct Buckets {
    cracks: Vec<(f64, f64, f64, f64)>, // x1, y1, x2, y2
    scratches: Vec<String>,             // wrapped <path> strings
    stones: Vec<String>,                // wrapped <ellipse> strings
}

impl Buckets {
    fn new() -> Self {
        Self {
            cracks: Vec::new(),
            scratches: Vec::new(),
            stones: Vec::new(),
        }
    }

    fn is_empty(&self) -> bool {
        self.cracks.is_empty()
            && self.scratches.is_empty()
            && self.stones.is_empty()
    }
}

/// Wrap the per-tile fragments into the three legacy `<g>`
/// envelopes. Mirrors `_floor_detail._emit_detail`.
fn wrap_buckets(buckets: Buckets) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    if !buckets.cracks.is_empty() {
        let mut s = String::from("<g opacity=\"0.5\">");
        for (x1, y1, x2, y2) in &buckets.cracks {
            s.push_str(&format!(
                "<line x1=\"{x1}\" y1=\"{y1}\" \
                 x2=\"{x2}\" y2=\"{y2}\" \
                 stroke=\"{INK}\" stroke-width=\"0.5\" \
                 stroke-linecap=\"round\"/>",
            ));
        }
        s.push_str("</g>");
        out.push(s);
    }
    if !buckets.scratches.is_empty() {
        let mut s = String::from("<g class=\"y-scratch\" opacity=\"0.45\">");
        for frag in &buckets.scratches {
            s.push_str(frag);
        }
        s.push_str("</g>");
        out.push(s);
    }
    if !buckets.stones.is_empty() {
        let mut s = String::from("<g opacity=\"0.8\">");
        for frag in &buckets.stones {
            s.push_str(frag);
        }
        s.push_str("</g>");
        out.push(s);
    }
    out
}

/// Single floor stone — brown ellipse. Mirrors
/// `_floor_detail._floor_stone`.
fn floor_stone(rng: &mut Pcg64Mcg, px: f64, py: f64, scale: f64) -> String {
    let sx = px + rng.gen_range((CELL * 0.25)..(CELL * 0.75));
    let sy = py + rng.gen_range((CELL * 0.25)..(CELL * 0.75));
    let rx = rng.gen_range(2.0..(CELL * 0.15)) * scale;
    let ry = rng.gen_range(2.0..(CELL * 0.12)) * scale;
    let angle: f64 = rng.gen_range(0.0..180.0);
    let sw: f64 = rng.gen_range(1.2..2.0);
    format!(
        "<ellipse cx=\"{sx:.1}\" cy=\"{sy:.1}\" \
         rx=\"{rx:.1}\" ry=\"{ry:.1}\" \
         transform=\"rotate({angle:.0},{sx:.1},{sy:.1})\" \
         fill=\"{FLOOR_STONE_FILL}\" stroke=\"{FLOOR_STONE_STROKE}\" \
         stroke-width=\"{sw:.1}\"/>",
    )
}

/// Random point on a tile edge. `edge`: 0=top, 1=right,
/// 2=bottom, 3=left. Mirrors `_svg_helpers._edge_point`.
fn edge_point(rng: &mut Pcg64Mcg, edge: i32, px: f64, py: f64) -> (f64, f64) {
    let t: f64 = rng.gen_range(0.2..0.8);
    match edge {
        0 => (px + t * CELL, py),
        1 => (px + CELL, py + t * CELL),
        2 => (px + t * CELL, py + CELL),
        _ => (px, py + t * CELL),
    }
}

/// Perlin-displaced wobbly line segment. Mirrors
/// `_svg_helpers._wobble_line`. `seed` keys the Perlin offset
/// per-segment so adjacent calls don't accidentally rhyme.
fn wobble_line(
    rng: &mut Pcg64Mcg,
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    seed: i32,
    n_seg: i32,
) -> String {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let length = (dx * dx + dy * dy).sqrt();
    if length < 0.1 {
        return format!("M{x0:.1},{y0:.1} L{x1:.1},{y1:.1}");
    }
    let nx = -dy / length;
    let ny = dx / length;
    let wobble = length * 0.12;
    let mut parts: Vec<String> =
        Vec::with_capacity(n_seg as usize + 1);
    parts.push(format!("M{x0:.1},{y0:.1}"));
    for i in 1..=n_seg {
        let t = f64::from(i) / f64::from(n_seg);
        let mut mx = x0 + dx * t;
        let mut my = y0 + dy * t;
        if i < n_seg {
            let mut w = pnoise2(mx * 0.15 + f64::from(seed), my * 0.15, 77)
                * wobble;
            w += rng.gen_range((-wobble * 0.3)..(wobble * 0.3));
            mx += nx * w;
            my += ny * w;
        }
        parts.push(format!("L{mx:.1},{my:.1}"));
    }
    parts.join(" ")
}

/// Y-shaped scratch with 3 ends on tile edges. Mirrors
/// `_svg_helpers._y_scratch`.
fn y_scratch(
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
    gx: i32,
    gy: i32,
    seed: u64,
) -> String {
    // Pick 3 distinct edges out of {0, 1, 2, 3}.
    let mut edges = [0_i32, 1, 2, 3];
    edges.shuffle(rng);
    let p0 = edge_point(rng, edges[0], px, py);
    let p1 = edge_point(rng, edges[1], px, py);
    let p2 = edge_point(rng, edges[2], px, py);

    // Fork point: weighted mean biased to tile centre with jitter.
    let cx = (p0.0 + p1.0 + p2.0) / 3.0;
    let cy = (p0.1 + p1.1 + p2.1) / 3.0;
    let tc_x = px + CELL * 0.5;
    let tc_y = py + CELL * 0.5;
    let fx = cx * 0.4 + tc_x * 0.6
        + rng.gen_range((-CELL * 0.1)..(CELL * 0.1));
    let fy = cy * 0.4 + tc_y * 0.6
        + rng.gen_range((-CELL * 0.1)..(CELL * 0.1));

    // Per-scratch offset key — mirrors the legacy
    // `seed + gx * 7 + gy` synthetic offset feeding
    // `_wobble_line` for each branch, with the +13 / +29 shifts
    // so the three branches don't rhyme.
    let ns: i32 =
        ((seed as i64) + (gx as i64) * 7 + gy as i64) as i32;
    let b0 = wobble_line(rng, fx, fy, p0.0, p0.1, ns, 4);
    let b1 = wobble_line(rng, fx, fy, p1.0, p1.1, ns + 13, 4);
    let b2 = wobble_line(rng, fx, fy, p2.0, p2.1, ns + 29, 4);

    let sw: f64 = rng.gen_range(0.3..0.7);
    format!(
        "<path d=\"{b0} {b1} {b2}\" fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{sw:.1}\" stroke-linecap=\"round\"/>",
    )
}

/// Per-tile detail — cracks, scratches, stones, clusters.
/// Mirrors `_floor_detail._tile_detail`.
fn tile_detail(
    rng: &mut Pcg64Mcg,
    x: i32,
    y: i32,
    seed: u64,
    buckets: &mut Buckets,
    params: &TileParams,
    detail_mul: f64,
) {
    let px = f64::from(x) * CELL;
    let py = f64::from(y) * CELL;

    let crack_p = params.crack_prob * detail_mul;
    let scratch_p = params.scratch_prob * detail_mul;

    let roll: f64 = rng.gen();
    if roll < crack_p {
        let corner: i32 = rng.gen_range(0..=3);
        let s1: f64 = rng.gen_range((CELL * 0.15)..(CELL * 0.4));
        let s2: f64 = rng.gen_range((CELL * 0.15)..(CELL * 0.4));
        let crack = match corner {
            0 => (px + s1, py, px, py + s2),
            1 => (px + CELL - s1, py, px + CELL, py + s2),
            2 => (px + s1, py + CELL, px, py + CELL - s2),
            _ => (px + CELL - s1, py + CELL, px + CELL, py + CELL - s2),
        };
        buckets.cracks.push(crack);
    } else if roll < crack_p + scratch_p {
        buckets.scratches.push(y_scratch(rng, px, py, x, y, seed));
    }

    if rng.gen::<f64>() < params.stone_prob * detail_mul {
        buckets
            .stones
            .push(floor_stone(rng, px, py, params.stone_scale));
    }

    if rng.gen::<f64>() < params.cluster_prob * detail_mul {
        let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        for _ in 0..3 {
            let sx = cx + rng.gen_range((-CELL * 0.2)..(CELL * 0.2));
            let sy = cy + rng.gen_range((-CELL * 0.2)..(CELL * 0.2));
            let scale: f64 =
                rng.gen_range(0.5..1.3) * params.stone_scale;
            let rx = rng.gen_range(2.0..(CELL * 0.15)) * scale;
            let ry = rng.gen_range(2.0..(CELL * 0.12)) * scale;
            let angle: f64 = rng.gen_range(0.0..180.0);
            let sw: f64 = rng.gen_range(1.2..2.0);
            buckets.stones.push(format!(
                "<ellipse cx=\"{sx:.1}\" cy=\"{sy:.1}\" \
                 rx=\"{rx:.1}\" ry=\"{ry:.1}\" \
                 transform=\"rotate({angle:.0},{sx:.1},{sy:.1})\" \
                 fill=\"{FLOOR_STONE_FILL}\" \
                 stroke=\"{FLOOR_STONE_STROKE}\" \
                 stroke-width=\"{sw:.1}\"/>",
            ));
        }
    }
}

/// Floor-detail layer entry point — Phase 4 sub-step 3.d.
///
/// `tiles` is the IR's post-filter candidate set produced
/// emit-side at sub-step 3.b: floor tiles in y-major /
/// x-minor order with a parallel `is_corridor` flag (third
/// tuple element). `seed` already carries the `+99` legacy
/// offset (set on emit at `_floor_layers.py:_emit_floor_detail_ir`).
///
/// Returns `(room_groups, corridor_groups)`: two lists of
/// `<g>` envelope strings ready for the dispatcher to splat.
/// Each side carries up to three groups (cracks / scratches /
/// stones) in legacy emit order; empty lists when the tile set
/// produces no fragments. When `macabre` is `false`, the stone
/// buckets are dropped entirely (legacy `if not macabre_detail:
/// stones = []` post-pass).
pub fn draw_floor_detail(
    tiles: &[(i32, i32, bool)],
    seed: u64,
    theme: &str,
    macabre: bool,
) -> (Vec<String>, Vec<String>) {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let params = TileParams::for_theme(theme);
    let detail_mul = detail_scale(theme);

    let mut room = Buckets::new();
    let mut corridor = Buckets::new();

    for &(x, y, is_corridor) in tiles {
        let target = if is_corridor { &mut corridor } else { &mut room };
        tile_detail(&mut rng, x, y, seed, target, &params, detail_mul);
    }

    if !macabre {
        room.stones.clear();
        corridor.stones.clear();
    }

    let room_groups =
        if room.is_empty() { Vec::new() } else { wrap_buckets(room) };
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
        let (r, c) = draw_floor_detail(&[], 1234, "dungeon", true);
        assert!(r.is_empty());
        assert!(c.is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32, bool)> = (0..30)
            .flat_map(|y| (0..30).map(move |x| (x, y, x % 3 == 0)))
            .collect();
        let a = draw_floor_detail(&tiles, 99, "dungeon", true);
        let b = draw_floor_detail(&tiles, 99, "dungeon", true);
        assert_eq!(a, b);
    }

    #[test]
    fn cave_theme_emits_more_cracks() {
        let tiles: Vec<(i32, i32, bool)> = (0..40)
            .flat_map(|y| (0..40).map(move |x| (x, y, false)))
            .collect();
        let (dungeon_room, _) =
            draw_floor_detail(&tiles, 7, "dungeon", true);
        let (cave_room, _) =
            draw_floor_detail(&tiles, 7, "cave", true);
        // Caves use 0.32 crack_prob × 2.0 detail_scale = 0.64,
        // dungeons use 0.08 × 1.0 = 0.08 — caves should produce
        // a substantially larger crack envelope.
        let dungeon_chars: usize =
            dungeon_room.iter().map(|s| s.len()).sum();
        let cave_chars: usize = cave_room.iter().map(|s| s.len()).sum();
        assert!(
            cave_chars > dungeon_chars,
            "cave envelope ({cave_chars}) should exceed dungeon \
             envelope ({dungeon_chars}) for the same tile set"
        );
    }

    #[test]
    fn macabre_off_drops_stones() {
        let tiles: Vec<(i32, i32, bool)> = (0..40)
            .flat_map(|y| (0..40).map(move |x| (x, y, false)))
            .collect();
        let (with_stones, _) =
            draw_floor_detail(&tiles, 41, "crypt", true);
        let (without_stones, _) =
            draw_floor_detail(&tiles, 41, "crypt", false);
        let with_count: usize = with_stones
            .iter()
            .map(|s| s.matches("<ellipse").count())
            .sum();
        let without_count: usize = without_stones
            .iter()
            .map(|s| s.matches("<ellipse").count())
            .sum();
        assert!(with_count > 0);
        assert_eq!(
            without_count, 0,
            "macabre=false must drop stone ellipses entirely"
        );
    }

    #[test]
    fn coordinates_stay_inside_bounds() {
        let tiles: Vec<(i32, i32, bool)> = (0..20)
            .flat_map(|y| (0..20).map(move |x| (x, y, y % 2 == 0)))
            .collect();
        let (room, corridor) =
            draw_floor_detail(&tiles, 13, "crypt", true);
        // Tile span is [0, 20*CELL]; allow a 2-cell margin for
        // the wobble-displaced scratch endpoints (the legacy
        // wobble width is `length * 0.12`, well within 1 cell).
        let max_coord = 22.0 * CELL;
        let min_coord = -CELL;
        let mut probed = 0;
        for group in room.iter().chain(corridor.iter()) {
            // Probe every numeric attribute pair we emit.
            for attr in ["x1=\"", "y1=\"", "x2=\"", "y2=\"", "cx=\"", "cy=\""] {
                let mut rest = group.as_str();
                while let Some(idx) = rest.find(attr) {
                    rest = &rest[idx + attr.len()..];
                    let end = rest.find('"').unwrap();
                    let v: f64 = rest[..end].parse().unwrap();
                    assert!(
                        v >= min_coord && v <= max_coord,
                        "coord {v} outside [{min_coord}, {max_coord}]"
                    );
                    rest = &rest[end + 1..];
                    probed += 1;
                }
            }
        }
        assert!(probed > 0, "no coordinates probed");
    }
}
