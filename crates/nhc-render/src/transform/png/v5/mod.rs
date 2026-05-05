//! v5 op handlers — Phase 1.3 of
//! `plans/nhc_pure_ir_v5_migration_plan.md`.
//!
//! Per-op modules under this directory consume the V5* FlatBuffers
//! reader types directly and drive the [`crate::painter::Painter`]
//! trait. Each handler is callable independently — the v5 ops are
//! NOT yet in the `Op` union, so the live `transform/png` dispatch
//! loop never reaches these handlers. Phase 1.4 wires v5 emit; the
//! atomic cut at Phase 1.8 makes them canonical.
//!
//! The handlers are backend-agnostic: they take `&mut dyn Painter`
//! rather than a concrete `SkiaPainter` or `SvgPainter`, mirroring
//! the v4 op handlers' shape (see `transform/png/floor_op.rs`).

pub mod fixture_op;
pub mod paint_op;
pub mod path_op;
pub mod region_path;
pub mod stamp_op;
pub mod stroke_op;

use crate::ir::{V5Material, V5MaterialFamily, V5Region};
use crate::painter::material::{Family, Material};

/// Bridge from a `V5Material` FB reader to the painter's POD
/// `Material`. The op handlers run this once per op; the painter
/// dispatches off the POD without re-reading the buffer.
pub fn material_from_fb(m: V5Material<'_>) -> Material {
    let family = match m.family() {
        V5MaterialFamily::Cave => Family::Cave,
        V5MaterialFamily::Wood => Family::Wood,
        V5MaterialFamily::Stone => Family::Stone,
        V5MaterialFamily::Earth => Family::Earth,
        V5MaterialFamily::Liquid => Family::Liquid,
        V5MaterialFamily::Special => Family::Special,
        // Plain (default) and any unknown trailing variant fall
        // through to Plain. v5 rejects unknown enum values at the
        // FB layer, so the catch-all is defensive only.
        _ => Family::Plain,
    };
    Material::new(family, m.style(), m.sub_pattern(), m.tone(), m.seed())
}

/// Linear scan a v5 regions vector for the entry whose id matches
/// `needle`. Mirrors the v4 `find_region` helpers across the per-op
/// handlers — small fixtures don't need a hash map.
pub fn find_v5_region<'a>(
    regions: ::flatbuffers::Vector<'a, ::flatbuffers::ForwardsUOffset<V5Region<'a>>>,
    needle: &str,
) -> Option<V5Region<'a>> {
    if needle.is_empty() {
        return None;
    }
    for i in 0..regions.len() {
        let r = regions.get(i);
        if r.id() == needle {
            return Some(r);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{V5Material, V5MaterialArgs, V5MaterialFamily};

    fn build_v5_material(family: V5MaterialFamily, style: u8) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let m = V5Material::create(
            &mut fbb,
            &V5MaterialArgs {
                family,
                style,
                sub_pattern: 0,
                tone: 0,
                seed: 0xCAFE,
            },
        );
        fbb.finish_minimal(m);
        fbb.finished_data().to_vec()
    }

    #[test]
    fn material_from_fb_maps_family_one_for_one() {
        for (fam_fb, fam_pod) in [
            (V5MaterialFamily::Plain, Family::Plain),
            (V5MaterialFamily::Cave, Family::Cave),
            (V5MaterialFamily::Wood, Family::Wood),
            (V5MaterialFamily::Stone, Family::Stone),
            (V5MaterialFamily::Earth, Family::Earth),
            (V5MaterialFamily::Liquid, Family::Liquid),
            (V5MaterialFamily::Special, Family::Special),
        ] {
            let buf = build_v5_material(fam_fb, 0);
            let m = flatbuffers::root::<V5Material>(&buf).expect("parse");
            let pod = material_from_fb(m);
            assert_eq!(pod.family, fam_pod, "mismatch for {fam_fb:?}");
            assert_eq!(pod.seed, 0xCAFE);
        }
    }
}
