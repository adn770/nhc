//! RoofOp consumer — projection-geometry roof.
//!
//! Phase 3.1 follow-on of `plans/nhc_pure_ir_v5_migration_plan.md`.
//! Bridges the v5 ``RoofOp`` to the polygon-driven inner painter
//! `super::roof::draw_roof_polygon`. The dispatch shape:
//!
//! 1. Look up the building region in ``v5_regions[]`` by
//!    ``op.region_ref``.
//! 2. Extract the polygon vertex list from the v5 region's
//!    outline.
//! 3. Pull style + tint + seed from the RoofOp; build a clip
//!    path from the region's outline (EvenOdd rule for multi-ring
//!    outlines).
//! 4. Hand off to the polygon-driven inner painter, which
//!    dispatches per-style: `Simple` (flat tint), `Pyramid`
//!    (centroid spokes), `Gable` (long-axis ridge), `Dome`
//!    (concentric rings), `WitchHat` (offset apex).

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
    let tint = op.tint().filter(|s| !s.is_empty()).unwrap_or("#8A7A5A");
    let clip = build_clip_pathops(&outline);
    super::roof::draw_roof_polygon(
        painter,
        &polygon,
        op.style(),
        op.sub_pattern(),
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
        RoofOpArgs, RoofStyle, RoofTilePattern, Vec2 as FbVec2,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    /// Out-of-enum `RoofTilePattern` byte: hits the dispatch
    /// catch-all so only the style geometry paints, no texture
    /// overlay. `Plain` used to serve this role before the
    /// roof-pattern redesign retired it; production never emits
    /// an unknown pattern, so this stays a test-only baseline for
    /// the geometry-isolation assertions below.
    const GEOMETRY_ONLY: RoofTilePattern = RoofTilePattern(0xFF);

    fn build_roof_op(shape_tag: &str, style: RoofStyle) -> Vec<u8> {
        build_roof_op_with_pattern(shape_tag, style, GEOMETRY_ONLY)
    }

    fn build_roof_op_with_pattern(
        shape_tag: &str,
        style: RoofStyle,
        sub_pattern: RoofTilePattern,
    ) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
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
                style,
                tone: 1,
                tint: Some(tint),
                seed: 0xCAFE_F00D,
                sub_pattern,
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

    fn fill_path_count(painter: &MockPainter) -> usize {
        painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillPath(_, _, _)))
            .count()
    }

    fn fill_circle_count(painter: &MockPainter) -> usize {
        painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillCircle(_, _, _, _)))
            .count()
    }

    fn fill_rect_count(painter: &MockPainter) -> usize {
        painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
            .count()
    }

    /// Every style still wraps painting in a clip envelope so
    /// shingles / fills stay inside the building outline.
    #[test]
    fn every_style_wraps_in_clip_envelope() {
        for style in [
            RoofStyle::Simple,
            RoofStyle::Pyramid,
            RoofStyle::Gable,
            RoofStyle::Dome,
            RoofStyle::WitchHat,
        ] {
            let painter = run(&build_roof_op("rect", style));
            let pushed = painter
                .calls
                .iter()
                .any(|c| matches!(c, PainterCall::PushClip(_, _)));
            assert!(pushed, "{style:?}: missing PushClip envelope");
        }
    }

    /// `Simple` → single flat-tint fill_path. No shingle rows, no
    /// ridge spokes. The catalog's Simple column renders this.
    #[test]
    fn simple_style_emits_single_flat_fill() {
        let painter = run(&build_roof_op("rect", RoofStyle::Simple));
        // Exactly one FillPath (the flat polygon fill).
        assert_eq!(fill_path_count(&painter), 1);
        // No shingle FillRects, no apex disc.
        assert_eq!(fill_rect_count(&painter), 0);
        assert_eq!(fill_circle_count(&painter), 0);
    }

    /// `Pyramid` → centroid spokes; one fill_path per polygon
    /// edge plus a single multi-segment ridge stroke. No apex
    /// disc.
    #[test]
    fn pyramid_style_emits_centroid_pyramid_sides() {
        let painter = run(&build_roof_op("rect", RoofStyle::Pyramid));
        // Square polygon has 4 edges → 4 FillPath calls (one per
        // triangular side).
        assert_eq!(fill_path_count(&painter), 4);
        assert_eq!(fill_circle_count(&painter), 0);
    }

    /// `Gable` → two flat shaded half-planes split on the long
    /// axis plus a ridge stroke. Geometry no longer bakes
    /// shingles (that is now the `Shingle` overlay pattern), so
    /// the bare gable emits exactly 2 FillPath (the halves) and
    /// zero FillRect.
    #[test]
    fn gable_style_emits_two_flat_planes() {
        let painter = run(&build_roof_op("rect", RoofStyle::Gable));
        assert_eq!(
            fill_path_count(&painter), 2,
            "Gable should emit two flat half-plane fills"
        );
        assert_eq!(
            fill_rect_count(&painter), 0,
            "Gable geometry must not bake shingle rects"
        );
    }

    /// `Dome` → concentric inset polygons, no spoke ridge stroke.
    /// Pin: at least 4 FillPath calls (one per ring) and zero
    /// FillRect / FillCircle calls.
    #[test]
    fn dome_style_emits_concentric_rings() {
        let painter = run(&build_roof_op("rect", RoofStyle::Dome));
        assert!(
            fill_path_count(&painter) >= 4,
            "Dome should emit concentric ring fills"
        );
        assert_eq!(fill_rect_count(&painter), 0);
        assert_eq!(fill_circle_count(&painter), 0);
    }

    /// `WitchHat` → pyramid-style sides plus a small bright apex
    /// disc. Pin: at least one FillCircle for the apex tip.
    #[test]
    fn witch_hat_style_renders_offset_apex_disc() {
        let painter = run(&build_roof_op("rect", RoofStyle::WitchHat));
        assert_eq!(
            fill_circle_count(&painter), 1,
            "WitchHat should overlay a bright apex disc"
        );
        // Spoked sides too.
        assert!(fill_path_count(&painter) >= 4);
    }

    fn stroke_path_count(painter: &MockPainter) -> usize {
        painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::StrokePath(_, _, _)))
            .count()
    }

    /// An unknown `RoofTilePattern` byte hits the dispatch
    /// catch-all and paints geometry only — no texture overlay.
    /// Pyramid geometry emits FillPath facets + ridge strokes but
    /// never FillRect / FillCircle, so the geometry-only baseline
    /// must show zero of those. This pins the no-op fallback that
    /// the geometry-isolation tests rely on now that `Plain` is
    /// gone.
    #[test]
    fn unknown_pattern_paints_geometry_only() {
        let geom = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, GEOMETRY_ONLY,
        ));
        assert_eq!(fill_rect_count(&geom), 0);
        assert_eq!(fill_circle_count(&geom), 0);
    }

    /// `Fishscale` → many `FillCircle` calls (one per scallop
    /// tile) on top of the geometry's base. A pyramid-only render
    /// emits zero FillCircles, so any FillCircle count > 0 is
    /// the fishscale overlay.
    #[test]
    fn fishscale_pattern_overlays_circles() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, RoofTilePattern::Fishscale,
        ));
        assert!(
            fill_circle_count(&painter) > 4,
            "Fishscale should paint many scallops"
        );
    }

    /// Each fishscale scallop carries a thin black outline so the
    /// pattern reads clearly. The bare pyramid emits only its
    /// single ridge stroke; fishscale adds one outline stroke per
    /// scale, so the StrokePath count climbs well past it.
    #[test]
    fn fishscale_scales_have_outline() {
        let bare = run(&build_roof_op("rect", RoofStyle::Pyramid));
        let fish = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, RoofTilePattern::Fishscale,
        ));
        assert!(
            stroke_path_count(&fish) > stroke_path_count(&bare) + 4,
            "Fishscale should outline each scallop (got {} vs bare {})",
            stroke_path_count(&fish),
            stroke_path_count(&bare),
        );
    }

    /// `Thatch` → many short `StrokePath` strands. The base
    /// pyramid emits 1 multi-segment ridge stroke; thatch adds
    /// many independent strands, so the StrokePath count climbs.
    #[test]
    fn thatch_pattern_overlays_short_strands() {
        let bare = run(&build_roof_op("rect", RoofStyle::Pyramid));
        let thatch = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, RoofTilePattern::Thatch,
        ));
        assert!(
            stroke_path_count(&thatch) > stroke_path_count(&bare) + 10,
            "Thatch should add many strand strokes"
        );
    }

    /// `Pantile` → wavy `FillPath` bands. Each band is a closed
    /// sinusoidal path. Pyramid alone emits N triangular FillPath
    /// calls; pantile overlays additional band fills.
    #[test]
    fn pantile_pattern_overlays_sinusoidal_bands() {
        let bare = run(&build_roof_op("rect", RoofStyle::Pyramid));
        let pant = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, RoofTilePattern::Pantile,
        ));
        assert!(
            fill_path_count(&pant) > fill_path_count(&bare),
            "Pantile should add band FillPaths"
        );
    }

    /// `Slate` → many small `FillRect` tiles. Pyramid alone emits
    /// zero FillRects, so any positive count is the slate
    /// overlay.
    #[test]
    fn slate_pattern_overlays_small_rect_tiles() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, RoofTilePattern::Slate,
        ));
        assert!(
            fill_rect_count(&painter) > 4,
            "Slate should paint many rect tiles"
        );
    }

    /// `Shingle` → organic running-bond `FillRect` tiles, each
    /// with a faint edge stroke. Pyramid alone emits zero
    /// FillRects; the overlay adds many tiles plus their strokes.
    #[test]
    fn shingle_pattern_overlays_running_bond_tiles() {
        let bare = run(&build_roof_op("rect", RoofStyle::Pyramid));
        let shingle = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, RoofTilePattern::Shingle,
        ));
        assert!(
            fill_rect_count(&shingle) > 4,
            "Shingle should paint many running-bond tiles"
        );
        assert!(
            stroke_path_count(&shingle) > stroke_path_count(&bare) + 4,
            "Shingle tiles should carry a faint edge stroke"
        );
    }

    fn push_transforms(painter: &MockPainter) -> Vec<crate::painter::Transform> {
        painter
            .calls
            .iter()
            .filter_map(|c| match c {
                PainterCall::PushTransform(t) => Some(*t),
                _ => None,
            })
            .collect()
    }

    /// Phase 4: a gable pattern mirrors across the ridge. The two
    /// halves are painted separately and the second is the
    /// reflection of the first, so exactly one `PushTransform`
    /// is recorded and it is a pure reflection (negative
    /// determinant). The tile fill is still present in both
    /// halves.
    #[test]
    fn gable_pattern_mirrors_across_ridge() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Gable, RoofTilePattern::Shingle,
        ));
        let xforms = push_transforms(&painter);
        assert_eq!(
            xforms.len(), 1,
            "gable pattern mirrors via exactly one reflection"
        );
        let t = xforms[0];
        let det = t.sx * t.sy - t.kx * t.ky;
        assert!(
            det < 0.0,
            "the mirror transform must be a reflection (det {det} < 0)"
        );
        assert!(
            fill_rect_count(&painter) > 4,
            "both gable halves still carry the shingle tile field"
        );
    }

    /// Geometry-only gable paints no overlay, so it must not open
    /// the per-half mirror scopes — zero `PushTransform`. Pins
    /// that the no-op fallback stays a clean single-pass render.
    #[test]
    fn gable_geometry_only_emits_no_transform() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Gable, GEOMETRY_ONLY,
        ));
        assert_eq!(push_transforms(&painter).len(), 0);
    }

    /// Phase 4: a Pyramid pattern is framed per facet — one
    /// `PushTransform` per polygon edge (the square test footprint
    /// has 4). The square's axis-aligned top/bottom facets frame
    /// as pure translations while the side facets carry a real
    /// rotation, so the frames must differ facet-to-facet and at
    /// least one must be a rotation (non-zero off-axis term). The
    /// tile fill survives across the facets.
    #[test]
    fn pyramid_pattern_rotates_per_facet() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Pyramid, RoofTilePattern::Shingle,
        ));
        let xforms = push_transforms(&painter);
        assert_eq!(
            xforms.len(), 4,
            "one frame transform per pyramid facet (4 edges)"
        );
        let any_rotation = xforms
            .iter()
            .any(|t| t.kx != 0.0 || t.ky != 0.0);
        assert!(any_rotation, "side facets must rotate the frame");
        let all_same = xforms.iter().all(|t| *t == xforms[0]);
        assert!(!all_same, "facet frames must differ per face");
        assert!(
            fill_rect_count(&painter) > 4,
            "the shingle field tiles every facet"
        );
    }

    /// WitchHat shares the faceted-frame path, so it also emits
    /// one transform per facet and still overlays its bright apex
    /// disc on top.
    #[test]
    fn witch_hat_pattern_rotates_per_facet_and_keeps_apex() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::WitchHat, RoofTilePattern::Shingle,
        ));
        assert_eq!(push_transforms(&painter).len(), 4);
        assert_eq!(
            fill_circle_count(&painter), 1,
            "WitchHat keeps its apex disc under the pattern"
        );
    }

    fn push_clip_rules(
        painter: &MockPainter,
    ) -> Vec<crate::painter::FillRule> {
        painter
            .calls
            .iter()
            .filter_map(|c| match c {
                PainterCall::PushClip(_, rule) => Some(*rule),
                _ => None,
            })
            .collect()
    }

    /// Phase 4: a Dome pattern follows concentric rings. The
    /// overlay is banded into the dome's tonal rings (one
    /// EvenOdd annulus clip per band) and the faceted frame is
    /// applied within each band so the texture curves around
    /// rather than tiling a straight screen grid. So a Dome +
    /// pattern emits several EvenOdd clips (the ring annuli) and
    /// many more facet transforms than a single faceted pass.
    #[test]
    fn dome_pattern_follows_concentric_rings() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Dome, RoofTilePattern::Shingle,
        ));
        let evenodd = push_clip_rules(&painter)
            .into_iter()
            .filter(|r| matches!(r, crate::painter::FillRule::EvenOdd))
            .count();
        assert!(
            evenodd >= 3,
            "dome pattern bands into concentric ring annuli \
             (got {evenodd} EvenOdd clips)"
        );
        assert!(
            push_transforms(&painter).len() >= 8,
            "facet frames repeat per ring band"
        );
        assert!(fill_rect_count(&painter) > 4);
    }

    /// Geometry-only Dome paints no overlay → no ring-band
    /// scopes, no facet transforms.
    #[test]
    fn dome_geometry_only_emits_no_transform() {
        let painter = run(&build_roof_op_with_pattern(
            "rect", RoofStyle::Dome, GEOMETRY_ONLY,
        ));
        assert_eq!(push_transforms(&painter).len(), 0);
    }
}
