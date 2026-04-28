//! Tree surface-feature primitive — Phase 4 sub-step 15
//! (plan §8 Q4).
//!
//! Reproduces ``_tree_fragment_for_tile`` (per-tile single tree
//! with trunk + multi-lobed canopy + shadow + volume marks) and
//! ``_grove_union_fragment`` (3+ adjacent trees union into one
//! fused canopy without trunks) from
//! ``nhc/rendering/_features_svg.py``.
//!
//! Grove detection (4-adjacent connected components of "tree"
//! feature tiles) is computed Python-side and shipped across
//! the FFI boundary as a separate ``groves`` argument. The
//! emitter passes singletons + pairs as ``free_trees`` (each
//! painted as an individual tree) and groves of size ≥ 3 as
//! ``groves`` (each painted as one fused fragment).
//!
//! **Parity contract:** relaxed gate — same as bush. The
//! polygon union via the geo crate's BooleanOps differs from
//! Shapely / GEOS in vertex ordering and numerical precision.

use std::f64::consts::PI;

use super::bush::{shift_color_pub, union_path_from_lobes_pub};
use super::well;

const CELL: f64 = 32.0;

const TREE_CANOPY_FILL: &str = "#6B8A56";
const TREE_CANOPY_STROKE: &str = "#3F5237";
const TREE_CANOPY_STROKE_WIDTH: f64 = 1.2;
const TREE_CANOPY_STROKE_ALPHA: f64 = 0.78;

const TREE_CANOPY_LOBE_COUNT_CHOICES: [i32; 2] = [6, 7];
const TREE_CANOPY_LOBE_RADIUS: f64 = 0.32 * CELL;
const TREE_CANOPY_CLUSTER_RADIUS: f64 = 0.30 * CELL;
const TREE_CANOPY_CLUSTER_RADIUS_JITTER: f64 = 0.18;
const TREE_CANOPY_LOBE_RADIUS_JITTER: f64 = 0.20;
const TREE_CANOPY_LOBE_OFFSET_JITTER: f64 = 0.30;
const TREE_CANOPY_LOBE_ANGLE_JITTER: f64 = 0.35;
const TREE_CANOPY_CENTER_OFFSET: f64 = 0.18 * CELL;

const TREE_CANOPY_SHADOW_FILL: &str = "#2F4527";
const TREE_CANOPY_SHADOW_LOBE_RADIUS: f64 = 0.36 * CELL;
const TREE_CANOPY_SHADOW_OFFSET: f64 = 0.05 * CELL;

const TREE_VOLUME_MARK_COUNT: i32 = 6;
const TREE_VOLUME_MARK_AREA_RADIUS: f64 = 0.45 * CELL;
const TREE_VOLUME_MARK_RADIUS_MIN: f64 = 0.07 * CELL;
const TREE_VOLUME_MARK_RADIUS_MAX: f64 = 0.13 * CELL;
const TREE_VOLUME_MARK_SWEEP_MIN: f64 = 0.7;
const TREE_VOLUME_MARK_SWEEP_MAX: f64 = 1.8;
const TREE_VOLUME_STROKE_WIDTH: f64 = 0.8;
const TREE_VOLUME_STROKE_ALPHA: f64 = 0.55;
const TREE_VOLUME_DASH: &str = "2 2";
const TREE_VOLUME_SALT: i32 = 7011;

const TREE_HUE_JITTER_DEG: f64 = 6.0;
const TREE_SAT_JITTER: f64 = 0.05;
const TREE_LIGHT_JITTER: f64 = 0.04;

const TREE_TRUNK_FILL: &str = "#4A3320";
const TREE_TRUNK_STROKE_WIDTH: f64 = 0.9;
const TREE_TRUNK_RADIUS: f64 = 0.16 * CELL;
const TREE_TRUNK_OFFSET_Y: f64 = 0.32 * CELL;
const INK: &str = "#000000";

const HUE_SALT: i32 = 1009;
const SAT_SALT: i32 = 2017;
const LIGHT_SALT: i32 = 3041;

const TREE_LOBE_COUNT_SALT: i32 = 8101;
const TREE_CLUSTER_RADIUS_SALT: i32 = 8111;
const TREE_CENTER_X_SALT: i32 = 8123;
const TREE_CENTER_Y_SALT: i32 = 8147;

const CANOPY_SHAPE_SALT: i32 = 4001;
const SHADOW_SHAPE_SALT: i32 = 5003;

fn lobe_count(tx: i32, ty: i32) -> i32 {
    let u = well::hash_unit(tx, ty, TREE_LOBE_COUNT_SALT);
    let n = TREE_CANOPY_LOBE_COUNT_CHOICES.len() as i32;
    let idx = ((u * f64::from(n)) as i32).min(n - 1);
    TREE_CANOPY_LOBE_COUNT_CHOICES[idx as usize]
}

fn cluster_radius(tx: i32, ty: i32) -> f64 {
    let j = well::hash_norm(tx, ty, TREE_CLUSTER_RADIUS_SALT);
    TREE_CANOPY_CLUSTER_RADIUS * (1.0 + j * TREE_CANOPY_CLUSTER_RADIUS_JITTER)
}

fn center_offset(tx: i32, ty: i32) -> (f64, f64) {
    let dx = well::hash_norm(tx, ty, TREE_CENTER_X_SALT)
        * TREE_CANOPY_CENTER_OFFSET;
    let dy = well::hash_norm(tx, ty, TREE_CENTER_Y_SALT)
        * TREE_CANOPY_CENTER_OFFSET;
    (dx, dy)
}

fn lobe_circles(
    cx: f64, cy: f64, tx: i32, ty: i32, salt: i32,
    n_lobes: i32, lobe_radius: f64, cluster_r: f64,
) -> Vec<(f64, f64, f64)> {
    let step = 2.0 * PI / f64::from(n_lobes);
    let mut out = Vec::with_capacity(n_lobes as usize);
    for i in 0..n_lobes {
        let a_jit = well::hash_norm(tx, ty, salt + i * 7)
            * TREE_CANOPY_LOBE_ANGLE_JITTER;
        let o_jit = 1.0
            + well::hash_norm(tx, ty, salt + i * 11 + 1)
                * TREE_CANOPY_LOBE_OFFSET_JITTER;
        let r_jit = 1.0
            + well::hash_norm(tx, ty, salt + i * 13 + 2)
                * TREE_CANOPY_LOBE_RADIUS_JITTER;
        let ang = f64::from(i) * step + a_jit;
        let offs = cluster_r * o_jit;
        let lr = lobe_radius * r_jit;
        out.push((cx + ang.cos() * offs, cy + ang.sin() * offs, lr));
    }
    out
}

fn canopy_lobes(cx: f64, cy: f64, tx: i32, ty: i32) -> Vec<(f64, f64, f64)> {
    lobe_circles(
        cx, cy, tx, ty, CANOPY_SHAPE_SALT,
        lobe_count(tx, ty),
        TREE_CANOPY_LOBE_RADIUS,
        cluster_radius(tx, ty),
    )
}

fn shadow_lobes(cx: f64, cy: f64, tx: i32, ty: i32) -> Vec<(f64, f64, f64)> {
    lobe_circles(
        cx + TREE_CANOPY_SHADOW_OFFSET,
        cy + TREE_CANOPY_SHADOW_OFFSET,
        tx, ty, SHADOW_SHAPE_SALT,
        lobe_count(tx, ty),
        TREE_CANOPY_SHADOW_LOBE_RADIUS,
        cluster_radius(tx, ty),
    )
}

fn canopy_fill_jitter(tx: i32, ty: i32) -> String {
    let dh = well::hash_norm(tx, ty, HUE_SALT) * TREE_HUE_JITTER_DEG;
    let ds = well::hash_norm(tx, ty, SAT_SALT) * TREE_SAT_JITTER;
    let dl = well::hash_norm(tx, ty, LIGHT_SALT) * TREE_LIGHT_JITTER;
    shift_color_pub(TREE_CANOPY_FILL, dh, ds, dl)
}

#[allow(clippy::too_many_arguments)]
fn scatter_volume_marks(
    cx: f64, cy: f64,
    tx: i32, ty: i32, salt: i32,
    n_marks: i32,
    area_radius: f64,
    mark_radius_min: f64, mark_radius_max: f64,
    sweep_min: f64, sweep_max: f64,
) -> Vec<String> {
    let mut out = Vec::with_capacity(n_marks as usize);
    for i in 0..n_marks {
        let u = well::hash_unit(tx, ty, salt + i * 17 + 3);
        let ang = well::hash_norm(tx, ty, salt + i * 19 + 5) * PI;
        let r_pos = area_radius * u.sqrt();
        let mx = cx + ang.cos() * r_pos;
        let my = cy + ang.sin() * r_pos;
        let u_r = well::hash_unit(tx, ty, salt + i * 23 + 7);
        let mr =
            mark_radius_min + (mark_radius_max - mark_radius_min) * u_r;
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

fn tree_volume_fragments(cx: f64, cy: f64, tx: i32, ty: i32) -> Vec<String> {
    scatter_volume_marks(
        cx, cy, tx, ty, TREE_VOLUME_SALT,
        TREE_VOLUME_MARK_COUNT,
        TREE_VOLUME_MARK_AREA_RADIUS,
        TREE_VOLUME_MARK_RADIUS_MIN,
        TREE_VOLUME_MARK_RADIUS_MAX,
        TREE_VOLUME_MARK_SWEEP_MIN,
        TREE_VOLUME_MARK_SWEEP_MAX,
    )
    .into_iter()
    .map(|d| {
        format!(
            "<path class=\"tree-volume\" d=\"{d}\" \
             fill=\"none\" stroke=\"{TREE_CANOPY_STROKE}\" \
             stroke-width=\"{TREE_VOLUME_STROKE_WIDTH:.2}\" \
             stroke-opacity=\"{TREE_VOLUME_STROKE_ALPHA:.2}\" \
             stroke-dasharray=\"{TREE_VOLUME_DASH}\" \
             stroke-linecap=\"round\"/>",
        )
    })
    .collect()
}

fn tree_fragment_for_tile(tx: i32, ty: i32) -> String {
    let (dx, dy) = center_offset(tx, ty);
    let cx = (f64::from(tx) + 0.5) * CELL + dx;
    let cy = (f64::from(ty) + 0.5) * CELL + dy;
    let trunk_cx = cx;
    let trunk_cy = cy + TREE_TRUNK_OFFSET_Y;
    let canopy_d =
        union_path_from_lobes_pub(&canopy_lobes(cx, cy, tx, ty));
    let shadow_d =
        union_path_from_lobes_pub(&shadow_lobes(cx, cy, tx, ty));
    let canopy_fill = canopy_fill_jitter(tx, ty);

    let mut parts = String::new();
    parts.push_str(&format!(
        "<g id=\"tree-{tx}-{ty}\" class=\"tree-feature\">",
    ));
    parts.push_str(&format!(
        "<circle class=\"tree-trunk\" cx=\"{trunk_cx:.1}\" \
         cy=\"{trunk_cy:.1}\" r=\"{TREE_TRUNK_RADIUS:.1}\" \
         fill=\"{TREE_TRUNK_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{TREE_TRUNK_STROKE_WIDTH:.1}\"/>",
    ));
    parts.push_str(&format!(
        "<path class=\"tree-canopy-shadow\" d=\"{shadow_d}\" \
         fill=\"{TREE_CANOPY_SHADOW_FILL}\" stroke=\"none\"/>",
    ));
    parts.push_str(&format!(
        "<path class=\"tree-canopy\" d=\"{canopy_d}\" \
         fill=\"{canopy_fill}\" stroke=\"{TREE_CANOPY_STROKE}\" \
         stroke-width=\"{TREE_CANOPY_STROKE_WIDTH:.1}\" \
         stroke-opacity=\"{TREE_CANOPY_STROKE_ALPHA:.2}\"/>",
    ));
    for frag in tree_volume_fragments(cx, cy, tx, ty) {
        parts.push_str(&frag);
    }
    parts.push_str("</g>");
    parts
}

fn grove_fragment(grove: &[(i32, i32)]) -> String {
    // Anchor = min(grove) by lexicographic order (x, y) — same as
    // Python's `min(grove)` on a (tx, ty) tuple.
    let mut sorted = grove.to_vec();
    sorted.sort_unstable();
    let anchor = sorted[0];

    // Collect all canopy + shadow lobes across the grove and
    // union them.
    let mut canopy_all: Vec<(f64, f64, f64)> = Vec::new();
    let mut shadow_all: Vec<(f64, f64, f64)> = Vec::new();
    for &(tx, ty) in &sorted {
        let (dx, dy) = center_offset(tx, ty);
        let cx = (f64::from(tx) + 0.5) * CELL + dx;
        let cy = (f64::from(ty) + 0.5) * CELL + dy;
        canopy_all.extend(canopy_lobes(cx, cy, tx, ty));
        shadow_all.extend(shadow_lobes(cx, cy, tx, ty));
    }
    let canopy_d = union_path_from_lobes_pub(&canopy_all);
    let shadow_d = union_path_from_lobes_pub(&shadow_all);
    let canopy_fill = canopy_fill_jitter(anchor.0, anchor.1);

    let mut parts = String::new();
    parts.push_str(&format!(
        "<g id=\"tree-grove-{}-{}\" class=\"tree-grove\">",
        anchor.0, anchor.1,
    ));
    parts.push_str(&format!(
        "<path class=\"tree-canopy-shadow\" d=\"{shadow_d}\" \
         fill=\"{TREE_CANOPY_SHADOW_FILL}\" stroke=\"none\"/>",
    ));
    parts.push_str(&format!(
        "<path class=\"tree-canopy\" d=\"{canopy_d}\" \
         fill=\"{canopy_fill}\" stroke=\"{TREE_CANOPY_STROKE}\" \
         stroke-width=\"{TREE_CANOPY_STROKE_WIDTH:.1}\" \
         stroke-opacity=\"{TREE_CANOPY_STROKE_ALPHA:.2}\"/>",
    ));
    // Volume marks: one set per tile, in sorted order.
    for &(tx, ty) in &sorted {
        let (dx, dy) = center_offset(tx, ty);
        let cx = (f64::from(tx) + 0.5) * CELL + dx;
        let cy = (f64::from(ty) + 0.5) * CELL + dy;
        for frag in tree_volume_fragments(cx, cy, tx, ty) {
            parts.push_str(&frag);
        }
    }
    parts.push_str("</g>");
    parts
}

/// Tree primitive entry point.
///
/// `free_trees` is the list of singletons / pair-tree tiles
/// (groves of size ≤ 2 — each tile painted individually).
/// `groves` is the list of groves of size ≥ 3 (each painted as
/// one fused fragment, anchored at `min(tiles)`).
///
/// The emitter Python-side runs a 4-adjacency BFS over
/// ``tile.feature == "tree"``, splits the result by component
/// size, and passes both lists across. Returns one fragment
/// per free tree + one fragment per grove.
pub fn draw_tree(
    free_trees: &[(i32, i32)], groves: &[Vec<(i32, i32)>],
) -> Vec<String> {
    if free_trees.is_empty() && groves.is_empty() {
        return Vec::new();
    }
    let mut out: Vec<String> = Vec::with_capacity(
        free_trees.len() + groves.len(),
    );
    for &(tx, ty) in free_trees {
        out.push(tree_fragment_for_tile(tx, ty));
    }
    for grove in groves {
        if grove.is_empty() {
            continue;
        }
        out.push(grove_fragment(grove));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_returns_empty() {
        assert!(draw_tree(&[], &[]).is_empty());
    }

    #[test]
    fn free_tree_envelope() {
        let out = draw_tree(&[(2, 3)], &[]);
        assert_eq!(out.len(), 1);
        assert!(out[0].starts_with("<g id=\"tree-2-3\""));
        assert!(out[0].contains("class=\"tree-feature\""));
        assert!(out[0].contains("class=\"tree-trunk\""));
        assert!(out[0].contains("class=\"tree-canopy\""));
    }

    #[test]
    fn grove_envelope() {
        let grove: Vec<(i32, i32)> = vec![(2, 3), (3, 3), (4, 3)];
        let out = draw_tree(&[], &[grove]);
        assert_eq!(out.len(), 1);
        assert!(out[0].starts_with("<g id=\"tree-grove-2-3\""));
        assert!(out[0].contains("class=\"tree-grove\""));
        // Groves drop trunks.
        assert!(!out[0].contains("class=\"tree-trunk\""));
    }

    #[test]
    fn deterministic() {
        let trees = vec![(5, 7)];
        let groves: Vec<Vec<(i32, i32)>> =
            vec![vec![(1, 1), (1, 2), (1, 3)]];
        assert_eq!(
            draw_tree(&trees, &groves),
            draw_tree(&trees, &groves),
        );
    }
}
