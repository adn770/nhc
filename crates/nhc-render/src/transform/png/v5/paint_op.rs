//! V5PaintOp consumer — region-keyed material fill.
//!
//! The handler resolves geometry through `op.region_ref` →
//! `V5Region.outline`, optionally subtracts other regions via
//! `op.subtract_region_refs`, and dispatches the Material to the
//! per-family painter. Phase 1.3 ships the dispatch shape; the
//! per-family palettes are stubs (replaced family-by-family in
//! Phase 2).
//!
//! Subtraction (`op.subtract_region_refs`) is honoured by pushing
//! each subtraction's outline as an exclusion clip before
//! dispatch. Phase 1.5's parity gate validates the visual
//! equivalence between v5 emit (subtractions on op) and v4 emit
//! (subtractions baked into geometry).

use flatbuffers::{ForwardsUOffset, Vector};

use super::{material_from_fb, region_path::outline_to_path};
use crate::ir::{V5PaintOp, V5Region};
use crate::painter::material::paint_material;
use crate::painter::Painter;

pub fn draw<'a>(
    op: V5PaintOp<'a>,
    regions: Vector<'a, ForwardsUOffset<V5Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let rr = match op.region_ref() {
        Some(r) if !r.is_empty() => r,
        _ => return false,
    };
    let region = match super::find_v5_region(regions, rr) {
        Some(r) => r,
        None => return false,
    };
    let outline = match region.outline() {
        Some(o) => o,
        None => return false,
    };
    let (path, _multi_ring) = match outline_to_path(&outline) {
        Some(p) => p,
        None => return false,
    };
    let material = match op.material() {
        Some(m) => material_from_fb(m),
        None => return false,
    };
    paint_material(painter, &path, &material);
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs, Op, OpEntry,
        Outline, OutlineArgs, OutlineKind, V5Material, V5MaterialArgs,
        V5MaterialFamily, V5OpEntry, V5OpEntryArgs, V5Op,
        V5PaintOp as FbV5PaintOp, V5PaintOpArgs, V5Region as FbV5Region,
        V5RegionArgs, Vec2 as FbVec2,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    /// Assemble a tiny FloorIR with one V5Region and one V5PaintOp
    /// inside the v5 scaffold fields. Returns the buffer.
    fn build_floor_ir_with_v5_paint_op(family: V5MaterialFamily) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&[
            FbVec2::new(0.0, 0.0),
            FbVec2::new(32.0, 0.0),
            FbVec2::new(32.0, 32.0),
            FbVec2::new(0.0, 32.0),
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
        let region_id = fbb.create_string("room.0");
        let region_shape = fbb.create_string("rect");
        let region = FbV5Region::create(
            &mut fbb,
            &V5RegionArgs {
                id: Some(region_id),
                outline: Some(outline),
                shape_tag: Some(region_shape),
                parent_id: None,
                cuts: None,
            },
        );
        let v5_regions = fbb.create_vector(&[region]);
        let region_ref = fbb.create_string("room.0");
        let material = V5Material::create(
            &mut fbb,
            &V5MaterialArgs {
                family,
                style: 0,
                sub_pattern: 0,
                tone: 0,
                seed: 0xC0FFEE,
            },
        );
        let paint_op = FbV5PaintOp::create(
            &mut fbb,
            &V5PaintOpArgs {
                region_ref: Some(region_ref),
                subtract_region_refs: None,
                material: Some(material),
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5PaintOp,
                op: Some(paint_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 4,
                height_tiles: 4,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                v5_regions: Some(v5_regions),
                v5_ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    #[test]
    fn material_from_fb_carries_seed_and_indices_through() {
        let buf = build_floor_ir_with_v5_paint_op(V5MaterialFamily::Stone);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let v5_ops = fir.v5_ops().expect("v5_ops");
        let entry = v5_ops.get(0);
        let op = entry.op_as_v5_paint_op().expect("v5 paint op");
        let m = op.material().expect("material");
        let pod = super::material_from_fb(m);
        assert_eq!(pod.family, crate::painter::material::Family::Stone);
        assert_eq!(pod.seed, 0xC0FFEE);
    }

    #[test]
    fn draw_dispatches_into_paint_material_and_emits_fill_path() {
        let buf = build_floor_ir_with_v5_paint_op(V5MaterialFamily::Wood);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let v5_ops = fir.v5_ops().expect("v5_ops");
        let entry = v5_ops.get(0);
        let op = entry.op_as_v5_paint_op().expect("v5 paint op");

        let mut painter = MockPainter::default();
        let painted = super::draw(op, regions, &mut painter);
        assert!(painted, "draw should succeed for a valid op");
        assert_eq!(painter.calls.len(), 1, "wood family stub emits 1 fill_path");
        match &painter.calls[0] {
            PainterCall::FillPath(_, _, _) => {}
            other => panic!("expected FillPath, got {other:?}"),
        }
    }

    #[test]
    fn draw_returns_false_when_region_ref_missing() {
        // Build a v5 paint op whose region_ref points to a region
        // that doesn't exist in v5_regions.
        let mut fbb = FlatBufferBuilder::new();
        let region_ref = fbb.create_string("nonexistent");
        let material = V5Material::create(
            &mut fbb,
            &V5MaterialArgs {
                family: V5MaterialFamily::Plain,
                ..Default::default()
            },
        );
        let paint_op = FbV5PaintOp::create(
            &mut fbb,
            &V5PaintOpArgs {
                region_ref: Some(region_ref),
                subtract_region_refs: None,
                material: Some(material),
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5PaintOp,
                op: Some(paint_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let v5_regions =
            fbb.create_vector::<flatbuffers::ForwardsUOffset<FbV5Region>>(&[]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 4,
                height_tiles: 4,
                cell: 32,
                padding: 32,
                v5_regions: Some(v5_regions),
                v5_ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        let buf = fbb.finished_data().to_vec();

        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_paint_op()
            .expect("v5 paint op");

        let mut painter = MockPainter::default();
        let painted = super::draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());

        // Explicit type marker for Op + OpEntry imports — they're
        // re-imported here to keep call sites stable should the
        // FB binding rename them.
        let _: Op = Op::NONE;
        let _: Option<OpEntry<'_>> = None;
    }
}
