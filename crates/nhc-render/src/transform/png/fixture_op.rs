//! FixtureOp consumer — discrete decorative objects with anchors.
//!
//! Phase 2.11 of `plans/nhc_pure_ir_v5_migration_plan.md`. The
//! dispatcher routes each ``FixtureKind`` to a per-kind painter:
//!
//! - **Tree / Bush / Well / Fountain / Stair** — lift the existing
//!   v4 fixture painters (``primitives::{tree, bush, well, fountain,
//!   stairs}.rs``) verbatim. Tree carries the group_id fusion
//!   logic (free trees + groves) end-to-end.
//! - **Web / Skull / Bone / LooseStone** — new painter algorithms
//!   inspired by ``primitives::thematic_detail`` (which lives at
//!   the FloorDetailOp / ThematicDetailOp scatter level rather
//!   than per-anchor). v5 anchors are explicit placements — every
//!   anchor IS a stamp, no probability gate — so the v5 painters
//!   take a single ``(px, py)`` per call, drive a per-anchor RNG
//!   from the FixtureOp seed for sub-style variation, and emit
//!   the per-shape stamp.
//! - **Gravestone / Sign / Mushroom** — new painter algorithms.
//!   Gravestone draws a slab + headstone shape; Sign draws a post
//!   + plank; Mushroom draws a stem + cap pair.
//!
//! Anchor.variant / orientation feed per-kind sub-style dispatch
//! (Well shape, Fountain shape, Stair direction, Web corner). The
//! group_id fusion lifts via the shared ``split_by_group`` helper
//! for all three clustering kinds: Tree groves union canopy /
//! shadow lobes; Mushroom clusters share a low-opacity mycelium
//! patch underlay; Gravestone clusters share a darker dirt-plot
//! underlay. Standalone anchors (group_id = 0) render without a
//! cluster envelope.

use std::collections::BTreeMap;
use std::f64::consts::PI;

use flatbuffers::{ForwardsUOffset, Vector};
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::ir::{Anchor, FixtureKind, FixtureOp, Region};
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};
use crate::primitives::bush::paint_bush;
use crate::primitives::fountain::paint_fountain;
use crate::primitives::stairs::paint_stairs;
use crate::primitives::tree::paint_tree;
use crate::primitives::well::paint_well;

const CELL: f64 = 32.0;

// ── Per-anchor painters for the seven new fixture kinds ─────────

const WEB_INK: Color = Color::rgba(0x33, 0x33, 0x33, 1.0);
const WEB_OPACITY: f32 = 0.45;
const SKULL_FILL: Color = Color::rgba(0xF5, 0xEC, 0xC8, 1.0);
const SKULL_INK: Color = Color::rgba(0x33, 0x2A, 0x1E, 1.0);
const SKULL_OPACITY: f32 = 0.85;
const BONE_FILL: Color = Color::rgba(0xE8, 0xDD, 0xB3, 1.0);
const BONE_INK: Color = Color::rgba(0x66, 0x55, 0x36, 1.0);
const BONE_OPACITY: f32 = 0.85;
const LOOSE_STONE_FILL: Color = Color::rgba(0x9A, 0x90, 0x82, 1.0);
const LOOSE_STONE_INK: Color = Color::rgba(0x55, 0x4D, 0x42, 1.0);
const LOOSE_STONE_OPACITY: f32 = 0.85;
const GRAVE_FILL: Color = Color::rgba(0x88, 0x80, 0x76, 1.0);
const GRAVE_INK: Color = Color::rgba(0x44, 0x40, 0x3A, 1.0);
const SIGN_POST: Color = Color::rgba(0x6B, 0x4F, 0x32, 1.0);
const SIGN_PLANK: Color = Color::rgba(0x8C, 0x66, 0x3A, 1.0);
const SIGN_INK: Color = Color::rgba(0x3A, 0x2A, 0x18, 1.0);
const MUSHROOM_STEM: Color = Color::rgba(0xE8, 0xDC, 0xC0, 1.0);
const MUSHROOM_CAP: Color = Color::rgba(0xB8, 0x44, 0x44, 1.0);
const MUSHROOM_DOT: Color = Color::rgba(0xF5, 0xEC, 0xC8, 1.0);
const MUSHROOM_PATCH_FILL: Color = Color::rgba(0x4A, 0x32, 0x1E, 1.0);
const MUSHROOM_PATCH_OPACITY: f32 = 0.25;
const GRAVE_PLOT_FILL: Color = Color::rgba(0x44, 0x36, 0x2A, 1.0);
const GRAVE_PLOT_OPACITY: f32 = 0.30;

/// Per-anchor RNG — keeps each anchor's sub-style variation
/// deterministic. Combines the FixtureOp's seed with the anchor's
/// (x, y) so anchors at different tiles diverge.
fn anchor_rng(seed: u64, x: i32, y: i32) -> Pcg64Mcg {
    let key = seed
        ^ ((x as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15))
        ^ ((y as u64).wrapping_mul(0xBF58_476D_1CE4_E5B9));
    Pcg64Mcg::seed_from_u64(key)
}

/// Resolve an anchor's pixel-space centre using the IR's sub-tile
/// offsets when present, falling back to ``tile-centre +
/// rng.gen_range(±jitter_radius)`` when both ``cx_off`` and
/// ``cy_off`` are zero (the back-compat sentinel — see
/// ``floor_ir.fbs::Anchor`` for the encoding contract).
///
/// The fallback path always advances the RNG by exactly two
/// `gen_range` draws regardless of the chosen branch, so any
/// downstream rng usage in the same painter sees the same rng
/// state whether or not the IR carries explicit offsets.
fn anchor_center_or_jitter(
    a: &Anchor,
    rng: &mut Pcg64Mcg,
    jitter_radius: f64,
) -> (f64, f64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let jx: f64 = rng.gen_range(-jitter_radius..jitter_radius);
    let jy: f64 = rng.gen_range(-jitter_radius..jitter_radius);
    if a.cx_off() != 0 || a.cy_off() != 0 {
        (
            px + CELL * f64::from(a.cx_off()) / 256.0,
            py + CELL * f64::from(a.cy_off()) / 256.0,
        )
    } else {
        (px + CELL * 0.5 + jx, py + CELL * 0.5 + jy)
    }
}

/// Web — radiating spokes from a corner + concentric ring threads.
/// ``orientation`` picks the corner (0=NW, 1=NE, 2=SE, 3=SW).
fn paint_web_anchor(painter: &mut dyn Painter, a: &Anchor, seed: u64) {
    let mut rng = anchor_rng(seed, a.x(), a.y());
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let corner = a.orientation() & 0x3;
    let cx = if corner == 0 || corner == 3 { px } else { px + CELL };
    let cy = if corner == 0 || corner == 1 { py } else { py + CELL };
    let sx: f64 = if corner == 0 || corner == 3 { 1.0 } else { -1.0 };
    let sy: f64 = if corner == 0 || corner == 1 { 1.0 } else { -1.0 };
    let n_radials: i32 = rng.gen_range(3..=4);
    let radial_len: f64 = rng.gen_range((CELL * 0.55)..(CELL * 0.85));
    let mut angles: Vec<f64> = (0..n_radials)
        .map(|_| rng.gen_range(0.05..(PI / 2.0 - 0.05)))
        .collect();
    angles.sort_by(|a, b| a.partial_cmp(b).unwrap());

    painter.begin_group(WEB_OPACITY);
    let stroke = Stroke {
        width: 0.4,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    let paint = Paint::solid(WEB_INK);

    let endpoints: Vec<(f64, f64)> = angles
        .iter()
        .map(|&a| (cx + sx * a.cos() * radial_len, cy + sy * a.sin() * radial_len))
        .collect();
    for &(ex, ey) in &endpoints {
        let mut path = PathOps::new();
        path.move_to(Vec2::new(cx as f32, cy as f32));
        path.line_to(Vec2::new(ex as f32, ey as f32));
        painter.stroke_path(&path, &paint, &stroke);
    }
    // Two ring-loop bands at 0.4 / 0.7 of radial_len.
    for ring_t in [0.4_f64, 0.7] {
        let mut path = PathOps::new();
        for (i, &(ex, ey)) in endpoints.iter().enumerate() {
            let dx = ex - cx;
            let dy = ey - cy;
            let rx = cx + dx * ring_t;
            let ry = cy + dy * ring_t;
            if i == 0 {
                path.move_to(Vec2::new(rx as f32, ry as f32));
            } else {
                path.line_to(Vec2::new(rx as f32, ry as f32));
            }
        }
        if endpoints.len() > 1 {
            painter.stroke_path(&path, &paint, &stroke);
        }
    }
    painter.end_group();
}

/// Skull — cranium circle + jaw + eye sockets. Variant rotates the
/// glyph slightly for visual variety; scale picks the size.
fn paint_skull_anchor(painter: &mut dyn Painter, a: &Anchor, seed: u64) {
    let mut rng = anchor_rng(seed, a.x(), a.y());
    let (cx, cy) = anchor_center_or_jitter(a, &mut rng, CELL * 0.10);
    let s: f64 = match a.scale() {
        0 => 1.0,
        1 => 0.85,
        2 => 1.15,
        _ => 1.0,
    };
    let cranium_r: f64 = CELL * 0.18 * s;
    let eye_r: f64 = CELL * 0.04 * s;
    let eye_dx: f64 = CELL * 0.07 * s;
    let eye_dy: f64 = CELL * 0.02 * s;
    let jaw_h: f64 = CELL * 0.10 * s;
    let jaw_w: f64 = CELL * 0.18 * s;

    painter.begin_group(SKULL_OPACITY);
    painter.fill_circle(
        cx as f32, cy as f32, cranium_r as f32,
        &Paint::solid(SKULL_FILL),
    );
    painter.fill_circle(
        (cx - eye_dx) as f32, (cy - eye_dy) as f32, eye_r as f32,
        &Paint::solid(SKULL_INK),
    );
    painter.fill_circle(
        (cx + eye_dx) as f32, (cy - eye_dy) as f32, eye_r as f32,
        &Paint::solid(SKULL_INK),
    );
    // Jaw — small filled rect under the cranium.
    let mut jaw = PathOps::new();
    let jx = cx - jaw_w * 0.5;
    let jy = cy + cranium_r * 0.6;
    jaw.move_to(Vec2::new(jx as f32, jy as f32));
    jaw.line_to(Vec2::new((jx + jaw_w) as f32, jy as f32));
    jaw.line_to(Vec2::new((jx + jaw_w) as f32, (jy + jaw_h) as f32));
    jaw.line_to(Vec2::new(jx as f32, (jy + jaw_h) as f32));
    jaw.close();
    painter.fill_path(&jaw, &Paint::solid(SKULL_FILL), FillRule::Winding);
    painter.end_group();
}

/// Bone — 2-3 stroked line segments crossing at the tile centre.
fn paint_bone_anchor(painter: &mut dyn Painter, a: &Anchor, seed: u64) {
    let mut rng = anchor_rng(seed, a.x(), a.y());
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let cy = py + CELL * 0.5;
    let n_bones = rng.gen_range(2..=3);

    painter.begin_group(BONE_OPACITY);
    let stroke = Stroke {
        width: 1.6,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    for _ in 0..n_bones {
        let angle: f64 = rng.gen_range(0.0..PI);
        let length: f64 = rng.gen_range((CELL * 0.20)..(CELL * 0.35));
        let dx = angle.cos() * length / 2.0;
        let dy = angle.sin() * length / 2.0;
        let bx = cx + rng.gen_range(-(CELL * 0.06)..(CELL * 0.06));
        let by = cy + rng.gen_range(-(CELL * 0.06)..(CELL * 0.06));
        let mut path = PathOps::new();
        path.move_to(Vec2::new((bx - dx) as f32, (by - dy) as f32));
        path.line_to(Vec2::new((bx + dx) as f32, (by + dy) as f32));
        painter.stroke_path(&path, &Paint::solid(BONE_FILL), &stroke);
        // Knuckle dots at each end.
        let er: f64 = rng.gen_range(1.4..1.9);
        painter.fill_circle(
            (bx - dx) as f32, (by - dy) as f32, er as f32,
            &Paint::solid(BONE_INK),
        );
        painter.fill_circle(
            (bx + dx) as f32, (by + dy) as f32, er as f32,
            &Paint::solid(BONE_INK),
        );
    }
    painter.end_group();
}

/// LooseStone — small cluster of 1-3 grey ellipses at sub-tile
/// positions. The cluster reads as a small rubble pile.
fn paint_loose_stone_anchor(painter: &mut dyn Painter, a: &Anchor, seed: u64) {
    let mut rng = anchor_rng(seed, a.x(), a.y());
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let n_stones = rng.gen_range(1..=3);

    painter.begin_group(LOOSE_STONE_OPACITY);
    for _ in 0..n_stones {
        let cx = px + rng.gen_range((CELL * 0.20)..(CELL * 0.80));
        let cy = py + rng.gen_range((CELL * 0.20)..(CELL * 0.80));
        let rx = rng.gen_range((CELL * 0.06)..(CELL * 0.11));
        let ry = rng.gen_range((CELL * 0.05)..(CELL * 0.09));
        painter.fill_ellipse(
            cx as f32, cy as f32, rx as f32, ry as f32,
            &Paint::solid(LOOSE_STONE_FILL),
        );
        // Thin ink outline for definition.
        let mut path = PathOps::new();
        let segs = 8;
        for i in 0..=segs {
            let theta = (i as f64) * (2.0 * PI) / (segs as f64);
            let ex = cx + rx * theta.cos();
            let ey = cy + ry * theta.sin();
            if i == 0 {
                path.move_to(Vec2::new(ex as f32, ey as f32));
            } else {
                path.line_to(Vec2::new(ex as f32, ey as f32));
            }
        }
        painter.stroke_path(
            &path,
            &Paint::solid(LOOSE_STONE_INK),
            &Stroke {
                width: 0.3,
                line_cap: LineCap::Round,
                line_join: LineJoin::Round,
            },
        );
    }
    painter.end_group();
}

/// Gravestone — tall slab silhouette with a curved top. Variant
/// picks the shape (0=slab, 1=cross, 2=celtic).
fn paint_gravestone_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let base_y = py + CELL * 0.85;
    let top_y = py + CELL * 0.20;
    let half_w: f64 = CELL * 0.18;

    let fill = Paint::solid(GRAVE_FILL);
    let ink = Paint::solid(GRAVE_INK);

    match a.variant() {
        1 => {
            // Cross — vertical bar + horizontal crossbar.
            let bar_w: f64 = CELL * 0.06;
            let mut v = PathOps::new();
            v.move_to(Vec2::new((cx - bar_w * 0.5) as f32, top_y as f32));
            v.line_to(Vec2::new((cx + bar_w * 0.5) as f32, top_y as f32));
            v.line_to(Vec2::new((cx + bar_w * 0.5) as f32, base_y as f32));
            v.line_to(Vec2::new((cx - bar_w * 0.5) as f32, base_y as f32));
            v.close();
            painter.fill_path(&v, &fill, FillRule::Winding);
            let bar_y = py + CELL * 0.38;
            let arm_w: f64 = CELL * 0.22;
            let mut h = PathOps::new();
            h.move_to(Vec2::new((cx - arm_w * 0.5) as f32, bar_y as f32));
            h.line_to(Vec2::new((cx + arm_w * 0.5) as f32, bar_y as f32));
            h.line_to(Vec2::new((cx + arm_w * 0.5) as f32, (bar_y + bar_w) as f32));
            h.line_to(Vec2::new((cx - arm_w * 0.5) as f32, (bar_y + bar_w) as f32));
            h.close();
            painter.fill_path(&h, &fill, FillRule::Winding);
        }
        2 => {
            // Celtic — slab with a circle at the top.
            let mut slab = PathOps::new();
            slab.move_to(Vec2::new((cx - half_w) as f32, (top_y + half_w) as f32));
            slab.line_to(Vec2::new((cx + half_w) as f32, (top_y + half_w) as f32));
            slab.line_to(Vec2::new((cx + half_w) as f32, base_y as f32));
            slab.line_to(Vec2::new((cx - half_w) as f32, base_y as f32));
            slab.close();
            painter.fill_path(&slab, &fill, FillRule::Winding);
            painter.fill_circle(
                cx as f32, top_y as f32, half_w as f32, &fill,
            );
            painter.stroke_path(
                &slab, &ink,
                &Stroke {
                    width: 0.4, line_cap: LineCap::Round,
                    line_join: LineJoin::Miter,
                },
            );
        }
        _ => {
            // Default slab — rounded-top headstone.
            let kappa: f64 = 0.5523;
            let r = half_w;
            let mut path = PathOps::new();
            path.move_to(Vec2::new((cx - half_w) as f32, base_y as f32));
            path.line_to(Vec2::new((cx - half_w) as f32, (top_y + r) as f32));
            // Top arc — top-left curve.
            path.cubic_to(
                Vec2::new((cx - half_w) as f32, (top_y + r - r * kappa) as f32),
                Vec2::new((cx - r + r * kappa) as f32, top_y as f32),
                Vec2::new(cx as f32, top_y as f32),
            );
            path.cubic_to(
                Vec2::new((cx + r - r * kappa) as f32, top_y as f32),
                Vec2::new((cx + half_w) as f32, (top_y + r - r * kappa) as f32),
                Vec2::new((cx + half_w) as f32, (top_y + r) as f32),
            );
            path.line_to(Vec2::new((cx + half_w) as f32, base_y as f32));
            path.close();
            painter.fill_path(&path, &fill, FillRule::Winding);
            painter.stroke_path(
                &path, &ink,
                &Stroke {
                    width: 0.4, line_cap: LineCap::Round,
                    line_join: LineJoin::Miter,
                },
            );
        }
    }
}

/// Sign — vertical post + horizontal plank near the top. Variant
/// 0 = post sign, 1 = billboard (wider plank, shorter post).
fn paint_sign_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let billboard = a.variant() == 1;
    let post_w: f64 = CELL * 0.06;
    let post_top = py + if billboard { CELL * 0.45 } else { CELL * 0.25 };
    let post_bot = py + CELL * 0.85;
    let plank_w: f64 = if billboard { CELL * 0.55 } else { CELL * 0.35 };
    let plank_h: f64 = CELL * 0.18;
    let plank_y = py + if billboard { CELL * 0.20 } else { CELL * 0.18 };

    let post_paint = Paint::solid(SIGN_POST);
    let plank_paint = Paint::solid(SIGN_PLANK);
    let ink = Paint::solid(SIGN_INK);

    let mut post = PathOps::new();
    post.move_to(Vec2::new((cx - post_w * 0.5) as f32, post_top as f32));
    post.line_to(Vec2::new((cx + post_w * 0.5) as f32, post_top as f32));
    post.line_to(Vec2::new((cx + post_w * 0.5) as f32, post_bot as f32));
    post.line_to(Vec2::new((cx - post_w * 0.5) as f32, post_bot as f32));
    post.close();
    painter.fill_path(&post, &post_paint, FillRule::Winding);

    let mut plank = PathOps::new();
    plank.move_to(Vec2::new((cx - plank_w * 0.5) as f32, plank_y as f32));
    plank.line_to(Vec2::new((cx + plank_w * 0.5) as f32, plank_y as f32));
    plank.line_to(Vec2::new((cx + plank_w * 0.5) as f32, (plank_y + plank_h) as f32));
    plank.line_to(Vec2::new((cx - plank_w * 0.5) as f32, (plank_y + plank_h) as f32));
    plank.close();
    painter.fill_path(&plank, &plank_paint, FillRule::Winding);
    painter.stroke_path(
        &plank, &ink,
        &Stroke {
            width: 0.4, line_cap: LineCap::Round,
            line_join: LineJoin::Miter,
        },
    );
}

/// Mushroom — stem + cap with a few cap-spots. Variant picks
/// the species; scale picks the size (0=small, 1=medium, 2=large).
fn paint_mushroom_anchor(painter: &mut dyn Painter, a: &Anchor, seed: u64) {
    let mut rng = anchor_rng(seed, a.x(), a.y());
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let s: f64 = match a.scale() {
        0 => 0.85,
        2 => 1.20,
        _ => 1.0,
    };
    let stem_h: f64 = CELL * 0.30 * s;
    let stem_w: f64 = CELL * 0.10 * s;
    let cap_rx: f64 = CELL * 0.20 * s;
    let cap_ry: f64 = CELL * 0.12 * s;
    let stem_top = py + CELL * 0.50;
    let stem_bot = stem_top + stem_h;
    let cap_cy = stem_top;

    // Stem rect.
    let mut stem = PathOps::new();
    stem.move_to(Vec2::new((cx - stem_w * 0.5) as f32, stem_top as f32));
    stem.line_to(Vec2::new((cx + stem_w * 0.5) as f32, stem_top as f32));
    stem.line_to(Vec2::new((cx + stem_w * 0.5) as f32, stem_bot as f32));
    stem.line_to(Vec2::new((cx - stem_w * 0.5) as f32, stem_bot as f32));
    stem.close();
    painter.fill_path(&stem, &Paint::solid(MUSHROOM_STEM), FillRule::Winding);

    // Cap — half ellipse via ellipse fill (the bottom half clips
    // visually under the stem so a full ellipse reads correctly).
    painter.fill_ellipse(
        cx as f32, cap_cy as f32, cap_rx as f32, cap_ry as f32,
        &Paint::solid(MUSHROOM_CAP),
    );
    // 2-3 cap spots.
    let n_dots = rng.gen_range(2..=3);
    for _ in 0..n_dots {
        let dx = rng.gen_range(-(cap_rx * 0.6)..(cap_rx * 0.6));
        let dy = rng.gen_range(-(cap_ry * 0.5)..0.0);
        let dr = rng.gen_range(0.8..1.4);
        painter.fill_circle(
            (cx + dx) as f32, (cap_cy + dy) as f32, dr as f32,
            &Paint::solid(MUSHROOM_DOT),
        );
    }
}

/// Mushroom cluster — shared mycelium patch under cluster members.
/// One soft elliptical halo per member tile, all wrapped in a
/// `begin_group(0.25)` envelope so the patch composites as a unified
/// dark mat without per-member darken stacking. The patch sits
/// slightly below the stem base of each member.
fn paint_mushroom_cluster_patch(
    painter: &mut dyn Painter, cluster: &[(i32, i32)],
) {
    if cluster.is_empty() {
        return;
    }
    painter.begin_group(MUSHROOM_PATCH_OPACITY);
    let paint = Paint::solid(MUSHROOM_PATCH_FILL);
    for &(tx, ty) in cluster {
        let cx = (f64::from(tx) + 0.5) * CELL;
        let cy = (f64::from(ty) + 0.5) * CELL + CELL * 0.30;
        painter.fill_ellipse(
            cx as f32, cy as f32,
            (CELL * 0.32) as f32, (CELL * 0.10) as f32,
            &paint,
        );
    }
    painter.end_group();
}

/// Gravestone cluster — shared dirt-plot under cluster members.
/// Bounding rect over the cluster's tile footprint with small inner
/// padding, painted under a `begin_group(0.30)` envelope so the
/// plot reads as one darker patch of disturbed earth. The plot
/// starts mid-tile (where the gravestone slab anchors) so it
/// doesn't bleed into adjacent tiles above the cluster.
fn paint_gravestone_cluster_plot(
    painter: &mut dyn Painter, cluster: &[(i32, i32)],
) {
    if cluster.is_empty() {
        return;
    }
    let min_x = cluster.iter().map(|&(x, _)| x).min().unwrap();
    let max_x = cluster.iter().map(|&(x, _)| x).max().unwrap();
    let min_y = cluster.iter().map(|&(_, y)| y).min().unwrap();
    let max_y = cluster.iter().map(|&(_, y)| y).max().unwrap();
    let pad = CELL * 0.10;
    let x0 = f64::from(min_x) * CELL - pad;
    let y0 = f64::from(min_y) * CELL + CELL * 0.40;
    let x1 = f64::from(max_x + 1) * CELL + pad;
    let y1 = f64::from(max_y + 1) * CELL - pad;

    painter.begin_group(GRAVE_PLOT_OPACITY);
    let mut path = PathOps::new();
    path.move_to(Vec2::new(x0 as f32, y0 as f32));
    path.line_to(Vec2::new(x1 as f32, y0 as f32));
    path.line_to(Vec2::new(x1 as f32, y1 as f32));
    path.line_to(Vec2::new(x0 as f32, y1 as f32));
    path.close();
    painter.fill_path(
        &path, &Paint::solid(GRAVE_PLOT_FILL), FillRule::Winding,
    );
    painter.end_group();
}

// ── Post-Phase-5 deferred-polish per-anchor painters ───────────
//
// Twelve new ``FixtureKind`` variants. Each painter is RNG-free
// and takes a single anchor + the FixtureOp seed (currently
// unused — kept on the signature so per-anchor jitter can land
// without re-threading the dispatcher). Variants drive small
// stylistic tweaks (e.g. ``Chest`` open / closed) where useful.

const CHEST_BODY: Color = Color::rgba(0x6B, 0x47, 0x28, 1.0);
const CHEST_LID: Color = Color::rgba(0x4A, 0x32, 0x1C, 1.0);
const CHEST_BAND: Color = Color::rgba(0x32, 0x24, 0x14, 1.0);
const CHEST_LOCK: Color = Color::rgba(0xC8, 0xB0, 0x40, 1.0);

/// Chest — wooden coffer with two iron bands and a brass lock
/// in the middle. ``variant == 1`` paints the lid raised by a
/// small angle (open chest).
fn paint_chest_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let body_x0 = px + CELL * 0.18;
    let body_x1 = px + CELL * 0.82;
    let body_y0 = py + CELL * 0.45;
    let body_y1 = py + CELL * 0.85;
    let lid_y0 = py + CELL * 0.30;
    let lid_y1 = body_y0;
    rect_fill(painter, body_x0, body_y0, body_x1, body_y1, CHEST_BODY);
    rect_fill(painter, body_x0, lid_y0, body_x1, lid_y1, CHEST_LID);
    // Two iron bands across the body.
    let band_w = CELL * 0.04;
    let b1_x = px + CELL * 0.30;
    let b2_x = px + CELL * 0.62;
    rect_fill(painter, b1_x, body_y0, b1_x + band_w, body_y1, CHEST_BAND);
    rect_fill(painter, b2_x, body_y0, b2_x + band_w, body_y1, CHEST_BAND);
    // Brass lock at the lid / body seam centre.
    painter.fill_circle(
        ((body_x0 + body_x1) * 0.5) as f32, body_y0 as f32,
        (CELL * 0.06) as f32,
        &Paint::solid(CHEST_LOCK),
    );
    if a.variant() == 1 {
        // Open lid — small triangular wedge above the body to
        // suggest the lid raised forward.
        let mut wedge = PathOps::new();
        wedge.move_to(Vec2::new(body_x0 as f32, lid_y0 as f32));
        wedge.line_to(Vec2::new(body_x1 as f32, lid_y0 as f32));
        wedge.line_to(Vec2::new(
            ((body_x0 + body_x1) * 0.5) as f32,
            (lid_y0 - CELL * 0.10) as f32,
        ));
        wedge.close();
        painter.fill_path(&wedge, &Paint::solid(CHEST_LID), FillRule::Winding);
    }
}

const CRATE_BODY: Color = Color::rgba(0x8B, 0x6A, 0x42, 1.0);
const CRATE_BRACE: Color = Color::rgba(0x4F, 0x36, 0x1E, 1.0);

/// Crate — square wooden box with diagonal cross-bracing on the
/// front face, suggesting reinforced shipping construction.
fn paint_crate_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let x0 = px + CELL * 0.20;
    let x1 = px + CELL * 0.80;
    let y0 = py + CELL * 0.25;
    let y1 = py + CELL * 0.85;
    rect_fill(painter, x0, y0, x1, y1, CRATE_BODY);
    let brace = Stroke {
        width: 1.4, line_cap: LineCap::Round, line_join: LineJoin::Miter,
    };
    let brace_paint = Paint::solid(CRATE_BRACE);
    let mut diag = PathOps::new();
    diag.move_to(Vec2::new(x0 as f32, y0 as f32));
    diag.line_to(Vec2::new(x1 as f32, y1 as f32));
    painter.stroke_path(&diag, &brace_paint, &brace);
    let mut anti = PathOps::new();
    anti.move_to(Vec2::new(x1 as f32, y0 as f32));
    anti.line_to(Vec2::new(x0 as f32, y1 as f32));
    painter.stroke_path(&anti, &brace_paint, &brace);
    let mut frame = PathOps::new();
    frame.move_to(Vec2::new(x0 as f32, y0 as f32));
    frame.line_to(Vec2::new(x1 as f32, y0 as f32));
    frame.line_to(Vec2::new(x1 as f32, y1 as f32));
    frame.line_to(Vec2::new(x0 as f32, y1 as f32));
    frame.close();
    painter.stroke_path(&frame, &brace_paint, &brace);
}

const BARREL_BODY: Color = Color::rgba(0x7A, 0x55, 0x30, 1.0);
const BARREL_HOOP: Color = Color::rgba(0x3A, 0x28, 0x14, 1.0);

/// Barrel — vertical oval body with three iron hoops at the
/// top, middle, and bottom.
fn paint_barrel_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let cy = py + CELL * 0.55;
    let rx = CELL * 0.27;
    let ry = CELL * 0.32;
    painter.fill_ellipse(
        cx as f32, cy as f32, rx as f32, ry as f32,
        &Paint::solid(BARREL_BODY),
    );
    let hoop_paint = Paint::solid(BARREL_HOOP);
    for offset in [-0.65_f64, 0.0, 0.65] {
        let hy = cy + ry * offset;
        let hx_half = (rx * rx * (1.0 - offset * offset)).sqrt();
        let mut hoop = PathOps::new();
        hoop.move_to(Vec2::new((cx - hx_half) as f32, hy as f32));
        hoop.line_to(Vec2::new((cx + hx_half) as f32, hy as f32));
        painter.stroke_path(
            &hoop, &hoop_paint,
            &Stroke {
                width: 1.2, line_cap: LineCap::Butt, line_join: LineJoin::Miter,
            },
        );
    }
}

const ALTAR_STONE: Color = Color::rgba(0x9C, 0x9C, 0x9C, 1.0);
const ALTAR_TOP: Color = Color::rgba(0xC8, 0xC8, 0xC8, 1.0);
const ALTAR_INK: Color = Color::rgba(0x4F, 0x4F, 0x4F, 1.0);

/// Altar — short stone slab with a raised top plate. ``variant
/// == 1`` adds a small dark blood smear on the top to suggest a
/// sacrificial altar.
fn paint_altar_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let body_x0 = px + CELL * 0.22;
    let body_x1 = px + CELL * 0.78;
    let body_y0 = py + CELL * 0.50;
    let body_y1 = py + CELL * 0.85;
    let top_x0 = px + CELL * 0.16;
    let top_x1 = px + CELL * 0.84;
    let top_y0 = py + CELL * 0.42;
    let top_y1 = body_y0;
    rect_fill(painter, body_x0, body_y0, body_x1, body_y1, ALTAR_STONE);
    rect_fill(painter, top_x0, top_y0, top_x1, top_y1, ALTAR_TOP);
    if a.variant() == 1 {
        let stain = Color::rgba(0x66, 0x10, 0x10, 1.0);
        painter.fill_ellipse(
            ((top_x0 + top_x1) * 0.5) as f32,
            ((top_y0 + top_y1) * 0.5) as f32,
            (CELL * 0.10) as f32, (CELL * 0.04) as f32,
            &Paint::solid(stain),
        );
    }
    // Thin shadow line under the top.
    let mut sep = PathOps::new();
    sep.move_to(Vec2::new(top_x0 as f32, top_y1 as f32));
    sep.line_to(Vec2::new(top_x1 as f32, top_y1 as f32));
    painter.stroke_path(
        &sep, &Paint::solid(ALTAR_INK),
        &Stroke {
            width: 0.6, line_cap: LineCap::Butt, line_join: LineJoin::Miter,
        },
    );
}

const BRAZIER_BOWL: Color = Color::rgba(0x4F, 0x33, 0x18, 1.0);
const BRAZIER_RIM: Color = Color::rgba(0x2A, 0x1C, 0x10, 1.0);
const BRAZIER_FLAME: Color = Color::rgba(0xFF, 0x9A, 0x30, 1.0);
const BRAZIER_FLAME_CORE: Color = Color::rgba(0xFF, 0xE0, 0x60, 1.0);

/// Brazier — small footed bowl with a flickering flame above.
fn paint_brazier_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let bowl_cy = py + CELL * 0.65;
    let bowl_rx = CELL * 0.22;
    let bowl_ry = CELL * 0.10;
    // Foot — short rect under the bowl.
    rect_fill(painter,
        cx - CELL * 0.08, bowl_cy + bowl_ry,
        cx + CELL * 0.08, py + CELL * 0.85,
        BRAZIER_BOWL,
    );
    // Bowl — wide ellipse.
    painter.fill_ellipse(
        cx as f32, bowl_cy as f32,
        bowl_rx as f32, bowl_ry as f32,
        &Paint::solid(BRAZIER_BOWL),
    );
    // Bowl rim — darker thin ellipse on top.
    painter.fill_ellipse(
        cx as f32, (bowl_cy - bowl_ry * 0.6) as f32,
        bowl_rx as f32, (bowl_ry * 0.4) as f32,
        &Paint::solid(BRAZIER_RIM),
    );
    // Flame — orange teardrop + brighter core.
    let mut flame = PathOps::new();
    let base_y = bowl_cy - bowl_ry * 0.6;
    flame.move_to(Vec2::new(
        (cx - CELL * 0.12) as f32, base_y as f32,
    ));
    flame.quad_to(
        Vec2::new(cx as f32, (base_y - CELL * 0.25) as f32),
        Vec2::new(cx as f32, (base_y - CELL * 0.32) as f32),
    );
    flame.quad_to(
        Vec2::new(cx as f32, (base_y - CELL * 0.25) as f32),
        Vec2::new((cx + CELL * 0.12) as f32, base_y as f32),
    );
    flame.close();
    painter.fill_path(&flame, &Paint::solid(BRAZIER_FLAME), FillRule::Winding);
    painter.fill_ellipse(
        cx as f32, (base_y - CELL * 0.10) as f32,
        (CELL * 0.04) as f32, (CELL * 0.10) as f32,
        &Paint::solid(BRAZIER_FLAME_CORE),
    );
}

const STATUE_STONE: Color = Color::rgba(0xB0, 0xAC, 0xA0, 1.0);
const STATUE_INK: Color = Color::rgba(0x55, 0x52, 0x4A, 1.0);

/// Statue — humanoid silhouette on a small base. Body is a
/// vertical capsule + circular head.
fn paint_statue_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let base_y = py + CELL * 0.85;
    let base_x0 = cx - CELL * 0.25;
    let base_x1 = cx + CELL * 0.25;
    rect_fill(painter,
        base_x0, base_y - CELL * 0.06, base_x1, base_y,
        STATUE_INK,
    );
    // Body — vertical pill.
    let body_x0 = cx - CELL * 0.10;
    let body_x1 = cx + CELL * 0.10;
    let body_y0 = py + CELL * 0.30;
    let body_y1 = base_y - CELL * 0.06;
    rect_fill(painter, body_x0, body_y0, body_x1, body_y1, STATUE_STONE);
    // Head — circle above the body.
    painter.fill_circle(
        cx as f32, (body_y0 - CELL * 0.06) as f32,
        (CELL * 0.10) as f32,
        &Paint::solid(STATUE_STONE),
    );
}

const PILLAR_STONE: Color = Color::rgba(0xC4, 0xBE, 0xA8, 1.0);
const PILLAR_DARK: Color = Color::rgba(0x88, 0x82, 0x70, 1.0);

/// Pillar — round column with a small base and capital plate.
fn paint_pillar_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let base_y = py + CELL * 0.82;
    let cap_y = py + CELL * 0.20;
    let col_x0 = cx - CELL * 0.10;
    let col_x1 = cx + CELL * 0.10;
    rect_fill(painter, col_x0, cap_y, col_x1, base_y, PILLAR_STONE);
    // Capital plate — wider rect at top.
    let plate_x0 = cx - CELL * 0.18;
    let plate_x1 = cx + CELL * 0.18;
    rect_fill(painter, plate_x0, cap_y - CELL * 0.06, plate_x1, cap_y, PILLAR_DARK);
    // Base plate — wider rect at bottom.
    rect_fill(painter, plate_x0, base_y, plate_x1, base_y + CELL * 0.06, PILLAR_DARK);
}

const PEDESTAL_STONE: Color = Color::rgba(0xA8, 0xA0, 0x88, 1.0);
const PEDESTAL_TOP: Color = Color::rgba(0xC8, 0xC0, 0xA8, 1.0);

/// Pedestal — short circular plinth, top plate raised.
fn paint_pedestal_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let base_cy = py + CELL * 0.72;
    let body_rx = CELL * 0.20;
    let body_ry = CELL * 0.08;
    painter.fill_ellipse(
        cx as f32, base_cy as f32,
        body_rx as f32, body_ry as f32,
        &Paint::solid(PEDESTAL_STONE),
    );
    rect_fill(painter,
        cx - body_rx, base_cy - CELL * 0.20,
        cx + body_rx, base_cy,
        PEDESTAL_STONE,
    );
    let top_cy = base_cy - CELL * 0.20;
    painter.fill_ellipse(
        cx as f32, top_cy as f32,
        body_rx as f32, body_ry as f32,
        &Paint::solid(PEDESTAL_TOP),
    );
}

const LADDER_RAIL: Color = Color::rgba(0x6B, 0x47, 0x28, 1.0);

/// Ladder — two vertical rails + 4 horizontal rungs.
fn paint_ladder_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let rail_x_l = cx - CELL * 0.16;
    let rail_x_r = cx + CELL * 0.16;
    let top_y = py + CELL * 0.15;
    let bot_y = py + CELL * 0.85;
    let rail_w = CELL * 0.04;
    rect_fill(painter,
        rail_x_l - rail_w * 0.5, top_y, rail_x_l + rail_w * 0.5, bot_y,
        LADDER_RAIL,
    );
    rect_fill(painter,
        rail_x_r - rail_w * 0.5, top_y, rail_x_r + rail_w * 0.5, bot_y,
        LADDER_RAIL,
    );
    let rung_h = CELL * 0.04;
    for i in 0..4 {
        let t = (i as f64 + 0.5) / 4.0;
        let ry = top_y + (bot_y - top_y) * t;
        rect_fill(painter,
            rail_x_l, ry - rung_h * 0.5, rail_x_r, ry + rung_h * 0.5,
            LADDER_RAIL,
        );
    }
}

const TRAPDOOR_PLANK: Color = Color::rgba(0x6B, 0x47, 0x28, 1.0);
const TRAPDOOR_OUTLINE: Color = Color::rgba(0x32, 0x24, 0x14, 1.0);
const TRAPDOOR_HINGE: Color = Color::rgba(0x4F, 0x4F, 0x4F, 1.0);

/// Trapdoor — square wooden hatch with a diagonal brace and a
/// circular hinge / handle dot.
fn paint_trapdoor_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let x0 = px + CELL * 0.25;
    let x1 = px + CELL * 0.75;
    let y0 = py + CELL * 0.25;
    let y1 = py + CELL * 0.75;
    rect_fill(painter, x0, y0, x1, y1, TRAPDOOR_PLANK);
    let outline = Stroke {
        width: 1.0, line_cap: LineCap::Butt, line_join: LineJoin::Miter,
    };
    let outline_paint = Paint::solid(TRAPDOOR_OUTLINE);
    let mut frame = PathOps::new();
    frame.move_to(Vec2::new(x0 as f32, y0 as f32));
    frame.line_to(Vec2::new(x1 as f32, y0 as f32));
    frame.line_to(Vec2::new(x1 as f32, y1 as f32));
    frame.line_to(Vec2::new(x0 as f32, y1 as f32));
    frame.close();
    painter.stroke_path(&frame, &outline_paint, &outline);
    let mut diag = PathOps::new();
    diag.move_to(Vec2::new(x0 as f32, y0 as f32));
    diag.line_to(Vec2::new(x1 as f32, y1 as f32));
    painter.stroke_path(&diag, &outline_paint, &outline);
    // Hinge dot at top-left, handle at bottom-right.
    painter.fill_circle(
        (x0 + CELL * 0.04) as f32, (y0 + CELL * 0.04) as f32,
        (CELL * 0.025) as f32,
        &Paint::solid(TRAPDOOR_HINGE),
    );
    painter.fill_circle(
        (x1 - CELL * 0.04) as f32, (y1 - CELL * 0.04) as f32,
        (CELL * 0.025) as f32,
        &Paint::solid(TRAPDOOR_HINGE),
    );
}

const FOOTPRINT_INK: Color = Color::rgba(0x4A, 0x35, 0x25, 1.0);

/// Footprint fixture — single boot-shape stamp at the anchor
/// (sole + heel ellipses). Distinct from the per-tile-decorator
/// ``Footprints`` bit by being a one-shot fixture rather than a
/// scattered density.
fn paint_footprint_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let cy = py + CELL * 0.5;
    let fill = Paint::solid(FOOTPRINT_INK);
    painter.fill_ellipse(
        cx as f32, cy as f32,
        (CELL * 0.10) as f32, (CELL * 0.18) as f32,
        &fill,
    );
    painter.fill_ellipse(
        cx as f32, (cy + CELL * 0.13) as f32,
        (CELL * 0.07) as f32, (CELL * 0.05) as f32,
        &fill,
    );
}

const CHALK_INK: Color = Color::rgba(0xF0, 0xF0, 0xE8, 1.0);

/// ChalkCircle — pale chalk ring with a few inscribed marks
/// (radial dashes) inside; reads as an arcane summoning circle.
fn paint_chalk_circle_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5;
    let cy = py + CELL * 0.5;
    let r_outer = CELL * 0.36;
    let r_inner = CELL * 0.28;
    let stroke = Stroke {
        width: 0.9, line_cap: LineCap::Round, line_join: LineJoin::Round,
    };
    let paint = Paint::solid(CHALK_INK);
    // Outer + inner rings — sample 32 segments for a smooth circle.
    for radius in [r_outer, r_inner] {
        let mut path = PathOps::new();
        let n = 32;
        for i in 0..=n {
            let theta = (i as f64) * 2.0 * PI / (n as f64);
            let pxx = cx + radius * theta.cos();
            let pyy = cy + radius * theta.sin();
            if i == 0 {
                path.move_to(Vec2::new(pxx as f32, pyy as f32));
            } else {
                path.line_to(Vec2::new(pxx as f32, pyy as f32));
            }
        }
        painter.stroke_path(&path, &paint, &stroke);
    }
    // Six radial inscribed dashes between the rings.
    for i in 0..6 {
        let theta = (i as f64) * PI / 3.0;
        let mut dash = PathOps::new();
        dash.move_to(Vec2::new(
            (cx + r_inner * theta.cos()) as f32,
            (cy + r_inner * theta.sin()) as f32,
        ));
        dash.line_to(Vec2::new(
            (cx + r_outer * theta.cos()) as f32,
            (cy + r_outer * theta.sin()) as f32,
        ));
        painter.stroke_path(&dash, &paint, &stroke);
    }
}

// ── Farm animals — top-down silhouettes ───────────────────────
//
// Each painter draws the animal viewed from above: oval body
// (length along the +x axis), small accent shapes (head /
// horns / mane / tail / ears / etc.) at characteristic
// positions. RNG-free; ``variant`` reserved on the signature
// for future per-individual colour variation but not yet
// consumed.

const COW_HIDE: Color = Color::rgba(0x8C, 0x6F, 0x4F, 1.0);
const COW_SPOT: Color = Color::rgba(0xF0, 0xEC, 0xE0, 1.0);
const COW_DARK: Color = Color::rgba(0x4A, 0x36, 0x22, 1.0);

/// Cow — large brown oval body with two pale hide spots and a
/// small dark head extension at the front (+x).
fn paint_cow_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let cx = f64::from(a.x()) * CELL + CELL * 0.5;
    let cy = f64::from(a.y()) * CELL + CELL * 0.5;
    let body_rx = CELL * 0.30;
    let body_ry = CELL * 0.18;
    painter.fill_ellipse(
        cx as f32, cy as f32,
        body_rx as f32, body_ry as f32,
        &Paint::solid(COW_HIDE),
    );
    // Two pale hide patches.
    painter.fill_ellipse(
        (cx - CELL * 0.10) as f32, (cy - CELL * 0.04) as f32,
        (CELL * 0.07) as f32, (CELL * 0.05) as f32,
        &Paint::solid(COW_SPOT),
    );
    painter.fill_ellipse(
        (cx + CELL * 0.06) as f32, (cy + CELL * 0.06) as f32,
        (CELL * 0.06) as f32, (CELL * 0.04) as f32,
        &Paint::solid(COW_SPOT),
    );
    // Head — small dark ellipse off the front (+x) end.
    painter.fill_ellipse(
        (cx + body_rx * 0.85) as f32, cy as f32,
        (CELL * 0.07) as f32, (CELL * 0.08) as f32,
        &Paint::solid(COW_DARK),
    );
}

const SHEEP_FLEECE: Color = Color::rgba(0xF0, 0xEC, 0xDC, 1.0);
const SHEEP_FACE: Color = Color::rgba(0x42, 0x36, 0x2A, 1.0);

/// Sheep — round white-fleece body with a small dark face poking
/// out the front. Top-down silhouette.
fn paint_sheep_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let cx = f64::from(a.x()) * CELL + CELL * 0.5;
    let cy = f64::from(a.y()) * CELL + CELL * 0.5;
    let body_r = CELL * 0.20;
    painter.fill_circle(
        cx as f32, cy as f32, body_r as f32,
        &Paint::solid(SHEEP_FLEECE),
    );
    painter.fill_circle(
        (cx + body_r * 0.85) as f32, cy as f32,
        (CELL * 0.06) as f32,
        &Paint::solid(SHEEP_FACE),
    );
}

const PIG_BODY: Color = Color::rgba(0xE8, 0xA8, 0x9C, 1.0);
const PIG_SNOUT: Color = Color::rgba(0xC8, 0x80, 0x70, 1.0);

/// Pig — pink oval body with a darker snout dot at the front
/// and a curly-tail dot at the back.
fn paint_pig_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let cx = f64::from(a.x()) * CELL + CELL * 0.5;
    let cy = f64::from(a.y()) * CELL + CELL * 0.5;
    let body_rx = CELL * 0.26;
    let body_ry = CELL * 0.17;
    painter.fill_ellipse(
        cx as f32, cy as f32,
        body_rx as f32, body_ry as f32,
        &Paint::solid(PIG_BODY),
    );
    // Snout — small darker dot at +x.
    painter.fill_circle(
        (cx + body_rx * 0.95) as f32, cy as f32,
        (CELL * 0.04) as f32,
        &Paint::solid(PIG_SNOUT),
    );
    // Curly tail — tiny dot at -x.
    painter.fill_circle(
        (cx - body_rx * 0.95) as f32, cy as f32,
        (CELL * 0.025) as f32,
        &Paint::solid(PIG_SNOUT),
    );
}

const CHICKEN_FEATHERS: Color = Color::rgba(0xE6, 0xC8, 0x88, 1.0);
const CHICKEN_BEAK: Color = Color::rgba(0xE0, 0x90, 0x30, 1.0);
const CHICKEN_COMB: Color = Color::rgba(0xC8, 0x30, 0x30, 1.0);

/// Chicken — small round buff body with an orange beak and a
/// red comb dot. Smaller than sheep / pig; reads as poultry at
/// tile scale.
fn paint_chicken_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let cx = f64::from(a.x()) * CELL + CELL * 0.5;
    let cy = f64::from(a.y()) * CELL + CELL * 0.5;
    let body_r = CELL * 0.13;
    painter.fill_circle(
        cx as f32, cy as f32, body_r as f32,
        &Paint::solid(CHICKEN_FEATHERS),
    );
    // Comb — small red dot above the head.
    painter.fill_circle(
        (cx + body_r * 0.6) as f32, (cy - body_r * 0.6) as f32,
        (CELL * 0.025) as f32,
        &Paint::solid(CHICKEN_COMB),
    );
    // Beak — small triangle / dot at +x.
    painter.fill_circle(
        (cx + body_r * 1.10) as f32, cy as f32,
        (CELL * 0.022) as f32,
        &Paint::solid(CHICKEN_BEAK),
    );
}

const GOAT_HIDE: Color = Color::rgba(0x9C, 0x88, 0x70, 1.0);
const GOAT_HORN: Color = Color::rgba(0x32, 0x28, 0x1A, 1.0);

/// Goat — gray-brown body with two small dark horn dabs at the
/// head and a small beard dot beneath.
fn paint_goat_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let cx = f64::from(a.x()) * CELL + CELL * 0.5;
    let cy = f64::from(a.y()) * CELL + CELL * 0.5;
    let body_rx = CELL * 0.24;
    let body_ry = CELL * 0.15;
    painter.fill_ellipse(
        cx as f32, cy as f32,
        body_rx as f32, body_ry as f32,
        &Paint::solid(GOAT_HIDE),
    );
    let head_x = cx + body_rx * 0.90;
    // Horns — two small darker dots above the head.
    painter.fill_circle(
        head_x as f32, (cy - body_ry * 0.55) as f32,
        (CELL * 0.025) as f32,
        &Paint::solid(GOAT_HORN),
    );
    painter.fill_circle(
        (head_x + CELL * 0.04) as f32, (cy - body_ry * 0.40) as f32,
        (CELL * 0.025) as f32,
        &Paint::solid(GOAT_HORN),
    );
    // Beard — small dot below the head.
    painter.fill_circle(
        head_x as f32, (cy + body_ry * 0.55) as f32,
        (CELL * 0.025) as f32,
        &Paint::solid(GOAT_HORN),
    );
}

const HORSE_COAT: Color = Color::rgba(0x6B, 0x47, 0x2A, 1.0);
const HORSE_MANE: Color = Color::rgba(0x32, 0x22, 0x14, 1.0);

/// Horse — long oval body with a darker mane stripe along the
/// back (the long axis) and a small tail dot at the rear.
fn paint_horse_anchor(painter: &mut dyn Painter, a: &Anchor, _seed: u64) {
    let cx = f64::from(a.x()) * CELL + CELL * 0.5;
    let cy = f64::from(a.y()) * CELL + CELL * 0.5;
    let body_rx = CELL * 0.34;
    let body_ry = CELL * 0.14;
    painter.fill_ellipse(
        cx as f32, cy as f32,
        body_rx as f32, body_ry as f32,
        &Paint::solid(HORSE_COAT),
    );
    // Mane — narrower darker ellipse offset slightly above the
    // body's long axis to read as a top-edge mane line.
    painter.fill_ellipse(
        cx as f32, (cy - body_ry * 0.45) as f32,
        (body_rx * 0.65) as f32, (body_ry * 0.30) as f32,
        &Paint::solid(HORSE_MANE),
    );
    // Tail — small dab at the rear (-x end).
    painter.fill_circle(
        (cx - body_rx * 1.05) as f32, cy as f32,
        (CELL * 0.040) as f32,
        &Paint::solid(HORSE_MANE),
    );
}

/// Convenience axis-aligned rectangle fill via fill_path. Used
/// by the per-anchor painters above instead of fill_rect so the
/// SVG painter renders a single ``<path>`` rather than mixing
/// ``<rect>`` + ``<path>`` elements in the same fixture.
fn rect_fill(
    painter: &mut dyn Painter,
    x0: f64, y0: f64, x1: f64, y1: f64,
    color: Color,
) {
    let mut path = PathOps::new();
    path.move_to(Vec2::new(x0 as f32, y0 as f32));
    path.line_to(Vec2::new(x1 as f32, y0 as f32));
    path.line_to(Vec2::new(x1 as f32, y1 as f32));
    path.line_to(Vec2::new(x0 as f32, y1 as f32));
    path.close();
    painter.fill_path(&path, &Paint::solid(color), FillRule::Winding);
}

fn collect_tiles(anchors: &Vector<'_, Anchor>) -> Vec<(i32, i32)> {
    (0..anchors.len())
        .map(|i| {
            let a = anchors.get(i);
            (a.x(), a.y())
        })
        .collect()
}

/// Group anchors by `group_id` for fusion-supporting kinds (Tree,
/// Mushroom, Gravestone). Returns `(free, groves)`: free are
/// anchors with `group_id = 0` (standalone), groves are the lists
/// of `(x, y)` tile coords keyed by `group_id`.
fn split_by_group(anchors: &Vector<'_, Anchor>) -> (Vec<(i32, i32)>, Vec<Vec<(i32, i32)>>) {
    let mut free = Vec::new();
    let mut groups: BTreeMap<u16, Vec<(i32, i32)>> = BTreeMap::new();
    for i in 0..anchors.len() {
        let a = anchors.get(i);
        if a.group_id() == 0 {
            free.push((a.x(), a.y()));
        } else {
            groups.entry(a.group_id()).or_default().push((a.x(), a.y()));
        }
    }
    (free, groups.into_values().collect())
}

pub fn draw<'a>(
    op: FixtureOp<'a>,
    _regions: Vector<'a, ForwardsUOffset<Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let anchors = match op.anchors() {
        Some(a) if !a.is_empty() => a,
        _ => return false,
    };
    let kind = op.kind();
    match kind {
        FixtureKind::Tree => {
            let (free, groves) = split_by_group(&anchors);
            paint_tree(painter, &free, &groves);
        }
        FixtureKind::Bush => {
            let tiles = collect_tiles(&anchors);
            paint_bush(painter, &tiles);
        }
        FixtureKind::Well => {
            // ``Anchor.variant`` carries the well shape (round / square).
            // Group anchors by variant since the v4 painter wants a
            // homogeneous tile list per shape.
            let mut by_variant: BTreeMap<u8, Vec<(i32, i32)>> = BTreeMap::new();
            for i in 0..anchors.len() {
                let a = anchors.get(i);
                by_variant.entry(a.variant()).or_default().push((a.x(), a.y()));
            }
            for (variant, tiles) in by_variant {
                paint_well(painter, &tiles, variant);
            }
        }
        FixtureKind::Fountain => {
            let mut by_variant: BTreeMap<u8, Vec<(i32, i32)>> = BTreeMap::new();
            for i in 0..anchors.len() {
                let a = anchors.get(i);
                by_variant.entry(a.variant()).or_default().push((a.x(), a.y()));
            }
            for (variant, tiles) in by_variant {
                paint_fountain(painter, &tiles, variant);
            }
        }
        FixtureKind::Stair => {
            // Anchor.orientation carries the direction (0=up, 1=down)
            // per design/map_ir_v5.md §7. Theme + fill colour default
            // to the v4 dungeon palette here; cave-stair styling
            // returns when the painter takes a substance reference
            // (deferred until Phase 3.1's PSNR gate flags it).
            let stairs: Vec<(i32, i32, u8)> = (0..anchors.len())
                .map(|i| {
                    let a = anchors.get(i);
                    (a.x(), a.y(), a.orientation())
                })
                .collect();
            paint_stairs(painter, &stairs, "dungeon", "#FFFFFF");
        }
        FixtureKind::Web => {
            for i in 0..anchors.len() {
                paint_web_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Skull => {
            for i in 0..anchors.len() {
                paint_skull_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Bone => {
            for i in 0..anchors.len() {
                paint_bone_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::LooseStone => {
            for i in 0..anchors.len() {
                paint_loose_stone_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Gravestone => {
            let (_free, clusters) = split_by_group(&anchors);
            for cluster in &clusters {
                paint_gravestone_cluster_plot(painter, cluster);
            }
            for i in 0..anchors.len() {
                paint_gravestone_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Sign => {
            for i in 0..anchors.len() {
                paint_sign_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Mushroom => {
            let (_free, clusters) = split_by_group(&anchors);
            for cluster in &clusters {
                paint_mushroom_cluster_patch(painter, cluster);
            }
            for i in 0..anchors.len() {
                paint_mushroom_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        // Post-Phase-5 deferred-polish kinds.
        FixtureKind::Chest => {
            for i in 0..anchors.len() {
                paint_chest_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Crate => {
            for i in 0..anchors.len() {
                paint_crate_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Barrel => {
            for i in 0..anchors.len() {
                paint_barrel_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Altar => {
            for i in 0..anchors.len() {
                paint_altar_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Brazier => {
            for i in 0..anchors.len() {
                paint_brazier_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Statue => {
            for i in 0..anchors.len() {
                paint_statue_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Pillar => {
            for i in 0..anchors.len() {
                paint_pillar_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Pedestal => {
            for i in 0..anchors.len() {
                paint_pedestal_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Ladder => {
            for i in 0..anchors.len() {
                paint_ladder_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Trapdoor => {
            for i in 0..anchors.len() {
                paint_trapdoor_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Footprint => {
            for i in 0..anchors.len() {
                paint_footprint_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::ChalkCircle => {
            for i in 0..anchors.len() {
                paint_chalk_circle_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        // Farm animals.
        FixtureKind::Cow => {
            for i in 0..anchors.len() {
                paint_cow_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Sheep => {
            for i in 0..anchors.len() {
                paint_sheep_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Pig => {
            for i in 0..anchors.len() {
                paint_pig_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Chicken => {
            for i in 0..anchors.len() {
                paint_chicken_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Goat => {
            for i in 0..anchors.len() {
                paint_goat_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        FixtureKind::Horse => {
            for i in 0..anchors.len() {
                paint_horse_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        _ => {
            // Defensive — unknown kinds (forward-compat enum
            // variants) hit the wildcard. Magenta sentinel fill so
            // visual review flags coverage gaps.
            let paint = Paint::solid(Color::rgba(0xFF, 0x00, 0xFF, 1.0));
            let cell = CELL as f32;
            for i in 0..anchors.len() {
                let a = anchors.get(i);
                let cx = a.x() as f32 * cell + cell * 0.5;
                let cy = a.y() as f32 * cell + cell * 0.5;
                painter.fill_circle(cx, cy, 6.0, &paint);
            }
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs, Anchor,
        FixtureKind, FixtureOp as FbFixtureOp, FixtureOpArgs,
        OpEntry, OpEntryArgs, Op, Region as FbRegion,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_fixture_op(kind: FixtureKind, anchors: &[Anchor]) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let anchors_vec = fbb.create_vector(anchors);
        let region_ref = fbb.create_string("");
        let fixture_op = FbFixtureOp::create(
            &mut fbb,
            &FixtureOpArgs {
                region_ref: Some(region_ref),
                kind,
                anchors: Some(anchors_vec),
                seed: 0xBEEF,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FixtureOp,
                op: Some(fixture_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let v5_regions = fbb
            .create_vector::<flatbuffers::ForwardsUOffset<FbRegion>>(&[]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 16,
                height_tiles: 16,
                cell: 32,
                padding: 32,
                regions: Some(v5_regions),
                ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    fn run(buf: &[u8]) -> MockPainter {
        let fir = root_as_floor_ir(buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_fixture_op()
            .expect("fixture op");
        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        painter
    }

    /// Tree dispatch routes to ``paint_tree``: each free tree paints
    /// trunk + canopy + shadow strokes (no group envelope per
    /// primitives/tree.rs §2.14c). One isolated tree anchor (group_id
    /// = 0) emits multiple painter calls — pin that the dispatcher
    /// reaches the lifted painter rather than the legacy circle stub.
    #[test]
    fn draw_routes_tree_kind_to_paint_tree() {
        let anchors = [Anchor::new(2, 3, 0, 0, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(FixtureKind::Tree, &anchors));
        // The legacy stub emitted exactly one FillCircle per anchor.
        // The lifted painter emits multiple calls (trunk, shadow,
        // canopy, volume marks) — assert > 1 to catch a regression
        // back to the stub.
        assert!(
            painter.calls.len() > 1,
            "expected multi-call lifted tree painter, got {}",
            painter.calls.len()
        );
    }

    /// Trees with the same non-zero `group_id` fuse into one grove.
    /// The painter's grove path differs from N free-tree paths in
    /// the call shape — pin that fusion took effect by routing
    /// through the grove branch.
    #[test]
    fn tree_anchors_with_same_group_id_fuse_into_grove() {
        let anchors = [
            Anchor::new(2, 3, 0, 0, 0, 7, 0, 0, 0),
            Anchor::new(3, 3, 0, 0, 0, 7, 0, 0, 0),
            Anchor::new(4, 3, 0, 0, 0, 7, 0, 0, 0),
        ];
        let painter = run(&build_fixture_op(FixtureKind::Tree, &anchors));
        // Grove painter emits a unified canopy path — pin that we
        // exercise the grove branch by checking that the call set
        // includes multiple kinds (the grove emits FillPath + StrokePath).
        let has_fill_path = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::FillPath(_, _, _)));
        assert!(has_fill_path);
    }

    #[test]
    fn draw_routes_bush_kind_to_paint_bush() {
        let anchors = [Anchor::new(5, 5, 0, 0, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(FixtureKind::Bush, &anchors));
        // The legacy stub emitted exactly one FillCircle.
        // The bush painter emits a closed PathOps fill via fill_path
        // — pin that we exercised the lifted painter.
        let has_fill_path = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::FillPath(_, _, _)));
        assert!(has_fill_path);
    }

    #[test]
    fn draw_routes_well_kind_to_paint_well() {
        let anchors = [Anchor::new(3, 4, 0, 0, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(FixtureKind::Well, &anchors));
        // Well painter emits multiple primitives (rim, water, mortar).
        // Multi-call signal pins the dispatch.
        assert!(painter.calls.len() > 1);
    }

    #[test]
    fn draw_routes_fountain_kind_to_paint_fountain() {
        let anchors = [Anchor::new(6, 6, 0, 0, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(FixtureKind::Fountain, &anchors));
        assert!(painter.calls.len() > 1);
    }

    #[test]
    fn draw_routes_stair_kind_to_paint_stairs() {
        // Direction = 0 (up).
        let anchors = [Anchor::new(7, 7, 0, 0, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(FixtureKind::Stair, &anchors));
        assert!(painter.calls.len() > 1);
    }

    /// Every newly-lifted kind (Web / Skull / Bone / LooseStone /
    /// Gravestone / Sign / Mushroom) emits multi-call output —
    /// distinct from the single-FillCircle placeholder stub the
    /// pre-Phase-2.11-close-out dispatcher produced. Pin the lift
    /// arrived at the dispatcher by asserting > 1 painter call per
    /// anchor.
    #[test]
    fn newly_lifted_kinds_emit_multi_call_output() {
        for kind in [
            FixtureKind::Web,
            FixtureKind::Skull,
            FixtureKind::Bone,
            FixtureKind::LooseStone,
            FixtureKind::Gravestone,
            FixtureKind::Sign,
            FixtureKind::Mushroom,
        ] {
            let anchors = [Anchor::new(2, 3, 0, 0, 0, 0, 0, 0, 0)];
            let painter = run(&build_fixture_op(kind, &anchors));
            assert!(
                painter.calls.len() > 1,
                "kind {kind:?}: expected multi-call lifted painter, got {}",
                painter.calls.len()
            );
        }
    }

    /// Farm-animal kinds (Cow / Sheep / Pig / Chicken / Goat /
    /// Horse) each dispatch to their per-anchor painter and emit
    /// multi-call output. Pin so a future enum addition that
    /// forgets the dispatch arm surfaces here as a single
    /// magenta-sentinel call.
    #[test]
    fn farm_animal_kinds_dispatch_to_their_painters() {
        for kind in [
            FixtureKind::Cow, FixtureKind::Sheep, FixtureKind::Pig,
            FixtureKind::Chicken, FixtureKind::Goat, FixtureKind::Horse,
        ] {
            let anchors = [Anchor::new(2, 3, 0, 0, 0, 0, 0, 0, 0)];
            let painter = run(&build_fixture_op(kind, &anchors));
            assert!(
                painter.calls.len() > 1,
                "kind {kind:?}: expected multi-call painter, got {}",
                painter.calls.len(),
            );
        }
    }

    /// Each post-Phase-5 deferred-polish kind dispatches to its
    /// per-anchor painter and emits multiple paint calls (none
    /// fall through to the magenta-sentinel wildcard arm).
    #[test]
    fn deferred_fixture_kinds_dispatch_to_their_painters() {
        for kind in [
            FixtureKind::Chest, FixtureKind::Crate, FixtureKind::Barrel,
            FixtureKind::Altar, FixtureKind::Brazier, FixtureKind::Statue,
            FixtureKind::Pillar, FixtureKind::Pedestal,
            FixtureKind::Ladder, FixtureKind::Trapdoor,
            FixtureKind::Footprint, FixtureKind::ChalkCircle,
        ] {
            let anchors = [Anchor::new(2, 3, 0, 0, 0, 0, 0, 0, 0)];
            let painter = run(&build_fixture_op(kind, &anchors));
            assert!(
                painter.calls.len() > 1,
                "kind {kind:?}: expected multi-call painter, got {}",
                painter.calls.len()
            );
            // The wildcard sentinel arm emits exactly one
            // FillCircle in magenta — pin that none of the new
            // kinds collapse to that single call.
            let only_one_call = painter.calls.len() == 1;
            assert!(
                !only_one_call,
                "kind {kind:?}: collapsed to sentinel single-FillCircle"
            );
        }
    }

    /// Anchor RNG keys differ between anchors at different tiles —
    /// pins that the per-anchor sub-style randomisation isn't
    /// global (which would give every Skull / Bone the same
    /// sub-style). Run two anchors at distinct positions and
    /// assert the painter call output diverges.
    #[test]
    fn per_anchor_rng_diverges_across_tiles() {
        let anchors_a = [Anchor::new(2, 3, 0, 0, 0, 0, 0, 0, 0)];
        let anchors_b = [Anchor::new(7, 8, 0, 0, 0, 0, 0, 0, 0)];
        let painter_a = run(&build_fixture_op(FixtureKind::Bone, &anchors_a));
        let painter_b = run(&build_fixture_op(FixtureKind::Bone, &anchors_b));
        // Bone painter consumes 1-2 random samples per sub-style;
        // different RNG seeds produce different stroke counts.
        // Stable test: assert the FillCircle count differs OR the
        // first FillCircle's coords differ.
        let count_a = painter_a.calls.iter().filter(|c| matches!(c, PainterCall::FillCircle(_, _, _, _))).count();
        let count_b = painter_b.calls.iter().filter(|c| matches!(c, PainterCall::FillCircle(_, _, _, _))).count();
        let coords_a: Vec<(f32, f32)> = painter_a.calls.iter().filter_map(|c| match c {
            PainterCall::FillCircle(x, y, _, _) => Some((*x, *y)),
            _ => None,
        }).collect();
        let coords_b: Vec<(f32, f32)> = painter_b.calls.iter().filter_map(|c| match c {
            PainterCall::FillCircle(x, y, _, _) => Some((*x, *y)),
            _ => None,
        }).collect();
        assert!(
            count_a != count_b || coords_a != coords_b,
            "per-anchor RNG didn't diverge across tiles (a: {count_a}, b: {count_b})"
        );
    }

    /// Mushroom anchors with the same non-zero `group_id` fuse via a
    /// shared mycelium-patch underlay wrapped in a `begin_group` /
    /// `end_group` envelope. Pin that fusion took effect by checking
    /// the cluster envelope reaches the painter — `Anchor::new`'s
    /// 7th arg is the `group_id` (5th = scale, 6th = pad0).
    #[test]
    fn mushroom_anchors_with_same_group_id_emit_cluster_patch() {
        let anchors = [
            Anchor::new(2, 3, 0, 0, 0, 0, 5, 0, 0),
            Anchor::new(3, 3, 0, 0, 0, 0, 5, 0, 0),
            Anchor::new(4, 3, 0, 0, 0, 0, 5, 0, 0),
        ];
        let painter = run(&build_fixture_op(FixtureKind::Mushroom, &anchors));
        let has_begin_group = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::BeginGroup(_)));
        assert!(
            has_begin_group,
            "expected mushroom cluster patch begin_group envelope"
        );
    }

    /// Standalone mushrooms (group_id = 0) skip the cluster patch
    /// — only per-anchor stamps emit, with no group envelope.
    #[test]
    fn standalone_mushroom_emits_no_cluster_envelope() {
        let anchors = [Anchor::new(2, 3, 0, 0, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(FixtureKind::Mushroom, &anchors));
        let has_begin_group = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::BeginGroup(_)));
        assert!(
            !has_begin_group,
            "free mushroom must not emit cluster envelope"
        );
    }

    /// Gravestone anchors with the same non-zero `group_id` fuse
    /// via a shared dirt-plot underlay wrapped in a `begin_group` /
    /// `end_group` envelope.
    #[test]
    fn gravestone_anchors_with_same_group_id_emit_cluster_plot() {
        let anchors = [
            Anchor::new(2, 3, 0, 0, 0, 0, 8, 0, 0),
            Anchor::new(3, 3, 0, 0, 0, 0, 8, 0, 0),
        ];
        let painter = run(&build_fixture_op(FixtureKind::Gravestone, &anchors));
        let has_begin_group = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::BeginGroup(_)));
        assert!(
            has_begin_group,
            "expected gravestone cluster plot begin_group envelope"
        );
    }

    /// Standalone gravestones (group_id = 0) skip the cluster plot
    /// — only per-anchor stamps emit, with no group envelope.
    #[test]
    fn standalone_gravestone_emits_no_cluster_envelope() {
        let anchors = [Anchor::new(2, 3, 0, 0, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(FixtureKind::Gravestone, &anchors));
        let has_begin_group = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::BeginGroup(_)));
        assert!(
            !has_begin_group,
            "free gravestone must not emit cluster envelope"
        );
    }

    #[test]
    fn draw_skips_empty_anchor_list() {
        let buf = build_fixture_op(FixtureKind::Skull, &[]);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_fixture_op()
            .expect("fixture op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }
}
