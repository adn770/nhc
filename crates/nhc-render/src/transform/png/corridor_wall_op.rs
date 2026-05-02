//! CorridorWallOp rasterisation — Phase 1.18 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Reads `CorridorWallOp.tiles` from the IR and emits one wall stroke
//! per tile edge that borders void (non-walkable) space.
//!
//! Algorithm mirrors `_draw_corridor_wall_op_from_ir` in `ir_to_svg.py`:
//! 1. Compute the walkable tile set from all FloorOps (`walkable_tiles`).
//! 2. For each corridor tile, check its four cardinal neighbours.
//!    Emit a stroke on each edge whose neighbour is NOT walkable.
//! 3. Building-footprint filter: when the floor has Building regions,
//!    a corridor tile inside the building only paints edges toward other
//!    building tiles (mirrors the `_draw_wall_to` predicate).
//!
//! Guard: only emits when the DungeonInk consumer is active (both a
//! CorridorWallOp and a DungeonInk ExteriorWallOp are present). On
//! floors without DungeonInk ExteriorWallOps (e.g. masonry-only sites),
//! the legacy `wall_segments` field still covers corridor walls.

use tiny_skia::{Color, LineCap, LineJoin, Paint, PathBuilder, Stroke};

use crate::ir::{FloorIR, FloorStyle, Op, OpEntry, OutlineKind, RegionKind};

use super::exterior_wall_op::has_dungeon_ink_wall_ops;
use super::RasterCtx;

const CELL: f32 = 32.0;
const INK_R: u8 = 0x00;
const INK_G: u8 = 0x00;
const INK_B: u8 = 0x00;
const WALL_WIDTH: f32 = 5.0;

fn ink_paint() -> Paint<'static> {
    let mut p = Paint::default();
    p.set_color(Color::from_rgba8(INK_R, INK_G, INK_B, 0xFF));
    p.anti_alias = true;
    p
}

fn wall_stroke() -> Stroke {
    Stroke {
        width: WALL_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
        ..Stroke::default()
    }
}

/// `OpHandler` dispatch entry — registered against `Op::CorridorWallOp`
/// in `super::op_handlers`.
pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    // Guard: only emit when the DungeonInk consumer is fully active.
    if !has_dungeon_ink_wall_ops(fir) {
        return;
    }

    let op = match entry.op_as_corridor_wall_op() {
        Some(o) => o,
        None => return,
    };
    let tiles_vec = match op.tiles() {
        Some(t) => t,
        None => return,
    };
    if tiles_vec.is_empty() {
        return;
    }

    let width = fir.width_tiles() as i32;
    let height = fir.height_tiles() as i32;

    let walkable = walkable_tiles_from_ir(fir, width, height);
    let building_tiles = building_footprint_tiles(fir, width, height);

    let mut pb = PathBuilder::new();
    let mut any = false;

    for tile in tiles_vec.iter() {
        let tx = tile.x();
        let ty = tile.y();
        let px = tx as f32 * CELL;
        let py = ty as f32 * CELL;

        let in_building = building_tiles
            .as_ref()
            .map(|bt| bt.contains(&(tx, ty)))
            .unwrap_or(false);

        // (neighbour_x, neighbour_y, x0, y0, x1, y1)
        let neighbours: [(i32, i32, f32, f32, f32, f32); 4] = [
            (tx, ty - 1, px, py, px + CELL, py),
            (tx, ty + 1, px, py + CELL, px + CELL, py + CELL),
            (tx - 1, ty, px, py, px, py + CELL),
            (tx + 1, ty, px + CELL, py, px + CELL, py + CELL),
        ];

        for (nx, ny, x0, y0, x1, y1) in neighbours.iter() {
            if walkable.contains(&(*nx, *ny)) {
                continue;
            }
            if in_building {
                if let Some(bt) = &building_tiles {
                    if !bt.contains(&(*nx, *ny)) {
                        continue;
                    }
                }
            }
            pb.move_to(*x0, *y0);
            pb.line_to(*x1, *y1);
            any = true;
        }
    }

    if !any {
        return;
    }
    let path = match pb.finish() {
        Some(p) => p,
        None => return,
    };
    ctx.pixmap
        .stroke_path(&path, &ink_paint(), &wall_stroke(), ctx.transform, None);
}

// ── Geometry helpers (mirrors Python DungeonInk consumer helpers) ────────

/// Compute the set of walkable tile coords from all FloorOps.
///
/// Mirrors `_walkable_tiles_from_ir` in `ir_to_svg.py`. For Polygon
/// FloorOps:
/// - 4-vertex axis-aligned bbox: enumerate tiles directly.
/// - Other polygon: bounding-box scan with centre-point containment.
/// Circle and Pill: bounding-box scan with centre-point containment.
fn walkable_tiles_from_ir(
    fir: &FloorIR<'_>,
    width: i32,
    height: i32,
) -> std::collections::HashSet<(i32, i32)> {
    use geo::{Contains, Coord, LineString, Point, Polygon as GeoPoly};

    let mut result = std::collections::HashSet::new();

    let ops = match fir.ops() {
        Some(o) => o,
        None => return result,
    };

    for entry in ops.iter() {
        if entry.op_type() != Op::FloorOp {
            continue;
        }
        let op = match entry.op_as_floor_op() {
            Some(o) => o,
            None => continue,
        };
        if op.style() != FloorStyle::DungeonFloor
            && op.style() != FloorStyle::CaveFloor
        {
            continue;
        }
        let outline = match op.outline() {
            Some(o) => o,
            None => continue,
        };

        match outline.descriptor_kind() {
            OutlineKind::Polygon => {
                let verts = match outline.vertices() {
                    Some(v) if !v.is_empty() => v,
                    _ => continue,
                };
                let coords: Vec<(f32, f32)> =
                    verts.iter().map(|v| (v.x(), v.y())).collect();
                // Phase 1.26d-3 — multi-ring outlines (merged corridor
                // FloorOp's disjoint connected components, plus
                // interior holes for annular components that wrap a
                // room) require ring-aware grouping. Group consecutive
                // ``is_hole=true`` rings under their preceding
                // exterior; build one geo polygon per exterior with
                // its holes so containment correctly excludes hole
                // regions.
                let rings = outline.rings();
                type Ring<'a> = &'a [(f32, f32)];
                type Group<'a> = (Ring<'a>, Vec<Ring<'a>>);
                let groups: Vec<Group<'_>> = match rings {
                    Some(rs) if rs.len() > 0 => {
                        let mut acc: Vec<Group<'_>> = Vec::new();
                        for r in rs.iter() {
                            let s = r.start() as usize;
                            let c = r.count() as usize;
                            if c < 2 || s + c > coords.len() {
                                continue;
                            }
                            let ring_slice = &coords[s..s + c];
                            if !r.is_hole() {
                                acc.push((ring_slice, Vec::new()));
                            } else if let Some(g) = acc.last_mut() {
                                g.1.push(ring_slice);
                            }
                            // Orphan hole (no preceding exterior) is dropped.
                        }
                        acc
                    }
                    _ => vec![(&coords[..], Vec::new())],
                };

                for (ext_coords, hole_rings) in groups {
                    let n = ext_coords.len();
                    if n < 2 {
                        continue;
                    }

                    if n == 4 && hole_rings.is_empty() {
                        // Axis-aligned bbox with no holes: derive directly.
                        let xs: Vec<f32> =
                            ext_coords.iter().map(|c| c.0).collect();
                        let ys: Vec<f32> =
                            ext_coords.iter().map(|c| c.1).collect();
                        let x0 = xs.iter().cloned().fold(f32::MAX, f32::min) as i32;
                        let y0 = ys.iter().cloned().fold(f32::MAX, f32::min) as i32;
                        let x1 = xs.iter().cloned().fold(f32::MIN, f32::max) as i32;
                        let y1 = ys.iter().cloned().fold(f32::MIN, f32::max) as i32;
                        let tx0 = x0 / CELL as i32;
                        let ty0 = y0 / CELL as i32;
                        let tx1 = x1 / CELL as i32;
                        let ty1 = y1 / CELL as i32;
                        for ty in ty0..ty1 {
                            for tx in tx0..tx1 {
                                if tx >= 0 && tx < width && ty >= 0 && ty < height {
                                    result.insert((tx, ty));
                                }
                            }
                        }
                    } else {
                        // Non-rectangular or with holes: containment test.
                        let exterior: Vec<Coord<f64>> = ext_coords
                            .iter()
                            .map(|&(x, y)| Coord { x: x as f64, y: y as f64 })
                            .collect();
                        let interiors: Vec<LineString<f64>> = hole_rings
                            .iter()
                            .map(|hr| {
                                LineString::from(
                                    hr.iter()
                                        .map(|&(x, y)| Coord {
                                            x: x as f64,
                                            y: y as f64,
                                        })
                                        .collect::<Vec<_>>(),
                                )
                            })
                            .collect();
                        let poly =
                            GeoPoly::new(LineString::from(exterior), interiors);
                        let xs: Vec<f32> =
                            ext_coords.iter().map(|c| c.0).collect();
                        let ys: Vec<f32> =
                            ext_coords.iter().map(|c| c.1).collect();
                        let bx0 = xs.iter().cloned().fold(f32::MAX, f32::min);
                        let by0 = ys.iter().cloned().fold(f32::MAX, f32::min);
                        let bx1 = xs.iter().cloned().fold(f32::MIN, f32::max);
                        let by1 = ys.iter().cloned().fold(f32::MIN, f32::max);
                        let tx0 = ((bx0 / CELL) as i32).max(0);
                        let ty0 = ((by0 / CELL) as i32).max(0);
                        let tx1 = ((bx1 / CELL) as i32 + 1).min(width);
                        let ty1 = ((by1 / CELL) as i32 + 1).min(height);
                        for ty in ty0..ty1 {
                            for tx in tx0..tx1 {
                                let cx = tx as f64 * CELL as f64
                                    + CELL as f64 / 2.0;
                                let cy = ty as f64 * CELL as f64
                                    + CELL as f64 / 2.0;
                                if poly.contains(&Point::new(cx, cy)) {
                                    result.insert((tx, ty));
                                }
                            }
                        }
                    }
                }
            }
            OutlineKind::Circle => {
                let cx = outline.cx();
                let cy = outline.cy();
                let r = outline.rx();
                if r <= 0.0 {
                    continue;
                }
                let tx0 = ((cx - r) / CELL).floor() as i32;
                let ty0 = ((cy - r) / CELL).floor() as i32;
                let tx1 = ((cx + r) / CELL).ceil() as i32;
                let ty1 = ((cy + r) / CELL).ceil() as i32;
                let r2 = r * r;
                for ty in ty0..ty1 {
                    for tx in tx0..tx1 {
                        if tx < 0 || tx >= width || ty < 0 || ty >= height {
                            continue;
                        }
                        let tcx = tx as f32 * CELL + CELL / 2.0;
                        let tcy = ty as f32 * CELL + CELL / 2.0;
                        let dx = tcx - cx;
                        let dy = tcy - cy;
                        if dx * dx + dy * dy <= r2 {
                            result.insert((tx, ty));
                        }
                    }
                }
            }
            OutlineKind::Pill => {
                let cx = outline.cx();
                let cy = outline.cy();
                let rx = outline.rx();
                let ry = outline.ry();
                if rx <= 0.0 || ry <= 0.0 {
                    continue;
                }
                let tx0 = (((cx - rx) / CELL) as i32).max(0);
                let ty0 = (((cy - ry) / CELL) as i32).max(0);
                let tx1 = (((cx + rx) / CELL) as i32 + 1).min(width);
                let ty1 = (((cy + ry) / CELL) as i32 + 1).min(height);
                for ty in ty0..ty1 {
                    for tx in tx0..tx1 {
                        let tcx = tx as f32 * CELL + CELL / 2.0;
                        let tcy = ty as f32 * CELL + CELL / 2.0;
                        if tcx >= cx - rx
                            && tcx <= cx + rx
                            && tcy >= cy - ry
                            && tcy <= cy + ry
                        {
                            result.insert((tx, ty));
                        }
                    }
                }
            }
            _ => {}
        }
    }

    result
}

/// Compute the set of tile coords covered by Building regions.
///
/// Mirrors `_building_footprint_tiles` in `ir_to_svg.py`. Returns
/// `None` when no Building regions are present (so the corridor handler
/// knows not to apply the filter at all).
fn building_footprint_tiles(
    fir: &FloorIR<'_>,
    width: i32,
    height: i32,
) -> Option<std::collections::HashSet<(i32, i32)>> {
    use geo::{Contains, Coord, LineString, Point, Polygon as GeoPoly};

    let regions = fir.regions()?;
    let mut result = std::collections::HashSet::new();
    let mut found_any = false;

    for i in 0..regions.len() {
        let region = regions.get(i);
        if region.kind() != RegionKind::Building {
            continue;
        }
        found_any = true;
        let poly_fb = match region.polygon() {
            Some(p) => p,
            None => continue,
        };
        // Reconstruct coords from Polygon.paths / rings.
        let paths = match poly_fb.paths() {
            Some(p) => p,
            None => continue,
        };
        if paths.is_empty() {
            continue;
        }
        let ring: Vec<Coord<f64>> = paths
            .iter()
            .map(|v| Coord { x: v.x() as f64, y: v.y() as f64 })
            .collect();
        let poly = GeoPoly::new(LineString::from(ring.clone()), vec![]);
        let xs: Vec<f64> = ring.iter().map(|c| c.x).collect();
        let ys: Vec<f64> = ring.iter().map(|c| c.y).collect();
        let bx0 = xs.iter().cloned().fold(f64::MAX, f64::min);
        let by0 = ys.iter().cloned().fold(f64::MAX, f64::min);
        let bx1 = xs.iter().cloned().fold(f64::MIN, f64::max);
        let by1 = ys.iter().cloned().fold(f64::MIN, f64::max);
        let tx0 = ((bx0 / CELL as f64) as i32).max(0);
        let ty0 = ((by0 / CELL as f64) as i32).max(0);
        let tx1 = ((bx1 / CELL as f64) as i32 + 1).min(width);
        let ty1 = ((by1 / CELL as f64) as i32 + 1).min(height);
        for ty in ty0..ty1 {
            for tx in tx0..tx1 {
                let cx = tx as f64 * CELL as f64 + CELL as f64 / 2.0;
                let cy = ty as f64 * CELL as f64 + CELL as f64 / 2.0;
                if poly.contains(&Point::new(cx, cy)) {
                    result.insert((tx as i32, ty as i32));
                }
            }
        }
    }

    if found_any { Some(result) } else { None }
}

#[cfg(test)]
mod tests {
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, CorridorWallOp, CorridorWallOpArgs,
        ExteriorWallOp, ExteriorWallOpArgs, FloorIR, FloorIRArgs, FloorOp,
        FloorOpArgs, FloorStyle, Op, OpEntry, OpEntryArgs, Outline, OutlineArgs,
        OutlineKind, TileCoord, Vec2, WallStyle,
    };
    use crate::test_util::{decode, pixel_at};
    use crate::transform::png::{floor_ir_to_png, BG_B, BG_G, BG_R};

    /// Build a minimal IR with:
    /// - FloorOp covering tiles [1..5, 3..5] (corridor tiles)
    /// - DungeonInk ExteriorWallOp (just the gate — no actual outline needed)
    /// - CorridorWallOp with one tile at (3, 3)
    ///
    /// The CorridorWallOp handler is gated by `has_dungeon_ink_wall_ops`
    /// which requires both a CorridorWallOp AND a DungeonInk ExteriorWallOp.
    fn build_corridor_wall_op_buf(corridor_tiles: &[(i32, i32)]) -> Vec<u8> {
        let cell = 32.0_f32;
        let mut fbb = FlatBufferBuilder::new();

        // FloorOp: 2×2 tile polygon floor covering [1,1]..[3,3]
        let floor_verts = fbb.create_vector(&[
            Vec2::new(1.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 3.0 * cell),
            Vec2::new(1.0 * cell, 3.0 * cell),
        ]);
        let floor_outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(floor_verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let floor_op = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(floor_outline),
                style: FloorStyle::DungeonFloor,
                region_ref: None,
            },
        );
        let floor_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(floor_op.as_union_value()),
            },
        );

        // DungeonInk ExteriorWallOp (just provides the gate signal).
        let ext_verts = fbb.create_vector(&[
            Vec2::new(1.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 3.0 * cell),
            Vec2::new(1.0 * cell, 3.0 * cell),
        ]);
        let ext_outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(ext_verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let ext_op = ExteriorWallOp::create(
            &mut fbb,
            &ExteriorWallOpArgs {
                outline: Some(ext_outline),
                style: WallStyle::DungeonInk,
                ..Default::default()
            },
        );
        let ext_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::ExteriorWallOp,
                op: Some(ext_op.as_union_value()),
            },
        );

        // CorridorWallOp with the given tiles.
        let tiles: Vec<TileCoord> = corridor_tiles
            .iter()
            .map(|&(x, y)| TileCoord::new(x, y))
            .collect();
        let tiles_vec = fbb.create_vector(&tiles);
        let corridor_op = CorridorWallOp::create(
            &mut fbb,
            &CorridorWallOpArgs {
                tiles: Some(tiles_vec),
                style: WallStyle::DungeonInk,
            },
        );
        let corridor_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::CorridorWallOp,
                op: Some(corridor_op.as_union_value()),
            },
        );

        let ops = fbb.create_vector(&[floor_entry, ext_entry, corridor_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    /// CorridorWallOp emits per-tile edge strokes for non-walkable
    /// neighbours. A corridor tile at (4, 4) (outside the floor area
    /// [1..3, 1..3]) should emit walls on all four of its edges since
    /// none of its neighbours are walkable.
    #[test]
    fn corridor_wall_op_emits_per_tile_edges() {
        // Tile (4, 4) is outside the FloorOp rect [1..3, 1..3].
        let buf = build_corridor_wall_op_buf(&[(4, 4)]);
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);

        // Top edge of tile (4,4): canvas y = 32 + 4*32 = 160,
        // x midpoint = 32 + 4.5*32 = 176.
        let (r, g, b) = pixel_at(&pixmap, 176, 160);
        assert_ne!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "top edge of isolated corridor tile should be painted"
        );

        // Bottom edge: y = 32 + 5*32 = 192.
        let (r2, g2, b2) = pixel_at(&pixmap, 176, 192);
        assert_ne!(
            (r2, g2, b2),
            (BG_R, BG_G, BG_B),
            "bottom edge of isolated corridor tile should be painted"
        );
    }

    /// When the DungeonInk consumer is NOT active (no DungeonInk
    /// ExteriorWallOp), the CorridorWallOp handler must not emit
    /// anything (legacy wall_segments still cover those walls).
    #[test]
    fn corridor_wall_op_silent_when_dungeon_ink_not_active() {
        let mut fbb = FlatBufferBuilder::new();

        // Only CorridorWallOp — no DungeonInk ExteriorWallOp.
        let tiles = fbb.create_vector(&[TileCoord::new(4, 4)]);
        let corridor_op = CorridorWallOp::create(
            &mut fbb,
            &CorridorWallOpArgs {
                tiles: Some(tiles),
                style: WallStyle::DungeonInk,
            },
        );
        let corridor_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::CorridorWallOp,
                op: Some(corridor_op.as_union_value()),
            },
        );

        let ops = fbb.create_vector(&[corridor_entry]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        let buf = fbb.finished_data().to_vec();
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);

        // Without the guard being satisfied, nothing should be painted.
        // Every pixel should be BG.
        let (r, g, b) = pixel_at(&pixmap, 176, 160);
        assert_eq!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "corridor wall should NOT paint when DungeonInk gate is not satisfied"
        );
    }

    /// A corridor tile adjacent to a walkable tile does NOT emit a wall
    /// on the shared edge.
    ///
    /// Layout:
    /// - FloorOp A covers tiles [1..3, 1..3] (room to the left).
    /// - FloorOp B covers tiles [4..6, 1..2] (small room; makes (4,1)
    ///   walkable — the north neighbour of the corridor tile).
    /// - ExteriorWallOp wraps FloorOp A (tiles [1..3, 1..3]) in pixel
    ///   coords 32..96. Its boundary is far from tile (4,*).
    /// - CorridorWallOp has a single tile at (4, 2).
    ///
    /// Expected:
    /// - North edge of (4,2) at canvas (176, 96): NO stroke (neighbour
    ///   (4,1) is walkable via FloorOp B).
    /// - South edge of (4,2) at canvas (176, 128): stroke IS present
    ///   (neighbour (4,3) is void).
    #[test]
    fn corridor_wall_op_no_wall_at_walkable_neighbour() {
        let cell = 32.0_f32;
        let mut fbb = FlatBufferBuilder::new();

        // FloorOp A: room at tiles [1..3, 1..3] (pixel 32..96, 32..96).
        let floor_verts_a = fbb.create_vector(&[
            Vec2::new(1.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 3.0 * cell),
            Vec2::new(1.0 * cell, 3.0 * cell),
        ]);
        let floor_outline_a = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(floor_verts_a),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let floor_op_a = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(floor_outline_a),
                style: FloorStyle::DungeonFloor,
                region_ref: None,
            },
        );
        let floor_entry_a = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(floor_op_a.as_union_value()),
            },
        );

        // FloorOp B: small room at tiles [4..6, 1..2] (pixel 128..192, 32..64).
        // Makes tile (4,1) walkable — the north neighbour of the corridor tile.
        let floor_verts_b = fbb.create_vector(&[
            Vec2::new(4.0 * cell, 1.0 * cell),
            Vec2::new(6.0 * cell, 1.0 * cell),
            Vec2::new(6.0 * cell, 2.0 * cell),
            Vec2::new(4.0 * cell, 2.0 * cell),
        ]);
        let floor_outline_b = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(floor_verts_b),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let floor_op_b = FloorOp::create(
            &mut fbb,
            &FloorOpArgs {
                outline: Some(floor_outline_b),
                style: FloorStyle::DungeonFloor,
                region_ref: None,
            },
        );
        let floor_entry_b = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::FloorOp,
                op: Some(floor_op_b.as_union_value()),
            },
        );

        // DungeonInk ExteriorWallOp wrapping FloorOp A only (stays in
        // pixel range 32..96; its boundary never touches tile (4,*)).
        let ext_verts = fbb.create_vector(&[
            Vec2::new(1.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 1.0 * cell),
            Vec2::new(3.0 * cell, 3.0 * cell),
            Vec2::new(1.0 * cell, 3.0 * cell),
        ]);
        let ext_outline = Outline::create(
            &mut fbb,
            &OutlineArgs {
                vertices: Some(ext_verts),
                closed: true,
                descriptor_kind: OutlineKind::Polygon,
                ..Default::default()
            },
        );
        let ext_op = ExteriorWallOp::create(
            &mut fbb,
            &ExteriorWallOpArgs {
                outline: Some(ext_outline),
                style: WallStyle::DungeonInk,
                ..Default::default()
            },
        );
        let ext_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::ExteriorWallOp,
                op: Some(ext_op.as_union_value()),
            },
        );

        // CorridorWallOp with tile (4, 2).
        // North neighbour (4,1) is walkable via FloorOp B → no north wall.
        // South neighbour (4,3) is void → south wall painted.
        let tiles = fbb.create_vector(&[TileCoord::new(4, 2)]);
        let corridor_op = CorridorWallOp::create(
            &mut fbb,
            &CorridorWallOpArgs {
                tiles: Some(tiles),
                style: WallStyle::DungeonInk,
            },
        );
        let corridor_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::CorridorWallOp,
                op: Some(corridor_op.as_union_value()),
            },
        );

        let ops = fbb.create_vector(&[
            floor_entry_a,
            floor_entry_b,
            ext_entry,
            corridor_entry,
        ]);
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 3,
                minor: 1,
                width_tiles: 8,
                height_tiles: 8,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ops: Some(ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        let buf = fbb.finished_data().to_vec();
        let png = floor_ir_to_png(&buf, 1.0, None).expect("render");
        let pixmap = decode(&png);

        // North edge of tile (4,2):
        //   canvas y = padding + 2*cell = 32 + 64 = 96
        //   canvas x_mid = padding + 4.5*cell = 32 + 144 = 176
        // Tile (4,1) is walkable → CorridorWallOp must NOT paint this edge.
        // The ExteriorWallOp outline (pixel 32..96) does not reach x=176.
        let (r, g, b) = pixel_at(&pixmap, 176, 96);
        assert_eq!(
            (r, g, b),
            (BG_R, BG_G, BG_B),
            "north edge of corridor tile adjacent to walkable tile should remain BG"
        );

        // South edge of tile (4,2):
        //   canvas y = padding + 3*cell = 32 + 96 = 128
        //   canvas x_mid = 176
        // Tile (4,3) is void → CorridorWallOp MUST paint this edge.
        let (r2, g2, b2) = pixel_at(&pixmap, 176, 128);
        assert_ne!(
            (r2, g2, b2),
            (BG_R, BG_G, BG_B),
            "south edge of corridor tile away from walkable should be painted"
        );
    }
}
