//! V5FixtureOp consumer — discrete decorative objects with anchors.
//!
//! Phase 2.11 of `plans/nhc_pure_ir_v5_migration_plan.md`. Lifts
//! the existing per-fixture painters from
//! `crates/nhc-render/src/primitives/{tree, bush, well, fountain,
//! stairs}.rs` into the v5 FixtureOp dispatcher. The remaining
//! seven kinds (Web, Skull, Bone, LooseStone, Gravestone, Sign,
//! Mushroom) ride additive Phase 2.11 follow-on commits — those
//! lift from `primitives/{floor_detail, thematic_detail}.rs` (Web
//! / Skull / Bone / LooseStone) or land as new painter algorithms
//! (Gravestone / Sign / Mushroom).
//!
//! Group_id fusion logic is shared across clustering kinds (Tree
//! groves, Mushroom clusters, Gravestone clusters): anchors with
//! the same non-zero `group_id` fuse into one cluster; group_id=0
//! means standalone. Anchor.variant / orientation feed per-kind
//! sub-style dispatch (Well shape, Fountain shape, Stair
//! direction).

use std::collections::BTreeMap;

use flatbuffers::{ForwardsUOffset, Vector};

use crate::ir::{V5Anchor, V5FixtureKind, V5FixtureOp, V5Region};
use crate::painter::{Color, Painter};
use crate::primitives::bush::paint_bush;
use crate::primitives::fountain::paint_fountain;
use crate::primitives::stairs::paint_stairs;
use crate::primitives::tree::paint_tree;
use crate::primitives::well::paint_well;

/// Sentinel placeholder colour for the seven not-yet-lifted kinds
/// (Web / Skull / Bone / LooseStone / Gravestone / Sign / Mushroom).
/// Each anchor renders as a small filled circle in the kind's
/// sentinel hue — enough for the dispatcher contract test, replaced
/// with real painter algorithms in Phase 2.11 follow-on commits.
fn stub_color(kind: V5FixtureKind) -> Color {
    match kind {
        V5FixtureKind::Web => Color::rgba(0xE0, 0xE0, 0xE0, 0.55),
        V5FixtureKind::Skull => Color::rgba(0xF5, 0xEC, 0xC8, 1.0),
        V5FixtureKind::Bone => Color::rgba(0xE8, 0xDD, 0xB3, 1.0),
        V5FixtureKind::LooseStone => Color::rgba(0x8A, 0x82, 0x76, 1.0),
        V5FixtureKind::Gravestone => Color::rgba(0x88, 0x80, 0x76, 1.0),
        V5FixtureKind::Sign => Color::rgba(0x8C, 0x66, 0x3A, 1.0),
        V5FixtureKind::Mushroom => Color::rgba(0xB8, 0x44, 0x44, 1.0),
        _ => Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    }
}

const STUB_RADIUS: f32 = 6.0;

fn collect_tiles(anchors: &Vector<'_, V5Anchor>) -> Vec<(i32, i32)> {
    (0..anchors.len())
        .map(|i| {
            let a = anchors.get(i);
            (a.x(), a.y())
        })
        .collect()
}

/// Group anchors by `group_id` for fusion-supporting kinds (Tree,
/// Mushroom, Gravestone). Returns `(free, groves)`: free are
/// anchors with `group_id = 0` (standalone), groves are the lists
/// of `(x, y)` tile coords keyed by `group_id`.
fn split_by_group(anchors: &Vector<'_, V5Anchor>) -> (Vec<(i32, i32)>, Vec<Vec<(i32, i32)>>) {
    let mut free = Vec::new();
    let mut groups: BTreeMap<u32, Vec<(i32, i32)>> = BTreeMap::new();
    for i in 0..anchors.len() {
        let a = anchors.get(i);
        if a.group_id() == 0 {
            free.push((a.x(), a.y()));
        } else {
            groups.entry(a.group_id()).or_default().push((a.x(), a.y()));
        }
    }
    (free, groups.into_values().collect())
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
    let kind = op.kind();
    match kind {
        V5FixtureKind::Tree => {
            let (free, groves) = split_by_group(&anchors);
            paint_tree(painter, &free, &groves);
        }
        V5FixtureKind::Bush => {
            let tiles = collect_tiles(&anchors);
            paint_bush(painter, &tiles);
        }
        V5FixtureKind::Well => {
            // ``Anchor.variant`` carries the well shape (round / square).
            // Group anchors by variant since the v4 painter wants a
            // homogeneous tile list per shape.
            let mut by_variant: BTreeMap<u8, Vec<(i32, i32)>> = BTreeMap::new();
            for i in 0..anchors.len() {
                let a = anchors.get(i);
                by_variant.entry(a.variant()).or_default().push((a.x(), a.y()));
            }
            for (variant, tiles) in by_variant {
                paint_well(painter, &tiles, variant);
            }
        }
        V5FixtureKind::Fountain => {
            let mut by_variant: BTreeMap<u8, Vec<(i32, i32)>> = BTreeMap::new();
            for i in 0..anchors.len() {
                let a = anchors.get(i);
                by_variant.entry(a.variant()).or_default().push((a.x(), a.y()));
            }
            for (variant, tiles) in by_variant {
                paint_fountain(painter, &tiles, variant);
            }
        }
        V5FixtureKind::Stair => {
            // Anchor.orientation carries the direction (0=up, 1=down)
            // per design/map_ir_v5.md §7. Theme + fill colour default
            // to the v4 dungeon palette here; cave-stair styling
            // returns when the painter takes a substance reference
            // (deferred until Phase 3.1's PSNR gate flags it).
            let stairs: Vec<(i32, i32, u8)> = (0..anchors.len())
                .map(|i| {
                    let a = anchors.get(i);
                    (a.x(), a.y(), a.orientation())
                })
                .collect();
            paint_stairs(painter, &stairs, "dungeon", "#FFFFFF");
        }
        _ => {
            // Seven not-yet-lifted kinds — paint a placeholder marker
            // circle per anchor in the kind's sentinel hue.
            let paint = crate::painter::Paint::solid(stub_color(kind));
            let cell = 32.0_f32;
            for i in 0..anchors.len() {
                let a = anchors.get(i);
                let cx = a.x() as f32 * cell + cell * 0.5;
                let cy = a.y() as f32 * cell + cell * 0.5;
                painter.fill_circle(cx, cy, STUB_RADIUS, &paint);
            }
        }
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

    fn run(buf: &[u8]) -> MockPainter {
        let fir = root_as_floor_ir(buf).expect("parse");
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
        painter
    }

    /// Tree dispatch routes to ``paint_tree``: each free tree paints
    /// trunk + canopy + shadow strokes (no group envelope per
    /// primitives/tree.rs §2.14c). One isolated tree anchor (group_id
    /// = 0) emits multiple painter calls — pin that the dispatcher
    /// reaches the lifted painter rather than the legacy circle stub.
    #[test]
    fn draw_routes_tree_kind_to_paint_tree() {
        let anchors = [V5Anchor::new(2, 3, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Tree, &anchors));
        // The legacy stub emitted exactly one FillCircle per anchor.
        // The lifted painter emits multiple calls (trunk, shadow,
        // canopy, volume marks) — assert > 1 to catch a regression
        // back to the stub.
        assert!(
            painter.calls.len() > 1,
            "expected multi-call lifted tree painter, got {}",
            painter.calls.len()
        );
    }

    /// Trees with the same non-zero `group_id` fuse into one grove.
    /// The painter's grove path differs from N free-tree paths in
    /// the call shape — pin that fusion took effect by routing
    /// through the grove branch.
    #[test]
    fn tree_anchors_with_same_group_id_fuse_into_grove() {
        let anchors = [
            V5Anchor::new(2, 3, 0, 0, 0, 7, 0),
            V5Anchor::new(3, 3, 0, 0, 0, 7, 0),
            V5Anchor::new(4, 3, 0, 0, 0, 7, 0),
        ];
        let painter = run(&build_fixture_op(V5FixtureKind::Tree, &anchors));
        // Grove painter emits a unified canopy path — pin that we
        // exercise the grove branch by checking that the call set
        // includes multiple kinds (the grove emits FillPath + StrokePath).
        let has_fill_path = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::FillPath(_, _, _)));
        assert!(has_fill_path);
    }

    #[test]
    fn draw_routes_bush_kind_to_paint_bush() {
        let anchors = [V5Anchor::new(5, 5, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Bush, &anchors));
        // The legacy stub emitted exactly one FillCircle.
        // The bush painter emits a closed PathOps fill via fill_path
        // — pin that we exercised the lifted painter.
        let has_fill_path = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::FillPath(_, _, _)));
        assert!(has_fill_path);
    }

    #[test]
    fn draw_routes_well_kind_to_paint_well() {
        let anchors = [V5Anchor::new(3, 4, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Well, &anchors));
        // Well painter emits multiple primitives (rim, water, mortar).
        // Multi-call signal pins the dispatch.
        assert!(painter.calls.len() > 1);
    }

    #[test]
    fn draw_routes_fountain_kind_to_paint_fountain() {
        let anchors = [V5Anchor::new(6, 6, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Fountain, &anchors));
        assert!(painter.calls.len() > 1);
    }

    #[test]
    fn draw_routes_stair_kind_to_paint_stairs() {
        // Direction = 0 (up).
        let anchors = [V5Anchor::new(7, 7, 0, 0, 0, 0, 0)];
        let painter = run(&build_fixture_op(V5FixtureKind::Stair, &anchors));
        assert!(painter.calls.len() > 1);
    }

    /// Not-yet-lifted kinds fall through to the placeholder marker:
    /// one FillCircle per anchor in the kind's sentinel hue.
    #[test]
    fn draw_emits_placeholder_circles_for_not_yet_lifted_kinds() {
        for kind in [
            V5FixtureKind::Web,
            V5FixtureKind::Skull,
            V5FixtureKind::Bone,
            V5FixtureKind::LooseStone,
            V5FixtureKind::Gravestone,
            V5FixtureKind::Sign,
            V5FixtureKind::Mushroom,
        ] {
            let anchors = [
                V5Anchor::new(1, 1, 0, 0, 0, 0, 0),
                V5Anchor::new(2, 2, 0, 0, 0, 0, 0),
            ];
            let painter = run(&build_fixture_op(kind, &anchors));
            assert_eq!(
                painter.calls.len(),
                2,
                "kind {kind:?}: expected 2 placeholder FillCircles"
            );
            for c in &painter.calls {
                assert!(matches!(c, PainterCall::FillCircle(_, _, _, _)));
            }
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
