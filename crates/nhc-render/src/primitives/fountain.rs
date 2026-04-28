//! Fountain surface-feature primitive — Phase 4 sub-step 14
//! (plan §8 Q4).
//!
//! Reproduces the five fountain variants from
//! ``nhc/rendering/_features_svg.py``:
//!
//! - circle (2x2 footprint, ``_circle_fountain_fragment_for_tile``)
//! - square (2x2 footprint, ``_square_fountain_fragment_for_tile``)
//! - large-circle (3x3 footprint, ``_circle_fountain_3x3_fragment_for_tile``)
//! - large-square (3x3 footprint, ``_square_fountain_3x3_fragment_for_tile``)
//! - cross (3x3 plus-shaped footprint,
//!   ``_cross_fountain_fragment_for_tile``)
//!
//! All variants are RNG-free (variation comes from the
//! ``_hash_norm`` / ``_hash_unit`` deterministic hash on
//! ``(tx, ty)``); the Rust port matches the legacy Python output
//! byte-equal.
//!
//! Shared helpers (``hash_norm``, ``hash_unit``, ``arc_path``,
//! ``keystone_path``, ``water_movement_fragments``,
//! ``square_stones_per_side``, ``keystone_count``) are imported
//! from the well primitive (sub-step 13's home), avoiding
//! duplication. A future pass can lift them into a shared
//! ``feature_helpers`` module when the bush / tree ports land.

use std::f64::consts::PI;

use super::well;

const CELL: f64 = 32.0;
const INK: &str = "#000000";

const STONE_DEPTH_PX: f64 = 9.0;

const FOUNTAIN_OUTER_RADIUS: f64 = 0.92 * CELL;
const FOUNTAIN_INNER_RADIUS: f64 = FOUNTAIN_OUTER_RADIUS - STONE_DEPTH_PX;
const FOUNTAIN_WATER_RADIUS: f64 = FOUNTAIN_INNER_RADIUS - 1.5;
const FOUNTAIN_PEDESTAL_OUTER_RADIUS: f64 = 0.22 * CELL;
const FOUNTAIN_PEDESTAL_INNER_RADIUS: f64 = 0.12 * CELL;

const FOUNTAIN_OUTER_RING_STROKE_WIDTH: f64 = 1.8;
const FOUNTAIN_PEDESTAL_STROKE_WIDTH: f64 = 1.4;
const FOUNTAIN_STONE_STROKE_WIDTH: f64 = 1.4;

const FOUNTAIN_WATER_FILL: &str = "#3F6E9A";
const FOUNTAIN_WATER_STROKE: &str = "#22466B";
const FOUNTAIN_STONE_FILL: &str = "#EFE4D2";
const FOUNTAIN_PEDESTAL_FILL: &str = "#D9C9AE";
const FOUNTAIN_SPOUT_FILL: &str = "#7FB6E0";

const FOUNTAIN_SQUARE_STONE_RADIUS_PX: f64 = 1.4;
const FOUNTAIN_SQUARE_OUTER_RX_PX: f64 = 4.0;
const FOUNTAIN_SQUARE_WATER_RX_PX: f64 = 2.5;
const FOUNTAIN_SQUARE_PEDESTAL_RX_PX: f64 = 2.0;

const FOUNTAIN_3X3_OUTER_RADIUS: f64 = 1.42 * CELL;
const FOUNTAIN_3X3_INNER_RADIUS: f64 =
    FOUNTAIN_3X3_OUTER_RADIUS - STONE_DEPTH_PX;
const FOUNTAIN_3X3_WATER_RADIUS: f64 = FOUNTAIN_3X3_INNER_RADIUS - 1.5;
const FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS: f64 = 0.30 * CELL;
const FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS: f64 = 0.18 * CELL;
const FOUNTAIN_3X3_SQUARE_OUTER_RX_PX: f64 = 5.0;
const FOUNTAIN_3X3_SQUARE_WATER_RX_PX: f64 = 3.0;

const FOUNTAIN_CROSS_INNER_HALF_WIDTH: f64 = 0.5 * CELL;
const FOUNTAIN_CROSS_INNER_HALF_LENGTH: f64 = 1.5 * CELL;
const FOUNTAIN_CROSS_OUTER_HALF_WIDTH: f64 =
    FOUNTAIN_CROSS_INNER_HALF_WIDTH + STONE_DEPTH_PX;
const FOUNTAIN_CROSS_OUTER_HALF_LENGTH: f64 =
    FOUNTAIN_CROSS_INNER_HALF_LENGTH + STONE_DEPTH_PX;
const FOUNTAIN_CROSS_WATER_INSET_PX: f64 = 1.5;
const FOUNTAIN_CROSS_PEDESTAL_OUTER_RADIUS: f64 = 0.26 * CELL;
const FOUNTAIN_CROSS_PEDESTAL_INNER_RADIUS: f64 = 0.14 * CELL;

const WATER_STROKE_WIDTH: f64 = 1.0; // = WELL_WATER_STROKE_WIDTH

fn fountain_stone_rect(x: f64, y: f64, w: f64, h: f64) -> String {
    format!(
        "<rect class=\"fountain-stone\" x=\"{x:.2}\" y=\"{y:.2}\" \
         width=\"{w:.2}\" height=\"{h:.2}\" \
         rx=\"{FOUNTAIN_SQUARE_STONE_RADIUS_PX:.2}\" \
         fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
    )
}

fn fountain_g_open(tx: i32, ty: i32) -> String {
    format!(
        "<g id=\"fountain-{tx}-{ty}\" class=\"fountain-feature\" \
         stroke-linejoin=\"round\">",
    )
}

fn fountain_circle(
    tx: i32, ty: i32, cx: f64, cy: f64,
    outer_r: f64, inner_r: f64, water_r: f64,
    keystone_gap_rad_deg: f64,
    pedestal_outer: f64, pedestal_inner: f64,
) -> String {
    let mut parts = String::new();
    parts.push_str(&fountain_g_open(tx, ty));
    parts.push_str(&format!(
        "<circle cx=\"{cx:.2}\" cy=\"{cy:.2}\" r=\"{outer_r:.2}\" \
         fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2}\"/>",
    ));
    let n = well::keystone_count(outer_r);
    let gap_rad = keystone_gap_rad_deg.to_radians();
    let step = 2.0 * PI / f64::from(n);
    for i in 0..n {
        let a0 = f64::from(i) * step + gap_rad / 2.0;
        let a1 = f64::from(i + 1) * step - gap_rad / 2.0;
        let d = well::keystone_path(cx, cy, inner_r, outer_r, a0, a1);
        parts.push_str(&format!(
            "<path class=\"fountain-keystone\" d=\"{d}\" \
             fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
             stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
        ));
    }
    parts.push_str(&format!(
        "<circle class=\"fountain-water\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{water_r:.2}\" \
         fill=\"{FOUNTAIN_WATER_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
    ));
    for ripple in well::water_movement_fragments(
        cx, cy, water_r, tx, ty, "fountain-water-movement",
    ) {
        parts.push_str(&ripple);
    }
    parts.push_str(&format!(
        "<circle class=\"fountain-pedestal\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{pedestal_outer:.2}\" \
         fill=\"{FOUNTAIN_PEDESTAL_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2}\"/>",
    ));
    parts.push_str(&format!(
        "<circle class=\"fountain-spout\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{pedestal_inner:.2}\" \
         fill=\"{FOUNTAIN_SPOUT_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
    ));
    parts.push_str("</g>");
    parts
}

fn fountain_square_emit(
    tx: i32, ty: i32, cx: f64, cy: f64,
    outer: f64, inner: f64, water: f64,
    pedestal: f64, spout: f64,
    outer_rx: f64, water_rx: f64, pedestal_rx: f64,
) -> String {
    let depth = outer - inner;
    let gap = well::STONE_GAP_PX;
    let mut parts = String::new();
    parts.push_str(&fountain_g_open(tx, ty));
    parts.push_str(&format!(
        "<rect x=\"{:.2}\" y=\"{:.2}\" width=\"{:.2}\" height=\"{:.2}\" \
         rx=\"{outer_rx:.2}\" fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2}\"/>",
        cx - outer, cy - outer, 2.0 * outer, 2.0 * outer,
    ));
    let long_n = well::square_stones_per_side(2.0 * outer);
    let long_span = 2.0 * outer;
    let long_stone =
        (long_span - f64::from(long_n + 1) * gap) / f64::from(long_n);
    for i in 0..long_n {
        let x0 = cx - outer + gap + f64::from(i) * (long_stone + gap);
        parts.push_str(&fountain_stone_rect(
            x0, cy - outer + gap, long_stone, depth - 2.0 * gap,
        ));
        parts.push_str(&fountain_stone_rect(
            x0, cy + inner + gap, long_stone, depth - 2.0 * gap,
        ));
    }
    let short_n =
        well::square_stones_per_side(2.0 * outer - 2.0 * STONE_DEPTH_PX);
    let short_span = 2.0 * inner;
    let short_stone =
        (short_span - f64::from(short_n + 1) * gap) / f64::from(short_n);
    for i in 0..short_n {
        let y0 = cy - inner + gap + f64::from(i) * (short_stone + gap);
        parts.push_str(&fountain_stone_rect(
            cx - outer + gap, y0, depth - 2.0 * gap, short_stone,
        ));
        parts.push_str(&fountain_stone_rect(
            cx + inner + gap, y0, depth - 2.0 * gap, short_stone,
        ));
    }
    parts.push_str(&format!(
        "<rect class=\"fountain-water\" x=\"{:.2}\" y=\"{:.2}\" \
         width=\"{:.2}\" height=\"{:.2}\" rx=\"{water_rx:.2}\" \
         fill=\"{FOUNTAIN_WATER_FILL}\" \
         stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
        cx - water, cy - water, 2.0 * water, 2.0 * water,
    ));
    for ripple in well::water_movement_fragments(
        cx, cy, water, tx, ty, "fountain-water-movement",
    ) {
        parts.push_str(&ripple);
    }
    parts.push_str(&format!(
        "<rect class=\"fountain-pedestal\" x=\"{:.2}\" y=\"{:.2}\" \
         width=\"{:.2}\" height=\"{:.2}\" rx=\"{pedestal_rx:.2}\" \
         fill=\"{FOUNTAIN_PEDESTAL_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2}\"/>",
        cx - pedestal, cy - pedestal, 2.0 * pedestal, 2.0 * pedestal,
    ));
    parts.push_str(&format!(
        "<rect class=\"fountain-spout\" x=\"{:.2}\" y=\"{:.2}\" \
         width=\"{:.2}\" height=\"{:.2}\" rx=\"{pedestal_rx:.2}\" \
         fill=\"{FOUNTAIN_SPOUT_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
        cx - spout, cy - spout, 2.0 * spout, 2.0 * spout,
    ));
    parts.push_str("</g>");
    parts
}

fn fountain_circle_2x2(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.0) * CELL;
    let cy = (f64::from(ty) + 1.0) * CELL;
    fountain_circle(
        tx, ty, cx, cy,
        FOUNTAIN_OUTER_RADIUS, FOUNTAIN_INNER_RADIUS,
        FOUNTAIN_WATER_RADIUS, 1.5,
        FOUNTAIN_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_PEDESTAL_INNER_RADIUS,
    )
}

fn fountain_square_2x2(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.0) * CELL;
    let cy = (f64::from(ty) + 1.0) * CELL;
    fountain_square_emit(
        tx, ty, cx, cy,
        FOUNTAIN_OUTER_RADIUS, FOUNTAIN_INNER_RADIUS,
        FOUNTAIN_WATER_RADIUS,
        FOUNTAIN_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_PEDESTAL_INNER_RADIUS,
        FOUNTAIN_SQUARE_OUTER_RX_PX,
        FOUNTAIN_SQUARE_WATER_RX_PX,
        FOUNTAIN_SQUARE_PEDESTAL_RX_PX,
    )
}

fn fountain_circle_3x3(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    fountain_circle(
        tx, ty, cx, cy,
        FOUNTAIN_3X3_OUTER_RADIUS, FOUNTAIN_3X3_INNER_RADIUS,
        FOUNTAIN_3X3_WATER_RADIUS, 1.0,
        FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS,
    )
}

fn fountain_square_3x3(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    fountain_square_emit(
        tx, ty, cx, cy,
        FOUNTAIN_3X3_OUTER_RADIUS, FOUNTAIN_3X3_INNER_RADIUS,
        FOUNTAIN_3X3_WATER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS,
        FOUNTAIN_3X3_SQUARE_OUTER_RX_PX,
        FOUNTAIN_3X3_SQUARE_WATER_RX_PX,
        FOUNTAIN_SQUARE_PEDESTAL_RX_PX,
    )
}

fn cross_fountain_polygon_pts(
    cx: f64, cy: f64, half_w: f64, half_l: f64,
) -> [(f64, f64); 12] {
    [
        (cx - half_w, cy - half_l),
        (cx + half_w, cy - half_l),
        (cx + half_w, cy - half_w),
        (cx + half_l, cy - half_w),
        (cx + half_l, cy + half_w),
        (cx + half_w, cy + half_w),
        (cx + half_w, cy + half_l),
        (cx - half_w, cy + half_l),
        (cx - half_w, cy + half_w),
        (cx - half_l, cy + half_w),
        (cx - half_l, cy - half_w),
        (cx - half_w, cy - half_w),
    ]
}

fn polygon_outline_d(pts: &[(f64, f64)]) -> String {
    let mut s = format!("M{:.2},{:.2}", pts[0].0, pts[0].1);
    for &(x, y) in &pts[1..] {
        s.push_str(&format!(" L{x:.2},{y:.2}"));
    }
    s.push_str(" Z");
    s
}

#[allow(clippy::too_many_arguments)]
fn stones_along_segment(
    x0: f64, y0: f64, x1: f64, y1: f64,
    depth: f64, gap_px: f64,
    stone_class: &str,
) -> Vec<String> {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let length = (dx * dx + dy * dy).sqrt();
    if length <= 0.0 {
        return Vec::new();
    }
    let n = ((length / well::STONE_SIDE_PX).round() as i32).max(1);
    let ux = dx / length;
    let uy = dy / length;
    let nx = -uy;
    let ny = ux;
    let mut stone_len = (length - f64::from(n + 1) * gap_px) / f64::from(n);
    let mut gap = gap_px;
    if stone_len <= 0.0 {
        stone_len = length / f64::from(n);
        gap = 0.0;
    }
    let mut out: Vec<String> = Vec::with_capacity(n as usize);
    for i in 0..n {
        let s = gap + f64::from(i) * (stone_len + gap);
        let e = s + stone_len;
        let ax = x0 + s * ux;
        let ay = y0 + s * uy;
        let bx = x0 + e * ux;
        let by = y0 + e * uy;
        let inset = (depth - gap).max(0.0);
        let cxx = bx + inset * nx;
        let cyy = by + inset * ny;
        let dxx = ax + inset * nx;
        let dyy = ay + inset * ny;
        let d = format!(
            "M{ax:.2},{ay:.2} L{bx:.2},{by:.2} L{cxx:.2},{cyy:.2} \
             L{dxx:.2},{dyy:.2} Z",
        );
        out.push(format!(
            "<path class=\"{stone_class}\" d=\"{d}\" \
             fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
             stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
        ));
    }
    out
}

fn fountain_cross(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    let inner_half_w = FOUNTAIN_CROSS_INNER_HALF_WIDTH;
    let inner_half_l = FOUNTAIN_CROSS_INNER_HALF_LENGTH;
    let outer_half_w = FOUNTAIN_CROSS_OUTER_HALF_WIDTH;
    let outer_half_l = FOUNTAIN_CROSS_OUTER_HALF_LENGTH;

    let mut parts = String::new();
    parts.push_str(&fountain_g_open(tx, ty));
    let outer_pts = cross_fountain_polygon_pts(
        cx, cy, outer_half_w, outer_half_l,
    );
    parts.push_str(&format!(
        "<path d=\"{}\" fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2}\"/>",
        polygon_outline_d(&outer_pts),
    ));

    let depth = STONE_DEPTH_PX;
    let n = outer_pts.len();
    for i in 0..n {
        let (x0, y0) = outer_pts[i];
        let (x1, y1) = outer_pts[(i + 1) % n];
        for stone in stones_along_segment(
            x0, y0, x1, y1,
            depth, well::STONE_GAP_PX, "fountain-keystone",
        ) {
            parts.push_str(&stone);
        }
    }

    // Concave-corner stones at vertices 2, 5, 8, 11.
    let corner_g = well::STONE_GAP_PX;
    let concave: [(usize, i8, i8); 4] = [
        (2, -1, 1),
        (5, -1, -1),
        (8, 1, -1),
        (11, 1, 1),
    ];
    for &(vidx, sx, sy) in &concave {
        let (ox, oy) = outer_pts[vidx];
        let (x_min, x_max) = if sx > 0 {
            (ox, ox + depth - corner_g)
        } else {
            (ox - depth + corner_g, ox)
        };
        let (y_min, y_max) = if sy > 0 {
            (oy, oy + depth - corner_g)
        } else {
            (oy - depth + corner_g, oy)
        };
        let d = format!(
            "M{x_min:.2},{y_min:.2} L{x_max:.2},{y_min:.2} \
             L{x_max:.2},{y_max:.2} L{x_min:.2},{y_max:.2} Z",
        );
        parts.push_str(&format!(
            "<path class=\"fountain-keystone\" d=\"{d}\" \
             fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
             stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
        ));
    }

    let inset = FOUNTAIN_CROSS_WATER_INSET_PX;
    let water_half_w = inner_half_w - inset;
    let water_half_l = inner_half_l - inset;
    let water_pts = cross_fountain_polygon_pts(
        cx, cy, water_half_w, water_half_l,
    );
    parts.push_str(&format!(
        "<path class=\"fountain-water\" d=\"{}\" \
         fill=\"{FOUNTAIN_WATER_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
        polygon_outline_d(&water_pts),
    ));

    let movement_radius = water_half_w.min(water_half_l);
    for ripple in well::water_movement_fragments(
        cx, cy, movement_radius, tx, ty, "fountain-water-movement",
    ) {
        parts.push_str(&ripple);
    }

    parts.push_str(&format!(
        "<circle class=\"fountain-pedestal\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{FOUNTAIN_CROSS_PEDESTAL_OUTER_RADIUS:.2}\" \
         fill=\"{FOUNTAIN_PEDESTAL_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2}\"/>",
    ));
    parts.push_str(&format!(
        "<circle class=\"fountain-spout\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{FOUNTAIN_CROSS_PEDESTAL_INNER_RADIUS:.2}\" \
         fill=\"{FOUNTAIN_SPOUT_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
    ));

    parts.push_str("</g>");
    parts
}

/// Fountain primitive entry point. `shape` matches the FB
/// FountainShape enum: 0 Round, 1 Square, 2 LargeRound,
/// 3 LargeSquare, 4 Cross.
pub fn draw_fountain(
    tiles: &[(i32, i32)], shape: u8,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    tiles
        .iter()
        .map(|&(tx, ty)| match shape {
            0 => fountain_circle_2x2(tx, ty),
            1 => fountain_square_2x2(tx, ty),
            2 => fountain_circle_3x3(tx, ty),
            3 => fountain_square_3x3(tx, ty),
            4 => fountain_cross(tx, ty),
            _ => fountain_circle_2x2(tx, ty),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_returns_empty() {
        assert!(draw_fountain(&[], 0).is_empty());
    }

    #[test]
    fn each_shape_produces_envelope() {
        for shape in 0..=4 {
            let out = draw_fountain(&[(2, 2)], shape);
            assert_eq!(out.len(), 1);
            assert!(out[0].contains("class=\"fountain-feature\""));
            assert!(out[0].ends_with("</g>"));
        }
    }

    #[test]
    fn circle_emits_keystones() {
        let out = draw_fountain(&[(0, 0)], 0);
        assert!(out[0].contains("class=\"fountain-keystone\""));
        assert!(out[0].contains("class=\"fountain-water\""));
        assert!(out[0].contains("class=\"fountain-pedestal\""));
        assert!(out[0].contains("class=\"fountain-spout\""));
    }

    #[test]
    fn square_uses_rect_rim() {
        let out = draw_fountain(&[(0, 0)], 1);
        assert!(out[0].contains("class=\"fountain-stone\""));
        // Square variant has no <circle> for rim/water.
    }

    #[test]
    fn deterministic() {
        for shape in 0..=4 {
            assert_eq!(
                draw_fountain(&[(3, 5)], shape),
                draw_fountain(&[(3, 5)], shape),
            );
        }
    }
}
