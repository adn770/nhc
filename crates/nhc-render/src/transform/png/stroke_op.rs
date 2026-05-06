//! StrokeOp consumer — wall stroke along outline.
//!
//! Phase 1.3 shipped the dispatch shape: read geometry from
//! `region_ref` (→ Region.outline) or from `op.outline` (interior
//! partitions, free-standing walls), dispatch on
//! `wall_material.treatment` (PlainStroke / Masonry / Partition /
//! Palisade / Fortification).
//!
//! Phase 2.8 of `plans/nhc_pure_ir_v5_migration_plan.md` wires
//! substance-aware palette resolution: stroke ink comes from the
//! wall material's `(family, style, tone)` shadow palette role —
//! the same shadow colour that decorators use for seams / mortar
//! when painting over a region of the same family. Per-treatment
//! stroke width gives a visible visual differentiator between the
//! five treatments (PlainStroke 1.5 px, Masonry 3.0, Partition
//! 1.0, Palisade 2.5, Fortification 4.0) so the dispatch is
//! observable on the rendered output even before each treatment's
//! drawing algorithm lands.
//!
//! Per-treatment drawing algorithms (Masonry running-bond layout,
//! Palisade vertical-pole grid, Fortification crenellated
//! battlement with `CornerStyle` handling, Partition dressed
//! thin-wall) ride additive Phase 2.8 follow-on commits — this
//! commit ships the dispatch shape + substance palette baseline
//! so the rest of the plan can sequence per-treatment work.

use flatbuffers::{ForwardsUOffset, Vector};

use super::region_path::outline_to_path;
use crate::ir::{MaterialFamily, Region, StrokeOp, WallTreatment};
use crate::painter::material::{substance_color, Family, PaletteRole};
use crate::painter::{Paint, Painter, Stroke};

/// Map the FlatBuffers `MaterialFamily` to the painter's `Family`
/// POD. Mirrors the bridge in `super::material_from_fb`.
fn family_from_fb(family: MaterialFamily) -> Family {
    match family {
        MaterialFamily::Cave => Family::Cave,
        MaterialFamily::Wood => Family::Wood,
        MaterialFamily::Stone => Family::Stone,
        MaterialFamily::Earth => Family::Earth,
        MaterialFamily::Liquid => Family::Liquid,
        MaterialFamily::Special => Family::Special,
        _ => Family::Plain,
    }
}

/// Per-treatment stroke width baseline. Acts as a visible visual
/// differentiator between the five treatments while the per-
/// treatment drawing algorithms are deferred to follow-on commits.
fn treatment_stroke_width(treatment: WallTreatment) -> f32 {
    match treatment {
        WallTreatment::PlainStroke => 1.5,
        WallTreatment::Masonry => 3.0,
        WallTreatment::Partition => 1.0,
        WallTreatment::Palisade => 2.5,
        WallTreatment::Fortification => 4.0,
        _ => 1.5,
    }
}

/// Walk an Outline's vertex list into a (closed) polygon-pair list.
/// Returns ``None`` when the outline carries fewer than 3 vertices
/// or no vertices at all.
fn outline_polygon(outline: &crate::ir::Outline<'_>) -> Option<Vec<(f32, f32)>> {
    let verts = outline.vertices()?;
    if verts.len() < 3 {
        return None;
    }
    let mut out: Vec<(f32, f32)> = Vec::with_capacity(verts.len());
    for i in 0..verts.len() {
        let v = verts.get(i);
        out.push((v.x(), v.y()));
    }
    // Drop a trailing duplicate if the source carries the closing
    // vertex inline (Shapely-style closed rings).
    if out.len() >= 2 {
        let last = out.len() - 1;
        if (out[0].0 - out[last].0).abs() < 1e-6
            && (out[0].1 - out[last].1).abs() < 1e-6
        {
            out.truncate(last);
        }
    }
    if out.len() < 3 { None } else { Some(out) }
}


pub fn draw<'a>(
    op: StrokeOp<'a>,
    regions: Vector<'a, ForwardsUOffset<Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let outline = if let Some(o) = op.outline() {
        Some(o)
    } else if let Some(rr) = op.region_ref() {
        if rr.is_empty() {
            None
        } else {
            super::find_region(regions, rr).and_then(|r| r.outline())
        }
    } else {
        None
    };
    let outline = match outline {
        Some(o) => o,
        None => return false,
    };
    let wm = match op.wall_material() {
        Some(m) => m,
        None => return false,
    };
    let family = family_from_fb(wm.family());

    // Per-treatment dispatch — Masonry / Palisade / Fortification
    // pull dedicated drawing algorithms; the rest fall through to
    // the simple shadow-color stroke.
    let polygon = outline_polygon(&outline);
    match (wm.treatment(), polygon.as_ref()) {
        (WallTreatment::Masonry, Some(poly)) => {
            super::masonry::render_masonry_polygon(
                poly, family, wm.style(), wm.seed(), painter,
            );
            return true;
        }
        (WallTreatment::Palisade, Some(poly)) => {
            super::enclosure::render_palisade_polygon(
                poly, op.cuts(), family, wm.style(), wm.seed(), painter,
            );
            return true;
        }
        (WallTreatment::Fortification, Some(poly)) => {
            super::enclosure::render_fortification_polygon(
                poly, op.cuts(), wm.corner_style(), painter,
            );
            return true;
        }
        _ => {}
    }

    let (path, _multi) = match outline_to_path(&outline) {
        Some(p) => p,
        None => return false,
    };
    let color = substance_color(family, wm.style(), wm.tone(), PaletteRole::Shadow);
    let paint = Paint::solid(color);
    let stroke = Stroke::solid(treatment_stroke_width(wm.treatment()));
    painter.stroke_path(&path, &paint, &stroke);
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, CornerStyle, FloorIR,
        FloorIRArgs, Outline, OutlineArgs, OutlineKind, MaterialFamily,
        OpEntry, OpEntryArgs, Op, Region as FbRegion, RegionArgs,
        StrokeOp as FbStrokeOp, StrokeOpArgs, WallMaterial,
        WallMaterialArgs, WallTreatment, Vec2 as FbVec2,
    };
    use crate::painter::families::stone;
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_stroke_op_with_region(
        family: MaterialFamily,
        style: u8,
        treatment: WallTreatment,
    ) -> Vec<u8> {
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
        let region_ref = fbb.create_string("room.0");
        let wall_material = WallMaterial::create(
            &mut fbb,
            &WallMaterialArgs {
                family,
                style,
                treatment,
                corner_style: CornerStyle::Merlon,
                tone: 0,
                seed: 0xC0FFEE,
            },
        );
        let stroke_op = FbStrokeOp::create(
            &mut fbb,
            &StrokeOpArgs {
                region_ref: Some(region_ref),
                outline: None,
                wall_material: Some(wall_material),
                cuts: None,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::StrokeOp,
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
                regions: Some(v5_regions),
                ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    fn paint_for(buf: &[u8]) -> (PainterCall,) {
        let fir = root_as_floor_ir(buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_stroke_op()
            .expect("stroke op");
        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        assert_eq!(painter.calls.len(), 1);
        (painter.calls.into_iter().next().unwrap(),)
    }

    /// PlainStroke pulls the family's `Shadow` palette. With a
    /// Stone family at style=0 (Cobblestone), the shadow colour is
    /// the cobblestone mortar (`#9A8A7A`).
    #[test]
    fn stroke_color_resolves_to_family_shadow_palette() {
        let buf = build_stroke_op_with_region(
            MaterialFamily::Stone,
            0,
            WallTreatment::PlainStroke,
        );
        let (call,) = paint_for(&buf);
        let expected = stone::palette(0).shadow;
        match call {
            PainterCall::StrokePath(_, paint, _) => {
                assert_eq!(paint.color, expected);
            }
            other => panic!("expected StrokePath, got {other:?}"),
        }
    }

    /// PlainStroke and Partition still flow through the plain-stroke
    /// fallback at distinct widths (1.5 vs 1.0). Polish 4d lifts
    /// Partition to its own dressed thin-wall algorithm; until then
    /// this gates the simple-stroke dispatch.
    #[test]
    fn plain_stroke_and_partition_pick_distinct_stroke_widths() {
        let mut seen = Vec::new();
        for treatment in [WallTreatment::PlainStroke, WallTreatment::Partition] {
            let buf = build_stroke_op_with_region(
                MaterialFamily::Stone, 0, treatment,
            );
            let (call,) = paint_for(&buf);
            match call {
                PainterCall::StrokePath(_, _, stroke) => {
                    assert!(
                        !seen.contains(&stroke.width.to_bits()),
                        "treatment {treatment:?} reuses earlier stroke width"
                    );
                    seen.push(stroke.width.to_bits());
                }
                other => panic!("expected StrokePath, got {other:?}"),
            }
        }
    }

    /// Different families produce distinct stroke colours for the
    /// same PlainStroke treatment — pins the substance-driven
    /// palette dispatch.
    #[test]
    fn different_families_produce_distinct_stroke_colors() {
        let stone_buf = build_stroke_op_with_region(
            MaterialFamily::Stone,
            0,
            WallTreatment::PlainStroke,
        );
        let wood_buf = build_stroke_op_with_region(
            MaterialFamily::Wood,
            0,
            WallTreatment::PlainStroke,
        );
        let (stone_call,) = paint_for(&stone_buf);
        let (wood_call,) = paint_for(&wood_buf);
        let stone_color = match stone_call {
            PainterCall::StrokePath(_, p, _) => p.color,
            _ => panic!(),
        };
        let wood_color = match wood_call {
            PainterCall::StrokePath(_, p, _) => p.color,
            _ => panic!(),
        };
        assert_ne!(stone_color, wood_color);
    }

    /// Masonry treatment paints a running-bond chain of rounded-rect
    /// stones (one per stone, two strips per edge) — far more
    /// FillPath calls than the trivial single-stroke baseline.
    #[test]
    fn masonry_treatment_emits_running_bond_stone_chain() {
        let buf = build_stroke_op_with_region(
            MaterialFamily::Stone,
            crate::transform::png::masonry::STONE_BRICK_STYLE,
            WallTreatment::Masonry,
        );
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("regions");
        let op = fir.ops().expect("ops").get(0)
            .op_as_stroke_op().expect("stroke op");
        let mut painter = MockPainter::default();
        assert!(draw(op, regions, &mut painter));
        // Rect outline 64×64 with WALL_THICKNESS=8 gives a running-
        // bond chain of ~5 stones × 2 strips × 4 edges. Pin a soft
        // floor (≥ 16 fill calls) rather than an exact count so
        // per-stone-width jitter doesn't flip the test.
        let fill_calls = painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillPath(_, _, _)))
            .count();
        assert!(
            fill_calls >= 16,
            "expected ≥ 16 stone fills for a 4-edge polygon, got {fill_calls}"
        );
    }

    /// Palisade treatment paints circle posts (one per fill_circle
    /// call) along the polygon edges. A 4-edge polygon at the test
    /// dimensions emits dozens of posts.
    #[test]
    fn palisade_treatment_emits_circle_post_chain() {
        let buf = build_stroke_op_with_region(
            MaterialFamily::Wood,
            0,
            WallTreatment::Palisade,
        );
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("regions");
        let op = fir.ops().expect("ops").get(0)
            .op_as_stroke_op().expect("stroke op");
        let mut painter = MockPainter::default();
        assert!(draw(op, regions, &mut painter));
        let circle_calls = painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillCircle(_, _, _, _)))
            .count();
        assert!(
            circle_calls >= 8,
            "expected ≥ 8 palisade post fills on a 4-edge polygon, got {circle_calls}"
        );
    }

    /// Fortification treatment paints alternating crenel / merlon
    /// rectangles along the polygon edges plus a corner shape per
    /// vertex. A 4-edge polygon emits at least one fill_rect per
    /// chain step + one per corner.
    #[test]
    fn fortification_treatment_emits_battlement_rects_and_corners() {
        let buf = build_stroke_op_with_region(
            MaterialFamily::Stone,
            crate::transform::png::masonry::STONE_BRICK_STYLE,
            WallTreatment::Fortification,
        );
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("regions");
        let op = fir.ops().expect("ops").get(0)
            .op_as_stroke_op().expect("stroke op");
        let mut painter = MockPainter::default();
        assert!(draw(op, regions, &mut painter));
        let rect_calls = painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::FillRect(_, _)))
            .count();
        // 4-edge polygon (64×64) yields multiple battlement steps
        // per edge plus 4 corner shapes — ≥ 8 fill_rect calls.
        assert!(
            rect_calls >= 8,
            "expected ≥ 8 fortification fill_rects, got {rect_calls}"
        );
    }

    /// Masonry stones pull the family-style palette base for fill
    /// and shadow for seam.
    #[test]
    fn masonry_stone_fill_and_seam_match_family_palette() {
        use crate::painter::material::{substance_color, PaletteRole};
        let buf = build_stroke_op_with_region(
            MaterialFamily::Stone,
            crate::transform::png::masonry::STONE_BRICK_STYLE,
            WallTreatment::Masonry,
        );
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("regions");
        let op = fir.ops().expect("ops").get(0)
            .op_as_stroke_op().expect("stroke op");
        let mut painter = MockPainter::default();
        draw(op, regions, &mut painter);
        let fill_color = substance_color(
            Family::Stone,
            crate::transform::png::masonry::STONE_BRICK_STYLE,
            0,
            PaletteRole::Base,
        );
        let seam_color = substance_color(
            Family::Stone,
            crate::transform::png::masonry::STONE_BRICK_STYLE,
            0,
            PaletteRole::Shadow,
        );
        let mut saw_fill = false;
        let mut saw_seam = false;
        for call in &painter.calls {
            match call {
                PainterCall::FillPath(_, paint, _) => {
                    if paint.color == fill_color {
                        saw_fill = true;
                    }
                }
                PainterCall::StrokePath(_, paint, _) => {
                    if paint.color == seam_color {
                        saw_seam = true;
                    }
                }
                _ => {}
            }
        }
        assert!(saw_fill, "no FillPath with Stone:Brick base color");
        assert!(saw_seam, "no StrokePath with Stone:Brick shadow color");
    }
}
