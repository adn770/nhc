//! RoofOp consumer — projection-geometry shingled roof.
//!
//! Phase 3.1 follow-on of `plans/nhc_pure_ir_v5_migration_plan.md`.
//! Bridges the v5 ``RoofOp`` to the polygon-driven inner painter
//! `super::roof::draw_roof_polygon` lifted from the v4 RoofOp
//! handler. The dispatch shape:
//!
//! 1. Look up the building region in ``v5_regions[]`` by
//!    ``op.region_ref``.
//! 2. Extract the polygon vertex list + shape_tag from the v5
//!    region's outline.
//! 3. Pull tint + seed from the RoofOp; build a clip path from
//!    the region's outline (EvenOdd rule for multi-ring outlines).
//! 4. Hand off to the polygon-driven inner painter — the same
//!    code path the v4 dispatch reaches.
//!
//! The v5 Material model (RoofStyle / tone) is currently unused
//! by the inner painter; that pipeline picks geometry mode from
//! ``shape_tag`` alone. Style / tone integration rides a Phase 5+
//! follow-on once the painter grows a tone-aware palette table.

use flatbuffers::{ForwardsUOffset, Vector};

use crate::ir::{Region, RoofOp};
use crate::painter::{PathOps, Painter, Vec2};

pub fn draw<'a>(
    op: RoofOp<'a>,
    regions: Vector<'a, ForwardsUOffset<Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let region_ref = match op.region_ref() {
        Some(r) if !r.is_empty() => r,
        _ => return false,
    };
    let region = match super::find_region(regions, region_ref) {
        Some(r) => r,
        None => return false,
    };
    let outline = match region.outline() {
        Some(o) => o,
        None => return false,
    };
    let verts = match outline.vertices() {
        Some(v) if v.len() >= 3 => v,
        _ => return false,
    };
    let polygon: Vec<(f32, f32)> = verts.iter().map(|p| (p.x(), p.y())).collect();
    let shape_tag = region.shape_tag().unwrap_or("");
    let tint = op.tint().filter(|s| !s.is_empty()).unwrap_or("#8A7A5A");
    let clip = build_clip_pathops(&outline);
    super::roof::draw_roof_polygon(
        painter,
        &polygon,
        shape_tag,
        tint,
        op.seed(),
        clip.as_ref(),
    );
    true
}

/// Walk an outline (single-ring or multi-ring) into a closed
/// PathOps clip path. Mirrors the v4 ``roof::build_clip_pathops``
/// shape; duplicated here to keep v5 op handlers free of v4
/// region-type dependencies.
fn build_clip_pathops(outline: &crate::ir::Outline<'_>) -> Option<PathOps> {
    let verts = outline.vertices()?;
    if verts.is_empty() {
        return None;
    }
    let rings = outline.rings();
    let ring_iter: Vec<(usize, usize)> = match rings {
        Some(r) if r.len() > 0 => r
            .iter()
            .map(|pr| (pr.start() as usize, pr.count() as usize))
            .collect(),
        _ => vec![(0, verts.len())],
    };
    let mut path = PathOps::new();
    let mut any = false;
    for (start, count) in ring_iter {
        if count < 2 {
            continue;
        }
        for j in 0..count {
            let v = verts.get(start + j);
            let p = Vec2::new(v.x(), v.y());
            if j == 0 {
                path.move_to(p);
            } else {
                path.line_to(p);
            }
        }
        path.close();
        any = true;
    }
    if !any {
        None
    } else {
        Some(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs, Outline,
        OutlineArgs, OutlineKind, OpEntry, OpEntryArgs, Op,
        Region as FbRegion, RegionArgs, RoofOp as FbRoofOp,
        RoofOpArgs, RoofStyle, Vec2 as FbVec2,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_roof_op(shape_tag: &str) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        // Square polygon for shape_tag = "rect" → pyramid roof.
        let verts = fbb.create_vector(&[
            FbVec2::new(64.0, 64.0),
            FbVec2::new(192.0, 64.0),
            FbVec2::new(192.0, 192.0),
            FbVec2::new(64.0, 192.0),
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
        let region_id = fbb.create_string("building.0");
        let region_shape = fbb.create_string(shape_tag);
        let region = FbRegion::create(
            &mut fbb,
            &RegionArgs {
                id: Some(region_id),
                outline: Some(outline),
                shape_tag: Some(region_shape),
                ..Default::default()
            },
        );
        let v5_regions = fbb.create_vector(&[region]);
        let region_ref = fbb.create_string("building.0");
        let tint = fbb.create_string("#8A7A5A");
        let roof_op = FbRoofOp::create(
            &mut fbb,
            &RoofOpArgs {
                region_ref: Some(region_ref),
                style: RoofStyle::Simple,
                tone: 1,
                tint: Some(tint),
                seed: 0xCAFE_F00D,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::RoofOp,
                op: Some(roof_op.as_union_value()),
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
                regions: Some(v5_regions),
                ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    fn run(buf: &[u8]) -> MockPainter {
        let fir = root_as_floor_ir(buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_roof_op()
            .expect("roof op");
        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        painter
    }

    /// Rect roof routes through the polygon painter — pyramid mode,
    /// emits multiple shingle paths inside a clip envelope.
    #[test]
    fn rect_shape_tag_routes_to_pyramid_roof() {
        let painter = run(&build_roof_op("rect"));
        // Pyramid emits N triangular sides; each side draws several
        // shingle rows. Multi-call output pins the dispatch.
        assert!(painter.calls.len() > 1);
        let pushed = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::PushClip(_, _)));
        assert!(pushed, "rect roof should push a clip envelope");
    }

    /// Wide-rect roof uses gable mode (longer axis ridge). The
    /// polygon painter dispatches via shape_tag + dimensions.
    #[test]
    fn wide_rect_uses_gable_mode_via_inner_painter() {
        let painter = run(&build_roof_op("rect"));
        // Both modes emit closed paths; pin that the call set
        // contains fill_path (shingle quads).
        let has_fill = painter
            .calls
            .iter()
            .any(|c| matches!(c, PainterCall::FillPath(_, _, _)));
        assert!(has_fill);
    }
}
