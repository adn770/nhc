//! `Family::Plain` painter — flat parchment-white fill.
//!
//! The single style (`Default = 0`) paints `#FFFFFF`. Any region
//! that should appear as the default canvas (most dungeon rooms,
//! most surface void areas) maps to this family. There is no
//! sub_pattern axis and no tone axis — `style`, `sub_pattern`,
//! and `tone` are all expected to be 0.

use crate::painter::material::{fill_region, Material};
use crate::painter::{Color, Painter, PathOps};

const PLAIN_FILL: Color = Color::rgba(0xFF, 0xFF, 0xFF, 1.0);

pub fn paint<P: Painter + ?Sized>(painter: &mut P, region_path: &PathOps, _material: &Material) {
    fill_region(painter, region_path, PLAIN_FILL);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::material::Family;
    use crate::painter::test_util::{MockPainter, PainterCall};
    use crate::painter::Vec2;

    fn one_tile_path() -> PathOps {
        let mut p = PathOps::new();
        p.move_to(Vec2::new(0.0, 0.0))
            .line_to(Vec2::new(32.0, 0.0))
            .line_to(Vec2::new(32.0, 32.0))
            .line_to(Vec2::new(0.0, 32.0))
            .close();
        p
    }

    #[test]
    fn plain_paints_solid_white_fill() {
        let mut p = MockPainter::default();
        let path = one_tile_path();
        let m = Material::new(Family::Plain, 0, 0, 0, 0);
        paint(&mut p, &path, &m);
        assert_eq!(p.calls.len(), 1);
        match &p.calls[0] {
            PainterCall::FillPath(_path, paint, _rule) => {
                assert_eq!(paint.color.r, 0xFF);
                assert_eq!(paint.color.g, 0xFF);
                assert_eq!(paint.color.b, 0xFF);
                assert_eq!(paint.color.a, 1.0);
            }
            other => panic!("expected FillPath, got {other:?}"),
        }
    }
}
