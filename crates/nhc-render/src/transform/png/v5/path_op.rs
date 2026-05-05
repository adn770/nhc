//! V5PathOp consumer — connected tile networks with style-driven
//! topology.
//!
//! Phase 1.3 ships the dispatch shape: read the unordered tile
//! list, dispatch on `style` (CartTracks / OreVein) to a stub
//! painter. Phase 2.10 lifts today's CartTracks 4-neighbour
//! topology painter (already shipped at d82c9900 — the L-corner /
//! T-junction dispatch) and OreVein contour painter into the v5
//! handler.

use flatbuffers::{ForwardsUOffset, Vector};

use crate::ir::{V5PathOp, V5PathStyle, V5Region};
use crate::painter::{Color, FillRule, Paint, Painter, PathOps, Vec2};

const CART_TRACK_STUB_COLOR: Color = Color::rgba(0x6B, 0x4A, 0x2A, 0.45);
const ORE_VEIN_STUB_COLOR: Color = Color::rgba(0xC2, 0x9B, 0x3F, 0.55);

pub fn draw<'a>(
    op: V5PathOp<'a>,
    _regions: Vector<'a, ForwardsUOffset<V5Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let tiles = match op.tiles() {
        Some(t) if !t.is_empty() => t,
        _ => return false,
    };
    let color = match op.style() {
        V5PathStyle::CartTracks => CART_TRACK_STUB_COLOR,
        V5PathStyle::OreVein => ORE_VEIN_STUB_COLOR,
        _ => return false,
    };
    // Phase 1.3 stub: paint a small marker rectangle at each tile
    // centre. Phase 2.10 replaces this with the per-style topology
    // painter. The path constructed here is a simple per-tile box
    // — enough for the dispatcher contract test.
    let mut path = PathOps::new();
    let cell = 32.0;
    for i in 0..tiles.len() {
        let t = tiles.get(i);
        let x = t.x() as f32 * cell + cell * 0.25;
        let y = t.y() as f32 * cell + cell * 0.25;
        path.move_to(Vec2::new(x, y));
        path.line_to(Vec2::new(x + cell * 0.5, y));
        path.line_to(Vec2::new(x + cell * 0.5, y + cell * 0.5));
        path.line_to(Vec2::new(x, y + cell * 0.5));
        path.close();
    }
    let paint = Paint::solid(color);
    painter.fill_path(&path, &paint, FillRule::Winding);
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs,
        TileCoord, V5OpEntry, V5OpEntryArgs, V5Op,
        V5PathOp as FbV5PathOp, V5PathOpArgs, V5PathStyle, V5Region as FbV5Region,
    };
    use crate::painter::test_util::MockPainter;

    fn build_path_op(style: V5PathStyle, n_tiles: usize) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let tiles_vec: Vec<TileCoord> = (0..n_tiles)
            .map(|i| TileCoord::new(i as i32, 5))
            .collect();
        let tiles = fbb.create_vector(&tiles_vec);
        let region_ref = fbb.create_string("corridor.0");
        let path_op = FbV5PathOp::create(
            &mut fbb,
            &V5PathOpArgs {
                region_ref: Some(region_ref),
                tiles: Some(tiles),
                style,
                seed: 0xFACE,
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5PathOp,
                op: Some(path_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let v5_regions = fbb
            .create_vector::<flatbuffers::ForwardsUOffset<FbV5Region>>(&[]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 16,
                height_tiles: 16,
                cell: 32,
                padding: 32,
                v5_regions: Some(v5_regions),
                v5_ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    #[test]
    fn draw_dispatches_on_cart_tracks_style() {
        let buf = build_path_op(V5PathStyle::CartTracks, 3);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_path_op()
            .expect("path op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        assert_eq!(painter.calls.len(), 1, "stub paints one fill_path");
    }

    #[test]
    fn draw_skips_empty_tile_list() {
        let buf = build_path_op(V5PathStyle::CartTracks, 0);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_path_op()
            .expect("path op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }
}
