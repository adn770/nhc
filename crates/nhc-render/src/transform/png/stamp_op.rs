//! StampOp consumer — per-region surface texture overlays.
//!
//! Phase 1.3 shipped the dispatch shape: walk the bits of
//! `decorator_mask`, fan out to per-bit painter stubs. Phase 2.9
//! of `plans/nhc_pure_ir_v5_migration_plan.md` lands real per-bit
//! algorithms one bit at a time:
//!
//! - GridLines (this commit) lifts ``primitives::floor_grid::
//!   paint_floor_grid_paths`` and pushes the region outline as a
//!   clip path so the wobbly-grid strokes stay inside the region.
//! - Cracks / Scratches / Moss / Blood / Ash / Puddles / Ripples /
//!   LavaCracks land in subsequent Phase 2.9 commits, sequenced
//!   one per bit per the migration plan §2.9 ladder.
//!
//! Per-bit baseline densities live in the painter source (not in
//! the IR). `StampOp.density` (uint8, 128 = baseline) scales
//! every enabled bit uniformly; for per-bit divergence the
//! emitter ships multiple StampOps with different masks /
//! densities targeting the same region.

use flatbuffers::{ForwardsUOffset, Vector};
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use super::region_path::outline_to_path;
use crate::ir::{FloorIR, Outline, Region, StampOp};
use crate::painter::{Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2};
use crate::primitives::floor_detail::{
    floor_detail_shapes, paint_floor_detail_side, FloorDetailShape,
};
use crate::primitives::floor_grid::paint_floor_grid_paths;

/// Tile size in pixels — same convention as the other v5 op
/// handlers. Matches the canonical `FloorIR.cell` default.
const CELL: f64 = 32.0;

/// Stable bit assignments — mirrors design/map_ir_v5.md §5 and
/// the StampOp bit registry. Adding a new decorator bit (Phase 2
/// or later) is one entry here plus a per-bit painter
/// implementation.
pub mod bit {
    pub const GRID_LINES: u32 = 1 << 0;
    pub const CRACKS: u32 = 1 << 1;
    pub const SCRATCHES: u32 = 1 << 2;
    pub const RIPPLES: u32 = 1 << 3;
    pub const LAVA_CRACKS: u32 = 1 << 4;
    pub const MOSS: u32 = 1 << 5;
    pub const BLOOD: u32 = 1 << 6;
    pub const ASH: u32 = 1 << 7;
    pub const PUDDLES: u32 = 1 << 8;

    pub const ALL: &[u32] = &[
        GRID_LINES, CRACKS, SCRATCHES, RIPPLES, LAVA_CRACKS,
        MOSS, BLOOD, ASH, PUDDLES,
    ];
}

/// Sentinel placeholder colour for not-yet-lifted bits. Each bit's
/// real painter replaces the corresponding match arm in
/// `dispatch_bit`; remaining bits emit a single translucent fill of
/// the region in the bit's sentinel hue so the dispatcher stays
/// observable while the per-bit work sequences in.
fn stub_color(bit_value: u32) -> Color {
    match bit_value {
        bit::CRACKS => Color::rgba(0x40, 0x40, 0x40, 0.45),
        bit::SCRATCHES => Color::rgba(0x60, 0x60, 0x60, 0.30),
        bit::RIPPLES => Color::rgba(0xFF, 0xFF, 0xFF, 0.20),
        bit::LAVA_CRACKS => Color::rgba(0xFF, 0xC8, 0x40, 0.50),
        bit::MOSS => Color::rgba(0x55, 0x88, 0x33, 0.40),
        bit::BLOOD => Color::rgba(0x88, 0x10, 0x10, 0.55),
        bit::ASH => Color::rgba(0x80, 0x80, 0x80, 0.35),
        bit::PUDDLES => Color::rgba(0x18, 0x28, 0x40, 0.30),
        _ => Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    }
}

/// GridLines stroke styling — lifts ``transform/png/floor_grid.rs``
/// constants verbatim so the lifted painter reads pixel-equal to
/// the v4 FloorGridOp dispatch.
const GRID_WIDTH: f32 = 0.3;
const GRID_OPACITY: f32 = 0.7;
const GRID_INK: Paint = Paint {
    color: Color { r: 0, g: 0, b: 0, a: GRID_OPACITY },
};

fn grid_stroke() -> Stroke {
    Stroke {
        width: GRID_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    }
}

/// Ray-cast point-in-polygon test against a single ring.
fn point_in_ring(px: f64, py: f64, ring: &[(f64, f64)]) -> bool {
    let n = ring.len();
    if n < 3 {
        return false;
    }
    let mut inside = false;
    let mut j = n - 1;
    for i in 0..n {
        let (xi, yi) = ring[i];
        let (xj, yj) = ring[j];
        if (yi > py) != (yj > py) {
            let t = (py - yi) / (yj - yi);
            if px < xi + t * (xj - xi) {
                inside = !inside;
            }
        }
        j = i;
    }
    inside
}

/// Multi-ring point-in-polygon via even-odd rule. Each enclosing
/// ring contributes XOR — outer ring + inner hole rings naturally
/// punch holes through the predicate.
fn point_in_outline(px: f64, py: f64, outline: &Outline<'_>) -> bool {
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 3 => v,
        _ => return false,
    };
    let coords: Vec<(f64, f64)> = verts
        .iter()
        .map(|p| (p.x() as f64, p.y() as f64))
        .collect();
    match outline.rings() {
        Some(rs) if rs.len() > 0 => {
            let mut inside = false;
            for r in rs.iter() {
                let start = r.start() as usize;
                let count = r.count() as usize;
                if start + count > coords.len() {
                    continue;
                }
                if point_in_ring(px, py, &coords[start..start + count]) {
                    inside = !inside;
                }
            }
            inside
        }
        _ => point_in_ring(px, py, &coords),
    }
}

/// Enumerate integer tile coords (x, y) whose centre lies inside
/// the region's outline. The shared backbone for every per-tile
/// decorator-bit painter (GridLines + the upcoming Cracks /
/// Scratches / Moss / Blood / Ash / Puddles).
fn enumerate_region_tiles(outline: &Outline<'_>) -> Vec<(i32, i32)> {
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 3 => v,
        _ => return Vec::new(),
    };
    let mut x0 = f64::INFINITY;
    let mut y0 = f64::INFINITY;
    let mut x1 = f64::NEG_INFINITY;
    let mut y1 = f64::NEG_INFINITY;
    for v in verts.iter() {
        let x = v.x() as f64;
        let y = v.y() as f64;
        if x < x0 { x0 = x; }
        if y < y0 { y0 = y; }
        if x > x1 { x1 = x; }
        if y > y1 { y1 = y; }
    }
    if !x0.is_finite() {
        return Vec::new();
    }
    let tx0 = (x0 / CELL).floor() as i32;
    let ty0 = (y0 / CELL).floor() as i32;
    let tx1 = (x1 / CELL).ceil() as i32 - 1;
    let ty1 = (y1 / CELL).ceil() as i32 - 1;
    let mut tiles = Vec::new();
    for ty in ty0..=ty1 {
        for tx in tx0..=tx1 {
            let cx = (tx as f64 + 0.5) * CELL;
            let cy = (ty as f64 + 0.5) * CELL;
            if point_in_outline(cx, cy, outline) {
                tiles.push((tx, ty));
            }
        }
    }
    tiles
}

/// GridLines bit — wobbly Perlin grid (lift from
/// ``primitives::floor_grid::paint_floor_grid_paths``). Emits the
/// per-tile right + bottom edges as stroked PathOps. The region
/// outline pushes as an EvenOdd clip so strokes don't leak past
/// the region boundary; matches the v4 FloorGridOp dispatch's
/// `Mask::new + mask.fill_path(EvenOdd)` envelope.
fn paint_grid_lines(
    painter: &mut dyn Painter,
    fir: &FloorIR<'_>,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    let tiles_xy = enumerate_region_tiles(outline);
    if tiles_xy.is_empty() {
        return;
    }
    // The v4 painter takes (x, y, is_corridor) — at the StampOp
    // level we no longer carry the corridor distinction, so feed
    // every tile through the room-bucket path. Corridor-specific
    // grid styling rides separate StampOps targeting the corridor
    // region with a different decorator mask if it ever needs to
    // diverge.
    let tiles: Vec<(i32, i32, bool)> = tiles_xy
        .into_iter()
        .map(|(x, y)| (x, y, false))
        .collect();
    let (room_paths, _corridor_paths) = paint_floor_grid_paths(
        fir.width_tiles() as i32,
        fir.height_tiles() as i32,
        &tiles,
        seed,
    );
    if room_paths.is_empty() {
        return;
    }
    let stroke = grid_stroke();
    painter.push_clip(region_path, FillRule::EvenOdd);
    painter.stroke_path(&room_paths, &GRID_INK, &stroke);
    painter.pop_clip();
}

/// Cracks bit — lift the per-tile crack generator from
/// ``primitives::floor_detail::floor_detail_shapes``. Walks every
/// region tile, picks ``crack_prob`` of them via the seeded RNG,
/// emits a diagonal corner-line shape per hit, and paints them
/// inside a single ``begin_group(CRACKS_OPACITY)`` envelope. The
/// scratches + stones buckets from the same generator are dropped
/// — the Scratches bit (Phase 2.9c) consumes the scratches bucket
/// independently, and the stones bucket isn't a v5 decorator
/// (LooseStone is a FixtureKind, not a StampOp bit).
fn paint_cracks(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    paint_floor_detail_bucket(painter, outline, region_path, seed, FloorDetailBucket::Cracks);
}

/// Scratches bit — same per-tile generator as Cracks, with the
/// scratches bucket selected. The Y-shaped scratch shape (three
/// Perlin-wobbled branches meeting at a fork) and its
/// ``SCRATCHES_OPACITY`` group envelope are painted by the lifted
/// `paint_floor_detail_side` dispatcher.
fn paint_scratches(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    paint_floor_detail_bucket(painter, outline, region_path, seed, FloorDetailBucket::Scratches);
}

/// Bucket selector for `paint_floor_detail_bucket` — picks which
/// of the three buckets `floor_detail_shapes` returns to paint.
/// Cracks (Phase 2.9b) and Scratches (Phase 2.9c) share the same
/// generator and only diverge on this selector.
#[derive(Clone, Copy, Debug, PartialEq)]
enum FloorDetailBucket {
    Cracks,
    Scratches,
}

fn paint_floor_detail_bucket(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
    bucket: FloorDetailBucket,
) {
    let tiles_xy = enumerate_region_tiles(outline);
    if tiles_xy.is_empty() {
        return;
    }
    let tiles: Vec<(i32, i32, bool)> = tiles_xy
        .into_iter()
        .map(|(x, y)| (x, y, false))
        .collect();
    // Theme defaults to "dungeon" — v5 doesn't carry a theme on
    // the IR. Cave-floor decorators (denser cracks, sparser
    // scratches) ride a separate StampOp emitted with a different
    // density / mask combination.
    let (room_side, _corridor_side) =
        floor_detail_shapes(&tiles, seed, "dungeon", false);
    let (cracks, scratches, _stones) = room_side;
    // Build a SideShapes tuple containing only the bucket the
    // caller asked for; the floor_detail dispatcher walks all 3
    // buckets but skips empty ones.
    let only_bucket: (
        Vec<FloorDetailShape>,
        Vec<FloorDetailShape>,
        Vec<FloorDetailShape>,
    ) = match bucket {
        FloorDetailBucket::Cracks => (cracks, Vec::new(), Vec::new()),
        FloorDetailBucket::Scratches => (Vec::new(), scratches, Vec::new()),
    };
    if only_bucket.0.is_empty() && only_bucket.1.is_empty() && only_bucket.2.is_empty() {
        return;
    }
    painter.push_clip(region_path, FillRule::EvenOdd);
    paint_floor_detail_side(painter, &only_bucket);
    painter.pop_clip();
}

/// Per-tile stamp scaffold — shared by Moss / Blood / Ash /
/// Puddles / Ripples / LavaCracks. Walks every region tile,
/// gates each through the bit's baseline probability against a
/// seed-salted ``Pcg64Mcg`` stream, and dispatches the per-hit
/// painting closure inside a single ``begin_group`` envelope.
///
/// The seed_salt argument keeps each bit's RNG independent — two
/// bits in the same StampOp run on the same base seed but diverge
/// on the salt so their per-tile placement doesn't correlate.
fn paint_per_tile_decorator<F>(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
    seed_salt: u64,
    base_prob: f64,
    group_opacity: f32,
    mut paint_one: F,
) where
    F: FnMut(&mut dyn Painter, &mut Pcg64Mcg, f64, f64),
{
    let tiles = enumerate_region_tiles(outline);
    if tiles.is_empty() {
        return;
    }
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ seed_salt);
    painter.push_clip(region_path, FillRule::EvenOdd);
    painter.begin_group(group_opacity);
    for (tx, ty) in tiles {
        if rng.gen::<f64>() < base_prob {
            let px = tx as f64 * CELL;
            let py = ty as f64 * CELL;
            paint_one(painter, &mut rng, px, py);
        }
    }
    painter.end_group();
    painter.pop_clip();
}

/// Moss bit — green tufts at low density. Per hit, paint 2-3
/// small filled green ellipses at sub-tile positions; the cluster
/// reads as a moss patch on the floor.
fn paint_moss(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    const MOSS_BASE: Color = Color::rgba(0x4A, 0x7A, 0x35, 1.0);
    const MOSS_DARK: Color = Color::rgba(0x32, 0x5A, 0x22, 1.0);
    const MOSS_PROB: f64 = 0.10;
    const MOSS_OPACITY: f32 = 0.55;
    const MOSS_SEED_SALT: u64 = 0x_0055_C0FF_EE00_0001;

    paint_per_tile_decorator(
        painter,
        outline,
        region_path,
        seed,
        MOSS_SEED_SALT,
        MOSS_PROB,
        MOSS_OPACITY,
        |painter, rng, px, py| {
            let n_tufts = rng.gen_range(2..=3);
            for _ in 0..n_tufts {
                let cx = px + rng.gen_range((CELL * 0.15)..(CELL * 0.85));
                let cy = py + rng.gen_range((CELL * 0.15)..(CELL * 0.85));
                let rx = rng.gen_range((CELL * 0.05)..(CELL * 0.10));
                let ry = rng.gen_range((CELL * 0.04)..(CELL * 0.08));
                let dark = rng.gen::<f64>() < 0.35;
                let paint = Paint::solid(if dark { MOSS_DARK } else { MOSS_BASE });
                painter.fill_ellipse(cx as f32, cy as f32, rx as f32, ry as f32, &paint);
            }
        },
    );
}

/// Blood bit — red splatters / stains at very low density. Per
/// hit, paint 1 large central ellipse + 1-2 small droplets nearby
/// to read as a splatter pattern.
fn paint_blood(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    const BLOOD_BASE: Color = Color::rgba(0x88, 0x10, 0x10, 1.0);
    const BLOOD_DARK: Color = Color::rgba(0x55, 0x08, 0x08, 1.0);
    const BLOOD_PROB: f64 = 0.04;
    const BLOOD_OPACITY: f32 = 0.65;
    const BLOOD_SEED_SALT: u64 = 0x_B100_D5EE_D000_0001;

    paint_per_tile_decorator(
        painter,
        outline,
        region_path,
        seed,
        BLOOD_SEED_SALT,
        BLOOD_PROB,
        BLOOD_OPACITY,
        |painter, rng, px, py| {
            let cx = px + rng.gen_range((CELL * 0.30)..(CELL * 0.70));
            let cy = py + rng.gen_range((CELL * 0.30)..(CELL * 0.70));
            let rx = rng.gen_range((CELL * 0.10)..(CELL * 0.18));
            let ry = rng.gen_range((CELL * 0.08)..(CELL * 0.16));
            painter.fill_ellipse(
                cx as f32, cy as f32, rx as f32, ry as f32,
                &Paint::solid(BLOOD_BASE),
            );
            let n_droplets = rng.gen_range(1..=2);
            for _ in 0..n_droplets {
                let dx = rng.gen_range(-(CELL * 0.20)..(CELL * 0.20));
                let dy = rng.gen_range(-(CELL * 0.20)..(CELL * 0.20));
                let dr = rng.gen_range((CELL * 0.025)..(CELL * 0.05));
                painter.fill_ellipse(
                    (cx + dx) as f32, (cy + dy) as f32,
                    dr as f32, dr as f32,
                    &Paint::solid(BLOOD_DARK),
                );
            }
        },
    );
}

/// Ash bit — fine grey dusting at moderate density. Per hit,
/// paint 4-6 tiny grey dots scattered uniformly in the tile.
fn paint_ash(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    const ASH_BASE: Color = Color::rgba(0x66, 0x66, 0x66, 1.0);
    const ASH_PROB: f64 = 0.30;
    const ASH_OPACITY: f32 = 0.40;
    const ASH_SEED_SALT: u64 = 0x_A5C0_DAD5_BE00_0001;

    paint_per_tile_decorator(
        painter,
        outline,
        region_path,
        seed,
        ASH_SEED_SALT,
        ASH_PROB,
        ASH_OPACITY,
        |painter, rng, px, py| {
            let n_dots = rng.gen_range(4..=6);
            for _ in 0..n_dots {
                let cx = px + rng.gen_range((CELL * 0.10)..(CELL * 0.90));
                let cy = py + rng.gen_range((CELL * 0.10)..(CELL * 0.90));
                let r = rng.gen_range((CELL * 0.015)..(CELL * 0.04));
                painter.fill_circle(
                    cx as f32, cy as f32, r as f32,
                    &Paint::solid(ASH_BASE),
                );
            }
        },
    );
}

/// Puddles bit — dark wet spots at low density. Per hit, paint 1
/// dark blue ellipse covering ~40% of the tile.
fn paint_puddles(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    const PUDDLE_BASE: Color = Color::rgba(0x18, 0x28, 0x40, 1.0);
    const PUDDLE_PROB: f64 = 0.05;
    const PUDDLE_OPACITY: f32 = 0.45;
    const PUDDLE_SEED_SALT: u64 = 0x_BEAD_DA85_E000_0001;

    paint_per_tile_decorator(
        painter,
        outline,
        region_path,
        seed,
        PUDDLE_SEED_SALT,
        PUDDLE_PROB,
        PUDDLE_OPACITY,
        |painter, rng, px, py| {
            let cx = px + rng.gen_range((CELL * 0.30)..(CELL * 0.70));
            let cy = py + rng.gen_range((CELL * 0.30)..(CELL * 0.70));
            let rx = rng.gen_range((CELL * 0.18)..(CELL * 0.30));
            let ry = rng.gen_range((CELL * 0.12)..(CELL * 0.22));
            painter.fill_ellipse(
                cx as f32, cy as f32, rx as f32, ry as f32,
                &Paint::solid(PUDDLE_BASE),
            );
        },
    );
}

/// Ripples bit (Liquid:Water) — static concentric-ring patterns.
/// Per hit, stroke 1-2 circles centred in the tile to read as
/// surface motion.
fn paint_ripples(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    const RIPPLE_INK: Color = Color::rgba(0x4A, 0x78, 0x88, 1.0);
    const RIPPLE_PROB: f64 = 0.45;
    const RIPPLE_OPACITY: f32 = 0.35;
    const RIPPLE_SEED_SALT: u64 = 0x_77AA_2E22_7E2E_7A77;

    paint_per_tile_decorator(
        painter,
        outline,
        region_path,
        seed,
        RIPPLE_SEED_SALT,
        RIPPLE_PROB,
        RIPPLE_OPACITY,
        |painter, rng, px, py| {
            let cx = px + rng.gen_range((CELL * 0.30)..(CELL * 0.70));
            let cy = py + rng.gen_range((CELL * 0.30)..(CELL * 0.70));
            let n_rings = rng.gen_range(1..=2);
            for ring in 0..n_rings {
                let r = (CELL * 0.15) + (ring as f64) * (CELL * 0.10);
                let mut path = PathOps::new();
                let segs = 16;
                let cx32 = cx as f32;
                let cy32 = cy as f32;
                let r32 = r as f32;
                for i in 0..=segs {
                    let theta = (i as f32) * std::f32::consts::TAU
                        / (segs as f32);
                    let x = cx32 + r32 * theta.cos();
                    let y = cy32 + r32 * theta.sin();
                    if i == 0 {
                        path.move_to(Vec2::new(x, y));
                    } else {
                        path.line_to(Vec2::new(x, y));
                    }
                }
                painter.stroke_path(
                    &path,
                    &Paint::solid(RIPPLE_INK),
                    &Stroke {
                        width: 0.5,
                        line_cap: LineCap::Round,
                        line_join: LineJoin::Round,
                    },
                );
            }
        },
    );
}

/// LavaCracks bit (Liquid:Lava) — static angular crack network.
/// Per hit, stroke 2-3 short line segments forming an angular
/// crack pattern in bright orange ink.
fn paint_lava_cracks(
    painter: &mut dyn Painter,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    const LAVA_INK: Color = Color::rgba(0xFF, 0xC8, 0x40, 1.0);
    const LAVA_PROB: f64 = 0.30;
    const LAVA_OPACITY: f32 = 0.55;
    const LAVA_SEED_SALT: u64 = 0x_1A7A_BEEF_DEAD_F1AA;

    paint_per_tile_decorator(
        painter,
        outline,
        region_path,
        seed,
        LAVA_SEED_SALT,
        LAVA_PROB,
        LAVA_OPACITY,
        |painter, rng, px, py| {
            let n_cracks = rng.gen_range(2..=3);
            for _ in 0..n_cracks {
                let x0 = px + rng.gen_range((CELL * 0.10)..(CELL * 0.90));
                let y0 = py + rng.gen_range((CELL * 0.10)..(CELL * 0.90));
                let x1 = px + rng.gen_range((CELL * 0.10)..(CELL * 0.90));
                let y1 = py + rng.gen_range((CELL * 0.10)..(CELL * 0.90));
                let mut path = PathOps::new();
                path.move_to(Vec2::new(x0 as f32, y0 as f32));
                path.line_to(Vec2::new(x1 as f32, y1 as f32));
                painter.stroke_path(
                    &path,
                    &Paint::solid(LAVA_INK),
                    &Stroke {
                        width: 0.6,
                        line_cap: LineCap::Round,
                        line_join: LineJoin::Round,
                    },
                );
            }
        },
    );
}

/// Per-bit dispatcher. Phase 2.9 commits replace each not-yet-
/// lifted arm with the bit's real painter.
fn dispatch_bit(
    bit_value: u32,
    painter: &mut dyn Painter,
    fir: &FloorIR<'_>,
    outline: &Outline<'_>,
    region_path: &PathOps,
    seed: u64,
) {
    match bit_value {
        bit::GRID_LINES => {
            paint_grid_lines(painter, fir, outline, region_path, seed);
        }
        bit::CRACKS => {
            paint_cracks(painter, outline, region_path, seed);
        }
        bit::SCRATCHES => {
            paint_scratches(painter, outline, region_path, seed);
        }
        bit::MOSS => {
            paint_moss(painter, outline, region_path, seed);
        }
        bit::BLOOD => {
            paint_blood(painter, outline, region_path, seed);
        }
        bit::ASH => {
            paint_ash(painter, outline, region_path, seed);
        }
        bit::PUDDLES => {
            paint_puddles(painter, outline, region_path, seed);
        }
        bit::RIPPLES => {
            paint_ripples(painter, outline, region_path, seed);
        }
        bit::LAVA_CRACKS => {
            paint_lava_cracks(painter, outline, region_path, seed);
        }
        // No more not-yet-lifted bits at Phase 2.9 — every bit in
        // the v5 registry has a real painter. The wildcard arm
        // keeps the sentinel-fill behaviour as a safety net for
        // future additive minor-bumps that introduce new bits;
        // visual review flags them via the magenta sentinel.
        _ => {
            let paint = Paint::solid(stub_color(bit_value));
            painter.fill_path(region_path, &paint, FillRule::Winding);
        }
    }
}

pub fn draw<'a>(
    op: StampOp<'a>,
    fir: &FloorIR<'_>,
    regions: Vector<'a, ForwardsUOffset<Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let rr = match op.region_ref() {
        Some(r) if !r.is_empty() => r,
        _ => return false,
    };
    let region = match super::find_region(regions, rr) {
        Some(r) => r,
        None => return false,
    };
    let outline = match region.outline() {
        Some(o) => o,
        None => return false,
    };
    let (path, _multi) = match outline_to_path(&outline) {
        Some(p) => p,
        None => return false,
    };
    let mask = op.decorator_mask();
    if mask == 0 {
        return false;
    }
    for bit_value in bit::ALL {
        if mask & bit_value != 0 {
            dispatch_bit(*bit_value, painter, fir, &outline, &path, op.seed());
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs, Outline,
        OutlineArgs, OutlineKind, OpEntry, OpEntryArgs, Op,
        Region as FbRegion, RegionArgs, StampOp as FbStampOp,
        StampOpArgs, Vec2 as FbVec2,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_stamp_op(mask: u32) -> Vec<u8> {
        // 12×12-tile region in pixel coords (0,0) → (384,384).
        // Sized so even the lowest-probability bits (Blood at 4%,
        // Puddles at 5%) reliably hit at least once on the
        // ``seed = 0xCAFE`` test stream — 144 tiles × 0.04 ≈ 5.76
        // expected hits. A 4×4 region only had 0.6 expected hits
        // for Blood, often producing empty groups that broke the
        // envelope-shape assertion.
        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&[
            FbVec2::new(0.0, 0.0),
            FbVec2::new(384.0, 0.0),
            FbVec2::new(384.0, 384.0),
            FbVec2::new(0.0, 384.0),
        ]);
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let region_id = fbb.create_string("room.0");
        let region_shape = fbb.create_string("rect");
        let region = FbRegion::create(
            &mut fbb,
            &RegionArgs {
                id: Some(region_id),
                outline: Some(outline),
                shape_tag: Some(region_shape),
                ..Default::default()
            },
        );
        let v5_regions = fbb.create_vector(&[region]);
        let region_ref = fbb.create_string("room.0");
        let stamp_op = FbStampOp::create(
            &mut fbb,
            &StampOpArgs {
                region_ref: Some(region_ref),
                subtract_region_refs: None,
                decorator_mask: mask,
                density: 128,
                seed: 0xCAFE,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::StampOp,
                op: Some(stamp_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 8,
                height_tiles: 8,
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
            .op_as_stamp_op()
            .expect("stamp op");
        let mut painter = MockPainter::default();
        let painted = draw(op, &fir, regions, &mut painter);
        assert!(painted);
        painter
    }

    /// GridLines bit emits a clipped stroke_path for the wobbly
    /// grid. Pin the call signature: push_clip + stroke_path +
    /// pop_clip in that order.
    #[test]
    fn grid_lines_bit_emits_clipped_stroke_path() {
        let painter = run(&build_stamp_op(bit::GRID_LINES));
        let kinds: Vec<&str> = painter
            .calls
            .iter()
            .map(|c| match c {
                PainterCall::PushClip(_, _) => "push_clip",
                PainterCall::PopClip => "pop_clip",
                PainterCall::StrokePath(_, _, _) => "stroke_path",
                _ => "other",
            })
            .collect();
        assert!(
            kinds.windows(3).any(|w| w == ["push_clip", "stroke_path", "pop_clip"]),
            "expected push_clip + stroke_path + pop_clip sequence, got {kinds:?}"
        );
    }

    /// Every bit in the v5 registry now has a real painter. Pin
    /// the dispatch envelope shape (push_clip ⊃ … ⊃ pop_clip) for
    /// each lifted bit so a regression in any individual arm
    /// surfaces with a fixture-flavour-aware error. Sentinel hits
    /// at the wildcard arm would emit a single FillPath without
    /// the clip envelope — distinct shape, easy to catch.
    #[test]
    fn every_bit_paints_inside_clipped_envelope() {
        for bit_value in [
            bit::GRID_LINES, bit::CRACKS, bit::SCRATCHES,
            bit::RIPPLES, bit::LAVA_CRACKS,
            bit::MOSS, bit::BLOOD, bit::ASH, bit::PUDDLES,
        ] {
            let painter = run(&build_stamp_op(bit_value));
            let kinds: Vec<&str> = painter
                .calls
                .iter()
                .map(|c| match c {
                    PainterCall::PushClip(_, _) => "push_clip",
                    PainterCall::PopClip => "pop_clip",
                    _ => "other",
                })
                .collect();
            assert_eq!(
                kinds.first(), Some(&"push_clip"),
                "bit 0x{bit_value:x}: missing push_clip envelope (calls: {kinds:?})"
            );
            assert_eq!(
                kinds.last(), Some(&"pop_clip"),
                "bit 0x{bit_value:x}: missing pop_clip envelope (calls: {kinds:?})"
            );
        }
    }

    /// Cracks bit emits the lifted floor-detail crack generator
    /// inside a `begin_group(CRACKS_OPACITY)` envelope, all under
    /// a region-clip. Pin the envelope shape: push_clip ⊃
    /// begin_group ⊃ stroke_paths ⊃ end_group ⊃ pop_clip.
    #[test]
    fn cracks_bit_paints_inside_clipped_group_envelope() {
        let painter = run(&build_stamp_op(bit::CRACKS));
        let kinds: Vec<&str> = painter
            .calls
            .iter()
            .map(|c| match c {
                PainterCall::PushClip(_, _) => "push_clip",
                PainterCall::PopClip => "pop_clip",
                PainterCall::BeginGroup(_) => "begin_group",
                PainterCall::EndGroup => "end_group",
                PainterCall::StrokePath(_, _, _) => "stroke_path",
                _ => "other",
            })
            .collect();
        assert_eq!(kinds.first(), Some(&"push_clip"));
        assert_eq!(kinds.last(), Some(&"pop_clip"));
        assert!(
            kinds.contains(&"begin_group") && kinds.contains(&"end_group"),
            "expected begin_group + end_group inside push_clip envelope, got {kinds:?}"
        );
        assert!(
            kinds.contains(&"stroke_path"),
            "expected stroke_path calls inside the group envelope, got {kinds:?}"
        );
    }

    #[test]
    fn empty_decorator_mask_skips_painting() {
        let buf = build_stamp_op(0);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_stamp_op()
            .expect("stamp op");

        let mut painter = MockPainter::default();
        let painted = draw(op, &fir, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }

    #[test]
    fn enumerate_region_tiles_for_12x12_rect_returns_144() {
        let buf = build_stamp_op(bit::GRID_LINES);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let region = regions.get(0);
        let outline = region.outline().expect("outline");
        let tiles = enumerate_region_tiles(&outline);
        // (0,0)→(384,384) at 32 px/tile = 12×12 = 144 tiles.
        assert_eq!(tiles.len(), 144);
    }

    #[test]
    fn point_in_ring_handles_simple_square() {
        let ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)];
        assert!(point_in_ring(5.0, 5.0, &ring));
        assert!(!point_in_ring(15.0, 5.0, &ring));
        assert!(!point_in_ring(5.0, -1.0, &ring));
    }
}
