# Floor IR — multi-runtime rendering with a canonical Rust core

Design for replacing direct SVG emission of dungeon / building / site floors
with a compact intermediate representation (IR) plus three pluggable
transformers: server-side **IR → SVG** (Python), server-side **IR → PNG**
(Rust), and client-side **IR → Canvas** (Rust compiled to WASM). All three
share one canonical procedural-primitive core implemented in a Rust crate;
splitmix64 RNG and Perlin noise live in that crate, so the
"Python and JS must produce bit-exact RNG output" parity headache goes
away by construction.

This is a forward-looking reference. The first preparatory work
(FlatBuffers schema, parity fixtures, Rust crate skeleton, resvg-py
stepping stone) can land incrementally; full IR cutover is gated by the
preparatory tasks listed in `plans/nhc_ir_migration_plan.md`.

## 1. Status & vision

### Status (2026-04-27)

The rendering refactor that this design depends on is **mostly complete**:

- `nhc/rendering/_render_context.py` — frozen `RenderContext` resolves
  floor kind (dungeon / cave / building / surface) plus feature flags
  (shadows, hatching, atmospherics, macabre detail, vegetation,
  interior-finish) once per render.
- `nhc/rendering/_pipeline.py` — `Layer`, `TileWalkLayer`, and the
  `render_layers(ctx, layers)` orchestrator.
- `nhc/rendering/_decorators.py` — `TileDecorator` contract,
  `walk_and_paint`, per-decorator seeded RNG.
- `nhc/rendering/_floor_layers.py` — ordered `FLOOR_LAYERS` registry
  of nine layers (shadows, hatching, walls_and_floors, terrain_tints,
  floor_grid, floor_detail, terrain_detail, stairs, surface_features).
- `nhc/rendering/svg.py` — `render_floor_svg` is now a thin shell
  around `build_render_context` + `render_layers(FLOOR_LAYERS)`.

The op vocabulary has grown from the original ten-op sketch to roughly
**thirty primitives** (trees with grove merging, bushes, wells in two
shapes, fountains in five variants, cobblestone in five variants, wood
floor as a `TileDecorator` with a `requires` gate, cart tracks, ore
deposits, GARDEN→GRASS overlay, FIELD overlay, building interior walls,
masonry runs, roofs, enclosures, doors). The IR schema below covers all
of them.

### Vision

```
              ┌──────────────────────────────────────┐
              │     FloorIR (FlatBuffers binary)     │
              │   structural regions + procedural    │
              │      ops + theme + version field     │
              └────────────────┬─────────────────────┘
                               │
              ┌────────────────┼────────────────────┐
              ▼                ▼                    ▼
       IR → SVG           IR → PNG             IR → Canvas
       (Python)           (Rust)               (Rust → WASM)
       cold paths /       gameplay cache /     gameplay hot
       export / debug     archival / share     path in browser
              │                │                    │
              └─────── shared procedural core ──────┘
                       Rust crate `nhc-render`:
                       splitmix64 RNG, Perlin noise,
                       primitive emitters, tiny-skia
                       rasterizer
                          ┌──────────┴──────────┐
                          ▼                     ▼
                   PyO3 bindings          wasm-bindgen
                   (server-side)          (browser-side)
```

The three transformers and Python all read the same FlatBuffers
buffer; the procedural primitives have one implementation that runs
in three embeddings (PyO3 native, WASM, host-Rust).

## 2. Principles

- **One canonical procedural source.** Every primitive — cross-hatch,
  per-tile rolls, vegetation jitter, cobblestone tiling, fountain
  shapes — is implemented exactly once, in Rust. Python loses its
  procedural-emission code over the migration; the JS side never
  grows one.
- **Structural vs procedural separation.** Region polygons (rooms,
  caves, building footprints, dungeon polygon for clipping) carry as
  baked coordinates because Shapely's union is prohibitive to reproduce
  client-side. Decoration is `(region_ref, seed, params)`; the renderer
  regenerates it deterministically.
- **Python keeps Shapely.** GEOS is already C-fast, the Python wrapper
  is small overhead, and porting Shapely to Rust is a year's worth of
  yak-shaving. The crate accepts pre-computed polygons as inputs.
- **FlatBuffers for the wire.** Schema-versioned, zero-copy on the
  client, smaller wire than JSON, generates idiomatic bindings for
  Python, Rust, and TypeScript. Debuggability cost mitigated by a
  one-shot `ir_to_json.py` dumper for humans.
- **Bit-exact determinism by construction.** Same IR → same pixels in
  every embedding. There is no "Python/JS port parity" because there
  is no Python procedural port and no JS procedural port — only
  embeddings of the Rust crate.
- **Phased migration with strict-TDD parity gates.** Every step gates
  on a parity fixture so the legacy Python emitter and the new
  Rust-via-PyO3 emitter can coexist while we move from one to the
  other.

## 3. Problem (revised)

Two pain points motivate the rework:

1. **Wire size.** Per-floor SVG runs 60–250 KB raw, ~20–70 KB gzipped
   (`web_client.py:1309`). Most bytes are decoration baked into long
   `<path d="…">` attributes. Add a tileable hatch SVG (~100 KB,
   fetched once per session). Target: 3–8 KB gzipped FlatBuffers IR
   plus a one-time WASM bundle (~150–300 KB after `wasm-opt`,
   gzip-compressed, served once).
2. **Server CPU.** Shapely runs regardless (cave union, dungeon
   polygon, grove merging). Python-side procedural detail (Perlin
   wobble, floor stones, hatching, fountains, vegetation jitter) is
   stringification-bound. Moving procedural emission into Rust
   reclaims that path; on the gameplay route the server only has to
   assemble the IR (small dataclass+FB serialise) and the client
   paints. Long-tail goal: 40–60 % drop in per-floor server CPU.

A new motivation versus the prior design:

3. **Server-side PNG.** Some clients (LLM image-mode tools, archival
   exports, share-a-map links) want a raster. We currently do not
   serve PNG. Rust-side rasterisation via `tiny-skia` from the IR is
   the long-term answer; `resvg-py` over IR→SVG is the cheap stepping
   stone.

A **zero-cost check before any IR work** still applies: confirm the
Flask endpoint at `nhc/web/app.py` is gzipped behind Caddy. SVG
compresses 3–5× with gzip alone.

## 4. Decisions

| Decision | Choice |
|---|---|
| IR wire format | **FlatBuffers** (`.fbs` schema in `nhc/rendering/ir/floor_ir.fbs`) |
| Canonical procedural source | **Rust crate** `nhc-render` (one impl, two embeddings) |
| Python integration | **PyO3** native module, distributed as wheel for linux x86_64 (server) and macOS arm64 (dev) |
| Browser integration | **wasm-bindgen + wasm-pack**, JS glue calls into WASM |
| Server PNG path | **Long-term: Rust + tiny-skia**; **stepping stone: resvg-py over IR→SVG** |
| PRNG | **splitmix64** (in Rust; PyO3 + WASM each expose the same wrapper) |
| Perlin noise | **Ported to Rust** with checked-in fixture vectors; both embeddings call the same impl |
| SVG role post-cutover | **Cold paths only** (export, /admin debug, regression fixtures) |
| Phase-1 parity gate | **Byte-equal SVG** between legacy `render_floor_svg` and `ir_to_svg(build_floor_ir(...))` |
| Determinism guarantee | **Rust-canonical** — three embeddings, one implementation; no cross-runtime port-drift class of bugs |
| IR scope | **Floor-scoped** (dungeon / cave / building / surface). Site overlays (roofs, enclosures, masonry) compose above the floor IR via the existing `building.py` / `site_svg.py` wrappers |
| Hex / overland IR | **Out of scope** — separate IR work if needed |
| Schedule | **Preparatory work starts now** (FB schema, fixture harness, resvg-py PNG); full Rust integration follows incrementally |

## 5. The IR (FlatBuffers)

### Why FlatBuffers (not JSON)

- **Smaller wire** before gzip (typical 30–50 % reduction for our
  geometry-heavy IR), comparable after gzip; **zero-copy reads** on
  the client mean the WASM Canvas renderer never allocates parser
  state.
- **Schema discipline by default.** Schema lives in version control
  alongside generated bindings; backward-compatible additions (new
  optional fields, new ops appended to a vector) need no client code
  change.
- **Cross-language bindings** for Python (`flatbuffers` package),
  Rust (`flatbuffers` crate), and TypeScript (`flatbuffers` npm) are
  all first-party.
- **Debuggability cost** offset by `nhc/rendering/ir/dump.py`, which
  prints any IR buffer as canonicalised JSON for humans (and for git-
  reviewable test fixtures).

### Schema sketch (`nhc/rendering/ir/floor_ir.fbs`)

```
namespace nhc.ir;

// Schema major version is the file's `file_identifier`; minor version
// is a uint32 field on the root table. Renderers dispatch on major;
// minor allows additive changes (new optional fields, new op kinds).
file_identifier "NIRF";          // NHC IR Floor v1
file_extension "nir";            // .nir file extension

table Vec2 { x: float; y: float; }

table Polygon {
  paths: [Vec2];   // flat list, separated by Path entries
  rings: [PathRange];
}

struct PathRange { start: uint32; count: uint32; is_hole: bool; }

enum RegionKind: byte {
  Dungeon = 0,
  Cave = 1,
  Room = 2,
  Building = 3,
  Site = 4,
}

table Region {
  id: string (key);
  kind: RegionKind;
  polygon: Polygon;
  shape_tag: string;        // "rect"|"octagon"|"circle"|"pill"|"temple"|"hybrid"|"cave"
}

table TileCoord { x: int; y: int; tag: string; }     // tag for typed buckets

enum FloorKind: byte { Dungeon = 0, Cave = 1, Building = 2, Surface = 3 }

table FeatureFlags {
  shadows_enabled: bool = true;
  hatching_enabled: bool = true;
  atmospherics_enabled: bool = true;
  macabre_detail: bool = false;
  vegetation_enabled: bool = true;
  interior_finish: string;   // "" | "wood" | "flagstone" | …
}

union Op {
  ShadowOp,
  HatchOp,
  WallsAndFloorsOp,
  TerrainTintOp,
  FloorGridOp,
  FloorDetailOp,
  TerrainDetailOp,
  StairsOp,
  CobblestoneOp,
  WoodFloorOp,
  GardenOverlayOp,
  FieldOverlayOp,
  CartTracksOp,
  OreDepositsOp,
  TreeFeatureOp,
  BushFeatureOp,
  WellFeatureOp,
  FountainFeatureOp,
  ThematicDetailOp,
  GenericProceduralOp,    // escape hatch for additive primitives
}

table FloorIR {
  major: uint32;          // schema major (gates renderers)
  minor: uint32;          // schema minor (additive)
  width_tiles: uint32;
  height_tiles: uint32;
  cell: uint32 = 32;
  padding: uint32 = 32;
  floor_kind: FloorKind;
  theme: string;          // "dungeon"|"crypt"|"cave"|"sewer"|"castle"|"forest"|"abyss"|"settlement"|...
  base_seed: uint64;
  flags: FeatureFlags;
  regions: [Region];
  ops: [Op];
}

root_type FloorIR;
```

Each `*Op` table carries the parameters its renderer needs; see §7
for the full op catalogue. Ops appear in the buffer in **layer-order**
(see §6) so the renderer streams ops linearly with no sort step.

### Versioning policy

- **Minor bump (1.x → 1.y)** — additive: new op-union variants, new
  optional fields on existing ops, new theme strings, new region
  shape tags. Old renderers ignore unknown union members (FlatBuffers
  semantics) and render the rest. Ship freely.
- **Major bump (1.x → 2.0)** — breaking: renamed ops, removed fields,
  changed op semantics, changed layer ordering. Both transformers
  (Python SVG, Rust PNG, Rust→WASM Canvas) must accept both versions
  for one release cycle.
- The buffer's `file_identifier` encodes major version. Major bumps
  also bump the `.fbs` file's `file_identifier`.
- `save_svg_cache` cache keys include `(major, minor)` so a version
  bump invalidates old caches cleanly.

## 6. Layer ordering

The IR carries ops in the same sequence as the legacy SVG layers, so
Phase 1 byte-equal parity holds and PNG / Canvas renderers can stream
with no sort step:

| Order | Layer name | Op kinds |
|---|---|---|
| 100 | shadows | `ShadowOp` (room, corridor) |
| 200 | hatching | `HatchOp` (room, hole, corridor) |
| 300 | walls_and_floors | `WallsAndFloorsOp` |
| 350 | terrain_tints | `TerrainTintOp` |
| 400 | floor_grid | `FloorGridOp` |
| 500 | floor_detail | `FloorDetailOp`, `ThematicDetailOp`, `CobblestoneOp`, `WoodFloorOp`, `GardenOverlayOp`, `FieldOverlayOp`, `CartTracksOp`, `OreDepositsOp` |
| 600 | terrain_detail | `TerrainDetailOp` |
| 700 | stairs | `StairsOp` |
| 800 | surface_features | `WellFeatureOp`, `FountainFeatureOp`, `TreeFeatureOp`, `BushFeatureOp` |

Order numbers preserve gaps of 50 between adjacent layers so future
primitives can slot in without re-numbering.

## 7. Op catalogue

Every op has (a) a FlatBuffers table shape, (b) a deterministic
contract — what is seeded, what parameters drive output, and the
exact RNG call sequence — and (c) a reference implementation path. To
keep this doc readable, the FB tables are summarised; a normative
spec lives in `design/ir_primitives.md` (a sibling file generated
from the `.fbs` schema plus per-op call-sequence notes).

### 7.1 ShadowOp

Renders room and corridor drop-shadows.

```
table ShadowOp {
  kind: ShadowKind;        // Room | Corridor
  region_ref: string;      // for Room kind (region id)
  tiles: [TileCoord];      // for Corridor kind (per-tile)
  dx: float = 3.0;
  dy: float = 3.0;
  opacity: float = 0.08;
}
```

Reference: `_shadows.py:_render_room_shadows`,
`_render_corridor_shadows`. Deterministic — no RNG.

### 7.2 HatchOp

Cross-hatched halo with section partitioning, Perlin-jittered strokes,
0–2 seeded stones per tile.

```
table HatchOp {
  kind: HatchKind;         // Room | Hole | Corridor
  region_out: string;      // exclusion region (e.g. "dungeon")
  region_in: string;       // hatched region (for Room/Hole)
  tiles: [TileCoord];      // for Corridor
  extent_tiles: float = 2.0;
  seed: uint64;            // base_seed + 77 (room) | + 7 (corridor) | hole-specific
  stride: float = 0.5;
  hatch_underlay_color: string;
}
```

Reference: `_hatching.py:_render_hatching`,
`_render_corridor_hatching`, `_render_hole_hatching`. Section
partitioning depends on `_dungeon_polygon._build_sections`; the
section anchor + boundary polygons are baked into the op so the
renderer does no Shapely work, only stroke generation.

### 7.3 WallsAndFloorsOp

Filled room outlines (smooth-shape rooms), rect-room floor fills,
corridor floor tiles, cave region (filled polygon + stroke), and the
combined wall-segment path.

```
table WallsAndFloorsOp {
  smooth_room_regions: [string];     // region ids of octagon/circle/pill/temple
  rect_rooms: [RectRoom];
  corridor_tiles: [TileCoord];
  cave_region: string;               // region id, empty if no cave
  wall_segments: [string];           // SVG path 'd' fragments — could become structured later
  floor_color: string;
  cave_floor_color: string;
  wall_color: string;
  wall_width: float;
  building_footprint: [TileCoord];   // optional, gates wall-segment emission near chamfer
}
```

Reference: `_walls_floors.py:_render_walls_and_floors`. Deterministic.

### 7.4 TerrainTintOp

Per-tile coloured rect tints (water/grass/lava/chasm) clipped to
dungeon interior, plus room-type washes.

```
table TerrainTintOp {
  tiles: [TerrainTintTile];          // (x, y, terrain_kind)
  room_washes: [RoomWash];           // (rect, color, opacity)
  clip_region: string;
}
```

Reference: `_terrain_detail.py:_render_terrain_tints`. Deterministic.

### 7.5 FloorGridOp

Wobbly grid (Perlin-displaced) at `cell`-tile spacing, theme-scaled.

```
table FloorGridOp {
  clip_region: string;
  seed: uint64;
  theme: string;
  scale: float;            // _DETAIL_SCALE[theme]
}
```

Reference: `_floor_detail.py:_render_floor_grid` +
`_svg_helpers.py:_wobbly_grid_seg`. Per-theme scale: dungeon 1.0,
crypt 2.0, cave 2.0, sewer 1.0, castle 0.8, forest 0.6, abyss 1.5.

### 7.6 FloorDetailOp

Per-tile cracks, scratches, stones, clusters. Theme-keyed
probabilities live in `_floor_detail._DETAIL_SCALE`.

```
table FloorDetailOp {
  tiles: [TileCoord];
  seed: uint64;            // base_seed + 99
  theme: string;
}
```

Reference: `_floor_detail.py:_render_floor_detail`, `_tile_detail`,
`_floor_stone`. Per-tile rolls: crack (0.08 dungeon / 0.32 cave * theme
scale), scratch (0.05 / 0.01), stone (0.06 / 0.10), cluster (0.03 /
0.06).

### 7.7 ThematicDetailOp

Per-tile webs, bone piles, skulls. Probabilities in
`_THEMATIC_DETAIL_PROBS`.

```
table ThematicDetailOp {
  tiles: [TileCoord];
  seed: uint64;            // base_seed + 199
  theme: string;
}
```

Reference: `_floor_detail.py:_tile_thematic_detail`, `_web_detail`,
`_bone_detail`, `_skull_detail`. Webs prefer wall-corner anchors.

### 7.8 TerrainDetailOp

Per-tile water ripples, lava cracks, chasm hatch. (Grass blade
emission was dropped — commit `35660d6`; grass shows only the flat
tint emitted by `TerrainTintOp`.)

```
table TerrainDetailOp {
  tiles: [TileCoord];      // (x, y, terrain_kind, is_corridor)
  seed: uint64;            // base_seed + 200
  theme: string;
  clip_region: string;
}
```

Reference: `_terrain_detail.py:_render_terrain_detail` +
`_water_detail`, `_lava_detail`, `_chasm_detail`.

### 7.9 StairsOp

Tapering wedges, per-direction step lines, optional cave fill.

```
table StairsOp {
  stairs: [StairTile];     // (x, y, "up"|"down")
  theme: string;
  fill_color: string;      // active when theme == "cave"
}
```

Reference: `_stairs_svg.py:_render_stairs`. Deterministic shape per
direction.

### 7.10 CobblestoneOp

Street tiles with a soft hex-offset stone pack. Variants:
`brick`, `flagstone`, `herringbone`, `opus_reticulatum`,
`versailles_4stone`.

```
table CobblestoneOp {
  tiles: [TileCoord];
  seed: uint64;            // base_seed + 333
  theme: string;
  pattern: CobblePattern;  // Brick | Flagstone | Herringbone | OpusReticulatum | Versailles4
}
```

Reference: `_floor_detail.py:_render_street_cobblestone` +
`_cobblestone_tile` per pattern.

### 7.11 WoodFloorOp

Wood-grain plank fill with a `requires` gate (only emitted when
`flags.interior_finish == "wood"`). Clipped to `building_polygon`
when present so planks reach the chamfer diagonal, not the bbox edge.

```
table WoodFloorOp {
  tiles: [TileCoord];
  seed: uint64;
  theme: string;
  building_polygon: [Vec2];      // optional clip
}
```

Reference: `_floor_detail.py:_wood_floor_*`.

### 7.12 GardenOverlayOp / FieldOverlayOp

Surface-tile overlays. Garden tiles render as the GRASS overlay
(commit `4499326`); FIELD overlays sit on town periphery (commit
`7dfa0c9`).

```
table GardenOverlayOp { tiles: [TileCoord]; seed: uint64; theme: string; }
table FieldOverlayOp  { tiles: [TileCoord]; seed: uint64; theme: string; }
```

### 7.13 CartTracksOp / OreDepositsOp

Decorator-driven surface markings (commits `7dfa0c9`,
`b64f03a`).

```
table CartTracksOp  { tiles: [TileCoord]; seed: uint64; }
table OreDepositsOp { tiles: [TileCoord]; seed: uint64; theme: string; }
```

### 7.14 TreeFeatureOp / BushFeatureOp

Cartographer-style vegetation. Trees: layered canopy with per-tile hue
jitter + grove merging via Shapely union for 3+ adjacent trees (the
union polygon is baked into the op so the renderer does no Shapely
work). Bushes: smaller canopy, no trunk.

```
table TreeFeatureOp {
  tiles: [TileCoord];
  seed: uint64;
  theme: string;
  groves: [GrovePolygon];  // baked union polygons for 3+ adjacent groups
}

table BushFeatureOp {
  tiles: [TileCoord];
  seed: uint64;
  theme: string;
}
```

Reference: `_features_svg.py:TREE_FEATURE`, `BUSH_FEATURE`,
`_connected_tree_groves`, `_grove_fragment`.

### 7.15 WellFeatureOp / FountainFeatureOp

Wells in two shapes (round, square). Fountains in five variants
(round, square, large round, large square, cross). All carry per-tile
seeded rolls for stone shape jitter.

```
enum WellShape { Round, Square }

table WellFeatureOp {
  tiles: [TileCoord];
  shape: WellShape;
  seed: uint64;
  theme: string;
}

enum FountainShape { Round, Square, LargeRound, LargeSquare, Cross }

table FountainFeatureOp {
  tiles: [TileCoord];
  shape: FountainShape;
  seed: uint64;
  theme: string;
}
```

Reference: `_features_svg.py:WELL_FEATURE`, `WELL_SQUARE_FEATURE`,
`FOUNTAIN_FEATURE`, `FOUNTAIN_SQUARE_FEATURE`,
`FOUNTAIN_LARGE_FEATURE`, `FOUNTAIN_LARGE_SQUARE_FEATURE`,
`FOUNTAIN_CROSS_FEATURE`.

### 7.16 GenericProceduralOp (escape hatch)

For new primitives that haven't yet earned their own table. Carries
`(name: string, tiles, seed, params: [KV])`. Renderers dispatch on
`name` to a registered handler. Use sparingly — promote to a
dedicated table once the primitive stabilises.

### 7.17 What the IR does NOT cover

Site / building overlays (composed *above* the floor IR by the
existing `building.py`, `site_svg.py` wrappers):

- Roofs (`_roofs.py:building_roof_fragments`) — site overlay
- Enclosures (`_enclosures.py`: palisade, fortification) — site
  overlay
- Building exterior masonry (`_building_walls.py`: brick / stone
  runs) — building overlay
- Doors (`_doors_svg.py`) — composed by callers as a separate canvas
  layer in the web client

These compose cleanly above any of the three transformer outputs and
do not benefit from being in the floor IR (they don't change the
"floor canvas" rasterisation).

## 8. The Rust crate `nhc-render`

### Module layout

```
crates/nhc-render/
├── Cargo.toml
├── src/
│   ├── lib.rs              # re-exports
│   ├── ir.rs               # FB-generated IR + thin wrappers
│   ├── rng.rs              # splitmix64 wrapper
│   ├── perlin.rs           # noise port (parity-fixture-tested)
│   ├── primitives/         # one module per op
│   │   ├── shadow.rs
│   │   ├── hatch.rs
│   │   ├── walls.rs
│   │   ├── floor_grid.rs
│   │   ├── floor_detail.rs
│   │   ├── terrain.rs
│   │   ├── stairs.rs
│   │   ├── cobblestone.rs
│   │   ├── wood_floor.rs
│   │   ├── vegetation.rs    # tree, bush
│   │   ├── well.rs
│   │   └── fountain.rs
│   ├── transform/          # IR-driven backends
│   │   ├── png.rs           # tiny-skia rasteriser (host-Rust + PyO3)
│   │   ├── canvas.rs        # canvas2d command stream (WASM)
│   │   └── svg.rs           # optional Rust SVG path (parity / fallback)
│   └── ffi/
│       ├── pyo3.rs          # Python bindings (cfg = "pyo3")
│       └── wasm.rs          # wasm-bindgen exports (cfg = "wasm")
```

### What lives in Rust

- **PRNG**: splitmix64 with a single `Rng::from_seed(seed)` constructor.
- **Perlin noise**: port of `noise.pnoise2` byte-for-byte, with
  fixture vectors in `tests/fixtures/perlin/` checked in both Python
  and Rust.
- **All procedural primitives** for every op in §7 (except the
  structural geometry — see "What stays in Python" below).
- **Three transformer back-ends**:
  - `png`: drives `tiny-skia` to produce a `Pixmap` (single-binary,
    no system deps, portable across linux x86_64 and macOS arm64).
  - `canvas`: emits a stream of canvas2d commands for the JS shim
    to replay (`fillRect`, `stroke`, `bezierCurveTo`, …) — keeps
    the JS bridge minimal and avoids per-call WASM↔JS overhead.
  - `svg` (optional): a Rust SVG emitter for parity testing
    against the Python emitter. Not strictly necessary for
    production but useful for diff tests.

### What stays in Python

- **Shapely-driven structural geometry** —
  `_dungeon_polygon`, `_cave_geometry`, `_room_outlines`. These
  produce `Polygon` and friends; the IR emitter walks the geometry
  and bakes coordinate arrays into FB Region tables. Porting Shapely
  to Rust is not on the critical path; GEOS is already C-fast.
- **The IR emitter** (`build_floor_ir`) — a Python pipeline of stage
  functions that walks the `Level` model and emits ops in layer
  order. Each stage is small and pickle-free; the heavy lifting it
  delegates is either (a) Shapely (unchanged) or (b) Rust crate
  primitive emission (when a stage simply needs a list of `(x, y,
  seed)` to feed to Rust later).

### PyO3 bindings (`ffi/pyo3.rs`)

Exposed as a Python module `nhc_render` (built and shipped as part
of the Python package). API surface:

```python
import nhc_render

# Rasterise a FlatBuffers IR buffer to PNG bytes.
png_bytes = nhc_render.ir_to_png(ir_bytes, scale=1.0)

# Replay an IR buffer through the Rust SVG transformer (parity test).
svg_str = nhc_render.ir_to_svg(ir_bytes)

# Standalone primitive primitives (used during the migration as the
# Python emitter migrates each layer one at a time):
nhc_render.draw_floor_grid(out_buf, region_polygon, seed, theme)
nhc_render.draw_hatch(out_buf, region_polygon, region_out_polygon,
                      seed, extent_tiles, stride)
# … etc, one per primitive
```

Wheels built via `maturin` for the two supported platforms:
**linux x86_64** (production server) and **macOS arm64** (Apple
Silicon dev). Linux aarch64 (single-board ARM) and macOS x86_64
(Intel Macs) and Windows can wait until somebody asks; the build
matrix and Cargo features are structured so adding a target is one
config-line change.

### WASM bindings (`ffi/wasm.rs`)

Exposed via `wasm-bindgen` and packaged with `wasm-pack` as
`nhc_render_wasm` (npm-installable, vendored into
`nhc/web/static/wasm/`). API surface:

```js
import init, { renderIRToCanvas, renderIRToCommands } from
  "/static/wasm/nhc_render_wasm.js";

await init();   // one-time WASM module load

// Direct path: pass the FB buffer + a Canvas2D context. Rust drives
// the canvas via the canvas2d command stream and JS is a thin
// dispatcher.
renderIRToCanvas(irBuffer, canvasCtx, hatchPattern);

// Alternate path: get the command stream as a typed array, replay in
// JS at this turn or buffer for later.
const cmds = renderIRToCommands(irBuffer);
replay(cmds, canvasCtx, hatchPattern);
```

The JS shim (~50 lines in `floor_ir_renderer.js`) translates command
opcodes into Canvas2D calls; everything else is in Rust.

## 9. Three transformer paths

### 9.1 IR → SVG (Python, cold path)

Lives at `nhc/rendering/ir_to_svg.py`. Iterates ops, calls per-op
`_draw_*_from_ir` helpers that string-build SVG fragments. Used for:

- `/admin` debug visualisation.
- Test parity gates (every other transformer is checked against
  the Python SVG output during migration).
- Export endpoints (`/api/game/<sid>/export/map_svg`).
- Eventually, a Rust port (`transform/svg.rs`) replaces the Python
  one as the parity gates close. Until then, the Python emitter is
  the legacy path that the new code must match.

This transformer must remain Python-only for the duration of the
migration; it's the reference implementation we diff against.

### 9.2 IR → PNG (Rust via PyO3, server path)

`nhc_render.ir_to_png(ir_bytes, scale)` returns PNG bytes. Used for:

- Cached raster fallback for clients that can't render WASM.
- Image-mode LLM tools that consume PNG.
- Share-a-map endpoints.

Two sub-phases:

1. **Stepping stone (no Rust required yet):** `ir_to_svg` →
   `resvg-py` → PNG. Adds ~5 ms per render, ~28 MB transient memory
   for an 80×60 floor at 1× scale. Lets us ship PNG
   delivery before the Rust crate is mature.
2. **Long-term:** `nhc_render.ir_to_png` direct, no SVG intermediate.
   `tiny-skia` rasteriser on a `Pixmap`, ~2 ms typical, ~6 MB
   transient.

### 9.3 IR → Canvas (Rust via WASM, client path)

`renderIRToCanvas(irBuffer, ctx, hatchPattern)` is the gameplay hot
path. The canvas overlay layers (door / hatch / fog / entity — see
`design/canvas_rendering.md`) are unchanged; only the floor layer
moves from "inline an SVG" to "paint via WASM."

Template change: `<div id="floor-svg">` → `<canvas
id="floor-canvas">`. `map.js`: `setFloorSVG` → `setFloorIR`. No other
JS layer changes.

## 10. Determinism contract

The promise the IR makes: **the same FB buffer rendered through any
of the three transformers produces visually identical output.** The
contract that makes this hold:

1. **Shared procedural source.** Every primitive lives once, in Rust.
   The Python `ir_to_svg` calls into Rust through PyO3 for procedural
   primitives (post-migration); the WASM transformer calls the same
   Rust functions; the PNG transformer calls the same Rust functions.
   There is no parallel Python or JS implementation.
2. **PRNG**: `splitmix64`, with all op seeds derived from `base_seed +
   per-op-salt`. Salts are constants in `crates/nhc-render/src/rng.rs`
   and listed in §7.
3. **Perlin**: ported once with checked-in fixture vectors. The
   parity gate is in `tests/fixtures/perlin/`; both the Python emitter
   side (which feeds Perlin-dependent silhouette geometry into the IR)
   and the Rust primitive side use the same impl.
4. **Op call sequence**: each op's `paint` function calls the RNG /
   Perlin in a specific order. That order is fixed by the Rust
   reference and documented in `design/ir_primitives.md`. There are
   no parallel implementations to drift.
5. **Float reproducibility**: Rust uses `f32` for procedural geometry
   (matches SVG floating-point precision) and `f64` only for
   structural Shapely-derived coordinates. PNG and Canvas use the
   same fp pipeline so anti-aliasing is identical to the cell.

This is a **strictly stronger guarantee than the previous design.**
The earlier doc carried the "Python and JS must match bit-for-bit"
parity worry as a top-3 risk; under the canonical-Rust architecture,
that class of bug is structurally impossible.

## 11. Endpoint surface

```
GET /api/game/<sid>/floor/<svg_id>.svg       # legacy, IR→SVG via Python
GET /api/game/<sid>/floor/<svg_id>.nir       # FlatBuffers IR (binary)
GET /api/game/<sid>/floor/<svg_id>.png       # IR→PNG via Rust+tiny-skia
GET /api/game/<sid>/floor/<svg_id>.json      # IR dumped as JSON (debug)
GET /api/hatch.svg                            # unchanged, shared session asset
```

The web client switches from `.svg` to `.nir`. The `.png` route
serves clients that don't run WASM (image-only LLM tools, share-map
links). The `.svg` route stays available for parity tests, exports,
and admin debug. The `.json` route is god-mode-gated and lets humans
read what the IR contains.

## 12. Phased plan

The migration is now eight phases, but the early phases are cheap and
unlock the rest. **Phases 0 – 3 can run in parallel with feature
work; the IR → Canvas cutover is the only phase that touches the
gameplay hot path.**

### Phase 0 — Preparatory (no gameplay change)

- Confirm gzip on the Flask floor endpoint (zero-cost win).
- Stand up the FB schema file at `nhc/rendering/ir/floor_ir.fbs`,
  generate Python + Rust + TS bindings.
- Stand up parity-fixture infrastructure: a `tests/fixtures/floor_ir/`
  tree with golden FB buffers + JSON dumps for a small set of
  canonical levels.
- Stand up the Rust crate skeleton (`crates/nhc-render/`) with no
  primitives yet — just the FB-generated IR, splitmix64 RNG,
  PyO3-wheel build, and a CI matrix for {linux x86_64, macos arm64}.
- Drop in `resvg-py` as the PNG rasterizer for the stepping-stone
  PNG endpoint. Doesn't need any Rust code yet.

### Phase 1 — IR emitter behind the existing signature

`render_floor_svg(level, seed, hatch_distance, …) -> str` keeps its
public shape. Internals:

```python
def render_floor_svg(level, seed=0, hatch_distance=2.0, …) -> str:
    ir = build_floor_ir(level, seed, hatch_distance, …)
    return ir_to_svg(ir)   # Python implementation
```

Each existing `_render_*` paint helper grows a sibling `_emit_*_ir`
that appends ops; the legacy SVG string-building moves into
`_draw_*_from_ir` dispatched by `ir_to_svg`. Zero behaviour change.

**Gate:** byte-equal SVG between `render_floor_svg` (legacy path)
and `ir_to_svg(build_floor_ir(...))` on every fixture in
`tests/fixtures/floor_ir/`.

### Phase 2 — `.nir` and `.json` endpoints + IR cache

Expose `/api/game/<sid>/floor/<id>.nir` and `.json`. Extend
`save_svg_cache` to cache IR buffers alongside SVG. No client change
yet — these endpoints are observable but not consumed.

**Gate:** all three serialised forms (.svg, .nir, .json) round-trip
to byte-equal SVG.

### Phase 3 — First primitive in Rust

Pick one self-contained primitive — `floor_grid` is a good first
target (small, no Shapely dependency, exercises Perlin) — and port
it to Rust. The Python emitter calls `nhc_render.draw_floor_grid(...)`
via PyO3 instead of doing the work in Python. PNG rasterisation
still uses `resvg-py`; Canvas doesn't exist yet.

**Gate:** for every fixture, the Python emitter with the Rust
primitive substituted produces byte-equal SVG to the legacy emitter.
This proves the splitmix64 RNG and Perlin port match the Python
reference.

This is the highest-risk phase from a determinism standpoint, so
Phase 3 ships **one** primitive. Once it's green, subsequent
primitives follow the same pattern with much lower risk.

### Phase 4 — Procedural primitives migrated to Rust

Iteratively port the rest of the procedural ops in §7 to Rust.
After each op moves, the Python emitter delegates that op's drawing
to Rust. The op order can prioritise highest-CPU primitives first
(hatch, floor_detail) to maximise the per-phase win.

**Gate (per op):** byte-equal SVG fixture parity. Once all are
green, the Python `_draw_*_from_ir` functions become wrappers around
Rust calls and can be deleted.

### Phase 5 — IR → PNG via `tiny-skia` (Rust direct)

`nhc_render.ir_to_png(ir_bytes, scale)` replaces the
`resvg-py`-via-SVG path. Faster, smaller transient memory. The PNG
endpoint switches over silently.

**Gate:** PNG-vs-PNG diff under `pixelmatch`-equivalent ≤ 0.5 %
against the `resvg-py` baseline.

### Phase 6 — IR → Canvas via WASM

Build the WASM bundle. Ship `floor_ir_renderer.js` (~50 lines that
load the WASM module and dispatch canvas2d commands).
`map.js`: `setFloorSVG` → `setFloorIR`. The other canvas overlays are
untouched. The server stops emitting `<g>...</g>` strings on the
gameplay path because the client now requests `.nir` instead of
`.svg`.

**Gate:** rasterised Canvas output (headless Chromium on the same
fixtures) matches Python `ir_to_svg` rasterised via `resvg-py`,
pixel-diff ≤ 0.5 %. Server CPU on a canonical floor: expect ≥ 40 %
drop vs Phase 0 baseline.

### Phase 7 — Deprecate legacy Python procedural code

With Phases 4 + 6 complete, every procedural primitive lives in
Rust. The Python `_render_*` paint helpers are now dead weight; they
get deleted. The IR emitter (`build_floor_ir`) and Shapely-driven
geometry stay in Python.

A ruff lint rule banning `import random` in `nhc/rendering/` makes
RNG-drift regressions impossible.

## 13. Critical files

### Existing — modified

- `nhc/rendering/svg.py` — `render_floor_svg` becomes
  `ir = build_floor_ir(level, ...); return ir_to_svg(ir)`.
- `nhc/rendering/_render_context.py` — emits `RenderContext` flags
  into the IR `FeatureFlags` table.
- `nhc/rendering/_floor_layers.py` — each `*_paint` helper grows an
  `*_emit_ir` sibling; over Phases 1–4, paint helpers become
  thin shims that consume IR ops produced by the emit siblings.
- `nhc/web/app.py` — adds `.nir`, `.png`, `.json` floor routes;
  extends `save_svg_cache`.
- `nhc/web/templates/play.html` — Phase 6: `<div id="floor-svg">` →
  `<canvas id="floor-canvas">`.
- `nhc/web/static/js/map.js` — Phase 6: `setFloorSVG` → `setFloorIR`.

### New — Python

- `nhc/rendering/ir/floor_ir.fbs` — FlatBuffers schema.
- `nhc/rendering/ir/__init__.py` — re-exports the generated bindings.
- `nhc/rendering/ir/dump.py` — IR → canonical-JSON dumper.
- `nhc/rendering/ir_emitter.py` — `build_floor_ir(level, …) -> bytes`
  pipeline of stage functions, one per layer.
- `nhc/rendering/ir_to_svg.py` — Phase-1 reference implementation;
  becomes a thin wrapper around `nhc_render.ir_to_svg` once
  `transform/svg.rs` lands.

### New — Rust

- `crates/nhc-render/Cargo.toml` — crate definition with `pyo3` and
  `wasm` feature gates.
- `crates/nhc-render/src/*` — see §8 module layout.
- `pyproject.toml` — `[tool.maturin]` build config.
- `crates/nhc-render-wasm/` — thin wrapper crate that reuses
  `nhc-render` with the `wasm` feature; produced as
  `wasm-pack build --target web`.
- `nhc/web/static/wasm/nhc_render_wasm{.js,_bg.wasm}` — vendored
  WASM artifact.
- `nhc/web/static/js/floor_ir_renderer.js` — JS shim that loads WASM
  and dispatches canvas2d commands.

### New — design

- `design/ir_primitives.md` — normative per-op spec: FlatBuffers
  shape, RNG-call sequence, parameters, reference implementation
  path. Generated from the `.fbs` schema plus per-op notes; used as
  the determinism reference.

## 14. Testing (strict TDD)

1. **`tests/unit/test_floor_ir.py`** — golden IR tests. For fixed
   `(level, seed)`, assert `build_floor_ir(...)` matches a
   committed FB buffer + JSON dump under `tests/fixtures/floor_ir/`.
2. **`tests/unit/test_ir_to_svg.py`** — byte-equal parity (Phase 1+).
   `ir_to_svg(ir) == render_floor_svg_legacy(...)`. Survives every
   later phase as the guardrail.
3. **`tests/unit/test_ir_rng.py`** — splitmix64 vectors and Perlin
   vectors checked across Python and Rust (via PyO3) and JS
   (via WASM headless harness).
4. **`tests/unit/test_ir_canvas_parity.py`** (`slow`, Phase 6) —
   rasterise IR via `nhc_render.ir_to_png` and via headless Chromium
   running the WASM Canvas renderer; pixel-diff ≤ 0.5 %.
5. **`tests/unit/test_ir_png_parity.py`** (`slow`, Phase 5) —
   `tiny-skia` PNG vs `resvg-py` PNG, pixel-diff ≤ 0.5 %.
6. **`tests/unit/test_ir_perf.py`** (`slow`) — p95 budgets on
   `build_floor_ir`, `ir_to_svg`, `ir_to_png`, WASM Canvas paint.
7. **`tests/samples/generate_svg.py`** — extend to emit
   `.svg`, `.nir`, `.json`, `.png` per fixture so visual inspection
   is one-stop.

WASM tests run via headless Chromium under pytest-playwright (or a
Node harness) so CI enforces parity without a live browser.

## 15. MCP debug tool interaction

Existing `get_svg_room_walls`, `get_svg_tile_elements` MCP tools
return SVG fragments. The IR exposes parallel tools that return op
slices and region polygons:

- `get_ir_region(region_id)` — region polygon + shape tag
- `get_ir_ops(op_kind=None)` — filtered op list with parameters
- `get_ir_buffer()` — full FB buffer + JSON dump for offline analysis
- `get_ir_diff(prev_buf, curr_buf)` — high-level structural diff
  (which regions changed, which ops added / removed) for debugging
  IR emission regressions

These land alongside the existing SVG tools in Phase 2. The SVG
tools stay available for backwards compatibility but are documented
as cold-path-only post-Phase-7.

## 16. Risks

| Risk | Mitigation |
|---|---|
| **WASM bundle size on first load.** Untrimmed Rust WASM can hit 2–3 MB; that's a lot for a roguelike. | `wasm-opt -Oz`, `wasm-snip` to drop unused panic infra, `wee_alloc` instead of default allocator. Target 200–400 KB gzipped. Cached after first load. |
| **Cross-platform wheel discipline.** Two targets today (linux x86_64 → manylinux_2_34, macOS arm64); easy for a wheel build to silently regress on one. | `cibuildwheel` runs both targets on every PR; smoke import test on each. Tagged releases cut wheels for both. The Docker base is `python:3.14-slim` (Debian bookworm, glibc 2.36) so manylinux_2_34 is the floor. |
| **`tiny-skia` feature gaps.** No SVG filter primitives, no shadow blur. | Our SVG decoration uses none of these (shadow is alpha rect, not Gaussian blur). Anti-aliased lines + filled polygons + gradients are all `tiny-skia` natives. |
| **PyO3 ABI breakage between Python versions.** | Build wheels for the supported Python versions (3.10–3.13 currently); `pyo3` abi3 mode pins one wheel per platform. |
| **WASM↔JS bridge overhead.** Each function call has FFI cost. | Use the canvas2d-command-stream design: one WASM call per render produces a typed-array of commands; JS replays in a tight loop. No per-primitive WASM↔JS hop. |
| **FlatBuffers schema evolution discipline.** Easy to break compat by reordering fields. | Schema review checklist; minor bumps go through additive-only review; major bumps require both transformers updated in lockstep. |
| **Determinism regression during Phase 4 migration.** Each op's port could reintroduce a subtle RNG-call-order drift. | Per-op SVG byte-equal parity gate; lint rule banning `random.Random` in `nhc/rendering/` post-migration. |
| **Disk cache invalidation on schema bumps.** | Cache key includes `(major, minor)`. |
| **Maturin / wasm-pack build complexity** for contributors. | `make rust-build` and `make wasm-build` Makefile targets; CI handles the matrix; document local setup in `CONTRIBUTING.md`. |

## 17. Success metrics

- **SVG path (Phases 1–4):** IR→SVG byte-equal to legacy
  `render_floor_svg` on every fixture.
- **IR wire size (Phase 2):** p95 `floor.nir` < 12 KB raw, < 4 KB
  gzipped.
- **PNG path (Phase 5):** server p95 ≤ 12 ms per floor at 1× scale
  on the deployment target (Intel Broadwell i5-5250U class, 2c/4t,
  AVX2, 15 GiB RAM); ≤ 60 ms at 2×. A datacenter-class CPU would
  comfortably halve those numbers — recalibrate if the server is
  ever upgraded.
- **Canvas path (Phase 6):** first-paint < 50 ms on a 2020-era laptop
  (Apple Silicon dev or comparable x86_64).
- **Server CPU (Phase 6):** per-floor render time on the gameplay
  hot path drops ≥ 40 % vs Phase 0 baseline (no decoration string
  emission).
- **WASM bundle:** < 400 KB gzipped after `wasm-opt -Oz`.

## 18. Extensibility patterns

(Carried over from the prior design — the IR is meant to absorb
world-expansion primitives without forcing rewrites.)

### Adding a new op

1. **Spec first.** Append a section to `design/ir_primitives.md` —
   FlatBuffers shape, determinism contract, reference implementation
   path. PR doesn't land without the spec.
2. **Schema entry.** Add a new variant to the `Op` union and a new
   table in `floor_ir.fbs`. Bump minor version.
3. **Rust primitive.** Implement in `crates/nhc-render/src/primitives/
   <name>.rs`. Reuse `rng.rs` and `perlin.rs`.
4. **Python emitter.** Add `_emit_<name>_ir` in the relevant helper
   module; wire into the `IR_STAGES` pipeline.
5. **Tests.** Golden IR fixture + SVG byte-equal parity (via Python
   `_draw_*_from_ir` calling Rust) + PNG parity + Canvas parity.

### Adding a new theme

Themes travel as a string parameter on relevant ops. To add one:

1. Add entry to `_DETAIL_SCALE` and `_THEMATIC_DETAIL_PROBS`
   (Python emitter tables) and to the matching Rust tables in
   `primitives/floor_grid.rs`, `primitives/floor_detail.rs`.
2. Add palette entry to `terrain_palette.py`.
3. Add fixtures for the new theme × representative shape.
4. Bump minor version.

Renderers treat unknown themes as `"dungeon"` (default fallback).

### Adding a new room shape

Shapes encode as polygons in the IR `regions` table — adding a shape
is **zero-IR-schema-change**. The new shape's vertex generator goes
in `_room_outlines.py`; the IR emitter automatically bakes the
polygon coordinates.

### Hook points in the emitter

`build_floor_ir(level, seed, ...)` is a pipeline:

```python
def build_floor_ir(level, seed, ...):
    builder = FloorIRBuilder(level, seed, ...)
    for stage in IR_STAGES:
        stage(builder)
    return builder.finish()    # returns FB bytes

IR_STAGES = [
    emit_regions,
    emit_shadows,
    emit_hatch,
    emit_walls_and_floors,
    emit_terrain_tints,
    emit_floor_grid,
    emit_floor_detail,        # includes thematic, cobblestone, wood, garden, field, cart_tracks, ore_deposits
    emit_terrain_detail,
    emit_stairs,
    emit_surface_features,    # wells, fountains, trees, bushes
]
```

World-expansion phases append new stages in their own PRs; layer
ordering is preserved.

### Theme-specific variants on existing ops

Prefer **new ops** over overloaded existing ones. If the new
behaviour is structurally distinct (different geometry, different
RNG sequence), give it its own table. Reserve theme-keyed parameter
overloading for cosmetic differences (color, scale).

### Deprecation

To remove an op:

1. Add the replacement op in version `1.x`. Emitter produces both
   for one release cycle.
2. Transformers accept both but log deprecation for the old op.
3. Remove the old op and bump major version.
4. Regenerate all fixtures.

## 19. Open questions

- **Is `tiny-skia` enough or do we need `skia-safe`?** `tiny-skia` is
  ~500 KB compiled, has no system deps, and covers our needs (lines,
  filled polygons, anti-aliasing, gradients, image patterns).
  `skia-safe` is heavier and links against the full Skia C++ engine.
  Default to `tiny-skia` until a primitive demands a feature it
  lacks.
- **Should IR cover hex / overland?** Out of scope for this design.
  If hex rendering ever wants the same canonical-Rust treatment, it
  gets its own IR file (`hex_ir.fbs`) and a separate transformer
  pipeline. The crate's RNG / Perlin / tiny-skia infrastructure is
  reusable.
- **Do we want a "lossy fast mode" on the cold-path SVG?** Skip
  decoration entirely for `/admin` debug views when humans just need
  the structural skeleton. Probably yes — a `?bare=1` query param
  toggles it.
- **Fixture granularity.** One fixture per shape × theme × seed, or
  one per shape × theme? Current guess: shape × theme (~45
  fixtures). Expand if debugging demands.
- **Browser support floor.** WASM + canvas2d is universal across
  modern browsers; do we drop IE11? (Yes.) Do we need a non-WASM
  fallback for ancient Android WebView? (Probably ship the PNG
  endpoint as the universal fallback and call it good.)

## Cross-references

- `design/canvas_rendering.md` — canvas overlay layers (door / hatch
  / fog / entity) that compose **above** the floor IR; unchanged by
  this design.
- `design/web_client.md` — endpoint surface, gunicorn / gevent
  concurrency model; new endpoints listed in §11.
- `design/debug_tools.md` — MCP debug tool surface; new IR-aware
  tools listed in §15.
- `design/views.md` — view dispatch; out of scope (the IR is
  rendered the same regardless of which view contains the canvas).
- `design/sites.md`, `design/biome_features.md`,
  `design/dungeon_generator.md`, `design/building_generator.md` —
  geometry producers; their `Level` outputs feed `build_floor_ir`
  unchanged.
- `plans/nhc_ir_migration_plan.md` — preparatory + per-phase TODO
  list to converge the codebase on this design.
