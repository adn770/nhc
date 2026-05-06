//! `Family::Stone` painter — masonry / paving substrate.
//!
//! 9 styles (Cobblestone, Brick, Flagstone, OpusRomano, FieldStone,
//! Pinwheel, Hopscotch, CrazyPaving, Ashlar). Per-style sub-pattern
//! axes (Cobblestone × 4, Brick × 3, Ashlar × 2; the rest none).
//! Per-style optional tone axis (typically Light / Medium / Dark).
//!
//! Phase 2.4a–b of `plans/nhc_pure_ir_v5_migration_plan.md`. The
//! per-style palette is already locked (lifted from the v4 stone
//! primitives); these commits add the (style, sub_pattern)
//! dispatch surface and ship the per-sub-pattern layout algorithms
//! for the two styles with sub-pattern axes:
//!
//! Cobblestone (style = 0, Phase 2.4a):
//! - `Herringbone (0)` — thin rotated bricks alternating ±45° in
//!   a chevron-interlock grid.
//! - `Stack (1)` — square pavers in a uniform grid; deep mortar
//!   joints between cells.
//! - `Rubble (2)` — irregular randomised ellipses (lifted spirit
//!   from the v4 ``primitives/cobblestone.rs`` decorator) over
//!   a mortar bed.
//! - `Mosaic (3)` — small jittered quad pavers tessellating the
//!   region; each paver fills with the base / highlight palette
//!   keyed off its tile-cell parity.
//!
//! Brick (style = 1, Phase 2.4b):
//! - `RunningBond (0)` — every brick a stretcher; rows offset by
//!   half a brick-width for the classic half-bond stagger.
//! - `EnglishBond (1)` — alternating courses of stretchers and
//!   square headers, banded layers by row parity.
//! - `FlemishBond (2)` — each row alternates stretcher + header
//!   pairs; rows offset by half a (stretcher + header) unit.
//!
//! Flagstone (style = 2, Phase 2.4c, no sub-patterns):
//! - Each 32 px tile splits into a 2×2 grid of pentagonal plates
//!   with seed-jittered corners; the joint between plates is the
//!   deep palette.shadow stroke.
//!
//! OpusRomano (style = 3, Phase 2.4d, no sub-patterns):
//! - Versailles pattern. Each 32 px tile splits into a 6×6
//!   subsquare grid with four stones (one 4×4 paver + 2×4 + 2×2
//!   + 4×2 trio); tile rotation is derived from tile coords so
//!   the pattern reads as a coherent tessellation across tiles.
//!
//! FieldStone (style = 4, Phase 2.4e, no sub-patterns):
//! - Irregular polygonal hewn stones tessellating the region; each
//!   ~16 px cell hosts a 5-7-sided polygon with seed-jittered radii
//!   so the stones read as fitted natural fieldstone.
//!
//! Pinwheel (style = 5, Phase 2.4f, no sub-patterns):
//! - 5-stone pinwheel unit tiling. Each 16×16 unit hosts one 8×8
//!   centre paver plus four perimeter rectangles (12×4 top, 4×12
//!   right, 12×4 bottom, 4×12 left) rotating around the centre.
//!
//! Hopscotch (style = 6, Phase 2.4g, no sub-patterns):
//! - 3-stone unit alternating one 12×12 square + a perimeter
//!   rectangle pair, rotated per-unit (`(ix*7 + iy*13) % 4`) so
//!   adjacent units read as a hopscotch pattern.
//!
//! CrazyPaving (style = 7, Phase 2.4h, no sub-patterns):
//! - Variable-size jittered slab tessellation. Walks rows with
//!   seed-driven row heights (12-22 px) and cell widths (12-22
//!   px); each cell becomes one quadrilateral with seed-jittered
//!   corners.
//!
//! The remaining one Stone style (Ashlar with 2 sub-patterns)
//! keeps its flat-fill behaviour; lifts ride Phase 2.4i follow-on.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::material::{fill_region, Material};
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOp, PathOps, Rect,
    Stroke, Vec2,
};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct StonePalette {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

const fn entry(base: u32, highlight: u32, shadow: u32) -> StonePalette {
    StonePalette {
        base: hex(base),
        highlight: hex(highlight),
        shadow: hex(shadow),
    }
}

const fn hex(rgb: u32) -> Color {
    Color::rgba(
        ((rgb >> 16) & 0xFF) as u8,
        ((rgb >> 8) & 0xFF) as u8,
        (rgb & 0xFF) as u8,
        1.0,
    )
}

/// Cobblestone — rounded stone fill ``#C8BEB0`` over mortar
/// ``#9A8A7A`` (lifted from primitives/cobblestone.rs's
/// ``STONE_FILL`` / ``STONE_STROKE`` / ``COBBLE_STROKE``).
const COBBLESTONE: StonePalette = entry(0xC8BEB0, 0xD8D0C2, 0x9A8A7A);

/// Brick — terracotta brick over mortar (lifted from
/// primitives/brick.rs's ``BRICK_STROKE``; base is the visible
/// brick face, shadow is the mortar joint).
const BRICK: StonePalette = entry(0xB8553F, 0xD8826B, 0xA05530);

/// Flagstone — large irregular stones with deep mortar joints.
/// Base is the v4 ``DungeonFloor`` white (the floor paint shows
/// between the joints); shadow is the joint stroke
/// (``FLAGSTONE_STROKE`` from primitives/flagstone.rs).
const FLAGSTONE: StonePalette = entry(0xE8E0D2, 0xF5F0E8, 0x6A6055);

/// OpusRomano — irregular polygonal pavers with a brown mortar
/// (``OPUS_ROMANO_STROKE`` from primitives/opus_romano.rs).
const OPUS_ROMANO: StonePalette = entry(0xE8DCC4, 0xF5ECE0, 0x7A5A3A);

/// FieldStone — natural fieldstone with greenish patina (lifted
/// from primitives/field_stone.rs's ``FIELD_STONE_FILL`` /
/// ``FIELD_STONE_STROKE``).
const FIELD_STONE: StonePalette = entry(0x8A9A6A, 0xA8B888, 0x4A5A3A);

/// Pinwheel — geometric pinwheel paving; sandy beige stones over
/// dark mortar.
const PINWHEEL: StonePalette = entry(0xCFC2A6, 0xE0D6BC, 0x88775E);

/// Hopscotch — square + rectangle alternation; warm beige.
const HOPSCOTCH: StonePalette = entry(0xD8C9A8, 0xE8DCC4, 0x9A8460);

/// CrazyPaving — irregular randomised stones; grey-green tone.
const CRAZY_PAVING: StonePalette = entry(0xBFB6A6, 0xD0C8B8, 0x807358);

/// Ashlar — dressed cut stone with thin even joints.
const ASHLAR: StonePalette = entry(0xD0C7B6, 0xE2DBCB, 0x988D7A);

const SENTINEL: StonePalette = entry(0xFF00FF, 0xFF00FF, 0xFF00FF);

pub(crate) fn palette(style: u8) -> StonePalette {
    match style {
        0 => COBBLESTONE,
        1 => BRICK,
        2 => FLAGSTONE,
        3 => OPUS_ROMANO,
        4 => FIELD_STONE,
        5 => PINWHEEL,
        6 => HOPSCOTCH,
        7 => CRAZY_PAVING,
        8 => ASHLAR,
        _ => SENTINEL,
    }
}

const COBBLE_GROUP_OPACITY: f32 = 0.85;
const BRICK_GROUP_OPACITY: f32 = 0.9;

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    let pal = palette(material.style);
    match material.style {
        // Cobblestone — 4 sub-patterns landed at Phase 2.4a.
        0 => match material.sub_pattern {
            0 => paint_cobblestone_herringbone(painter, region_path, pal, material.seed),
            1 => paint_cobblestone_stack(painter, region_path, pal, material.seed),
            2 => paint_cobblestone_rubble(painter, region_path, pal, material.seed),
            3 => paint_cobblestone_mosaic(painter, region_path, pal, material.seed),
            _ => fill_region(painter, region_path, pal.base),
        },
        // Brick — 3 bonds landed at Phase 2.4b.
        1 => match material.sub_pattern {
            0 => paint_brick_running_bond(painter, region_path, pal, material.seed),
            1 => paint_brick_english_bond(painter, region_path, pal, material.seed),
            2 => paint_brick_flemish_bond(painter, region_path, pal, material.seed),
            _ => fill_region(painter, region_path, pal.base),
        },
        // Flagstone — single layout, no sub-patterns (Phase 2.4c).
        2 => paint_flagstone(painter, region_path, pal, material.seed),
        // OpusRomano — Versailles pattern, no sub-patterns
        // (Phase 2.4d).
        3 => paint_opus_romano(painter, region_path, pal, material.seed),
        // FieldStone — irregular polygonal hewn stones, no
        // sub-patterns (Phase 2.4e).
        4 => paint_field_stone(painter, region_path, pal, material.seed),
        // Pinwheel — 5-stone pinwheel unit tiling, no sub-patterns
        // (Phase 2.4f).
        5 => paint_pinwheel(painter, region_path, pal, material.seed),
        // Hopscotch — 3-stone square+rectangle unit tiling with
        // per-unit rotation (Phase 2.4g).
        6 => paint_hopscotch(painter, region_path, pal, material.seed),
        // CrazyPaving — irregular variable-size slab tessellation,
        // no sub-patterns (Phase 2.4h).
        7 => paint_crazy_paving(painter, region_path, pal, material.seed),
        // Forward-compat sub-pattern values for unknown styles
        // and the remaining 1 style (Phase 2.4i Ashlar with 2 sub-
        // patterns) fall back to flat fill.
        _ => fill_region(painter, region_path, pal.base),
    }
}

// ── Cobblestone sub-pattern algorithms ─────────────────────────

/// Compute axis-aligned bounds of every control / endpoint in the
/// path. Conservative for cubic / quadratic curves (control points
/// can lie outside the actual curve), but cheap and adequate for
/// region paths which are predominantly polygons in current usage.
fn path_bounds(path: &PathOps) -> (f32, f32, f32, f32) {
    let mut min_x = f32::INFINITY;
    let mut min_y = f32::INFINITY;
    let mut max_x = f32::NEG_INFINITY;
    let mut max_y = f32::NEG_INFINITY;
    let mut visit = |p: Vec2| {
        min_x = min_x.min(p.x);
        min_y = min_y.min(p.y);
        max_x = max_x.max(p.x);
        max_y = max_y.max(p.y);
    };
    for op in &path.ops {
        match *op {
            PathOp::MoveTo(p) | PathOp::LineTo(p) => visit(p),
            PathOp::QuadTo(c, p) => {
                visit(c);
                visit(p);
            }
            PathOp::CubicTo(c1, c2, p) => {
                visit(c1);
                visit(c2);
                visit(p);
            }
            PathOp::Close => {}
        }
    }
    (min_x, min_y, max_x, max_y)
}

/// Closed rectangular path centred at `(cx, cy)` with dimensions
/// `(w, h)` rotated by `angle_rad` around the centre. Used by the
/// Herringbone layout for ±45° brick stamps.
fn rotated_rect_path(cx: f64, cy: f64, w: f64, h: f64, angle_rad: f64) -> PathOps {
    let cos_t = angle_rad.cos();
    let sin_t = angle_rad.sin();
    let hw = w * 0.5;
    let hh = h * 0.5;
    let xform = |dx: f64, dy: f64| -> Vec2 {
        let rxv = dx * cos_t - dy * sin_t;
        let ryv = dx * sin_t + dy * cos_t;
        Vec2::new((cx + rxv) as f32, (cy + ryv) as f32)
    };
    let mut path = PathOps::new();
    path.move_to(xform(-hw, -hh));
    path.line_to(xform(hw, -hh));
    path.line_to(xform(hw, hh));
    path.line_to(xform(-hw, hh));
    path.close();
    path
}

/// Closed quadrilateral path through four explicit corners.
fn quad_path(p0: Vec2, p1: Vec2, p2: Vec2, p3: Vec2) -> PathOps {
    let mut path = PathOps::new();
    path.move_to(p0);
    path.line_to(p1);
    path.line_to(p2);
    path.line_to(p3);
    path.close();
    path
}

/// Closed cubic-Bezier ellipse rotated by `angle_rad`. Used by the
/// Rubble layout for irregular per-stone shapes; mirrors the
/// helper in `primitives/cobblestone.rs` so the visual idiom
/// carries forward.
fn rotated_ellipse_path(cx: f64, cy: f64, rx: f64, ry: f64, angle_rad: f64) -> PathOps {
    const KAPPA: f64 = 0.552_284_8;
    let ox = rx * KAPPA;
    let oy = ry * KAPPA;
    let cos_t = angle_rad.cos();
    let sin_t = angle_rad.sin();
    let xform = |dx: f64, dy: f64| -> Vec2 {
        let rxv = dx * cos_t - dy * sin_t;
        let ryv = dx * sin_t + dy * cos_t;
        Vec2::new((cx + rxv) as f32, (cy + ryv) as f32)
    };
    let mut path = PathOps::new();
    path.move_to(xform(rx, 0.0));
    path.cubic_to(xform(rx, oy), xform(ox, ry), xform(0.0, ry));
    path.cubic_to(xform(-ox, ry), xform(-rx, oy), xform(-rx, 0.0));
    path.cubic_to(xform(-rx, -oy), xform(-ox, -ry), xform(0.0, -ry));
    path.cubic_to(xform(ox, -ry), xform(rx, -oy), xform(rx, 0.0));
    path.close();
    path
}

/// Herringbone — ±45° rotated thin bricks tile the region in an
/// alternating chevron grid. Each brick fills with palette.base
/// over a palette.shadow mortar bed.
fn paint_cobblestone_herringbone<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(COBBLE_GROUP_OPACITY);
    let bw = 18.0_f64;
    let bh = 6.0_f64;
    let stride = 9.0_f64;
    let pi4 = std::f64::consts::FRAC_PI_4;
    let base_paint = Paint::solid(pal.base);
    let mut row = 0_i32;
    let mut y = f64::from(y0) - bw;
    while y < f64::from(y1) + bw {
        let mut col = 0_i32;
        let mut x = f64::from(x0) - bw;
        while x < f64::from(x1) + bw {
            let angle = if (row + col).rem_euclid(2) == 0 { pi4 } else { -pi4 };
            let path = rotated_rect_path(x + bw * 0.5, y + bh * 0.5, bw, bh, angle);
            painter.fill_path(&path, &base_paint, FillRule::Winding);
            x += stride;
            col += 1;
        }
        y += stride;
        row += 1;
    }
    painter.end_group();
    painter.pop_clip();
}

/// Stack — square pavers in a regular grid with mortar joints
/// between cells. Pavers alternate base / highlight by parity for
/// subtle two-tone variation.
fn paint_cobblestone_stack<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(COBBLE_GROUP_OPACITY);
    let cell = 12.0_f64;
    let pad = 1.0_f64;
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let mut row = 0_i32;
    let mut y = f64::from(y0);
    while y < f64::from(y1) {
        let mut col = 0_i32;
        let mut x = f64::from(x0);
        while x < f64::from(x1) {
            let pick = if (row + col).rem_euclid(2) == 0 {
                &base_paint
            } else {
                &highlight_paint
            };
            painter.fill_rect(
                Rect::new(
                    (x + pad) as f32,
                    (y + pad) as f32,
                    (cell - 2.0 * pad) as f32,
                    (cell - 2.0 * pad) as f32,
                ),
                pick,
            );
            x += cell;
            col += 1;
        }
        y += cell;
        row += 1;
    }
    painter.end_group();
    painter.pop_clip();
}

/// Rubble — irregular ellipse stones randomly distributed over a
/// mortar bed. Stone density proportional to region area (one
/// stone per ~64 px²); each stone gets seed-driven size + rotation.
fn paint_cobblestone_rubble<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    let w = (x1 - x0) as f64;
    let h = (y1 - y0) as f64;
    if !(w > 0.0 && h > 0.0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(COBBLE_GROUP_OPACITY);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ 0xC0BB1E_u64);
    let area = w * h;
    let n = ((area / 64.0).round() as i32).clamp(1, 4096);
    let base_paint = Paint::solid(pal.base);
    let stroke_paint = Paint::solid(pal.shadow);
    let stroke = Stroke {
        width: 0.4,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    for _ in 0..n {
        let cx = rng.gen_range(f64::from(x0)..f64::from(x1));
        let cy = rng.gen_range(f64::from(y0)..f64::from(y1));
        let rx = rng.gen_range(2.5..5.0);
        let ry = rng.gen_range(2.0..4.0);
        let angle = rng.gen_range(0.0..std::f64::consts::PI);
        let path = rotated_ellipse_path(cx, cy, rx, ry, angle);
        painter.fill_path(&path, &base_paint, FillRule::Winding);
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
    painter.end_group();
    painter.pop_clip();
}

/// Mosaic — small jittered quadrilateral pavers tessellating the
/// region. Each paver corner is offset by a small seed-driven jitter
/// so the tessellation looks hand-laid; pavers alternate base /
/// highlight by cell parity.
fn paint_cobblestone_mosaic<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(COBBLE_GROUP_OPACITY);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ 0x0_5A1C_5A1C_u64);
    let cell = 8.0_f64;
    let jit = cell * 0.18;
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let mut row = 0_i32;
    let mut y = f64::from(y0);
    while y < f64::from(y1) {
        let mut col = 0_i32;
        let mut x = f64::from(x0);
        while x < f64::from(x1) {
            let j = |rng: &mut Pcg64Mcg| rng.gen_range(-jit..jit);
            let p0 = Vec2::new((x + j(&mut rng)) as f32, (y + j(&mut rng)) as f32);
            let p1 = Vec2::new((x + cell + j(&mut rng)) as f32, (y + j(&mut rng)) as f32);
            let p2 = Vec2::new(
                (x + cell + j(&mut rng)) as f32,
                (y + cell + j(&mut rng)) as f32,
            );
            let p3 = Vec2::new((x + j(&mut rng)) as f32, (y + cell + j(&mut rng)) as f32);
            let path = quad_path(p0, p1, p2, p3);
            let pick = if (row + col).rem_euclid(2) == 0 {
                &base_paint
            } else {
                &highlight_paint
            };
            painter.fill_path(&path, pick, FillRule::Winding);
            x += cell;
            col += 1;
        }
        y += cell;
        row += 1;
    }
    painter.end_group();
    painter.pop_clip();
}

// ── Brick sub-pattern algorithms ───────────────────────────────

const BRICK_W: f64 = 16.0;
const BRICK_H: f64 = 6.0;
const BRICK_GAP: f64 = 0.6;

/// RunningBond — every brick is a stretcher (long side horizontal).
/// Each row offset by half a brick-width for the classic
/// half-bond stagger. Brick face fills with palette.base over a
/// palette.shadow mortar bed.
fn paint_brick_running_bond<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(BRICK_GROUP_OPACITY);
    let row_h = BRICK_H + BRICK_GAP;
    let col_w = BRICK_W + BRICK_GAP;
    let base_paint = Paint::solid(pal.base);
    let mut row = 0_i32;
    let mut y = f64::from(y0);
    while y < f64::from(y1) {
        let row_offset = if (row & 1) == 0 { 0.0 } else { -BRICK_W * 0.5 };
        let mut x = f64::from(x0) + row_offset - col_w;
        while x < f64::from(x1) {
            painter.fill_rect(
                Rect::new(
                    x as f32,
                    y as f32,
                    (BRICK_W - BRICK_GAP) as f32,
                    (BRICK_H - BRICK_GAP) as f32,
                ),
                &base_paint,
            );
            x += col_w;
        }
        y += row_h;
        row += 1;
    }
    painter.end_group();
    painter.pop_clip();
}

/// EnglishBond — alternating courses: one row of stretchers (long
/// side horizontal, palette.base) followed by one row of headers
/// (square brick ends, palette.highlight). The classic English
/// bond pattern reads as banded layers.
fn paint_brick_english_bond<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(BRICK_GROUP_OPACITY);
    let row_h = BRICK_H + BRICK_GAP;
    let stretcher_w = BRICK_W + BRICK_GAP;
    let header_w = BRICK_H + BRICK_GAP;
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let mut row = 0_i32;
    let mut y = f64::from(y0);
    while y < f64::from(y1) {
        if (row & 1) == 0 {
            let mut x = f64::from(x0);
            while x < f64::from(x1) {
                painter.fill_rect(
                    Rect::new(
                        x as f32,
                        y as f32,
                        (BRICK_W - BRICK_GAP) as f32,
                        (BRICK_H - BRICK_GAP) as f32,
                    ),
                    &base_paint,
                );
                x += stretcher_w;
            }
        } else {
            let mut x = f64::from(x0);
            while x < f64::from(x1) {
                painter.fill_rect(
                    Rect::new(
                        x as f32,
                        y as f32,
                        (BRICK_H - BRICK_GAP) as f32,
                        (BRICK_H - BRICK_GAP) as f32,
                    ),
                    &highlight_paint,
                );
                x += header_w;
            }
        }
        y += row_h;
        row += 1;
    }
    painter.end_group();
    painter.pop_clip();
}

/// FlemishBond — each row alternates stretcher + header pairs;
/// successive rows offset by half a (stretcher + header) unit so
/// the headers form a vertical staggered grid through the wall.
fn paint_brick_flemish_bond<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(BRICK_GROUP_OPACITY);
    let row_h = BRICK_H + BRICK_GAP;
    let unit_w = BRICK_W + BRICK_H + 2.0 * BRICK_GAP;
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let mut row = 0_i32;
    let mut y = f64::from(y0);
    while y < f64::from(y1) {
        let row_offset = if (row & 1) == 0 { 0.0 } else { -unit_w * 0.5 };
        let mut x = f64::from(x0) + row_offset - unit_w;
        while x < f64::from(x1) {
            painter.fill_rect(
                Rect::new(
                    x as f32,
                    y as f32,
                    (BRICK_W - BRICK_GAP) as f32,
                    (BRICK_H - BRICK_GAP) as f32,
                ),
                &base_paint,
            );
            let hx = x + BRICK_W + BRICK_GAP;
            painter.fill_rect(
                Rect::new(
                    hx as f32,
                    y as f32,
                    (BRICK_H - BRICK_GAP) as f32,
                    (BRICK_H - BRICK_GAP) as f32,
                ),
                &highlight_paint,
            );
            x += unit_w;
        }
        y += row_h;
        row += 1;
    }
    painter.end_group();
    painter.pop_clip();
}

// ── Flagstone (no sub-patterns) ────────────────────────────────

const FLAGSTONE_GROUP_OPACITY: f32 = 0.85;
const FLAGSTONE_TILE: f64 = 32.0;

/// Flagstone — large irregular pentagonal stones with deep mortar
/// joints. Each 32 px tile splits into a 2×2 grid of pentagonal
/// plates with seed-jittered corners; the joint between plates is
/// the deep palette.shadow stroke. Algorithm spirit lifted from
/// the v4 ``primitives/flagstone.rs`` decorator (which strokes
/// only over a transparent floor); v5 substrate emit ships the
/// palette.base flagstone fill underneath so the whole region
/// reads as flagstone rather than dungeon white.
fn paint_flagstone<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.base);
    painter.begin_group(FLAGSTONE_GROUP_OPACITY);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ 0xF1A6_5701_F1A6_5701_u64);
    let half = FLAGSTONE_TILE * 0.5;
    let inset = half * 0.08;
    let stroke_paint = Paint::solid(pal.shadow);
    let stroke = Stroke {
        width: 0.6,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    let tile_x0 = (f64::from(x0) / FLAGSTONE_TILE).floor() * FLAGSTONE_TILE;
    let tile_y0 = (f64::from(y0) / FLAGSTONE_TILE).floor() * FLAGSTONE_TILE;
    let mut ty = tile_y0;
    while ty < f64::from(y1) {
        let mut tx = tile_x0;
        while tx < f64::from(x1) {
            for qy in 0..2 {
                for qx in 0..2 {
                    let cx = tx + f64::from(qx) * half;
                    let cy = ty + f64::from(qy) * half;
                    let mut j = || rng.gen_range(-half * 0.07..half * 0.07);
                    let p0 = Vec2::new(
                        (cx + inset + j()) as f32,
                        (cy + inset + j()) as f32,
                    );
                    let p1 = Vec2::new(
                        (cx + half * 0.5 + j()) as f32,
                        (cy + inset * 0.5 + j()) as f32,
                    );
                    let p2 = Vec2::new(
                        (cx + half - inset + j()) as f32,
                        (cy + inset + j()) as f32,
                    );
                    let p3 = Vec2::new(
                        (cx + half - inset + j()) as f32,
                        (cy + half - inset + j()) as f32,
                    );
                    let p4 = Vec2::new(
                        (cx + inset + j()) as f32,
                        (cy + half - inset + j()) as f32,
                    );
                    let mut path = PathOps::with_capacity(6);
                    path.move_to(p0)
                        .line_to(p1)
                        .line_to(p2)
                        .line_to(p3)
                        .line_to(p4)
                        .close();
                    painter.stroke_path(&path, &stroke_paint, &stroke);
                }
            }
            tx += FLAGSTONE_TILE;
        }
        ty += FLAGSTONE_TILE;
    }
    painter.end_group();
    painter.pop_clip();
}

// ── OpusRomano (no sub-patterns) ───────────────────────────────

const OPUS_ROMANO_GROUP_OPACITY: f32 = 0.85;
const OPUS_ROMANO_TILE: f64 = 32.0;
const OPUS_ROMANO_SUBDIVISIONS: i32 = 6;
const OPUS_ROMANO_INSET: f64 = 0.5;
/// Versailles-pattern 4-stone arrangement on a 6×6 subsquare grid:
/// `(sub_x, sub_y, sub_w, sub_h)`. Lifted from the v4
/// ``primitives/opus_romano.rs::STONES``.
const OPUS_ROMANO_STONES: [(i32, i32, i32, i32); 4] = [
    (0, 0, 4, 4),
    (4, 0, 2, 4),
    (0, 4, 2, 2),
    (2, 4, 4, 2),
];

fn opus_romano_rotate(
    sx: i32, sy: i32, sw: i32, sh: i32, n_quarter: i32,
) -> (i32, i32, i32, i32) {
    let mut s = (sx, sy, sw, sh);
    let n = ((n_quarter % 4) + 4) % 4;
    for _ in 0..n {
        s = (OPUS_ROMANO_SUBDIVISIONS - s.1 - s.3, s.0, s.3, s.2);
    }
    s
}

/// OpusRomano — Versailles pattern. Each 32 px tile splits into a
/// 6×6 subsquare grid with four stones arranged as one large
/// 4×4 paver + a 2×4 + 2×2 + 4×2 trio. Tile rotation is derived
/// from the tile coords (`(tx * 7 + ty * 13) % 4`) so adjacent
/// tiles read as a single visually-coherent pattern. Stones
/// alternate base / highlight by stone index for two-tone variation
/// over a palette.shadow mortar bed. Algorithm spirit lifted from
/// the v4 ``primitives/opus_romano.rs`` decorator.
fn paint_opus_romano<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(OPUS_ROMANO_GROUP_OPACITY);
    let sub = OPUS_ROMANO_TILE / f64::from(OPUS_ROMANO_SUBDIVISIONS);
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let tile_x0 = (f64::from(x0) / OPUS_ROMANO_TILE).floor() * OPUS_ROMANO_TILE;
    let tile_y0 = (f64::from(y0) / OPUS_ROMANO_TILE).floor() * OPUS_ROMANO_TILE;
    let mut ty = tile_y0;
    while ty < f64::from(y1) {
        let mut tx = tile_x0;
        while tx < f64::from(x1) {
            let tile_ix = (tx / OPUS_ROMANO_TILE) as i32;
            let tile_iy = (ty / OPUS_ROMANO_TILE) as i32;
            let rotation = (tile_ix * 7 + tile_iy * 13).rem_euclid(4);
            for (idx, &(sx, sy, sw, sh)) in OPUS_ROMANO_STONES.iter().enumerate() {
                let (sx, sy, sw, sh) = opus_romano_rotate(sx, sy, sw, sh, rotation);
                let xx = tx + f64::from(sx) * sub + OPUS_ROMANO_INSET;
                let yy = ty + f64::from(sy) * sub + OPUS_ROMANO_INSET;
                let w = f64::from(sw) * sub - 2.0 * OPUS_ROMANO_INSET;
                let h = f64::from(sh) * sub - 2.0 * OPUS_ROMANO_INSET;
                let pick = if idx & 1 == 0 { &base_paint } else { &highlight_paint };
                painter.fill_rect(
                    Rect::new(xx as f32, yy as f32, w as f32, h as f32),
                    pick,
                );
            }
            tx += OPUS_ROMANO_TILE;
        }
        ty += OPUS_ROMANO_TILE;
    }
    painter.end_group();
    painter.pop_clip();
}

// ── FieldStone (no sub-patterns) ───────────────────────────────

const FIELD_STONE_GROUP_OPACITY: f32 = 0.85;
const FIELD_STONE_CELL: f64 = 16.0;

/// FieldStone — irregular polygonal hewn stones tessellating the
/// region. Each ~16 px cell hosts one polygon stone with 5-7 sides
/// and seed-jittered radii; cells overlap slightly so the stones
/// read as fitted natural fieldstone rather than a regular grid.
/// Algorithm spirit lifted from the v4 ``primitives/field_stone.rs``
/// decorator (which used 10% probability ellipses); v5 substrate
/// emit needs every cell painted, so density is increased and the
/// shape shifts from ellipse to irregular polygon for visual
/// differentiation from Cobblestone Rubble.
fn paint_field_stone<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(FIELD_STONE_GROUP_OPACITY);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ 0xF1E1_D570_F1E1_D570_u64);
    let base_paint = Paint::solid(pal.base);
    let stroke_paint = Paint::solid(pal.shadow);
    let stroke = Stroke {
        width: 0.5,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    };
    let cell_x0 = (f64::from(x0) / FIELD_STONE_CELL).floor() * FIELD_STONE_CELL;
    let cell_y0 = (f64::from(y0) / FIELD_STONE_CELL).floor() * FIELD_STONE_CELL;
    let mut ty = cell_y0;
    while ty < f64::from(y1) {
        let mut tx = cell_x0;
        while tx < f64::from(x1) {
            let cx = tx + FIELD_STONE_CELL * 0.5
                + rng.gen_range(-FIELD_STONE_CELL * 0.20..FIELD_STONE_CELL * 0.20);
            let cy = ty + FIELD_STONE_CELL * 0.5
                + rng.gen_range(-FIELD_STONE_CELL * 0.20..FIELD_STONE_CELL * 0.20);
            let n_sides = rng.gen_range(5..=7);
            let radius = FIELD_STONE_CELL * rng.gen_range(0.42..0.58);
            let mut path = PathOps::new();
            for i in 0..n_sides {
                let theta = f64::from(i) * std::f64::consts::TAU / f64::from(n_sides);
                let r = radius * rng.gen_range(0.80..1.15);
                let px = cx + r * theta.cos();
                let py = cy + r * theta.sin();
                let pt = Vec2::new(px as f32, py as f32);
                if i == 0 {
                    path.move_to(pt);
                } else {
                    path.line_to(pt);
                }
            }
            path.close();
            painter.fill_path(&path, &base_paint, FillRule::Winding);
            painter.stroke_path(&path, &stroke_paint, &stroke);
            tx += FIELD_STONE_CELL;
        }
        ty += FIELD_STONE_CELL;
    }
    painter.end_group();
    painter.pop_clip();
}

// ── Pinwheel (no sub-patterns) ─────────────────────────────────

const PINWHEEL_GROUP_OPACITY: f32 = 0.9;
const PINWHEEL_UNIT: f64 = 16.0;
const PINWHEEL_PAD: f64 = 0.5;

/// Pinwheel — 5-stone pinwheel unit tiling. Each 16 × 16 unit
/// hosts one 8×8 centre paver plus four perimeter rectangles
/// (12×4 top, 4×12 right, 12×4 bottom, 4×12 left) rotating around
/// the centre like a windmill blade. Adjacent units alternate
/// base / highlight by parity for two-tone variation.
/// RNG-free — geometry is purely tile-derived.
fn paint_pinwheel<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(PINWHEEL_GROUP_OPACITY);
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let unit_x0 = (f64::from(x0) / PINWHEEL_UNIT).floor() * PINWHEEL_UNIT;
    let unit_y0 = (f64::from(y0) / PINWHEEL_UNIT).floor() * PINWHEEL_UNIT;
    let mut iy = 0_i32;
    let mut ty = unit_y0;
    while ty < f64::from(y1) {
        let mut ix = 0_i32;
        let mut tx = unit_x0;
        while tx < f64::from(x1) {
            let pick = if (ix + iy) & 1 == 0 {
                &base_paint
            } else {
                &highlight_paint
            };
            // 5 stones per unit (A=top, B=right, C=bottom, D=left,
            // E=centre); paddings shave 2*PAD from each axis to
            // expose the mortar bed between stones.
            // A — top-left horizontal arm (12×4)
            painter.fill_rect(
                Rect::new(
                    (tx + PINWHEEL_PAD) as f32,
                    (ty + PINWHEEL_PAD) as f32,
                    (12.0 - 2.0 * PINWHEEL_PAD) as f32,
                    (4.0 - 2.0 * PINWHEEL_PAD) as f32,
                ),
                pick,
            );
            // B — top-right vertical arm (4×12)
            painter.fill_rect(
                Rect::new(
                    (tx + 12.0 + PINWHEEL_PAD) as f32,
                    (ty + PINWHEEL_PAD) as f32,
                    (4.0 - 2.0 * PINWHEEL_PAD) as f32,
                    (12.0 - 2.0 * PINWHEEL_PAD) as f32,
                ),
                pick,
            );
            // C — bottom-right horizontal arm (12×4)
            painter.fill_rect(
                Rect::new(
                    (tx + 4.0 + PINWHEEL_PAD) as f32,
                    (ty + 12.0 + PINWHEEL_PAD) as f32,
                    (12.0 - 2.0 * PINWHEEL_PAD) as f32,
                    (4.0 - 2.0 * PINWHEEL_PAD) as f32,
                ),
                pick,
            );
            // D — bottom-left vertical arm (4×12)
            painter.fill_rect(
                Rect::new(
                    (tx + PINWHEEL_PAD) as f32,
                    (ty + 4.0 + PINWHEEL_PAD) as f32,
                    (4.0 - 2.0 * PINWHEEL_PAD) as f32,
                    (12.0 - 2.0 * PINWHEEL_PAD) as f32,
                ),
                pick,
            );
            // E — centre square (8×8)
            painter.fill_rect(
                Rect::new(
                    (tx + 4.0 + PINWHEEL_PAD) as f32,
                    (ty + 4.0 + PINWHEEL_PAD) as f32,
                    (8.0 - 2.0 * PINWHEEL_PAD) as f32,
                    (8.0 - 2.0 * PINWHEEL_PAD) as f32,
                ),
                pick,
            );
            tx += PINWHEEL_UNIT;
            ix += 1;
        }
        ty += PINWHEEL_UNIT;
        iy += 1;
    }
    painter.end_group();
    painter.pop_clip();
}

// ── Hopscotch (no sub-patterns) ────────────────────────────────

const HOPSCOTCH_GROUP_OPACITY: f32 = 0.9;
const HOPSCOTCH_UNIT: f64 = 16.0;
const HOPSCOTCH_PAD: f64 = 0.5;

/// Three-stone unit (sx, sy, sw, sh) on the 16-unit grid: a 12×12
/// square plus a 4×12 perimeter rectangle plus a 16×4 bottom
/// rectangle. Per-unit rotation is `(tx*7 + ty*13) % 4` (same
/// quarter-turn idiom as OpusRomano).
const HOPSCOTCH_STONES: [(f64, f64, f64, f64); 3] = [
    (0.0, 0.0, 12.0, 12.0),
    (12.0, 0.0, 4.0, 12.0),
    (0.0, 12.0, 16.0, 4.0),
];

fn hopscotch_rotate(
    sx: f64, sy: f64, sw: f64, sh: f64, n_quarter: i32,
) -> (f64, f64, f64, f64) {
    let mut s = (sx, sy, sw, sh);
    let n = ((n_quarter % 4) + 4) % 4;
    for _ in 0..n {
        s = (HOPSCOTCH_UNIT - s.1 - s.3, s.0, s.3, s.2);
    }
    s
}

/// Hopscotch — 3-stone unit alternating one 12×12 square + a
/// perimeter rectangle pair, rotated per-unit so adjacent units
/// read as a hopscotch pattern rather than a uniform grid. The
/// square fills with palette.base; the rectangles fill with
/// palette.highlight for two-tone variation. RNG-free —
/// per-unit rotation is derived from unit indices.
fn paint_hopscotch<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    _seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(HOPSCOTCH_GROUP_OPACITY);
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let unit_x0 = (f64::from(x0) / HOPSCOTCH_UNIT).floor() * HOPSCOTCH_UNIT;
    let unit_y0 = (f64::from(y0) / HOPSCOTCH_UNIT).floor() * HOPSCOTCH_UNIT;
    let mut ty = unit_y0;
    while ty < f64::from(y1) {
        let mut tx = unit_x0;
        while tx < f64::from(x1) {
            let ix = (tx / HOPSCOTCH_UNIT) as i32;
            let iy = (ty / HOPSCOTCH_UNIT) as i32;
            let rotation = (ix * 7 + iy * 13).rem_euclid(4);
            for (idx, &(sx, sy, sw, sh)) in HOPSCOTCH_STONES.iter().enumerate() {
                let (sx, sy, sw, sh) = hopscotch_rotate(sx, sy, sw, sh, rotation);
                let pick = if idx == 0 { &base_paint } else { &highlight_paint };
                painter.fill_rect(
                    Rect::new(
                        (tx + sx + HOPSCOTCH_PAD) as f32,
                        (ty + sy + HOPSCOTCH_PAD) as f32,
                        (sw - 2.0 * HOPSCOTCH_PAD) as f32,
                        (sh - 2.0 * HOPSCOTCH_PAD) as f32,
                    ),
                    pick,
                );
            }
            tx += HOPSCOTCH_UNIT;
        }
        ty += HOPSCOTCH_UNIT;
    }
    painter.end_group();
    painter.pop_clip();
}

// ── CrazyPaving (no sub-patterns) ──────────────────────────────

const CRAZY_PAVING_GROUP_OPACITY: f32 = 0.9;

/// CrazyPaving — irregular variable-size slab tessellation. Walks
/// the region in rows of seed-driven variable heights; within each
/// row, walks variable-width cells. Each cell becomes one
/// quadrilateral with seed-jittered corners, alternating base /
/// highlight by the seed so the mosaic reads as randomised paving.
/// Distinct from FieldStone (uniform 16 px cells, polygons) and
/// Cobblestone Mosaic (uniform 8 px cells, jittered quads) by its
/// non-uniform cell sizing — visually closer to crazy-paving.
fn paint_crazy_paving<P: Painter + ?Sized>(
    painter: &mut P,
    region_path: &PathOps,
    pal: StonePalette,
    seed: u64,
) {
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, pal.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, pal.shadow);
    painter.begin_group(CRAZY_PAVING_GROUP_OPACITY);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ 0xC4A2_5DAB_C4A2_5DAB_u64);
    let base_paint = Paint::solid(pal.base);
    let highlight_paint = Paint::solid(pal.highlight);
    let pad = 1.0_f64;
    let jit = 1.5_f64;
    let mut y = f64::from(y0);
    while y < f64::from(y1) {
        let row_h = rng.gen_range(12.0..22.0);
        let mut x = f64::from(x0);
        while x < f64::from(x1) {
            let cell_w = rng.gen_range(12.0..22.0);
            let jx0 = rng.gen_range(-jit..jit);
            let jy0 = rng.gen_range(-jit..jit);
            let jx1 = rng.gen_range(-jit..jit);
            let jy1 = rng.gen_range(-jit..jit);
            let jx2 = rng.gen_range(-jit..jit);
            let jy2 = rng.gen_range(-jit..jit);
            let jx3 = rng.gen_range(-jit..jit);
            let jy3 = rng.gen_range(-jit..jit);
            let p0 = Vec2::new((x + pad + jx0) as f32, (y + pad + jy0) as f32);
            let p1 = Vec2::new(
                (x + cell_w - pad + jx1) as f32,
                (y + pad + jy1) as f32,
            );
            let p2 = Vec2::new(
                (x + cell_w - pad + jx2) as f32,
                (y + row_h - pad + jy2) as f32,
            );
            let p3 = Vec2::new(
                (x + pad + jx3) as f32,
                (y + row_h - pad + jy3) as f32,
            );
            let path = quad_path(p0, p1, p2, p3);
            let pick = if rng.gen::<f64>() < 0.5 {
                &base_paint
            } else {
                &highlight_paint
            };
            painter.fill_path(&path, pick, FillRule::Winding);
            x += cell_w;
        }
        y += row_h;
    }
    painter.end_group();
    painter.pop_clip();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::material::Family;
    use crate::painter::test_util::{MockPainter, PainterCall};
    use crate::painter::Vec2;

    fn one_tile_path() -> PathOps {
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(32.0, 0.0))
            .line_to(Vec2::new(32.0, 32.0))
            .line_to(Vec2::new(0.0, 32.0))
            .close();
        p
    }

    /// Larger 4×4 tile region path — used by sub-pattern tests so
    /// each layout has enough bbox area to emit multiple stamps.
    fn four_tile_path() -> PathOps {
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(128.0, 0.0))
            .line_to(Vec2::new(128.0, 128.0))
            .line_to(Vec2::new(0.0, 128.0))
            .close();
        p
    }

    #[test]
    fn each_style_has_a_distinct_base_colour() {
        let mut bases = Vec::new();
        for style in 0..9u8 {
            let p = palette(style);
            let key = (p.base.r, p.base.g, p.base.b);
            assert!(!bases.contains(&key), "style {style} reuses base {key:?}");
            bases.push(key);
        }
    }

    #[test]
    fn each_style_has_distinct_highlight_and_shadow_from_base() {
        for style in 0..9u8 {
            let p = palette(style);
            assert_ne!(p.base, p.highlight, "style {style}: highlight==base");
            assert_ne!(p.base, p.shadow, "style {style}: shadow==base");
        }
    }

    /// Highlight must be brighter than base and shadow darker. Pins
    /// the visual semantics of the role names so future palette
    /// edits stay coherent.
    #[test]
    fn highlight_is_brighter_and_shadow_is_darker_than_base() {
        let brightness = |c: Color| c.r as u32 + c.g as u32 + c.b as u32;
        for style in 0..9u8 {
            let p = palette(style);
            let b = brightness(p.base);
            let h = brightness(p.highlight);
            let s = brightness(p.shadow);
            assert!(h >= b, "style {style}: highlight ({h}) must be >= base ({b})");
            assert!(s <= b, "style {style}: shadow ({s}) must be <= base ({b})");
        }
    }

    /// The only style without a lifted layout is Ashlar (style=8,
    /// Phase 2.4i). Styles 0–7 lifted in 2.4a–2.4h are excluded
    /// from this gate.
    #[test]
    fn non_lifted_styles_keep_flat_fill() {
        let path = one_tile_path();
        for style in 8..9u8 {
            let expected = palette(style).base;
            let mut p = MockPainter::default();
            let m = Material::new(Family::Stone, style, 0, 0, 0xCAFE);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}: expected 1 call");
            match &p.calls[0] {
                PainterCall::FillPath(_, paint, _) => {
                    assert_eq!(paint.color, expected, "style {style}");
                }
                other => panic!("expected FillPath, got {other:?}"),
            }
        }
    }

    /// Flagstone (style=2, no sub-patterns) wraps decoration in a
    /// push_clip / pop_clip pair plus a balanced begin_group /
    /// end_group envelope, and emits stroked pentagonal plates
    /// (no fill_rect / fill_polygon stamps; the plate interiors
    /// stay transparent so palette.base shows through).
    #[test]
    fn flagstone_emits_stroked_plates_with_clip_envelope() {
        let path = four_tile_path();
        let mut p = MockPainter::default();
        let m = Material::new(Family::Stone, 2, 0, 0, 0xCAFE);
        paint(&mut p, &path, &m);
        assert_eq!(count_pushed_clips(&p.calls), 1, "expected 1 push_clip");
        assert_eq!(count_begin_groups(&p.calls), 1, "expected 1 begin_group");
        let strokes = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::StrokePath(_, _, _)))
            .count();
        assert!(strokes > 4, "expected many stroked plates, got {strokes}");
        let rects = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
            .count();
        assert_eq!(rects, 0, "expected no fill_rect (plates use stroke_path)");
    }

    /// Flagstone is seed-aware: jitter on every plate corner driven
    /// by the seed RNG. Different seeds must diverge.
    #[test]
    fn flagstone_diverges_across_seeds() {
        let path = four_tile_path();
        let mut a = MockPainter::default();
        let mut b = MockPainter::default();
        paint(&mut a, &path, &Material::new(Family::Stone, 2, 0, 0, 333));
        paint(&mut b, &path, &Material::new(Family::Stone, 2, 0, 0, 7));
        assert_ne!(a.calls, b.calls, "seeds must diverge");
    }

    /// OpusRomano (style=3, no sub-patterns) wraps decoration in a
    /// push_clip / pop_clip pair plus a balanced begin_group /
    /// end_group envelope, and emits fill_rect stamps for the
    /// Versailles-pattern stones (4 stones × N tiles).
    #[test]
    fn opus_romano_emits_versailles_stones_with_clip_envelope() {
        let path = four_tile_path();
        let mut p = MockPainter::default();
        let m = Material::new(Family::Stone, 3, 0, 0, 0xCAFE);
        paint(&mut p, &path, &m);
        assert_eq!(count_pushed_clips(&p.calls), 1, "expected 1 push_clip");
        assert_eq!(count_begin_groups(&p.calls), 1, "expected 1 begin_group");
        // 4×4 tile region → 16 tiles × 4 stones = 64 fill_rect.
        let rects = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
            .count();
        assert_eq!(rects, 64, "expected 4 stones × 16 tiles = 64 fill_rect");
        let strokes = p
            .calls
            .iter()
            .filter(|c| {
                matches!(c, PainterCall::StrokePath(_, _, _))
                    || matches!(c, PainterCall::StrokeRect(_, _, _))
            })
            .count();
        assert_eq!(strokes, 0, "OpusRomano must not stroke its stones");
    }

    /// OpusRomano rotation is derived from tile coords, not RNG —
    /// the same region under different seeds must produce identical
    /// painter calls (deterministic, RNG-free).
    #[test]
    fn opus_romano_is_seed_independent() {
        let path = four_tile_path();
        let mut a = MockPainter::default();
        let mut b = MockPainter::default();
        paint(&mut a, &path, &Material::new(Family::Stone, 3, 0, 0, 333));
        paint(&mut b, &path, &Material::new(Family::Stone, 3, 0, 0, 7));
        assert_eq!(
            a.calls, b.calls,
            "OpusRomano is RNG-free — different seeds must produce identical output",
        );
    }

    /// FieldStone (style=4, no sub-patterns) wraps decoration in a
    /// push_clip / pop_clip pair plus a balanced begin_group /
    /// end_group envelope, and emits each polygon stone as a
    /// fill_path + stroke_path pair (irregular polygons rather than
    /// axis-aligned rects).
    #[test]
    fn field_stone_emits_polygon_stones_with_clip_envelope() {
        let path = four_tile_path();
        let mut p = MockPainter::default();
        paint(
            &mut p, &path,
            &Material::new(Family::Stone, 4, 0, 0, 0xCAFE),
        );
        assert_eq!(count_pushed_clips(&p.calls), 1);
        assert_eq!(count_begin_groups(&p.calls), 1);
        let fill_paths = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillPath(_, _, _)))
            .count();
        let stroke_paths = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::StrokePath(_, _, _)))
            .count();
        // Each FieldStone polygon emits a fill_path + stroke_path
        // pair. Plus the mortar bed fill_path (1). Pin pairs balance.
        assert!(fill_paths > 1, "expected mortar + polygon fill_paths");
        assert_eq!(
            fill_paths - 1,
            stroke_paths,
            "polygon fill / stroke counts must match (excluding mortar)",
        );
        let rects = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
            .count();
        assert_eq!(rects, 0, "FieldStone uses polygons, not rects");
    }

    /// FieldStone is seed-aware: stone radii + jitter driven by the
    /// seed RNG. Different seeds must diverge.
    #[test]
    fn field_stone_diverges_across_seeds() {
        let path = four_tile_path();
        let mut a = MockPainter::default();
        let mut b = MockPainter::default();
        paint(&mut a, &path, &Material::new(Family::Stone, 4, 0, 0, 333));
        paint(&mut b, &path, &Material::new(Family::Stone, 4, 0, 0, 7));
        assert_ne!(a.calls, b.calls, "seeds must diverge");
    }

    /// Pinwheel (style=5, no sub-patterns) wraps decoration in a
    /// push_clip / pop_clip pair plus a balanced begin_group /
    /// end_group envelope, and emits exactly 5 fill_rect stamps
    /// per unit (4 perimeter arms + 1 centre square).
    #[test]
    fn pinwheel_emits_five_stones_per_unit_with_clip_envelope() {
        let path = four_tile_path();
        let mut p = MockPainter::default();
        paint(
            &mut p, &path,
            &Material::new(Family::Stone, 5, 0, 0, 0xCAFE),
        );
        assert_eq!(count_pushed_clips(&p.calls), 1);
        assert_eq!(count_begin_groups(&p.calls), 1);
        // 128/16 = 8 units per side → 64 units × 5 stones = 320.
        let rects = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
            .count();
        assert_eq!(rects, 320, "expected 5 stones × 64 units = 320 fill_rect");
        let strokes = p
            .calls
            .iter()
            .filter(|c| {
                matches!(c, PainterCall::StrokePath(_, _, _))
                    || matches!(c, PainterCall::StrokeRect(_, _, _))
            })
            .count();
        assert_eq!(strokes, 0, "Pinwheel must not stroke its stones");
    }

    /// Pinwheel is RNG-free — different seeds must produce
    /// identical painter calls.
    #[test]
    fn pinwheel_is_seed_independent() {
        let path = four_tile_path();
        let mut a = MockPainter::default();
        let mut b = MockPainter::default();
        paint(&mut a, &path, &Material::new(Family::Stone, 5, 0, 0, 333));
        paint(&mut b, &path, &Material::new(Family::Stone, 5, 0, 0, 7));
        assert_eq!(a.calls, b.calls, "Pinwheel is RNG-free");
    }

    /// Hopscotch (style=6, no sub-patterns) wraps decoration in a
    /// push_clip / pop_clip pair plus a balanced begin_group /
    /// end_group envelope, and emits exactly 3 fill_rect stamps
    /// per unit (square + 2 perimeter rects).
    #[test]
    fn hopscotch_emits_three_stones_per_unit_with_clip_envelope() {
        let path = four_tile_path();
        let mut p = MockPainter::default();
        paint(
            &mut p, &path,
            &Material::new(Family::Stone, 6, 0, 0, 0xCAFE),
        );
        assert_eq!(count_pushed_clips(&p.calls), 1);
        assert_eq!(count_begin_groups(&p.calls), 1);
        // 128/16 = 8 units per side → 64 units × 3 stones = 192.
        let rects = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
            .count();
        assert_eq!(rects, 192, "expected 3 stones × 64 units = 192 fill_rect");
    }

    /// Hopscotch is RNG-free — rotation is derived from unit
    /// indices.
    #[test]
    fn hopscotch_is_seed_independent() {
        let path = four_tile_path();
        let mut a = MockPainter::default();
        let mut b = MockPainter::default();
        paint(&mut a, &path, &Material::new(Family::Stone, 6, 0, 0, 333));
        paint(&mut b, &path, &Material::new(Family::Stone, 6, 0, 0, 7));
        assert_eq!(a.calls, b.calls, "Hopscotch is RNG-free");
    }

    /// CrazyPaving (style=7, no sub-patterns) wraps decoration in
    /// a push_clip / pop_clip pair plus a balanced begin_group /
    /// end_group envelope, and emits jittered quad slabs as
    /// fill_path stamps (no fill_rect / stroke).
    #[test]
    fn crazy_paving_emits_quad_slabs_with_clip_envelope() {
        let path = four_tile_path();
        let mut p = MockPainter::default();
        paint(
            &mut p, &path,
            &Material::new(Family::Stone, 7, 0, 0, 0xCAFE),
        );
        assert_eq!(count_pushed_clips(&p.calls), 1);
        assert_eq!(count_begin_groups(&p.calls), 1);
        let fill_paths = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillPath(_, _, _)))
            .count();
        assert!(
            fill_paths > 10,
            "expected many fill_path slabs, got {fill_paths}",
        );
        let strokes = p
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::StrokePath(_, _, _)))
            .count();
        assert_eq!(strokes, 0, "CrazyPaving must not stroke its slabs");
    }

    /// CrazyPaving is seed-aware: row heights, cell widths, and
    /// per-corner jitter all derive from the seed RNG. Different
    /// seeds must diverge.
    #[test]
    fn crazy_paving_diverges_across_seeds() {
        let path = four_tile_path();
        let mut a = MockPainter::default();
        let mut b = MockPainter::default();
        paint(&mut a, &path, &Material::new(Family::Stone, 7, 0, 0, 333));
        paint(&mut b, &path, &Material::new(Family::Stone, 7, 0, 0, 7));
        assert_ne!(a.calls, b.calls, "seeds must diverge");
    }

    /// Forward-compat sub-pattern values for lifted styles
    /// (Cobblestone, Brick) fall back to flat fill rather than
    /// emitting a magenta sentinel.
    #[test]
    fn lifted_styles_unknown_sub_pattern_falls_back_to_flat_fill() {
        let path = one_tile_path();
        for style in [0u8, 1u8] {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Stone, style, 99, 0, 0xCAFE);
            paint(&mut p, &path, &m);
            assert_eq!(p.calls.len(), 1, "style {style}");
            assert!(
                matches!(p.calls[0], PainterCall::FillPath(_, _, _)),
                "style {style}",
            );
        }
    }

    fn count_pushed_clips(calls: &[PainterCall]) -> usize {
        calls
            .iter()
            .filter(|c| matches!(c, PainterCall::PushClip(_, _)))
            .count()
    }

    fn count_begin_groups(calls: &[PainterCall]) -> usize {
        calls
            .iter()
            .filter(|c| matches!(c, PainterCall::BeginGroup(_)))
            .count()
    }

    /// Every Cobblestone sub-pattern wraps its decoration in a
    /// push_clip / pop_clip pair (region clip) and a balanced
    /// begin_group / end_group envelope. Pin both invariants so
    /// future algorithm changes don't drop the clip or the
    /// group-opacity composite.
    #[test]
    fn every_cobblestone_sub_pattern_emits_clip_and_group_envelopes() {
        let path = four_tile_path();
        for sub in 0..4u8 {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Stone, 0, sub, 0, 0xCAFE);
            paint(&mut p, &path, &m);
            assert_eq!(
                count_pushed_clips(&p.calls),
                1,
                "sub_pattern {sub}: expected 1 push_clip",
            );
            assert_eq!(
                count_begin_groups(&p.calls),
                1,
                "sub_pattern {sub}: expected 1 begin_group",
            );
            // Balanced envelopes — every begin_group / push_clip
            // gets its matching close.
            let pops = p
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::PopClip))
                .count();
            let ends = p
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::EndGroup))
                .count();
            assert_eq!(pops, 1, "sub_pattern {sub}: expected 1 pop_clip");
            assert_eq!(ends, 1, "sub_pattern {sub}: expected 1 end_group");
        }
    }

    /// Each Cobblestone sub-pattern emits a distinct call signature
    /// — pin the per-pattern stamp kind so sub-patterns don't
    /// silently degrade to identical output.
    #[test]
    fn cobblestone_sub_patterns_emit_distinct_stamp_kinds() {
        let path = four_tile_path();

        // Herringbone (0): rotated rects → many fill_path stamps,
        // no fill_rect / stroke_path.
        let mut p0 = MockPainter::default();
        paint(
            &mut p0, &path,
            &Material::new(Family::Stone, 0, 0, 0, 0xCAFE),
        );
        let p0_fill_paths = p0.calls.iter().filter(|c| matches!(c, PainterCall::FillPath(_, _, _))).count();
        // The base mortar fill is one fill_path; herringbone bricks add many more.
        assert!(
            p0_fill_paths > 10,
            "Herringbone: expected many fill_path bricks, got {p0_fill_paths}",
        );
        let p0_strokes = p0.calls.iter().filter(|c| matches!(c, PainterCall::StrokePath(_, _, _))).count();
        assert_eq!(p0_strokes, 0, "Herringbone: expected no stroke_path");

        // Stack (1): square pavers → fill_rect stamps.
        let mut p1 = MockPainter::default();
        paint(
            &mut p1, &path,
            &Material::new(Family::Stone, 0, 1, 0, 0xCAFE),
        );
        let p1_rects = p1.calls.iter().filter(|c| matches!(c, PainterCall::FillRect(_, _))).count();
        assert!(p1_rects > 0, "Stack: expected fill_rect pavers");

        // Rubble (2): irregular ellipses → fill_path + stroke_path
        // pairs (each stone strokes its silhouette).
        let mut p2 = MockPainter::default();
        paint(
            &mut p2, &path,
            &Material::new(Family::Stone, 0, 2, 0, 0xCAFE),
        );
        let p2_strokes = p2.calls.iter().filter(|c| matches!(c, PainterCall::StrokePath(_, _, _))).count();
        assert!(p2_strokes > 0, "Rubble: expected stroke_path stones");

        // Mosaic (3): jittered quad pavers → many fill_paths, no
        // strokes (pavers are filled outlines only).
        let mut p3 = MockPainter::default();
        paint(
            &mut p3, &path,
            &Material::new(Family::Stone, 0, 3, 0, 0xCAFE),
        );
        let p3_fill_paths = p3.calls.iter().filter(|c| matches!(c, PainterCall::FillPath(_, _, _))).count();
        let p3_strokes = p3.calls.iter().filter(|c| matches!(c, PainterCall::StrokePath(_, _, _))).count();
        assert!(p3_fill_paths > 1, "Mosaic: expected jittered quad fills");
        assert_eq!(p3_strokes, 0, "Mosaic: expected no stroke_path");
    }

    /// Different seeds drive different RNG streams in Rubble +
    /// Mosaic — the captured call sequence must differ between
    /// seeds for the seed-aware sub-patterns.
    #[test]
    fn cobblestone_seed_aware_sub_patterns_diverge_across_seeds() {
        let path = four_tile_path();
        for sub in [2u8, 3u8] {
            let mut a = MockPainter::default();
            let mut b = MockPainter::default();
            paint(&mut a, &path, &Material::new(Family::Stone, 0, sub, 0, 333));
            paint(&mut b, &path, &Material::new(Family::Stone, 0, sub, 0, 7));
            assert_ne!(
                a.calls, b.calls,
                "sub_pattern {sub}: different seeds must diverge",
            );
        }
    }

    /// Every Brick sub-pattern wraps decoration in a push_clip /
    /// pop_clip pair plus a balanced begin_group / end_group
    /// envelope. Mirrors the Cobblestone gate for Phase 2.4b.
    #[test]
    fn every_brick_sub_pattern_emits_clip_and_group_envelopes() {
        let path = four_tile_path();
        for sub in 0..3u8 {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Stone, 1, sub, 0, 0xCAFE);
            paint(&mut p, &path, &m);
            assert_eq!(
                count_pushed_clips(&p.calls),
                1,
                "brick sub_pattern {sub}: expected 1 push_clip",
            );
            assert_eq!(
                count_begin_groups(&p.calls),
                1,
                "brick sub_pattern {sub}: expected 1 begin_group",
            );
            let pops = p
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::PopClip))
                .count();
            let ends = p
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::EndGroup))
                .count();
            assert_eq!(pops, 1, "brick sub_pattern {sub}: expected 1 pop_clip");
            assert_eq!(ends, 1, "brick sub_pattern {sub}: expected 1 end_group");
        }
    }

    /// Every Brick sub-pattern emits its bricks via fill_rect
    /// stamps over the mortar fill_path (exactly one fill_path for
    /// the mortar bed, no stroke_path / fill_polygon stamps). Pin
    /// the call shape so future algorithm tweaks don't accidentally
    /// switch to stroked outlines.
    #[test]
    fn brick_sub_patterns_emit_only_fill_rect_decoration() {
        let path = four_tile_path();
        for sub in 0..3u8 {
            let mut p = MockPainter::default();
            paint(
                &mut p, &path,
                &Material::new(Family::Stone, 1, sub, 0, 0xCAFE),
            );
            let rects = p
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
                .count();
            let strokes = p
                .calls
                .iter()
                .filter(|c| {
                    matches!(c, PainterCall::StrokePath(_, _, _))
                        || matches!(c, PainterCall::StrokeRect(_, _, _))
                })
                .count();
            assert!(
                rects > 10,
                "brick sub_pattern {sub}: expected many fill_rect bricks, got {rects}",
            );
            assert_eq!(
                strokes, 0,
                "brick sub_pattern {sub}: expected no stroke calls",
            );
        }
    }

    /// The three Brick bonds emit distinct stamp counts on the same
    /// region — RunningBond uses uniform stretchers, EnglishBond
    /// alternates row sizes (header rows pack more bricks),
    /// FlemishBond pairs stretcher + header per cell. Pin that no
    /// two bonds collapse to identical output.
    #[test]
    fn brick_sub_patterns_diverge_across_bonds() {
        let path = four_tile_path();
        let count_rects = |sub: u8| -> usize {
            let mut p = MockPainter::default();
            paint(
                &mut p, &path,
                &Material::new(Family::Stone, 1, sub, 0, 0xCAFE),
            );
            p.calls
                .iter()
                .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
                .count()
        };
        let running = count_rects(0);
        let english = count_rects(1);
        let flemish = count_rects(2);
        // All three counts must differ pairwise — the bond layouts
        // produce visibly distinct masonry.
        assert_ne!(running, english, "RunningBond vs EnglishBond identical count");
        assert_ne!(running, flemish, "RunningBond vs FlemishBond identical count");
        assert_ne!(english, flemish, "EnglishBond vs FlemishBond identical count");
    }
}
