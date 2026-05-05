//! V5FixtureOp consumer — discrete decorative objects with anchors.
//!
//! Phase 1.3 ships the dispatch shape: walk anchors, dispatch on
//! `kind` to per-kind painter stubs. Phase 2.11 lifts the existing
//! per-fixture painters (TreeFeatureOp, BushFeatureOp,
//! WellFeatureOp, FountainFeatureOp, StairsOp) plus the
//! ThematicDetailOp scatter painters (Web, Skull, Bone,
//! LooseStone) and the new ones (Gravestone, Sign, Mushroom).
//!
//! Group_id fusion logic (Tree groves, Mushroom clusters,
//! Gravestone clusters) is shared across clustering kinds and
//! lands at Phase 2.11.

use flatbuffers::{ForwardsUOffset, Vector};

use crate::ir::{V5FixtureKind, V5FixtureOp, V5Region};
use crate::painter::{Color, Painter};

const FIXTURE_STUB_RADIUS: f32 = 6.0;

/// Sentinel placeholder colour for each fixture kind.
fn stub_color(kind: V5FixtureKind) -> Color {
    match kind {
        V5FixtureKind::Web => Color::rgba(0xE0, 0xE0, 0xE0, 0.55),
        V5FixtureKind::Skull => Color::rgba(0xF5, 0xEC, 0xC8, 1.0),
        V5FixtureKind::Bone => Color::rgba(0xE8, 0xDD, 0xB3, 1.0),
        V5FixtureKind::LooseStone => Color::rgba(0x8A, 0x82, 0x76, 1.0),
        V5FixtureKind::Tree => Color::rgba(0x4A, 0x6E, 0x2C, 1.0),
        V5FixtureKind::Bush => Color::rgba(0x5C, 0x82, 0x3A, 1.0),
        V5FixtureKind::Well => Color::rgba(0x6E, 0x6A, 0x60, 1.0),
        V5FixtureKind::Fountain => Color::rgba(0x6E, 0x8C, 0xB6, 1.0),
        V5FixtureKind::Stair => Color::rgba(0xC8, 0xC0, 0xA0, 1.0),
        V5FixtureKind::Gravestone => Color::rgba(0x88, 0x80, 0x76, 1.0),
        V5FixtureKind::Sign => Color::rgba(0x8C, 0x66, 0x3A, 1.0),
        V5FixtureKind::Mushroom => Color::rgba(0xB8, 0x44, 0x44, 1.0),
        _ => Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    }
}

pub fn draw<'a>(
    op: V5FixtureOp<'a>,
    _regions: Vector<'a, ForwardsUOffset<V5Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let anchors = match op.anchors() {
        Some(a) if !a.is_empty() => a,
        _ => return false,
    };
    let color = stub_color(op.kind());
    let paint = crate::painter::Paint::solid(color);
    let cell = 32.0_f32;
    for i in 0..anchors.len() {
        let a = anchors.get(i);
        let cx = a.x() as f32 * cell + cell * 0.5;
        let cy = a.y() as f32 * cell + cell * 0.5;
        painter.fill_circle(cx, cy, FIXTURE_STUB_RADIUS, &paint);
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs, V5Anchor,
        V5FixtureKind, V5FixtureOp as FbV5FixtureOp, V5FixtureOpArgs,
        V5OpEntry, V5OpEntryArgs, V5Op, V5Region as FbV5Region,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_fixture_op(kind: V5FixtureKind, anchors: &[V5Anchor]) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let anchors_vec = fbb.create_vector(anchors);
        let region_ref = fbb.create_string("");
        let fixture_op = FbV5FixtureOp::create(
            &mut fbb,
            &V5FixtureOpArgs {
                region_ref: Some(region_ref),
                kind,
                anchors: Some(anchors_vec),
                seed: 0xBEEF,
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5FixtureOp,
                op: Some(fixture_op.as_union_value()),
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
    fn draw_emits_one_circle_per_anchor() {
        let anchors = [
            V5Anchor::new(2, 3, 0, 0, 0, 0, 0),
            V5Anchor::new(4, 5, 0, 0, 0, 0, 0),
            V5Anchor::new(6, 7, 0, 0, 0, 0, 0),
        ];
        let buf = build_fixture_op(V5FixtureKind::Tree, &anchors);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_fixture_op()
            .expect("fixture op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        assert_eq!(painter.calls.len(), 3, "one circle per anchor");
        for call in &painter.calls {
            assert!(matches!(call, PainterCall::FillCircle(_, _, _, _)));
        }
    }

    #[test]
    fn draw_skips_empty_anchor_list() {
        let buf = build_fixture_op(V5FixtureKind::Skull, &[]);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_fixture_op()
            .expect("fixture op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }
}
