//! Tree surface-feature primitive — Phase 4 sub-step 15
//! (plan §8 Q4), ported to the Painter trait in Phase 2.14c of
//! `plans/nhc_pure_ir_plan.md` (the **third of four fixture
//! ports** — well / fountain / tree / bush). Per the plan §2.14
//! table, fixtures are NO group-opacity: solid stamps that
//! composite directly without `begin_group` / `end_group`
//! envelopes.
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
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_tree` SVG-string emitter (used by the
//!   FFI / `nhc/rendering/ir_to_svg.py` Python path until 2.17
//!   ships the `SvgPainter`-based PyO3 export and 2.19 retires
//!   the Python `ir_to_svg` path).
//! - The new `paint_tree` Painter-based emitter (used by the
//!   Rust `transform/png` path via `SkiaPainter` and, after 2.17,
//!   by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! ## Group-opacity contract
//!
//! NO group envelope. The legacy SVG `<g>` wrapper carries no
//! `opacity` attribute (only `id` and `class`), so
//! `paint_fragment`'s `strip_g_wrapper` returns `opacity=1.0` and
//! the children render directly to the pixmap. The Painter port
//! skips `begin_group` / `end_group` entirely — fixtures
//! composite as solid stamps per the plan §2.14 contract.
//!
//! ## Canopy / shadow union paths
//!
//! Canopy and shadow lobe-circles are unioned via the geo
//! crate's `BooleanOps::union` (from `bush::union_path_from_lobes_pub`,
//! shared with the bush primitive) and emitted as one
//! `<path d="M…L…L…Z M…L…L…Z…">` per silhouette at `:.1`
//! precision. The legacy PNG path runs `parse_path_d` on that
//! string, which builds an open polyline + close per subpath.
//! The Painter port re-parses the same string into PathOps,
//! preserving the exact `move_to + line_to* + close` segment
//! sequence so stroking miters render identically. Re-using
//! the string keeps both paths bit-equal — no risk of drift
//! from a parallel geo-union mirror.
//!
//! ## Trunk circle
//!
//! Trunks are `<circle>` at `:.1` precision (matching
//! `_tree_fragment_for_tile`'s formatter). Mirrors the
//! `paint_circle` KAPPA-cubic ellipse path from `fragment.rs`,
//! at the same precision.
//!
//! ## Volume-mark arcs
//!
//! Volume marks reuse `well::arc_path` (`:.1`) and emit one
//! `<path>` per arc with `stroke-dasharray="2 2"` and
//! `stroke-opacity="0.55"`. As with fountain ripples,
//! `transform/png`'s `paint_for` / `stroke_for` ignore both
//! attributes — the Painter port also ignores them, so volume
//! marks render at full alpha, undashed, exactly matching the
//! legacy PNG.

use std::f64::consts::PI;

use super::bush::{shift_color_pub, union_path_from_lobes_pub};
use super::well;
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

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

// ── Painter-trait port (Phase 2.14c) ──────────────────────────

/// Painter-trait entry point — Phase 2.14c port (the third of
/// four fixture ports — well / fountain / tree / bush).
///
/// Walks the same per-tile + per-grove geometry as `draw_tree`
/// and dispatches each silhouette through the Painter trait
/// directly — no `begin_group` / `end_group` envelope (fixtures
/// are NO group-opacity per plan §2.14). PNG output stays pixel-
/// equal with the pre-port `paint_fragments` path; only the
/// intermediate SVG-string round-trip disappears.
pub fn paint_tree(
    painter: &mut dyn Painter,
    free_trees: &[(i32, i32)],
    groves: &[Vec<(i32, i32)>],
) {
    if free_trees.is_empty() && groves.is_empty() {
        return;
    }
    for &(tx, ty) in free_trees {
        paint_free_tree(painter, tx, ty);
    }
    for grove in groves {
        if grove.is_empty() {
            continue;
        }
        paint_grove(painter, grove);
    }
}

fn paint_free_tree(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let (dx, dy) = center_offset(tx, ty);
    let cx = (f64::from(tx) + 0.5) * CELL + dx;
    let cy = (f64::from(ty) + 0.5) * CELL + dy;
    let trunk_cx = cx;
    let trunk_cy = cy + TREE_TRUNK_OFFSET_Y;

    // Element order mirrors `tree_fragment_for_tile`: trunk
    // first, then shadow path, then canopy path, then volume
    // marks. Painters composite in document order.
    paint_trunk(painter, trunk_cx, trunk_cy);
    paint_shadow_canopy(
        painter,
        &shadow_lobes(cx, cy, tx, ty),
    );
    paint_canopy(
        painter,
        &canopy_lobes(cx, cy, tx, ty),
        &canopy_fill_jitter(tx, ty),
    );
    paint_volume_marks(painter, cx, cy, tx, ty);
}

fn paint_grove(painter: &mut dyn Painter, grove: &[(i32, i32)]) {
    // Anchor = min(grove) by lex (x, y) — same as Python `min`.
    let mut sorted = grove.to_vec();
    sorted.sort_unstable();
    let anchor = sorted[0];

    let mut canopy_all: Vec<(f64, f64, f64)> = Vec::new();
    let mut shadow_all: Vec<(f64, f64, f64)> = Vec::new();
    for &(tx, ty) in &sorted {
        let (dx, dy) = center_offset(tx, ty);
        let cx = (f64::from(tx) + 0.5) * CELL + dx;
        let cy = (f64::from(ty) + 0.5) * CELL + dy;
        canopy_all.extend(canopy_lobes(cx, cy, tx, ty));
        shadow_all.extend(shadow_lobes(cx, cy, tx, ty));
    }
    paint_shadow_canopy(painter, &shadow_all);
    paint_canopy(
        painter,
        &canopy_all,
        &canopy_fill_jitter(anchor.0, anchor.1),
    );
    // Volume marks: one set per tile, in sorted order.
    for &(tx, ty) in &sorted {
        let (dx, dy) = center_offset(tx, ty);
        let cx = (f64::from(tx) + 0.5) * CELL + dx;
        let cy = (f64::from(ty) + 0.5) * CELL + dy;
        paint_volume_marks(painter, cx, cy, tx, ty);
    }
}

fn paint_trunk(painter: &mut dyn Painter, trunk_cx: f64, trunk_cy: f64) {
    // `<circle ... cx=":.1" cy=":.1" r=":.1" fill stroke
    // stroke-width=":.1"/>`. Mirror the legacy `paint_circle`'s
    // KAPPA-cubic ellipse path at `:.1` precision.
    let path = ellipse_path_ops_1(
        trunk_cx, trunk_cy, TREE_TRUNK_RADIUS, TREE_TRUNK_RADIUS,
    );
    let trunk_fill = paint_for_hex(TREE_TRUNK_FILL);
    let ink = paint_for_hex(INK);
    let stroke = Stroke {
        width: round_legacy_1(TREE_TRUNK_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    painter.fill_path(&path, &trunk_fill, FillRule::Winding);
    painter.stroke_path(&path, &ink, &stroke);
}

fn paint_shadow_canopy(
    painter: &mut dyn Painter,
    lobes: &[(f64, f64, f64)],
) {
    // `<path d="M…L…L…Z M…L…L…Z…" fill stroke="none"/>` at
    // `:.1` precision. `polygon_to_svg_path` (in bush.rs) emits
    // one M…L…L…Z subpath per polygon ring; we re-parse the
    // string into PathOps so the segment sequence matches what
    // `parse_path_d` builds on the legacy path.
    let d = union_path_from_lobes_pub(lobes);
    if d.is_empty() {
        return;
    }
    let path = polygon_d_to_path_ops(&d);
    if path.is_empty() {
        return;
    }
    let fill = paint_for_hex(TREE_CANOPY_SHADOW_FILL);
    painter.fill_path(&path, &fill, FillRule::Winding);
}

fn paint_canopy(
    painter: &mut dyn Painter,
    lobes: &[(f64, f64, f64)],
    fill_hex: &str,
) {
    // `<path d="M…L…L…Z M…L…L…Z…" fill stroke
    // stroke-width=":.1" stroke-opacity=":.2"/>` at `:.1`
    // precision. `stroke-opacity` is ignored by `paint_for`
    // (only group opacity is applied; tree's group has none).
    let d = union_path_from_lobes_pub(lobes);
    if d.is_empty() {
        return;
    }
    let path = polygon_d_to_path_ops(&d);
    if path.is_empty() {
        return;
    }
    let fill = paint_for_hex(fill_hex);
    let stroke_paint = paint_for_hex(TREE_CANOPY_STROKE);
    let stroke = Stroke {
        width: round_legacy_1(TREE_CANOPY_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    painter.fill_path(&path, &fill, FillRule::Winding);
    painter.stroke_path(&path, &stroke_paint, &stroke);
}

fn paint_volume_marks(
    painter: &mut dyn Painter,
    cx: f64, cy: f64, tx: i32, ty: i32,
) {
    // One stroke_path per arc. `stroke-dasharray` /
    // `stroke-opacity` from the legacy `<path>` are ignored by
    // `transform/png` (see module docs). `stroke-linecap=round`
    // IS honoured by `stroke_for`.
    let arcs = volume_arc_shapes(
        cx, cy, tx, ty, TREE_VOLUME_SALT,
        TREE_VOLUME_MARK_COUNT,
        TREE_VOLUME_MARK_AREA_RADIUS,
        TREE_VOLUME_MARK_RADIUS_MIN,
        TREE_VOLUME_MARK_RADIUS_MAX,
        TREE_VOLUME_MARK_SWEEP_MIN,
        TREE_VOLUME_MARK_SWEEP_MAX,
    );
    let stroke_paint = paint_for_hex(TREE_CANOPY_STROKE);
    let stroke = Stroke {
        width: round_legacy_2(TREE_VOLUME_STROKE_WIDTH),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    for arc in arcs {
        let path = arc_path_ops(arc.cx, arc.cy, arc.r, arc.a0, arc.a1);
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
}

/// Per-arc record. Mirrors `well::ArcShape` / fountain's
/// `ArcShape` in shape; duplicated locally because the well
/// version is private and the fountain copy is module-local too.
#[derive(Clone, Copy, Debug, PartialEq)]
struct ArcShape {
    cx: f64,
    cy: f64,
    r: f64,
    a0: f64,
    a1: f64,
}

#[allow(clippy::too_many_arguments)]
fn volume_arc_shapes(
    cx: f64, cy: f64,
    tx: i32, ty: i32, salt: i32,
    n_marks: i32,
    area_radius: f64,
    mark_radius_min: f64, mark_radius_max: f64,
    sweep_min: f64, sweep_max: f64,
) -> Vec<ArcShape> {
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
        out.push(ArcShape {
            cx: mx,
            cy: my,
            r: mr,
            a0: sweep_start,
            a1: sweep_start + sweep_len,
        });
    }
    out
}

// ── Path-op builders mirroring fragment.rs / path_parser.rs ──

const KAPPA: f32 = 0.552_284_8;

/// KAPPA-cubic ellipse path matching `fragment.rs::ellipse_path`
/// at `:.1` precision (matches `<circle r=":.1">`).
fn ellipse_path_ops_1(cx: f64, cy: f64, rx: f64, ry: f64) -> PathOps {
    let cx = round_legacy_1(cx);
    let cy = round_legacy_1(cy);
    let rx = round_legacy_1(rx);
    let ry = round_legacy_1(ry);
    let ox = rx * KAPPA;
    let oy = ry * KAPPA;
    let mut p = PathOps::with_capacity(6);
    p.move_to(Vec2::new(cx + rx, cy));
    p.cubic_to(
        Vec2::new(cx + rx, cy + oy),
        Vec2::new(cx + ox, cy + ry),
        Vec2::new(cx, cy + ry),
    );
    p.cubic_to(
        Vec2::new(cx - ox, cy + ry),
        Vec2::new(cx - rx, cy + oy),
        Vec2::new(cx - rx, cy),
    );
    p.cubic_to(
        Vec2::new(cx - rx, cy - oy),
        Vec2::new(cx - ox, cy - ry),
        Vec2::new(cx, cy - ry),
    );
    p.cubic_to(
        Vec2::new(cx + ox, cy - ry),
        Vec2::new(cx + rx, cy - oy),
        Vec2::new(cx + rx, cy),
    );
    p.close();
    p
}

/// Open ripple arc: `M sx,sy A r,r 0 large sweep ex,ey` at
/// `:.1` precision. Mirrors `well::arc_path` plus the cubic
/// approximation in `path_parser::append_arc`.
fn arc_path_ops(cx: f64, cy: f64, r: f64, a0: f64, a1: f64) -> PathOps {
    let sx = round_legacy_1(cx + a0.cos() * r);
    let sy = round_legacy_1(cy + a0.sin() * r);
    let ex = round_legacy_1(cx + a1.cos() * r);
    let ey = round_legacy_1(cy + a1.sin() * r);
    let r_f = round_legacy_1(r);
    let sweep_len = a1 - a0;
    let large = sweep_len.abs() > PI;
    let sweep = sweep_len >= 0.0;

    let mut p = PathOps::new();
    p.move_to(Vec2::new(sx, sy));
    append_arc_to_path_ops(&mut p, (sx, sy), r_f, large, sweep, ex, ey);
    p
}

/// Re-parse a `M{x:.1},{y:.1} L{x:.1},{y:.1} … Z M…Z` polygon
/// path into PathOps. Mirrors what `parse_path_d` does on the
/// legacy PNG path for the canopy / shadow `<path>` strings
/// emitted by `bush::polygon_to_svg_path`. Multi-subpath safe
/// (each new `M` starts a fresh subpath).
fn polygon_d_to_path_ops(d: &str) -> PathOps {
    let mut p = PathOps::new();
    let mut tokens = d.split_whitespace();
    while let Some(tok) = tokens.next() {
        let first = match tok.chars().next() {
            Some(c) => c,
            None => continue,
        };
        match first {
            'M' => {
                if let Some((x, y)) = parse_xy_after(tok, 'M') {
                    p.move_to(Vec2::new(x, y));
                }
            }
            'L' => {
                if let Some((x, y)) = parse_xy_after(tok, 'L') {
                    p.line_to(Vec2::new(x, y));
                }
            }
            'Z' | 'z' => {
                p.close();
            }
            _ => {}
        }
    }
    p
}

fn parse_xy_after(tok: &str, letter: char) -> Option<(f32, f32)> {
    let rest = tok.strip_prefix(letter)?;
    let comma = rest.find(',')?;
    let x: f32 = rest[..comma].trim().parse().ok()?;
    let y: f32 = rest[comma + 1..].trim().parse().ok()?;
    Some((x, y))
}

/// Append cubic-bezier segments approximating an SVG circular
/// arc to `path`. Mirrors `transform/png/path_parser::append_arc`
/// exactly (same +90° perpendicular sign convention, same chord-
/// fits-radius scaling, same ≤90° split + tan-based control
/// magnitude). NHC only emits circular arcs (rx == ry, no x-axis
/// rotation), the path_parser's hot path.
fn append_arc_to_path_ops(
    path: &mut PathOps,
    start: (f32, f32),
    r: f32,
    large: bool,
    sweep: bool,
    end_x: f32,
    end_y: f32,
) {
    use std::f32::consts::{FRAC_PI_2, PI as PI_F32};
    let (x1, y1) = start;
    if r <= 0.0 {
        path.line_to(Vec2::new(end_x, end_y));
        return;
    }
    let dx = end_x - x1;
    let dy = end_y - y1;
    let chord = (dx * dx + dy * dy).sqrt();
    if chord < 1e-6 {
        return;
    }
    let r = r.max(chord * 0.5);
    let h_sq = r * r - (chord * 0.5).powi(2);
    let h = if h_sq > 0.0 { h_sq.sqrt() } else { 0.0 };
    let perp_x = -dy / chord;
    let perp_y = dx / chord;
    let sign = if large == sweep { -1.0 } else { 1.0 };
    let mid_x = (x1 + end_x) * 0.5;
    let mid_y = (y1 + end_y) * 0.5;
    let cx = mid_x + sign * h * perp_x;
    let cy = mid_y + sign * h * perp_y;
    let a1 = (y1 - cy).atan2(x1 - cx);
    let a2 = (end_y - cy).atan2(end_x - cx);
    let mut delta = a2 - a1;
    if sweep && delta < 0.0 {
        delta += 2.0 * PI_F32;
    } else if !sweep && delta > 0.0 {
        delta -= 2.0 * PI_F32;
    }
    let n = ((delta.abs() / FRAC_PI_2).ceil() as usize).max(1);
    let seg = delta / n as f32;
    let alpha = (4.0 / 3.0) * (seg * 0.25).tan();
    for i in 0..n {
        let a = a1 + seg * i as f32;
        let b = a1 + seg * (i + 1) as f32;
        let cos_a = a.cos();
        let sin_a = a.sin();
        let cos_b = b.cos();
        let sin_b = b.sin();
        let p1x = cx + r * cos_a - r * alpha * sin_a;
        let p1y = cy + r * sin_a + r * alpha * cos_a;
        let p2x = cx + r * cos_b + r * alpha * sin_b;
        let p2y = cy + r * sin_b - r * alpha * cos_b;
        let p3x = cx + r * cos_b;
        let p3y = cy + r * sin_b;
        path.cubic_to(
            Vec2::new(p1x, p1y),
            Vec2::new(p2x, p2y),
            Vec2::new(p3x, p3y),
        );
    }
}

/// Mirror the legacy `{:.1}` truncation + reparse for `:.1`
/// elements (canopy / shadow / trunk / volume-mark arcs).
fn round_legacy_1(v: f64) -> f32 {
    let s = format!("{:.1}", v);
    s.parse::<f64>().unwrap_or(v) as f32
}

/// Mirror the legacy `{:.2}` truncation + reparse for `:.2`
/// elements (volume-mark stroke-width).
fn round_legacy_2(v: f64) -> f32 {
    let s = format!("{:.2}", v);
    s.parse::<f64>().unwrap_or(v) as f32
}

fn parse_hex_rgb(s: &str) -> (u8, u8, u8) {
    s.strip_prefix('#')
        .filter(|t| t.len() == 6)
        .and_then(|t| {
            let r = u8::from_str_radix(&t[0..2], 16).ok()?;
            let g = u8::from_str_radix(&t[2..4], 16).ok()?;
            let b = u8::from_str_radix(&t[4..6], 16).ok()?;
            Some((r, g, b))
        })
        .unwrap_or((0, 0, 0))
}

fn paint_for_hex(hex: &str) -> Paint {
    let (r, g, b) = parse_hex_rgb(hex);
    Paint::solid(Color::rgb(r, g, b))
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

    // ── Painter-path tests ─────────────────────────────────────

    use crate::painter::{
        FillRule as PFillRule, Paint as PPaint, Painter as PainterTrait,
        PathOps as PPathOps, Rect as PRect, Stroke as PStroke,
        Vec2 as PVec2,
    };

    /// Records every Painter call. Modelled on the well + fountain
    /// port CaptureCalls fixtures.
    #[derive(Debug, Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
        group_depth: i32,
        max_group_depth: i32,
    }

    #[derive(Debug, Clone, PartialEq)]
    enum Call {
        FillRect(i32, i32, i32, i32),
        StrokeRect(i32, i32, i32, i32),
        FillPath(usize, i32, i32),
        StrokePath(usize, i32, i32),
        BeginGroup(u32),
        EndGroup,
    }

    fn first_move_to(path: &PPathOps) -> (i32, i32) {
        for op in &path.ops {
            if let crate::painter::PathOp::MoveTo(v) = op {
                return (
                    (v.x * 10.0).round() as i32,
                    (v.y * 10.0).round() as i32,
                );
            }
        }
        (0, 0)
    }

    impl PainterTrait for CaptureCalls {
        fn fill_rect(&mut self, rect: PRect, _: &PPaint) {
            self.calls.push(Call::FillRect(
                (rect.x * 100.0).round() as i32,
                (rect.y * 100.0).round() as i32,
                (rect.w * 100.0).round() as i32,
                (rect.h * 100.0).round() as i32,
            ));
        }
        fn stroke_rect(&mut self, rect: PRect, _: &PPaint, _: &PStroke) {
            self.calls.push(Call::StrokeRect(
                (rect.x * 100.0).round() as i32,
                (rect.y * 100.0).round() as i32,
                (rect.w * 100.0).round() as i32,
                (rect.h * 100.0).round() as i32,
            ));
        }
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &PPaint) {}
        fn fill_ellipse(
            &mut self, _: f32, _: f32, _: f32, _: f32, _: &PPaint,
        ) {
        }
        fn fill_polygon(
            &mut self, _: &[PVec2], _: &PPaint, _: PFillRule,
        ) {
        }
        fn stroke_polyline(
            &mut self, _: &[PVec2], _: &PPaint, _: &PStroke,
        ) {
        }
        fn fill_path(&mut self, path: &PPathOps, _: &PPaint, _: PFillRule) {
            let (mx, my) = first_move_to(path);
            self.calls.push(Call::FillPath(path.ops.len(), mx, my));
        }
        fn stroke_path(&mut self, path: &PPathOps, _: &PPaint, _: &PStroke) {
            let (mx, my) = first_move_to(path);
            self.calls.push(Call::StrokePath(path.ops.len(), mx, my));
        }
        fn begin_group(&mut self, opacity: f32) {
            self.group_depth += 1;
            if self.group_depth > self.max_group_depth {
                self.max_group_depth = self.group_depth;
            }
            self.calls.push(Call::BeginGroup(
                (opacity * 100.0).round() as u32,
            ));
        }
        fn end_group(&mut self) {
            self.group_depth -= 1;
            self.calls.push(Call::EndGroup);
        }
        fn push_clip(&mut self, _: &PPathOps, _: PFillRule) {}
        fn pop_clip(&mut self) {}
    }

    impl CaptureCalls {
        fn fill_rect_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::FillRect(_, _, _, _)))
                .count()
        }
        fn stroke_rect_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::StrokeRect(_, _, _, _)))
                .count()
        }
        fn fill_path_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::FillPath(_, _, _)))
                .count()
        }
        fn stroke_path_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::StrokePath(_, _, _)))
                .count()
        }
        fn group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::BeginGroup(_)))
                .count()
        }
    }

    #[test]
    fn paint_empty_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_tree(&mut painter, &[], &[]);
        assert!(painter.calls.is_empty());
    }

    /// Fixtures are NO group-opacity per plan §2.14 —
    /// `paint_tree` MUST NOT open / close any group envelope
    /// for free trees OR groves.
    #[test]
    fn paint_emits_no_group_envelope() {
        // Free tree.
        let mut a = CaptureCalls::default();
        paint_tree(&mut a, &[(2, 3)], &[]);
        assert_eq!(a.group_count(), 0, "free tree must not begin_group");
        assert_eq!(a.group_depth, 0);
        assert_eq!(a.max_group_depth, 0);

        // Grove.
        let mut b = CaptureCalls::default();
        let grove: Vec<(i32, i32)> = vec![(0, 0), (1, 0), (2, 0)];
        paint_tree(&mut b, &[], &[grove]);
        assert_eq!(b.group_count(), 0, "grove must not begin_group");
        assert_eq!(b.group_depth, 0);
        assert_eq!(b.max_group_depth, 0);
    }

    /// Free tree paints (in order): trunk fill+stroke, shadow
    /// fill, canopy fill+stroke, then N volume-mark strokes. NO
    /// rects.
    #[test]
    fn paint_free_tree_uses_only_paths() {
        let mut painter = CaptureCalls::default();
        paint_tree(&mut painter, &[(2, 3)], &[]);
        assert_eq!(painter.fill_rect_count(), 0);
        assert_eq!(painter.stroke_rect_count(), 0);
        // fills: trunk + shadow + canopy = 3.
        assert_eq!(painter.fill_path_count(), 3);
        // strokes: trunk + canopy + N volume marks.
        assert_eq!(
            painter.stroke_path_count(),
            2 + TREE_VOLUME_MARK_COUNT as usize,
        );
    }

    /// Groves drop the trunk: shadow fill + canopy fill+stroke +
    /// N*tile_count volume marks. NO rects.
    #[test]
    fn paint_grove_drops_trunk() {
        let grove: Vec<(i32, i32)> = vec![(0, 0), (1, 0), (2, 0)];
        let n_tiles = grove.len();
        let mut painter = CaptureCalls::default();
        paint_tree(&mut painter, &[], &[grove]);
        assert_eq!(painter.fill_rect_count(), 0);
        assert_eq!(painter.stroke_rect_count(), 0);
        // fills: shadow + canopy = 2 (no trunks).
        assert_eq!(painter.fill_path_count(), 2);
        // strokes: canopy + per-tile volume marks.
        assert_eq!(
            painter.stroke_path_count(),
            1 + n_tiles * (TREE_VOLUME_MARK_COUNT as usize),
        );
    }

    /// Painter-path determinism for both free trees and groves.
    #[test]
    fn paint_deterministic_for_same_input() {
        let trees = vec![(5, 7)];
        let groves: Vec<Vec<(i32, i32)>> =
            vec![vec![(1, 1), (1, 2), (1, 3)]];

        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_tree(&mut a, &trees, &groves);
        paint_tree(&mut b, &trees, &groves);
        assert_eq!(a.calls, b.calls);
    }

    /// Different positions drive different hash streams, so the
    /// call sequence differs for free trees.
    #[test]
    fn paint_position_sensitive_free_tree() {
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_tree(&mut a, &[(5, 7)], &[]);
        paint_tree(&mut b, &[(99, 99)], &[]);
        assert_ne!(a.calls, b.calls);
    }

    /// Multi-tile / multi-grove input emits per-stamp call
    /// sequences in order.
    #[test]
    fn paint_emits_one_stamp_per_tree_then_per_grove() {
        let trees = vec![(0, 0), (3, 3)];
        let groves: Vec<Vec<(i32, i32)>> = vec![
            vec![(5, 5), (6, 5), (7, 5)],
            vec![(10, 10), (11, 10), (12, 10), (13, 10)],
        ];
        let mut painter = CaptureCalls::default();
        paint_tree(&mut painter, &trees, &groves);

        let n_tree = trees.len();
        let n_grove_tiles: usize =
            groves.iter().map(|g| g.len()).sum();
        // fills: 3 per free tree (trunk+shadow+canopy) + 2 per
        // grove (shadow+canopy).
        assert_eq!(
            painter.fill_path_count(),
            3 * n_tree + 2 * groves.len(),
        );
        // strokes: 2 per free tree + N*tile marks +
        //          1 per grove + N*per-tile marks for grove.
        let marks = TREE_VOLUME_MARK_COUNT as usize;
        let expected_strokes = n_tree * (2 + marks)
            + groves.len()
            + n_grove_tiles * marks;
        assert_eq!(painter.stroke_path_count(), expected_strokes);
    }

    /// Empty grove inside `groves` is silently skipped.
    #[test]
    fn paint_skips_empty_grove() {
        let groves: Vec<Vec<(i32, i32)>> = vec![vec![]];
        let mut painter = CaptureCalls::default();
        paint_tree(&mut painter, &[], &groves);
        assert!(painter.calls.is_empty());
    }

    /// `polygon_d_to_path_ops` round-trips a single-subpath
    /// `M…L…L…Z` correctly: 1 move_to + (N-1) line_to + close.
    #[test]
    fn polygon_d_to_path_ops_single_subpath() {
        let d = "M1.0,2.0 L3.0,4.0 L5.0,6.0 Z";
        let p = polygon_d_to_path_ops(d);
        assert_eq!(p.ops.len(), 4);
        assert!(matches!(p.ops[0], crate::painter::PathOp::MoveTo(_)));
        assert!(matches!(p.ops[1], crate::painter::PathOp::LineTo(_)));
        assert!(matches!(p.ops[2], crate::painter::PathOp::LineTo(_)));
        assert!(matches!(p.ops[3], crate::painter::PathOp::Close));
    }

    /// Multi-subpath: each `M` starts a fresh subpath in the
    /// PathOps stream.
    #[test]
    fn polygon_d_to_path_ops_multi_subpath() {
        let d = "M1.0,2.0 L3.0,4.0 Z M5.0,6.0 L7.0,8.0 Z";
        let p = polygon_d_to_path_ops(d);
        assert_eq!(p.ops.len(), 6);
        assert!(matches!(p.ops[0], crate::painter::PathOp::MoveTo(_)));
        assert!(matches!(p.ops[2], crate::painter::PathOp::Close));
        assert!(matches!(p.ops[3], crate::painter::PathOp::MoveTo(_)));
        assert!(matches!(p.ops[5], crate::painter::PathOp::Close));
    }
}
