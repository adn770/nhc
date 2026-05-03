//! Fountain surface-feature primitive — Phase 4 sub-step 14
//! (plan §8 Q4), ported to the Painter trait in Phase 2.14b of
//! `plans/nhc_pure_ir_plan.md` (the **second of four fixture
//! ports** — well / fountain / tree / bush). Per the plan §2.14
//! table, fixtures are NO group-opacity: solid stamps that
//! composite directly without `begin_group` / `end_group`
//! envelopes.
//!
//! Reproduces the five fountain variants from
//! ``nhc/rendering/_features_svg.py``:
//!
//! - circle (2x2 footprint, ``_circle_fountain_fragment_for_tile``)
//! - square (2x2 footprint, ``_square_fountain_fragment_for_tile``)
//! - large-circle (3x3 footprint, ``_circle_fountain_3x3_fragment_for_tile``)
//! - large-square (3x3 footprint, ``_square_fountain_3x3_fragment_for_tile``)
//! - cross (3x3 plus-shaped footprint,
//!   ``_cross_fountain_fragment_for_tile``)
//!
//! All variants are RNG-free (variation comes from the
//! ``_hash_norm`` / ``_hash_unit`` deterministic hash on
//! ``(tx, ty)``); the Rust port matches the legacy Python output
//! byte-equal.
//!
//! Shared helpers (``hash_norm``, ``hash_unit``, ``arc_path``,
//! ``keystone_path``, ``water_movement_fragments``,
//! ``square_stones_per_side``, ``keystone_count``) are imported
//! from the well primitive (sub-step 13's home), avoiding
//! duplication. A future pass can lift them into a shared
//! ``feature_helpers`` module when the bush / tree ports land.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_fountain` SVG-string emitter (used by the
//!   FFI / `nhc/rendering/ir_to_svg.py` Python path until 2.17
//!   ships the `SvgPainter`-based PyO3 export and 2.19 retires
//!   the Python `ir_to_svg` path).
//! - The new `paint_fountain` Painter-based emitter (used by the
//!   Rust `transform/png` path via `SkiaPainter` and, after 2.17,
//!   by the Rust `ir_to_svg` path via `SvgPainter`).
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
//! Mirrors the `well.rs` strategy: `<circle>` elements use a
//! KAPPA-cubic `ellipse_path_ops_2` matching `fragment.rs::
//! ellipse_path` exactly; ripple `<path d="M…A…">` arcs use a
//! local `append_arc_to_path_ops` mirroring
//! `path_parser::append_arc`. Stroke-dasharray and stroke-opacity
//! attributes on the legacy ripple `<path>`s are NOT honoured by
//! `transform/png` (its `stroke_for` ignores them; `paint_for`
//! uses the group opacity, not `stroke-opacity`), so the Painter
//! port also ignores them — strokes render at full alpha,
//! undashed, exactly matching the legacy PNG.
//!
//! ## Cross-fountain polygon paths
//!
//! Cross-shape outer/water polygons are emitted by the legacy as
//! `<path d="M…L…L…Z"/>`, which `path_parser::parse_path_d`
//! converts to an open polyline + close. The Painter port
//! mirrors that exact M/L/Z structure via `polygon_path_ops`
//! (12-point plus-shape) so stroking miters render identically.
//! Per-edge cross stones (4-pt axis-aligned quads) and the four
//! concave-corner stones (4-pt axis-aligned rects emitted as
//! `<path>`, not `<rect>`) likewise route through `fill_path` /
//! `stroke_path` — using `fill_rect` would diverge because
//! `tiny_skia::PathBuilder::push_rect` emits a different segment
//! sequence than the M/L/Z polygon path.

use std::f64::consts::PI;

use super::well;
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps,
    Stroke, Vec2,
};

const CELL: f64 = 32.0;
const INK: &str = "#000000";

const STONE_DEPTH_PX: f64 = 9.0;

const FOUNTAIN_OUTER_RADIUS: f64 = 0.92 * CELL;
const FOUNTAIN_INNER_RADIUS: f64 = FOUNTAIN_OUTER_RADIUS - STONE_DEPTH_PX;
const FOUNTAIN_WATER_RADIUS: f64 = FOUNTAIN_INNER_RADIUS - 1.5;
const FOUNTAIN_PEDESTAL_OUTER_RADIUS: f64 = 0.22 * CELL;
const FOUNTAIN_PEDESTAL_INNER_RADIUS: f64 = 0.12 * CELL;

const FOUNTAIN_OUTER_RING_STROKE_WIDTH: f64 = 1.8;
const FOUNTAIN_PEDESTAL_STROKE_WIDTH: f64 = 1.4;
const FOUNTAIN_STONE_STROKE_WIDTH: f64 = 1.4;

const FOUNTAIN_WATER_FILL: &str = "#3F6E9A";
const FOUNTAIN_WATER_STROKE: &str = "#22466B";
const FOUNTAIN_STONE_FILL: &str = "#EFE4D2";
const FOUNTAIN_PEDESTAL_FILL: &str = "#D9C9AE";
const FOUNTAIN_SPOUT_FILL: &str = "#7FB6E0";

const FOUNTAIN_SQUARE_STONE_RADIUS_PX: f64 = 1.4;
const FOUNTAIN_SQUARE_OUTER_RX_PX: f64 = 4.0;
const FOUNTAIN_SQUARE_WATER_RX_PX: f64 = 2.5;
const FOUNTAIN_SQUARE_PEDESTAL_RX_PX: f64 = 2.0;

const FOUNTAIN_3X3_OUTER_RADIUS: f64 = 1.42 * CELL;
const FOUNTAIN_3X3_INNER_RADIUS: f64 =
    FOUNTAIN_3X3_OUTER_RADIUS - STONE_DEPTH_PX;
const FOUNTAIN_3X3_WATER_RADIUS: f64 = FOUNTAIN_3X3_INNER_RADIUS - 1.5;
const FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS: f64 = 0.30 * CELL;
const FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS: f64 = 0.18 * CELL;
const FOUNTAIN_3X3_SQUARE_OUTER_RX_PX: f64 = 5.0;
const FOUNTAIN_3X3_SQUARE_WATER_RX_PX: f64 = 3.0;

const FOUNTAIN_CROSS_INNER_HALF_WIDTH: f64 = 0.5 * CELL;
const FOUNTAIN_CROSS_INNER_HALF_LENGTH: f64 = 1.5 * CELL;
const FOUNTAIN_CROSS_OUTER_HALF_WIDTH: f64 =
    FOUNTAIN_CROSS_INNER_HALF_WIDTH + STONE_DEPTH_PX;
const FOUNTAIN_CROSS_OUTER_HALF_LENGTH: f64 =
    FOUNTAIN_CROSS_INNER_HALF_LENGTH + STONE_DEPTH_PX;
const FOUNTAIN_CROSS_WATER_INSET_PX: f64 = 1.5;
const FOUNTAIN_CROSS_PEDESTAL_OUTER_RADIUS: f64 = 0.26 * CELL;
const FOUNTAIN_CROSS_PEDESTAL_INNER_RADIUS: f64 = 0.14 * CELL;

const WATER_STROKE_WIDTH: f64 = 1.0; // = WELL_WATER_STROKE_WIDTH

fn fountain_stone_rect(x: f64, y: f64, w: f64, h: f64) -> String {
    format!(
        "<rect class=\"fountain-stone\" x=\"{x:.2}\" y=\"{y:.2}\" \
         width=\"{w:.2}\" height=\"{h:.2}\" \
         rx=\"{FOUNTAIN_SQUARE_STONE_RADIUS_PX:.2}\" \
         fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
    )
}

fn fountain_g_open(tx: i32, ty: i32) -> String {
    format!(
        "<g id=\"fountain-{tx}-{ty}\" class=\"fountain-feature\" \
         stroke-linejoin=\"round\">",
    )
}

fn fountain_circle(
    tx: i32, ty: i32, cx: f64, cy: f64,
    outer_r: f64, inner_r: f64, water_r: f64,
    keystone_gap_rad_deg: f64,
    pedestal_outer: f64, pedestal_inner: f64,
) -> String {
    let mut parts = String::new();
    parts.push_str(&fountain_g_open(tx, ty));
    parts.push_str(&format!(
        "<circle cx=\"{cx:.2}\" cy=\"{cy:.2}\" r=\"{outer_r:.2}\" \
         fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2}\"/>",
    ));
    let n = well::keystone_count(outer_r);
    let gap_rad = keystone_gap_rad_deg.to_radians();
    let step = 2.0 * PI / f64::from(n);
    for i in 0..n {
        let a0 = f64::from(i) * step + gap_rad / 2.0;
        let a1 = f64::from(i + 1) * step - gap_rad / 2.0;
        let d = well::keystone_path(cx, cy, inner_r, outer_r, a0, a1);
        parts.push_str(&format!(
            "<path class=\"fountain-keystone\" d=\"{d}\" \
             fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
             stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
        ));
    }
    parts.push_str(&format!(
        "<circle class=\"fountain-water\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{water_r:.2}\" \
         fill=\"{FOUNTAIN_WATER_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
    ));
    for ripple in well::water_movement_fragments(
        cx, cy, water_r, tx, ty, "fountain-water-movement",
    ) {
        parts.push_str(&ripple);
    }
    parts.push_str(&format!(
        "<circle class=\"fountain-pedestal\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{pedestal_outer:.2}\" \
         fill=\"{FOUNTAIN_PEDESTAL_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2}\"/>",
    ));
    parts.push_str(&format!(
        "<circle class=\"fountain-spout\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{pedestal_inner:.2}\" \
         fill=\"{FOUNTAIN_SPOUT_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
    ));
    parts.push_str("</g>");
    parts
}

fn fountain_square_emit(
    tx: i32, ty: i32, cx: f64, cy: f64,
    outer: f64, inner: f64, water: f64,
    pedestal: f64, spout: f64,
    outer_rx: f64, water_rx: f64, pedestal_rx: f64,
) -> String {
    let depth = outer - inner;
    let gap = well::STONE_GAP_PX;
    let mut parts = String::new();
    parts.push_str(&fountain_g_open(tx, ty));
    parts.push_str(&format!(
        "<rect x=\"{:.2}\" y=\"{:.2}\" width=\"{:.2}\" height=\"{:.2}\" \
         rx=\"{outer_rx:.2}\" fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2}\"/>",
        cx - outer, cy - outer, 2.0 * outer, 2.0 * outer,
    ));
    let long_n = well::square_stones_per_side(2.0 * outer);
    let long_span = 2.0 * outer;
    let long_stone =
        (long_span - f64::from(long_n + 1) * gap) / f64::from(long_n);
    for i in 0..long_n {
        let x0 = cx - outer + gap + f64::from(i) * (long_stone + gap);
        parts.push_str(&fountain_stone_rect(
            x0, cy - outer + gap, long_stone, depth - 2.0 * gap,
        ));
        parts.push_str(&fountain_stone_rect(
            x0, cy + inner + gap, long_stone, depth - 2.0 * gap,
        ));
    }
    let short_n =
        well::square_stones_per_side(2.0 * outer - 2.0 * STONE_DEPTH_PX);
    let short_span = 2.0 * inner;
    let short_stone =
        (short_span - f64::from(short_n + 1) * gap) / f64::from(short_n);
    for i in 0..short_n {
        let y0 = cy - inner + gap + f64::from(i) * (short_stone + gap);
        parts.push_str(&fountain_stone_rect(
            cx - outer + gap, y0, depth - 2.0 * gap, short_stone,
        ));
        parts.push_str(&fountain_stone_rect(
            cx + inner + gap, y0, depth - 2.0 * gap, short_stone,
        ));
    }
    parts.push_str(&format!(
        "<rect class=\"fountain-water\" x=\"{:.2}\" y=\"{:.2}\" \
         width=\"{:.2}\" height=\"{:.2}\" rx=\"{water_rx:.2}\" \
         fill=\"{FOUNTAIN_WATER_FILL}\" \
         stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
        cx - water, cy - water, 2.0 * water, 2.0 * water,
    ));
    for ripple in well::water_movement_fragments(
        cx, cy, water, tx, ty, "fountain-water-movement",
    ) {
        parts.push_str(&ripple);
    }
    parts.push_str(&format!(
        "<rect class=\"fountain-pedestal\" x=\"{:.2}\" y=\"{:.2}\" \
         width=\"{:.2}\" height=\"{:.2}\" rx=\"{pedestal_rx:.2}\" \
         fill=\"{FOUNTAIN_PEDESTAL_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2}\"/>",
        cx - pedestal, cy - pedestal, 2.0 * pedestal, 2.0 * pedestal,
    ));
    parts.push_str(&format!(
        "<rect class=\"fountain-spout\" x=\"{:.2}\" y=\"{:.2}\" \
         width=\"{:.2}\" height=\"{:.2}\" rx=\"{pedestal_rx:.2}\" \
         fill=\"{FOUNTAIN_SPOUT_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
        cx - spout, cy - spout, 2.0 * spout, 2.0 * spout,
    ));
    parts.push_str("</g>");
    parts
}

fn fountain_circle_2x2(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.0) * CELL;
    let cy = (f64::from(ty) + 1.0) * CELL;
    fountain_circle(
        tx, ty, cx, cy,
        FOUNTAIN_OUTER_RADIUS, FOUNTAIN_INNER_RADIUS,
        FOUNTAIN_WATER_RADIUS, 1.5,
        FOUNTAIN_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_PEDESTAL_INNER_RADIUS,
    )
}

fn fountain_square_2x2(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.0) * CELL;
    let cy = (f64::from(ty) + 1.0) * CELL;
    fountain_square_emit(
        tx, ty, cx, cy,
        FOUNTAIN_OUTER_RADIUS, FOUNTAIN_INNER_RADIUS,
        FOUNTAIN_WATER_RADIUS,
        FOUNTAIN_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_PEDESTAL_INNER_RADIUS,
        FOUNTAIN_SQUARE_OUTER_RX_PX,
        FOUNTAIN_SQUARE_WATER_RX_PX,
        FOUNTAIN_SQUARE_PEDESTAL_RX_PX,
    )
}

fn fountain_circle_3x3(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    fountain_circle(
        tx, ty, cx, cy,
        FOUNTAIN_3X3_OUTER_RADIUS, FOUNTAIN_3X3_INNER_RADIUS,
        FOUNTAIN_3X3_WATER_RADIUS, 1.0,
        FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS,
    )
}

fn fountain_square_3x3(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    fountain_square_emit(
        tx, ty, cx, cy,
        FOUNTAIN_3X3_OUTER_RADIUS, FOUNTAIN_3X3_INNER_RADIUS,
        FOUNTAIN_3X3_WATER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS,
        FOUNTAIN_3X3_SQUARE_OUTER_RX_PX,
        FOUNTAIN_3X3_SQUARE_WATER_RX_PX,
        FOUNTAIN_SQUARE_PEDESTAL_RX_PX,
    )
}

fn cross_fountain_polygon_pts(
    cx: f64, cy: f64, half_w: f64, half_l: f64,
) -> [(f64, f64); 12] {
    [
        (cx - half_w, cy - half_l),
        (cx + half_w, cy - half_l),
        (cx + half_w, cy - half_w),
        (cx + half_l, cy - half_w),
        (cx + half_l, cy + half_w),
        (cx + half_w, cy + half_w),
        (cx + half_w, cy + half_l),
        (cx - half_w, cy + half_l),
        (cx - half_w, cy + half_w),
        (cx - half_l, cy + half_w),
        (cx - half_l, cy - half_w),
        (cx - half_w, cy - half_w),
    ]
}

fn polygon_outline_d(pts: &[(f64, f64)]) -> String {
    let mut s = format!("M{:.2},{:.2}", pts[0].0, pts[0].1);
    for &(x, y) in &pts[1..] {
        s.push_str(&format!(" L{x:.2},{y:.2}"));
    }
    s.push_str(" Z");
    s
}

#[allow(clippy::too_many_arguments)]
fn stones_along_segment(
    x0: f64, y0: f64, x1: f64, y1: f64,
    depth: f64, gap_px: f64,
    stone_class: &str,
) -> Vec<String> {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let length = (dx * dx + dy * dy).sqrt();
    if length <= 0.0 {
        return Vec::new();
    }
    let n = ((length / well::STONE_SIDE_PX).round() as i32).max(1);
    let ux = dx / length;
    let uy = dy / length;
    let nx = -uy;
    let ny = ux;
    let mut stone_len = (length - f64::from(n + 1) * gap_px) / f64::from(n);
    let mut gap = gap_px;
    if stone_len <= 0.0 {
        stone_len = length / f64::from(n);
        gap = 0.0;
    }
    let mut out: Vec<String> = Vec::with_capacity(n as usize);
    for i in 0..n {
        let s = gap + f64::from(i) * (stone_len + gap);
        let e = s + stone_len;
        let ax = x0 + s * ux;
        let ay = y0 + s * uy;
        let bx = x0 + e * ux;
        let by = y0 + e * uy;
        let inset = (depth - gap).max(0.0);
        let cxx = bx + inset * nx;
        let cyy = by + inset * ny;
        let dxx = ax + inset * nx;
        let dyy = ay + inset * ny;
        let d = format!(
            "M{ax:.2},{ay:.2} L{bx:.2},{by:.2} L{cxx:.2},{cyy:.2} \
             L{dxx:.2},{dyy:.2} Z",
        );
        out.push(format!(
            "<path class=\"{stone_class}\" d=\"{d}\" \
             fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
             stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
        ));
    }
    out
}

fn fountain_cross(tx: i32, ty: i32) -> String {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    let inner_half_w = FOUNTAIN_CROSS_INNER_HALF_WIDTH;
    let inner_half_l = FOUNTAIN_CROSS_INNER_HALF_LENGTH;
    let outer_half_w = FOUNTAIN_CROSS_OUTER_HALF_WIDTH;
    let outer_half_l = FOUNTAIN_CROSS_OUTER_HALF_LENGTH;

    let mut parts = String::new();
    parts.push_str(&fountain_g_open(tx, ty));
    let outer_pts = cross_fountain_polygon_pts(
        cx, cy, outer_half_w, outer_half_l,
    );
    parts.push_str(&format!(
        "<path d=\"{}\" fill=\"none\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_OUTER_RING_STROKE_WIDTH:.2}\"/>",
        polygon_outline_d(&outer_pts),
    ));

    let depth = STONE_DEPTH_PX;
    let n = outer_pts.len();
    for i in 0..n {
        let (x0, y0) = outer_pts[i];
        let (x1, y1) = outer_pts[(i + 1) % n];
        for stone in stones_along_segment(
            x0, y0, x1, y1,
            depth, well::STONE_GAP_PX, "fountain-keystone",
        ) {
            parts.push_str(&stone);
        }
    }

    // Concave-corner stones at vertices 2, 5, 8, 11.
    let corner_g = well::STONE_GAP_PX;
    let concave: [(usize, i8, i8); 4] = [
        (2, -1, 1),
        (5, -1, -1),
        (8, 1, -1),
        (11, 1, 1),
    ];
    for &(vidx, sx, sy) in &concave {
        let (ox, oy) = outer_pts[vidx];
        let (x_min, x_max) = if sx > 0 {
            (ox, ox + depth - corner_g)
        } else {
            (ox - depth + corner_g, ox)
        };
        let (y_min, y_max) = if sy > 0 {
            (oy, oy + depth - corner_g)
        } else {
            (oy - depth + corner_g, oy)
        };
        let d = format!(
            "M{x_min:.2},{y_min:.2} L{x_max:.2},{y_min:.2} \
             L{x_max:.2},{y_max:.2} L{x_min:.2},{y_max:.2} Z",
        );
        parts.push_str(&format!(
            "<path class=\"fountain-keystone\" d=\"{d}\" \
             fill=\"{FOUNTAIN_STONE_FILL}\" stroke=\"{INK}\" \
             stroke-width=\"{FOUNTAIN_STONE_STROKE_WIDTH:.2}\"/>",
        ));
    }

    let inset = FOUNTAIN_CROSS_WATER_INSET_PX;
    let water_half_w = inner_half_w - inset;
    let water_half_l = inner_half_l - inset;
    let water_pts = cross_fountain_polygon_pts(
        cx, cy, water_half_w, water_half_l,
    );
    parts.push_str(&format!(
        "<path class=\"fountain-water\" d=\"{}\" \
         fill=\"{FOUNTAIN_WATER_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
        polygon_outline_d(&water_pts),
    ));

    let movement_radius = water_half_w.min(water_half_l);
    for ripple in well::water_movement_fragments(
        cx, cy, movement_radius, tx, ty, "fountain-water-movement",
    ) {
        parts.push_str(&ripple);
    }

    parts.push_str(&format!(
        "<circle class=\"fountain-pedestal\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{FOUNTAIN_CROSS_PEDESTAL_OUTER_RADIUS:.2}\" \
         fill=\"{FOUNTAIN_PEDESTAL_FILL}\" stroke=\"{INK}\" \
         stroke-width=\"{FOUNTAIN_PEDESTAL_STROKE_WIDTH:.2}\"/>",
    ));
    parts.push_str(&format!(
        "<circle class=\"fountain-spout\" cx=\"{cx:.2}\" cy=\"{cy:.2}\" \
         r=\"{FOUNTAIN_CROSS_PEDESTAL_INNER_RADIUS:.2}\" \
         fill=\"{FOUNTAIN_SPOUT_FILL}\" stroke=\"{FOUNTAIN_WATER_STROKE}\" \
         stroke-width=\"{WATER_STROKE_WIDTH:.2}\"/>",
    ));

    parts.push_str("</g>");
    parts
}

/// Fountain primitive entry point. `shape` matches the FB
/// FountainShape enum: 0 Round, 1 Square, 2 LargeRound,
/// 3 LargeSquare, 4 Cross.
pub fn draw_fountain(
    tiles: &[(i32, i32)], shape: u8,
) -> Vec<String> {
    if tiles.is_empty() {
        return Vec::new();
    }
    tiles
        .iter()
        .map(|&(tx, ty)| match shape {
            0 => fountain_circle_2x2(tx, ty),
            1 => fountain_square_2x2(tx, ty),
            2 => fountain_circle_3x3(tx, ty),
            3 => fountain_square_3x3(tx, ty),
            4 => fountain_cross(tx, ty),
            _ => fountain_circle_2x2(tx, ty),
        })
        .collect()
}

// ── Painter-trait port (Phase 2.14b) ──────────────────────────

/// Painter-trait entry point — Phase 2.14b port (the second of
/// four fixture ports — well / fountain / tree / bush).
///
/// Walks the same per-tile geometry as `draw_fountain` and
/// dispatches each shape through the Painter trait directly — no
/// `begin_group` / `end_group` envelope (fixtures are NO group-
/// opacity per plan §2.14). PNG output stays pixel-equal with the
/// pre-port `paint_fragments` path; only the intermediate SVG-
/// string round-trip disappears.
pub fn paint_fountain(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    shape: u8,
) {
    if tiles.is_empty() {
        return;
    }
    for &(tx, ty) in tiles {
        match shape {
            0 => paint_fountain_circle_2x2(painter, tx, ty),
            1 => paint_fountain_square_2x2(painter, tx, ty),
            2 => paint_fountain_circle_3x3(painter, tx, ty),
            3 => paint_fountain_square_3x3(painter, tx, ty),
            4 => paint_fountain_cross(painter, tx, ty),
            _ => paint_fountain_circle_2x2(painter, tx, ty),
        }
    }
}

fn paint_fountain_circle_2x2(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let cx = (f64::from(tx) + 1.0) * CELL;
    let cy = (f64::from(ty) + 1.0) * CELL;
    paint_fountain_circle(
        painter, tx, ty, cx, cy,
        FOUNTAIN_OUTER_RADIUS, FOUNTAIN_INNER_RADIUS,
        FOUNTAIN_WATER_RADIUS, 1.5,
        FOUNTAIN_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_PEDESTAL_INNER_RADIUS,
    );
}

fn paint_fountain_circle_3x3(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    paint_fountain_circle(
        painter, tx, ty, cx, cy,
        FOUNTAIN_3X3_OUTER_RADIUS, FOUNTAIN_3X3_INNER_RADIUS,
        FOUNTAIN_3X3_WATER_RADIUS, 1.0,
        FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS,
    );
}

fn paint_fountain_square_2x2(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let cx = (f64::from(tx) + 1.0) * CELL;
    let cy = (f64::from(ty) + 1.0) * CELL;
    paint_fountain_square(
        painter, tx, ty, cx, cy,
        FOUNTAIN_OUTER_RADIUS, FOUNTAIN_INNER_RADIUS,
        FOUNTAIN_WATER_RADIUS,
        FOUNTAIN_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_PEDESTAL_INNER_RADIUS,
    );
}

fn paint_fountain_square_3x3(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    paint_fountain_square(
        painter, tx, ty, cx, cy,
        FOUNTAIN_3X3_OUTER_RADIUS, FOUNTAIN_3X3_INNER_RADIUS,
        FOUNTAIN_3X3_WATER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_3X3_PEDESTAL_INNER_RADIUS,
    );
}

#[allow(clippy::too_many_arguments)]
fn paint_fountain_circle(
    painter: &mut dyn Painter,
    tx: i32, ty: i32,
    cx: f64, cy: f64,
    outer_r: f64, inner_r: f64, water_r: f64,
    keystone_gap_rad_deg: f64,
    pedestal_outer: f64, pedestal_inner: f64,
) {
    let ink = paint_for_hex(INK);
    let stone_fill = paint_for_hex(FOUNTAIN_STONE_FILL);
    let water_fill = paint_for_hex(FOUNTAIN_WATER_FILL);
    let water_stroke = paint_for_hex(FOUNTAIN_WATER_STROKE);
    let pedestal_fill = paint_for_hex(FOUNTAIN_PEDESTAL_FILL);
    let spout_fill = paint_for_hex(FOUNTAIN_SPOUT_FILL);
    let movement_stroke = paint_for_hex(WATER_MOVEMENT_STROKE);

    // Outer ring — `<circle fill="none" stroke="#000" .../>` at
    // `:.2`. Mirrors `paint_circle` (KAPPA cubic ellipse path).
    let outer_path = ellipse_path_ops_2(cx, cy, outer_r, outer_r);
    let outer_stroke = Stroke {
        width: round_legacy_2(FOUNTAIN_OUTER_RING_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.stroke_path(&outer_path, &ink, &outer_stroke);

    // Keystone wedges — same precision (`:.2`) as well's.
    let n = well::keystone_count(outer_r);
    let gap_rad = keystone_gap_rad_deg.to_radians();
    let step = 2.0 * PI / f64::from(n);
    let stone_stroke = Stroke {
        width: round_legacy_2(FOUNTAIN_STONE_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    for i in 0..n {
        let a0 = f64::from(i) * step + gap_rad / 2.0;
        let a1 = f64::from(i + 1) * step - gap_rad / 2.0;
        let path = keystone_path_ops(cx, cy, inner_r, outer_r, a0, a1);
        painter.fill_path(&path, &stone_fill, FillRule::Winding);
        painter.stroke_path(&path, &ink, &stone_stroke);
    }

    // Water disc — `<circle fill stroke .../>` at `:.2`.
    let water_path = ellipse_path_ops_2(cx, cy, water_r, water_r);
    let water_stroke_def = Stroke {
        width: round_legacy_2(WATER_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.fill_path(&water_path, &water_fill, FillRule::Winding);
    painter.stroke_path(&water_path, &water_stroke, &water_stroke_def);

    // Ripple arcs — same hash stream as `well::
    // water_movement_fragments`, dasharray + stroke-opacity
    // ignored (see module docs).
    paint_water_movement_arcs(
        painter, cx, cy, water_r, tx, ty, &movement_stroke,
    );

    // Pedestal disc — `<circle fill stroke .../>` at `:.2`.
    let pedestal_path =
        ellipse_path_ops_2(cx, cy, pedestal_outer, pedestal_outer);
    let pedestal_stroke_def = Stroke {
        width: round_legacy_2(FOUNTAIN_PEDESTAL_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.fill_path(&pedestal_path, &pedestal_fill, FillRule::Winding);
    painter.stroke_path(&pedestal_path, &ink, &pedestal_stroke_def);

    // Spout disc.
    let spout_path =
        ellipse_path_ops_2(cx, cy, pedestal_inner, pedestal_inner);
    painter.fill_path(&spout_path, &spout_fill, FillRule::Winding);
    painter.stroke_path(&spout_path, &water_stroke, &water_stroke_def);
}

#[allow(clippy::too_many_arguments)]
fn paint_fountain_square(
    painter: &mut dyn Painter,
    tx: i32, ty: i32,
    cx: f64, cy: f64,
    outer: f64, inner: f64, water: f64,
    pedestal: f64, spout: f64,
) {
    let depth = outer - inner;
    let gap = well::STONE_GAP_PX;

    let ink = paint_for_hex(INK);
    let stone_fill = paint_for_hex(FOUNTAIN_STONE_FILL);
    let water_fill = paint_for_hex(FOUNTAIN_WATER_FILL);
    let water_stroke = paint_for_hex(FOUNTAIN_WATER_STROKE);
    let pedestal_fill = paint_for_hex(FOUNTAIN_PEDESTAL_FILL);
    let spout_fill = paint_for_hex(FOUNTAIN_SPOUT_FILL);
    let movement_stroke = paint_for_hex(WATER_MOVEMENT_STROKE);

    // Outer rim — `<rect fill="none" stroke="#000" rx=… .../>`.
    // `paint_rect` ignores `rx`, so this is a sharp-cornered
    // stroked rect.
    let outer_stroke = Stroke {
        width: round_legacy_2(FOUNTAIN_OUTER_RING_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    paint_stroke_rect(
        painter,
        cx - outer, cy - outer,
        2.0 * outer, 2.0 * outer,
        &ink, &outer_stroke,
    );

    // Long-side stones (top + bottom rows).
    let stone_stroke = Stroke {
        width: round_legacy_2(FOUNTAIN_STONE_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    let long_n = well::square_stones_per_side(2.0 * outer);
    let long_span = 2.0 * outer;
    let long_stone =
        (long_span - f64::from(long_n + 1) * gap) / f64::from(long_n);
    for i in 0..long_n {
        let x0 = cx - outer + gap + f64::from(i) * (long_stone + gap);
        paint_square_stone(
            painter, x0, cy - outer + gap,
            long_stone, depth - 2.0 * gap,
            &stone_fill, &ink, &stone_stroke,
        );
        paint_square_stone(
            painter, x0, cy + inner + gap,
            long_stone, depth - 2.0 * gap,
            &stone_fill, &ink, &stone_stroke,
        );
    }

    // Short-side stones (left + right columns).
    let short_n =
        well::square_stones_per_side(2.0 * outer - 2.0 * STONE_DEPTH_PX);
    let short_span = 2.0 * inner;
    let short_stone =
        (short_span - f64::from(short_n + 1) * gap) / f64::from(short_n);
    for i in 0..short_n {
        let y0 = cy - inner + gap + f64::from(i) * (short_stone + gap);
        paint_square_stone(
            painter, cx - outer + gap, y0,
            depth - 2.0 * gap, short_stone,
            &stone_fill, &ink, &stone_stroke,
        );
        paint_square_stone(
            painter, cx + inner + gap, y0,
            depth - 2.0 * gap, short_stone,
            &stone_fill, &ink, &stone_stroke,
        );
    }

    // Square pool — `<rect fill stroke rx=… .../>` (rx ignored).
    let water_stroke_def = Stroke {
        width: round_legacy_2(WATER_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    paint_fill_rect(
        painter,
        cx - water, cy - water, 2.0 * water, 2.0 * water,
        &water_fill,
    );
    paint_stroke_rect(
        painter,
        cx - water, cy - water, 2.0 * water, 2.0 * water,
        &water_stroke, &water_stroke_def,
    );

    // Ripple arcs.
    paint_water_movement_arcs(
        painter, cx, cy, water, tx, ty, &movement_stroke,
    );

    // Pedestal rect.
    let pedestal_stroke_def = Stroke {
        width: round_legacy_2(FOUNTAIN_PEDESTAL_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    paint_fill_rect(
        painter,
        cx - pedestal, cy - pedestal,
        2.0 * pedestal, 2.0 * pedestal,
        &pedestal_fill,
    );
    paint_stroke_rect(
        painter,
        cx - pedestal, cy - pedestal,
        2.0 * pedestal, 2.0 * pedestal,
        &ink, &pedestal_stroke_def,
    );

    // Spout rect.
    paint_fill_rect(
        painter,
        cx - spout, cy - spout, 2.0 * spout, 2.0 * spout,
        &spout_fill,
    );
    paint_stroke_rect(
        painter,
        cx - spout, cy - spout, 2.0 * spout, 2.0 * spout,
        &water_stroke, &water_stroke_def,
    );
}

fn paint_fountain_cross(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let cx = (f64::from(tx) + 1.5) * CELL;
    let cy = (f64::from(ty) + 1.5) * CELL;
    let inner_half_w = FOUNTAIN_CROSS_INNER_HALF_WIDTH;
    let inner_half_l = FOUNTAIN_CROSS_INNER_HALF_LENGTH;
    let outer_half_w = FOUNTAIN_CROSS_OUTER_HALF_WIDTH;
    let outer_half_l = FOUNTAIN_CROSS_OUTER_HALF_LENGTH;

    let ink = paint_for_hex(INK);
    let stone_fill = paint_for_hex(FOUNTAIN_STONE_FILL);
    let water_fill = paint_for_hex(FOUNTAIN_WATER_FILL);
    let water_stroke = paint_for_hex(FOUNTAIN_WATER_STROKE);
    let pedestal_fill = paint_for_hex(FOUNTAIN_PEDESTAL_FILL);
    let spout_fill = paint_for_hex(FOUNTAIN_SPOUT_FILL);
    let movement_stroke = paint_for_hex(WATER_MOVEMENT_STROKE);

    // Outer plus-shape outline as `<path d="M…L…Z" fill="none"
    // stroke .../>`. Mirrors `polygon_outline_d` (`:.2`) — the
    // 12-point M/L/Z path goes through `parse_path_d`, which
    // builds an open polyline + close. Use `polygon_path_ops` so
    // stroking miters render identically.
    let outer_pts = cross_fountain_polygon_pts(
        cx, cy, outer_half_w, outer_half_l,
    );
    let outer_path = polygon_path_ops_2(&outer_pts);
    let outer_stroke = Stroke {
        width: round_legacy_2(FOUNTAIN_OUTER_RING_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.stroke_path(&outer_path, &ink, &outer_stroke);

    // Per-edge keystone stones — 4-pt axis-aligned quads emitted
    // by the legacy as `<path d="M…L…L…L…Z"/>` (NOT `<rect>`).
    // Use `fill_path` / `stroke_path` to keep the same segment
    // sequence.
    let depth = STONE_DEPTH_PX;
    let stone_stroke = Stroke {
        width: round_legacy_2(FOUNTAIN_STONE_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    let n = outer_pts.len();
    for i in 0..n {
        let (x0, y0) = outer_pts[i];
        let (x1, y1) = outer_pts[(i + 1) % n];
        for stone in stones_along_segment_pts(
            x0, y0, x1, y1, depth, well::STONE_GAP_PX,
        ) {
            let path = quad_path_ops_2(&stone);
            painter.fill_path(&path, &stone_fill, FillRule::Winding);
            painter.stroke_path(&path, &ink, &stone_stroke);
        }
    }

    // Concave-corner stones at vertices 2, 5, 8, 11 — also
    // axis-aligned, also emitted as `<path d="M…L…L…L…Z"/>`.
    let corner_g = well::STONE_GAP_PX;
    let concave: [(usize, i8, i8); 4] = [
        (2, -1, 1),
        (5, -1, -1),
        (8, 1, -1),
        (11, 1, 1),
    ];
    for &(vidx, sx, sy) in &concave {
        let (ox, oy) = outer_pts[vidx];
        let (x_min, x_max) = if sx > 0 {
            (ox, ox + depth - corner_g)
        } else {
            (ox - depth + corner_g, ox)
        };
        let (y_min, y_max) = if sy > 0 {
            (oy, oy + depth - corner_g)
        } else {
            (oy - depth + corner_g, oy)
        };
        let quad = [
            (x_min, y_min),
            (x_max, y_min),
            (x_max, y_max),
            (x_min, y_max),
        ];
        let path = quad_path_ops_2(&quad);
        painter.fill_path(&path, &stone_fill, FillRule::Winding);
        painter.stroke_path(&path, &ink, &stone_stroke);
    }

    // Water polygon (inset plus-shape).
    let inset = FOUNTAIN_CROSS_WATER_INSET_PX;
    let water_half_w = inner_half_w - inset;
    let water_half_l = inner_half_l - inset;
    let water_pts = cross_fountain_polygon_pts(
        cx, cy, water_half_w, water_half_l,
    );
    let water_path = polygon_path_ops_2(&water_pts);
    let water_stroke_def = Stroke {
        width: round_legacy_2(WATER_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.fill_path(&water_path, &water_fill, FillRule::Winding);
    painter.stroke_path(&water_path, &water_stroke, &water_stroke_def);

    // Ripple arcs (radius = min of half_w / half_l).
    let movement_radius = water_half_w.min(water_half_l);
    paint_water_movement_arcs(
        painter, cx, cy, movement_radius, tx, ty, &movement_stroke,
    );

    // Pedestal + spout circles.
    let pedestal_path = ellipse_path_ops_2(
        cx, cy,
        FOUNTAIN_CROSS_PEDESTAL_OUTER_RADIUS,
        FOUNTAIN_CROSS_PEDESTAL_OUTER_RADIUS,
    );
    let pedestal_stroke_def = Stroke {
        width: round_legacy_2(FOUNTAIN_PEDESTAL_STROKE_WIDTH),
        line_cap: LineCap::Butt,
        line_join: LineJoin::Round,
    };
    painter.fill_path(&pedestal_path, &pedestal_fill, FillRule::Winding);
    painter.stroke_path(&pedestal_path, &ink, &pedestal_stroke_def);

    let spout_path = ellipse_path_ops_2(
        cx, cy,
        FOUNTAIN_CROSS_PEDESTAL_INNER_RADIUS,
        FOUNTAIN_CROSS_PEDESTAL_INNER_RADIUS,
    );
    painter.fill_path(&spout_path, &spout_fill, FillRule::Winding);
    painter.stroke_path(&spout_path, &water_stroke, &water_stroke_def);
}

/// Geometry-only mirror of `stones_along_segment` — returns the
/// 4-point quad vertices for each stone instead of formatted SVG
/// strings. Same sequencing: stone i runs from offset `gap +
/// i*(stone_len+gap)` to `+stone_len` along the (x0,y0)→(x1,y1)
/// segment, with depth-inset perpendicular vertices.
#[allow(clippy::too_many_arguments)]
fn stones_along_segment_pts(
    x0: f64, y0: f64, x1: f64, y1: f64,
    depth: f64, gap_px: f64,
) -> Vec<[(f64, f64); 4]> {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let length = (dx * dx + dy * dy).sqrt();
    if length <= 0.0 {
        return Vec::new();
    }
    let n = ((length / well::STONE_SIDE_PX).round() as i32).max(1);
    let ux = dx / length;
    let uy = dy / length;
    let nx = -uy;
    let ny = ux;
    let mut stone_len = (length - f64::from(n + 1) * gap_px) / f64::from(n);
    let mut gap = gap_px;
    if stone_len <= 0.0 {
        stone_len = length / f64::from(n);
        gap = 0.0;
    }
    let mut out: Vec<[(f64, f64); 4]> = Vec::with_capacity(n as usize);
    for i in 0..n {
        let s = gap + f64::from(i) * (stone_len + gap);
        let e = s + stone_len;
        let ax = x0 + s * ux;
        let ay = y0 + s * uy;
        let bx = x0 + e * ux;
        let by = y0 + e * uy;
        let inset = (depth - gap).max(0.0);
        let cxx = bx + inset * nx;
        let cyy = by + inset * ny;
        let dxx = ax + inset * nx;
        let dyy = ay + inset * ny;
        out.push([(ax, ay), (bx, by), (cxx, cyy), (dxx, dyy)]);
    }
    out
}

fn paint_square_stone(
    painter: &mut dyn Painter,
    x: f64, y: f64, w: f64, h: f64,
    fill: &Paint,
    stroke_paint: &Paint,
    stroke: &Stroke,
) {
    paint_fill_rect(painter, x, y, w, h, fill);
    paint_stroke_rect(painter, x, y, w, h, stroke_paint, stroke);
}

fn paint_fill_rect(
    painter: &mut dyn Painter,
    x: f64, y: f64, w: f64, h: f64,
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
    x: f64, y: f64, w: f64, h: f64,
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
/// call per arc. Mirrors `well::water_movement_fragments` shape
/// generation.
fn paint_water_movement_arcs(
    painter: &mut dyn Painter,
    cx: f64, cy: f64, water_radius: f64,
    tx: i32, ty: i32,
    stroke_paint: &Paint,
) {
    let stroke = Stroke {
        width: round_legacy_2(WATER_MOVEMENT_STROKE_WIDTH),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    let arcs = water_movement_arc_shapes(
        cx, cy, water_radius, tx, ty, WATER_MOVEMENT_SALT,
    );
    for arc in arcs {
        let path = arc_path_ops(arc.cx, arc.cy, arc.r, arc.a0, arc.a1);
        painter.stroke_path(&path, stroke_paint, &stroke);
    }
}

/// Per-arc record. Mirrors `well::ArcShape` in shape; duplicated
/// locally because the well version is private. Fountain reuses
/// the well-side `WATER_MOVEMENT_*` constants for the hash
/// stream — listed below.
#[derive(Clone, Copy, Debug, PartialEq)]
struct ArcShape {
    cx: f64,
    cy: f64,
    r: f64,
    a0: f64,
    a1: f64,
}

/// Same constants as `well.rs` ripple generation. Duplicated
/// locally to avoid widening the well's pub(crate) surface.
const WATER_MOVEMENT_STROKE: &str = "#FFFFFF";
const WATER_MOVEMENT_STROKE_WIDTH: f64 = 0.9;
const WATER_MOVEMENT_MARK_COUNT: i32 = 4;
const WATER_MOVEMENT_AREA_FACTOR: f64 = 0.55;
const WATER_MOVEMENT_RADIUS_MIN_FACTOR: f64 = 0.18;
const WATER_MOVEMENT_RADIUS_MAX_FACTOR: f64 = 0.34;
const WATER_MOVEMENT_SWEEP_MIN: f64 = 0.5;
const WATER_MOVEMENT_SWEEP_MAX: f64 = 1.4;
const WATER_MOVEMENT_SALT: i32 = 22013;

fn water_movement_arc_shapes(
    cx: f64, cy: f64, area_radius_in: f64,
    tx: i32, ty: i32, salt: i32,
) -> Vec<ArcShape> {
    let area_radius = area_radius_in * WATER_MOVEMENT_AREA_FACTOR;
    let mark_radius_min = area_radius_in * WATER_MOVEMENT_RADIUS_MIN_FACTOR;
    let mark_radius_max = area_radius_in * WATER_MOVEMENT_RADIUS_MAX_FACTOR;
    let mut out = Vec::with_capacity(WATER_MOVEMENT_MARK_COUNT as usize);
    for i in 0..WATER_MOVEMENT_MARK_COUNT {
        let u = well::hash_unit(tx, ty, salt + i * 17 + 3);
        let ang = well::hash_norm(tx, ty, salt + i * 19 + 5) * PI;
        let r_pos = area_radius * u.sqrt();
        let mx = cx + ang.cos() * r_pos;
        let my = cy + ang.sin() * r_pos;
        let u_r = well::hash_unit(tx, ty, salt + i * 23 + 7);
        let mr = mark_radius_min
            + (mark_radius_max - mark_radius_min) * u_r;
        let sweep_start = well::hash_norm(tx, ty, salt + i * 29 + 11) * PI;
        let u_sw = well::hash_unit(tx, ty, salt + i * 31 + 13);
        let sweep_len = WATER_MOVEMENT_SWEEP_MIN
            + (WATER_MOVEMENT_SWEEP_MAX - WATER_MOVEMENT_SWEEP_MIN) * u_sw;
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
/// at `:.2` precision (matches `<circle r="…">`).
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

/// Keystone wedge — outer-arc → line-to-inner → inner-arc-back
/// → close. Mirrors `well::keystone_path` (`:.2`) plus
/// `path_parser::append_arc`'s cubic approximation.
fn keystone_path_ops(
    cx: f64, cy: f64, inner_r: f64, outer_r: f64, a0: f64, a1: f64,
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
    append_arc_to_path_ops(
        &mut p, (ox0, oy0), outer_r_f, false, true, ox1, oy1,
    );
    p.line_to(Vec2::new(ix1, iy1));
    append_arc_to_path_ops(
        &mut p, (ix1, iy1), inner_r_f, false, false, ix0, iy0,
    );
    p.close();
    p
}

/// Open ripple arc: `M sx,sy A r,r 0 large sweep ex,ey` at `:.1`
/// precision. Mirrors `well::arc_path` plus the cubic approx.
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

/// Closed M…L…L…Z polygon path at `:.2`. Mirrors
/// `polygon_outline_d` — `parse_path_d` builds the equivalent
/// `move_to + line_to* + close` sequence, so stroking miters
/// render identically to the legacy SVG path.
fn polygon_path_ops_2(pts: &[(f64, f64)]) -> PathOps {
    let mut p = PathOps::with_capacity(pts.len() + 2);
    if pts.is_empty() {
        return p;
    }
    p.move_to(Vec2::new(
        round_legacy_2(pts[0].0),
        round_legacy_2(pts[0].1),
    ));
    for &(x, y) in &pts[1..] {
        p.line_to(Vec2::new(round_legacy_2(x), round_legacy_2(y)));
    }
    p.close();
    p
}

/// Closed 4-point quad path at `:.2` — the per-edge / per-corner
/// stone shape used by the cross fountain. Same precision /
/// op-sequence as the legacy `<path d="M…L…L…L…Z"/>`.
fn quad_path_ops_2(quad: &[(f64, f64); 4]) -> PathOps {
    let mut p = PathOps::with_capacity(6);
    p.move_to(Vec2::new(
        round_legacy_2(quad[0].0),
        round_legacy_2(quad[0].1),
    ));
    p.line_to(Vec2::new(
        round_legacy_2(quad[1].0),
        round_legacy_2(quad[1].1),
    ));
    p.line_to(Vec2::new(
        round_legacy_2(quad[2].0),
        round_legacy_2(quad[2].1),
    ));
    p.line_to(Vec2::new(
        round_legacy_2(quad[3].0),
        round_legacy_2(quad[3].1),
    ));
    p.close();
    p
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

/// Mirror the legacy `{:.1}` truncation + reparse for the ripple
/// arcs (`well::arc_path` uses `:.1`).
fn round_legacy_1(v: f64) -> f32 {
    let s = format!("{:.1}", v);
    s.parse::<f64>().unwrap_or(v) as f32
}

/// Mirror the legacy `{:.2}` truncation + reparse for circles,
/// rects, keystones, polygon paths.
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
        assert!(draw_fountain(&[], 0).is_empty());
    }

    #[test]
    fn each_shape_produces_envelope() {
        for shape in 0..=4 {
            let out = draw_fountain(&[(2, 2)], shape);
            assert_eq!(out.len(), 1);
            assert!(out[0].contains("class=\"fountain-feature\""));
            assert!(out[0].ends_with("</g>"));
        }
    }

    #[test]
    fn circle_emits_keystones() {
        let out = draw_fountain(&[(0, 0)], 0);
        assert!(out[0].contains("class=\"fountain-keystone\""));
        assert!(out[0].contains("class=\"fountain-water\""));
        assert!(out[0].contains("class=\"fountain-pedestal\""));
        assert!(out[0].contains("class=\"fountain-spout\""));
    }

    #[test]
    fn square_uses_rect_rim() {
        let out = draw_fountain(&[(0, 0)], 1);
        assert!(out[0].contains("class=\"fountain-stone\""));
        // Square variant has no <circle> for rim/water.
    }

    #[test]
    fn deterministic() {
        for shape in 0..=4 {
            assert_eq!(
                draw_fountain(&[(3, 5)], shape),
                draw_fountain(&[(3, 5)], shape),
            );
        }
    }

    // ── Painter-path tests ─────────────────────────────────────

    use crate::painter::{
        FillRule as PFillRule, Paint as PPaint, Painter as PainterTrait,
        PathOps as PPathOps, Rect as PRect, Stroke as PStroke,
        Vec2 as PVec2,
    };

    /// Records every Painter call. Modelled on the well port's
    /// CaptureCalls fixture.
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
    fn paint_empty_tiles_emits_no_calls() {
        for shape in 0..=4 {
            let mut painter = CaptureCalls::default();
            paint_fountain(&mut painter, &[], shape);
            assert!(
                painter.calls.is_empty(),
                "shape {shape}: empty tiles must emit nothing",
            );
        }
    }

    /// Fixtures are NO group-opacity per plan §2.14 —
    /// `paint_fountain` MUST NOT open / close any group envelope
    /// for ANY of the 5 shapes.
    #[test]
    fn paint_emits_no_group_envelope() {
        for shape in 0..=4 {
            let mut painter = CaptureCalls::default();
            paint_fountain(&mut painter, &[(2, 3)], shape);
            assert_eq!(
                painter.group_count(), 0,
                "shape {shape}: must not begin_group",
            );
            assert_eq!(painter.group_depth, 0);
            assert_eq!(painter.max_group_depth, 0);
        }
    }

    /// Round (2x2 + 3x3) fountains use only paths — outer ring,
    /// keystones, water disc, ripple arcs, pedestal disc, spout
    /// disc. No fill_rect / stroke_rect.
    #[test]
    fn paint_round_uses_only_paths() {
        for &shape in &[0u8, 2u8] {
            let mut painter = CaptureCalls::default();
            paint_fountain(&mut painter, &[(1, 1)], shape);
            assert_eq!(
                painter.fill_rect_count(), 0,
                "shape {shape}: round must not fill_rect",
            );
            assert_eq!(
                painter.stroke_rect_count(), 0,
                "shape {shape}: round must not stroke_rect",
            );
            // fill_path: N keystones + water + pedestal + spout.
            assert!(painter.fill_path_count() >= 4);
            // stroke_path: outer + N keystones + water + M ripples
            // + pedestal + spout.
            assert!(painter.stroke_path_count() > 4);
        }
    }

    /// Round 2x2 stamp counts: 1 outer-ring stroke + N keystones
    /// (fill+stroke) + 1 water (fill+stroke) + M ripples + 1
    /// pedestal (fill+stroke) + 1 spout (fill+stroke).
    #[test]
    fn paint_round_2x2_stamp_counts_match_geometry() {
        let mut painter = CaptureCalls::default();
        paint_fountain(&mut painter, &[(2, 3)], 0);
        let n = well::keystone_count(FOUNTAIN_OUTER_RADIUS) as usize;
        let m = WATER_MOVEMENT_MARK_COUNT as usize;
        // fills: N keystones + water + pedestal + spout.
        assert_eq!(painter.fill_path_count(), n + 3);
        // strokes: outer + N keystones + water + M ripples +
        // pedestal + spout.
        assert_eq!(painter.stroke_path_count(), 1 + n + 1 + m + 2);
    }

    /// Round 3x3 stamp counts mirror 2x2 with the larger radius's
    /// keystone count.
    #[test]
    fn paint_round_3x3_stamp_counts_match_geometry() {
        let mut painter = CaptureCalls::default();
        paint_fountain(&mut painter, &[(2, 3)], 2);
        let n = well::keystone_count(FOUNTAIN_3X3_OUTER_RADIUS) as usize;
        let m = WATER_MOVEMENT_MARK_COUNT as usize;
        assert_eq!(painter.fill_path_count(), n + 3);
        assert_eq!(painter.stroke_path_count(), 1 + n + 1 + m + 2);
    }

    /// Square (2x2 + 3x3) fountains use rects for rim, stones,
    /// pool, pedestal, spout. fill_path / stroke_path appear only
    /// from the M ripple arcs.
    #[test]
    fn paint_square_uses_rects_plus_ripples() {
        for &(shape, outer) in &[
            (1u8, FOUNTAIN_OUTER_RADIUS),
            (3u8, FOUNTAIN_3X3_OUTER_RADIUS),
        ] {
            let mut painter = CaptureCalls::default();
            paint_fountain(&mut painter, &[(0, 0)], shape);
            let long_n = well::square_stones_per_side(2.0 * outer) as usize;
            let short_n = well::square_stones_per_side(
                2.0 * outer - 2.0 * STONE_DEPTH_PX,
            ) as usize;
            let stones = 2 * long_n + 2 * short_n;
            // fill_rects: stones + water pool + pedestal + spout.
            assert_eq!(
                painter.fill_rect_count(), stones + 3,
                "shape {shape}: fill_rect count",
            );
            // stroke_rects: outer rim + stones + water + pedestal
            // + spout.
            assert_eq!(
                painter.stroke_rect_count(), 1 + stones + 3,
                "shape {shape}: stroke_rect count",
            );
            // No fill_path (no circles, no keystones).
            assert_eq!(
                painter.fill_path_count(), 0,
                "shape {shape}: fill_path count",
            );
            // stroke_path: only ripple arcs.
            assert_eq!(
                painter.stroke_path_count(),
                WATER_MOVEMENT_MARK_COUNT as usize,
                "shape {shape}: stroke_path count",
            );
        }
    }

    /// Cross fountain mixes rects-NO with paths-YES: outer plus-
    /// shape outline, per-edge stones, 4 concave-corner stones,
    /// water polygon, M ripples, pedestal + spout circles. NO
    /// rects at all (pedestal + spout are circles in the cross
    /// variant).
    #[test]
    fn paint_cross_uses_paths_only() {
        let mut painter = CaptureCalls::default();
        paint_fountain(&mut painter, &[(0, 0)], 4);
        assert_eq!(
            painter.fill_rect_count(), 0,
            "cross: must not fill_rect",
        );
        assert_eq!(
            painter.stroke_rect_count(), 0,
            "cross: must not stroke_rect",
        );
        // fill_paths: per-edge stones + 4 concave + water +
        // pedestal + spout.
        assert!(painter.fill_path_count() >= 4 + 1 + 1 + 1);
        // stroke_paths: outer + same stones + 4 concave + water +
        // M ripples + pedestal + spout.
        assert!(painter.stroke_path_count() >= 1 + 4 + 1 + 1 + 1);
    }

    /// Painter-path determinism across all 5 shapes.
    #[test]
    fn paint_deterministic_for_same_input() {
        for shape in 0..=4 {
            let mut a = CaptureCalls::default();
            let mut b = CaptureCalls::default();
            paint_fountain(&mut a, &[(5, 7)], shape);
            paint_fountain(&mut b, &[(5, 7)], shape);
            assert_eq!(a.calls, b.calls, "shape {shape} deterministic");
        }
    }

    /// Different tile positions drive different ripple-hash
    /// streams, so the call sequence differs.
    #[test]
    fn paint_position_sensitive_round_2x2() {
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_fountain(&mut a, &[(5, 7)], 0);
        paint_fountain(&mut b, &[(3, 4)], 0);
        assert_ne!(a.calls, b.calls);
    }

    /// Multi-tile input emits per-tile call sequences in order.
    #[test]
    fn paint_emits_one_fountain_per_tile() {
        let tiles = vec![(0, 0), (3, 3), (6, 6)];
        let mut painter = CaptureCalls::default();
        paint_fountain(&mut painter, &tiles, 0);
        let n = well::keystone_count(FOUNTAIN_OUTER_RADIUS) as usize;
        let m = WATER_MOVEMENT_MARK_COUNT as usize;
        assert_eq!(
            painter.fill_path_count(),
            tiles.len() * (n + 3),
        );
        assert_eq!(
            painter.stroke_path_count(),
            tiles.len() * (1 + n + 1 + m + 2),
        );
    }
}
