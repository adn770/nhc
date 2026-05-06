//! Thematic-detail primitive — Phase 4, sub-step 4.d (plan §8 Q3),
//! ported to the Painter trait in Phase 2.11 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Reproduces ``_tile_thematic_detail`` from
//! ``nhc/rendering/_floor_detail.py`` together with its three
//! per-fragment painters: ``_web_detail`` (spider-web with
//! 3-4 radials and 2 cross-thread rings), ``_bone_detail``
//! (2-3 crossed bones with bulbous epiphyses), and
//! ``_skull_detail`` (hand-drawn skull with cranium, eye
//! sockets, nasal cavity, tooth line, and mandible).
//!
//! Per-tile probabilities and the macabre-detail gate are
//! resolved Rust-side; the per-tile wall-corner bitmap (web
//! placement) and the corridor / room routing flag travel in
//! through the IR (see :func:`_emit_thematic_detail_ir`).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Output is gated by
//! structural invariants
//! (``tests/unit/test_emit_thematic_detail_invariants.py``)
//! plus a snapshot lock against the new Rust output (lands at
//! sub-step 4.f). The RNG is ``Pcg64Mcg::seed_from_u64(seed)``
//! (seed already carries the ``+199`` offset from the emitter).
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_thematic_detail` SVG-string emitter (used
//!   by the FFI / `nhc/rendering/ir_to_svg.py` Python path until
//!   2.17 ships the `SvgPainter`-based PyO3 export and 2.19
//!   retires the Python `ir_to_svg` path).
//! - The new `paint_thematic_detail_side` Painter-based emitter
//!   (used by the Rust `transform/png` path via `SkiaPainter`
//!   and, after 2.17, by the Rust `ir_to_svg` path via
//!   `SvgPainter`).
//!
//! Both paths share the private `tile_shapes_into_buckets` shape-
//! stream generator — the per-tile geometry is RNG-driven and the
//! snapshot/structural-invariants gates require a single source of
//! truth for the per-tile shape sequence.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! Unlike floor_detail's per-bucket envelopes, the thematic-detail
//! envelopes are **per-fragment**:
//!
//! - **Web**: a single self-closing `<path opacity="0.35"/>` —
//!   one shape, one composite at 0.35.
//! - **Bone**: `<g opacity="0.4">…line + ellipses…</g>` per pile.
//! - **Skull**: `<g transform="…" opacity="0.45">…</g>` per skull.
//!
//! The outer per-class envelopes (`<g class="detail-webs">`,
//! `detail-bones`, `detail-skulls`) carry NO opacity attribute —
//! they're class markers for CSS and composite at 1.0. The
//! Painter port wraps each per-fragment composite in
//! `begin_group(opacity) / end_group()` so overlapping stamps
//! composite via the offscreen-buffer mechanism (Phase 5.10's
//! `paint_offscreen_group` lifted into `SkiaPainter`).
//!
//! Pre-2.11 the PNG handler dispatched through `paint_fragments`,
//! which only handles a single level of `<g>` wrapper and silently
//! mishandles the nested per-fragment groups inside the
//! per-class envelope. Phase 2.11's Painter port renders the
//! nested groups correctly; PNG output diverges slightly from
//! pre-port references for fixtures that exercise bones / skulls.

use std::f64::consts::PI;

use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};

const CELL: f64 = 32.0;
const INK: &str = "#000000";

/// Per-fragment opacity for a single web stamp. Lifts the
/// `opacity="0.35"` attribute on the legacy `<path>` element.
pub const WEB_OPACITY: f32 = 0.35;
/// Per-fragment opacity for a single bone pile. Lifts the
/// `<g opacity="0.4">` envelope.
pub const BONE_OPACITY: f32 = 0.4;
/// Per-fragment opacity for a single skull. Lifts the
/// `<g transform="…" opacity="0.45">` envelope.
pub const SKULL_OPACITY: f32 = 0.45;

#[derive(Clone, Copy, Default)]
struct ThemeProbs {
    web: f64,
    bones: f64,
    skull: f64,
}

/// Per-theme probabilities — mirrors ``_THEMATIC_DETAIL_PROBS``
/// from ``nhc/rendering/_floor_detail.py``. Default falls back
/// to the dungeon row.
fn theme_probs(theme: &str) -> ThemeProbs {
    match theme {
        "crypt" => ThemeProbs { web: 0.08, bones: 0.10, skull: 0.06 },
        "cave" => ThemeProbs { web: 0.12, bones: 0.04, skull: 0.02 },
        "sewer" => ThemeProbs { web: 0.06, bones: 0.03, skull: 0.01 },
        "castle" => ThemeProbs { web: 0.02, bones: 0.01, skull: 0.005 },
        "forest" => ThemeProbs { web: 0.04, bones: 0.01, skull: 0.005 },
        "abyss" => ThemeProbs { web: 0.05, bones: 0.08, skull: 0.10 },
        _ => ThemeProbs { web: 0.03, bones: 0.02, skull: 0.01 }, // dungeon
    }
}

// ── Shape stream ──────────────────────────────────────────────

/// One spider-web stamp — a single `<path>` with N radial M-L
/// commands plus 2 rings of cross-threads (M-Q-L per pair). The
/// path geometry travels as raw `parts` so both emit paths
/// (SVG-string formatter / Painter dispatch) consume the same
/// RNG-baked geometry verbatim.
#[derive(Clone, Debug, PartialEq)]
pub struct WebShape {
    /// Pre-formatted SVG path-`d` segments (`M…L…` for each
    /// radial; `M…Q…` for each cross-thread). Joined with spaces
    /// for SVG; walked as PathOps for Painter via the same parse.
    pub parts: Vec<String>,
    /// Stroke width in pixels.
    pub sw: f64,
}

/// One bone — a `<line>` axis with two ellipse epiphyses at its
/// endpoints. Stroke width is fixed at 1.2 in the legacy
/// emitter (matches the SVG `stroke-width="1.2"` attribute).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Bone {
    pub x1: f64,
    pub y1: f64,
    pub x2: f64,
    pub y2: f64,
    pub er: f64,
}

/// One bone pile — 2-3 crossed bones, painted under a single
/// `begin_group(BONE_OPACITY)` / `end_group()` envelope.
#[derive(Clone, Debug, PartialEq)]
pub struct BonesShape {
    pub bones: Vec<Bone>,
}

/// One skull — translate+rotate group with cranium / eyes /
/// nasal / tooth-line / mandible. Sub-shape coords are baked
/// against a local origin; the (cx, cy, rot_deg) pre-multiply
/// into world coords for the Painter path so we don't need a
/// transform stack.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SkullShape {
    pub cx: f64,
    pub cy: f64,
    pub rot_deg: f64,
    pub s: f64,
}

/// A single per-tile fragment in legacy emit order.
#[derive(Clone, Debug, PartialEq)]
pub enum ThematicDetailShape {
    Web(WebShape),
    Bones(BonesShape),
    Skull(SkullShape),
}

/// Per-side bucket triple in legacy emit order:
/// `(webs, bones, skulls)`. Used as the source of truth for
/// both the SVG-string formatter and the Painter dispatcher.
type SideShapes = (
    Vec<ThematicDetailShape>,
    Vec<ThematicDetailShape>,
    Vec<ThematicDetailShape>,
);

fn empty_side() -> SideShapes {
    (Vec::new(), Vec::new(), Vec::new())
}
/// Walk every tile once and yield three buckets per side
/// (room, corridor) — `(webs, bones, skulls)` per side. Mirrors
/// the legacy `_render_thematic_detail` per-tile dispatch. When
/// `macabre` is `false`, every bones / skull bucket is dropped
/// (legacy `if not macabre_detail: bones, skulls = [], []`
/// post-pass).
pub fn thematic_detail_shapes(
    tiles: &[(i32, i32, bool, u8)],
    seed: u64,
    theme: &str,
    macabre: bool,
) -> (SideShapes, SideShapes) {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let probs = theme_probs(theme);

    let mut room = empty_side();
    let mut corridor = empty_side();

    for &(x, y, is_corridor, wall_bits) in tiles {
        let target = if is_corridor { &mut corridor } else { &mut room };
        tile_shapes_into_buckets(&mut rng, x, y, wall_bits, &probs, target);
    }

    if !macabre {
        room.1.clear();
        room.2.clear();
        corridor.1.clear();
        corridor.2.clear();
    }

    (room, corridor)
}

// ── Per-tile shape generation ─────────────────────────────────

/// Spider-web shape — mirrors ``_web_detail``. ``corner``:
/// 0=TL, 1=TR, 2=BL, 3=BR. Anchored at the wall corner of the
/// tile, radiating into the interior.
fn web_shape(rng: &mut Pcg64Mcg, px: f64, py: f64, corner: i32) -> WebShape {
    let cx = if corner == 0 || corner == 2 { px } else { px + CELL };
    let cy = if corner == 0 || corner == 1 { py } else { py + CELL };
    let sx: f64 = if corner == 0 || corner == 2 { 1.0 } else { -1.0 };
    let sy: f64 = if corner == 0 || corner == 1 { 1.0 } else { -1.0 };

    let n_radials: i32 = rng.gen_range(3..=4);
    let radial_len: f64 =
        rng.gen_range((CELL * 0.5)..(CELL * 0.85));
    let mut angles: Vec<f64> = (0..n_radials)
        .map(|_| rng.gen_range(0.0..(PI / 2.0)))
        .collect();
    angles.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let mut parts: Vec<String> = Vec::new();

    // For each radial, emit the radial M-L plus two ring-points
    // for the cross-thread loops.
    let mut ring_pts: Vec<[(f64, f64); 2]> = Vec::new();
    for &a in &angles {
        let dx = sx * a.cos() * radial_len;
        let dy = sy * a.sin() * radial_len;
        let ex = cx + dx;
        let ey = cy + dy;
        parts.push(format!(
            "M{cx:.1},{cy:.1} L{ex:.1},{ey:.1}",
        ));
        ring_pts.push([
            (cx + dx * 0.4, cy + dy * 0.4),
            (cx + dx * 0.7, cy + dy * 0.7),
        ]);
    }

    // Cross-threads connecting consecutive radials at each ring.
    for ring_idx in 0..2 {
        for i in 0..(ring_pts.len().saturating_sub(1)) {
            let p1 = ring_pts[i][ring_idx];
            let p2 = ring_pts[i + 1][ring_idx];
            let mx = (p1.0 + p2.0) / 2.0 + rng.gen_range(-1.5..1.5);
            let my = (p1.1 + p2.1) / 2.0 + rng.gen_range(-1.5..1.5);
            parts.push(format!(
                "M{:.1},{:.1} Q{mx:.1},{my:.1} {:.1},{:.1}",
                p1.0, p1.1, p2.0, p2.1,
            ));
        }
    }

    let sw: f64 = rng.gen_range(0.3..0.6);
    WebShape { parts, sw }
}

/// Pile of 2-3 crossed bones — mirrors ``_bone_detail``. RNG
/// consumption order is preserved verbatim against the legacy
/// emitter so the SVG / Painter paths stay stamp-for-stamp
/// aligned.
fn bones_shape(rng: &mut Pcg64Mcg, px: f64, py: f64) -> BonesShape {
    let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let n_bones: i32 = rng.gen_range(2..=3);

    let mut bones: Vec<Bone> = Vec::with_capacity(n_bones as usize);
    for _ in 0..n_bones {
        let angle: f64 = rng.gen_range(0.0..PI);
        let length: f64 =
            rng.gen_range((CELL * 0.2)..(CELL * 0.35));
        let dx = angle.cos() * length / 2.0;
        let dy = angle.sin() * length / 2.0;
        let bx = cx + rng.gen_range((-CELL * 0.08)..(CELL * 0.08));
        let by = cy + rng.gen_range((-CELL * 0.08)..(CELL * 0.08));
        let x1 = bx - dx;
        let y1 = by - dy;
        let x2 = bx + dx;
        let y2 = by + dy;
        let er: f64 = rng.gen_range(1.2..1.8);
        bones.push(Bone { x1, y1, x2, y2, er });
    }
    BonesShape { bones }
}

/// Hand-drawn skull — mirrors ``_skull_detail``. Just records
/// the placement params (cx, cy, rot, scale); the per-element
/// geometry is derived in lock-step by `format_skull_svg` /
/// `paint_skull` so the same numbers land in both paths.
fn skull_shape(rng: &mut Pcg64Mcg, px: f64, py: f64) -> SkullShape {
    let cx = px + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let cy = py + rng.gen_range((CELL * 0.3)..(CELL * 0.7));
    let s: f64 = rng.gen_range(0.8..1.2);
    let rot: f64 = rng.gen_range(-20.0..20.0);
    SkullShape { cx, cy, rot_deg: rot, s }
}

/// Per-tile thematic painter — mirrors
/// ``_tile_thematic_detail`` from
/// ``nhc/rendering/_floor_detail.py``. The probability gates
/// fire in legacy order (web → bones → skull) so the RNG-stream
/// alignment matches the legacy interleaved walk.
fn tile_shapes_into_buckets(
    rng: &mut Pcg64Mcg,
    x: i32,
    y: i32,
    wall_bits: u8,
    probs: &ThemeProbs,
    side: &mut SideShapes,
) {
    let (ref mut webs, ref mut bones, ref mut skulls) = *side;

    let px = f64::from(x) * CELL;
    let py = f64::from(y) * CELL;

    if rng.gen::<f64>() < probs.web {
        let mut available: Vec<i32> = Vec::with_capacity(4);
        if wall_bits & 0x01 != 0 {
            available.push(0);
        }
        if wall_bits & 0x02 != 0 {
            available.push(1);
        }
        if wall_bits & 0x04 != 0 {
            available.push(2);
        }
        if wall_bits & 0x08 != 0 {
            available.push(3);
        }
        if !available.is_empty() {
            // Random pick mirrors `random.choice`.
            let &corner = available.choose(rng).unwrap();
            webs.push(ThematicDetailShape::Web(web_shape(rng, px, py, corner)));
        }
    }

    if rng.gen::<f64>() < probs.bones {
        bones.push(ThematicDetailShape::Bones(bones_shape(rng, px, py)));
    }

    if rng.gen::<f64>() < probs.skull {
        skulls.push(ThematicDetailShape::Skull(skull_shape(rng, px, py)));
    }
}

// ── Anchor-placement entry point (v5 emit) ────────────────────

/// Per-anchor placement record — what the v5 emit pipeline ships
/// as a `FixtureOp` anchor. ``kind`` is one of
/// `KIND_WEB` / `KIND_BONES` / `KIND_SKULL`; ``orientation`` carries
/// the web corner (0=NW, 1=NE, 2=SW, 3=SE per the legacy
/// `wall_bits` encoding) for Web kind, otherwise 0.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ThematicDetailPlacement {
    pub kind: u8,
    pub x: i32,
    pub y: i32,
    pub orientation: u8,
}

pub const KIND_WEB: u8 = 0;
pub const KIND_BONES: u8 = 2;
pub const KIND_SKULL: u8 = 1;

/// Run the v4 thematic-detail probability gate to determine which
/// tiles get web / bone / skull placements. Walks the same RNG
/// stream as `thematic_detail_shapes` so the gate decisions are
/// byte-equal between the v4 paint path (which calls
/// `thematic_detail_shapes` and renders shapes inline) and the v5
/// emit path (which calls this function to land explicit
/// FixtureOp anchors).
///
/// The macabre gate drops bones / skulls when ``macabre`` is
/// `false` — same post-pass the legacy emitter applies.
pub fn thematic_detail_placements(
    tiles: &[(i32, i32, bool, u8)],
    seed: u64,
    theme: &str,
    macabre: bool,
) -> Vec<ThematicDetailPlacement> {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let probs = theme_probs(theme);
    let mut out: Vec<ThematicDetailPlacement> = Vec::new();

    for &(x, y, _is_corridor, wall_bits) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;

        // Web gate — consume the same RNG samples the painter
        // would, so subsequent tiles see the same RNG state.
        if rng.gen::<f64>() < probs.web {
            let mut available: Vec<i32> = Vec::with_capacity(4);
            if wall_bits & 0x01 != 0 { available.push(0); }
            if wall_bits & 0x02 != 0 { available.push(1); }
            if wall_bits & 0x04 != 0 { available.push(2); }
            if wall_bits & 0x08 != 0 { available.push(3); }
            if !available.is_empty() {
                let &corner = available.choose(&mut rng).unwrap();
                // Drain the same RNG samples ``web_shape`` consumes
                // so the gate's RNG stream stays aligned with the
                // v4 painter's stream.
                let _ = web_shape(&mut rng, px, py, corner);
                out.push(ThematicDetailPlacement {
                    kind: KIND_WEB,
                    x,
                    y,
                    orientation: corner as u8,
                });
            }
        }

        // Bones gate — same RNG-drain pattern.
        if rng.gen::<f64>() < probs.bones {
            let _ = bones_shape(&mut rng, px, py);
            if macabre {
                out.push(ThematicDetailPlacement {
                    kind: KIND_BONES,
                    x,
                    y,
                    orientation: 0,
                });
            }
        }

        // Skull gate — same RNG-drain pattern.
        if rng.gen::<f64>() < probs.skull {
            let _ = skull_shape(&mut rng, px, py);
            if macabre {
                out.push(ThematicDetailPlacement {
                    kind: KIND_SKULL,
                    x,
                    y,
                    orientation: 0,
                });
            }
        }
    }

    out
}

// ── Legacy SVG-string emit path ───────────────────────────────
// ── Painter dispatcher ────────────────────────────────────────

/// Paint a single side's bucket stream onto `painter`. Each
/// per-fragment shape is wrapped in `begin_group(opacity)` /
/// `end_group()` to match the legacy SVG per-fragment opacity
/// envelopes (web 0.35, bone 0.4, skull 0.45). Per-tile emission
/// order is preserved verbatim within each bucket.
pub fn paint_thematic_detail_side(
    painter: &mut dyn Painter,
    side: &SideShapes,
) {
    let (webs, bones, skulls) = side;
    for shape in webs {
        if let ThematicDetailShape::Web(w) = shape {
            painter.begin_group(WEB_OPACITY);
            paint_web(painter, w);
            painter.end_group();
        }
    }
    for shape in bones {
        if let ThematicDetailShape::Bones(b) = shape {
            painter.begin_group(BONE_OPACITY);
            paint_bones(painter, b);
            painter.end_group();
        }
    }
    for shape in skulls {
        if let ThematicDetailShape::Skull(k) = shape {
            painter.begin_group(SKULL_OPACITY);
            paint_skull(painter, k);
            painter.end_group();
        }
    }
}

fn paint_web(painter: &mut dyn Painter, w: &WebShape) {
    // Each `parts[i]` is either an `M…L…` (radial) or `M…Q…`
    // (cross-thread) segment. The legacy SVG path emits all
    // numbers through `{:.1}`, so route every PathOps coord
    // through `round_legacy` to land at the same f32 the SVG
    // round-trip would arrive at.
    let mut path = PathOps::new();
    for seg in &w.parts {
        parse_web_segment(seg, &mut path);
    }
    painter.stroke_path(
        &path,
        &paint_for_hex(INK),
        &Stroke {
            width: round_legacy(w.sw),
            line_cap: LineCap::Round,
            line_join: LineJoin::Miter,
        },
    );
}

/// Parse one of the `M…L…` / `M…Q…` segments produced by
/// `web_shape` into PathOps. The format is fixed (we emit it
/// ourselves a few lines above) so we can trust the structure
/// — split on whitespace and dispatch per command letter.
fn parse_web_segment(seg: &str, path: &mut PathOps) {
    // Tokens are space-separated; each token starts with a
    // command letter (`M`, `L`, `Q`) followed by `x,y` or
    // `x,y x,y` (Q has two coord pairs).
    let mut tokens = seg.split_whitespace().peekable();
    while let Some(tok) = tokens.next() {
        let (cmd, first) = tok.split_at(1);
        match cmd {
            "M" => {
                let (x, y) = parse_xy(first);
                path.move_to(Vec2::new(round_legacy(x), round_legacy(y)));
            }
            "L" => {
                let (x, y) = parse_xy(first);
                path.line_to(Vec2::new(round_legacy(x), round_legacy(y)));
            }
            "Q" => {
                let (cx, cy) = parse_xy(first);
                // The endpoint is the next token (no command
                // letter — it's an implicit continuation of `Q`).
                let next = tokens.next().expect("Q without endpoint");
                let (ex, ey) = parse_xy(next);
                path.quad_to(
                    Vec2::new(round_legacy(cx), round_legacy(cy)),
                    Vec2::new(round_legacy(ex), round_legacy(ey)),
                );
            }
            _ => {}
        }
    }
}

fn parse_xy(s: &str) -> (f64, f64) {
    let mut it = s.splitn(2, ',');
    let x: f64 = it.next().and_then(|t| t.parse().ok()).unwrap_or(0.0);
    let y: f64 = it.next().and_then(|t| t.parse().ok()).unwrap_or(0.0);
    (x, y)
}

fn paint_bones(painter: &mut dyn Painter, b: &BonesShape) {
    for bone in &b.bones {
        // Bone axis — `<line>` with stroke-width 1.2, round caps.
        let mut line = PathOps::new();
        line.move_to(Vec2::new(
            round_legacy(bone.x1),
            round_legacy(bone.y1),
        ));
        line.line_to(Vec2::new(
            round_legacy(bone.x2),
            round_legacy(bone.y2),
        ));
        painter.stroke_path(
            &line,
            &paint_for_hex(INK),
            &Stroke {
                width: round_legacy(1.2),
                line_cap: LineCap::Round,
                line_join: LineJoin::Miter,
            },
        );
        // Two epiphyses — `<ellipse>` filled, no stroke.
        let er = round_legacy(bone.er);
        for (ex, ey) in [(bone.x1, bone.y1), (bone.x2, bone.y2)] {
            painter.fill_ellipse(
                round_legacy(ex),
                round_legacy(ey),
                er,
                er,
                &paint_for_hex(INK),
            );
        }
    }
}

fn paint_skull(painter: &mut dyn Painter, k: &SkullShape) {
    let s = k.s;
    let sw = 0.7_f64;

    let cw = 4.5 * s;
    let ch = 5.0 * s;
    let zw = cw * 0.85;
    let mw = cw * 0.55;

    let top_y = -ch;
    let zyg_y = ch * 0.35;
    let max_y = ch * 0.55;

    // The legacy SVG emits the skull inside a
    // `<g transform="translate(cx,cy) rotate(rot)">` — here we
    // bake the transform into local coords via the same `{:.1}`
    // round-trip lens (translate / rotate apply post-truncation
    // of the local coord, mirroring the SVG attribute parse
    // chain).
    let cos_t = k.rot_deg.to_radians().cos();
    let sin_t = k.rot_deg.to_radians().sin();
    let xform = |lx: f64, ly: f64| -> Vec2 {
        // Mirror the SVG round-trip: each legacy parts[i]
        // string emits `lx`, `ly` through `{:.1}`. Apply
        // `round_legacy` BEFORE the rotate+translate so the
        // local-coord truncation happens at the same point as
        // the SVG round-trip.
        let lx = f64::from(round_legacy(lx));
        let ly = f64::from(round_legacy(ly));
        let rx = lx * cos_t - ly * sin_t;
        let ry = lx * sin_t + ly * cos_t;
        Vec2::new((k.cx + rx) as f32, (k.cy + ry) as f32)
    };

    // Cranium
    {
        let mut path = PathOps::new();
        path.move_to(xform(-zw, zyg_y));
        path.cubic_to(xform(-cw, -ch * 0.2), xform(-cw * 0.6, top_y), xform(0.0, top_y));
        path.cubic_to(xform(cw * 0.6, top_y), xform(cw, -ch * 0.2), xform(zw, zyg_y));
        path.line_to(xform(mw, max_y));
        path.line_to(xform(-mw, max_y));
        path.close();
        painter.stroke_path(
            &path,
            &paint_for_hex(INK),
            &Stroke {
                width: round_legacy(sw),
                line_cap: LineCap::Butt,
                line_join: LineJoin::Miter,
            },
        );
    }

    // Eye sockets — `<ellipse>` filled. The skull's transform
    // includes a rotation, so axis-aligned `fill_ellipse` would
    // ignore it; emit the rotated ellipse path explicitly.
    let eye_y = -ch * 0.05;
    let eye_sep = cw * 0.42;
    let eye_rx = cw * 0.26;
    let eye_ry = ch * 0.16;
    for ex in [-eye_sep, eye_sep] {
        let path = rotated_ellipse_path_local(
            ex,
            eye_y,
            eye_rx,
            eye_ry,
            k.cx,
            k.cy,
            cos_t,
            sin_t,
        );
        painter.fill_path(&path, &paint_for_hex(INK), FillRule::Winding);
    }

    // Nasal cavity — triangle path filled.
    let nose_y = ch * 0.2;
    let nose_w = cw * 0.18;
    let nose_h = ch * 0.2;
    {
        let mut path = PathOps::new();
        path.move_to(xform(0.0, nose_y));
        path.line_to(xform(-nose_w, nose_y + nose_h));
        path.line_to(xform(nose_w, nose_y + nose_h));
        path.close();
        painter.fill_path(&path, &paint_for_hex(INK), FillRule::Winding);
    }

    // Tooth line — dashed `<line>`. tiny-skia doesn't support
    // dash patterns through the Painter trait yet (no Stroke
    // dash field); emit a short stroked line at the same
    // coords. The dash pattern is cosmetic over a 1-2 px line —
    // the offscreen group composite at SKULL_OPACITY hides the
    // visual difference at fixture resolution.
    let tooth_y = max_y + s * 0.8;
    let tooth_w = mw * 0.75;
    {
        let mut path = PathOps::new();
        path.move_to(xform(-tooth_w, tooth_y));
        path.line_to(xform(tooth_w, tooth_y));
        painter.stroke_path(
            &path,
            &paint_for_hex(INK),
            &Stroke {
                width: round_legacy(0.4),
                line_cap: LineCap::Butt,
                line_join: LineJoin::Miter,
            },
        );
    }

    // Mandible
    let jaw_top = max_y + s * 0.4;
    let chin_y = max_y + ch * 0.55;
    let ramus_w = mw * 1.05;
    let chin_w = mw * 0.35;
    {
        let mut path = PathOps::new();
        path.move_to(xform(-ramus_w, jaw_top));
        path.cubic_to(
            xform(-ramus_w, chin_y - s),
            xform(-chin_w, chin_y),
            xform(0.0, chin_y),
        );
        path.cubic_to(
            xform(chin_w, chin_y),
            xform(ramus_w, chin_y - s),
            xform(ramus_w, jaw_top),
        );
        painter.stroke_path(
            &path,
            &paint_for_hex(INK),
            &Stroke {
                width: round_legacy(sw),
                line_cap: LineCap::Butt,
                line_join: LineJoin::Miter,
            },
        );
    }
}

/// Build a closed cubic-Bezier ellipse path centred at local
/// `(lx, ly)`, with radii `(rx, ry)`, then transformed into world
/// coords via the skull's `(cx, cy)` translate and the supplied
/// `(cos_t, sin_t)` rotation. KAPPA approximation matches
/// `floor_detail::rotated_ellipse_path` and `primitives::hatch`.
fn rotated_ellipse_path_local(
    lx: f64,
    ly: f64,
    rx: f64,
    ry: f64,
    cx: f64,
    cy: f64,
    cos_t: f64,
    sin_t: f64,
) -> PathOps {
    const KAPPA: f64 = 0.552_284_8;
    let ox = rx * KAPPA;
    let oy = ry * KAPPA;
    let xform = |dx: f64, dy: f64| -> Vec2 {
        // Mirror the SVG `{:.1}` round-trip on the local-frame
        // coord (lx + dx, ly + dy) BEFORE the world transform.
        let lx = f64::from(round_legacy(lx + dx));
        let ly = f64::from(round_legacy(ly + dy));
        let rx = lx * cos_t - ly * sin_t;
        let ry = lx * sin_t + ly * cos_t;
        Vec2::new((cx + rx) as f32, (cy + ry) as f32)
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
/// reparse. Same helper as `floor_detail::round_legacy`.
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::{Paint, Painter, PathOps, Rect, Stroke, Vec2};
    // ── Painter-path tests ─────────────────────────────────────

    /// Records every Painter call. Mirrors the floor_detail
    /// CaptureCalls fixture so the assertions stay close to the
    /// primitive.
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
        FillEllipse,
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
            self.calls.push(Call::FillEllipse);
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
            // bucket constants are 0.35 / 0.40 / 0.45 so two
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
    /// spurious begin_group / end_group fires.
    #[test]
    fn paint_thematic_detail_side_empty_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        let empty = empty_side();
        paint_thematic_detail_side(&mut painter, &empty);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// Crypt + macabre + wall corners → all three buckets fire
    /// with the documented per-fragment opacities.
    #[test]
    fn paint_thematic_detail_side_wraps_per_fragment_in_groups() {
        let tiles: Vec<(i32, i32, bool, u8)> = (0..30)
            .flat_map(|y| {
                (0..30).map(move |x| (x, y, false, 0x0F_u8))
            })
            .collect();
        let (room, _) = thematic_detail_shapes(&tiles, 199, "abyss", true);
        // Sanity: this seed/theme produces all three bucket types.
        assert!(!room.0.is_empty(), "expected non-empty webs");
        assert!(!room.1.is_empty(), "expected non-empty bones");
        assert!(!room.2.is_empty(), "expected non-empty skulls");

        let mut painter = CaptureCalls::default();
        paint_thematic_detail_side(&mut painter, &room);

        assert_eq!(painter.group_depth, 0);
        assert_eq!(
            painter.begin_group_count(),
            painter.end_group_count(),
        );
        assert!(
            painter.max_group_depth <= 1,
            "per-fragment groups must not nest — max depth {}",
            painter.max_group_depth,
        );
        // begin_group count = total fragments (web + bones + skull).
        assert_eq!(
            painter.begin_group_count(),
            room.0.len() + room.1.len() + room.2.len(),
        );
    }

    /// Group wrapper opacities match the documented per-fragment
    /// constants (0.35 web, 0.4 bone, 0.45 skull) in legacy
    /// emission order.
    #[test]
    fn paint_thematic_detail_side_uses_documented_per_fragment_opacities() {
        let tiles: Vec<(i32, i32, bool, u8)> = (0..30)
            .flat_map(|y| {
                (0..30).map(move |x| (x, y, false, 0x0F_u8))
            })
            .collect();
        let (room, _) = thematic_detail_shapes(&tiles, 199, "abyss", true);
        assert!(!room.0.is_empty() && !room.1.is_empty() && !room.2.is_empty());

        let mut painter = CaptureCalls::default();
        paint_thematic_detail_side(&mut painter, &room);

        let opacities = painter.opacities();
        // Each web → BeginGroup(35), each bone → BeginGroup(40),
        // each skull → BeginGroup(45). Order is (webs, bones,
        // skulls) per side.
        let want_web = (WEB_OPACITY * 100.0).round() as u32;
        let want_bone = (BONE_OPACITY * 100.0).round() as u32;
        let want_skull = (SKULL_OPACITY * 100.0).round() as u32;
        let mut web_count = 0;
        let mut bone_count = 0;
        let mut skull_count = 0;
        for op in &opacities {
            if *op == want_web {
                web_count += 1;
            } else if *op == want_bone {
                bone_count += 1;
            } else if *op == want_skull {
                skull_count += 1;
            } else {
                panic!("unexpected opacity {op}");
            }
        }
        assert_eq!(web_count, room.0.len(), "web count mismatch");
        assert_eq!(bone_count, room.1.len(), "bone count mismatch");
        assert_eq!(skull_count, room.2.len(), "skull count mismatch");
    }

    /// macabre=false → bones / skulls buckets are empty so their
    /// groups do not fire; webs still wrap normally.
    #[test]
    fn paint_thematic_detail_side_macabre_off_drops_bone_skull_groups() {
        let tiles: Vec<(i32, i32, bool, u8)> = (0..30)
            .flat_map(|y| {
                (0..30).map(move |x| (x, y, false, 0x0F_u8))
            })
            .collect();
        let (room, _) = thematic_detail_shapes(&tiles, 199, "abyss", false);
        assert!(room.1.is_empty(), "bones bucket must be empty");
        assert!(room.2.is_empty(), "skulls bucket must be empty");

        let mut painter = CaptureCalls::default();
        paint_thematic_detail_side(&mut painter, &room);

        let opacities = painter.opacities();
        let want_bone = (BONE_OPACITY * 100.0).round() as u32;
        let want_skull = (SKULL_OPACITY * 100.0).round() as u32;
        assert!(
            !opacities.contains(&want_bone),
            "bone group must not fire when macabre=false; got {:?}",
            opacities,
        );
        assert!(
            !opacities.contains(&want_skull),
            "skull group must not fire when macabre=false; got {:?}",
            opacities,
        );
        assert_eq!(painter.group_depth, 0);
    }

    /// Cross-check: SVG-string emitter and Painter emitter agree
    /// on per-bucket fragment counts for the same seed/tiles.
    #[test]
    fn paint_and_draw_agree_on_bucket_counts() {
        let tiles: Vec<(i32, i32, bool, u8)> = (0..20)
            .flat_map(|y| {
                (0..20).map(move |x| (x, y, false, 0x0F_u8))
            })
            .collect();
        let seed = 199;

        let (room, _) =
            thematic_detail_shapes(&tiles, seed, "abyss", true);

        let mut painter = CaptureCalls::default();
        paint_thematic_detail_side(&mut painter, &room);

        // Each web contributes 1 stroke_path, each bone in a
        // pile contributes 1 stroke_path + 2 fill_ellipse, each
        // skull contributes 4 stroke_paths + 3 fill_paths
        // (cranium, tooth, mandible strokes; 2 eye fills + nasal
        // fill).
        let total_bones: usize = room
            .1
            .iter()
            .map(|s| match s {
                ThematicDetailShape::Bones(b) => b.bones.len(),
                _ => 0,
            })
            .sum();
        let want_stroke = room.0.len()  // web paths
            + total_bones  // bone axes
            + room.2.len() * 3;  // cranium + tooth + mandible
        let want_fill_ellipse = total_bones * 2; // epiphyses
        let want_fill_path = room.2.len() * 3; // 2 eyes + nasal

        assert_eq!(
            painter.count(&Call::StrokePath),
            want_stroke,
            "stroke_path count mismatch",
        );
        assert_eq!(
            painter.count(&Call::FillEllipse),
            want_fill_ellipse,
            "fill_ellipse count (epiphyses) mismatch",
        );
        assert_eq!(
            painter.count(&Call::FillPath),
            want_fill_path,
            "fill_path count (eyes + nasal) mismatch",
        );
    }
}
