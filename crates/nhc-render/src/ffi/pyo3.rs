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

use crate::perlin;
use crate::primitives;
use crate::rng::SplitMix64;

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

/// Walls + floors layer — partial port. Structural geometry
/// (smooth-room outlines, cave region paths, wall extension
/// computations) stays Python-side and travels in via the
/// pre-rendered SVG fragment strings; only the stroke-emission
/// envelope (rect emission, the `/>`-replacement injection of
/// fill/stroke attributes around the cave region) lives here.
///
/// See `crates/nhc-render/src/primitives/walls_and_floors.rs`
/// for the per-input contract.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn draw_walls_and_floors(
    corridor_tiles: Vec<(i32, i32)>,
    rect_rooms: Vec<(i32, i32, i32, i32)>,
    smooth_fills: Vec<String>,
    cave_region: &str,
    smooth_walls: Vec<String>,
    wall_extensions_d: &str,
    wall_segments: Vec<String>,
) -> Vec<String> {
    primitives::walls_and_floors::draw_walls_and_floors(
        &corridor_tiles,
        &rect_rooms,
        &smooth_fills,
        cave_region,
        &smooth_walls,
        wall_extensions_d,
        &wall_segments,
    )
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
    m.add_function(wrap_pyfunction!(draw_walls_and_floors, m)?)?;
    m.add_function(wrap_pyfunction!(draw_hatch_corridor, m)?)?;
    m.add_function(wrap_pyfunction!(draw_hatch_room, m)?)?;
    m.add_function(wrap_pyfunction!(draw_floor_detail, m)?)?;
    m.add_function(wrap_pyfunction!(draw_thematic_detail, m)?)?;
    m.add_function(wrap_pyfunction!(draw_cobblestone, m)?)?;
    m.add_function(wrap_pyfunction!(draw_brick, m)?)?;
    m.add_function(wrap_pyfunction!(draw_flagstone, m)?)?;
    m.add_function(wrap_pyfunction!(draw_opus_romano, m)?)?;
    m.add_function(wrap_pyfunction!(draw_field_stone, m)?)?;
    Ok(())
}
