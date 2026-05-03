//! InteriorWallOp rasterisation — Phase 1.18 of
//! `plans/nhc_pure_ir_plan.md`, ported to the Painter trait in
//! Phase 2.15c.
//!
//! Reads `InteriorWallOp.outline` + `InteriorWallOp.style` from the
//! IR and strokes a line between each consecutive vertex pair.
//!
//! Supported styles:
//! - `PartitionStone` (4): stone partition color `#6E6E6E`.
//! - `PartitionBrick` (5): brick partition color `#9E5040`.
//! - `PartitionWood`  (6): wood partition color `#8B5E3C`.
//! - `DungeonInk`    (0): alias for stone color (matches Python's
//!   `_STYLE_TO_MATERIAL` mapping: DungeonInk → 0 → stone).
//!
//! Stroke width is `CELL * 0.25 = 8.0px`, linecap `Round`.
//! Mirrors `_draw_interior_wall_op_from_ir` in `ir_to_svg.py`.
//!
//! Interior walls are open polylines with NO clip envelope — they
//! are not region perimeters, so the handler simply constructs a
//! `SkiaPainter::with_transform` over the active pixmap and emits
//! one `stroke_path` call. First of the four v4-op handler ports
//! (interior_wall_op, corridor_wall_op, exterior_wall_op,
//! floor_op) required for Phase 2.16 (transform/svg/) to share
//! dispatch via the Painter trait.

use crate::ir::{FloorIR, OpEntry, WallStyle};
use crate::painter::{
    Color, LineCap, Paint, Painter, PathOps, SkiaPainter, Stroke, Vec2,
};

use super::RasterCtx;

// Interior wall stroke width: CELL * 0.25.
// CELL = 32 px → 8.0 px.
const INTERIOR_WALL_WIDTH: f32 = 8.0;

// Partition material colors — match `_INTERIOR_WALL_COLORS` in
// `nhc/rendering/ir_to_svg.py`.
const STONE_RGB: (u8, u8, u8) = (0x6E, 0x6E, 0x6E);
const BRICK_RGB: (u8, u8, u8) = (0x9E, 0x50, 0x40);
const WOOD_RGB: (u8, u8, u8) = (0x8B, 0x5E, 0x3C);

fn interior_wall_paint(style: WallStyle) -> Paint {
    let (r, g, b) = match style {
        WallStyle::PartitionBrick => BRICK_RGB,
        WallStyle::PartitionWood => WOOD_RGB,
        _ => STONE_RGB, // PartitionStone + DungeonInk + fallback
    };
    Paint::solid(Color::rgba(r, g, b, 1.0))
}

fn interior_wall_stroke() -> Stroke {
    Stroke {
        width: INTERIOR_WALL_WIDTH,
        line_cap: LineCap::Round,
        ..Stroke::default()
    }
}

/// `OpHandler` dispatch entry — registered against `Op::InteriorWallOp`
/// in `super::op_handlers`.
pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_interior_wall_op() {
        Some(o) => o,
        None => return,
    };
    let outline = match op.outline() {
        Some(o) => o,
        None => return,
    };
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 2 => v,
        _ => return,
    };

    let style = op.style();
    let paint = interior_wall_paint(style);
    let stroke = interior_wall_stroke();

    let mut path = PathOps::new();
    let mut first = true;
    for v in verts.iter() {
        let p = Vec2::new(v.x(), v.y());
        if first {
            path.move_to(p);
            first = false;
        } else {
            path.line_to(p);
        }
    }
    if path.is_empty() {
        return;
    }
    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);
    painter.stroke_path(&path, &paint, &stroke);
}

#[cfg(test)]
mod tests {
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, FloorIR, FloorIRArgs, InteriorWallOp,
        InteriorWallOpArgs, Op, OpEntry, OpEntryArgs, Outline, OutlineArgs,
        OutlineKind, Vec2, WallStyle,
    };
    use crate::test_util::{decode, pixel_at};
    use crate::transform::png::{floor_ir_to_png, BG_B, BG_G, BG_R};

    /// Build an IR with a single InteriorWallOp (2-vertex open polyline).
    fn build_interior_wall_op_buf(
        x0: f32, y0: f32, x1: f32, y1: f32,
        style: WallStyle,
    ) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&[
            Vec2::new(x0, y0),
            Vec2::new(x1, y1),
        ]);
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(verts),
                closed: false,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let wall_op = InteriorWallOp::create(
            &mut fbb,
            &InteriorWallOpArgs {
                outline: Some(outline),
                style,
                cuts: None,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::InteriorWallOp,
                op: Some(wall_op.as_union_value()),
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

    /// A horizontal interior wall paints something other than the
    /// background along its path. PartitionStone uses grey (#6E6E6E).
    #[test]
    fn wall_op_paints_full_outline_when_no_cuts_interior_stone() {
        // Wall from (1*32, 4*32) to (6*32, 4*32) — horizontal line in
        // tile-pixel space; transform adds padding=32.
        let cell = 32.0_f32;
        let buf = build_interior_wall_op_buf(
            1.0 * cell,
            4.0 * cell,
            6.0 * cell,
            4.0 * cell,
            WallStyle::PartitionStone,
        );
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // Sample a pixel near the midpoint of the wall. The stroke is 8 px
        // wide and anti-aliased, so the centre should be solidly coloured.
        // Canvas pixel: padding=32, tile (3, 4) centre y = 32 + 4*32 = 160.
        // x midpoint ≈ 32 + 3.5*32 = 144.
        let (r, g, b) = pixel_at(&pixmap, 144, 32 + 4 * 32);
        assert_ne!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "interior wall stroke should paint over background at (144,160)"
        );
        // Stone colour is #6E6E6E — not identical to BG (#F5EDE0).
        assert_eq!(r, g, "stone wall should be grey (r=g)");
    }

    #[test]
    fn wall_op_paints_full_outline_when_no_cuts_interior_brick() {
        let cell = 32.0_f32;
        let buf = build_interior_wall_op_buf(
            1.0 * cell,
            4.0 * cell,
            6.0 * cell,
            4.0 * cell,
            WallStyle::PartitionBrick,
        );
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        let (r, _g, _b) = pixel_at(&pixmap, 144, 32 + 4 * 32);
        assert_ne!(
            r,
            BG_R,
            "brick interior wall should paint over background"
        );
    }

    #[test]
    fn wall_op_paints_full_outline_when_no_cuts_interior_wood() {
        let cell = 32.0_f32;
        let buf = build_interior_wall_op_buf(
            1.0 * cell,
            4.0 * cell,
            6.0 * cell,
            4.0 * cell,
            WallStyle::PartitionWood,
        );
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        let (r, _g, _b) = pixel_at(&pixmap, 144, 32 + 4 * 32);
        assert_ne!(
            r,
            BG_R,
            "wood interior wall should paint over background"
        );
    }

    /// Far from the wall line, pixels remain background colour.
    #[test]
    fn interior_wall_does_not_paint_outside_line() {
        let cell = 32.0_f32;
        // Horizontal wall at y=4*32 in tile space.
        let buf = build_interior_wall_op_buf(
            1.0 * cell,
            4.0 * cell,
            6.0 * cell,
            4.0 * cell,
            WallStyle::PartitionStone,
        );
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);
        // Sample a pixel far above the wall — at tile (4, 1).
        // Canvas y = padding + 1*cell + cell/2 = 32 + 32 + 16 = 80.
        let (r, g, b) = pixel_at(&pixmap, 144, 80);
        assert_eq!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "pixel far from wall should remain parchment BG"
        );
    }

    /// Stroke width and linecap are the documented constants —
    /// pinned so a future refactor can't silently widen the wall.
    #[test]
    fn interior_wall_stroke_uses_documented_width_and_cap() {
        let s = super::interior_wall_stroke();
        assert_eq!(s.width, super::INTERIOR_WALL_WIDTH);
        assert_eq!(s.line_cap, crate::painter::LineCap::Round);
    }
}
