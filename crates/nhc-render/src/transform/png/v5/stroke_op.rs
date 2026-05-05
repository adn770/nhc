//! V5StrokeOp consumer — wall stroke along outline.
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
use crate::ir::{V5MaterialFamily, V5Region, V5StrokeOp, V5WallTreatment};
use crate::painter::material::{substance_color, Family, PaletteRole};
use crate::painter::{Paint, Painter, Stroke};

/// Map the FlatBuffers `V5MaterialFamily` to the painter's `Family`
/// POD. Mirrors the bridge in `super::material_from_fb`.
fn family_from_fb(family: V5MaterialFamily) -> Family {
    match family {
        V5MaterialFamily::Cave => Family::Cave,
        V5MaterialFamily::Wood => Family::Wood,
        V5MaterialFamily::Stone => Family::Stone,
        V5MaterialFamily::Earth => Family::Earth,
        V5MaterialFamily::Liquid => Family::Liquid,
        V5MaterialFamily::Special => Family::Special,
        _ => Family::Plain,
    }
}

/// Per-treatment stroke width baseline. Acts as a visible visual
/// differentiator between the five treatments while the per-
/// treatment drawing algorithms are deferred to follow-on commits.
fn treatment_stroke_width(treatment: V5WallTreatment) -> f32 {
    match treatment {
        V5WallTreatment::PlainStroke => 1.5,
        V5WallTreatment::Masonry => 3.0,
        V5WallTreatment::Partition => 1.0,
        V5WallTreatment::Palisade => 2.5,
        V5WallTreatment::Fortification => 4.0,
        _ => 1.5,
    }
}

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
    let family = family_from_fb(wm.family());
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
        FloorIRArgs, Outline, OutlineArgs, OutlineKind, V5MaterialFamily,
        V5OpEntry, V5OpEntryArgs, V5Op, V5Region as FbV5Region, V5RegionArgs,
        V5StrokeOp as FbV5StrokeOp, V5StrokeOpArgs, V5WallMaterial,
        V5WallMaterialArgs, V5WallTreatment, Vec2 as FbVec2,
    };
    use crate::painter::families::stone;
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_stroke_op_with_region(
        family: V5MaterialFamily,
        style: u8,
        treatment: V5WallTreatment,
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
                family,
                style,
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

    fn paint_for(buf: &[u8]) -> (PainterCall,) {
        let fir = root_as_floor_ir(buf).expect("parse");
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
        (painter.calls.into_iter().next().unwrap(),)
    }

    /// Stroke colour pulls the family's `Shadow` palette. With a
    /// Stone family at style=0 (Cobblestone), the shadow colour is
    /// the cobblestone mortar (`#9A8A7A`).
    #[test]
    fn stroke_color_resolves_to_family_shadow_palette() {
        let buf = build_stroke_op_with_region(
            V5MaterialFamily::Stone,
            0,
            V5WallTreatment::Masonry,
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

    /// Per-treatment stroke widths must be distinct so the dispatch
    /// is observable on rendered output even before each treatment's
    /// drawing algorithm lands.
    #[test]
    fn each_treatment_picks_a_distinct_stroke_width() {
        let mut seen = Vec::new();
        for treatment in [
            V5WallTreatment::PlainStroke,
            V5WallTreatment::Masonry,
            V5WallTreatment::Partition,
            V5WallTreatment::Palisade,
            V5WallTreatment::Fortification,
        ] {
            let buf = build_stroke_op_with_region(
                V5MaterialFamily::Stone,
                0,
                treatment,
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
    /// same treatment — pins the substance-driven palette dispatch.
    #[test]
    fn different_families_produce_distinct_stroke_colors() {
        let stone_buf = build_stroke_op_with_region(
            V5MaterialFamily::Stone,
            0,
            V5WallTreatment::Masonry,
        );
        let wood_buf = build_stroke_op_with_region(
            V5MaterialFamily::Wood,
            0,
            V5WallTreatment::Masonry,
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
}
