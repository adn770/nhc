//! PyO3 binding stub.
//!
//! Exposes the Rust crate as a Python extension module named
//! `nhc_render`. Module surface grows primitive-by-primitive per
//! `plans/nhc_ir_migration_plan.md` Phase 3+. Today:
//! `splitmix64_next` (Phase 0.3 sentinel), `perlin2` (Phase 3
//! cross-language gate), `draw_floor_grid` (Phase 3 canary
//! primitive), `draw_terrain_tints` (Phase 4.1 first
//! deterministic primitive), and the shadow family
//! (`draw_corridor_shadows` + `draw_room_shadow_{rect,octagon,
//! cave}`, Phase 4.2).
//!
//! Only compiled when the `pyo3` feature is on — disabled for
//! WASM builds and for `cargo test`-without-features.

use std::collections::HashMap;

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;

use crate::perlin;
use crate::primitives;
use crate::rng::SplitMix64;
use crate::transform::png as transform_png;
use crate::transform::svg as transform_svg;

/// Pull the next splitmix64 output for a given seed.
///
/// One-call helper rather than a stateful Python class — the IR
/// emitter is the only consumer right now and it materialises a
/// fresh stream per primitive. A class wrapper can land later if
/// streaming becomes the bottleneck.
#[pyfunction]
fn splitmix64_next(seed: u64) -> u64 {
    SplitMix64::from_seed(seed).next_u64()
}

/// 2D Perlin noise — same call shape as `nhc.rendering._perlin.pnoise2`.
///
/// Byte-equal to the Python reference; the cross-language gate is
/// `tests/fixtures/perlin/pnoise2_vectors.json` (Phase 0.6).
#[pyfunction]
#[pyo3(signature = (x, y, base = 0))]
fn perlin2(x: f64, y: f64, base: i32) -> f64 {
    perlin::pnoise2(x, y, base)
}

/// Floor-grid layer — Phase 3 canary primitive.
///
/// Returns `(room_d, corridor_d)`: the joined `d=` attribute
/// strings for the two `<path>` buckets. The Python handler at
/// `nhc/rendering/ir_to_svg.py:_draw_floor_grid_from_ir` wraps
/// these in `<path>` elements and adds the dungeon-interior clip
/// envelope when the IR's `clip_region` resolves.
///
/// `tiles` is a list of `(x, y, is_corridor)` triples in the IR's
/// y-major iteration order. The byte-equal parity gate lives at
/// `tests/unit/test_emit_floor_grid_parity.py` — drift on either
/// the Rust or Python side fails it before any SVG fixture
/// notices.
#[pyfunction]
fn draw_floor_grid(
    width_tiles: i32,
    height_tiles: i32,
    tiles: Vec<(i32, i32, bool)>,
    seed: u64,
) -> (String, String) {
    primitives::floor_grid::draw_floor_grid(
        width_tiles,
        height_tiles,
        &tiles,
        seed,
    )
}

/// Terrain-tints layer — Phase 4.1, first deterministic Phase 4
/// port.
///
/// Returns `(tint_rects, wash_rects)`: two lists of formatted
/// `<rect>` strings. The Python handler at
/// `ir_to_svg.py:_draw_terrain_tint_from_ir` stitches them into
/// the layer fragment, wrapping `tint_rects` in the dungeon-
/// interior clip envelope when the IR carries one.
///
/// The palette is resolved Python-side (the colour table at
/// `nhc/rendering/terrain_palette.py` is display data, not
/// procedural logic) and crossed via the four `(tint, opacity)`
/// pairs in the schema's enum order (`Water`, `Grass`, `Lava`,
/// `Chasm`). The byte-equal parity gate lives at
/// `tests/unit/test_emit_terrain_tints_parity.py`.
#[pyfunction]
fn draw_terrain_tints(
    tiles: Vec<(i32, i32, u8)>,
    palette: HashMap<u8, (String, f64)>,
    washes: Vec<(i32, i32, i32, i32, String, f64)>,
) -> (Vec<String>, Vec<String>) {
    primitives::terrain_tints::draw_terrain_tints(
        &tiles, &palette, &washes,
    )
}

/// Per-tile corridor shadow rects.
///
/// Returns a list of `<rect>` strings — one per tile, with the
/// `+3` offset and `0.08` opacity baked in. The Python handler
/// at `ir_to_svg.py:_draw_shadow_from_ir` walks the IR's
/// `op.tiles` and crosses the FFI boundary with a flat list.
#[pyfunction]
fn draw_corridor_shadows(tiles: Vec<(i32, i32)>) -> Vec<String> {
    primitives::shadow::draw_corridor_shadows(&tiles)
}

/// Rect-shape room shadow — single `<rect>` with bbox baked in.
#[pyfunction]
fn draw_room_shadow_rect(coords: Vec<(f64, f64)>) -> String {
    primitives::shadow::draw_room_shadow_rect(&coords)
}

/// Octagon-shape room shadow — `<polygon>` wrapped in
/// `<g transform="translate(3,3)">`.
#[pyfunction]
fn draw_room_shadow_octagon(coords: Vec<(f64, f64)>) -> String {
    primitives::shadow::draw_room_shadow_octagon(&coords)
}

/// Cave-shape room shadow — Catmull-Rom-smoothed `<path>`
/// wrapped in `<g transform="translate(3,3)">`.
#[pyfunction]
fn draw_room_shadow_cave(coords: Vec<(f64, f64)>) -> String {
    primitives::shadow::draw_room_shadow_cave(&coords)
}

/// Stairs layer — per-stair tapering wedge + step lines, with an
/// optional cave-theme fill polygon when `theme == "cave"`.
///
/// Returns one SVG element per polygon / line in the legacy emit
/// order: cave-fill (if theme matches) → top rail → bottom rail
/// → 6 step lines. Eight or nine elements per stair total.
#[pyfunction]
fn draw_stairs(
    stairs: Vec<(i32, i32, u8)>,
    theme: &str,
    fill_color: &str,
) -> Vec<String> {
    primitives::stairs::draw_stairs(&stairs, theme, fill_color)
}

/// Hatch corridor halo — Phase 4 sub-step 1.d.
///
/// Returns `(tile_fills, hatch_lines, hatch_stones)`: three SVG
/// fragment buckets the Python handler at
/// `ir_to_svg.py:_draw_hatch_corridor` wraps in the legacy
/// `<g opacity="...">` envelopes. `tiles` is the IR's pre-sorted
/// halo tile list; `seed` already includes the legacy `+7`
/// offset (set on emit at `_floor_layers.py:_emit_hatch_ir`).
#[pyfunction]
fn draw_hatch_corridor(
    tiles: Vec<(i32, i32)>,
    seed: u64,
) -> (Vec<String>, Vec<String>, Vec<String>) {
    primitives::hatch::draw_hatch_corridor(&tiles, seed)
}

/// Hatch room halo — Phase 4 sub-step 1.d.
///
/// Returns `(tile_fills, hatch_lines, hatch_stones)`. `tiles` is
/// the candidate set produced emit-side at sub-step 1.b (post-
/// Perlin distance filter, row-major); `is_outer` runs parallel
/// to it (cave-aware `dist > base_distance_limit*0.5` flag) and
/// gates the 10 % RNG skip Rust-side so the consumer doesn't
/// reconstruct dist.
#[pyfunction]
fn draw_hatch_room(
    tiles: Vec<(i32, i32)>,
    is_outer: Vec<bool>,
    seed: u64,
) -> (Vec<String>, Vec<String>, Vec<String>) {
    primitives::hatch::draw_hatch_room(&tiles, &is_outer, seed)
}

/// Floor-detail layer — Phase 4 sub-step 3.d.
///
/// Returns `(room_groups, corridor_groups)`: two lists of `<g>`
/// envelope strings (cracks / scratches / stones, in legacy
/// emit order). The dispatcher at
/// `ir_to_svg.py:_draw_floor_detail_from_ir` splats them into
/// the layer fragment. `tiles` is the IR's post-filter candidate
/// set produced emit-side at sub-step 3.b: `(x, y, is_corridor)`
/// triples in y-major / x-minor order. `seed` already includes
/// the legacy `+99` offset.
#[pyfunction]
fn draw_floor_detail(
    tiles: Vec<(i32, i32, bool)>,
    seed: u64,
    theme: &str,
    macabre: bool,
) -> (Vec<String>, Vec<String>) {
    primitives::floor_detail::draw_floor_detail(
        &tiles, seed, theme, macabre,
    )
}

/// Flagstone decorator — Phase 4 sub-step 8.
///
/// 4 irregular pentagon plates per tile, ``<g>`` opacity 0.35
/// with grey-brown stroke. `tiles` is the FLAGSTONE-surface
/// tile list; `seed` already includes the `+333` decorator
/// offset.
#[pyfunction]
fn draw_flagstone(tiles: Vec<(i32, i32)>, seed: u64) -> Vec<String> {
    primitives::flagstone::draw_flagstone(&tiles, seed)
}

/// Opus-romano decorator — Phase 4 sub-step 9.
///
/// 4-stone Versailles tiling per tile (one 4×4 square, one 2×4
/// vertical, one 2×2 small, one 4×2 horizontal), with a per-
/// tile coordinate-derived rotation. RNG-free.
#[pyfunction]
fn draw_opus_romano(tiles: Vec<(i32, i32)>, seed: u64) -> Vec<String> {
    primitives::opus_romano::draw_opus_romano(&tiles, seed)
}

/// Field-stone decorator — Phase 4 sub-step 10.
///
/// 10 % per-tile probabilistic single ellipse (green stone)
/// for FIELD-surface GRASS tiles.
#[pyfunction]
fn draw_field_stone(
    tiles: Vec<(i32, i32)>, seed: u64,
) -> Vec<String> {
    primitives::field_stone::draw_field_stone(&tiles, seed)
}

/// Cart-tracks decorator — Phase 4 sub-step 11.
///
/// Two parallel rails + one cross-tie per TRACK tile, with
/// per-tile horizontal / vertical orientation pre-resolved by
/// the emitter. Returns up to two ``<g>`` envelopes (rails +
/// ties).
#[pyfunction]
fn draw_cart_tracks(
    tiles: Vec<(i32, i32, bool)>, seed: u64,
) -> Vec<String> {
    primitives::cart_tracks::draw_cart_tracks(&tiles, seed)
}

/// Ore-deposit decorator — Phase 4 sub-step 12. One diamond
/// glint per ore-deposit wall tile.
#[pyfunction]
fn draw_ore_deposit(
    tiles: Vec<(i32, i32)>, seed: u64,
) -> Vec<String> {
    primitives::ore_deposit::draw_ore_deposit(&tiles, seed)
}

/// Tree surface feature — Phase 4 sub-step 15.
///
/// `free_trees` is the singletons / pair-tree tile list (each
/// painted as an individual tree with trunk + canopy).
/// `groves` is the list of groves of size ≥ 3 (each painted as
/// one fused fragment without trunks). Grove detection is
/// computed Python-side. Returns one fragment per free tree +
/// one fragment per grove.
#[pyfunction]
fn draw_tree(
    free_trees: Vec<(i32, i32)>,
    groves: Vec<Vec<(i32, i32)>>,
) -> Vec<String> {
    primitives::tree::draw_tree(&free_trees, &groves)
}

/// Bush surface feature — Phase 4 sub-step 16.
///
/// Multi-lobe canopy + shadow with HLS-jittered fill colour.
/// Lobe-circle union via the `geo` crate's BooleanOps under the
/// relaxed parity gate (vertex ordering / numerical precision
/// differs from Shapely; structural-invariants gate accepted).
#[pyfunction]
fn draw_bush(tiles: Vec<(i32, i32)>) -> Vec<String> {
    primitives::bush::draw_bush(&tiles)
}

/// Fountain surface feature — Phase 4 sub-step 14.
///
/// `shape` matches the FB FountainShape enum:
/// 0 = Round (2x2), 1 = Square (2x2),
/// 2 = LargeRound (3x3), 3 = LargeSquare (3x3),
/// 4 = Cross (3x3 plus). Returns one ``<g>`` envelope per
/// tile, byte-equal to the legacy Python painters.
#[pyfunction]
fn draw_fountain(tiles: Vec<(i32, i32)>, shape: u8) -> Vec<String> {
    primitives::fountain::draw_fountain(&tiles, shape)
}

/// Well surface feature — Phase 4 sub-step 13.
///
/// `shape` selects the variant: 0 = Round (16 keystone arcs +
/// circular water disc), 1 = Square (rectangular rim + square
/// pool). Returns one ``<g>`` envelope per tile, byte-equal to
/// the legacy Python painter (``_well_fragment_for_tile`` /
/// ``_square_well_fragment_for_tile``).
#[pyfunction]
fn draw_well(tiles: Vec<(i32, i32)>, shape: u8) -> Vec<String> {
    primitives::well::draw_well(&tiles, shape)
}

/// Brick decorator — Phase 4 sub-step 7.
///
/// 4×2 running-bond brick layout, ``<g>`` opacity 0.35 with
/// brick-red stroke. `tiles` is the BRICK-surface tile list;
/// `seed` already includes the `+333` decorator offset.
#[pyfunction]
fn draw_brick(tiles: Vec<(i32, i32)>, seed: u64) -> Vec<String> {
    primitives::brick::draw_brick(&tiles, seed)
}

/// Cobblestone decorator — Phase 4 sub-step 6.
///
/// Returns a list of `<g>` envelope strings: the cobblestone
/// grid (3×3 jittered rects per tile, opacity 0.35) and an
/// optional cobble-stone group (opacity 0.5 ellipses, 12 % per
/// tile). The dispatcher at
/// `ir_to_svg.py:_draw_decorator_from_ir` splats them into the
/// floor_detail layer fragment. `tiles` is the cobble-tile list
/// produced emit-side at the cobble candidate walk; `seed`
/// already includes the legacy `+333` decorator-pipeline offset.
#[pyfunction]
fn draw_cobblestone(tiles: Vec<(i32, i32)>, seed: u64) -> Vec<String> {
    primitives::cobblestone::draw_cobblestone(&tiles, seed)
}

/// Thematic-detail layer — Phase 4 sub-step 4.d.
///
/// Returns `(room_groups, corridor_groups)`: two lists of `<g>`
/// envelope strings (`detail-webs` / `detail-bones` /
/// `detail-skulls` in legacy emit order). The dispatcher at
/// `ir_to_svg.py:_draw_thematic_detail_from_ir` splats them
/// into the layer fragment. `tiles` is the IR's candidate set
/// from sub-step 4.b: `(x, y, is_corridor, wall_corners)`
/// quadruples where `wall_corners` is the 4-bit
/// `TL/TR/BL/BR` bitmap produced emit-side. `seed` already
/// includes the legacy `+199` offset.
#[pyfunction]
fn draw_thematic_detail(
    tiles: Vec<(i32, i32, bool, u8)>,
    seed: u64,
    theme: &str,
    macabre: bool,
) -> (Vec<String>, Vec<String>) {
    primitives::thematic_detail::draw_thematic_detail(
        &tiles, seed, theme, macabre,
    )
}

/// IR → PNG raster — Phase 5.1.1 envelope.
///
/// Reads a `FloorIR` FlatBuffer and returns the rasterised PNG
/// bytes. `scale` multiplies the SVG-equivalent canvas size; the
/// `.png` web endpoint passes 1.0 to match the legacy `resvg-py`
/// rendering. `layer` (when not None) dispatches a single named
/// layer — the parity harness in `tests/unit/test_ir_png_parity.py`
/// uses this to gate per-primitive 5.2 / 5.3 / 5.4 commits one
/// layer at a time. Phase 5.1.1 paints the BG envelope; per-
/// primitive commits add op handlers without changing the
/// signature.
#[pyfunction]
#[pyo3(signature = (ir_bytes, scale = 1.0, layer = None))]
fn ir_to_png(
    ir_bytes: &[u8],
    scale: f32,
    layer: Option<&str>,
) -> PyResult<Vec<u8>> {
    transform_png::floor_ir_to_png(ir_bytes, scale, layer)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// SVG → PNG rasteriser — Phase 10.4 cross-rasteriser parity
/// gate. The parity harness in `tests/unit/test_ir_png_parity.py`
/// pipes `ir_to_svg(buf)` through this function and compares the
/// resulting pixels against the reference image, replacing the
/// legacy `resvg-py` Python wheel. Production code never calls
/// this — the `.png` endpoint flows straight through
/// `ir_to_png` from the IR buffer.
#[pyfunction]
fn svg_to_png(svg: &str) -> PyResult<Vec<u8>> {
    transform_svg::svg_to_png(svg)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// IR → SVG document — Phase 2.17 envelope.
///
/// Reads a `FloorIR` FlatBuffer and returns a complete SVG
/// document string. Mirrors `ir_to_png`'s argument shape:
/// `scale` multiplies the canvas dimensions (1.0 matches the
/// legacy emitter's natural canvas), `layer` (when not None)
/// dispatches a single named layer through the same
/// `transform::png::layer_ops` map the PNG entry point uses.
/// Wraps `crate::transform::svg::floor_ir_to_svg` for the
/// Python-side `ir_to_svg.py` consumers as the Painter-trait
/// migration moves SVG generation across the FFI boundary.
#[pyfunction]
#[pyo3(signature = (ir_bytes, scale = 1.0, layer = None))]
fn ir_to_svg(
    ir_bytes: &[u8],
    scale: f32,
    layer: Option<&str>,
) -> PyResult<String> {
    transform_svg::floor_ir_to_svg(ir_bytes, scale, layer)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// PyO3 module entry point. The function name MUST match the
/// `[lib] name` in Cargo.toml (`nhc_render`) so Python's
/// import machinery finds it.
#[pymodule]
fn nhc_render(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(splitmix64_next, m)?)?;
    m.add_function(wrap_pyfunction!(perlin2, m)?)?;
    m.add_function(wrap_pyfunction!(draw_floor_grid, m)?)?;
    m.add_function(wrap_pyfunction!(draw_terrain_tints, m)?)?;
    m.add_function(wrap_pyfunction!(draw_corridor_shadows, m)?)?;
    m.add_function(wrap_pyfunction!(draw_room_shadow_rect, m)?)?;
    m.add_function(wrap_pyfunction!(draw_room_shadow_octagon, m)?)?;
    m.add_function(wrap_pyfunction!(draw_room_shadow_cave, m)?)?;
    m.add_function(wrap_pyfunction!(draw_stairs, m)?)?;
    m.add_function(wrap_pyfunction!(draw_hatch_corridor, m)?)?;
    m.add_function(wrap_pyfunction!(draw_hatch_room, m)?)?;
    m.add_function(wrap_pyfunction!(draw_floor_detail, m)?)?;
    m.add_function(wrap_pyfunction!(draw_thematic_detail, m)?)?;
    m.add_function(wrap_pyfunction!(draw_cobblestone, m)?)?;
    m.add_function(wrap_pyfunction!(draw_brick, m)?)?;
    m.add_function(wrap_pyfunction!(draw_flagstone, m)?)?;
    m.add_function(wrap_pyfunction!(draw_opus_romano, m)?)?;
    m.add_function(wrap_pyfunction!(draw_field_stone, m)?)?;
    m.add_function(wrap_pyfunction!(draw_cart_tracks, m)?)?;
    m.add_function(wrap_pyfunction!(draw_ore_deposit, m)?)?;
    m.add_function(wrap_pyfunction!(draw_well, m)?)?;
    m.add_function(wrap_pyfunction!(draw_fountain, m)?)?;
    m.add_function(wrap_pyfunction!(draw_bush, m)?)?;
    m.add_function(wrap_pyfunction!(draw_tree, m)?)?;
    m.add_function(wrap_pyfunction!(ir_to_png, m)?)?;
    m.add_function(wrap_pyfunction!(svg_to_png, m)?)?;
    m.add_function(wrap_pyfunction!(ir_to_svg, m)?)?;
    Ok(())
}
