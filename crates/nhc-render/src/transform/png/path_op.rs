//! PathOp consumer — connected tile networks with style-driven
//! topology.
//!
//! Phase 2.10 of `plans/nhc_pure_ir_v5_migration_plan.md`. Lifts
//! the v4e CartTracks 4-neighbour topology painter (the L-corner /
//! T-junction dispatch shipped at d82c9900, lifted here from
//! `crates/nhc-render/src/primitives/cart_tracks.rs::paint_cart_tracks`)
//! and the OreVein contour painter
//! (`primitives/ore_deposit.rs::paint_ore_deposit`) into the v5
//! handler. The unordered tile list in `PathOp.tiles` is enough
//! for both pipelines: CartTracks derives the per-tile open-sides
//! 4-bit mask from the set, OreVein consumes the raw set.

use std::collections::HashSet;

use flatbuffers::{ForwardsUOffset, Vector};

use crate::ir::{PathOp, PathStyle, Region};
use crate::painter::Painter;
use crate::primitives::cart_tracks::{
    paint_cart_tracks, OPEN_E, OPEN_N, OPEN_S, OPEN_W,
};
use crate::primitives::ore_deposit::paint_ore_deposit;

/// Compute the 4-bit open-sides mask for each tile in `tiles`. Bit
/// `OPEN_N` is set when the tile's N neighbour is also in the set,
/// etc. Mirrors the v4 `_open_sides_for_tracks` helper that the
/// emitter used to fill `CartTracksVariant.open_sides[]`.
fn open_sides_for(tiles: &[(i32, i32)]) -> Vec<(i32, i32, u8)> {
    let set: HashSet<(i32, i32)> = tiles.iter().copied().collect();
    tiles
        .iter()
        .map(|&(x, y)| {
            let mut mask: u8 = 0;
            if set.contains(&(x, y - 1)) {
                mask |= OPEN_N;
            }
            if set.contains(&(x, y + 1)) {
                mask |= OPEN_S;
            }
            if set.contains(&(x + 1, y)) {
                mask |= OPEN_E;
            }
            if set.contains(&(x - 1, y)) {
                mask |= OPEN_W;
            }
            (x, y, mask)
        })
        .collect()
}

pub fn draw<'a>(
    op: PathOp<'a>,
    _regions: Vector<'a, ForwardsUOffset<Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let tiles = match op.tiles() {
        Some(t) if !t.is_empty() => t,
        _ => return false,
    };
    let coords: Vec<(i32, i32)> = (0..tiles.len())
        .map(|i| {
            let t = tiles.get(i);
            (t.x(), t.y())
        })
        .collect();
    let seed = op.seed();
    match op.style() {
        PathStyle::CartTracks => {
            let with_mask = open_sides_for(&coords);
            paint_cart_tracks(painter, &with_mask, seed);
            true
        }
        PathStyle::OreVein => {
            paint_ore_deposit(painter, &coords, seed);
            true
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs,
        TileCoord, OpEntry, OpEntryArgs, Op,
        PathOp as FbPathOp, PathOpArgs, PathStyle, Region as FbRegion,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_path_op(style: PathStyle, tiles: &[(i32, i32)]) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let tiles_vec: Vec<TileCoord> = tiles
            .iter()
            .map(|&(x, y)| TileCoord::new(x, y))
            .collect();
        let tiles_offset = fbb.create_vector(&tiles_vec);
        let region_ref = fbb.create_string("corridor.0");
        let path_op = FbPathOp::create(
            &mut fbb,
            &PathOpArgs {
                region_ref: Some(region_ref),
                tiles: Some(tiles_offset),
                style,
                seed: 0xFACE,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::PathOp,
                op: Some(path_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let v5_regions = fbb
            .create_vector::<flatbuffers::ForwardsUOffset<FbRegion>>(&[]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 16,
                height_tiles: 16,
                cell: 32,
                padding: 32,
                regions: Some(v5_regions),
                ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    fn run_draw(buf: &[u8]) -> MockPainter {
        let fir = root_as_floor_ir(buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_path_op()
            .expect("path op");
        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        painter
    }

    /// Three connected tiles `(0,5)-(1,5)-(2,5)` form a horizontal
    /// straight track segment. Cart-tracks paints rail strokes (in a
    /// group envelope) and tie strokes (in another group envelope).
    /// Pin that the lifted painter ran by asserting at least one
    /// `BeginGroup` + `StrokePolyline` + `EndGroup` triple.
    #[test]
    fn draw_runs_cart_tracks_painter_for_connected_tiles() {
        let tiles = [(0, 5), (1, 5), (2, 5)];
        let buf = build_path_op(PathStyle::CartTracks, &tiles);
        let painter = run_draw(&buf);
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::BeginGroup(_))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::StrokePolyline(_, _, _))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::EndGroup)));
    }

    /// OreVein paints diamonds (fill_path + stroke_path per diamond)
    /// inside one `BeginGroup` envelope. Pin that the lifted painter
    /// ran by checking for `FillPath` + `StrokePath` calls inside
    /// the group envelope.
    #[test]
    fn draw_runs_ore_vein_painter_for_tile_set() {
        let tiles = [(2, 4), (3, 4), (4, 4), (4, 5)];
        let buf = build_path_op(PathStyle::OreVein, &tiles);
        let painter = run_draw(&buf);
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::BeginGroup(_))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::FillPath(_, _, _))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::StrokePath(_, _, _))));
    }

    /// open_sides_for derives the 4-bit neighbour mask correctly
    /// from an unordered tile set. A 3-tile horizontal run `(0,5)-
    /// (1,5)-(2,5)` produces masks: left tile open-E only, middle
    /// open-E|W, right open-W only.
    #[test]
    fn open_sides_for_derives_neighbour_mask_from_tile_set() {
        let tiles = vec![(0, 5), (1, 5), (2, 5)];
        let with_mask = open_sides_for(&tiles);
        let lookup: std::collections::HashMap<(i32, i32), u8> = with_mask
            .iter()
            .map(|&(x, y, m)| ((x, y), m))
            .collect();
        assert_eq!(lookup[&(0, 5)], OPEN_E);
        assert_eq!(lookup[&(1, 5)], OPEN_E | OPEN_W);
        assert_eq!(lookup[&(2, 5)], OPEN_W);
    }

    #[test]
    fn draw_skips_empty_tile_list() {
        let buf = build_path_op(PathStyle::CartTracks, &[]);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_path_op()
            .expect("path op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }
}
