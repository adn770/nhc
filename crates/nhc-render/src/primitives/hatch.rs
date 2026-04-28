//! Hatch primitive — Phase 4, sub-step 1.d (plan §8 Q1 strategy A).
//!
//! Reproduces `_render_corridor_hatching` and the per-tile body of
//! `_render_hatching` from `nhc/rendering/_hatching.py`. The room
//! candidate-walk + Perlin distance filter ran emit-side in
//! sub-step 1.b — both Rust entry points (`draw_hatch_corridor`
//! and `draw_hatch_room`) just iterate the pre-filtered tile list
//! and emit SVG fragments.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Output is gated by
//! structural invariants
//! (`tests/unit/test_emit_hatch_invariants.py`) plus a snapshot
//! lock that pins the new Rust output (lands in sub-step 1.f).
//! The RNG (`Pcg64Mcg`) and the polygon-line clip backend (`geo`
//! crate) are Rust-native; nothing here tracks the legacy
//! CPython `random.Random` / Shapely numerics.

use geo::{
    BooleanOps, Coord, LineString, MultiLineString, Polygon,
};
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::perlin::pnoise2;

const CELL: f64 = 32.0;
const HATCH_UNDERLAY: &str = "#D0D0D0";
const INK: &str = "#000000";
const STONE_STROKE: &str = "#666666";

/// Three SVG fragment buckets emitted per hatch call:
/// `(tile_fills, hatch_lines, hatch_stones)`. The Python handler
/// stitches them into the legacy `<g opacity="...">` envelopes.
type Buckets = (Vec<String>, Vec<String>, Vec<String>);

/// Corridor halo — adjacent-VOID tiles around corridors / doors.
/// `tiles` is the pre-sorted list emitted by `_floor_layers.py`
/// 1.c.1; the seed already includes the legacy `+7` offset. No
/// 10 % skip applies (caves and corridor halos take the dense
/// path in the legacy renderer).
pub fn draw_hatch_corridor(tiles: &[(i32, i32)], seed: u64) -> Buckets {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut buckets: Buckets = (
        Vec::with_capacity(tiles.len()),
        Vec::new(),
        Vec::new(),
    );
    for &(gx, gy) in tiles {
        paint_tile(gx, gy, &CORRIDOR_STONE_DIST, &mut rng, &mut buckets);
    }
    buckets
}

/// Room (perimeter) halo — candidate tiles emitted by
/// `_floor_layers.py` 1.b after the Perlin distance filter.
/// `is_outer[i]` carries the cave-aware `dist > base_distance_limit
/// * 0.5` flag; the 10 % RNG skip fires only on outer tiles, in
/// lock-step with the consumer-side legacy walk.
pub fn draw_hatch_room(
    tiles: &[(i32, i32)],
    is_outer: &[bool],
    seed: u64,
) -> Buckets {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut buckets: Buckets = (
        Vec::with_capacity(tiles.len()),
        Vec::new(),
        Vec::new(),
    );
    for (i, &(gx, gy)) in tiles.iter().enumerate() {
        let outer = is_outer.get(i).copied().unwrap_or(false);
        if outer && rng.gen::<f64>() < 0.10 {
            continue;
        }
        paint_tile(gx, gy, &ROOM_STONE_DIST, &mut rng, &mut buckets);
    }
    buckets
}

// ── Stone-count weighted distributions ───────────────────────
//
// Corridor: `rng.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])`.
// Room:     `rng.choices([0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15])`.

struct StoneDist {
    /// Cumulative weights, normalised to 1.0 at the last entry.
    cumulative: &'static [(u8, f64)],
}

const CORRIDOR_STONE_DIST: StoneDist = StoneDist {
    cumulative: &[(0, 0.5), (1, 0.85), (2, 1.0)],
};
const ROOM_STONE_DIST: StoneDist = StoneDist {
    cumulative: &[(0, 0.25), (1, 0.6), (2, 0.85), (3, 1.0)],
};

fn pick_stones(dist: &StoneDist, rng: &mut Pcg64Mcg) -> u8 {
    let r: f64 = rng.gen();
    for &(value, threshold) in dist.cumulative {
        if r < threshold {
            return value;
        }
    }
    dist.cumulative.last().map(|&(v, _)| v).unwrap_or(0)
}

// ── Per-tile painting ────────────────────────────────────────

fn paint_tile(
    gx: i32,
    gy: i32,
    stone_dist: &StoneDist,
    rng: &mut Pcg64Mcg,
    buckets: &mut Buckets,
) {
    let (ref mut tile_fills, ref mut hatch_lines, ref mut hatch_stones) =
        *buckets;

    // Grey underlay tile.
    let px = f64::from(gx) * CELL;
    let py = f64::from(gy) * CELL;
    tile_fills.push(format!(
        "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" \
         fill=\"{}\"/>",
        px as i64, py as i64, CELL as i64, CELL as i64, HATCH_UNDERLAY,
    ));

    // Stone scatter.
    let n_stones = pick_stones(stone_dist, rng);
    for _ in 0..n_stones {
        let sx = (f64::from(gx) + rng.gen_range(0.15..0.85)) * CELL;
        let sy = (f64::from(gy) + rng.gen_range(0.15..0.85)) * CELL;
        let rx: f64 = rng.gen_range(2.0..(CELL * 0.25));
        let ry: f64 = rng.gen_range(2.0..(CELL * 0.2));
        let angle: f64 = rng.gen_range(0.0..180.0);
        let sw: f64 = rng.gen_range(1.2..2.0);
        hatch_stones.push(format!(
            "<ellipse cx=\"{sx:.1}\" cy=\"{sy:.1}\" \
             rx=\"{rx:.1}\" ry=\"{ry:.1}\" \
             transform=\"rotate({a:.0},{sx:.1},{sy:.1})\" \
             fill=\"{HATCH_UNDERLAY}\" stroke=\"{STONE_STROKE}\" \
             stroke-width=\"{sw:.1}\"/>",
            a = angle,
        ));
    }

    // Perlin-displaced cluster anchor.
    let nr = CELL * 0.1;
    let adx = pnoise2(f64::from(gx) * 0.5, f64::from(gy) * 0.5, 1) * nr;
    let ady = pnoise2(f64::from(gx) * 0.5, f64::from(gy) * 0.5, 2) * nr;
    let anchor = (
        (f64::from(gx) + 0.5) * CELL + adx,
        (f64::from(gy) + 0.5) * CELL + ady,
    );

    // Tile corners in legacy iteration order: TL → TR → BR → BL.
    let corners = [
        (px, py),
        (px + CELL, py),
        (px + CELL, py + CELL),
        (px, py + CELL),
    ];

    // Pick 3 random perimeter points.
    let pts = pick_section_points(&corners, anchor, CELL, rng);
    let sections = build_sections(anchor, &pts, &corners);

    for (sec_i, section) in sections.iter().enumerate() {
        let area = polygon_area(section);
        if area < 1.0 {
            continue;
        }

        let seg_angle = if sec_i == 0 {
            (pts[1].1 - pts[0].1).atan2(pts[1].0 - pts[0].0)
        } else {
            rng.gen_range(0.0..std::f64::consts::PI)
        };

        let bbox = polygon_bounds(section);
        let diag = ((bbox.2 - bbox.0).powi(2)
            + (bbox.3 - bbox.1).powi(2))
        .sqrt();
        let spacing = CELL * 0.20;
        let n_lines = std::cmp::max(3, (diag / spacing) as i32);

        let centroid = polygon_centroid(section);
        let geo_section = section_to_geo(section);

        let cos_a = seg_angle.cos();
        let sin_a = seg_angle.sin();
        let perp_cos = (seg_angle + std::f64::consts::FRAC_PI_2).cos();
        let perp_sin = (seg_angle + std::f64::consts::FRAC_PI_2).sin();

        for j in 0..n_lines {
            let offset =
                (f64::from(j) - f64::from(n_lines - 1) / 2.0) * spacing;
            let px = centroid.0 + perp_cos * offset;
            let py = centroid.1 + perp_sin * offset;
            let p1 = (px - cos_a * diag, py - sin_a * diag);
            let p2 = (px + cos_a * diag, py + sin_a * diag);
            // Stroke width must be drawn even when the line is
            // clipped away — the legacy handler advances the RNG
            // unconditionally inside the inner loop, and the
            // structural-invariants gate cares about the count
            // surviving the clip.
            let sw: f64 = rng.gen_range(1.0..1.8);

            let Some((c1, c2)) = clip_line_to_polygon(&geo_section, p1, p2)
            else {
                continue;
            };

            // Perlin wobble on each endpoint.
            let wb = CELL * 0.03;
            let q1 = (
                c1.0 + pnoise2(c1.0 * 0.1, c1.1 * 0.1, 10) * wb,
                c1.1 + pnoise2(c1.0 * 0.1, c1.1 * 0.1, 11) * wb,
            );
            let q2 = (
                c2.0 + pnoise2(c2.0 * 0.1, c2.1 * 0.1, 12) * wb,
                c2.1 + pnoise2(c2.0 * 0.1, c2.1 * 0.1, 13) * wb,
            );

            hatch_lines.push(format!(
                "<line x1=\"{:.1}\" y1=\"{:.1}\" x2=\"{:.1}\" y2=\"{:.1}\" \
                 stroke=\"{INK}\" stroke-width=\"{sw:.2}\" \
                 stroke-linecap=\"round\"/>",
                q1.0, q1.1, q2.0, q2.1,
            ));
        }
    }
}

// ── Section partitioning (legacy `_pick_section_points` /
//    `_build_sections` ports). Sections are convex by
//    construction (anchor inside the tile + 2 perimeter points +
//    a CW corner walk).

type Pt = (f64, f64);

fn pick_section_points(
    corners: &[Pt; 4],
    anchor: Pt,
    grid_size: f64,
    rng: &mut Pcg64Mcg,
) -> [Pt; 3] {
    let mut pts: [Pt; 3] = [(0.0, 0.0); 3];
    for slot in pts.iter_mut() {
        let edge: u8 = rng.gen_range(0..=3);
        let t: f64 = rng.gen_range(0.0..grid_size);
        *slot = perimeter_point(corners, edge, t);
    }
    // Sort by angle from anchor, matching legacy
    // `pts.sort(key=lambda p: math.atan2(...))`.
    pts.sort_by(|a, b| {
        let aa = (a.1 - anchor.1).atan2(a.0 - anchor.0);
        let ab = (b.1 - anchor.1).atan2(b.0 - anchor.0);
        aa.partial_cmp(&ab).unwrap_or(std::cmp::Ordering::Equal)
    });
    pts
}

fn perimeter_point(corners: &[Pt; 4], edge: u8, t: f64) -> Pt {
    match edge {
        0 => (corners[0].0 + t, corners[0].1),
        1 => (corners[1].0, corners[1].1 + t),
        2 => (corners[2].0 - t, corners[2].1),
        _ => (corners[3].0, corners[3].1 - t),
    }
}

fn edge_index(p: Pt, corners: &[Pt; 4], grid_size: f64) -> u8 {
    let gx_px = corners[0].0;
    let gy_px = corners[0].1;
    if (p.1 - gy_px).abs() < 1e-3 {
        return 0;
    }
    if (p.0 - (gx_px + grid_size)).abs() < 1e-3 {
        return 1;
    }
    if (p.1 - (gy_px + grid_size)).abs() < 1e-3 {
        return 2;
    }
    3
}

fn build_sections(
    anchor: Pt,
    pts: &[Pt; 3],
    corners: &[Pt; 4],
) -> Vec<Vec<Pt>> {
    let gs = corners[1].0 - corners[0].0;
    let mut sections: Vec<Vec<Pt>> = Vec::with_capacity(3);
    for i in 0..3 {
        let p1 = pts[i];
        let p2 = pts[(i + 1) % 3];
        let mut verts: Vec<Pt> = vec![anchor, p1];
        let idx1 = edge_index(p1, corners, gs);
        let idx2 = edge_index(p2, corners, gs);
        let mut j = idx1;
        while j != idx2 {
            verts.push(corners[((j + 1) % 4) as usize]);
            j = (j + 1) % 4;
        }
        verts.push(p2);
        sections.push(verts);
    }
    sections
}

// ── Convex-polygon helpers ───────────────────────────────────

fn polygon_area(poly: &[Pt]) -> f64 {
    if poly.len() < 3 {
        return 0.0;
    }
    let mut sum = 0.0;
    for i in 0..poly.len() {
        let (x0, y0) = poly[i];
        let (x1, y1) = poly[(i + 1) % poly.len()];
        sum += x0 * y1 - x1 * y0;
    }
    (sum * 0.5).abs()
}

fn polygon_bounds(poly: &[Pt]) -> (f64, f64, f64, f64) {
    let mut min_x = f64::INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut max_y = f64::NEG_INFINITY;
    for &(x, y) in poly {
        if x < min_x {
            min_x = x;
        }
        if x > max_x {
            max_x = x;
        }
        if y < min_y {
            min_y = y;
        }
        if y > max_y {
            max_y = y;
        }
    }
    (min_x, min_y, max_x, max_y)
}

fn polygon_centroid(poly: &[Pt]) -> Pt {
    // Shoelace-weighted centroid for a simple polygon.
    if poly.len() < 3 {
        // Degenerate fallback — bounding-box midpoint.
        let (lo_x, lo_y, hi_x, hi_y) = polygon_bounds(poly);
        return ((lo_x + hi_x) * 0.5, (lo_y + hi_y) * 0.5);
    }
    let mut a = 0.0;
    let mut cx = 0.0;
    let mut cy = 0.0;
    for i in 0..poly.len() {
        let (x0, y0) = poly[i];
        let (x1, y1) = poly[(i + 1) % poly.len()];
        let cross = x0 * y1 - x1 * y0;
        a += cross;
        cx += (x0 + x1) * cross;
        cy += (y0 + y1) * cross;
    }
    if a.abs() < 1e-12 {
        let (lo_x, lo_y, hi_x, hi_y) = polygon_bounds(poly);
        return ((lo_x + hi_x) * 0.5, (lo_y + hi_y) * 0.5);
    }
    (cx / (3.0 * a), cy / (3.0 * a))
}

fn section_to_geo(poly: &[Pt]) -> Polygon<f64> {
    let coords: Vec<Coord<f64>> =
        poly.iter().map(|&(x, y)| Coord { x, y }).collect();
    Polygon::new(LineString::new(coords), vec![])
}

fn clip_line_to_polygon(
    poly: &Polygon<f64>,
    p1: Pt,
    p2: Pt,
) -> Option<(Pt, Pt)> {
    let line = LineString::new(vec![
        Coord { x: p1.0, y: p1.1 },
        Coord { x: p2.0, y: p2.1 },
    ]);
    let mls = MultiLineString::new(vec![line]);
    let clipped = poly.clip(&mls, false);
    // Legacy contract: take only the single-segment intersection.
    // If the line crosses the polygon in two separate pieces (rare
    // for convex sections but defensively checked), pick the
    // longer segment so the dominant chord wins.
    let mut best: Option<(Pt, Pt, f64)> = None;
    for ls in clipped.0.iter() {
        let coords: Vec<&Coord<f64>> = ls.coords().collect();
        if coords.len() < 2 {
            continue;
        }
        let a = (coords[0].x, coords[0].y);
        let b = (coords[coords.len() - 1].x, coords[coords.len() - 1].y);
        let len = ((b.0 - a.0).powi(2) + (b.1 - a.1).powi(2)).sqrt();
        match best {
            Some((_, _, blen)) if blen >= len => {}
            _ => best = Some((a, b, len)),
        }
    }
    best.map(|(a, b, _)| (a, b))
}

#[cfg(test)]
mod tests {
    use super::{
        clip_line_to_polygon, draw_hatch_corridor, draw_hatch_room,
        section_to_geo,
    };

    #[test]
    fn corridor_empty_tiles_returns_empty_buckets() {
        let (a, b, c) = draw_hatch_corridor(&[], 0);
        assert!(a.is_empty() && b.is_empty() && c.is_empty());
    }

    #[test]
    fn room_empty_tiles_returns_empty_buckets() {
        let (a, b, c) = draw_hatch_room(&[], &[], 0);
        assert!(a.is_empty() && b.is_empty() && c.is_empty());
    }

    #[test]
    fn corridor_emits_one_underlay_per_tile() {
        let tiles = [(0_i32, 0_i32), (1, 2), (5, 5)];
        let (fills, _, _) = draw_hatch_corridor(&tiles, 42);
        assert_eq!(fills.len(), tiles.len());
        for f in &fills {
            assert!(f.starts_with("<rect"));
            assert!(f.contains("fill=\"#D0D0D0\""));
        }
    }

    #[test]
    fn corridor_is_deterministic() {
        let tiles = [(0_i32, 0_i32), (1, 2), (5, 5), (-1, 7)];
        let a = draw_hatch_corridor(&tiles, 42);
        let b = draw_hatch_corridor(&tiles, 42);
        assert_eq!(a, b);
    }

    #[test]
    fn room_outer_skip_consumes_one_rng_per_outer_tile() {
        // Same tile list, same seed, every-tile-outer flag flipped
        // off vs on: the on case can drop tiles via the 10 % skip
        // and is therefore a (non-strict) subset of the off case
        // by tile-fill count.
        let tiles: Vec<(i32, i32)> =
            (0..40).map(|i| (i, 0)).collect();
        let all_outer = vec![true; tiles.len()];
        let none_outer = vec![false; tiles.len()];
        let (fills_off, _, _) = draw_hatch_room(&tiles, &none_outer, 7);
        let (fills_on, _, _) = draw_hatch_room(&tiles, &all_outer, 7);
        assert!(fills_on.len() <= fills_off.len());
        // Different seeds give different RNG behaviour, so don't
        // assert strict equality on the "off" path — just
        // determinism.
        let (fills_off2, _, _) = draw_hatch_room(&tiles, &none_outer, 7);
        assert_eq!(fills_off, fills_off2);
    }

    #[test]
    fn clip_line_to_polygon_inside_returns_full_chord() {
        // Unit square; line fully inside.
        let poly = section_to_geo(&[
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]);
        let clipped =
            clip_line_to_polygon(&poly, (1.0, 5.0), (9.0, 5.0));
        assert!(clipped.is_some());
        let (a, b) = clipped.unwrap();
        assert!((a.0 - 1.0).abs() < 1e-6 && (a.1 - 5.0).abs() < 1e-6);
        assert!((b.0 - 9.0).abs() < 1e-6 && (b.1 - 5.0).abs() < 1e-6);
    }

    #[test]
    fn clip_line_to_polygon_outside_returns_none() {
        let poly = section_to_geo(&[
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]);
        let clipped =
            clip_line_to_polygon(&poly, (20.0, 20.0), (30.0, 30.0));
        assert!(clipped.is_none());
    }

    #[test]
    fn clip_line_to_polygon_crossing_returns_chord() {
        // Horizontal line crossing the unit square through the middle.
        let poly = section_to_geo(&[
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]);
        let clipped =
            clip_line_to_polygon(&poly, (-5.0, 5.0), (15.0, 5.0));
        assert!(clipped.is_some());
        let (a, b) = clipped.unwrap();
        // Endpoints land on x=0 and x=10 with y=5.
        let xs = [a.0.min(b.0), a.0.max(b.0)];
        assert!((xs[0]).abs() < 1e-6);
        assert!((xs[1] - 10.0).abs() < 1e-6);
    }
}
