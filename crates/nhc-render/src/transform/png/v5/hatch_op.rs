//! V5HatchOp consumer — hatched outer band.
//!
//! Phase 3.1 follow-on of `plans/nhc_pure_ir_v5_migration_plan.md`.
//! Lifts ``primitives::hatch::paint_hatch_corridor`` /
//! ``paint_hatch_room`` (the v4 HatchOp painters) into the v5
//! dispatcher. The v5 anti-geometry convention puts the hatched
//! region in ``region_ref`` and any subtractions in
//! ``subtract_region_refs[]``; this commit's painter consumes
//! ``tiles`` / ``is_outer`` / ``seed`` directly and ignores the
//! region / subtraction strings (the painter doesn't currently
//! intersect with region geometry — the v4 reference doesn't
//! either; the tile list is pre-filtered at emit time).
//!
//! The HatchKind dispatch matches v4: Corridor → corridor painter;
//! Room → room painter. HatchKind::Hole carries the same shape as
//! Room and would dispatch through the same painter once the
//! region-anti-geometry plumbing in this handler matures.

use flatbuffers::{ForwardsUOffset, Vector};

use crate::ir::{HatchKind, V5HatchOp, V5Region};
use crate::painter::Painter;
use crate::primitives::hatch::{paint_hatch_corridor, paint_hatch_room};

pub fn draw<'a>(
    op: V5HatchOp<'a>,
    _regions: Vector<'a, ForwardsUOffset<V5Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let tiles: Vec<(i32, i32)> = match op.tiles() {
        Some(t) => t.iter().map(|c| (c.x(), c.y())).collect(),
        None => return false,
    };
    if tiles.is_empty() {
        return false;
    }
    match op.kind() {
        HatchKind::Corridor => {
            paint_hatch_corridor(painter, &tiles, op.seed());
            true
        }
        HatchKind::Room | HatchKind::Hole => {
            let is_outer: Vec<bool> = op
                .is_outer()
                .map(|v| v.iter().collect())
                .unwrap_or_else(|| vec![false; tiles.len()]);
            paint_hatch_room(painter, &tiles, &is_outer, op.seed());
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
        HatchKind, TileCoord, V5HatchOp as FbV5HatchOp, V5HatchOpArgs,
        V5OpEntry, V5OpEntryArgs, V5Op, V5Region as FbV5Region,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_hatch_op(kind: HatchKind, n_tiles: usize) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let tiles_vec: Vec<TileCoord> = (0..n_tiles)
            .map(|i| TileCoord::new(i as i32, 0))
            .collect();
        let tiles = fbb.create_vector(&tiles_vec);
        let is_outer: Vec<bool> = vec![false; n_tiles];
        let is_outer_v = fbb.create_vector(&is_outer);
        let region_ref = fbb.create_string("dungeon");
        let underlay = fbb.create_string("#000000");
        let hatch_op = FbV5HatchOp::create(
            &mut fbb,
            &V5HatchOpArgs {
                kind,
                region_ref: Some(region_ref),
                subtract_region_refs: None,
                tiles: Some(tiles),
                is_outer: Some(is_outer_v),
                extent_tiles: 2.0,
                seed: 0xFACE,
                hatch_underlay_color: Some(underlay),
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5HatchOp,
                op: Some(hatch_op.as_union_value()),
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

    fn run(buf: &[u8]) -> MockPainter {
        let fir = root_as_floor_ir(buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_hatch_op()
            .expect("hatch op");
        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        painter
    }

    /// Corridor hatch routes to ``paint_hatch_corridor``. The lifted
    /// painter emits multi-call output (per-tile fills + strokes
    /// inside group envelopes); pin the dispatcher reaches it.
    #[test]
    fn corridor_kind_routes_to_paint_hatch_corridor() {
        let painter = run(&build_hatch_op(HatchKind::Corridor, 4));
        assert!(painter.calls.len() > 1);
    }

    /// Room hatch routes to ``paint_hatch_room``.
    #[test]
    fn room_kind_routes_to_paint_hatch_room() {
        let painter = run(&build_hatch_op(HatchKind::Room, 4));
        assert!(painter.calls.len() > 1);
    }

    /// Hole hatch routes through the same painter as Room (they
    /// share geometry; the difference is at emit time).
    #[test]
    fn hole_kind_routes_to_paint_hatch_room() {
        let painter = run(&build_hatch_op(HatchKind::Hole, 4));
        assert!(painter.calls.len() > 1);
    }

    /// Empty tile list short-circuits without touching the painter.
    #[test]
    fn empty_tile_list_skips_painting() {
        let buf = build_hatch_op(HatchKind::Corridor, 0);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_hatch_op()
            .expect("hatch op");
        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());

        // Match-arm marker so the unused PainterCall import doesn't
        // fall out of cfg(test).
        let _: Option<PainterCall> = None;
    }
}
