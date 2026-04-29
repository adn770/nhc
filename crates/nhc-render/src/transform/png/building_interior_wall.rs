//! BuildingInteriorWallOp rasterisation — Phase 8.3c of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_building_interior_wall_from_ir` in
//! `nhc/rendering/ir_to_svg.py`. Each `InteriorEdge` resolves to
//! a corner-grid line `(tile_x + Δx) × CELL` in pixel coords;
//! the rasteriser strokes it in the InteriorWallMaterial palette.
//! RNG-free; deterministic.

use tiny_skia::{
    Color, LineCap, Paint, PathBuilder, Stroke,
};

use crate::ir::{
    BuildingInteriorWallOp, FloorIR, InteriorEdge,
    InteriorWallMaterial, OpEntry, TileCorner,
};

use super::RasterCtx;


// Constants mirror nhc/rendering/ir_to_svg.py interior-wall block.

const CELL: f32 = 32.0;
const STROKE_WIDTH: f32 = CELL * 0.25;

// InteriorWallMaterial: Stone=0, Brick=1, Wood=2.
const STONE_RGB: (u8, u8, u8) = (0x70, 0x70, 0x70);
const BRICK_RGB: (u8, u8, u8) = (0xc4, 0x65, 0x1d);
const WOOD_RGB:  (u8, u8, u8) = (0x7a, 0x4e, 0x2c);


fn material_rgb(material: InteriorWallMaterial) -> (u8, u8, u8) {
    if material == InteriorWallMaterial::Brick {
        BRICK_RGB
    } else if material == InteriorWallMaterial::Wood {
        WOOD_RGB
    } else {
        STONE_RGB
    }
}


fn corner_delta(corner: TileCorner) -> (i32, i32) {
    if corner == TileCorner::NW {
        (0, 0)
    } else if corner == TileCorner::NE {
        (1, 0)
    } else if corner == TileCorner::SE {
        (1, 1)
    } else {
        (0, 1)  // SW
    }
}


fn paint_edge(
    edge: &InteriorEdge, paint: &Paint<'_>, stroke: &Stroke,
    ctx: &mut RasterCtx<'_>,
) {
    let (adx, ady) = corner_delta(edge.a_corner());
    let (bdx, bdy) = corner_delta(edge.b_corner());
    let px0 = ((edge.ax() + adx) as f32) * CELL;
    let py0 = ((edge.ay() + ady) as f32) * CELL;
    let px1 = ((edge.bx() + bdx) as f32) * CELL;
    let py1 = ((edge.by() + bdy) as f32) * CELL;
    let mut pb = PathBuilder::new();
    pb.move_to(px0, py0);
    pb.line_to(px1, py1);
    if let Some(path) = pb.finish() {
        ctx.pixmap.stroke_path(
            &path, paint, stroke, ctx.transform, None,
        );
    }
}


pub(super) fn draw(
    entry: &OpEntry<'_>,
    _fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op: BuildingInteriorWallOp = match entry.op_as_building_interior_wall_op() {
        Some(o) => o,
        None => return,
    };
    let edges = match op.edges() {
        Some(e) => e,
        None => return,
    };
    if edges.is_empty() {
        return;
    }
    let rgb = material_rgb(op.material());
    let mut paint = Paint::default();
    paint.set_color(Color::from_rgba8(rgb.0, rgb.1, rgb.2, 255));
    paint.anti_alias = true;
    let mut stroke = Stroke::default();
    stroke.width = STROKE_WIDTH;
    stroke.line_cap = LineCap::Round;
    for edge in edges.iter() {
        paint_edge(&edge, &paint, &stroke, ctx);
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn corner_delta_maps_correctly() {
        assert_eq!(corner_delta(TileCorner::NW), (0, 0));
        assert_eq!(corner_delta(TileCorner::NE), (1, 0));
        assert_eq!(corner_delta(TileCorner::SE), (1, 1));
        assert_eq!(corner_delta(TileCorner::SW), (0, 1));
    }

    #[test]
    fn material_rgb_brick_vs_stone_vs_wood() {
        assert_eq!(material_rgb(InteriorWallMaterial::Stone), STONE_RGB);
        assert_eq!(material_rgb(InteriorWallMaterial::Brick), BRICK_RGB);
        assert_eq!(material_rgb(InteriorWallMaterial::Wood), WOOD_RGB);
    }
}
