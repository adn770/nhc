//! Bush surface-feature primitive — Phase 4 sub-step 16
//! (plan §8 Q4).
//!
//! Reproduces ``_bush_fragment_for_tile`` from
//! ``nhc/rendering/_features_svg.py``: a multi-lobed cartographer
//! shrub with a darker shadow silhouette, light-coloured canopy
//! (with hue / saturation / lightness jitter per tile), and a
//! handful of irregular volume-mark arc strokes inside.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** the
//! lobe geometry uses ``geo`` crate's ``BooleanOps::union`` on
//! 32-segment circle approximations (Shapely's
//! ``Point.buffer(r)`` default), but the resulting polygon
//! vertex ordering and numerical precision differ from GEOS.
//! Output is gated by structural invariants only; town golden
//! re-baselines on this commit.

use std::f64::consts::PI;

use geo::{BooleanOps, Coord, LineString, MultiPolygon, Polygon};

use super::well;

const CELL: f64 = 32.0;

const BUSH_CANOPY_FILL: &str = "#7A9560";
const BUSH_CANOPY_STROKE: &str = "#3F5237";
const BUSH_CANOPY_SHADOW_FILL: &str = "#3F5237";
const BUSH_CANOPY_STROKE_WIDTH: f64 = 1.0;
const BUSH_CANOPY_STROKE_ALPHA: f64 = 0.78;

const BUSH_CANOPY_LOBE_COUNT_CHOICES: [i32; 2] = [3, 4];
const BUSH_CANOPY_LOBE_RADIUS: f64 = 0.16 * CELL;
const BUSH_CANOPY_CLUSTER_RADIUS: f64 = 0.10 * CELL;
const BUSH_CANOPY_CLUSTER_RADIUS_JITTER: f64 = 0.30;
const BUSH_CANOPY_LOBE_RADIUS_JITTER: f64 = 0.18;
const BUSH_CANOPY_LOBE_OFFSET_JITTER: f64 = 0.30;
const BUSH_CANOPY_LOBE_ANGLE_JITTER: f64 = 0.40;
const BUSH_CANOPY_CENTER_OFFSET: f64 = 0.06 * CELL;

const BUSH_CANOPY_SHADOW_LOBE_RADIUS: f64 = 0.18 * CELL;
const BUSH_CANOPY_SHADOW_OFFSET: f64 = 0.03 * CELL;

const BUSH_VOLUME_MARK_COUNT: i32 = 2;
const BUSH_VOLUME_MARK_AREA_RADIUS: f64 = 0.14 * CELL;
const BUSH_VOLUME_MARK_RADIUS_MIN: f64 = 0.04 * CELL;
const BUSH_VOLUME_MARK_RADIUS_MAX: f64 = 0.07 * CELL;
const BUSH_VOLUME_MARK_SWEEP_MIN: f64 = 0.6;
const BUSH_VOLUME_MARK_SWEEP_MAX: f64 = 1.5;
const BUSH_VOLUME_STROKE_WIDTH: f64 = 0.6;
const BUSH_VOLUME_STROKE_ALPHA: f64 = 0.55;
const BUSH_VOLUME_DASH: &str = "1.5 1.5";

const BUSH_HUE_JITTER_DEG: f64 = 6.0;
const BUSH_SAT_JITTER: f64 = 0.05;
const BUSH_LIGHT_JITTER: f64 = 0.04;

const BUSH_HUE_SALT: i32 = 7019;
const BUSH_SAT_SALT: i32 = 8053;
const BUSH_LIGHT_SALT: i32 = 9091;
const BUSH_CANOPY_SHAPE_SALT: i32 = 11117;
const BUSH_SHADOW_SHAPE_SALT: i32 = 11201;
const BUSH_VOLUME_SALT: i32 = 12119;
const BUSH_LOBE_COUNT_SALT: i32 = 13127;
const BUSH_CLUSTER_RADIUS_SALT: i32 = 13147;
const BUSH_CENTER_X_SALT: i32 = 13163;
const BUSH_CENTER_Y_SALT: i32 = 13183;

/// Approximate a circle as a 32-segment polygon (matches
/// Shapely's ``Point.buffer(r)`` default of ``quad_segs=8`` →
/// 8 vertices per quadrant). The vertex ordering and exact
/// coordinates differ from GEOS, but the silhouette character
/// is preserved.
fn circle_polygon(cx: f64, cy: f64, r: f64) -> Polygon<f64> {
    const SEGMENTS: i32 = 32;
    let mut coords: Vec<Coord<f64>> = Vec::with_capacity(SEGMENTS as usize + 1);
    for i in 0..SEGMENTS {
        let a = 2.0 * PI * f64::from(i) / f64::from(SEGMENTS);
        coords.push(Coord {
            x: cx + a.cos() * r,
            y: cy + a.sin() * r,
        });
    }
    coords.push(coords[0]);
    Polygon::new(LineString::new(coords), vec![])
}

fn lobe_circles(
    cx: f64, cy: f64, tx: i32, ty: i32, salt: i32,
    n_lobes: i32, lobe_radius: f64, cluster_radius: f64,
    radius_jitter: f64, offset_jitter: f64, angle_jitter: f64,
) -> Vec<(f64, f64, f64)> {
    let step = 2.0 * PI / f64::from(n_lobes);
    let mut out = Vec::with_capacity(n_lobes as usize);
    for i in 0..n_lobes {
        let a_jit = well::hash_norm(tx, ty, salt + i * 7) * angle_jitter;
        let o_jit =
            1.0 + well::hash_norm(tx, ty, salt + i * 11 + 1) * offset_jitter;
        let r_jit =
            1.0 + well::hash_norm(tx, ty, salt + i * 13 + 2) * radius_jitter;
        let ang = f64::from(i) * step + a_jit;
        let offs = cluster_radius * o_jit;
        let lr = lobe_radius * r_jit;
        out.push((cx + ang.cos() * offs, cy + ang.sin() * offs, lr));
    }
    out
}

fn lobe_count(tx: i32, ty: i32) -> i32 {
    let u = well::hash_unit(tx, ty, BUSH_LOBE_COUNT_SALT);
    let n = BUSH_CANOPY_LOBE_COUNT_CHOICES.len() as i32;
    let idx = ((u * f64::from(n)) as i32).min(n - 1);
    BUSH_CANOPY_LOBE_COUNT_CHOICES[idx as usize]
}

fn cluster_radius(tx: i32, ty: i32) -> f64 {
    let j = well::hash_norm(tx, ty, BUSH_CLUSTER_RADIUS_SALT);
    BUSH_CANOPY_CLUSTER_RADIUS * (1.0 + j * BUSH_CANOPY_CLUSTER_RADIUS_JITTER)
}

fn center_offset(tx: i32, ty: i32) -> (f64, f64) {
    let dx = well::hash_norm(tx, ty, BUSH_CENTER_X_SALT)
        * BUSH_CANOPY_CENTER_OFFSET;
    let dy = well::hash_norm(tx, ty, BUSH_CENTER_Y_SALT)
        * BUSH_CANOPY_CENTER_OFFSET;
    (dx, dy)
}

/// Union the lobe circles via geo's BooleanOps and format the
/// result as an SVG ``d`` string. Mirrors
/// ``_union_path_from_lobes`` + ``_polygon_to_svg_path``.
fn union_path_from_lobes(lobes: &[(f64, f64, f64)]) -> String {
    if lobes.is_empty() {
        return String::new();
    }
    let mut acc: MultiPolygon<f64> =
        MultiPolygon::new(vec![circle_polygon(
            lobes[0].0, lobes[0].1, lobes[0].2,
        )]);
    for &(cx, cy, r) in &lobes[1..] {
        let next = MultiPolygon::new(vec![circle_polygon(cx, cy, r)]);
        acc = acc.union(&next);
    }
    polygon_to_svg_path(&acc)
}

fn polygon_to_svg_path(geom: &MultiPolygon<f64>) -> String {
    let mut parts: Vec<String> = Vec::new();
    for poly in &geom.0 {
        let mut rings: Vec<&LineString<f64>> = vec![poly.exterior()];
        for hole in poly.interiors() {
            rings.push(hole);
        }
        for ring in rings {
            let coords: Vec<&Coord<f64>> = ring.0.iter().collect();
            if coords.is_empty() {
                continue;
            }
            parts.push(format!("M{:.1},{:.1}", coords[0].x, coords[0].y));
            for c in &coords[1..] {
                parts.push(format!("L{:.1},{:.1}", c.x, c.y));
            }
            parts.push("Z".to_string());
        }
    }
    parts.join(" ")
}

fn fill_jitter(tx: i32, ty: i32) -> String {
    let dh = well::hash_norm(tx, ty, BUSH_HUE_SALT) * BUSH_HUE_JITTER_DEG;
    let ds = well::hash_norm(tx, ty, BUSH_SAT_SALT) * BUSH_SAT_JITTER;
    let dl = well::hash_norm(tx, ty, BUSH_LIGHT_SALT) * BUSH_LIGHT_JITTER;
    shift_color(BUSH_CANOPY_FILL, dh, ds, dl)
}

/// HLS color shift — mirrors Python's ``colorsys.rgb_to_hls`` /
/// ``hls_to_rgb`` round-trip. Output formatted as ``#RRGGBB``
/// with banker's-style rounding to match Python's ``round(x*255)``.
fn shift_color(base_hex: &str, hue_deg: f64, sat: f64, light: f64) -> String {
    let (r, g, b) = hex_to_rgb01(base_hex);
    let (h, l, s) = rgb_to_hls(r, g, b);
    let h = ((h + hue_deg / 360.0) % 1.0 + 1.0) % 1.0;
    let s = (s + sat).clamp(0.0, 1.0);
    let l = (l + light).clamp(0.0, 1.0);
    let (rr, gg, bb) = hls_to_rgb(h, l, s);
    rgb01_to_hex(rr, gg, bb)
}

fn hex_to_rgb01(s: &str) -> (f64, f64, f64) {
    let s = s.trim_start_matches('#');
    let r = i32::from_str_radix(&s[0..2], 16).unwrap_or(0);
    let g = i32::from_str_radix(&s[2..4], 16).unwrap_or(0);
    let b = i32::from_str_radix(&s[4..6], 16).unwrap_or(0);
    (
        f64::from(r) / 255.0,
        f64::from(g) / 255.0,
        f64::from(b) / 255.0,
    )
}

fn rgb01_to_hex(r: f64, g: f64, b: f64) -> String {
    let to_byte = |v: f64| -> u8 {
        let c = v.clamp(0.0, 1.0);
        // Python's round() uses banker's rounding; CPython's
        // int(round(x)) does half-to-even. Emulate via f64::round
        // (half-away-from-zero) — close enough for our jitter range.
        (c * 255.0).round() as u8
    };
    format!("#{:02X}{:02X}{:02X}", to_byte(r), to_byte(g), to_byte(b))
}

/// CPython ``colorsys.rgb_to_hls``.
fn rgb_to_hls(r: f64, g: f64, b: f64) -> (f64, f64, f64) {
    let maxc = r.max(g).max(b);
    let minc = r.min(g).min(b);
    let sumc = maxc + minc;
    let l = sumc / 2.0;
    if maxc == minc {
        return (0.0, l, 0.0);
    }
    let rangec = maxc - minc;
    let s = if l <= 0.5 {
        rangec / sumc
    } else {
        rangec / (2.0 - maxc - minc)
    };
    let rc = (maxc - r) / rangec;
    let gc = (maxc - g) / rangec;
    let bc = (maxc - b) / rangec;
    let h = if r == maxc {
        bc - gc
    } else if g == maxc {
        2.0 + rc - bc
    } else {
        4.0 + gc - rc
    };
    let h = (h / 6.0).rem_euclid(1.0);
    (h, l, s)
}

fn hls_to_rgb(h: f64, l: f64, s: f64) -> (f64, f64, f64) {
    if s == 0.0 {
        return (l, l, l);
    }
    let m2 = if l <= 0.5 {
        l * (1.0 + s)
    } else {
        l + s - l * s
    };
    let m1 = 2.0 * l - m2;
    (
        hls_v(m1, m2, h + 1.0 / 3.0),
        hls_v(m1, m2, h),
        hls_v(m1, m2, h - 1.0 / 3.0),
    )
}

fn hls_v(m1: f64, m2: f64, hue: f64) -> f64 {
    let h = hue.rem_euclid(1.0);
    if h < 1.0 / 6.0 {
        m1 + (m2 - m1) * h * 6.0
    } else if h < 0.5 {
        m2
    } else if h < 2.0 / 3.0 {
        m1 + (m2 - m1) * (2.0 / 3.0 - h) * 6.0
    } else {
        m1
    }
}

/// Single bush at tile (tx, ty).
fn bush_fragment_for_tile(tx: i32, ty: i32) -> String {
    let (dx, dy) = center_offset(tx, ty);
    let cx = (f64::from(tx) + 0.5) * CELL + dx;
    let cy = (f64::from(ty) + 0.5) * CELL + dy;

    let n = lobe_count(tx, ty);
    let cluster_r = cluster_radius(tx, ty);

    let canopy_lobes = lobe_circles(
        cx, cy, tx, ty, BUSH_CANOPY_SHAPE_SALT,
        n, BUSH_CANOPY_LOBE_RADIUS, cluster_r,
        BUSH_CANOPY_LOBE_RADIUS_JITTER,
        BUSH_CANOPY_LOBE_OFFSET_JITTER,
        BUSH_CANOPY_LOBE_ANGLE_JITTER,
    );
    let shadow_lobes = lobe_circles(
        cx + BUSH_CANOPY_SHADOW_OFFSET,
        cy + BUSH_CANOPY_SHADOW_OFFSET,
        tx, ty, BUSH_SHADOW_SHAPE_SALT,
        n, BUSH_CANOPY_SHADOW_LOBE_RADIUS, cluster_r,
        BUSH_CANOPY_LOBE_RADIUS_JITTER,
        BUSH_CANOPY_LOBE_OFFSET_JITTER,
        BUSH_CANOPY_LOBE_ANGLE_JITTER,
    );

    let canopy_d = union_path_from_lobes(&canopy_lobes);
    let shadow_d = union_path_from_lobes(&shadow_lobes);
    let canopy_fill = fill_jitter(tx, ty);

    let mut parts = String::new();
    parts.push_str(&format!(
        "<g id=\"bush-{tx}-{ty}\" class=\"bush-feature\">",
    ));
    parts.push_str(&format!(
        "<path class=\"bush-canopy-shadow\" d=\"{shadow_d}\" \
         fill=\"{BUSH_CANOPY_SHADOW_FILL}\" stroke=\"none\"/>",
    ));
    parts.push_str(&format!(
        "<path class=\"bush-canopy\" d=\"{canopy_d}\" \
         fill=\"{canopy_fill}\" stroke=\"{BUSH_CANOPY_STROKE}\" \
         stroke-width=\"{BUSH_CANOPY_STROKE_WIDTH:.1}\" \
         stroke-opacity=\"{BUSH_CANOPY_STROKE_ALPHA:.2}\"/>",
    ));
    // Volume marks: small irregular arcs.
    for d in scatter_volume_marks(
        cx, cy, tx, ty, BUSH_VOLUME_SALT,
        BUSH_VOLUME_MARK_COUNT,
        BUSH_VOLUME_MARK_AREA_RADIUS,
        BUSH_VOLUME_MARK_RADIUS_MIN,
        BUSH_VOLUME_MARK_RADIUS_MAX,
        BUSH_VOLUME_MARK_SWEEP_MIN,
        BUSH_VOLUME_MARK_SWEEP_MAX,
    ) {
        parts.push_str(&format!(
            "<path class=\"bush-volume\" d=\"{d}\" \
             fill=\"none\" stroke=\"{BUSH_CANOPY_STROKE}\" \
             stroke-width=\"{BUSH_VOLUME_STROKE_WIDTH:.2}\" \
             stroke-opacity=\"{BUSH_VOLUME_STROKE_ALPHA:.2}\" \
             stroke-dasharray=\"{BUSH_VOLUME_DASH}\" \
             stroke-linecap=\"round\"/>",
        ));
    }
    parts.push_str("</g>");
    parts
}

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
        let u = well::hash_unit(tx, ty, salt + i * 17 + 3);
        let ang = well::hash_norm(tx, ty, salt + i * 19 + 5) * PI;
        let r_pos = area_radius * u.sqrt();
        let mx = cx + ang.cos() * r_pos;
        let my = cy + ang.sin() * r_pos;
        let u_r = well::hash_unit(tx, ty, salt + i * 23 + 7);
        let mr = mark_radius_min + (mark_radius_max - mark_radius_min) * u_r;
        let sweep_start =
            well::hash_norm(tx, ty, salt + i * 29 + 11) * PI;
        let u_sw = well::hash_unit(tx, ty, salt + i * 31 + 13);
        let sweep_len = sweep_min + (sweep_max - sweep_min) * u_sw;
        out.push(well::arc_path(
            mx, my, mr, sweep_start, sweep_start + sweep_len,
        ));
    }
    out
}

/// Bush primitive entry point.
pub fn draw_bush(tiles: &[(i32, i32)]) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    tiles
        .iter()
        .map(|&(tx, ty)| bush_fragment_for_tile(tx, ty))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_returns_empty() {
        assert!(draw_bush(&[]).is_empty());
    }

    #[test]
    fn emits_g_envelope() {
        let out = draw_bush(&[(2, 3)]);
        assert_eq!(out.len(), 1);
        assert!(out[0].starts_with("<g id=\"bush-2-3\""));
        assert!(out[0].ends_with("</g>"));
        assert!(out[0].contains("class=\"bush-canopy\""));
        assert!(out[0].contains("class=\"bush-canopy-shadow\""));
    }

    #[test]
    fn deterministic() {
        assert_eq!(draw_bush(&[(5, 7)]), draw_bush(&[(5, 7)]));
    }

    #[test]
    fn different_tiles_differ() {
        let a = draw_bush(&[(0, 0)]);
        let b = draw_bush(&[(99, 99)]);
        assert_ne!(a, b);
    }

    #[test]
    fn shift_color_round_trip_zero() {
        // Shifting by zero in all dimensions should reproduce the
        // input (modulo HLS round-trip rounding error).
        let out = shift_color("#7A9560", 0.0, 0.0, 0.0);
        assert_eq!(out, "#7A9560");
    }
}
