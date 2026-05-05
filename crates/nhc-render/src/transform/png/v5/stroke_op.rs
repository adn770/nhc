//! V5StrokeOp consumer — wall stroke along outline.
//!
//! Phase 1.3 ships the dispatch shape: read geometry from
//! `region_ref` (→ Region.outline) or from `op.outline` (interior
//! partitions, free-standing walls). Dispatch on
//! `wall_material.treatment` (PlainStroke / Masonry / Partition /
//! Palisade / Fortification).
//!
//! Phase 2.8 lifts today's per-treatment painters (Masonry,
//! Palisade, Fortification — already implemented in v4e) into the
//! v5 dispatcher. PlainStroke and Partition are new for v5.

use flatbuffers::{ForwardsUOffset, Vector};

use super::region_path::outline_to_path;
use crate::ir::{V5Region, V5StrokeOp, V5WallTreatment};
use crate::painter::{Color, Paint, Painter, Stroke};

/// Sentinel placeholder colour per WallTreatment. Phase 2.8
/// replaces these with substance-aware palettes (the wall's
/// MaterialFamily / style picks the colour; the treatment picks
/// the drawing algorithm).
fn stub_paint(treatment: V5WallTreatment) -> Paint {
    Paint::solid(match treatment {
        V5WallTreatment::PlainStroke => Color::rgba(0x18, 0x12, 0x0E, 1.0),
        V5WallTreatment::Masonry => Color::rgba(0x40, 0x38, 0x2C, 1.0),
        V5WallTreatment::Partition => Color::rgba(0x60, 0x4A, 0x32, 1.0),
        V5WallTreatment::Palisade => Color::rgba(0x55, 0x3B, 0x22, 1.0),
        V5WallTreatment::Fortification => Color::rgba(0x12, 0x10, 0x10, 1.0),
        _ => Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    })
}

const STUB_STROKE_WIDTH: f32 = 2.0;

pub fn draw<'a>(
    op: V5StrokeOp<'a>,
    regions: Vector<'a, ForwardsUOffset<V5Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let outline = if let Some(o) = op.outline() {
        Some(o)
    } else if let Some(rr) = op.region_ref() {
        if rr.is_empty() {
            None
        } else {
            super::find_v5_region(regions, rr).and_then(|r| r.outline())
        }
    } else {
        None
    };
    let outline = match outline {
        Some(o) => o,
        None => return false,
    };
    let (path, _multi) = match outline_to_path(&outline) {
        Some(p) => p,
        None => return false,
    };
    let wm = match op.wall_material() {
        Some(m) => m,
        None => return false,
    };
    let paint = stub_paint(wm.treatment());
    let stroke = Stroke::solid(STUB_STROKE_WIDTH);
    painter.stroke_path(&path, &paint, &stroke);
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, CornerStyle, FloorIR,
        FloorIRArgs, Outline, OutlineArgs, OutlineKind, V5MaterialFamily,
        V5OpEntry, V5OpEntryArgs, V5Op, V5Region as FbV5Region, V5RegionArgs,
        V5StrokeOp as FbV5StrokeOp, V5StrokeOpArgs, V5WallMaterial,
        V5WallMaterialArgs, V5WallTreatment, Vec2 as FbVec2,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_stroke_op_with_region(treatment: V5WallTreatment) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let verts = fbb.create_vector(&[
            FbVec2::new(0.0, 0.0),
            FbVec2::new(64.0, 0.0),
            FbVec2::new(64.0, 64.0),
            FbVec2::new(0.0, 64.0),
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
                ..Default::default()
            },
        );
        let v5_regions = fbb.create_vector(&[region]);
        let region_ref = fbb.create_string("room.0");
        let wall_material = V5WallMaterial::create(
            &mut fbb,
            &V5WallMaterialArgs {
                family: V5MaterialFamily::Stone,
                style: 0,
                treatment,
                corner_style: CornerStyle::Merlon,
                tone: 0,
                seed: 0xC0FFEE,
            },
        );
        let stroke_op = FbV5StrokeOp::create(
            &mut fbb,
            &V5StrokeOpArgs {
                region_ref: Some(region_ref),
                outline: None,
                wall_material: Some(wall_material),
                cuts: None,
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5StrokeOp,
                op: Some(stroke_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 8,
                height_tiles: 8,
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
    fn draw_strokes_region_outline_with_treatment_paint() {
        let buf = build_stroke_op_with_region(V5WallTreatment::Masonry);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_stroke_op()
            .expect("stroke op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        assert_eq!(painter.calls.len(), 1);
        match &painter.calls[0] {
            PainterCall::StrokePath(_, paint, stroke) => {
                assert_eq!(stroke.width, 2.0);
                // Masonry stub paint = #40382C
                assert_eq!(paint.color.r, 0x40);
                assert_eq!(paint.color.g, 0x38);
                assert_eq!(paint.color.b, 0x2C);
            }
            other => panic!("expected StrokePath, got {other:?}"),
        }
    }

    #[test]
    fn draw_picks_distinct_paint_per_treatment() {
        let mut seen = Vec::new();
        for treatment in [
            V5WallTreatment::PlainStroke,
            V5WallTreatment::Masonry,
            V5WallTreatment::Partition,
            V5WallTreatment::Palisade,
            V5WallTreatment::Fortification,
        ] {
            let buf = build_stroke_op_with_region(treatment);
            let fir = root_as_floor_ir(&buf).expect("parse");
            let regions = fir.v5_regions().expect("v5_regions");
            let op = fir
                .v5_ops()
                .expect("v5_ops")
                .get(0)
                .op_as_v5_stroke_op()
                .expect("stroke op");
            let mut painter = MockPainter::default();
            assert!(draw(op, regions, &mut painter));
            match &painter.calls[0] {
                PainterCall::StrokePath(_, paint, _) => {
                    let key = (paint.color.r, paint.color.g, paint.color.b);
                    assert!(
                        !seen.contains(&key),
                        "treatment {treatment:?} reuses earlier palette"
                    );
                    seen.push(key);
                }
                other => panic!("expected StrokePath, got {other:?}"),
            }
        }
    }
}
