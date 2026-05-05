//! V5StampOp consumer — per-region surface texture overlays.
//!
//! Phase 1.3 ships the dispatch shape: walk the bits of
//! `decorator_mask`, fan out to per-bit painter stubs. Phase 2.9
//! lands real per-bit algorithms (cracks, scratches, moss, blood,
//! ash, puddles, ripples, lava-cracks, grid-lines).
//!
//! Per-bit baseline densities live in the painter source (not in
//! the IR). `StampOp.density` (uint8, 128 = baseline) scales
//! every enabled bit uniformly; for per-bit divergence the
//! emitter ships multiple StampOps with different masks /
//! densities targeting the same region.

use flatbuffers::{ForwardsUOffset, Vector};

use super::region_path::outline_to_path;
use crate::ir::{V5Region, V5StampOp};
use crate::painter::{Color, FillRule, Paint, Painter};

/// Stable bit assignments — mirrors design/map_ir_v5.md §5 and
/// the V5StampOp bit registry. Adding a new decorator bit (Phase 2
/// or later) is one entry here plus a per-bit painter
/// implementation.
pub mod bit {
    pub const GRID_LINES: u32 = 1 << 0;
    pub const CRACKS: u32 = 1 << 1;
    pub const SCRATCHES: u32 = 1 << 2;
    pub const RIPPLES: u32 = 1 << 3;
    pub const LAVA_CRACKS: u32 = 1 << 4;
    pub const MOSS: u32 = 1 << 5;
    pub const BLOOD: u32 = 1 << 6;
    pub const ASH: u32 = 1 << 7;
    pub const PUDDLES: u32 = 1 << 8;

    pub const ALL: &[u32] = &[
        GRID_LINES, CRACKS, SCRATCHES, RIPPLES, LAVA_CRACKS,
        MOSS, BLOOD, ASH, PUDDLES,
    ];
}

/// Sentinel placeholder colour for each bit (Phase 1.3 stub).
/// Phase 2.9 swaps these for real per-bit painters with seed-
/// driven per-tile placement.
fn stub_color(bit_value: u32) -> Color {
    match bit_value {
        bit::GRID_LINES => Color::rgba(0xC0, 0xC0, 0xC0, 0.20),
        bit::CRACKS => Color::rgba(0x40, 0x40, 0x40, 0.45),
        bit::SCRATCHES => Color::rgba(0x60, 0x60, 0x60, 0.30),
        bit::RIPPLES => Color::rgba(0xFF, 0xFF, 0xFF, 0.20),
        bit::LAVA_CRACKS => Color::rgba(0xFF, 0xC8, 0x40, 0.50),
        bit::MOSS => Color::rgba(0x55, 0x88, 0x33, 0.40),
        bit::BLOOD => Color::rgba(0x88, 0x10, 0x10, 0.55),
        bit::ASH => Color::rgba(0x80, 0x80, 0x80, 0.35),
        bit::PUDDLES => Color::rgba(0x18, 0x28, 0x40, 0.30),
        _ => Color::rgba(0xFF, 0x00, 0xFF, 1.0),
    }
}

pub fn draw<'a>(
    op: V5StampOp<'a>,
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
    let (path, _multi) = match outline_to_path(&outline) {
        Some(p) => p,
        None => return false,
    };
    let mask = op.decorator_mask();
    if mask == 0 {
        return false;
    }
    // Phase 1.3 stub: each enabled bit emits one full-region
    // translucent fill in its sentinel hue. Phase 2.9 replaces
    // each arm with seed-driven per-tile stamping.
    for bit_value in bit::ALL {
        if mask & bit_value != 0 {
            let paint = Paint::solid(stub_color(*bit_value));
            painter.fill_path(&path, &paint, FillRule::Winding);
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs, Outline,
        OutlineArgs, OutlineKind, V5OpEntry, V5OpEntryArgs, V5Op,
        V5Region as FbV5Region, V5RegionArgs, V5StampOp as FbV5StampOp,
        V5StampOpArgs, Vec2 as FbVec2,
    };
    use crate::painter::test_util::MockPainter;

    fn build_stamp_op(mask: u32) -> Vec<u8> {
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
                ..Default::default()
            },
        );
        let v5_regions = fbb.create_vector(&[region]);
        let region_ref = fbb.create_string("room.0");
        let stamp_op = FbV5StampOp::create(
            &mut fbb,
            &V5StampOpArgs {
                region_ref: Some(region_ref),
                subtract_region_refs: None,
                decorator_mask: mask,
                density: 128,
                seed: 0xCAFE,
            },
        );
        let op_entry = V5OpEntry::create(
            &mut fbb,
            &V5OpEntryArgs {
                op_type: V5Op::V5StampOp,
                op: Some(stamp_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
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
        fbb.finished_data().to_vec()
    }

    #[test]
    fn draw_emits_one_call_per_enabled_decorator_bit() {
        // Three bits set: GridLines | Cracks | Moss → 3 fill_path
        // calls in stub-mode.
        let mask = bit::GRID_LINES | bit::CRACKS | bit::MOSS;
        let buf = build_stamp_op(mask);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_stamp_op()
            .expect("stamp op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        assert_eq!(painter.calls.len(), 3);
    }

    #[test]
    fn empty_decorator_mask_skips_painting() {
        let buf = build_stamp_op(0);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.v5_regions().expect("v5_regions");
        let op = fir
            .v5_ops()
            .expect("v5_ops")
            .get(0)
            .op_as_v5_stamp_op()
            .expect("stamp op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }
}
