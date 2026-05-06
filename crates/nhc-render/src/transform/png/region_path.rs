//! Build a `PathOps` from a v5 / v4-shared `Outline`.
//!
//! Lifts the polygon / circle / pill outline-traversal logic out
//! of `transform/png/floor_op.rs` so v5 op handlers (PaintOp,
//! StrokeOp) share a single implementation. The shape construction
//! is identical to today's FloorOp polygon path; only the call site
//! changes.

use crate::ir::{Outline, OutlineKind};
use crate::painter::{PathOps, Vec2};

/// Cubic Bézier kappa for a quarter-circle arc — used by Pill.
const PILL_KAPPA: f32 = 0.5523;

/// Build a `PathOps` representing the outline. Returns `None` for
/// outlines that can't produce a valid path (empty vertex list,
/// zero radii, unknown descriptor). Caller decides what to fill.
pub fn outline_to_path(outline: &Outline<'_>) -> Option<(PathOps, MultiRing)> {
    match outline.descriptor_kind() {
        OutlineKind::Polygon => polygon_path(outline),
        OutlineKind::Circle => circle_path(outline).map(|p| (p, MultiRing::Single)),
        OutlineKind::Pill => pill_path(outline).map(|p| (p, MultiRing::Single)),
        _ => None,
    }
}

/// Whether the path carries multiple rings (caller's hint for
/// `FillRule::EvenOdd`). Single-ring outlines fill with Winding.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MultiRing {
    Single,
    Multi,
}

fn polygon_path(outline: &Outline<'_>) -> Option<(PathOps, MultiRing)> {
    let verts = outline.vertices()?;
    if verts.len() < 3 {
        return None;
    }
    let rings = outline.rings();
    let mut path = PathOps::new();
    let mut any = false;
    let mut multi_ring = MultiRing::Single;

    let push_ring = |path: &mut PathOps, start: usize, count: usize| -> bool {
        if count < 2 || start + count > verts.len() {
            return false;
        }
        let v0 = verts.get(start);
        path.move_to(Vec2::new(v0.x(), v0.y()));
        for j in 1..count {
            let v = verts.get(start + j);
            path.line_to(Vec2::new(v.x(), v.y()));
        }
        path.close();
        true
    };

    match rings {
        Some(rs) if rs.len() > 0 => {
            multi_ring = MultiRing::Multi;
            for r in rs.iter() {
                if push_ring(&mut path, r.start() as usize, r.count() as usize) {
                    any = true;
                }
            }
        }
        _ => {
            if push_ring(&mut path, 0, verts.len()) {
                any = true;
            }
        }
    }

    if !any {
        return None;
    }
    Some((path, multi_ring))
}

fn circle_path(outline: &Outline<'_>) -> Option<PathOps> {
    let cx = outline.cx();
    let cy = outline.cy();
    let r = outline.rx();
    if r <= 0.0 {
        return None;
    }
    // SVG-equivalent quarter-arc cubic Bézier ladder.
    let k = r * PILL_KAPPA;
    let mut path = PathOps::new();
    path.move_to(Vec2::new(cx + r, cy));
    path.cubic_to(
        Vec2::new(cx + r, cy + k),
        Vec2::new(cx + k, cy + r),
        Vec2::new(cx, cy + r),
    );
    path.cubic_to(
        Vec2::new(cx - k, cy + r),
        Vec2::new(cx - r, cy + k),
        Vec2::new(cx - r, cy),
    );
    path.cubic_to(
        Vec2::new(cx - r, cy - k),
        Vec2::new(cx - k, cy - r),
        Vec2::new(cx, cy - r),
    );
    path.cubic_to(
        Vec2::new(cx + k, cy - r),
        Vec2::new(cx + r, cy - k),
        Vec2::new(cx + r, cy),
    );
    path.close();
    Some(path)
}

fn pill_path(outline: &Outline<'_>) -> Option<PathOps> {
    let cx = outline.cx();
    let cy = outline.cy();
    let rx = outline.rx();
    let ry = outline.ry();
    if rx <= 0.0 || ry <= 0.0 {
        return None;
    }
    let r = rx.min(ry);
    let x0 = cx - rx;
    let y0 = cy - ry;
    let x1 = cx + rx;
    let y1 = cy + ry;
    let k = r * PILL_KAPPA;
    let mut path = PathOps::new();
    path.move_to(Vec2::new(x0 + r, y0));
    path.line_to(Vec2::new(x1 - r, y0));
    path.cubic_to(
        Vec2::new(x1 - r + k, y0),
        Vec2::new(x1, y0 + r - k),
        Vec2::new(x1, y0 + r),
    );
    path.line_to(Vec2::new(x1, y1 - r));
    path.cubic_to(
        Vec2::new(x1, y1 - r + k),
        Vec2::new(x1 - r + k, y1),
        Vec2::new(x1 - r, y1),
    );
    path.line_to(Vec2::new(x0 + r, y1));
    path.cubic_to(
        Vec2::new(x0 + r - k, y1),
        Vec2::new(x0, y1 - r + k),
        Vec2::new(x0, y1 - r),
    );
    path.line_to(Vec2::new(x0, y0 + r));
    path.cubic_to(
        Vec2::new(x0, y0 + r - k),
        Vec2::new(x0 + r - k, y0),
        Vec2::new(x0 + r, y0),
    );
    path.close();
    Some(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{Outline, OutlineArgs, OutlineKind, Vec2 as FbVec2};

    fn build_polygon_outline_buf() -> Vec<u8> {
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
        fbb.finish_minimal(outline);
        fbb.finished_data().to_vec()
    }

    #[test]
    fn polygon_outline_produces_single_ring_path() {
        let buf = build_polygon_outline_buf();
        let outline = flatbuffers::root::<Outline>(&buf).expect("parse");
        let (path, ring) = outline_to_path(&outline).expect("path");
        assert_eq!(ring, MultiRing::Single);
        assert!(!path.is_empty());
    }

    #[test]
    fn empty_polygon_returns_none() {
        let mut fbb = FlatBufferBuilder::new();
        let outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        fbb.finish_minimal(outline);
        let buf = fbb.finished_data().to_vec();
        let outline = flatbuffers::root::<Outline>(&buf).expect("parse");
        assert!(outline_to_path(&outline).is_none());
    }
}
