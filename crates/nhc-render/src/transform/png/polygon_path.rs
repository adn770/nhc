//! Shared `Outline` → `tiny-skia::Path` conversion.
//!
//! The IR's `Outline` table holds a flat vertex list optionally
//! keyed by `PathRange` rings (exterior + holes). Several
//! rasterisers (`terrain_tints`, `floor_grid`, ...) want the same
//! multi-subpath conversion, so it lives here rather than per
//! handler.

use tiny_skia::PathBuilder;

use crate::ir::Outline;

/// Walk every ring (exterior + holes) into a single Path with one
/// subpath per ring. When ``outline.rings`` is empty (the v4e
/// shorthand: vertices IS the single exterior ring), the walker
/// emits one subpath covering the entire vertex list. Caller
/// decides the fill rule when rendering — even-odd is the right
/// choice for clip masks / hole-aware fills.
pub fn build_outline_path(outline: &Outline<'_>) -> Option<tiny_skia::Path> {
    let verts = outline.vertices()?;
    if verts.is_empty() {
        return None;
    }
    let mut pb = PathBuilder::new();
    let mut any = false;
    let rings = outline.rings();
    let ring_iter: Vec<(usize, usize)> = match rings {
        Some(r) if r.len() > 0 => r
            .iter()
            .map(|pr| (pr.start() as usize, pr.count() as usize))
            .collect(),
        _ => vec![(0, verts.len())],
    };
    for (start, count) in ring_iter {
        if count < 2 {
            continue;
        }
        for j in 0..count {
            let v = verts.get(start + j);
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
