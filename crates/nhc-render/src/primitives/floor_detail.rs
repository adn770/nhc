//! Floor-detail primitive — Phase 4, sub-step 3.d (plan §8 Q3),
//! ported to the Painter trait in Phase 2.10 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Reproduces the floor-detail-proper portion of
//! `_render_floor_detail` from `nhc/rendering/_floor_layers.py`:
//! the per-tile painters `_tile_detail` + `_floor_stone` +
//! `_y_scratch` (with its `_wobble_line` / `_edge_point` helpers)
//! produce three SVG fragment buckets (cracks / scratches /
//! stones) per side (room / corridor). The thematic painters
//! (`_tile_thematic_detail`, webs / bones / skulls) port at
//! step 4 into a separate `ThematicDetailOp`.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Output is gated by
//! structural invariants
//! (`tests/unit/test_emit_floor_detail_invariants.py`) plus a
//! snapshot lock that pins the new Rust output (lands at sub-
//! step 3.f). The RNG (`Pcg64Mcg::seed_from_u64(seed)`, where
//! `seed` already carries the legacy `+99` offset from the
//! emitter) is Rust-native; nothing here tracks the legacy
//! CPython `random.Random` MT19937 stream.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_floor_detail` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until 2.17
//!   ships the `SvgPainter`-based PyO3 export and 2.19 retires
//!   the Python `ir_to_svg` path).
//! - The new `paint_floor_detail_side` Painter-based emitter
//!   (used by the Rust `transform/png` path via `SkiaPainter`
//!   and, after 2.17, by the Rust `ir_to_svg` path via
//!   `SvgPainter`).
//!
//! Both paths share the private `tile_shapes_into_buckets` shape-
//! stream generator — the per-tile geometry is RNG- and Perlin-
//! driven and the snapshot/structural-invariants gates require a
//! single source of truth for the per-tile shape sequence.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps each non-empty bucket in
//! `<g opacity="…">` — `0.5` for `cracks`, `0.45` for
//! `scratches` (with a `class="y-scratch"` marker), `0.8` for
//! `stones`. The pre-2.10 PNG handler dispatched to
//! `paint_fragments`, which already routes each `<g opacity>`
//! envelope through `paint_offscreen_group` (Phase 5.10's
//! offscreen-buffer composite). The Painter port replaces the
//! SVG-string round-trip with native `begin_group(opacity)` /
//! `end_group()` calls so the Painter trait owns the
//! offscreen-buffer mechanism end-to-end. PNG output should be
//! pixel-equal with the pre-port PNG references — only the
//! intermediate SVG-string emission disappears.

use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};
use crate::perlin::pnoise2;

const CELL: f64 = 32.0;
const INK: &str = "#000000";
const FLOOR_STONE_FILL: &str = "#E8D5B8";
const FLOOR_STONE_STROKE: &str = "#666666";

/// Group-opacity envelope for the cracks bucket. Lifts the
/// `<g opacity="0.5">` wrapper from `nhc/rendering/_floor_layers.py`.
pub const CRACKS_OPACITY: f32 = 0.5;
/// Group-opacity envelope for the y-scratches bucket. Lifts the
/// `<g class="y-scratch" opacity="0.45">` wrapper.
pub const SCRATCHES_OPACITY: f32 = 0.45;
/// Group-opacity envelope for the floor-stones bucket. Lifts the
/// `<g opacity="0.8">` wrapper.
pub const STONES_OPACITY: f32 = 0.8;

/// Per-theme detail-density multiplier — pulled from
/// `_floor_detail._DETAIL_SCALE`. Crypts and caves get 2× more
/// detail; castles 0.8×; forests 0.6×; abyss 1.5×; everything
/// else (dungeon, sewer) 1.0×.
fn detail_scale(theme: &str) -> f64 {
    match theme {
        "crypt" | "cave" => 2.0,
        "castle" => 0.8,
        "forest" => 0.6,
        "abyss" => 1.5,
        _ => 1.0,
    }
}

/// Per-theme tile-detail probabilities. Caves take a denser
/// crack rate, fewer scratches, larger stones — same shape as
/// the legacy `_tile_detail` cave / non-cave branches.
struct TileParams {
    crack_prob: f64,
    scratch_prob: f64,
    stone_prob: f64,
    cluster_prob: f64,
    stone_scale: f64,
}

impl TileParams {
    fn for_theme(theme: &str) -> Self {
        if theme == "cave" {
            Self {
                crack_prob: 0.32,
                scratch_prob: 0.01,
                stone_prob: 0.10,
                cluster_prob: 0.06,
                stone_scale: 1.8,
            }
        } else {
            Self {
                crack_prob: 0.08,
                scratch_prob: 0.05,
                stone_prob: 0.06,
                cluster_prob: 0.03,
                stone_scale: 1.0,
            }
        }
    }
}

/// Per-tile shape — backend-agnostic record. The shape stream is
/// the single source of truth: the legacy `draw_floor_detail`
/// formats each shape as an SVG fragment string,
/// `paint_floor_detail_side` dispatches each shape through the
/// Painter trait. Both paths consume the same RNG sequence in
/// lock-step, so the Painter and SVG output stay stamp-for-stamp
/// aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum FloorDetailShape {
    /// Diagonal corner crack — straight `<line>` from
    /// `(x1, y1)` to `(x2, y2)`. Stroke width 0.5, INK colour,
    /// LineCap::Round.
    Crack { x1: f64, y1: f64, x2: f64, y2: f64 },
    /// Rotated stone ellipse. `cx`, `cy` are the centre; `rx`,
    /// `ry` the radii; `angle_deg` the rotation. Stroke width
    /// `sw` uses `FLOOR_STONE_STROKE`; fill `FLOOR_STONE_FILL`.
    Stone {
        cx: f64,
        cy: f64,
        rx: f64,
        ry: f64,
        angle_deg: f64,
        sw: f64,
    },
    /// Y-shaped scratch — three Perlin-wobbled branches meeting
    /// at a fork point. `branches[i]` holds the polyline points
    /// for branch `i` (legacy `wobble_line` output, n_seg = 4 →
    /// 5 points each). `sw` is the stroke width.
    Scratch {
        branches: [[(f64, f64); 5]; 3],
        sw: f64,
    },
}

/// Per-side shape buckets in legacy emission order:
/// `(cracks, scratches, stones)`.
type SideShapes = (
    Vec<FloorDetailShape>,
    Vec<FloorDetailShape>,
    Vec<FloorDetailShape>,
);

fn empty_side() -> SideShapes {
    (Vec::new(), Vec::new(), Vec::new())
}

fn side_is_empty(side: &SideShapes) -> bool {
    side.0.is_empty() && side.1.is_empty() && side.2.is_empty()
}

/// Walk every tile once and yield three buckets per side (room,
/// corridor) — `(cracks, scratches, stones)` per side. Mirrors
/// the legacy `_render_floor_detail` per-tile dispatch. When
/// `macabre` is `false`, every stone bucket is dropped (legacy
/// `if not macabre_detail: stones = []` post-pass).
pub fn floor_detail_shapes(
    tiles: &[(i32, i32, bool)],
    seed: u64,
    theme: &str,
    macabre: bool,
) -> (SideShapes, SideShapes) {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let params = TileParams::for_theme(theme);
    let detail_mul = detail_scale(theme);

    let mut room = empty_side();
    let mut corridor = empty_side();

    for &(x, y, is_corridor) in tiles {
        let target = if is_corridor { &mut corridor } else { &mut room };
        tile_shapes_into_buckets(
            &mut rng, x, y, seed, target, &params, detail_mul,
        );
    }

    if !macabre {
        room.2.clear();
        corridor.2.clear();
    }

    (room, corridor)
}

/// Floor-detail layer entry point — Phase 4 sub-step 3.d.
///
/// `tiles` is the IR's post-filter candidate set produced
/// emit-side at sub-step 3.b: floor tiles in y-major /
/// x-minor order with a parallel `is_corridor` flag (third
/// tuple element). `seed` already carries the `+99` legacy
/// offset (set on emit at `_floor_layers.py:_emit_floor_detail_ir`).
///
/// Returns `(room_groups, corridor_groups)`: two lists of
/// `<g>` envelope strings ready for the dispatcher to splat.
/// Each side carries up to three groups (cracks / scratches /
/// stones) in legacy emit order; empty lists when the tile set
/// produces no fragments. When `macabre` is `false`, the stone
/// buckets are dropped entirely (legacy `if not macabre_detail:
/// stones = []` post-pass).
pub fn draw_floor_detail(
    tiles: &[(i32, i32, bool)],
    seed: u64,
    theme: &str,
    macabre: bool,
) -> (Vec<String>, Vec<String>) {
    let (room, corridor) =
        floor_detail_shapes(tiles, seed, theme, macabre);
    (side_to_svg_groups(&room), side_to_svg_groups(&corridor))
}

/// Paint a single side's bucket stream onto `painter`. Each
/// non-empty bucket is wrapped in `begin_group(opacity)` /
/// `end_group()` to match the legacy SVG `<g opacity="…">`
/// envelopes. Per-tile emission order is preserved verbatim
/// within each bucket.
pub fn paint_floor_detail_side(
    painter: &mut dyn Painter,
    side: &SideShapes,
) {
    let (cracks, scratches, stones) = side;
    if !cracks.is_empty() {
        painter.begin_group(CRACKS_OPACITY);
        for shape in cracks {
            paint_shape(painter, shape);
        }
        painter.end_group();
    }
    if !scratches.is_empty() {
        painter.begin_group(SCRATCHES_OPACITY);
        for shape in scratches {
            paint_shape(painter, shape);
        }
        painter.end_group();
    }
    if !stones.is_empty() {
        painter.begin_group(STONES_OPACITY);
        for shape in stones {
            paint_shape(painter, shape);
        }
        painter.end_group();
    }
}

// ── SVG-string formatter (legacy path) ────────────────────────

fn side_to_svg_groups(side: &SideShapes) -> Vec<String> {
    if side_is_empty(side) {
        return Vec::new();
    }
    let mut out: Vec<String> = Vec::new();
    let (cracks, scratches, stones) = side;
    if !cracks.is_empty() {
        let mut s = String::from("<g opacity=\"0.5\">");
        for shape in cracks {
            s.push_str(&format_shape_svg(shape));
        }
        s.push_str("</g>");
        out.push(s);
    }
    if !scratches.is_empty() {
        let mut s = String::from("<g class=\"y-scratch\" opacity=\"0.45\">");
        for shape in scratches {
            s.push_str(&format_shape_svg(shape));
        }
        s.push_str("</g>");
        out.push(s);
    }
    if !stones.is_empty() {
        let mut s = String::from("<g opacity=\"0.8\">");
        for shape in stones {
            s.push_str(&format_shape_svg(shape));
        }
        s.push_str("</g>");
        out.push(s);
    }
    out
}

fn format_shape_svg(shape: &FloorDetailShape) -> String {
    match *shape {
        FloorDetailShape::Crack { x1, y1, x2, y2 } => format!(
            "<line x1=\"{x1}\" y1=\"{y1}\" \
             x2=\"{x2}\" y2=\"{y2}\" \
             stroke=\"{INK}\" stroke-width=\"0.5\" \
             stroke-linecap=\"round\"/>",
        ),
        FloorDetailShape::Stone {
            cx, cy, rx, ry, angle_deg, sw,
        } => format!(
            "<ellipse cx=\"{cx:.1}\" cy=\"{cy:.1}\" \
             rx=\"{rx:.1}\" ry=\"{ry:.1}\" \
             transform=\"rotate({a:.0},{cx:.1},{cy:.1})\" \
             fill=\"{FLOOR_STONE_FILL}\" stroke=\"{FLOOR_STONE_STROKE}\" \
             stroke-width=\"{sw:.1}\"/>",
            a = angle_deg,
        ),
        FloorDetailShape::Scratch { branches, sw } => {
            let mut d = String::new();
            for (i, branch) in branches.iter().enumerate() {
                if i > 0 {
                    d.push(' ');
                }
                let (x0, y0) = branch[0];
                d.push_str(&format!("M{x0:.1},{y0:.1}"));
                for &(x, y) in &branch[1..] {
                    d.push_str(&format!(" L{x:.1},{y:.1}"));
                }
            }
            format!(
                "<path d=\"{d}\" fill=\"none\" stroke=\"{INK}\" \
                 stroke-width=\"{sw:.1}\" stroke-linecap=\"round\"/>",
            )
        }
    }
}

// ── Painter dispatcher ────────────────────────────────────────

fn paint_shape(painter: &mut dyn Painter, shape: &FloorDetailShape) {
    match *shape {
        FloorDetailShape::Crack { x1, y1, x2, y2 } => {
            // Cracks emit raw `{x1}` (no `{:.1}`) in the SVG path
            // — the legacy round-trip parses the printed f64 as
            // f32, which is identical to `as f32`. No rounding
            // helper needed.
            let mut path = PathOps::new();
            path.move_to(Vec2::new(x1 as f32, y1 as f32));
            path.line_to(Vec2::new(x2 as f32, y2 as f32));
            painter.stroke_path(
                &path,
                &paint_for_hex(INK),
                &Stroke {
                    width: 0.5,
                    line_cap: LineCap::Round,
                    line_join: LineJoin::Miter,
                },
            );
        }
        FloorDetailShape::Stone {
            cx, cy, rx, ry, angle_deg, sw,
        } => {
            // Stone ellipses emit cx/cy/rx/ry through `{:.1}` in
            // the SVG path; route through `round_legacy` so the
            // PathOps land at the same f32 the legacy SVG parse
            // would have arrived at. `sw` similarly truncates
            // through `{:.1}` before tiny-skia stroke width is
            // set.
            let path = rotated_ellipse_path(
                round_legacy(cx),
                round_legacy(cy),
                round_legacy(rx),
                round_legacy(ry),
                angle_deg,
            );
            painter.fill_path(
                &path,
                &paint_for_hex(FLOOR_STONE_FILL),
                FillRule::Winding,
            );
            painter.stroke_path(
                &path,
                &paint_for_hex(FLOOR_STONE_STROKE),
                &Stroke {
                    width: round_legacy(sw),
                    line_cap: LineCap::Butt,
                    line_join: LineJoin::Miter,
                },
            );
        }
        FloorDetailShape::Scratch { branches, sw } => {
            // Y-scratches emit branch points through `{:.1}`. The
            // legacy SVG path concatenates all 3 branches into a
            // single `<path d="…">` element; replicate that in
            // PathOps so a single stroke_path call produces one
            // logical path with 3 subpaths (matches the legacy
            // single `<path>` element exactly).
            let mut path = PathOps::new();
            for branch in &branches {
                let (x0, y0) = branch[0];
                path.move_to(Vec2::new(round_legacy(x0), round_legacy(y0)));
                for &(x, y) in &branch[1..] {
                    path.line_to(Vec2::new(round_legacy(x), round_legacy(y)));
                }
            }
            painter.stroke_path(
                &path,
                &paint_for_hex(INK),
                &Stroke {
                    width: round_legacy(sw),
                    line_cap: LineCap::Round,
                    line_join: LineJoin::Round,
                },
            );
        }
    }
}

/// Build a closed cubic-Bezier ellipse path centred at `(cx, cy)`
/// with radii `(rx, ry)`, rotated by `angle_deg` around `(cx, cy)`.
/// Mirrors the rotated-ellipse helper in `primitives::hatch` (same
/// KAPPA approximation) — the rotation bakes into the control-
/// point coords so the path is backend-agnostic. The Painter
/// trait's `fill_ellipse` is axis-aligned, so the rotated stones
/// go through `fill_path` / `stroke_path` instead.
fn rotated_ellipse_path(
    cx: f32,
    cy: f32,
    rx: f32,
    ry: f32,
    angle_deg: f64,
) -> PathOps {
    const KAPPA: f64 = 0.552_284_8;
    let cx = cx as f64;
    let cy = cy as f64;
    let rx = rx as f64;
    let ry = ry as f64;
    let ox = rx * KAPPA;
    let oy = ry * KAPPA;
    let theta = angle_deg.to_radians();
    let cos_t = theta.cos();
    let sin_t = theta.sin();
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

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d` / `extract_f32`.
fn round_legacy(v: f64) -> f32 {
    let s = format!("{:.1}", v);
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

// ── Per-tile shape generation ─────────────────────────────────

/// Single floor stone — emit a `Stone` shape into the side's
/// stone bucket. Mirrors `_floor_detail._floor_stone` (RNG
/// consumption order verbatim).
fn floor_stone_shape(
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
    scale: f64,
) -> FloorDetailShape {
    let sx = px + rng.gen_range((CELL * 0.25)..(CELL * 0.75));
    let sy = py + rng.gen_range((CELL * 0.25)..(CELL * 0.75));
    let rx = rng.gen_range(2.0..(CELL * 0.15)) * scale;
    let ry = rng.gen_range(2.0..(CELL * 0.12)) * scale;
    let angle: f64 = rng.gen_range(0.0..180.0);
    let sw: f64 = rng.gen_range(1.2..2.0);
    FloorDetailShape::Stone {
        cx: sx,
        cy: sy,
        rx,
        ry,
        angle_deg: angle,
        sw,
    }
}

/// Random point on a tile edge. `edge`: 0=top, 1=right,
/// 2=bottom, 3=left. Mirrors `_svg_helpers._edge_point`.
fn edge_point(rng: &mut Pcg64Mcg, edge: i32, px: f64, py: f64) -> (f64, f64) {
    let t: f64 = rng.gen_range(0.2..0.8);
    match edge {
        0 => (px + t * CELL, py),
        1 => (px + CELL, py + t * CELL),
        2 => (px + t * CELL, py + CELL),
        _ => (px, py + t * CELL),
    }
}

/// Perlin-displaced wobbly polyline — 5 points (move + 4 line
/// segments at n_seg = 4). Mirrors `_svg_helpers._wobble_line`.
/// `seed` keys the Perlin offset per-segment so adjacent calls
/// don't accidentally rhyme.
fn wobble_polyline(
    rng: &mut Pcg64Mcg,
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    seed: i32,
) -> [(f64, f64); 5] {
    let n_seg: i32 = 4;
    let dx = x1 - x0;
    let dy = y1 - y0;
    let length = (dx * dx + dy * dy).sqrt();
    let mut pts = [(0.0, 0.0); 5];
    pts[0] = (x0, y0);
    if length < 0.1 {
        // Degenerate fallback — straight line, n_seg + 1 == 5
        // copies of the endpoints (the SVG-string path emits
        // `M{x0} L{x1}`; we expand that into 5 collinear
        // points so the polyline path emits the same logical
        // segment).
        pts[1] = (x0, y0);
        pts[2] = (x0, y0);
        pts[3] = (x0, y0);
        pts[4] = (x1, y1);
        return pts;
    }
    let nx = -dy / length;
    let ny = dx / length;
    let wobble = length * 0.12;
    for i in 1..=n_seg {
        let t = f64::from(i) / f64::from(n_seg);
        let mut mx = x0 + dx * t;
        let mut my = y0 + dy * t;
        if i < n_seg {
            let mut w = pnoise2(mx * 0.15 + f64::from(seed), my * 0.15, 77)
                * wobble;
            w += rng.gen_range((-wobble * 0.3)..(wobble * 0.3));
            mx += nx * w;
            my += ny * w;
        }
        pts[i as usize] = (mx, my);
    }
    pts
}

/// Y-shaped scratch with 3 ends on tile edges. Mirrors
/// `_svg_helpers._y_scratch`.
fn y_scratch_shape(
    rng: &mut Pcg64Mcg,
    px: f64,
    py: f64,
    gx: i32,
    gy: i32,
    seed: u64,
) -> FloorDetailShape {
    // Pick 3 distinct edges out of {0, 1, 2, 3}.
    let mut edges = [0_i32, 1, 2, 3];
    edges.shuffle(rng);
    let p0 = edge_point(rng, edges[0], px, py);
    let p1 = edge_point(rng, edges[1], px, py);
    let p2 = edge_point(rng, edges[2], px, py);

    // Fork point: weighted mean biased to tile centre with jitter.
    let cx = (p0.0 + p1.0 + p2.0) / 3.0;
    let cy = (p0.1 + p1.1 + p2.1) / 3.0;
    let tc_x = px + CELL * 0.5;
    let tc_y = py + CELL * 0.5;
    let fx = cx * 0.4 + tc_x * 0.6
        + rng.gen_range((-CELL * 0.1)..(CELL * 0.1));
    let fy = cy * 0.4 + tc_y * 0.6
        + rng.gen_range((-CELL * 0.1)..(CELL * 0.1));

    // Per-scratch offset key — mirrors the legacy
    // `seed + gx * 7 + gy` synthetic offset feeding
    // `_wobble_line` for each branch, with the +13 / +29 shifts
    // so the three branches don't rhyme.
    let ns: i32 =
        ((seed as i64) + (gx as i64) * 7 + gy as i64) as i32;
    let b0 = wobble_polyline(rng, fx, fy, p0.0, p0.1, ns);
    let b1 = wobble_polyline(rng, fx, fy, p1.0, p1.1, ns + 13);
    let b2 = wobble_polyline(rng, fx, fy, p2.0, p2.1, ns + 29);

    let sw: f64 = rng.gen_range(0.3..0.7);
    FloorDetailShape::Scratch {
        branches: [b0, b1, b2],
        sw,
    }
}

/// Per-tile detail — cracks, scratches, stones, clusters.
/// Pushes shapes into the side's three buckets in legacy order.
/// Mirrors `_floor_detail._tile_detail` — RNG consumption order
/// is preserved verbatim so the two emit paths (SVG / Painter)
/// stay stamp-for-stamp aligned.
fn tile_shapes_into_buckets(
    rng: &mut Pcg64Mcg,
    x: i32,
    y: i32,
    seed: u64,
    side: &mut SideShapes,
    params: &TileParams,
    detail_mul: f64,
) {
    let (ref mut cracks, ref mut scratches, ref mut stones) = *side;

    let px = f64::from(x) * CELL;
    let py = f64::from(y) * CELL;

    let crack_p = params.crack_prob * detail_mul;
    let scratch_p = params.scratch_prob * detail_mul;

    let roll: f64 = rng.gen();
    if roll < crack_p {
        let corner: i32 = rng.gen_range(0..=3);
        let s1: f64 = rng.gen_range((CELL * 0.15)..(CELL * 0.4));
        let s2: f64 = rng.gen_range((CELL * 0.15)..(CELL * 0.4));
        let crack = match corner {
            0 => (px + s1, py, px, py + s2),
            1 => (px + CELL - s1, py, px + CELL, py + s2),
            2 => (px + s1, py + CELL, px, py + CELL - s2),
            _ => (px + CELL - s1, py + CELL, px + CELL, py + CELL - s2),
        };
        cracks.push(FloorDetailShape::Crack {
            x1: crack.0,
            y1: crack.1,
            x2: crack.2,
            y2: crack.3,
        });
    } else if roll < crack_p + scratch_p {
        scratches.push(y_scratch_shape(rng, px, py, x, y, seed));
    }

    if rng.gen::<f64>() < params.stone_prob * detail_mul {
        stones.push(floor_stone_shape(rng, px, py, params.stone_scale));
    }

    if rng.gen::<f64>() < params.cluster_prob * detail_mul {
        let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
        for _ in 0..3 {
            let sx = cx + rng.gen_range((-CELL * 0.2)..(CELL * 0.2));
            let sy = cy + rng.gen_range((-CELL * 0.2)..(CELL * 0.2));
            let scale: f64 =
                rng.gen_range(0.5..1.3) * params.stone_scale;
            let rx = rng.gen_range(2.0..(CELL * 0.15)) * scale;
            let ry = rng.gen_range(2.0..(CELL * 0.12)) * scale;
            let angle: f64 = rng.gen_range(0.0..180.0);
            let sw: f64 = rng.gen_range(1.2..2.0);
            stones.push(FloorDetailShape::Stone {
                cx: sx,
                cy: sy,
                rx,
                ry,
                angle_deg: angle,
                sw,
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::{Paint, Painter, PathOps, Rect, Stroke, Vec2};

    #[test]
    fn empty_tiles_returns_empty_groups() {
        let (r, c) = draw_floor_detail(&[], 1234, "dungeon", true);
        assert!(r.is_empty());
        assert!(c.is_empty());
    }

    #[test]
    fn deterministic_for_same_seed() {
        let tiles: Vec<(i32, i32, bool)> = (0..30)
            .flat_map(|y| (0..30).map(move |x| (x, y, x % 3 == 0)))
            .collect();
        let a = draw_floor_detail(&tiles, 99, "dungeon", true);
        let b = draw_floor_detail(&tiles, 99, "dungeon", true);
        assert_eq!(a, b);
    }

    #[test]
    fn cave_theme_emits_more_cracks() {
        let tiles: Vec<(i32, i32, bool)> = (0..40)
            .flat_map(|y| (0..40).map(move |x| (x, y, false)))
            .collect();
        let (dungeon_room, _) =
            draw_floor_detail(&tiles, 7, "dungeon", true);
        let (cave_room, _) =
            draw_floor_detail(&tiles, 7, "cave", true);
        // Caves use 0.32 crack_prob × 2.0 detail_scale = 0.64,
        // dungeons use 0.08 × 1.0 = 0.08 — caves should produce
        // a substantially larger crack envelope.
        let dungeon_chars: usize =
            dungeon_room.iter().map(|s| s.len()).sum();
        let cave_chars: usize = cave_room.iter().map(|s| s.len()).sum();
        assert!(
            cave_chars > dungeon_chars,
            "cave envelope ({cave_chars}) should exceed dungeon \
             envelope ({dungeon_chars}) for the same tile set"
        );
    }

    #[test]
    fn macabre_off_drops_stones() {
        let tiles: Vec<(i32, i32, bool)> = (0..40)
            .flat_map(|y| (0..40).map(move |x| (x, y, false)))
            .collect();
        let (with_stones, _) =
            draw_floor_detail(&tiles, 41, "crypt", true);
        let (without_stones, _) =
            draw_floor_detail(&tiles, 41, "crypt", false);
        let with_count: usize = with_stones
            .iter()
            .map(|s| s.matches("<ellipse").count())
            .sum();
        let without_count: usize = without_stones
            .iter()
            .map(|s| s.matches("<ellipse").count())
            .sum();
        assert!(with_count > 0);
        assert_eq!(
            without_count, 0,
            "macabre=false must drop stone ellipses entirely"
        );
    }

    #[test]
    fn coordinates_stay_inside_bounds() {
        let tiles: Vec<(i32, i32, bool)> = (0..20)
            .flat_map(|y| (0..20).map(move |x| (x, y, y % 2 == 0)))
            .collect();
        let (room, corridor) =
            draw_floor_detail(&tiles, 13, "crypt", true);
        // Tile span is [0, 20*CELL]; allow a 2-cell margin for
        // the wobble-displaced scratch endpoints (the legacy
        // wobble width is `length * 0.12`, well within 1 cell).
        let max_coord = 22.0 * CELL;
        let min_coord = -CELL;
        let mut probed = 0;
        for group in room.iter().chain(corridor.iter()) {
            // Probe every numeric attribute pair we emit.
            for attr in ["x1=\"", "y1=\"", "x2=\"", "y2=\"", "cx=\"", "cy=\""] {
                let mut rest = group.as_str();
                while let Some(idx) = rest.find(attr) {
                    rest = &rest[idx + attr.len()..];
                    let end = rest.find('"').unwrap();
                    let v: f64 = rest[..end].parse().unwrap();
                    assert!(
                        v >= min_coord && v <= max_coord,
                        "coord {v} outside [{min_coord}, {max_coord}]"
                    );
                    rest = &rest[end + 1..];
                    probed += 1;
                }
            }
        }
        assert!(probed > 0, "no coordinates probed");
    }

    // ── Painter-path tests ─────────────────────────────────────

    /// Records every Painter call. Mirrors the trait-level
    /// `MockPainter` in `painter::tests` but lives in this module
    /// so the assertions stay close to the primitive.
    #[derive(Debug, Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
        group_depth: i32,
        max_group_depth: i32,
    }

    #[derive(Debug, PartialEq)]
    enum Call {
        FillPath,
        StrokePath,
        BeginGroup(u32),
        EndGroup,
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {}
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {}
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_ellipse(
            &mut self, _: f32, _: f32, _: f32, _: f32, _: &Paint,
        ) {
        }
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {}
        fn stroke_polyline(
            &mut self, _: &[Vec2], _: &Paint, _: &Stroke,
        ) {
        }
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {
            self.calls.push(Call::FillPath);
        }
        fn stroke_path(&mut self, _: &PathOps, _: &Paint, _: &Stroke) {
            self.calls.push(Call::StrokePath);
        }
        fn begin_group(&mut self, opacity: f32) {
            self.group_depth += 1;
            if self.group_depth > self.max_group_depth {
                self.max_group_depth = self.group_depth;
            }
            // Quantise opacity for stable comparisons — the
            // bucket constants are 0.5 / 0.45 / 0.8 so two
            // decimal places suffices.
            self.calls.push(Call::BeginGroup(
                (opacity * 100.0).round() as u32,
            ));
        }
        fn end_group(&mut self) {
            self.group_depth -= 1;
            self.calls.push(Call::EndGroup);
        }
        fn push_clip(&mut self, _: &PathOps, _: FillRule) {}
        fn pop_clip(&mut self) {}
        fn push_transform(&mut self, _: crate::painter::Transform) {}
        fn pop_transform(&mut self) {}
    }

    impl CaptureCalls {
        fn count(&self, target: &Call) -> usize {
            self.calls.iter().filter(|c| *c == target).count()
        }
        fn begin_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::BeginGroup(_)))
                .count()
        }
        fn end_group_count(&self) -> usize {
            self.count(&Call::EndGroup)
        }
        fn opacities(&self) -> Vec<u32> {
            self.calls
                .iter()
                .filter_map(|c| match c {
                    Call::BeginGroup(op) => Some(*op),
                    _ => None,
                })
                .collect()
        }
    }

    /// Empty side → zero painter calls. Sanity check that no
    /// spurious begin_group / end_group fires on an empty bucket
    /// stream.
    #[test]
    fn paint_floor_detail_side_empty_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        let empty = empty_side();
        paint_floor_detail_side(&mut painter, &empty);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// Crypt + macabre → all three buckets fire with the
    /// documented opacities.
    #[test]
    fn paint_floor_detail_side_wraps_buckets_in_groups() {
        let tiles: Vec<(i32, i32, bool)> = (0..30)
            .flat_map(|y| (0..30).map(move |x| (x, y, false)))
            .collect();
        let (room, _) = floor_detail_shapes(&tiles, 13, "crypt", true);
        // Sanity: this seed/theme produces all three bucket types.
        assert!(!room.0.is_empty(), "expected non-empty cracks");
        assert!(!room.1.is_empty(), "expected non-empty scratches");
        assert!(!room.2.is_empty(), "expected non-empty stones");

        let mut painter = CaptureCalls::default();
        paint_floor_detail_side(&mut painter, &room);

        assert_eq!(painter.group_depth, 0);
        assert_eq!(
            painter.begin_group_count(),
            painter.end_group_count(),
        );
        assert!(
            painter.max_group_depth <= 1,
            "buckets must not nest — max depth {}",
            painter.max_group_depth,
        );
    }

    /// Group wrapper opacities match the documented bucket
    /// constants (0.5 cracks, 0.45 scratches, 0.8 stones), in
    /// legacy emission order.
    #[test]
    fn paint_floor_detail_side_uses_documented_bucket_opacities() {
        let tiles: Vec<(i32, i32, bool)> = (0..30)
            .flat_map(|y| (0..30).map(move |x| (x, y, false)))
            .collect();
        let (room, _) = floor_detail_shapes(&tiles, 13, "crypt", true);
        assert!(!room.0.is_empty() && !room.1.is_empty() && !room.2.is_empty());

        let mut painter = CaptureCalls::default();
        paint_floor_detail_side(&mut painter, &room);

        let opacities = painter.opacities();
        assert_eq!(
            opacities,
            vec![
                (CRACKS_OPACITY * 100.0).round() as u32,
                (SCRATCHES_OPACITY * 100.0).round() as u32,
                (STONES_OPACITY * 100.0).round() as u32,
            ],
            "group opacities must be (CRACKS, SCRATCHES, STONES) in legacy order",
        );
    }

    /// macabre=false → stones bucket is empty so its group does
    /// not fire; cracks + scratches still wrap normally.
    #[test]
    fn paint_floor_detail_side_macabre_off_drops_stones_group() {
        let tiles: Vec<(i32, i32, bool)> = (0..30)
            .flat_map(|y| (0..30).map(move |x| (x, y, false)))
            .collect();
        let (room, _) = floor_detail_shapes(&tiles, 13, "crypt", false);
        assert!(room.2.is_empty(), "stones bucket must be empty");

        let mut painter = CaptureCalls::default();
        paint_floor_detail_side(&mut painter, &room);

        // The 0.8 opacity must NOT appear (no stones group).
        let opacities = painter.opacities();
        assert!(
            !opacities.contains(&((STONES_OPACITY * 100.0).round() as u32)),
            "stones group must not fire when macabre=false; got {:?}",
            opacities,
        );
        assert_eq!(painter.group_depth, 0);
    }

    /// Cross-check that the SVG-string emitter and the Painter
    /// emitter agree on bucket sizes for the same seed/tiles.
    /// Both consume the same shape stream, so the count of
    /// stroke_path calls equals (cracks + scratches + 2 * stones)
    /// — each stone produces one fill_path + one stroke_path,
    /// each crack/scratch produces one stroke_path.
    #[test]
    fn paint_and_draw_agree_on_bucket_counts() {
        let tiles: Vec<(i32, i32, bool)> = (0..20)
            .flat_map(|y| (0..20).map(move |x| (x, y, false)))
            .collect();
        let seed = 42;

        let (room, _) =
            floor_detail_shapes(&tiles, seed, "crypt", true);

        let mut painter = CaptureCalls::default();
        paint_floor_detail_side(&mut painter, &room);

        assert_eq!(
            room.2.len(),
            painter.count(&Call::FillPath),
            "stones → fill_path count mismatch",
        );
        assert_eq!(
            room.0.len() + room.1.len() + room.2.len(),
            painter.count(&Call::StrokePath),
            "stroke_path count = cracks + scratches + stones",
        );
    }
}
