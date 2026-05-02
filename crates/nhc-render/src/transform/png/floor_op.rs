//! FloorOp rasterisation — Phase 1.17 / 1.18 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Reads `FloorOp.outline` + `FloorOp.style` from the IR and
//! fills via tiny-skia primitives.
//!
//! Dispatch by `outline.descriptor_kind`:
//! - `Polygon` + `DungeonFloor`: walk `outline.vertices`, build a
//!   filled path (white floor colour, `FillRule::Winding`).
//! - `Polygon` + `CaveFloor`: Phase 1.18 — runs the real cave
//!   geometry pipeline (`cave_path_from_outline`) reading
//!   `FloorOp.outline.vertices`. The 1.17 provisional bridge that
//!   read the legacy `cave_region` SVG-path string is retired here.
//!   Phase 1.19 (stop legacy emit) is now unblocked for cave geometry.
//! - `Circle`: tiny-skia `PathBuilder::push_oval` centered on
//!   `(cx, cy)` with radius `rx`.
//! - `Pill`: tiny-skia `PathBuilder::push_rounded_rect` covering
//!   `[cx-rx, cy-ry, 2*rx, 2*ry]` with corner radius `min(rx,ry)`.
//!
//! The `walls_and_floors.rs` legacy floor pass is gated off when
//! FloorOps are present: `draw_corridor_tiles`, `draw_rect_rooms`,
//! and `draw_cave_region` are all suppressed. Wall passes are gated
//! off by Phase 1.18 wall-op handlers (see `exterior_wall_op.rs`).

use tiny_skia::{Color, FillRule, Paint, PathBuilder, Rect};

use crate::geometry::cave_path_from_outline;
use crate::ir::{FloorIR, FloorStyle, Op, OpEntry, OutlineKind};

use super::path_parser::parse_path_d;
use super::RasterCtx;

// Colour constants — match the existing palette in
// `walls_and_floors.rs` exactly; do NOT redefine.
const FLOOR_R: u8 = 0xFF;
const FLOOR_G: u8 = 0xFF;
const FLOOR_B: u8 = 0xFF;
const CAVE_FLOOR_R: u8 = 0xF5;
const CAVE_FLOOR_G: u8 = 0xEB;
const CAVE_FLOOR_B: u8 = 0xD8;
// Phase 1.20b — wood-floor brown for buildings with
// `interior_finish == "wood"`. Mirrors Python's
// `nhc/rendering/_floor_detail.py:WOOD_FLOOR_FILL = "#B58B5A"`.
const WOOD_FLOOR_R: u8 = 0xB5;
const WOOD_FLOOR_G: u8 = 0x8B;
const WOOD_FLOOR_B: u8 = 0x5A;

fn dungeon_floor_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(FLOOR_R, FLOOR_G, FLOOR_B, 0xFF));
    p.anti_alias = true;
    p
}

fn cave_floor_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(
        CAVE_FLOOR_R,
        CAVE_FLOOR_G,
        CAVE_FLOOR_B,
        0xFF,
    ));
    p.anti_alias = true;
    p
}

fn wood_floor_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(
        WOOD_FLOOR_R,
        WOOD_FLOOR_G,
        WOOD_FLOOR_B,
        0xFF,
    ));
    p.anti_alias = true;
    p
}

/// Return `true` if the IR contains any `FloorOp` entries.
///
/// Called by `walls_and_floors::draw` to gate the legacy floor pass
/// off when the new FloorOp handler owns the floor surface.
pub(super) fn has_floor_ops(fir: &FloorIR<'_>) -> bool {
    let ops = match fir.ops() {
        Some(o) => o,
        None => return false,
    };
    ops.iter().any(|e| e.op_type() == Op::FloorOp)
}

/// Return `true` if the IR contains any `FloorOp` with
/// `style == CaveFloor`.
///
/// Called by `walls_and_floors::draw` to gate `draw_cave_region`
/// off when the new FloorOp handler owns the cave fill.
pub(super) fn has_cave_floor_op(fir: &FloorIR<'_>) -> bool {
    let ops = match fir.ops() {
        Some(o) => o,
        None => return false,
    };
    ops.iter().any(|e| {
        if e.op_type() != Op::FloorOp {
            return false;
        }
        e.op_as_floor_op()
            .map(|op| op.style() == FloorStyle::CaveFloor)
            .unwrap_or(false)
    })
}

/// `OpHandler` dispatch entry — registered against `Op::FloorOp`
/// in `super::op_handlers`.
///
/// Phase 1.23a — region-keyed dispatch: when ``op.region_ref`` is
/// non-empty AND resolves to a Region with a populated outline,
/// the geometry comes from ``region.outline()`` instead of
/// ``op.outline()``. The op's own outline survives as the fallback
/// for per-tile corridor FloorOps (no per-tile Region) and for 3.x
/// cached buffers that pre-date the field. Mirrors the Python
/// consumer in ``ir_to_svg.py::_draw_floor_op_from_ir``.
pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_floor_op() {
        Some(o) => o,
        None => return,
    };
    // Resolve geometry: prefer the Region's outline when region_ref
    // is non-empty AND points to a known Region; otherwise fall back
    // to the op's own outline.
    let region_outline = match op.region_ref() {
        Some(rr) if !rr.is_empty() => {
            find_region(fir, rr).and_then(|r| r.outline())
        }
        _ => None,
    };
    let outline = match region_outline.or_else(|| op.outline()) {
        Some(o) => o,
        None => return,
    };
    let style = op.style();
    match outline.descriptor_kind() {
        OutlineKind::Circle => draw_circle(&outline, style, ctx),
        OutlineKind::Pill => draw_pill(&outline, style, ctx),
        OutlineKind::Polygon => {
            if style == FloorStyle::CaveFloor {
                draw_cave_floor(&outline, fir, ctx);
            } else {
                draw_polygon(&outline, style, ctx);
            }
        }
        _ => {}
    }
}

/// Linear scan of `fir.regions()` for the Region with id matching
/// `region_ref`. Mirrors `_find_region` in `ir_to_svg.py`. Cheap
/// for the starter fixtures (~20 regions × ~20 room ops per parity
/// test); revisit with a regions-by-id map if a fixture grows past
/// a couple hundred regions and the lookup shows up in profiling.
fn find_region<'a>(
    fir: &FloorIR<'a>,
    needle: &str,
) -> Option<crate::ir::Region<'a>> {
    if needle.is_empty() {
        return None;
    }
    let regions = fir.regions()?;
    for i in 0..regions.len() {
        let r = regions.get(i);
        if r.id() == needle {
            return Some(r);
        }
    }
    None
}

/// Polygon outline — walk `outline.vertices`, build a filled path.
fn draw_polygon(
    outline: &crate::ir::Outline<'_>,
    style: FloorStyle,
    ctx: &mut RasterCtx<'_>,
) {
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 3 => v,
        _ => return,
    };
    let mut pb = PathBuilder::new();
    let mut iter = verts.iter();
    if let Some(v0) = iter.next() {
        pb.move_to(v0.x(), v0.y());
    }
    for v in iter {
        pb.line_to(v.x(), v.y());
    }
    pb.close();
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = floor_paint(style);
    ctx.pixmap.fill_path(
        &path,
        &paint,
        FillRule::Winding,
        ctx.transform,
        None,
    );
}

/// Circle descriptor — tiny-skia `push_oval`.
fn draw_circle(
    outline: &crate::ir::Outline<'_>,
    style: FloorStyle,
    ctx: &mut RasterCtx<'_>,
) {
    let cx = outline.cx();
    let cy = outline.cy();
    let r = outline.rx();
    if r <= 0.0 {
        return;
    }
    let rect = match Rect::from_xywh(cx - r, cy - r, r * 2.0, r * 2.0) {
        Some(rect) => rect,
        None => return,
    };
    let mut pb = PathBuilder::new();
    pb.push_oval(rect);
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = floor_paint(style);
    ctx.pixmap.fill_path(
        &path,
        &paint,
        FillRule::Winding,
        ctx.transform,
        None,
    );
}

/// Pill descriptor — SVG-equivalent `<rect rx ry>` rounded rect.
///
/// Mirrors the Python consumer which emits:
/// `<rect x=… y=… width=… height=… rx=min(rx,ry) ry=min(rx,ry)>`.
/// SVG rounded-rect corners are quarter-ellipses with radii
/// `(corner, corner)`; we approximate each quarter with a single
/// cubic Bézier using the standard kappa ≈ 0.5523 constant for
/// a circular quarter arc.
fn draw_pill(
    outline: &crate::ir::Outline<'_>,
    style: FloorStyle,
    ctx: &mut RasterCtx<'_>,
) {
    let cx = outline.cx();
    let cy = outline.cy();
    let rx = outline.rx();
    let ry = outline.ry();
    if rx <= 0.0 || ry <= 0.0 {
        return;
    }
    // SVG uses `rx = ry = min(rx, ry)` for the pill corner radius.
    let r = rx.min(ry);
    let x0 = cx - rx;
    let y0 = cy - ry;
    let x1 = cx + rx;
    let y1 = cy + ry;
    // Cubic Bézier kappa for a quarter-circle arc.
    const KAPPA: f32 = 0.5523;
    let k = r * KAPPA;
    let mut pb = PathBuilder::new();
    // Start at top-left corner, moving right along the top edge.
    pb.move_to(x0 + r, y0);
    pb.line_to(x1 - r, y0); // top edge
    pb.cubic_to(x1 - r + k, y0, x1, y0 + r - k, x1, y0 + r); // top-right
    pb.line_to(x1, y1 - r); // right edge
    pb.cubic_to(x1, y1 - r + k, x1 - r + k, y1, x1 - r, y1); // bottom-right
    pb.line_to(x0 + r, y1); // bottom edge
    pb.cubic_to(x0 + r - k, y1, x0, y1 - r + k, x0, y1 - r); // bottom-left
    pb.line_to(x0, y0 + r); // left edge
    pb.cubic_to(x0, y0 + r - k, x0 + r - k, y0, x0 + r, y0); // top-left
    pb.close();
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    let paint = floor_paint(style);
    ctx.pixmap.fill_path(
        &path,
        &paint,
        FillRule::Winding,
        ctx.transform,
        None,
    );
}

/// CaveFloor — Phase 1.18 real consumer: runs the cave geometry
/// pipeline from `FloorOp.outline.vertices`.
///
/// Replaces the Phase 1.17 provisional bridge that read the legacy
/// `WallsAndFloorsOp.cave_region` SVG-path string. The pipeline
/// mirrors `_cave_path_from_outline` from `ir_to_svg.py`:
///   `Polygon(vertices) → buffer(0.3*CELL) → simplify → orient CCW
///   → densify(0.8*CELL) → jitter_ring_outward(seed + 0x5A17E5)
///   → smooth_closed_path`
///
/// Phase 1.19 (stop legacy emit) is now unblocked for cave geometry.
fn draw_cave_floor(
    outline: &crate::ir::Outline<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 4 => v,
        _ => return,
    };
    let coords: Vec<(f64, f64)> = verts
        .iter()
        .map(|v| (v.x() as f64, v.y() as f64))
        .collect();

    let path_svg = cave_path_from_outline(&coords, fir.base_seed());
    let d = match extract_d_from_path(path_svg.as_str()) {
        Some(d) if !d.is_empty() => d,
        _ => return,
    };
    let path = match parse_path_d(d) {
        Some(p) => p,
        None => return,
    };
    let paint = cave_floor_paint();
    ctx.pixmap.fill_path(
        &path,
        &paint,
        FillRule::EvenOdd,
        ctx.transform,
        None,
    );
}

/// Select the fill paint by `FloorStyle`.
fn floor_paint(style: FloorStyle) -> Paint<'static> {
    match style {
        FloorStyle::CaveFloor => cave_floor_paint(),
        FloorStyle::WoodFloor => wood_floor_paint(),
        _ => dungeon_floor_paint(),
    }
}

/// `<path d="..."/>` → the inner d= string.
///
/// Mirrors the helper in `walls_and_floors.rs` — kept local to
/// avoid coupling the two modules.
fn extract_d_from_path(s: &str) -> Option<&str> {
    let needle = "d=\"";
    let start = s.find(needle)? + needle.len();
    let rest = &s[start..];
    let end = rest.find('"')?;
    Some(&rest[..end])
}

#[cfg(test)]
mod tests {
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, FloorIRArgs, FloorOp, FloorOpArgs,
        FloorStyle, FloorIR, Op, OpEntry, OpEntryArgs, Outline,
        OutlineArgs, OutlineKind, RectRoom, RectRoomArgs, Vec2,
        WallsAndFloorsOp, WallsAndFloorsOpArgs,
    };
    use crate::test_util::{decode, pixel_at};
    use crate::transform::png::{floor_ir_to_png, BG_B, BG_G, BG_R};

    const FLOOR_R: u8 = 0xFF;
    const FLOOR_G: u8 = 0xFF;
    const FLOOR_B: u8 = 0xFF;
    const CAVE_FLOOR_R: u8 = 0xF5;
    const CAVE_FLOOR_G: u8 = 0xEB;
    const CAVE_FLOOR_B: u8 = 0xD8;
    // Phase 1.20b — wood-floor brown (#B58B5A); mirrors Python's
    // `_floor_detail.WOOD_FLOOR_FILL`.
    const WOOD_FLOOR_R: u8 = 0xB5;
    const WOOD_FLOOR_G: u8 = 0x8B;
    const WOOD_FLOOR_B: u8 = 0x5A;

    /// Canvas coords for the centre of tile (tx, ty).
    /// `padding = 32`, `cell = 32`.
    fn tile_centre_px(tx: u32, ty: u32) -> (u32, u32) {
        let pad = 32_u32;
        let cell = 32_u32;
        (pad + tx * cell + cell / 2, pad + ty * cell + cell / 2)
    }

    /// Build an IR with one polygon FloorOp (rect bounding box in tile
    /// coords). Canvas is 8×8 tiles, padding=32, cell=32.
    fn build_rect_floor_op_buf(
        tile_x: i32,
        tile_y: i32,
        tile_w: i32,
        tile_h: i32,
        style: FloorStyle,
    ) -> Vec<u8> {
        let cell = 32.0_f32;
        let px0 = tile_x as f32 * cell;
        let py0 = tile_y as f32 * cell;
        let px1 = (tile_x + tile_w) as f32 * cell;
        let py1 = (tile_y + tile_h) as f32 * cell;

        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&[
            Vec2::new(px0, py0),
            Vec2::new(px1, py0),
            Vec2::new(px1, py1),
            Vec2::new(px0, py1),
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
        let floor_op = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(outline),
                style,
                region_ref: None,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(floor_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// Build an IR with one Circle FloorOp.
    ///
    /// `cx` and `cy` are in *canvas* pixel coords (include padding).
    fn build_circle_floor_op_buf(
        cx: f32,
        cy: f32,
        r: f32,
        style: FloorStyle,
    ) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                descriptor_kind: OutlineKind::Circle,
                cx,
                cy,
                rx: r,
                ry: r,
                closed: true,
                ..Default::default()
            },
        );
        let floor_op = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(outline),
                style,
                region_ref: None,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(floor_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// Build an IR with one Pill FloorOp.
    ///
    /// `cx` and `cy` are in *canvas* pixel coords (include padding).
    fn build_pill_floor_op_buf(
        cx: f32,
        cy: f32,
        rx: f32,
        ry: f32,
        style: FloorStyle,
    ) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                descriptor_kind: OutlineKind::Pill,
                cx,
                cy,
                rx,
                ry,
                closed: true,
                ..Default::default()
            },
        );
        let floor_op = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(outline),
                style,
                region_ref: None,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(floor_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// Build an IR with an octagon-shaped (8-vertex polygon)
    /// DungeonFloor FloorOp.
    fn build_octagon_floor_op_buf() -> Vec<u8> {
        let cell = 32.0_f32;
        // Octagon centred at tile (4,4) in pixel space.
        // These coords are in *tile* space (no padding) because
        // the `transform` in `floor_ir_to_png` adds the padding.
        let cx = 4.0 * cell + cell / 2.0;
        let cy = 4.0 * cell + cell / 2.0;
        let r = 1.5 * cell;
        let s = r * std::f32::consts::FRAC_1_SQRT_2;
        let verts_data = [
            Vec2::new(cx + r, cy),
            Vec2::new(cx + s, cy + s),
            Vec2::new(cx, cy + r),
            Vec2::new(cx - s, cy + s),
            Vec2::new(cx - r, cy),
            Vec2::new(cx - s, cy - s),
            Vec2::new(cx, cy - r),
            Vec2::new(cx + s, cy - s),
        ];
        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&verts_data);
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let floor_op = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(outline),
                style: FloorStyle::DungeonFloor,
                region_ref: None,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(floor_op.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// Build an IR with a CaveFloor FloorOp whose `outline.vertices`
    /// hold a 6×6-tile square (raw tile-boundary ring).
    ///
    /// Phase 1.18: `draw_cave_floor` now runs the real cave geometry
    /// pipeline (buffer+jitter+smooth) from `outline.vertices` rather
    /// than the provisional bridge that read the legacy `cave_region`
    /// string. No `WallsAndFloorsOp` is needed.
    fn build_cave_floor_op_buf() -> Vec<u8> {
        let cell = 32.0_f32;
        // Tile-space square [2,2]..[6,6] — raw tile-boundary ring.
        // The pipeline will buffer outward by 0.3*CELL, simplify, and
        // jitter before filling with cave-floor colour.
        let x0 = 2.0 * cell;
        let y0 = 2.0 * cell;
        let x1 = 6.0 * cell;
        let y1 = 6.0 * cell;

        let mut fbb = FlatBufferBuilder::new();

        // FloorOp: CaveFloor polygon outline (raw tile ring, no WallsAndFloorsOp).
        let cave_verts = fbb.create_vector(&[
            Vec2::new(x0, y0),
            Vec2::new(x1, y0),
            Vec2::new(x1, y1),
            Vec2::new(x0, y1),
        ]);
        let cave_outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(cave_verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let cave_floor_op = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(cave_outline),
                style: FloorStyle::CaveFloor,
                region_ref: None,
            },
        );
        let cave_floor_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(cave_floor_op.as_union_value()),
            },
        );

        let ops = fbb.create_vector(&[cave_floor_entry]);
        let theme = fbb.create_string("cave");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 10,
                height_tiles: 10,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                base_seed: 42,
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// Build an IR with a WallsAndFloorsOp carrying `rect_rooms` and
    /// NO FloorOps — simulates a legacy 3.x cache buffer.
    fn build_legacy_rect_rooms_buf(
        tile_x: i32,
        tile_y: i32,
        tile_w: i32,
        tile_h: i32,
    ) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let room = RectRoom::create(
            &mut fbb,
            &RectRoomArgs {
                x: tile_x,
                y: tile_y,
                w: tile_w,
                h: tile_h,
                ..Default::default()
            },
        );
        let rooms = fbb.create_vector(&[room]);
        let waf = WallsAndFloorsOp::create(
            &mut fbb,
            &WallsAndFloorsOpArgs {
                rect_rooms: Some(rooms),
                ..Default::default()
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::WallsAndFloorsOp,
                op: Some(waf.as_union_value()),
            },
        );
        let ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    // ── Rect polygon DungeonFloor fill ──────────────────────────

    #[test]
    fn floor_op_polygon_dungeon_floor_paints_white() {
        // FloorOp covering tiles [1,1]..[4,4] — centre at tile (2,2).
        let buf =
            build_rect_floor_op_buf(1, 1, 3, 3, FloorStyle::DungeonFloor);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        let (px, py) = tile_centre_px(2, 2);
        let (r, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (r, g, b),
            (FLOOR_R, FLOOR_G, FLOOR_B),
            "pixel ({px},{py}) inside FloorOp rect should be white floor"
        );
    }

    // ── Phase 1.20b — WoodFloor polygon paints brown ────────────

    #[test]
    fn floor_op_polygon_wood_floor_paints_brown() {
        // FloorOp covering tiles [1,1]..[4,4] — centre at tile (2,2).
        // WoodFloor must select the WOOD_FLOOR_FILL paint (#B58B5A),
        // not the white DungeonFloor paint that the legacy
        // smoothFillSvg path leaked when the Rust gate suppressed it.
        let buf =
            build_rect_floor_op_buf(1, 1, 3, 3, FloorStyle::WoodFloor);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        let (px, py) = tile_centre_px(2, 2);
        let (r, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (r, g, b),
            (WOOD_FLOOR_R, WOOD_FLOOR_G, WOOD_FLOOR_B),
            "pixel ({px},{py}) inside WoodFloor FloorOp should be brown"
        );
    }

    // ── Octagon (smooth polygon) DungeonFloor fill ──────────────

    #[test]
    fn floor_op_polygon_octagon_paints_white_at_centre() {
        let buf = build_octagon_floor_op_buf();
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // Centre of the octagon is at tile (4,4).
        let (px, py) = tile_centre_px(4, 4);
        let (r, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (r, g, b),
            (FLOOR_R, FLOOR_G, FLOOR_B),
            "pixel ({px},{py}) inside octagon FloorOp should be white"
        );
    }

    // ── Circle DungeonFloor fill ────────────────────────────────

    #[test]
    fn floor_op_circle_dungeon_floor_paints_white() {
        // Circle in *tile-pixel* space (no padding — transform adds it).
        // Centred at tile (4,4) centre.
        let cell = 32.0_f32;
        let pad = 32_u32;
        let cx = 4.0 * cell + cell / 2.0;
        let cy = 4.0 * cell + cell / 2.0;
        let r = 1.5 * cell;
        let buf = build_circle_floor_op_buf(cx, cy, r, FloorStyle::DungeonFloor);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // Canvas pixel: padding + tile-pixel-centre.
        let (px, py) = tile_centre_px(4, 4);
        // The `pad` binding is used via `tile_centre_px` which adds 32px.
        let _ = pad;
        let (red, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (red, g, b),
            (FLOOR_R, FLOOR_G, FLOOR_B),
            "pixel ({px},{py}) inside Circle FloorOp should be white"
        );
    }

    // ── Pill DungeonFloor fill ──────────────────────────────────

    #[test]
    fn floor_op_pill_dungeon_floor_paints_white() {
        // Pill in *tile-pixel* space (no padding — transform adds it).
        // Centred at tile (4,4) centre.
        let cell = 32.0_f32;
        let cx = 4.0 * cell + cell / 2.0;
        let cy = 4.0 * cell + cell / 2.0;
        let rx = 1.25 * cell;
        let ry = 0.75 * cell;
        let buf =
            build_pill_floor_op_buf(cx, cy, rx, ry, FloorStyle::DungeonFloor);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        let (px, py) = tile_centre_px(4, 4);
        let (red, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (red, g, b),
            (FLOOR_R, FLOOR_G, FLOOR_B),
            "pixel ({px},{py}) inside Pill FloorOp should be white"
        );
    }

    // ── CaveFloor FloorOp fill (via cave geometry pipeline) ────────

    /// Phase 1.18: CaveFloor FloorOp fill is painted via the real
    /// cave geometry pipeline (buffer+jitter+smooth) reading
    /// `FloorOp.outline.vertices`. The pipeline expands outward by
    /// ~0.3*CELL + jitter, so the tile-centre of the original [2,2]
    /// to [6,6] region remains inside the filled area.
    #[test]
    fn cave_floor_consumes_outline_vertices_via_pipeline() {
        let buf = build_cave_floor_op_buf();
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // Centre of the cave region at tile (4,4). The pipeline expands
        // outward so the centre is well inside the filled cave area.
        let (px, py) = tile_centre_px(4, 4);
        let (r, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (r, g, b),
            (CAVE_FLOOR_R, CAVE_FLOOR_G, CAVE_FLOOR_B),
            "pixel ({px},{py}) inside CaveFloor FloorOp should be \
             cave-floor colour (#F5EBD8) after pipeline"
        );
    }

    // ── Legacy fallback: WallsAndFloorsOp without FloorOps ─────

    #[test]
    fn legacy_rect_rooms_still_render_without_floor_ops() {
        // An IR with ONLY WallsAndFloorsOp.rect_rooms (no FloorOps)
        // must still paint white floor via the legacy path in
        // `walls_and_floors.rs`. Regression guard for the gate logic.
        let buf = build_legacy_rect_rooms_buf(1, 1, 4, 4);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        let (px, py) = tile_centre_px(3, 3);
        let (r, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (r, g, b),
            (FLOOR_R, FLOOR_G, FLOOR_B),
            "pixel ({px},{py}) should be white via legacy rect_rooms \
             (no FloorOps in IR)"
        );
    }

    // ── Background outside FloorOp area stays parchment ─────────

    #[test]
    fn floor_op_does_not_paint_outside_outline() {
        // Tile (0,0) centre is outside the [1,1]..[4,4] FloorOp.
        let buf =
            build_rect_floor_op_buf(1, 1, 3, 3, FloorStyle::DungeonFloor);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        let (px, py) = tile_centre_px(0, 0);
        let (r, g, b) = pixel_at(&pixmap, px, py);
        assert_eq!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "pixel ({px},{py}) outside FloorOp should remain parchment BG"
        );
    }

    // ── extract_d_from_path helper ───────────────────────────────

    #[test]
    fn extract_d_pulls_attribute() {
        use super::extract_d_from_path;
        let s = "<path d=\"M0,0 L10,10 Z\"/>";
        assert_eq!(extract_d_from_path(s), Some("M0,0 L10,10 Z"));
    }
}
