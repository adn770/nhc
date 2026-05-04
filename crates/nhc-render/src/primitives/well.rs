//! Well surface-feature primitive — Phase 4 sub-step 13 (plan §8 Q4),
//! ported to the Painter trait in Phase 2.14a of
//! `plans/nhc_pure_ir_plan.md` (the **first of four fixture
//! ports** — well / fountain / tree / bush). Per the plan §2.14
//! table, fixtures are NO group-opacity: solid stamps that
//! composite directly without `begin_group` / `end_group`
//! envelopes.
//!
//! Reproduces ``_well_fragment_for_tile`` (circular keystone ring +
//! water disc + ripples) and ``_square_well_fragment_for_tile``
//! (square masonry rim + square pool + ripples) from
//! ``nhc/rendering/_features_svg.py``. Both painters are
//! deterministic and use ``_hash_norm`` / ``_hash_unit`` for
//! per-tile variation; no ``random.Random`` is involved.
//!
//! **Parity contract:** because the painters are RNG-free
//! (deterministic ``Knuth-style multiply-and-xor`` hash on
//! ``(tx, ty, salt)``), the Rust port can match the legacy Python
//! output byte-equal — and does. Snapshot-locked via
//! ``tests/unit/test_emit_well_invariants.py``.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_well` SVG-string emitter (used by the FFI /
//!   `nhc/rendering/ir_to_svg.py` Python path until 2.17 ships
//!   the `SvgPainter`-based PyO3 export and 2.19 retires the
//!   Python `ir_to_svg` path).
//! - The new `paint_well` Painter-based emitter (used by the
//!   Rust `transform/png` path via `SkiaPainter` and, after 2.17,
//!   by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share private helpers (`well_circle_shapes` /
//! `well_square_shapes`) that build the per-tile shape stream;
//! the legacy emitter formats each shape as an SVG fragment, the
//! Painter emitter dispatches each shape through the Painter
//! trait. Hash-based generation keeps the two outputs aligned
//! without an RNG lock-step requirement.
//!
//! ## Group-opacity contract
//!
//! NO group envelope. The legacy SVG `<g>` wrapper carries no
//! `opacity` attribute (only `id`, `class`, and
//! `stroke-linejoin`), so `paint_fragment`'s `strip_g_wrapper`
//! returns `opacity=1.0` and the children render directly to the
//! pixmap. The Painter port skips `begin_group` / `end_group`
//! entirely — fixtures composite as solid stamps per the plan
//! §2.14 contract.
//!
//! ## Arc → cubic-bezier conversion
//!
//! The legacy `<path d="M x,y A r,r 0 0 1 x,y …"/>` emit goes
//! through `transform/png/path_parser::append_arc`, which
//! approximates the SVG arc with ≤90° cubic-bezier segments. The
//! Painter port mirrors that approximation locally
//! (`append_arc_to_path_ops`) so `fill_path` / `stroke_path`
//! produce identical pixmap output. Circles use a KAPPA-cubic
//! `ellipse_path_ops` mirror for the same reason —
//! `SkiaPainter::fill_circle` calls `tiny_skia::push_circle`
//! which uses a conic approximation, whereas `paint_fragment`'s
//! `paint_circle` builds a cubic-KAPPA ellipse. Going through
//! `fill_path` keeps the two paths pixel-equivalent.
//!
//! Stroke-dasharray and stroke-opacity attributes on the legacy
//! ripple `<path>`s are NOT honoured by `transform/png` (its
//! `stroke_for` ignores them and `paint_for` uses the group
//! opacity, not `stroke-opacity`), so the Painter port also
//! ignores them — strokes render at full alpha, undashed, exactly
//! matching the legacy PNG.

use std::f64::consts::PI;

use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps,
    Stroke, Vec2,
};

const CELL: f64 = 32.0;
const INK: &str = "#000000";

const STONE_DEPTH_PX: f64 = 9.0;
pub(crate) const STONE_GAP_PX: f64 = 0.4;
pub(crate) const STONE_SIDE_PX: f64 = 11.0;

const WELL_OUTER_RADIUS: f64 = 0.85 * CELL;
const WELL_INNER_RADIUS: f64 = WELL_OUTER_RADIUS - STONE_DEPTH_PX;
const WELL_WATER_RADIUS: f64 = WELL_INNER_RADIUS - 1.5;

const WELL_STONE_FILL: &str = "#EFE4D2";
const WELL_STONE_STROKE_WIDTH: f64 = 1.4;
const WELL_OUTER_RING_STROKE_WIDTH: f64 = 1.8;

const WELL_WATER_FILL: &str = "#3F6E9A";
const WELL_WATER_STROKE: &str = "#22466B";
const WELL_WATER_STROKE_WIDTH: f64 = 1.0;
const WATER_MOVEMENT_STROKE: &str = "#FFFFFF";
const WATER_MOVEMENT_STROKE_WIDTH: f64 = 0.9;
const WATER_MOVEMENT_MARK_COUNT: i32 = 4;
const WATER_MOVEMENT_AREA_FACTOR: f64 = 0.55;
const WATER_MOVEMENT_RADIUS_MIN_FACTOR: f64 = 0.18;
const WATER_MOVEMENT_RADIUS_MAX_FACTOR: f64 = 0.34;
const WATER_MOVEMENT_SWEEP_MIN: f64 = 0.5;
const WATER_MOVEMENT_SWEEP_MAX: f64 = 1.4;
const WATER_MOVEMENT_SALT: i32 = 22013;

/// 2D hash → ``[-1, 1]``. Mirrors ``_hash_norm`` exactly: same
/// Knuth multiply-and-xor + 32-bit mask on the wrapping integer
/// product. Python's int is arbitrary-precision but the operands
/// stay well within i64 for the (tx, ty) ranges used here.
pub(crate) fn hash_norm(tx: i32, ty: i32, salt: i32) -> f64 {
    let a = (tx as i64).wrapping_mul(73856093);
    let b = (ty as i64).wrapping_mul(19349663);
    let c = (salt as i64).wrapping_mul(83492791);
    let h = (a ^ b ^ c) as u64;
    let h = (h ^ (h >> 13)) & 0xFFFF_FFFF;
    (h as f64 / 0xFFFF_FFFF_u32 as f64) * 2.0 - 1.0
}

/// 2D hash → ``[0, 1]``. Mirrors ``_hash_unit``.
pub(crate) fn hash_unit(tx: i32, ty: i32, salt: i32) -> f64 {
    let a = (tx as i64).wrapping_mul(73856093);
    let b = (ty as i64).wrapping_mul(19349663);
    let c = (salt as i64).wrapping_mul(83492791);
    let h = (a ^ b ^ c) as u64;
    let h = (h ^ (h >> 13)) & 0xFFFF_FFFF;
    let h = (h.wrapping_mul(2654435761) ^ (h >> 16)) & 0xFFFF_FFFF;
    h as f64 / 0xFFFF_FFFF_u32 as f64
}

pub(crate) fn keystone_count(outer_radius: f64) -> i32 {
    let circumference = 2.0 * PI * outer_radius;
    let n = (circumference / STONE_SIDE_PX).round() as i32;
    n.max(8)
}

pub(crate) fn square_stones_per_side(side_len: f64) -> i32 {
    let n = (side_len / STONE_SIDE_PX).round() as i32;
    n.max(2)
}
/// Scatter ``n_marks`` short irregular arcs inside a circle.
/// Mirrors ``_scatter_volume_marks``.
#[allow(clippy::too_many_arguments)]
// ── Painter-trait port (Phase 2.14a) ──────────────────────────

/// Painter-trait entry point — Phase 2.14a port (the first of
/// four fixture ports — well / fountain / tree / bush).
///
/// Walks the same per-tile geometry as `draw_well` and dispatches
/// each shape through the Painter trait directly — no
/// `begin_group` / `end_group` envelope (fixtures are NO group-
/// opacity per plan §2.14). Each tile composites as a solid
/// stamp: outer ring, keystone wedges (round) or rim stones
/// (square), water disc / pool, and ripple arcs. PNG output stays
/// pixel-equal with the pre-port `paint_fragments` path — only
/// the intermediate SVG-string round-trip disappears.
pub fn paint_well(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    shape: u8,
) {
    if tiles.is_empty() {
        return;
    }
    for &(tx, ty) in tiles {
        match shape {
            1 => paint_well_square(painter, tx, ty),
            _ => paint_well_circle(painter, tx, ty),
        }
    }
}

fn paint_well_circle(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let cx = (f64::from(tx) + 0.5) * CELL;
    let cy = (f64::from(ty) + 0.5) * CELL;

    let ink = paint_for_hex(INK);
    let stone_fill = paint_for_hex(WELL_STONE_FILL);
    let water_fill = paint_for_hex(WELL_WATER_FILL);
    let water_stroke = paint_for_hex(WELL_WATER_STROKE);
    let movement_stroke = paint_for_hex(WATER_MOVEMENT_STROKE);

    // Outer ring — `<circle fill="none" stroke="#000" .../>` at
    // `:.2` precision. `paint_circle` in fragment.rs builds a
    // KAPPA-cubic ellipse path; mirror that here.
    let outer_path = ellipse_path_ops_2(cx, cy, WELL_OUTER_RADIUS, WELL_OUTER_RADIUS);
    let outer_stroke = Stroke {
        width: round_legacy_2(WELL_OUTER_RING_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.stroke_path(&outer_path, &ink, &outer_stroke);

    // Keystone wedges — `<path d="M…A…L…A…Z" fill stroke .../>`
    // at `:.2` precision.
    let n = keystone_count(WELL_OUTER_RADIUS);
    let gap_rad: f64 = 1.5_f64.to_radians();
    let step = 2.0 * PI / f64::from(n);
    let stone_stroke = Stroke {
        width: round_legacy_2(WELL_STONE_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    for i in 0..n {
        let a0 = f64::from(i) * step + gap_rad / 2.0;
        let a1 = f64::from(i + 1) * step - gap_rad / 2.0;
        let path = keystone_path_ops(
            cx, cy, WELL_INNER_RADIUS, WELL_OUTER_RADIUS, a0, a1,
        );
        painter.fill_path(&path, &stone_fill, FillRule::Winding);
        painter.stroke_path(&path, &ink, &stone_stroke);
    }

    // Water disc — `<circle fill stroke .../>` at `:.2`.
    let water_path =
        ellipse_path_ops_2(cx, cy, WELL_WATER_RADIUS, WELL_WATER_RADIUS);
    let water_stroke_def = Stroke {
        width: round_legacy_2(WELL_WATER_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.fill_path(&water_path, &water_fill, FillRule::Winding);
    painter.stroke_path(&water_path, &water_stroke, &water_stroke_def);

    // Ripple arcs — `<path d="M…A…" fill="none" stroke ...
    // stroke-dasharray=… stroke-opacity=…/>` at `:.1`. Dasharray
    // and stroke-opacity are ignored by `transform/png` (see
    // module docs).
    paint_water_movement_arcs(
        painter,
        cx,
        cy,
        WELL_WATER_RADIUS,
        tx,
        ty,
        &movement_stroke,
    );
}

fn paint_well_square(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let cx = (f64::from(tx) + 0.5) * CELL;
    let cy = (f64::from(ty) + 0.5) * CELL;
    let outer = WELL_OUTER_RADIUS;
    let inner = WELL_INNER_RADIUS;
    let depth = outer - inner;
    let gap = STONE_GAP_PX;

    let ink = paint_for_hex(INK);
    let stone_fill = paint_for_hex(WELL_STONE_FILL);
    let water_fill = paint_for_hex(WELL_WATER_FILL);
    let water_stroke = paint_for_hex(WELL_WATER_STROKE);
    let movement_stroke = paint_for_hex(WATER_MOVEMENT_STROKE);

    // Outer rim — `<rect fill="none" stroke="#000" rx=… .../>`.
    // `paint_rect` in fragment.rs ignores `rx`, so this renders as
    // a sharp-cornered stroked rect.
    let outer_stroke = Stroke {
        width: round_legacy_2(WELL_OUTER_RING_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    paint_stroke_rect(
        painter,
        cx - outer,
        cy - outer,
        2.0 * outer,
        2.0 * outer,
        &ink,
        &outer_stroke,
    );

    // Long-side stones (top + bottom rows).
    let stone_stroke = Stroke {
        width: round_legacy_2(WELL_STONE_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    let long_n = square_stones_per_side(2.0 * outer);
    let long_span = 2.0 * outer;
    let long_stone =
        (long_span - f64::from(long_n + 1) * gap) / f64::from(long_n);
    for i in 0..long_n {
        let x0 = cx - outer + gap + f64::from(i) * (long_stone + gap);
        paint_square_stone(
            painter,
            x0,
            cy - outer + gap,
            long_stone,
            depth - 2.0 * gap,
            &stone_fill,
            &ink,
            &stone_stroke,
        );
        paint_square_stone(
            painter,
            x0,
            cy + inner + gap,
            long_stone,
            depth - 2.0 * gap,
            &stone_fill,
            &ink,
            &stone_stroke,
        );
    }

    // Short-side stones (left + right columns).
    let short_n = square_stones_per_side(2.0 * outer - 2.0 * STONE_DEPTH_PX);
    let short_span = 2.0 * inner;
    let short_stone =
        (short_span - f64::from(short_n + 1) * gap) / f64::from(short_n);
    for i in 0..short_n {
        let y0 = cy - inner + gap + f64::from(i) * (short_stone + gap);
        paint_square_stone(
            painter,
            cx - outer + gap,
            y0,
            depth - 2.0 * gap,
            short_stone,
            &stone_fill,
            &ink,
            &stone_stroke,
        );
        paint_square_stone(
            painter,
            cx + inner + gap,
            y0,
            depth - 2.0 * gap,
            short_stone,
            &stone_fill,
            &ink,
            &stone_stroke,
        );
    }

    // Square pool — `<rect fill stroke rx=… .../>` (rx ignored).
    let water = WELL_WATER_RADIUS;
    let water_stroke_def = Stroke {
        width: round_legacy_2(WELL_WATER_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    paint_fill_rect(
        painter,
        cx - water,
        cy - water,
        2.0 * water,
        2.0 * water,
        &water_fill,
    );
    paint_stroke_rect(
        painter,
        cx - water,
        cy - water,
        2.0 * water,
        2.0 * water,
        &water_stroke,
        &water_stroke_def,
    );

    // Ripple arcs.
    paint_water_movement_arcs(
        painter,
        cx,
        cy,
        water,
        tx,
        ty,
        &movement_stroke,
    );
}

fn paint_square_stone(
    painter: &mut dyn Painter,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    fill: &Paint,
    stroke_paint: &Paint,
    stroke: &Stroke,
) {
    paint_fill_rect(painter, x, y, w, h, fill);
    paint_stroke_rect(painter, x, y, w, h, stroke_paint, stroke);
}

fn paint_fill_rect(
    painter: &mut dyn Painter,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    fill: &Paint,
) {
    let rect = crate::painter::Rect::new(
        round_legacy_2(x),
        round_legacy_2(y),
        round_legacy_2(w),
        round_legacy_2(h),
    );
    painter.fill_rect(rect, fill);
}

fn paint_stroke_rect(
    painter: &mut dyn Painter,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    stroke_paint: &Paint,
    stroke: &Stroke,
) {
    let rect = crate::painter::Rect::new(
        round_legacy_2(x),
        round_legacy_2(y),
        round_legacy_2(w),
        round_legacy_2(h),
    );
    painter.stroke_rect(rect, stroke_paint, stroke);
}

/// Walk the ripple-arc shape stream and emit one `stroke_path`
/// call per arc. Mirrors `water_movement_fragments` shape
/// generation but emits Painter calls instead of SVG strings.
fn paint_water_movement_arcs(
    painter: &mut dyn Painter,
    cx: f64,
    cy: f64,
    water_radius: f64,
    tx: i32,
    ty: i32,
    stroke_paint: &Paint,
) {
    let stroke = Stroke {
        width: round_legacy_2(WATER_MOVEMENT_STROKE_WIDTH),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    let arcs = water_movement_arc_shapes(
        cx,
        cy,
        water_radius,
        tx,
        ty,
        WATER_MOVEMENT_SALT,
        WATER_MOVEMENT_MARK_COUNT,
        WATER_MOVEMENT_AREA_FACTOR,
        WATER_MOVEMENT_RADIUS_MIN_FACTOR,
        WATER_MOVEMENT_RADIUS_MAX_FACTOR,
        WATER_MOVEMENT_SWEEP_MIN,
        WATER_MOVEMENT_SWEEP_MAX,
    );
    for arc in arcs {
        let path = arc_path_ops(arc.cx, arc.cy, arc.r, arc.a0, arc.a1);
        painter.stroke_path(&path, stroke_paint, &stroke);
    }
}

/// Per-arc record consumed by both the SVG-string emitter (via
/// `arc_path` / `water_movement_fragments`) and the Painter
/// emitter (via `arc_path_ops`). Shape-stream parity is
/// guaranteed because `_hash_norm` / `_hash_unit` are
/// deterministic — no RNG state to keep aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
struct ArcShape {
    cx: f64,
    cy: f64,
    r: f64,
    a0: f64,
    a1: f64,
}

#[allow(clippy::too_many_arguments)]
fn water_movement_arc_shapes(
    cx: f64,
    cy: f64,
    area_radius_in: f64,
    tx: i32,
    ty: i32,
    salt: i32,
    n_marks: i32,
    area_factor: f64,
    radius_min_factor: f64,
    radius_max_factor: f64,
    sweep_min: f64,
    sweep_max: f64,
) -> Vec<ArcShape> {
    let area_radius = area_radius_in * area_factor;
    let mark_radius_min = area_radius_in * radius_min_factor;
    let mark_radius_max = area_radius_in * radius_max_factor;
    let mut out = Vec::with_capacity(n_marks as usize);
    for i in 0..n_marks {
        let u = hash_unit(tx, ty, salt + i * 17 + 3);
        let ang = hash_norm(tx, ty, salt + i * 19 + 5) * PI;
        let r_pos = area_radius * u.sqrt();
        let mx = cx + ang.cos() * r_pos;
        let my = cy + ang.sin() * r_pos;
        let u_r = hash_unit(tx, ty, salt + i * 23 + 7);
        let mr = mark_radius_min + (mark_radius_max - mark_radius_min) * u_r;
        let sweep_start = hash_norm(tx, ty, salt + i * 29 + 11) * PI;
        let u_sw = hash_unit(tx, ty, salt + i * 31 + 13);
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

/// Build a KAPPA-cubic ellipse path matching `fragment.rs::
/// ellipse_path` exactly. Inputs at `:.2` precision (matches the
/// `<circle cx="…" cy="…" r="…">` formatter in well.rs).
fn ellipse_path_ops_2(cx: f64, cy: f64, rx: f64, ry: f64) -> PathOps {
    let cx = round_legacy_2(cx);
    let cy = round_legacy_2(cy);
    let rx = round_legacy_2(rx);
    let ry = round_legacy_2(ry);
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

/// Build the keystone wedge path: outer-arc start → outer-arc
/// end → line to inner-arc end → inner-arc back to start → close.
/// Mirrors `keystone_path` (`:.2` precision) plus
/// `path_parser::append_arc`'s cubic-bezier approximation.
fn keystone_path_ops(
    cx: f64,
    cy: f64,
    inner_r: f64,
    outer_r: f64,
    a0: f64,
    a1: f64,
) -> PathOps {
    let ox0 = round_legacy_2(cx + a0.cos() * outer_r);
    let oy0 = round_legacy_2(cy + a0.sin() * outer_r);
    let ox1 = round_legacy_2(cx + a1.cos() * outer_r);
    let oy1 = round_legacy_2(cy + a1.sin() * outer_r);
    let ix1 = round_legacy_2(cx + a1.cos() * inner_r);
    let iy1 = round_legacy_2(cy + a1.sin() * inner_r);
    let ix0 = round_legacy_2(cx + a0.cos() * inner_r);
    let iy0 = round_legacy_2(cy + a0.sin() * inner_r);
    let outer_r_f = round_legacy_2(outer_r);
    let inner_r_f = round_legacy_2(inner_r);

    let mut p = PathOps::new();
    p.move_to(Vec2::new(ox0, oy0));
    // Outer arc, sweep_flag=1 (clockwise in SVG y-down).
    append_arc_to_path_ops(&mut p, (ox0, oy0), outer_r_f, false, true, ox1, oy1);
    p.line_to(Vec2::new(ix1, iy1));
    // Inner arc, sweep_flag=0 (counter-clockwise back to start).
    append_arc_to_path_ops(&mut p, (ix1, iy1), inner_r_f, false, false, ix0, iy0);
    p.close();
    p
}

/// Build an open arc-path: `M start_x,start_y A r,r 0 0 1
/// end_x,end_y` at `:.1` precision. Mirrors `arc_path` plus
/// `path_parser::append_arc`'s cubic approximation.
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

/// Append cubic-bezier segments approximating an SVG circular
/// arc to `path`. Mirrors `transform/png/path_parser::append_arc`
/// exactly (same sign convention for the +90° vs -90°
/// perpendicular, same chord-fits-radius scaling, same ≤90° split
/// + tan-based control magnitude). NHC only emits circular arcs
/// (rx == ry, no x-axis rotation), which is the path_parser's
/// hot path.
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
    // +90° perpendicular (matches path_parser's sign convention).
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

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse for the ripple arcs (`arc_path` uses `:.1`).
fn round_legacy_1(v: f64) -> f32 {
    let s = format!("{:.1}", v);
    s.parse::<f64>().unwrap_or(v) as f32
}

/// Mirror the legacy SVG-string path's `{:.2}` truncation +
/// reparse for the circles, rects, and keystone arcs.
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
    fn hash_norm_in_range() {
        for tx in 0..10 {
            for ty in 0..10 {
                let h = hash_norm(tx, ty, 42);
                assert!((-1.0..=1.0).contains(&h));
            }
        }
    }

    #[test]
    fn hash_unit_in_range() {
        for tx in 0..10 {
            for ty in 0..10 {
                let h = hash_unit(tx, ty, 42);
                assert!((0.0..=1.0).contains(&h));
            }
        }
    }

    // ── Painter-path tests ─────────────────────────────────────

    use crate::painter::{
        FillRule as PFillRule, Paint as PPaint, Painter as PainterTrait,
        PathOps as PPathOps, Rect as PRect, Stroke as PStroke,
        Vec2 as PVec2,
    };

    /// Records every Painter call. Modelled on the same fixture
    /// used in the decorator ports.
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
        /// (path-op count, first-move-to x*10 rounded, first-move-to y*10).
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
        fn push_transform(&mut self, _: crate::painter::Transform) {}
        fn pop_transform(&mut self) {}
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
    fn paint_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_well(&mut painter, &[], 0);
        assert!(painter.calls.is_empty());
        paint_well(&mut painter, &[], 1);
        assert!(painter.calls.is_empty());
    }

    /// Fixtures are NO group-opacity per plan §2.14 — `paint_well`
    /// must NOT open / close any group envelope.
    #[test]
    fn paint_emits_no_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_well(&mut painter, &[(2, 3)], 0);
        assert_eq!(painter.group_count(), 0, "round well must not begin_group");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 0);

        let mut painter = CaptureCalls::default();
        paint_well(&mut painter, &[(0, 0)], 1);
        assert_eq!(painter.group_count(), 0, "square well must not begin_group");
        assert_eq!(painter.group_depth, 0);
    }

    /// Round well: 1 outer-ring stroke_path + N keystone (fill +
    /// stroke) pairs + 1 water (fill + stroke) + M ripple stroke
    /// arcs. fill_rect / stroke_rect MUST be zero (round well
    /// uses only paths).
    #[test]
    fn paint_round_well_emits_only_paths() {
        let mut painter = CaptureCalls::default();
        paint_well(&mut painter, &[(2, 3)], 0);
        assert_eq!(painter.fill_rect_count(), 0, "round well: no fill_rect");
        assert_eq!(painter.stroke_rect_count(), 0, "round well: no stroke_rect");
        // Water disc + N keystones → fill_path > 0.
        assert!(painter.fill_path_count() >= 2);
        // Outer ring + N keystone strokes + water stroke + M ripples.
        assert!(painter.stroke_path_count() > 2);
    }

    /// Round well stamp counts: 1 outer ring stroke + N keystones
    /// (fill + stroke) + 1 water (fill + stroke) + M ripple
    /// strokes. Compares against `keystone_count` and the
    /// `WATER_MOVEMENT_MARK_COUNT` constant.
    #[test]
    fn paint_round_well_stamp_counts_match_geometry() {
        let mut painter = CaptureCalls::default();
        paint_well(&mut painter, &[(2, 3)], 0);
        let n = keystone_count(WELL_OUTER_RADIUS) as usize;
        let m = WATER_MOVEMENT_MARK_COUNT as usize;
        // fills: N keystones + 1 water disc.
        assert_eq!(painter.fill_path_count(), n + 1);
        // strokes: 1 outer ring + N keystones + 1 water + M ripples.
        assert_eq!(painter.stroke_path_count(), 1 + n + 1 + m);
    }

    /// Square well: outer rim stroke_rect + 2*long_n + 2*short_n
    /// stones (each fill + stroke) + water (fill + stroke) + M
    /// ripple strokes. fill_path / stroke_path on circles MUST be
    /// zero (square well uses only rects + ripple arcs).
    #[test]
    fn paint_square_well_uses_rects_for_rim_and_pool() {
        let mut painter = CaptureCalls::default();
        paint_well(&mut painter, &[(0, 0)], 1);
        let long_n = square_stones_per_side(2.0 * WELL_OUTER_RADIUS) as usize;
        let short_n = square_stones_per_side(
            2.0 * WELL_OUTER_RADIUS - 2.0 * STONE_DEPTH_PX,
        ) as usize;
        let stones = 2 * long_n + 2 * short_n;
        // fill_rects: stones + water pool.
        assert_eq!(painter.fill_rect_count(), stones + 1);
        // stroke_rects: outer rim + stones + water pool stroke.
        assert_eq!(painter.stroke_rect_count(), 1 + stones + 1);
        // Square well has no fill_path (no circles, no keystones).
        assert_eq!(painter.fill_path_count(), 0);
        // stroke_path emits only ripple arcs.
        assert_eq!(
            painter.stroke_path_count(),
            WATER_MOVEMENT_MARK_COUNT as usize,
        );
    }

    /// Painter-path determinism: same input → same call sequence.
    #[test]
    fn paint_deterministic_for_same_input() {
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_well(&mut a, &[(5, 7)], 0);
        paint_well(&mut b, &[(5, 7)], 0);
        assert_eq!(a.calls, b.calls);

        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_well(&mut a, &[(5, 7)], 1);
        paint_well(&mut b, &[(5, 7)], 1);
        assert_eq!(a.calls, b.calls);
    }

    /// Different tiles drive different hash streams — the call
    /// path-op counts on the ripple arcs differ between (5,7) and
    /// (3,4) because hash_norm/hash_unit on (tx,ty) returns
    /// different chord lengths → different arc segment counts.
    #[test]
    fn paint_position_sensitive_round() {
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_well(&mut a, &[(5, 7)], 0);
        paint_well(&mut b, &[(3, 4)], 0);
        assert_ne!(a.calls, b.calls);
    }

    /// Multi-tile input emits per-tile call sequences in order.
    #[test]
    fn paint_emits_one_well_per_tile() {
        let tiles = vec![(0, 0), (1, 1), (2, 2)];
        let mut painter = CaptureCalls::default();
        paint_well(&mut painter, &tiles, 0);
        let n = keystone_count(WELL_OUTER_RADIUS) as usize;
        let m = WATER_MOVEMENT_MARK_COUNT as usize;
        // Per-tile: (n + 1) fill_paths, (1 + n + 1 + m) stroke_paths.
        assert_eq!(painter.fill_path_count(), tiles.len() * (n + 1));
        assert_eq!(
            painter.stroke_path_count(),
            tiles.len() * (1 + n + 1 + m),
        );
    }
}
