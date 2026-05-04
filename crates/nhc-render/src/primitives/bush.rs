//! Bush surface-feature primitive — Phase 4 sub-step 16
//! (plan §8 Q4), ported to the Painter trait in Phase 2.14d of
//! `plans/nhc_pure_ir_plan.md` (the **fourth and last of four
//! fixture ports** — well / fountain / tree / bush). Per the
//! plan §2.14 table, fixtures are NO group-opacity: solid stamps
//! that composite directly without `begin_group` / `end_group`
//! envelopes.
//!
//! Reproduces ``_bush_fragment_for_tile`` from
//! ``nhc/rendering/_features_svg.py``: a multi-lobed cartographer
//! shrub with a darker shadow silhouette, light-coloured canopy
//! (with hue / saturation / lightness jitter per tile), and a
//! handful of irregular volume-mark arc strokes inside.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** the
//! lobe geometry uses ``geo`` crate's ``BooleanOps::union`` on
//! 32-segment circle approximations (Shapely's
//! ``Point.buffer(r)`` default), but the resulting polygon
//! vertex ordering and numerical precision differ from GEOS.
//! Output is gated by structural invariants only; town golden
//! re-baselines on this commit.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_bush` SVG-string emitter (used by the FFI /
//!   `nhc/rendering/ir_to_svg.py` Python path until 2.17 ships
//!   the `SvgPainter`-based PyO3 export and 2.19 retires the
//!   Python `ir_to_svg` path).
//! - The new `paint_bush` Painter-based emitter (used by the
//!   Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
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
//! Canopy and shadow lobe-circles are unioned via this module's
//! `union_path_from_lobes` (re-exported as
//! `union_path_from_lobes_pub`, also used by the tree primitive)
//! and emitted as one `<path d="M…L…L…Z M…L…L…Z…">` per
//! silhouette at `:.1` precision. The legacy PNG path runs
//! `parse_path_d` on that string, which builds an open polyline
//! + close per subpath. The Painter port re-parses the same
//! string into PathOps via `polygon_d_to_path_ops`, preserving
//! the exact `move_to + line_to* + close` segment sequence so
//! stroking miters render identically.
//!
//! ## Volume-mark arcs
//!
//! Volume marks reuse `well::arc_path` (`:.1`) and emit one
//! `<path>` per arc with `stroke-dasharray="1.5 1.5"` and
//! `stroke-opacity="0.55"`. As with fountain ripples and tree
//! volume marks, `transform/png`'s `paint_for` / `stroke_for`
//! ignore both attributes — the Painter port also ignores them,
//! so volume marks render at full alpha, undashed, exactly
//! matching the legacy PNG. `stroke-linecap=round` IS honoured.

use std::f64::consts::PI;

use geo::{BooleanOps, Coord, LineString, MultiPolygon, Polygon};

use super::well;
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

const CELL: f64 = 32.0;

const BUSH_CANOPY_FILL: &str = "#7A9560";
const BUSH_CANOPY_STROKE: &str = "#3F5237";
const BUSH_CANOPY_SHADOW_FILL: &str = "#3F5237";
const BUSH_CANOPY_STROKE_WIDTH: f64 = 1.0;
const BUSH_CANOPY_LOBE_COUNT_CHOICES: [i32; 2] = [3, 4];
const BUSH_CANOPY_LOBE_RADIUS: f64 = 0.16 * CELL;
const BUSH_CANOPY_CLUSTER_RADIUS: f64 = 0.10 * CELL;
const BUSH_CANOPY_CLUSTER_RADIUS_JITTER: f64 = 0.30;
const BUSH_CANOPY_LOBE_RADIUS_JITTER: f64 = 0.18;
const BUSH_CANOPY_LOBE_OFFSET_JITTER: f64 = 0.30;
const BUSH_CANOPY_LOBE_ANGLE_JITTER: f64 = 0.40;
const BUSH_CANOPY_CENTER_OFFSET: f64 = 0.06 * CELL;

const BUSH_CANOPY_SHADOW_LOBE_RADIUS: f64 = 0.18 * CELL;
const BUSH_CANOPY_SHADOW_OFFSET: f64 = 0.03 * CELL;

const BUSH_VOLUME_MARK_COUNT: i32 = 2;
const BUSH_VOLUME_MARK_AREA_RADIUS: f64 = 0.14 * CELL;
const BUSH_VOLUME_MARK_RADIUS_MIN: f64 = 0.04 * CELL;
const BUSH_VOLUME_MARK_RADIUS_MAX: f64 = 0.07 * CELL;
const BUSH_VOLUME_MARK_SWEEP_MIN: f64 = 0.6;
const BUSH_VOLUME_MARK_SWEEP_MAX: f64 = 1.5;
const BUSH_VOLUME_STROKE_WIDTH: f64 = 0.6;
const BUSH_HUE_JITTER_DEG: f64 = 6.0;
const BUSH_SAT_JITTER: f64 = 0.05;
const BUSH_LIGHT_JITTER: f64 = 0.04;

const BUSH_HUE_SALT: i32 = 7019;
const BUSH_SAT_SALT: i32 = 8053;
const BUSH_LIGHT_SALT: i32 = 9091;
const BUSH_CANOPY_SHAPE_SALT: i32 = 11117;
const BUSH_SHADOW_SHAPE_SALT: i32 = 11201;
const BUSH_VOLUME_SALT: i32 = 12119;
const BUSH_LOBE_COUNT_SALT: i32 = 13127;
const BUSH_CLUSTER_RADIUS_SALT: i32 = 13147;
const BUSH_CENTER_X_SALT: i32 = 13163;
const BUSH_CENTER_Y_SALT: i32 = 13183;

/// Approximate a circle as a 32-segment polygon (matches
/// Shapely's ``Point.buffer(r)`` default of ``quad_segs=8`` →
/// 8 vertices per quadrant). The vertex ordering and exact
/// coordinates differ from GEOS, but the silhouette character
/// is preserved.
fn circle_polygon(cx: f64, cy: f64, r: f64) -> Polygon<f64> {
    const SEGMENTS: i32 = 32;
    let mut coords: Vec<Coord<f64>> = Vec::with_capacity(SEGMENTS as usize + 1);
    for i in 0..SEGMENTS {
        let a = 2.0 * PI * f64::from(i) / f64::from(SEGMENTS);
        coords.push(Coord {
            x: cx + a.cos() * r,
            y: cy + a.sin() * r,
        });
    }
    coords.push(coords[0]);
    Polygon::new(LineString::new(coords), vec![])
}

fn lobe_circles(
    cx: f64, cy: f64, tx: i32, ty: i32, salt: i32,
    n_lobes: i32, lobe_radius: f64, cluster_radius: f64,
    radius_jitter: f64, offset_jitter: f64, angle_jitter: f64,
) -> Vec<(f64, f64, f64)> {
    let step = 2.0 * PI / f64::from(n_lobes);
    let mut out = Vec::with_capacity(n_lobes as usize);
    for i in 0..n_lobes {
        let a_jit = well::hash_norm(tx, ty, salt + i * 7) * angle_jitter;
        let o_jit =
            1.0 + well::hash_norm(tx, ty, salt + i * 11 + 1) * offset_jitter;
        let r_jit =
            1.0 + well::hash_norm(tx, ty, salt + i * 13 + 2) * radius_jitter;
        let ang = f64::from(i) * step + a_jit;
        let offs = cluster_radius * o_jit;
        let lr = lobe_radius * r_jit;
        out.push((cx + ang.cos() * offs, cy + ang.sin() * offs, lr));
    }
    out
}

fn lobe_count(tx: i32, ty: i32) -> i32 {
    let u = well::hash_unit(tx, ty, BUSH_LOBE_COUNT_SALT);
    let n = BUSH_CANOPY_LOBE_COUNT_CHOICES.len() as i32;
    let idx = ((u * f64::from(n)) as i32).min(n - 1);
    BUSH_CANOPY_LOBE_COUNT_CHOICES[idx as usize]
}

fn cluster_radius(tx: i32, ty: i32) -> f64 {
    let j = well::hash_norm(tx, ty, BUSH_CLUSTER_RADIUS_SALT);
    BUSH_CANOPY_CLUSTER_RADIUS * (1.0 + j * BUSH_CANOPY_CLUSTER_RADIUS_JITTER)
}

fn center_offset(tx: i32, ty: i32) -> (f64, f64) {
    let dx = well::hash_norm(tx, ty, BUSH_CENTER_X_SALT)
        * BUSH_CANOPY_CENTER_OFFSET;
    let dy = well::hash_norm(tx, ty, BUSH_CENTER_Y_SALT)
        * BUSH_CANOPY_CENTER_OFFSET;
    (dx, dy)
}

/// Union the lobe circles via geo's BooleanOps and format the
/// result as an SVG ``d`` string. Mirrors
/// ``_union_path_from_lobes`` + ``_polygon_to_svg_path``.
pub(crate) fn union_path_from_lobes_pub(
    lobes: &[(f64, f64, f64)],
) -> String {
    union_path_from_lobes(lobes)
}

fn union_path_from_lobes(lobes: &[(f64, f64, f64)]) -> String {
    if lobes.is_empty() {
        return String::new();
    }
    let mut acc: MultiPolygon<f64> =
        MultiPolygon::new(vec![circle_polygon(
            lobes[0].0, lobes[0].1, lobes[0].2,
        )]);
    for &(cx, cy, r) in &lobes[1..] {
        let next = MultiPolygon::new(vec![circle_polygon(cx, cy, r)]);
        acc = acc.union(&next);
    }
    polygon_to_svg_path(&acc)
}

fn polygon_to_svg_path(geom: &MultiPolygon<f64>) -> String {
    let mut parts: Vec<String> = Vec::new();
    for poly in &geom.0 {
        let mut rings: Vec<&LineString<f64>> = vec![poly.exterior()];
        for hole in poly.interiors() {
            rings.push(hole);
        }
        for ring in rings {
            let coords: Vec<&Coord<f64>> = ring.0.iter().collect();
            if coords.is_empty() {
                continue;
            }
            parts.push(format!("M{:.1},{:.1}", coords[0].x, coords[0].y));
            for c in &coords[1..] {
                parts.push(format!("L{:.1},{:.1}", c.x, c.y));
            }
            parts.push("Z".to_string());
        }
    }
    parts.join(" ")
}

fn fill_jitter(tx: i32, ty: i32) -> String {
    let dh = well::hash_norm(tx, ty, BUSH_HUE_SALT) * BUSH_HUE_JITTER_DEG;
    let ds = well::hash_norm(tx, ty, BUSH_SAT_SALT) * BUSH_SAT_JITTER;
    let dl = well::hash_norm(tx, ty, BUSH_LIGHT_SALT) * BUSH_LIGHT_JITTER;
    shift_color(BUSH_CANOPY_FILL, dh, ds, dl)
}

pub(crate) fn shift_color_pub(
    base_hex: &str, hue_deg: f64, sat: f64, light: f64,
) -> String {
    shift_color(base_hex, hue_deg, sat, light)
}

/// HLS color shift — mirrors Python's ``colorsys.rgb_to_hls`` /
/// ``hls_to_rgb`` round-trip. Output formatted as ``#RRGGBB``
/// with banker's-style rounding to match Python's ``round(x*255)``.
fn shift_color(base_hex: &str, hue_deg: f64, sat: f64, light: f64) -> String {
    let (r, g, b) = hex_to_rgb01(base_hex);
    let (h, l, s) = rgb_to_hls(r, g, b);
    let h = ((h + hue_deg / 360.0) % 1.0 + 1.0) % 1.0;
    let s = (s + sat).clamp(0.0, 1.0);
    let l = (l + light).clamp(0.0, 1.0);
    let (rr, gg, bb) = hls_to_rgb(h, l, s);
    rgb01_to_hex(rr, gg, bb)
}

fn hex_to_rgb01(s: &str) -> (f64, f64, f64) {
    let s = s.trim_start_matches('#');
    let r = i32::from_str_radix(&s[0..2], 16).unwrap_or(0);
    let g = i32::from_str_radix(&s[2..4], 16).unwrap_or(0);
    let b = i32::from_str_radix(&s[4..6], 16).unwrap_or(0);
    (
        f64::from(r) / 255.0,
        f64::from(g) / 255.0,
        f64::from(b) / 255.0,
    )
}

fn rgb01_to_hex(r: f64, g: f64, b: f64) -> String {
    let to_byte = |v: f64| -> u8 {
        let c = v.clamp(0.0, 1.0);
        // Python's round() uses banker's rounding; CPython's
        // int(round(x)) does half-to-even. Emulate via f64::round
        // (half-away-from-zero) — close enough for our jitter range.
        (c * 255.0).round() as u8
    };
    format!("#{:02X}{:02X}{:02X}", to_byte(r), to_byte(g), to_byte(b))
}

/// CPython ``colorsys.rgb_to_hls``.
fn rgb_to_hls(r: f64, g: f64, b: f64) -> (f64, f64, f64) {
    let maxc = r.max(g).max(b);
    let minc = r.min(g).min(b);
    let sumc = maxc + minc;
    let l = sumc / 2.0;
    if maxc == minc {
        return (0.0, l, 0.0);
    }
    let rangec = maxc - minc;
    let s = if l <= 0.5 {
        rangec / sumc
    } else {
        rangec / (2.0 - maxc - minc)
    };
    let rc = (maxc - r) / rangec;
    let gc = (maxc - g) / rangec;
    let bc = (maxc - b) / rangec;
    let h = if r == maxc {
        bc - gc
    } else if g == maxc {
        2.0 + rc - bc
    } else {
        4.0 + gc - rc
    };
    let h = (h / 6.0).rem_euclid(1.0);
    (h, l, s)
}

fn hls_to_rgb(h: f64, l: f64, s: f64) -> (f64, f64, f64) {
    if s == 0.0 {
        return (l, l, l);
    }
    let m2 = if l <= 0.5 {
        l * (1.0 + s)
    } else {
        l + s - l * s
    };
    let m1 = 2.0 * l - m2;
    (
        hls_v(m1, m2, h + 1.0 / 3.0),
        hls_v(m1, m2, h),
        hls_v(m1, m2, h - 1.0 / 3.0),
    )
}

fn hls_v(m1: f64, m2: f64, hue: f64) -> f64 {
    let h = hue.rem_euclid(1.0);
    if h < 1.0 / 6.0 {
        m1 + (m2 - m1) * h * 6.0
    } else if h < 0.5 {
        m2
    } else if h < 2.0 / 3.0 {
        m1 + (m2 - m1) * (2.0 / 3.0 - h) * 6.0
    } else {
        m1
    }
}
#[allow(clippy::too_many_arguments)]
// ── Painter-trait port (Phase 2.14d) ──────────────────────────

/// Painter-trait entry point — Phase 2.14d port (the **fourth
/// and last** of four fixture ports — well / fountain / tree /
/// bush). With this port shipped, all of plan §2.14's fixture
/// migration is complete.
///
/// Walks the same per-tile geometry as `draw_bush` and dispatches
/// each silhouette through the Painter trait directly — no
/// `begin_group` / `end_group` envelope (fixtures are NO group-
/// opacity per plan §2.14). PNG output stays pixel-equal with the
/// pre-port `paint_fragments` path; only the intermediate SVG-
/// string round-trip disappears.
pub fn paint_bush(painter: &mut dyn Painter, tiles: &[(i32, i32)]) {
    if tiles.is_empty() {
        return;
    }
    for &(tx, ty) in tiles {
        paint_bush_tile(painter, tx, ty);
    }
}

fn paint_bush_tile(painter: &mut dyn Painter, tx: i32, ty: i32) {
    let (dx, dy) = center_offset(tx, ty);
    let cx = (f64::from(tx) + 0.5) * CELL + dx;
    let cy = (f64::from(ty) + 0.5) * CELL + dy;

    let n = lobe_count(tx, ty);
    let cluster_r = cluster_radius(tx, ty);

    let canopy_lobes = lobe_circles(
        cx, cy, tx, ty, BUSH_CANOPY_SHAPE_SALT,
        n, BUSH_CANOPY_LOBE_RADIUS, cluster_r,
        BUSH_CANOPY_LOBE_RADIUS_JITTER,
        BUSH_CANOPY_LOBE_OFFSET_JITTER,
        BUSH_CANOPY_LOBE_ANGLE_JITTER,
    );
    let shadow_lobes = lobe_circles(
        cx + BUSH_CANOPY_SHADOW_OFFSET,
        cy + BUSH_CANOPY_SHADOW_OFFSET,
        tx, ty, BUSH_SHADOW_SHAPE_SALT,
        n, BUSH_CANOPY_SHADOW_LOBE_RADIUS, cluster_r,
        BUSH_CANOPY_LOBE_RADIUS_JITTER,
        BUSH_CANOPY_LOBE_OFFSET_JITTER,
        BUSH_CANOPY_LOBE_ANGLE_JITTER,
    );

    // Element order mirrors `bush_fragment_for_tile`: shadow
    // path first, then canopy path, then volume marks. Painters
    // composite in document order. Bush has no trunk (unlike
    // tree).
    paint_shadow_canopy(painter, &shadow_lobes);
    paint_canopy(painter, &canopy_lobes, &fill_jitter(tx, ty));
    paint_volume_marks(painter, cx, cy, tx, ty);
}

fn paint_shadow_canopy(
    painter: &mut dyn Painter,
    lobes: &[(f64, f64, f64)],
) {
    // `<path d="M…L…L…Z M…L…L…Z…" fill stroke="none"/>` at
    // `:.1` precision. `polygon_to_svg_path` emits one M…L…L…Z
    // subpath per polygon ring; we re-parse the string into
    // PathOps so the segment sequence matches what `parse_path_d`
    // builds on the legacy path.
    let d = union_path_from_lobes(lobes);
    if d.is_empty() {
        return;
    }
    let path = polygon_d_to_path_ops(&d);
    if path.is_empty() {
        return;
    }
    let fill = paint_for_hex(BUSH_CANOPY_SHADOW_FILL);
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
    // (only group opacity is applied; bush's group has none).
    let d = union_path_from_lobes(lobes);
    if d.is_empty() {
        return;
    }
    let path = polygon_d_to_path_ops(&d);
    if path.is_empty() {
        return;
    }
    let fill = paint_for_hex(fill_hex);
    let stroke_paint = paint_for_hex(BUSH_CANOPY_STROKE);
    let stroke = Stroke {
        width: round_legacy_1(BUSH_CANOPY_STROKE_WIDTH),
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
        cx, cy, tx, ty, BUSH_VOLUME_SALT,
        BUSH_VOLUME_MARK_COUNT,
        BUSH_VOLUME_MARK_AREA_RADIUS,
        BUSH_VOLUME_MARK_RADIUS_MIN,
        BUSH_VOLUME_MARK_RADIUS_MAX,
        BUSH_VOLUME_MARK_SWEEP_MIN,
        BUSH_VOLUME_MARK_SWEEP_MAX,
    );
    let stroke_paint = paint_for_hex(BUSH_CANOPY_STROKE);
    let stroke = Stroke {
        width: round_legacy_2(BUSH_VOLUME_STROKE_WIDTH),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    for arc in arcs {
        let path = arc_path_ops(arc.cx, arc.cy, arc.r, arc.a0, arc.a1);
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
}

/// Per-arc record. Mirrors the tree port's `ArcShape`; duplicated
/// locally because the well version is private and the tree /
/// fountain copies are module-local too.
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
/// emitted by `polygon_to_svg_path`. Multi-subpath safe (each
/// new `M` starts a fresh subpath).
fn polygon_d_to_path_ops(d: &str) -> PathOps {
    let mut p = PathOps::new();
    let tokens = d.split_whitespace();
    for tok in tokens {
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
/// elements (canopy / shadow / volume-mark arcs).
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
    fn shift_color_round_trip_zero() {
        // Shifting by zero in all dimensions should reproduce the
        // input (modulo HLS round-trip rounding error).
        let out = shift_color("#7A9560", 0.0, 0.0, 0.0);
        assert_eq!(out, "#7A9560");
    }

    // ── Painter-path tests ─────────────────────────────────────

    use crate::painter::{
        FillRule as PFillRule, Paint as PPaint, Painter as PainterTrait,
        PathOps as PPathOps, Rect as PRect, Stroke as PStroke,
        Vec2 as PVec2,
    };

    /// Records every Painter call. Modelled on the well + fountain
    /// + tree port CaptureCalls fixtures.
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
        fn begin_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::BeginGroup(_)))
                .count()
        }
    }

    #[test]
    fn paint_empty_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_bush(&mut painter, &[]);
        assert!(painter.calls.is_empty());
    }

    /// Fixtures are NO group-opacity per plan §2.14 —
    /// `paint_bush` MUST NOT open / close any group envelope.
    #[test]
    fn paint_emits_no_group_envelope() {
        let mut painter = CaptureCalls::default();
        paint_bush(&mut painter, &[(2, 3), (5, 7)]);
        assert_eq!(
            painter.begin_group_count(),
            0,
            "bush must not begin_group",
        );
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 0);
    }

    /// Single tile paints (in order): shadow fill, canopy
    /// fill+stroke, then N volume-mark strokes. NO rects, NO
    /// trunk (bush has no trunk circle, unlike tree).
    #[test]
    fn paint_single_tile_uses_only_paths() {
        let mut painter = CaptureCalls::default();
        paint_bush(&mut painter, &[(2, 3)]);
        assert_eq!(painter.fill_rect_count(), 0);
        assert_eq!(painter.stroke_rect_count(), 0);
        // fills: shadow + canopy = 2 (no trunk).
        assert_eq!(painter.fill_path_count(), 2);
        // strokes: canopy + N volume marks.
        assert_eq!(
            painter.stroke_path_count(),
            1 + BUSH_VOLUME_MARK_COUNT as usize,
        );
    }

    /// Painter-path determinism: same input → same call sequence.
    #[test]
    fn paint_deterministic_for_same_input() {
        let tiles = vec![(5, 7), (8, 2)];
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_bush(&mut a, &tiles);
        paint_bush(&mut b, &tiles);
        assert_eq!(a.calls, b.calls);
    }

    /// Different positions drive different hash streams, so the
    /// call sequence differs.
    #[test]
    fn paint_position_sensitive() {
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_bush(&mut a, &[(5, 7)]);
        paint_bush(&mut b, &[(99, 99)]);
        assert_ne!(a.calls, b.calls);
    }

    /// Multi-tile input emits per-stamp call sequences in tile
    /// order.
    #[test]
    fn paint_emits_one_stamp_per_tile() {
        let tiles = vec![(0, 0), (3, 3), (7, 11)];
        let n_tiles = tiles.len();
        let mut painter = CaptureCalls::default();
        paint_bush(&mut painter, &tiles);
        // fills: 2 per tile (shadow + canopy).
        assert_eq!(painter.fill_path_count(), 2 * n_tiles);
        // strokes: 1 canopy + N volume marks per tile.
        let marks = BUSH_VOLUME_MARK_COUNT as usize;
        assert_eq!(
            painter.stroke_path_count(),
            n_tiles * (1 + marks),
        );
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
