//! V5FixtureOp consumer — discrete decorative objects with anchors.
//!
//! Phase 2.11 of `plans/nhc_pure_ir_v5_migration_plan.md`. The
//! dispatcher routes each ``V5FixtureKind`` to a per-kind painter:
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
//! group_id fusion (Tree groves, Mushroom clusters, Gravestone
//! clusters) lifts via the shared ``split_by_group`` helper for
//! Tree only at this commit; Mushroom + Gravestone clustering
//! rides additive future work — each anchor renders standalone.

use std::collections::BTreeMap;
use std::f64::consts::PI;

use flatbuffers::{ForwardsUOffset, Vector};
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::ir::{V5Anchor, V5FixtureKind, V5FixtureOp, V5Region};
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

/// Per-anchor RNG — keeps each anchor's sub-style variation
/// deterministic. Combines the FixtureOp's seed with the anchor's
/// (x, y) so anchors at different tiles diverge.
fn anchor_rng(seed: u64, x: i32, y: i32) -> Pcg64Mcg {
    let key = seed
        ^ ((x as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15))
        ^ ((y as u64).wrapping_mul(0xBF58_476D_1CE4_E5B9));
    Pcg64Mcg::seed_from_u64(key)
}

/// Web — radiating spokes from a corner + concentric ring threads.
/// ``orientation`` picks the corner (0=NW, 1=NE, 2=SE, 3=SW).
fn paint_web_anchor(painter: &mut dyn Painter, a: &V5Anchor, seed: u64) {
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
fn paint_skull_anchor(painter: &mut dyn Painter, a: &V5Anchor, seed: u64) {
    let mut rng = anchor_rng(seed, a.x(), a.y());
    let px = f64::from(a.x()) * CELL;
    let py = f64::from(a.y()) * CELL;
    let cx = px + CELL * 0.5 + rng.gen_range(-(CELL * 0.10)..(CELL * 0.10));
    let cy = py + CELL * 0.5 + rng.gen_range(-(CELL * 0.10)..(CELL * 0.10));
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
fn paint_bone_anchor(painter: &mut dyn Painter, a: &V5Anchor, seed: u64) {
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
fn paint_loose_stone_anchor(painter: &mut dyn Painter, a: &V5Anchor, seed: u64) {
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
fn paint_gravestone_anchor(painter: &mut dyn Painter, a: &V5Anchor, _seed: u64) {
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
fn paint_sign_anchor(painter: &mut dyn Painter, a: &V5Anchor, _seed: u64) {
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
fn paint_mushroom_anchor(painter: &mut dyn Painter, a: &V5Anchor, seed: u64) {
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

fn collect_tiles(anchors: &Vector<'_, V5Anchor>) -> Vec<(i32, i32)> {
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
fn split_by_group(anchors: &Vector<'_, V5Anchor>) -> (Vec<(i32, i32)>, Vec<Vec<(i32, i32)>>) {
    let mut free = Vec::new();
    let mut groups: BTreeMap<u32, Vec<(i32, i32)>> = BTreeMap::new();
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
    op: V5FixtureOp<'a>,
    _regions: Vector<'a, ForwardsUOffset<V5Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let anchors = match op.anchors() {
        Some(a) if !a.is_empty() => a,
        _ => return false,
    };
    let kind = op.kind();
    match kind {
        V5FixtureKind::Tree => {
            let (free, groves) = split_by_group(&anchors);
            paint_tree(painter, &free, &groves);
        }
        V5FixtureKind::Bush => {
            let tiles = collect_tiles(&anchors);
            paint_bush(painter, &tiles);
        }
        V5FixtureKind::Well => {
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
        V5FixtureKind::Fountain => {
            let mut by_variant: BTreeMap<u8, Vec<(i32, i32)>> = BTreeMap::new();
            for i in 0..anchors.len() {
                let a = anchors.get(i);
                by_variant.entry(a.variant()).or_default().push((a.x(), a.y()));
            }
            for (variant, tiles) in by_variant {
                paint_fountain(painter, &tiles, variant);
            }
        }
        V5FixtureKind::Stair => {
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
        V5FixtureKind::Web => {
            for i in 0..anchors.len() {
                paint_web_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        V5FixtureKind::Skull => {
            for i in 0..anchors.len() {
                paint_skull_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        V5FixtureKind::Bone => {
            for i in 0..anchors.len() {
                paint_bone_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        V5FixtureKind::LooseStone => {
            for i in 0..anchors.len() {
                paint_loose_stone_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        V5FixtureKind::Gravestone => {
            for i in 0..anchors.len() {
                paint_gravestone_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        V5FixtureKind::Sign => {
            for i in 0..anchors.len() {
                paint_sign_anchor(painter, &anchors.get(i), op.seed());
            }
        }
        V5FixtureKind::Mushroom => {
            for i in 0..anchors.len() {
                paint_mushroom_anchor(painter, &anchors.get(i), op.seed());
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
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs, V5Anchor,
        V5FixtureKind, V5FixtureOp as FbV5FixtureOp, V5FixtureOpArgs,
        V5OpEntry, V5OpEntryArgs, V5Op, V5Region as FbV5Region,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_fixture_op(kind: V5FixtureKind, anchors: &[V5Anchor]) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let anchors_vec = fbb.create_vector(anchors);
        let region_ref = fbb.create_string("");
        let fixture_op = FbV5FixtureOp::create(
            &mut fbb,
            &V5FixtureOpArgs {
                region_ref: Some(region_ref),
                kind,
                anchors: Some(anchors_vec),
                seed: 0xBEEF,
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5FixtureOp,
                op: Some(fixture_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let v5_regions = fbb
            .create_vector::<flatbuffers::ForwardsUOffset<FbV5Region>>(&[]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 16,
                height_tiles: 16,
                cell: 32,
                padding: 32,
                v5_regions: Some(v5_regions),
                v5_ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    fn run(buf: &[u8]) -> MockPainter {
        let fir = root_as_floor_ir(buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_fixture_op()
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
        let anchors = [V5Anchor::new(2, 3, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Tree, &anchors));
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
            V5Anchor::new(2, 3, 0, 0, 0, 7, 0),
            V5Anchor::new(3, 3, 0, 0, 0, 7, 0),
            V5Anchor::new(4, 3, 0, 0, 0, 7, 0),
        ];
        let painter = run(&build_fixture_op(V5FixtureKind::Tree, &anchors));
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
        let anchors = [V5Anchor::new(5, 5, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Bush, &anchors));
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
        let anchors = [V5Anchor::new(3, 4, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Well, &anchors));
        // Well painter emits multiple primitives (rim, water, mortar).
        // Multi-call signal pins the dispatch.
        assert!(painter.calls.len() > 1);
    }

    #[test]
    fn draw_routes_fountain_kind_to_paint_fountain() {
        let anchors = [V5Anchor::new(6, 6, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Fountain, &anchors));
        assert!(painter.calls.len() > 1);
    }

    #[test]
    fn draw_routes_stair_kind_to_paint_stairs() {
        // Direction = 0 (up).
        let anchors = [V5Anchor::new(7, 7, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Stair, &anchors));
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
            V5FixtureKind::Web,
            V5FixtureKind::Skull,
            V5FixtureKind::Bone,
            V5FixtureKind::LooseStone,
            V5FixtureKind::Gravestone,
            V5FixtureKind::Sign,
            V5FixtureKind::Mushroom,
        ] {
            let anchors = [V5Anchor::new(2, 3, 0, 0, 0, 0, 0)];
            let painter = run(&build_fixture_op(kind, &anchors));
            assert!(
                painter.calls.len() > 1,
                "kind {kind:?}: expected multi-call lifted painter, got {}",
                painter.calls.len()
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
        let anchors_a = [V5Anchor::new(2, 3, 0, 0, 0, 0, 0)];
        let anchors_b = [V5Anchor::new(7, 8, 0, 0, 0, 0, 0)];
        let painter_a = run(&build_fixture_op(V5FixtureKind::Bone, &anchors_a));
        let painter_b = run(&build_fixture_op(V5FixtureKind::Bone, &anchors_b));
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

    #[test]
    fn draw_skips_empty_anchor_list() {
        let buf = build_fixture_op(V5FixtureKind::Skull, &[]);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_fixture_op()
            .expect("fixture op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }
}
