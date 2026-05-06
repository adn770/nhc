//! `Family::Stone` painter — masonry / paving substrate.
//!
//! 9 styles (Cobblestone, Brick, Flagstone, OpusRomano, FieldStone,
//! Pinwheel, Hopscotch, CrazyPaving, Ashlar). Per-style sub-pattern
//! axes (Cobblestone × 4, Brick × 3, Ashlar × 2; the rest none).
//! Per-style optional tone axis (typically Light / Medium / Dark).
//!
//! Phase 2.4a of `plans/nhc_pure_ir_v5_migration_plan.md`. The
//! per-style palette is already locked (lifted from the v4 stone
//! primitives); this commit adds the (style, sub_pattern) dispatch
//! surface and ships all four Cobblestone sub-patterns as
//! distinct layout algorithms over a shared palette:
//!
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
//! The remaining eight Stone styles (Brick, Flagstone, OpusRomano,
//! FieldStone, Pinwheel, Hopscotch, CrazyPaving, Ashlar) keep
//! their flat-fill behaviour; per-style sub-pattern lifts ride
//! Phase 2.4b–2.4i follow-on commits.

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

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, material: &Material) {
    let pal = palette(material.style);
    // Cobblestone (style = 0) is the only style with sub-pattern
    // layouts implemented in this commit. The remaining 8 styles
    // keep the flat-fill stub from Phase 2.4 baseline; per-style
    // lifts ride Phase 2.4b–2.4i follow-ons.
    if material.style == 0 {
        match material.sub_pattern {
            0 => paint_cobblestone_herringbone(painter, region_path, pal, material.seed),
            1 => paint_cobblestone_stack(painter, region_path, pal, material.seed),
            2 => paint_cobblestone_rubble(painter, region_path, pal, material.seed),
            3 => paint_cobblestone_mosaic(painter, region_path, pal, material.seed),
            // Forward-compat sub-pattern values fall back to flat
            // fill so silent loss-of-pattern is still a visible
            // floor rather than a magenta sentinel block.
            _ => fill_region(painter, region_path, pal.base),
        }
        return;
    }
    fill_region(painter, region_path, pal.base);
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

    /// Non-Cobblestone styles still emit the flat-fill (single
    /// fill_path per call). Per-style sub-pattern lifts ride
    /// Phase 2.4b–2.4i follow-ons.
    #[test]
    fn non_cobblestone_styles_keep_flat_fill() {
        let path = one_tile_path();
        for style in 1..9u8 {
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

    /// Forward-compat sub-pattern values for Cobblestone fall back
    /// to flat fill rather than emitting a magenta sentinel.
    #[test]
    fn cobblestone_unknown_sub_pattern_falls_back_to_flat_fill() {
        let path = one_tile_path();
        let mut p = MockPainter::default();
        let m = Material::new(Family::Stone, 0, 99, 0, 0xCAFE);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        assert!(matches!(p.calls[0], PainterCall::FillPath(_, _, _)));
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
}
