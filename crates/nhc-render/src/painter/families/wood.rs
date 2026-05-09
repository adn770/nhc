//! `Family::Wood` painter — species / tone / sub-pattern dispatch.
//!
//! 12 species (Oak, Walnut, Cherry, Pine, Weathered + the
//! post-Phase-5 deferred-polish additions Mahogany, Ebony, Ash,
//! Maple, Birch, Teak, Bamboo) × 6 tones (Light, Medium, Dark,
//! Charred + the post-Phase-5 additions Bleached, Aged) × 6
//! sub-patterns (Plank, BasketWeave, Parquet, Herringbone +
//! the post-Phase-5 additions Chevron, Brick) = 432 wood
//! combinations. The palette holds 216 colour entries (12
//! species × 6 tones × 3 roles [base, highlight, shadow]);
//! sub-patterns are algorithm-side, not palette-side.
//!
//! Tone semantics: tones 0–3 (Light → Charred) form a strict
//! darkening progression — pinned by
//! ``tones_within_each_species_decrease_in_brightness``. Tones
//! 4 (Bleached) and 5 (Aged) sit OUTSIDE the gradient: Bleached
//! is paler than Light (sun-faded surface), Aged is between
//! Medium and Charred with a grayer patina (weathered surface).
//!
//! Phase 2.3a–d of `plans/nhc_pure_ir_v5_migration_plan.md`. The
//! per-(species, tone) palette is locked (Phase 2.3 baseline);
//! this commit adds the per-sub-pattern seam grids and Plank's
//! per-plank grain noise:
//!
//! - `Plank (0)` — horizontal plank rows (8 px wide) with random
//!   plank lengths (24–72 px); seams at row boundaries + plank
//!   ends. Plus the per-plank grain-noise pass: 2 light/dark
//!   horizontal grain lines per plank wrapped in
//!   `begin_group(0.35)` per the Phase 5.10 group-opacity contract.
//! - `BasketWeave (1)` — 32×32 cells alternating horizontal /
//!   vertical orientation in a checkerboard; per cell, 3 internal
//!   seams parallel to the orientation + 2 boundary seams. Lifted
//!   from the v4 ``primitives/wood_floor.rs::emit_room_seams_basket``
//!   spirit.
//! - `Parquet (2)` — 16×16 4-stick parquet panels alternating
//!   horizontal / vertical orientation; each panel hosts 4
//!   thin planks (4×16) parallel to its orientation.
//! - `Herringbone (3)` — ±45° rotated planks (24×6) tessellating
//!   the region in a chevron-interlock grid (alternating angle
//!   per (row, col) parity).
//!
//! All four sub-patterns share the (palette.base) substrate fill,
//! a push_clip / pop_clip region envelope, and a begin_group / end_
//! group seam composite envelope (opacity 0.7) per the load-bearing
//! group-opacity contract.

use std::f64::consts::FRAC_PI_4;

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::material::{fill_region, Material};
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOp, PathOps, Stroke,
    Vec2,
};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct WoodToneEntry {
    pub base: Color,
    pub highlight: Color,
    pub shadow: Color,
}

const fn entry(base: u32, highlight: u32, shadow: u32) -> WoodToneEntry {
    WoodToneEntry {
        base: hex_to_color(base),
        highlight: hex_to_color(highlight),
        shadow: hex_to_color(shadow),
    }
}

const fn hex_to_color(rgb: u32) -> Color {
    let r = ((rgb >> 16) & 0xFF) as u8;
    let g = ((rgb >> 8) & 0xFF) as u8;
    let b = (rgb & 0xFF) as u8;
    Color::rgba(r, g, b, 1.0)
}

const N_SPECIES: usize = 12;
const N_TONES: usize = 6;

/// 5 species × 4 tones × 3 roles. Light / Medium / Dark are lifted
/// directly from the v4 ``WOOD_SPECIES`` table in
/// ``crates/nhc-render/src/primitives/wood_floor.rs``: the
/// ``(fill, grain_light, grain_dark)`` triple maps to ``(base,
/// highlight, shadow)``. Charred (the new 4th tone) is hand-picked
/// per species so the four tones read as a darkening progression.
// Each row: 6 tones in the order
//   [Light=0, Medium=1, Dark=2, Charred=3, Bleached=4, Aged=5].
// Light → Charred is a strict darkening gradient; Bleached
// (sun-faded surface) sits PALER than Light; Aged (weathered
// surface with patina) sits BETWEEN Medium and Charred with a
// grayer cast.
const WOOD_PALETTE: [[WoodToneEntry; N_TONES]; N_SPECIES] = [
    // Oak — warm tan.
    [
        entry(0xC4A076, 0xD4B690, 0xA88058), // Light
        entry(0xB58B5A, 0xC4A076, 0x8F6540), // Medium
        entry(0x9B7548, 0xAC8A60, 0x7A5530), // Dark
        entry(0x402A18, 0x5A3E26, 0x281810), // Charred
        entry(0xE8D8B8, 0xF2E5C8, 0xC0AC8C), // Bleached
        entry(0x886F58, 0xA08868, 0x5A463A), // Aged
    ],
    // Walnut — deep cocoa, redder hue.
    [
        entry(0x8C6440, 0xA07A55, 0x684A2C),
        entry(0x6E4F32, 0x8B6446, 0x523820),
        entry(0x553820, 0x6E4F32, 0x3F2818),
        entry(0x221810, 0x382A1C, 0x140C08),
        entry(0xC8A088, 0xDCB89C, 0x9C7F65),
        entry(0x5C4838, 0x726046, 0x3A2D24),
    ],
    // Cherry — reddish brown, slight orange.
    [
        entry(0xB07A55, 0xC49075, 0x8E5C3A),
        entry(0x9B6442, 0xB07A55, 0x7A4D2E),
        entry(0x7E4F32, 0x955F44, 0x5F3820),
        entry(0x362018, 0x4C2E22, 0x1E120C),
        entry(0xDCB098, 0xE8C0A8, 0xB48E78),
        entry(0x705548, 0x8A6A5C, 0x4A372E),
    ],
    // Pine — pale honey, the lightest species.
    [
        entry(0xD8B888, 0xE6CDA8, 0xB8966C),
        entry(0xC4A176, 0xD8B888, 0xA48458),
        entry(0xA88556, 0xBFA070, 0x88683C),
        entry(0x443620, 0x5A4A30, 0x2A1F12),
        entry(0xEED8B0, 0xF5E8C8, 0xC4B090),
        entry(0x9E8A6E, 0xB6A088, 0x6E5F4E),
    ],
    // Weathered grey — silvered teak / driftwood.
    [
        entry(0x8A8478, 0xA09A8E, 0x6E695F),
        entry(0x6E695F, 0x8A8478, 0x544F46),
        entry(0x544F46, 0x6E695F, 0x3D3932),
        entry(0x201C18, 0x322E28, 0x100C0A),
        entry(0xC4C0B8, 0xD8D4CC, 0x9C9890),
        entry(0x564F46, 0x6E6759, 0x3A352E),
    ],
    // Mahogany — deep red-brown, classic furniture wood.
    [
        entry(0xB85843, 0xC86F58, 0x8E3F2E),
        entry(0x9C4530, 0xB85843, 0x762E1E),
        entry(0x7A3320, 0x923F2A, 0x592216),
        entry(0x2C1208, 0x401D14, 0x180A04),
        entry(0xDC9888, 0xE8B0A0, 0xB47C6C),
        entry(0x705048, 0x8A6862, 0x4A3328),
    ],
    // Ebony — near-black with subtle warm tint.
    [
        entry(0x4D3E32, 0x5E4E40, 0x3A2D24),
        entry(0x3A2D24, 0x4D3E32, 0x271E16),
        entry(0x271E16, 0x3A2D24, 0x180F0A),
        entry(0x0E0805, 0x1A1108, 0x080402),
        entry(0x988880, 0xB0A098, 0x726660),
        entry(0x261D18, 0x382E26, 0x18120E),
    ],
    // Ash — pale, creamy with subtle grain.
    [
        entry(0xD8CCB4, 0xE6DCC4, 0xAA9D88),
        entry(0xC1B498, 0xD8CCB4, 0x988A70),
        entry(0x9D907A, 0xB2A38B, 0x7A6F58),
        entry(0x3E3424, 0x504432, 0x2C2418),
        entry(0xECE4D0, 0xF6F0DE, 0xC0B8A0),
        entry(0x847C68, 0x9E9684, 0x5A544A),
    ],
    // Maple — warm light beige.
    [
        entry(0xE6CFA0, 0xF0DDB6, 0xB8A074),
        entry(0xC8B080, 0xE6CFA0, 0xA08D5C),
        entry(0xA48E68, 0xBCA47C, 0x806842),
        entry(0x382818, 0x4C3A24, 0x261810),
        entry(0xF0DEB8, 0xF8E8CA, 0xC8B898),
        entry(0x86714F, 0xA08D6E, 0x5A4D38),
    ],
    // Birch — very pale with hint of pink-cream.
    [
        entry(0xE8DEC2, 0xF2EAD2, 0xC0B294),
        entry(0xD2C5A6, 0xE8DEC2, 0xA89A78),
        entry(0xB0A488, 0xC8BCA0, 0x847656),
        entry(0x322820, 0x443830, 0x1F1A12),
        entry(0xF6EED2, 0xFAF4DE, 0xC8C0AC),
        entry(0x8A7E68, 0xA09684, 0x5C5446),
    ],
    // Teak — warm golden-brown with mid-saturation.
    [
        entry(0xC68C5C, 0xD49E72, 0x986C40),
        entry(0xA77548, 0xC68C5C, 0x82582C),
        entry(0x866038, 0x9E7244, 0x624222),
        entry(0x382410, 0x4C3018, 0x281808),
        entry(0xE0B898, 0xECC8AC, 0xB89880),
        entry(0x745548, 0x8E6A5C, 0x4A382E),
    ],
    // Bamboo — pale yellow-tan with linear grain feel.
    [
        entry(0xDDC988, 0xE6D7A4, 0xB59E60),
        entry(0xC4AB68, 0xDDC988, 0xA08848),
        entry(0xA08544, 0xB89C5C, 0x7A642C),
        entry(0x302410, 0x402F18, 0x1E1708),
        entry(0xEEDFB0, 0xF6EAC8, 0xC4B594),
        entry(0x806E50, 0x9C8A68, 0x5A4E3A),
    ],
];

const SENTINEL: WoodToneEntry = WoodToneEntry {
    base: hex_to_color(0xFF00FF),
    highlight: hex_to_color(0xFF00FF),
    shadow: hex_to_color(0xFF00FF),
};

pub(crate) fn palette(style: u8, tone: u8) -> WoodToneEntry {
    let s = style as usize;
    let t = tone as usize;
    if s >= N_SPECIES || t >= N_TONES {
        return SENTINEL;
    }
    WOOD_PALETTE[s][t]
}

const WOOD_SEAM_OPACITY: f32 = 0.7;
const WOOD_GRAIN_OPACITY: f32 = 0.35;
const WOOD_SEAM_WIDTH: f32 = 0.6;
const WOOD_GRAIN_STROKE_WIDTH: f32 = 0.4;
const WOOD_PLANK_WIDTH: f64 = 8.0;
const WOOD_PLANK_LEN_MIN: f64 = 24.0;
const WOOD_PLANK_LEN_MAX: f64 = 72.0;
const WOOD_BASKET_CELL: f64 = 32.0;
const WOOD_PARQUET_CELL: f64 = 16.0;
const WOOD_HERRINGBONE_W: f64 = 24.0;
const WOOD_HERRINGBONE_H: f64 = 6.0;
const WOOD_HERRINGBONE_STRIDE: f64 = 12.0;
// Chevron reuses the herringbone plank dimensions. The pattern
// switches the angle on column-parity only (vs. herringbone's
// (row + col) parity), so each row stacks identical V-units
// vertically rather than interlocking diagonals.
const WOOD_BRICK_W: f64 = 24.0;
const WOOD_BRICK_H: f64 = 8.0;

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    let entry = palette(material.style, material.tone);
    if material.sub_pattern > 5 {
        // Forward-compat: unknown sub-patterns paint base fill only.
        fill_region(painter, region_path, entry.base);
        return;
    }
    let (x0, y0, x1, y1) = path_bounds(region_path);
    if !(x1 > x0 && y1 > y0) {
        fill_region(painter, region_path, entry.base);
        return;
    }
    painter.push_clip(region_path, FillRule::Winding);
    fill_region(painter, region_path, entry.base);
    match material.sub_pattern {
        0 => paint_plank(painter, x0, y0, x1, y1, entry, material.seed),
        1 => paint_basket_weave(painter, x0, y0, x1, y1, entry),
        2 => paint_parquet(painter, x0, y0, x1, y1, entry),
        3 => paint_herringbone(painter, x0, y0, x1, y1, entry),
        4 => paint_chevron(painter, x0, y0, x1, y1, entry),
        5 => paint_brick(painter, x0, y0, x1, y1, entry),
        _ => unreachable!(),
    }
    painter.pop_clip();
}

// ── Helpers ────────────────────────────────────────────────────

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

fn line_path(x1: f64, y1: f64, x2: f64, y2: f64) -> PathOps {
    let mut path = PathOps::new();
    path.move_to(Vec2::new(x1 as f32, y1 as f32));
    path.line_to(Vec2::new(x2 as f32, y2 as f32));
    path
}

fn seam_stroke() -> Stroke {
    Stroke {
        width: WOOD_SEAM_WIDTH,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    }
}

fn grain_stroke() -> Stroke {
    Stroke {
        width: WOOD_GRAIN_STROKE_WIDTH,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    }
}

// ── Plank (sub_pattern = 0) ────────────────────────────────────

/// Plank — horizontal plank rows with random plank lengths and
/// per-plank grain noise. Seams are stroked palette.shadow at
/// row boundaries + at plank ends inside each row. Grain noise
/// is two horizontal lines per plank stroked with palette.highlight
/// inside a `begin_group(0.35)` envelope per the Phase 5.10
/// contract.
fn paint_plank<P: Painter + ?Sized>(
    painter: &mut P,
    x0: f32, y0: f32, x1: f32, y1: f32,
    entry: WoodToneEntry,
    seed: u64,
) {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let shadow_paint = Paint::solid(entry.shadow);
    let highlight_paint = Paint::solid(entry.highlight);
    let stroke = seam_stroke();
    let grain = grain_stroke();
    let row_h = WOOD_PLANK_WIDTH;
    let bx0 = f64::from(x0);
    let by0 = f64::from(y0);
    let bx1 = f64::from(x1);
    let by1 = f64::from(y1);

    // Seam pass — row boundary horizontals + per-plank vertical
    // ends. Plank end positions cached for the grain pass below.
    type RowPlanks = Vec<(f64, f64, f64)>; // (x_start, x_end, y_top)
    let mut planks: Vec<RowPlanks> = Vec::new();

    painter.begin_group(WOOD_SEAM_OPACITY);
    let mut y = by0;
    while y < by1 {
        let row_planks: &mut RowPlanks = {
            planks.push(Vec::new());
            planks.last_mut().unwrap()
        };
        let mut x_start = bx0;
        let mut x_end = bx0 + rng.gen_range(WOOD_PLANK_LEN_MIN..WOOD_PLANK_LEN_MAX);
        while x_end < bx1 {
            row_planks.push((x_start, x_end, y));
            painter.stroke_path(
                &line_path(x_end, y, x_end, (y + row_h).min(by1)),
                &shadow_paint,
                &stroke,
            );
            x_start = x_end;
            x_end += rng.gen_range(WOOD_PLANK_LEN_MIN..WOOD_PLANK_LEN_MAX);
        }
        row_planks.push((x_start, bx1, y));
        y += row_h;
        if y < by1 {
            painter.stroke_path(
                &line_path(bx0, y, bx1, y),
                &shadow_paint,
                &stroke,
            );
        }
    }
    painter.end_group();

    // Grain pass — 2 jittered horizontal grain lines per plank,
    // stroked with the highlight tone at 0.35 opacity. Plank ends
    // taper the lines slightly so adjacent plank grains don't blend.
    painter.begin_group(WOOD_GRAIN_OPACITY);
    for row in &planks {
        for &(px0, px1, py) in row {
            let span_w = px1 - px0;
            let span_h = row_h;
            if span_w < 4.0 || span_h < 2.0 {
                continue;
            }
            for _ in 0..2 {
                let gy = py + rng.gen_range(span_h * 0.18..span_h * 0.82);
                let inset = span_w * 0.10;
                painter.stroke_path(
                    &line_path(px0 + inset, gy, px1 - inset, gy),
                    &highlight_paint,
                    &grain,
                );
            }
        }
    }
    painter.end_group();
}

// ── BasketWeave (sub_pattern = 1) ──────────────────────────────

/// BasketWeave — 32×32 cells in a checkerboard alternating
/// horizontal / vertical plank orientation. Each cell hosts 3
/// internal seams parallel to its orientation + 2 boundary seams
/// perpendicular to it. RNG-free.
fn paint_basket_weave<P: Painter + ?Sized>(
    painter: &mut P,
    x0: f32, y0: f32, x1: f32, y1: f32,
    entry: WoodToneEntry,
) {
    let shadow_paint = Paint::solid(entry.shadow);
    let stroke = seam_stroke();
    painter.begin_group(WOOD_SEAM_OPACITY);
    let cell_x0 = (f64::from(x0) / WOOD_BASKET_CELL).floor() * WOOD_BASKET_CELL;
    let cell_y0 = (f64::from(y0) / WOOD_BASKET_CELL).floor() * WOOD_BASKET_CELL;
    let bx1 = f64::from(x1);
    let by1 = f64::from(y1);
    let mut iy = 0_i32;
    let mut cy = cell_y0;
    while cy < by1 {
        let mut ix = 0_i32;
        let mut cx = cell_x0;
        while cx < bx1 {
            let horizontal = (ix + iy) & 1 == 0;
            if horizontal {
                let mut k = 1.0_f64;
                while k * WOOD_PLANK_WIDTH < WOOD_BASKET_CELL {
                    let sy = cy + k * WOOD_PLANK_WIDTH;
                    painter.stroke_path(
                        &line_path(cx, sy, cx + WOOD_BASKET_CELL, sy),
                        &shadow_paint,
                        &stroke,
                    );
                    k += 1.0;
                }
                painter.stroke_path(
                    &line_path(cx, cy, cx, cy + WOOD_BASKET_CELL),
                    &shadow_paint,
                    &stroke,
                );
                painter.stroke_path(
                    &line_path(
                        cx + WOOD_BASKET_CELL, cy,
                        cx + WOOD_BASKET_CELL, cy + WOOD_BASKET_CELL,
                    ),
                    &shadow_paint,
                    &stroke,
                );
            } else {
                let mut k = 1.0_f64;
                while k * WOOD_PLANK_WIDTH < WOOD_BASKET_CELL {
                    let sx = cx + k * WOOD_PLANK_WIDTH;
                    painter.stroke_path(
                        &line_path(sx, cy, sx, cy + WOOD_BASKET_CELL),
                        &shadow_paint,
                        &stroke,
                    );
                    k += 1.0;
                }
                painter.stroke_path(
                    &line_path(cx, cy, cx + WOOD_BASKET_CELL, cy),
                    &shadow_paint,
                    &stroke,
                );
                painter.stroke_path(
                    &line_path(
                        cx, cy + WOOD_BASKET_CELL,
                        cx + WOOD_BASKET_CELL, cy + WOOD_BASKET_CELL,
                    ),
                    &shadow_paint,
                    &stroke,
                );
            }
            cx += WOOD_BASKET_CELL;
            ix += 1;
        }
        cy += WOOD_BASKET_CELL;
        iy += 1;
    }
    painter.end_group();
}

// ── Parquet (sub_pattern = 2) ──────────────────────────────────

/// Parquet — 16×16 panels in a checkerboard alternating horizontal
/// / vertical plank orientation. Each panel hosts 3 thin seam
/// lines parallel to its orientation (at the plank-width interior
/// grid: 4, 8, 12 px). RNG-free.
fn paint_parquet<P: Painter + ?Sized>(
    painter: &mut P,
    x0: f32, y0: f32, x1: f32, y1: f32,
    entry: WoodToneEntry,
) {
    let shadow_paint = Paint::solid(entry.shadow);
    let stroke = seam_stroke();
    painter.begin_group(WOOD_SEAM_OPACITY);
    let cell_x0 = (f64::from(x0) / WOOD_PARQUET_CELL).floor() * WOOD_PARQUET_CELL;
    let cell_y0 = (f64::from(y0) / WOOD_PARQUET_CELL).floor() * WOOD_PARQUET_CELL;
    let bx1 = f64::from(x1);
    let by1 = f64::from(y1);
    let plank_w = WOOD_PARQUET_CELL / 4.0; // 4 sticks per panel
    let mut iy = 0_i32;
    let mut cy = cell_y0;
    while cy < by1 {
        let mut ix = 0_i32;
        let mut cx = cell_x0;
        while cx < bx1 {
            let horizontal = (ix + iy) & 1 == 0;
            if horizontal {
                for k in 1..4_i32 {
                    let sy = cy + f64::from(k) * plank_w;
                    painter.stroke_path(
                        &line_path(cx, sy, cx + WOOD_PARQUET_CELL, sy),
                        &shadow_paint,
                        &stroke,
                    );
                }
            } else {
                for k in 1..4_i32 {
                    let sx = cx + f64::from(k) * plank_w;
                    painter.stroke_path(
                        &line_path(sx, cy, sx, cy + WOOD_PARQUET_CELL),
                        &shadow_paint,
                        &stroke,
                    );
                }
            }
            // Panel boundary box (always emitted so the panel
            // outline reads cleanly even when neighbours share
            // orientation at region edges).
            painter.stroke_path(
                &line_path(cx, cy, cx + WOOD_PARQUET_CELL, cy),
                &shadow_paint,
                &stroke,
            );
            painter.stroke_path(
                &line_path(cx, cy, cx, cy + WOOD_PARQUET_CELL),
                &shadow_paint,
                &stroke,
            );
            cx += WOOD_PARQUET_CELL;
            ix += 1;
        }
        cy += WOOD_PARQUET_CELL;
        iy += 1;
    }
    painter.end_group();
}

// ── Herringbone (sub_pattern = 3) ──────────────────────────────

/// Closed rectangular path centred at `(cx, cy)` with dimensions
/// `(w, h)` rotated by `angle_rad` around the centre. Used by the
/// Herringbone layout for ±45° plank stamps — same idiom as the
/// Stone family's Cobblestone Herringbone.
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

/// Herringbone — ±45° rotated planks (24×6) tessellating in a
/// chevron-interlock grid; per (row, col) parity flips the plank
/// angle. Each plank fills with palette.shadow at the seam
/// opacity. RNG-free.
fn paint_herringbone<P: Painter + ?Sized>(
    painter: &mut P,
    x0: f32, y0: f32, x1: f32, y1: f32,
    entry: WoodToneEntry,
) {
    let shadow_paint = Paint::solid(entry.shadow);
    let stroke = seam_stroke();
    painter.begin_group(WOOD_SEAM_OPACITY);
    let bx0 = f64::from(x0);
    let by0 = f64::from(y0);
    let bx1 = f64::from(x1);
    let by1 = f64::from(y1);
    let mut row = 0_i32;
    let mut y = by0 - WOOD_HERRINGBONE_W;
    while y < by1 + WOOD_HERRINGBONE_W {
        let mut col = 0_i32;
        let mut x = bx0 - WOOD_HERRINGBONE_W;
        while x < bx1 + WOOD_HERRINGBONE_W {
            let angle = if (row + col).rem_euclid(2) == 0 {
                FRAC_PI_4
            } else {
                -FRAC_PI_4
            };
            let path = rotated_rect_path(
                x + WOOD_HERRINGBONE_W * 0.5,
                y + WOOD_HERRINGBONE_H * 0.5,
                WOOD_HERRINGBONE_W,
                WOOD_HERRINGBONE_H,
                angle,
            );
            painter.stroke_path(&path, &shadow_paint, &stroke);
            x += WOOD_HERRINGBONE_STRIDE;
            col += 1;
        }
        y += WOOD_HERRINGBONE_STRIDE;
        row += 1;
    }
    painter.end_group();
}

// ── Chevron (sub_pattern = 4) ──────────────────────────────────

/// Chevron — ±45° rotated planks with the angle alternating on
/// column-parity only (independent of row), so each row stacks
/// identical V-units vertically. The result reads as a clean
/// chevron march, distinct from Herringbone's interlocking
/// diagonal weave (where the angle flips on (row + col) parity).
/// Same plank dimensions as Herringbone; RNG-free.
fn paint_chevron<P: Painter + ?Sized>(
    painter: &mut P,
    x0: f32, y0: f32, x1: f32, y1: f32,
    entry: WoodToneEntry,
) {
    let shadow_paint = Paint::solid(entry.shadow);
    let stroke = seam_stroke();
    painter.begin_group(WOOD_SEAM_OPACITY);
    let bx0 = f64::from(x0);
    let by0 = f64::from(y0);
    let bx1 = f64::from(x1);
    let by1 = f64::from(y1);
    let mut y = by0 - WOOD_HERRINGBONE_W;
    while y < by1 + WOOD_HERRINGBONE_W {
        let mut col = 0_i32;
        let mut x = bx0 - WOOD_HERRINGBONE_W;
        while x < bx1 + WOOD_HERRINGBONE_W {
            let angle = if col.rem_euclid(2) == 0 {
                FRAC_PI_4
            } else {
                -FRAC_PI_4
            };
            let path = rotated_rect_path(
                x + WOOD_HERRINGBONE_W * 0.5,
                y + WOOD_HERRINGBONE_H * 0.5,
                WOOD_HERRINGBONE_W,
                WOOD_HERRINGBONE_H,
                angle,
            );
            painter.stroke_path(&path, &shadow_paint, &stroke);
            x += WOOD_HERRINGBONE_STRIDE;
            col += 1;
        }
        y += WOOD_HERRINGBONE_STRIDE;
    }
    painter.end_group();
}

// ── Brick (sub_pattern = 5) ────────────────────────────────────

/// Brick — wooden block bond. Rectangular ``WOOD_BRICK_W ×
/// WOOD_BRICK_H`` blocks laid in a half-bond stagger (alternating
/// rows offset by half a brick). Strokes the row boundaries
/// horizontal + per-block vertical seams in palette.shadow over
/// the dispatcher's base fill — no per-block fill_rect since the
/// base shows through the stroked outlines and reads as clean
/// wood-block masonry. RNG-free.
fn paint_brick<P: Painter + ?Sized>(
    painter: &mut P,
    x0: f32, y0: f32, x1: f32, y1: f32,
    entry: WoodToneEntry,
) {
    let shadow_paint = Paint::solid(entry.shadow);
    let stroke = seam_stroke();
    painter.begin_group(WOOD_SEAM_OPACITY);
    let bx0 = f64::from(x0);
    let by0 = f64::from(y0);
    let bx1 = f64::from(x1);
    let by1 = f64::from(y1);
    let mut row = 0_i32;
    let mut y = by0;
    while y < by1 {
        // Row boundary horizontal — skip the very top edge so the
        // dispatcher's base fill carries the surface there.
        if y > by0 {
            painter.stroke_path(
                &line_path(bx0, y, bx1, y),
                &shadow_paint,
                &stroke,
            );
        }
        let row_offset = if (row & 1) == 0 { 0.0 } else { -WOOD_BRICK_W * 0.5 };
        let mut x = bx0 + row_offset;
        // Skip the partial brick that pokes off the left edge on
        // odd rows — its right vertical lands inside the region
        // and we want it to render. Walk in normal step.
        while x < bx1 {
            if x > bx0 {
                painter.stroke_path(
                    &line_path(x, y, x, (y + WOOD_BRICK_H).min(by1)),
                    &shadow_paint,
                    &stroke,
                );
            }
            x += WOOD_BRICK_W;
        }
        y += WOOD_BRICK_H;
        row += 1;
    }
    painter.end_group();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::material::Family;
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn one_tile_path() -> PathOps {
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(32.0, 0.0))
            .line_to(Vec2::new(32.0, 32.0))
            .line_to(Vec2::new(0.0, 32.0))
            .close();
        p
    }

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
    fn every_palette_entry_has_distinct_base_colour() {
        let mut bases = Vec::with_capacity(N_SPECIES * N_TONES);
        for s in 0..N_SPECIES as u8 {
            for t in 0..N_TONES as u8 {
                let entry = palette(s, t);
                assert_ne!(entry.base, entry.highlight, "(s={s}, t={t}) base==highlight");
                assert_ne!(entry.base, entry.shadow, "(s={s}, t={t}) base==shadow");
                let key = (entry.base.r, entry.base.g, entry.base.b);
                assert!(
                    !bases.contains(&key),
                    "duplicate base colour at (s={s}, t={t}): {key:?}"
                );
                bases.push(key);
            }
        }
        assert_eq!(bases.len(), N_SPECIES * N_TONES);
    }

    /// Within a species, the 4 baseline tones must be a darkening
    /// progression: Light > Medium > Dark > Charred (sum of
    /// channels). The post-Phase-5 additions Bleached and Aged
    /// sit OUTSIDE this gradient and are pinned by their own
    /// test below.
    #[test]
    fn tones_within_each_species_decrease_in_brightness() {
        for s in 0..N_SPECIES as u8 {
            let brightness = |t: u8| {
                let c = palette(s, t).base;
                c.r as u32 + c.g as u32 + c.b as u32
            };
            let light = brightness(0);
            let medium = brightness(1);
            let dark = brightness(2);
            let charred = brightness(3);
            assert!(light > medium, "species {s}: Light <= Medium");
            assert!(medium > dark, "species {s}: Medium <= Dark");
            assert!(dark > charred, "species {s}: Dark <= Charred");
        }
    }

    /// Bleached (tone=4) is sun-faded — paler than every species'
    /// Light tone. Aged (tone=5) is weathered with a grayer
    /// patina — sits between Medium and Charred so it reads as
    /// worn but not burnt.
    #[test]
    fn bleached_outranks_light_aged_sits_between_medium_and_charred() {
        for s in 0..N_SPECIES as u8 {
            let brightness = |t: u8| {
                let c = palette(s, t).base;
                c.r as u32 + c.g as u32 + c.b as u32
            };
            let light = brightness(0);
            let medium = brightness(1);
            let charred = brightness(3);
            let bleached = brightness(4);
            let aged = brightness(5);
            assert!(
                bleached > light,
                "species {s}: Bleached ({bleached}) must be paler than Light ({light})",
            );
            assert!(
                aged < medium && aged > charred,
                "species {s}: Aged ({aged}) must sit between Medium ({medium}) and Charred ({charred})",
            );
        }
    }

    #[test]
    fn out_of_range_indices_resolve_to_sentinel() {
        let entry = palette(99, 99);
        assert_eq!(entry, SENTINEL);
    }

    /// Forward-compat sub-patterns (≥ 4) fall back to the Phase 2.3
    /// baseline behaviour — flat (species, tone) base fill.
    #[test]
    fn out_of_range_sub_pattern_falls_back_to_flat_fill() {
        let path = one_tile_path();
        let mut p = MockPainter::default();
        let m = Material::new(Family::Wood, 0, 99, 0, 0xCAFE);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        assert!(matches!(p.calls[0], PainterCall::FillPath(_, _, _)));
    }

    fn count_pushed_clips(calls: &[PainterCall]) -> usize {
        calls.iter().filter(|c| matches!(c, PainterCall::PushClip(_, _))).count()
    }

    fn count_begin_groups(calls: &[PainterCall]) -> usize {
        calls.iter().filter(|c| matches!(c, PainterCall::BeginGroup(_))).count()
    }

    /// Every Wood sub-pattern wraps its decoration in a push_clip /
    /// pop_clip pair (region clip) and at least one begin_group /
    /// end_group envelope (seams). Plank additionally adds a
    /// second begin_group for grain noise (0.35 opacity).
    #[test]
    fn every_sub_pattern_emits_clip_and_group_envelopes() {
        let path = four_tile_path();
        for sub in 0..6u8 {
            let mut p = MockPainter::default();
            let m = Material::new(Family::Wood, 0, sub, 0, 0xCAFE);
            paint(&mut p, &path, &m);
            assert_eq!(
                count_pushed_clips(&p.calls),
                1,
                "wood sub_pattern {sub}: expected 1 push_clip",
            );
            let begins = count_begin_groups(&p.calls);
            // Plank emits 2 (seam + grain); others emit 1 (seam).
            let expected_begins = if sub == 0 { 2 } else { 1 };
            assert_eq!(
                begins, expected_begins,
                "wood sub_pattern {sub}: expected {expected_begins} begin_groups",
            );
            // Balanced envelopes — every begin_group / push_clip
            // gets its matching close.
            let pops = p.calls.iter().filter(|c| matches!(c, PainterCall::PopClip)).count();
            let ends = p.calls.iter().filter(|c| matches!(c, PainterCall::EndGroup)).count();
            assert_eq!(pops, 1, "wood sub_pattern {sub}: expected 1 pop_clip");
            assert_eq!(
                ends, expected_begins,
                "wood sub_pattern {sub}: end_group balance",
            );
        }
    }

    /// Every Wood sub-pattern emits stroke_path seam stamps over
    /// the base fill_path. RNG-driven sub-patterns (Plank) also
    /// emit grain stroke_paths; RNG-free sub-patterns emit only
    /// seams.
    #[test]
    fn every_sub_pattern_emits_stroke_path_decoration() {
        let path = four_tile_path();
        for sub in 0..6u8 {
            let mut p = MockPainter::default();
            paint(
                &mut p, &path,
                &Material::new(Family::Wood, 0, sub, 0, 0xCAFE),
            );
            let strokes = p
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::StrokePath(_, _, _)))
                .count();
            assert!(
                strokes > 4,
                "wood sub_pattern {sub}: expected many stroke_path stamps, got {strokes}",
            );
        }
    }

    /// Plank is seed-aware (random plank lengths + grain jitter);
    /// BasketWeave / Parquet / Herringbone are RNG-free.
    #[test]
    fn plank_is_seed_aware_others_are_seed_independent() {
        let path = four_tile_path();
        // Plank diverges across seeds.
        let mut a = MockPainter::default();
        let mut b = MockPainter::default();
        paint(&mut a, &path, &Material::new(Family::Wood, 0, 0, 0, 333));
        paint(&mut b, &path, &Material::new(Family::Wood, 0, 0, 0, 7));
        assert_ne!(a.calls, b.calls, "Plank must be seed-aware");

        // Other sub-patterns are RNG-free.
        for sub in [1u8, 2u8, 3u8, 4u8, 5u8] {
            let mut a = MockPainter::default();
            let mut b = MockPainter::default();
            paint(&mut a, &path, &Material::new(Family::Wood, 0, sub, 0, 333));
            paint(&mut b, &path, &Material::new(Family::Wood, 0, sub, 0, 7));
            assert_eq!(
                a.calls, b.calls,
                "sub_pattern {sub} must be RNG-free",
            );
        }
    }

    /// All four sub-patterns produce visibly distinct call shapes
    /// — pin pairwise inequality so future tweaks don't collapse
    /// two sub-patterns to identical output.
    #[test]
    fn sub_patterns_pairwise_diverge() {
        let path = four_tile_path();
        let mut shapes: Vec<Vec<PainterCall>> = Vec::new();
        for sub in 0..6u8 {
            let mut p = MockPainter::default();
            paint(
                &mut p, &path,
                &Material::new(Family::Wood, 0, sub, 0, 0xCAFE),
            );
            shapes.push(p.calls);
        }
        for a in 0..4 {
            for b in (a + 1)..4 {
                assert_ne!(
                    shapes[a], shapes[b],
                    "sub_patterns {a} and {b} produced identical output",
                );
            }
        }
    }
}
