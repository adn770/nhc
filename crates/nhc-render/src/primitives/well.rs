//! Well surface-feature primitive — Phase 4 sub-step 13 (plan §8 Q4).
//!
//! Reproduces ``_well_fragment_for_tile`` (circular keystone ring +
//! water disc + ripples) and ``_square_well_fragment_for_tile``
//! (square masonry rim + square pool + ripples) from
//! ``nhc/rendering/_features_svg.py``. Both painters are
//! deterministic and use ``_hash_norm`` / ``_hash_unit`` for
//! per-tile variation; no ``random.Random`` is involved.
//!
//! **Parity contract:** because the painters are RNG-free
//! (deterministic ``Knuth-style multiply-and-xor`` hash on
//! ``(tx, ty, salt)``), the Rust port can match the legacy Python
//! output byte-equal — and does. Snapshot-locked via
//! ``tests/unit/test_emit_well_invariants.py``.

use std::f64::consts::PI;

const CELL: f64 = 32.0;
const INK: &str = "#000000";

const STONE_DEPTH_PX: f64 = 9.0;
const STONE_GAP_PX: f64 = 0.4;
const STONE_SIDE_PX: f64 = 11.0;

const WELL_OUTER_RADIUS: f64 = 0.85 * CELL;
const WELL_INNER_RADIUS: f64 = WELL_OUTER_RADIUS - STONE_DEPTH_PX;
const WELL_WATER_RADIUS: f64 = WELL_INNER_RADIUS - 1.5;

const WELL_STONE_FILL: &str = "#EFE4D2";
const WELL_STONE_STROKE_WIDTH: f64 = 1.4;
const WELL_OUTER_RING_STROKE_WIDTH: f64 = 1.8;

const WELL_WATER_FILL: &str = "#3F6E9A";
const WELL_WATER_STROKE: &str = "#22466B";
const WELL_WATER_STROKE_WIDTH: f64 = 1.0;

const WELL_SQUARE_STONE_RADIUS_PX: f64 = 1.4;
const WELL_SQUARE_OUTER_RX_PX: f64 = 3.0;
const WELL_SQUARE_WATER_RX_PX: f64 = 2.0;

const WATER_MOVEMENT_STROKE: &str = "#FFFFFF";
const WATER_MOVEMENT_STROKE_WIDTH: f64 = 0.9;
const WATER_MOVEMENT_STROKE_ALPHA: f64 = 0.65;
const WATER_MOVEMENT_DASH: &str = "2 2";
const WATER_MOVEMENT_MARK_COUNT: i32 = 4;
const WATER_MOVEMENT_AREA_FACTOR: f64 = 0.55;
const WATER_MOVEMENT_RADIUS_MIN_FACTOR: f64 = 0.18;
const WATER_MOVEMENT_RADIUS_MAX_FACTOR: f64 = 0.34;
const WATER_MOVEMENT_SWEEP_MIN: f64 = 0.5;
const WATER_MOVEMENT_SWEEP_MAX: f64 = 1.4;
const WATER_MOVEMENT_SALT: i32 = 22013;

/// 2D hash → ``[-1, 1]``. Mirrors ``_hash_norm`` exactly: same
/// Knuth multiply-and-xor + 32-bit mask on the wrapping integer
/// product. Python's int is arbitrary-precision but the operands
/// stay well within i64 for the (tx, ty) ranges used here.
fn hash_norm(tx: i32, ty: i32, salt: i32) -> f64 {
    let a = (tx as i64).wrapping_mul(73856093);
    let b = (ty as i64).wrapping_mul(19349663);
    let c = (salt as i64).wrapping_mul(83492791);
    let h = (a ^ b ^ c) as u64;
    let h = (h ^ (h >> 13)) & 0xFFFF_FFFF;
    (h as f64 / 0xFFFF_FFFF_u32 as f64) * 2.0 - 1.0
}

/// 2D hash → ``[0, 1]``. Mirrors ``_hash_unit``.
fn hash_unit(tx: i32, ty: i32, salt: i32) -> f64 {
    let a = (tx as i64).wrapping_mul(73856093);
    let b = (ty as i64).wrapping_mul(19349663);
    let c = (salt as i64).wrapping_mul(83492791);
    let h = (a ^ b ^ c) as u64;
    let h = (h ^ (h >> 13)) & 0xFFFF_FFFF;
    let h = (h.wrapping_mul(2654435761) ^ (h >> 16)) & 0xFFFF_FFFF;
    h as f64 / 0xFFFF_FFFF_u32 as f64
}

fn keystone_count(outer_radius: f64) -> i32 {
    let circumference = 2.0 * PI * outer_radius;
    let n = (circumference / STONE_SIDE_PX).round() as i32;
    n.max(8)
}

fn square_stones_per_side(side_len: f64) -> i32 {
    let n = (side_len / STONE_SIDE_PX).round() as i32;
    n.max(2)
}

/// Open arc segment from ``a0`` → ``a1`` (radians). Mirrors
/// ``_arc_path``.
fn arc_path(cx: f64, cy: f64, r: f64, a0: f64, a1: f64) -> String {
    let sx = cx + a0.cos() * r;
    let sy = cy + a0.sin() * r;
    let ex = cx + a1.cos() * r;
    let ey = cy + a1.sin() * r;
    let sweep_len = a1 - a0;
    let large_arc = if sweep_len.abs() > PI { 1 } else { 0 };
    let sweep_dir = if sweep_len >= 0.0 { 1 } else { 0 };
    format!(
        "M{sx:.1},{sy:.1} A{r:.1},{r:.1} 0 {large_arc} {sweep_dir} \
         {ex:.1},{ey:.1}",
    )
}

/// Keystone wedge between two angles on inner / outer radii.
/// Mirrors ``_keystone_path``.
fn keystone_path(
    cx: f64, cy: f64, inner_r: f64, outer_r: f64, a0: f64, a1: f64,
) -> String {
    let ox0 = cx + a0.cos() * outer_r;
    let oy0 = cy + a0.sin() * outer_r;
    let ox1 = cx + a1.cos() * outer_r;
    let oy1 = cy + a1.sin() * outer_r;
    let ix1 = cx + a1.cos() * inner_r;
    let iy1 = cy + a1.sin() * inner_r;
    let ix0 = cx + a0.cos() * inner_r;
    let iy0 = cy + a0.sin() * inner_r;
    format!(
        "M{ox0:.2},{oy0:.2} A{outer_r:.2},{outer_r:.2} 0 0 1 \
         {ox1:.2},{oy1:.2} L{ix1:.2},{iy1:.2} \
         A{inner_r:.2},{inner_r:.2} 0 0 0 {ix0:.2},{iy0:.2} Z",
    )
}

/// Scatter ``n_marks`` short irregular arcs inside a circle.
/// Mirrors ``_scatter_volume_marks``.
#[allow(clippy::too_many_arguments)]
fn scatter_volume_marks(
    cx: f64, cy: f64,
    tx: i32, ty: i32, salt: i32,
    n_marks: i32,
    area_radius: f64,
    mark_radius_min: f64,
    mark_radius_max: f64,
    sweep_min: f64,
    sweep_max: f64,
) -> Vec<String> {
    let mut out = Vec::with_capacity(n_marks as usize);
    for i in 0..n_marks {
        let u = hash_unit(tx, ty, salt + i * 17 + 3);
        let ang = hash_norm(tx, ty, salt + i * 19 + 5) * PI;
        let r_pos = area_radius * u.sqrt();
        let mx = cx + ang.cos() * r_pos;
        let my = cy + ang.sin() * r_pos;
        let u_r = hash_unit(tx, ty, salt + i * 23 + 7);
        let mr = mark_radius_min + (mark_radius_max - mark_radius_min) * u_r;
        let sweep_start = hash_norm(tx, ty, salt + i * 29 + 11) * PI;
        let u_sw = hash_unit(tx, ty, salt + i * 31 + 13);
        let sweep_len = sweep_min + (sweep_max - sweep_min) * u_sw;
        out.push(arc_path(mx, my, mr, sweep_start, sweep_start + sweep_len));
    }
    out
}

fn water_movement_fragments(
    cx: f64, cy: f64, water_radius: f64, tx: i32, ty: i32, cls: &str,
) -> Vec<String> {
    let paths = scatter_volume_marks(
        cx, cy,
        tx, ty, WATER_MOVEMENT_SALT,
        WATER_MOVEMENT_MARK_COUNT,
        water_radius * WATER_MOVEMENT_AREA_FACTOR,
        water_radius * WATER_MOVEMENT_RADIUS_MIN_FACTOR,
        water_radius * WATER_MOVEMENT_RADIUS_MAX_FACTOR,
        WATER_MOVEMENT_SWEEP_MIN,
        WATER_MOVEMENT_SWEEP_MAX,
    );
    paths
        .into_iter()
        .map(|d| {
            format!(
                "<path class=\"{cls}\" d=\"{d}\" \
                 fill=\"none\" stroke=\"{WATER_MOVEMENT_STROKE}\" \
                 stroke-width=\"{WATER_MOVEMENT_STROKE_WIDTH:.2}\" \
                 stroke-opacity=\"{WATER_MOVEMENT_STROKE_ALPHA:.2}\" \
                 stroke-dasharray=\"{WATER_MOVEMENT_DASH}\" \
                 stroke-linecap=\"round\"/>",
            )
        })
        .collect()
}

fn well_circle_fragment(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 0.5) * CELL;
    let cy = (f64::from(ty) + 0.5) * CELL;
    let mut parts = String::new();
    parts.push_str(&format!(
        "<g id=\"well-{tx}-{ty}\" class=\"well-feature\" \
         stroke-linejoin=\"round\">",
    ));
    parts.push_str(&format!(
        "<circle cx=\"{cx:.2}\" cy=\"{cy:.2}\" r=\"{WELL_OUTER_RADIUS:.2}\" \
         fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{WELL_OUTER_RING_STROKE_WIDTH:.2}\"/>",
    ));
    let n = keystone_count(WELL_OUTER_RADIUS);
    let gap_rad: f64 = 1.5_f64.to_radians();
    let step = 2.0 * PI / f64::from(n);
    for i in 0..n {
        let a0 = f64::from(i) * step + gap_rad / 2.0;
        let a1 = f64::from(i + 1) * step - gap_rad / 2.0;
        let d = keystone_path(cx, cy, WELL_INNER_RADIUS, WELL_OUTER_RADIUS, a0, a1);
        parts.push_str(&format!(
            "<path class=\"well-keystone\" d=\"{d}\" \
             fill=\"{WELL_STONE_FILL}\" stroke=\"{INK}\" \
             stroke-width=\"{WELL_STONE_STROKE_WIDTH:.2}\"/>",
        ));
    }
    parts.push_str(&format!(
        "<circle class=\"well-water\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{WELL_WATER_RADIUS:.2}\" \
         fill=\"{WELL_WATER_FILL}\" stroke=\"{WELL_WATER_STROKE}\" \
         stroke-width=\"{WELL_WATER_STROKE_WIDTH:.2}\"/>",
    ));
    for ripple in water_movement_fragments(
        cx, cy, WELL_WATER_RADIUS, tx, ty, "well-water-movement",
    ) {
        parts.push_str(&ripple);
    }
    parts.push_str("</g>");
    parts
}

fn square_stone_rect(x: f64, y: f64, w: f64, h: f64) -> String {
    format!(
        "<rect class=\"well-stone\" x=\"{x:.2}\" y=\"{y:.2}\" \
         width=\"{w:.2}\" height=\"{h:.2}\" \
         rx=\"{WELL_SQUARE_STONE_RADIUS_PX:.2}\" \
         fill=\"{WELL_STONE_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{WELL_STONE_STROKE_WIDTH:.2}\"/>",
    )
}

fn well_square_fragment(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 0.5) * CELL;
    let cy = (f64::from(ty) + 0.5) * CELL;
    let outer = WELL_OUTER_RADIUS;
    let inner = WELL_INNER_RADIUS;
    let depth = outer - inner;
    let gap = STONE_GAP_PX;

    let mut parts = String::new();
    parts.push_str(&format!(
        "<g id=\"well-{tx}-{ty}\" class=\"well-feature\" \
         stroke-linejoin=\"round\">",
    ));
    parts.push_str(&format!(
        "<rect x=\"{:.2}\" y=\"{:.2}\" width=\"{:.2}\" height=\"{:.2}\" \
         rx=\"{WELL_SQUARE_OUTER_RX_PX:.2}\" fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{WELL_OUTER_RING_STROKE_WIDTH:.2}\"/>",
        cx - outer,
        cy - outer,
        2.0 * outer,
        2.0 * outer,
    ));

    let long_n = square_stones_per_side(2.0 * outer);
    let long_span = 2.0 * outer;
    let long_stone =
        (long_span - f64::from(long_n + 1) * gap) / f64::from(long_n);
    for i in 0..long_n {
        let x0 = cx - outer + gap + f64::from(i) * (long_stone + gap);
        parts.push_str(&square_stone_rect(
            x0, cy - outer + gap, long_stone, depth - 2.0 * gap,
        ));
        parts.push_str(&square_stone_rect(
            x0, cy + inner + gap, long_stone, depth - 2.0 * gap,
        ));
    }

    let short_n = square_stones_per_side(2.0 * outer - 2.0 * STONE_DEPTH_PX);
    let short_span = 2.0 * inner;
    let short_stone =
        (short_span - f64::from(short_n + 1) * gap) / f64::from(short_n);
    for i in 0..short_n {
        let y0 = cy - inner + gap + f64::from(i) * (short_stone + gap);
        parts.push_str(&square_stone_rect(
            cx - outer + gap, y0, depth - 2.0 * gap, short_stone,
        ));
        parts.push_str(&square_stone_rect(
            cx + inner + gap, y0, depth - 2.0 * gap, short_stone,
        ));
    }

    let water = WELL_WATER_RADIUS;
    parts.push_str(&format!(
        "<rect class=\"well-water\" x=\"{:.2}\" y=\"{:.2}\" \
         width=\"{:.2}\" height=\"{:.2}\" \
         rx=\"{WELL_SQUARE_WATER_RX_PX:.2}\" fill=\"{WELL_WATER_FILL}\" \
         stroke=\"{WELL_WATER_STROKE}\" \
         stroke-width=\"{WELL_WATER_STROKE_WIDTH:.2}\"/>",
        cx - water,
        cy - water,
        2.0 * water,
        2.0 * water,
    ));
    for ripple in water_movement_fragments(
        cx, cy, water, tx, ty, "well-water-movement",
    ) {
        parts.push_str(&ripple);
    }
    parts.push_str("</g>");
    parts
}

/// Well-feature primitive entry point. `tiles` is the well-tile
/// list; `shape` selects the visual variant (0=Round, 1=Square,
/// matching the FB ``WellShape`` enum). Returns one ``<g>``
/// fragment per tile.
pub fn draw_well(tiles: &[(i32, i32)], shape: u8) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    tiles
        .iter()
        .map(|&(tx, ty)| match shape {
            1 => well_square_fragment(tx, ty),
            _ => well_circle_fragment(tx, ty),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tiles_returns_empty() {
        assert!(draw_well(&[], 0).is_empty());
    }

    #[test]
    fn round_well_emits_g_envelope() {
        let out = draw_well(&[(2, 3)], 0);
        assert_eq!(out.len(), 1);
        assert!(out[0].starts_with("<g id=\"well-2-3\""));
        assert!(out[0].ends_with("</g>"));
        assert!(out[0].contains("class=\"well-feature\""));
        assert!(out[0].contains("class=\"well-keystone\""));
        assert!(out[0].contains("class=\"well-water\""));
    }

    #[test]
    fn square_well_emits_rect_rim() {
        let out = draw_well(&[(0, 0)], 1);
        assert!(out[0].contains("class=\"well-feature\""));
        // Square variant uses <rect> for the rim, not <circle>.
        assert!(!out[0].contains("<circle"));
        assert!(out[0].contains("class=\"well-stone\""));
    }

    #[test]
    fn deterministic() {
        assert_eq!(draw_well(&[(5, 7)], 0), draw_well(&[(5, 7)], 0));
        assert_eq!(draw_well(&[(5, 7)], 1), draw_well(&[(5, 7)], 1));
    }

    #[test]
    fn hash_norm_in_range() {
        for tx in 0..10 {
            for ty in 0..10 {
                let h = hash_norm(tx, ty, 42);
                assert!((-1.0..=1.0).contains(&h));
            }
        }
    }

    #[test]
    fn hash_unit_in_range() {
        for tx in 0..10 {
            for ty in 0..10 {
                let h = hash_unit(tx, ty, 42);
                assert!((0.0..=1.0).contains(&h));
            }
        }
    }
}
