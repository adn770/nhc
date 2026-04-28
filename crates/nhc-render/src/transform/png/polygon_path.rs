//! Shared `Polygon` → `tiny-skia::Path` conversion.
//!
//! The IR's `Polygon` table holds a flat point list keyed by
//! `PathRange` rings (exterior + holes). Several rasterisers
//! (`terrain_tints`, `floor_grid`, the `walls_and_floors` cave
//! branch in 5.5) want the same multi-subpath conversion, so it
//! lives here rather than per handler.

use tiny_skia::PathBuilder;

use crate::ir::Polygon;

/// Walk every ring (exterior + holes) into a single Path with
/// one subpath per ring. Caller decides the fill rule when
/// rendering — even-odd is the right choice for clip masks /
/// hole-aware fills.
pub fn build_polygon_path(polygon: &Polygon<'_>) -> Option<tiny_skia::Path> {
    let paths = polygon.paths()?;
    let rings = polygon.rings()?;
    let mut pb = PathBuilder::new();
    let mut any = false;
    for ring in rings.iter() {
        let start = ring.start() as usize;
        let count = ring.count() as usize;
        if count < 2 {
            continue;
        }
        for j in 0..count {
            let v = paths.get(start + j);
            let x = v.x();
            let y = v.y();
            if j == 0 {
                pb.move_to(x, y);
            } else {
                pb.line_to(x, y);
            }
        }
        pb.close();
        any = true;
    }
    if !any {
        return None;
    }
    pb.finish()
}
