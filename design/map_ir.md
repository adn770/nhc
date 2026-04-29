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

### Status (2026-04-29)

The IR migration shipped through Phase 5 + Phase 7. Schema is at
major version **2.0** (Phase 7 cleanup retired the unused reserved
op-union variants and the empty Phase-1 transitional fields). The
`.png` endpoint is live for dungeon, cave, and dungeon-style
building floors via Rust + tiny-skia; the web client routes through
PNG with a transitional SVG fallback for site surfaces and
composite building floors.

- `nhc/rendering/_render_context.py` — frozen `RenderContext` resolves
  floor kind (dungeon / cave / building / surface) plus feature flags
  (shadows, hatching, atmospherics, macabre detail, vegetation,
  interior-finish) once per render.
- `nhc/rendering/ir_emitter.py` — Python emitter that builds a
  `FloorIR` FlatBuffer from a `Level` + `RenderContext`. The IR
  carries one op per layer; per-layer `_emit_*_ir` helpers in
  `_floor_layers.py` route per-shape data into structured ops.
- `nhc/rendering/ir_to_svg.py` — Python transformer; calls into the
  Rust crate `nhc-render` (PyO3) for the per-op procedural geometry
  and wraps the output in clip-path / dungeon-poly envelopes.
- `nhc/rendering/svg.py` — `render_floor_svg` is now a thin shell
  around `ir_to_svg(build_floor_ir(...))`.
- `crates/nhc-render/` — Rust core for procedural rendering
  (splitmix64 RNG, Perlin noise, per-primitive emitters). Exposed
  to Python via PyO3 (`nhc_render` wheel) and slated for WASM
  exposure in Phase 11.
- `nhc/rendering/_decorators.py` — `TileDecorator` contract +
  `walk_and_paint`. Two live callers remain (terrain-detail
  decorators + the wood-floor short-circuit); both pending their
  Rust ports in Phase 9. Slated for deletion at Phase 9.3.

The op vocabulary covers shadows, hatching, walls/floors, terrain
tints + detail, floor grid, floor detail (cracks / scratches /
stones), thematic detail (webs / bones / skulls), stairs, the
seven decorator variants (cobblestone / brick / flagstone /
opus_romano / field_stone / cart_tracks / ore_deposit) flowing
through `DecoratorOp`'s per-variant tables, plus the four surface
features (well / fountain / tree / bush). Total: 15 op-union
variants (counting `GenericProceduralOp` as the escape-hatch slot).

### Forward plan (Phases 8 – 11)

The closing arc of the migration converges every gameplay floor on
the IR pipeline as the only path that emits visuals, with three
switchable rasterisers downstream:

- **Phase 8 — structural composites through IR.** Roofs, enclosures
  (palisade / fortification), gates, and building walls (interior
  partitions + exterior masonry) move into the IR as new ops in a
  renamed `structural` layer (was `walls_and_floors`). Site surfaces
  and composite building floors stop hitting the SVG fallback because
  every structural shape is now expressible in the IR. Schema bumps
  2.0 → 2.1 → 2.2 → 2.3 (additive).
- **Phase 9 — retire the last `walk_and_paint` primitives.**
  `terrain_detail` and the `wood_floor` short-circuit get Rust ports
  + structured per-tile data. Schema 2.4 → 2.5 (additive).
  Phase 9.3 majors to **3.0**, deletes the wood-floor / terrain-detail
  passthroughs, and retires `_decorators.py` + `walk_and_paint`.
- **Phase 10 — three switchable IR-driven rasterisers.** The legacy
  procedural Python emitters (`render_floor_svg`,
  `render_site_surface_svg`, `render_building_floor_svg`) retire; the
  `.svg` endpoint rewires to `ir_to_svg(emit_floor(...))`. Render mode
  is server-side (`NHC_RENDER_MODE` env var); the web client picks
  the matching endpoint at page load. Cross-rasteriser parity
  migrates from `resvg-py` pixel-diff to **two-layer parity**:
  IR-level structural validation + PSNR > 35 dB vs canonical
  reference image. The Rust `resvg` crate replaces `resvg-py` for
  SVG-mode pixel comparison.
- **Phase 11 — IR → Canvas via WASM.** Per the original Phase 6 stub,
  retargeted to the new slot. Canvas joins as the third switchable
  mode; the PNG endpoint stays live as one of three options.

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
| SVG role post-cutover | **First-class switchable rasteriser** alongside PNG and Canvas. Selected per server instance via `NHC_RENDER_MODE` env var; same IR drives all three |
| Phase-1 parity gate | **Byte-equal SVG** between legacy `render_floor_svg` and `ir_to_svg(build_floor_ir(...))` (held until Phase 5; converted to PSNR + structural at Phase 10.4) |
| Cross-rasteriser parity (post-Phase-10) | **Two-layer**: IR-level structural validation + PSNR > 35 dB vs canonical reference image (canonical = tiny-skia PNG of the fixture's IR) |
| Determinism guarantee | **Rust-canonical** — three embeddings, one implementation; no cross-runtime port-drift class of bugs |
| IR scope | **Every gameplay floor** (dungeon / cave / building / surface) is fully described by a `FloorIR`. Phase 8 brings site composites (roofs, enclosures, building walls) into the IR; the legacy `building.py` / `site_svg.py` composite emitters retire in Phase 10 |
| Render mode selection | **Server-side `NHC_RENDER_MODE` env var** (`svg` / `png` / `wasm`); `--render-mode` CLI flag; default `png`. All three endpoints stay alive at all times |
| Hex / overland IR | **Out of scope** — separate IR work if needed |
| Schedule | **Phase 5 + 7 shipped**; Phase 8 (structural composites) is the active resumption point |

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
  Building = 3,            // emitted per-building from Phase 8.1
  Site = 4,                // emitted once per site IR from Phase 8.1
}

table Region {
  id: string (key);
  kind: RegionKind;
  polygon: Polygon;
  shape_tag: string;        // "rect"|"octagon"|"circle"|"pill"|"temple"|"hybrid"|"cave"|"L"
}

table TileCoord { x: int; y: int; tag: string; }     // tag for typed buckets

enum FloorKind: byte { Dungeon = 0, Cave = 1, Building = 2, Surface = 3 }

enum TileCorner: byte {     // Phase 8.3 — interior wall edge endpoints
  NW = 0,   // tile (x, y) NW corner = corner-grid (x, y)
  NE = 1,   // tile (x, y) NE corner = corner-grid (x+1, y)
  SE = 2,   // tile (x, y) SE corner = corner-grid (x+1, y+1)
  SW = 3,   // tile (x, y) SW corner = corner-grid (x, y+1)
}

table FeatureFlags {
  shadows_enabled: bool = true;
  hatching_enabled: bool = true;
  atmospherics_enabled: bool = true;
  macabre_detail: bool = false;
  vegetation_enabled: bool = true;
  interior_finish: string;   // "" | "wood" | "flagstone" | …
}

// Schema 2.0 (Phase 7 cleanup) removed six reserved variants that
// were never emitted (CobblestoneOp / WoodFloorOp / GardenOverlayOp /
// FieldOverlayOp / CartTracksOp / OreDepositsOp). The seven decorator
// variants ride through DecoratorOp's per-variant vector tables;
// surface features ship through the four per-shape FeatureOps.
union Op {
  ShadowOp,
  HatchOp,
  WallsAndFloorsOp,
  TerrainTintOp,
  FloorGridOp,
  FloorDetailOp,
  ThematicDetailOp,
  TerrainDetailOp,
  StairsOp,
  TreeFeatureOp,
  BushFeatureOp,
  WellFeatureOp,
  FountainFeatureOp,
  GenericProceduralOp,    // escape hatch for additive primitives
  DecoratorOp,
  // Phase 8 — structural composites
  RoofOp,                 // 8.1, schema 2.1
  EnclosureOp,            // 8.2, schema 2.2
  BuildingExteriorWallOp, // 8.3, schema 2.3
  BuildingInteriorWallOp, // 8.3, schema 2.3
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

Schema is currently at **major version 2.0** — Phase 7 cleanup
removed the empty Phase-1 transitional fields and the never-emitted
reserved op-union variants. Future evolution:

- **Minor bump (2.x → 2.y)** — additive: new op-union variants, new
  optional fields on existing ops, new theme strings, new region
  shape tags. Old renderers ignore unknown union members (FlatBuffers
  semantics) and render the rest. Ship freely.
- **Major bump (2.x → 3.0)** — breaking: renamed ops, removed fields,
  changed op semantics, changed layer ordering. All three rasterisers
  (Python SVG, Rust PNG, Rust→WASM Canvas) must accept both versions
  for one release cycle.
- The buffer's `file_identifier` encodes major version. Major bumps
  also bump the `.fbs` file's `file_identifier`.
- The floor-artefact disk cache (`nhc/core/autosave.py`) gates on
  the `(major, minor)` pair so version bumps auto-invalidate stale
  caches at load time.

**Phase 8 / 9 / 10 schema bump path**:

| Schema | Phase | Change |
|---|---|---|
| 2.1 | 8.1 | Add `RoofOp` + `RoofStyle` enum; emit `Region(kind=Building/Site)` |
| 2.2 | 8.2 | Add `EnclosureOp` + `EnclosureStyle` + `CornerStyle` + `Gate` + `GateStyle` |
| 2.3 | 8.3 | Add `BuildingExteriorWallOp` + `BuildingInteriorWallOp` + `WallMaterial` + `InteriorWallMaterial` + `TileCorner` + `InteriorEdge` |
| 2.4 | 9.1 | Add structured per-tile data fields to `TerrainDetailOp` (legacy passthrough fields stay, deprecated) |
| 2.5 | 9.2 | Add structured per-room plank data fields to `FloorDetailOp` (legacy `wood_floor_groups` stays, deprecated) |
| **3.0** | 9.3 | **Major** — delete `TerrainDetailOp.room_groups`, `corridor_groups`, `FloorDetailOp.wood_floor_groups`. The `file_identifier` advances |

## 6. Layer ordering

The IR carries ops in the same sequence as the legacy SVG layers, so
Phase 1 byte-equal parity holds and PNG / Canvas renderers can stream
with no sort step:

| Order | Layer name | Op kinds |
|---|---|---|
| 100 | shadows | `ShadowOp` (room, corridor) |
| 200 | hatching | `HatchOp` (room, hole, corridor) |
| 300 | structural | `WallsAndFloorsOp`, `RoofOp`, `EnclosureOp`, `BuildingExteriorWallOp`, `BuildingInteriorWallOp` (within-layer order in §6.1) |
| 350 | terrain_tints | `TerrainTintOp` |
| 400 | floor_grid | `FloorGridOp` |
| 500 | floor_detail | `FloorDetailOp`, `ThematicDetailOp`, `DecoratorOp` (cobblestone / brick / flagstone / opus_romano / field_stone / cart_tracks / ore_deposit per-variant tables) |
| 600 | terrain_detail | `TerrainDetailOp` |
| 700 | stairs | `StairsOp` |
| 800 | surface_features | `WellFeatureOp`, `FountainFeatureOp`, `TreeFeatureOp`, `BushFeatureOp` |

Order numbers preserve gaps of 50 between adjacent layers so future
primitives can slot in without re-numbering. The `structural` layer
was renamed from `walls_and_floors` at Phase 8.0; the rename
reflects that the layer now carries every primitive that fills the
structural envelope (walls, floors, roofs, enclosures, building
masonry).

Floor-paint primitives in layers 350 – 800 honour an emit-time
**building-footprint exclusion mask** sourced from
`Region(kind=Building)` polygons: tiles inside any building footprint
are skipped during emit, leaving the `RoofOp` in the structural
layer to paint that area. Roofs *replace* floor inside building
footprints; they do not overlay on top.

### 6.1 Within-`structural` paint order

The `structural` layer holds multiple op kinds depending on IR type.
Within the layer, ops paint in `ops[]` order; the emitter populates
`ops[]` according to the per-IR sequence below:

| IR kind | Op sequence within `structural` |
|---|---|
| Dungeon | `WallsAndFloorsOp` |
| Cave | `WallsAndFloorsOp` |
| Building | `WallsAndFloorsOp` → `BuildingInteriorWallOp` → `BuildingExteriorWallOp` |
| Site | `WallsAndFloorsOp` → `RoofOp` → `EnclosureOp` |

Rationale:

- **Building**: interior partitions paint first; the curved or
  clipped exterior masonry then overlays any partition extension into
  the rim zone, cleaning up T-junctions for circle and octagon
  buildings (mirrors `building.py:97-104`).
- **Site**: roofs paint per-building inside their footprints; the
  enclosure perimeter paints last (above roofs in document order)
  for byte-equal mirror of the legacy site composition. Visual
  effect identical when enclosures don't overlap building footprints
  (always true today).

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

Reference: Rust port at `crates/nhc-render/src/primitives/floor_detail.rs`
(invoked via `nhc_render.draw_floor_detail`). Per-tile rolls: crack
(0.08 dungeon / 0.32 cave × theme scale), scratch (0.05 / 0.01),
stone (0.06 / 0.10), cluster (0.03 / 0.06). The Python emitter
(`_floor_layers.py:_emit_floor_detail_ir`) ships the candidate
tile list + per-tile corridor classification; the wood-floor
short-circuit ships pre-rendered `<g>` groups via
`FloorDetailOp.wood_floor_groups` until the wood-floor port lands.

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

Reference: Rust port at `crates/nhc-render/src/primitives/thematic_detail.rs`
(invoked via `nhc_render.draw_thematic_detail`). Webs prefer
wall-corner anchors; the Python emitter
(`_floor_layers.py:_emit_thematic_detail_ir`) pre-resolves the
per-tile wall-corner bitmap so the consumer doesn't need level
access.

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

### 7.10 DecoratorOp

The seven legacy decorator types — cobblestone (with five
sub-patterns), brick, flagstone, opus_romano, field_stone,
cart_tracks, ore_deposit — ride through one `DecoratorOp` per
floor with seven parallel variant-table vectors:

```
table DecoratorOp {
  cobblestone: [CobblestoneVariant];
  brick: [BrickVariant];
  flagstone: [FlagstoneVariant];
  opus_romano: [OpusRomanoVariant];
  field_stone: [FieldStoneVariant];
  cart_tracks: [CartTracksVariant];
  ore_deposit: [OreDepositVariant];
  seed: uint64;            // base_seed + 333
  theme: string;
  clip_region: string;     // dungeon clip when applicable
}
```

Each variant table carries `tiles: [TileCoord]` plus its own
shape-specific fields (e.g. `CobblestoneVariant.pattern` for the
five cobble sub-patterns; `CartTracksVariant.is_horizontal[]` for
the rail orientation derived by the emitter from neighbour tiles).

Reference: Rust ports under `crates/nhc-render/src/primitives/`
(one file per decorator); Python emitter populates the variant
vectors in `_floor_layers.py:_emit_floor_detail_ir`.

### 7.11 TreeFeatureOp / BushFeatureOp

Cartographer-style vegetation. Trees: layered canopy with per-tile
hue jitter. Groves of 3+ 4-adjacent trees fuse into a single canopy
silhouette via the Rust crate's `geo::BooleanOps` polygon union;
free trees (singletons / pairs) render per-tile. Bushes: smaller
multi-lobe canopy, no trunk.

```
table TreeFeatureOp {
  tiles: [TileCoord];        // free trees (size <= 2)
  seed: uint64;
  theme: string;
  // Groves of size >= 3: flat list of (tx, ty) tuples partitioned
  // by grove_sizes (sum(grove_sizes) == len(grove_tiles)). Each
  // grove fuses Rust-side via geo::BooleanOps.
  grove_tiles: [TileCoord];
  grove_sizes: [uint32];
}

table BushFeatureOp {
  tiles: [TileCoord];
  seed: uint64;
  theme: string;
}
```

Reference: Rust ports at `crates/nhc-render/src/primitives/tree.rs`
and `bush.rs`. The Python emitter
(`_floor_layers.py:_emit_surface_features_ir`) calls
`_features_svg._connected_tree_groves` to BFS-walk tree connectivity
and split free trees from groves.

### 7.12 WellFeatureOp / FountainFeatureOp

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

Reference: Rust ports at `crates/nhc-render/src/primitives/well.rs`
and `fountain.rs`. Each fountain shape variant has its own
emission function; the Python emitter
(`_floor_layers.py:_emit_surface_features_ir`) splits anchor
tiles per `Tile.feature` value into one op per shape.

### 7.13 GenericProceduralOp (escape hatch)

For new primitives that haven't yet earned their own table. Carries
`(name: string, tiles, seed, params: [KV])`. Renderers dispatch on
`name` to a registered handler. Use sparingly — promote to a
dedicated table once the primitive stabilises.

### 7.14 RoofOp (Phase 8.1)

Per-building roof primitive. Emitted in the `structural` layer for
site IRs only. Renders shingled gable / pyramid roofs over each
building's outer footprint; floor-paint primitives in later layers
exclude tiles inside the building footprint so the roof replaces
them rather than overlaying on top.

```
enum RoofStyle: byte {
  Simple = 0,          // gable for non-square rect/L; pyramid for octagon/square/circle
  Dome = 1,            // future — concentric shingle rings on circular buildings
  WitchHat = 2,        // future — tall pointed cone
}

table RoofOp {
  region_ref: string;     // → Building region id
  style: RoofStyle = Simple;
  tint: string;           // hex colour chosen at emit-time from ROOF_TINTS
  rng_seed: uint64;       // shingle layout perturbation
}
```

The geometric strategy (gable vs pyramid) is derived at render-time
from the referenced `Region.shape_tag` and `Region.polygon` bounding
box (rect non-square or L → gable; octagon, square rect, circle →
pyramid). `gable_horizontal` is `bbox.w >= bbox.h`. `Dome` and
`WitchHat` are reserved enum slots; Phase 8.1 falls back to `Simple`
for any non-`Simple` style.

Reference: `_roofs.py:building_roof_fragments` (legacy);
`crates/nhc-render/src/transform/png/roof.rs` (Rust port).
RNG seed = `base_seed + 0xCAFE + building_index`.

### 7.15 EnclosureOp (Phase 8.2)

Site-perimeter enclosure (palisade or fortification). Emitted in the
`structural` layer for site IRs only.

```
enum EnclosureStyle: byte {
  Palisade = 0,
  Fortification = 1,
  // Future: Brick, Stone, Hedge, ...
}

enum CornerStyle: byte {
  Merlon = 0,         // axis-aligned black square (legacy default)
  Diamond = 1,        // 45° rotated black square (legacy alt)
  Tower = 2,          // future — round/towered corner
  // Future: Round, Octagon, Battlement, ...
}

enum GateStyle: byte {
  Wood = 0,           // brown filled rect (legacy palisade door)
  Portcullis = 1,     // future — black dots crossed with thin line
  // Future: Iron, Stone, OpenArch, ...
}

table Gate {
  edge_idx: uint32;
  t_center: float;    // 0..1 along edge
  half_px: float;
  style: GateStyle = Wood;
}

table EnclosureOp {
  polygon: Polygon;
  style: EnclosureStyle;
  corner_style: CornerStyle = Merlon;   // fortification-only; ignored by Palisade
  gates: [Gate];
  rng_seed: uint64;
}
```

Renderer dispatches per-edge on `EnclosureStyle` (palisade circles
or fortification battlement chain), per-gate on `GateStyle` (wood
rect or fall-back), per-vertex on `CornerStyle` for fortification
(merlon / diamond / fall-back). `Gate.style` defaults to `Wood`;
unknown gate / corner styles fall back to documented defaults
(Wood / Merlon).

Visual delta vs legacy:

- **Palisade**: byte-equal — same circles + wood gate rects.
- **Fortification (keep)**: gates now draw wood rects (legacy drew
  nothing at fortification gate positions). Corners draw `Merlon`
  by default (matches legacy default). Fortification fixture's
  golden snapshot updates on Phase 8.2.

Reference: `_enclosures.py:render_palisade_enclosure`,
`render_fortification_enclosure` (legacy);
`crates/nhc-render/src/transform/png/enclosure.rs` (Rust port).
Per-edge RNG seed = `rng_seed + edge_idx`.

### 7.16 BuildingExteriorWallOp (Phase 8.3)

Building exterior masonry — brick or stone running-bond rounded-rect
chain along the perimeter polygon. Emitted in the `structural` layer
for building floor IRs only. Buildings with `wall_material ==
"dungeon"` do not emit this op; the existing `WallsAndFloorsOp`
dungeon-wall pass handles them.

```
enum WallMaterial: byte {
  Brick = 0,
  Stone = 1,
  // Future: Wood, Adobe, Timber, Wattle, ...
}

table BuildingExteriorWallOp {
  region_ref: string;        // → Building region; perimeter is the source
  material: WallMaterial;
  rng_seed: uint64;          // per-stone width jitter
}
```

Reference: `_building_walls.py:render_brick_wall_run`,
`render_stone_wall_run` (legacy);
`crates/nhc-render/src/transform/png/building_exterior_wall.rs`
(Rust port). Polygon walked from `Region(kind=Building).polygon`;
each ortho edge runs through `_render_masonry_wall_run`, each
non-orthogonal edge through `_render_diagonal_run` for circle /
octagon footprints.

### 7.17 BuildingInteriorWallOp (Phase 8.3)

Interior partition walls — thin axis-aligned single-line strokes
between adjacent corner-grid points. Emitted in the `structural`
layer for building floor IRs only. Interior edges are
**pre-coalesced and post-door-suppression-filtered at emit-time**:
canonical `(x, y, side)` triples from `Level.interior_edges`
become coalesced runs; door-suppressed edges are filtered out so
door glyphs substitute for the wall stroke.

```
enum InteriorWallMaterial: byte {
  Stone = 0,           // legacy default — thin grey line
  Brick = 1,
  Wood = 2,
}

struct InteriorEdge {
  ax: int32;           // start tile x
  ay: int32;           // start tile y
  a_corner: TileCorner;
  bx: int32;           // end tile x
  by: int32;
  b_corner: TileCorner;
}

table BuildingInteriorWallOp {
  region_ref: string;
  material: InteriorWallMaterial;
  edges: [InteriorEdge];
}
```

The endpoint encoding is **explicit `(tile, corner) × 2`** rather
than implicit corner-grid coords, so the IR is self-documenting
without external convention. Renderer conversion:
`(tile.x + ΔX, tile.y + ΔY) × CELL + PADDING` where
`(ΔX, ΔY) ∈ {NW: (0,0), NE: (1,0), SE: (1,1), SW: (0,1)}`.

Today's emit produces axis-aligned edges only (every edge between
adjacent corners on the same row or column). The schema does not
restrict to axis-aligned; future diagonal interior partitions or
half-tile partitions are expressible without a schema bump.

Reference: `building.py:_render_interior_walls`,
`_coalesce_north_edges`, `_coalesce_west_edges`, `_edge_line`
(legacy); `crates/nhc-render/src/transform/png/building_interior_wall.rs`
(Rust port).

### 7.18 What the IR does NOT cover (post-Phase-10)

- Doors (`_doors_svg.py`) — composed by the web client as a
  separate canvas overlay layer; door state (open / closed / locked)
  is dynamic and out-of-IR-scope.
- Fog of war / visibility — entity-canvas overlay.
- Entities (creatures, items, player) — entity-canvas overlay.
- Future: open-state gate animation — entity-canvas overlay paints
  the open variant; the IR carries the closed-state visual via
  `Gate.style = Wood` (or `Portcullis` etc).

## 8. The Rust crate `nhc-render`

### Module layout

```
crates/nhc-render/
├── Cargo.toml
├── src/
│   ├── lib.rs                              # re-exports
│   ├── ir.rs                               # FB-generated IR + thin wrappers
│   ├── rng.rs                              # splitmix64 wrapper
│   ├── perlin.rs                           # noise port (parity-fixture-tested)
│   ├── transform/
│   │   ├── png/                             # tiny-skia rasteriser, one file per op
│   │   │   ├── mod.rs
│   │   │   ├── shadow.rs
│   │   │   ├── hatch.rs
│   │   │   ├── walls_and_floors.rs
│   │   │   ├── floor_grid.rs
│   │   │   ├── terrain_tints.rs
│   │   │   ├── floor_detail.rs
│   │   │   ├── thematic_detail.rs
│   │   │   ├── terrain_detail.rs
│   │   │   ├── stairs.rs
│   │   │   ├── decorator.rs
│   │   │   ├── tree.rs / bush.rs
│   │   │   ├── well.rs / fountain.rs
│   │   │   ├── generic_procedural.rs
│   │   │   ├── fragment.rs / svg_attr.rs / path_parser.rs / polygon_path.rs
│   │   │   ├── roof.rs                      # Phase 8.1
│   │   │   ├── enclosure.rs                 # Phase 8.2
│   │   │   ├── building_exterior_wall.rs    # Phase 8.3
│   │   │   └── building_interior_wall.rs    # Phase 8.3
│   │   ├── canvas/                          # canvas2d command stream (WASM, Phase 11)
│   │   └── svg.rs                           # Rust resvg crate (Phase 10.4 — replaces resvg-py)
│   └── ffi/
│       ├── pyo3.rs                          # Python bindings (cfg = "pyo3")
│       └── wasm.rs                          # wasm-bindgen exports (cfg = "wasm")

crates/nhc-render-wasm/                      # Phase 11 — thin wrapper crate
├── Cargo.toml
└── src/lib.rs                               # re-exports nhc-render with `wasm` feature
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

The three rasterisers are **switchable first-class modes**, not a
migration ladder. After Phase 8 every gameplay floor produces a
complete `FloorIR`; each rasteriser is a pure function from IR to
its output. The active rasteriser is selected per server instance
via the `NHC_RENDER_MODE` env var (see §11). Performance comparison
between modes is the design intent: one IR build cost, three
downstream transforms, head-to-head measurable.

### 9.1 IR → SVG (Python wrapper, Rust transform from Phase 10.1)

Lives at `nhc/rendering/ir_to_svg.py`. Today (Phase 5) this iterates
ops and calls per-op `_draw_*_from_ir` helpers that string-build SVG
fragments. From Phase 10.1, the `.svg` endpoint rewires to
`ir_to_svg(emit_floor(...))` — same byte-equal SVG output, but
served from the IR pipeline rather than the legacy
`render_floor_svg` chain.

Used for:

- The `svg` mode of `NHC_RENDER_MODE` — gameplay floor rendering.
- `/admin` debug visualisation (`?bare=1` query strips decoration).
- Export endpoints (`/api/game/<sid>/export/map_svg`).
- Cross-rasteriser parity (rendered through Rust `resvg` crate to
  PNG for PSNR comparison vs reference image — see Phase 10.4).

### 9.2 IR → PNG (Rust via PyO3, tiny-skia)

`nhc_render.ir_to_png(ir_bytes, scale)` returns PNG bytes via
`tiny-skia` rasteriser on a `Pixmap`. Phase 5 cut over from the
`resvg-py` stepping stone; production today serves dungeon and cave
floors through this path. Phase 8 extends coverage to site surfaces
and composite building floors.

Used for:

- The `png` mode of `NHC_RENDER_MODE` (default mode) — gameplay
  floor rendering.
- Image-mode LLM tools that consume PNG.
- Share-a-map endpoints.
- Canonical reference image for cross-rasteriser parity (the
  reference for PSNR is the tiny-skia PNG of the fixture's IR).

### 9.3 IR → Canvas (Rust via WASM, client path) — Phase 11

`renderIRToCanvas(irBuffer, ctx, hatchPattern)` is the client-side
rasteriser. The canvas overlay layers (door / hatch / fog / entity —
see `design/canvas_rendering.md`) are unchanged; only the floor
layer moves from "inline an SVG" to "paint via WASM."

Used for:

- The `wasm` mode of `NHC_RENDER_MODE` — gameplay floor rendering;
  server emits raw IR (`.nir`), client paints. Server CPU drops on
  the gameplay hot path because the server stops rasterising.

Template change: `<div id="floor-svg">` → `<canvas
id="floor-canvas">`. `map.js`: `setFloorSVG` → `setFloorIR`.

### 9.4 Cross-rasteriser parity contract

Replaces the previous byte-equal SVG / pixel-diff regime at Phase
10.4. **Two-layer parity validation**:

1. **IR-level structural validation** (rasteriser-independent).
   Every parity fixture's IR is regenerated; structural invariants
   checked: op count by type, element count per layer, region
   polygon counts, ordering. Catches emit-side regressions before
   any rasteriser runs. Cheap: a single FlatBuffer parse + counters.
2. **Pixel-level PSNR vs reference image** (per rasteriser). One
   canonical reference image per fixture — the tiny-skia PNG of the
   fixture's IR — frozen at
   `tests/fixtures/floor_ir/<descriptor>/reference.png`. Each
   rasteriser's output is PSNR'd against the reference. Default
   threshold: **PSNR > 35 dB**, tightenable per-`(rasteriser,
   fixture)` pair if measurements show headroom. Threshold for the
   `wasm-canvas` mode may be lower (e.g. 30 dB) because Canvas2D AA
   varies by browser; calibrated when Phase 11 lands.

Reference image lifecycle:

- New fixture lands → reference rendered from the canonical
  rasteriser (tiny-skia PNG) and committed.
- Fixture inputs change → reference regenerated via
  `tests/samples/regenerate_fixtures.py --regen-reference
  <descriptor>`. Without the explicit flag, the harness errors if
  the reference would change. Catches accidental drift.
- Canonical rasteriser changes (tiny-skia upgrade, palette tweak) →
  explicit reference regeneration step in the migration commit, with
  a body note explaining the cause.

PSNR is global across the image; localised artifacts can be hidden
by overall agreement. Mitigation if the metric proves blind in
practice: add per-region PSNR (split image into 4×4 tiles, take
min) or SSIM > 0.95 as a secondary gate. Phase 8 ships PSNR-only;
escalation depends on empirical measurement.

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
   and listed in §7. Phase 8 ops add the following salts:
   - `RoofOp.rng_seed = base_seed + 0xCAFE + building_index`
   - `EnclosureOp.rng_seed = base_seed + 0xE101` (per-edge stream
     keyed `rng_seed + edge_idx` so adding / removing a gate on edge
     X doesn't shift RNG state on other edges)
   - `BuildingExteriorWallOp.rng_seed = base_seed + 0xBE71 +
     building_index` (per-stone width jitter)
   - `BuildingInteriorWallOp` is RNG-free (deterministic line strokes).
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
GET /api/game/<sid>/floor/<svg_id>.svg       # IR→SVG (Python today, ir_to_svg(emit_floor) from Phase 10.1)
GET /api/game/<sid>/floor/<svg_id>.nir       # FlatBuffers IR (binary) — consumed by the wasm-canvas mode client
GET /api/game/<sid>/floor/<svg_id>.png       # IR→PNG via Rust + tiny-skia
GET /api/game/<sid>/floor/<svg_id>.json      # IR dumped as JSON (debug)
GET /api/hatch.svg                            # unchanged, shared session asset
```

**All three rendering endpoints stay alive at all times** — `.svg`,
`.png`, `.nir` are first-class siblings. Independent endpoints
matter because (a) different consumers want different formats
(LLM tools want PNG, browsers want WASM-Canvas, exports want SVG),
and (b) cross-rasteriser performance comparison requires being able
to fetch any of them on demand from any server instance.

### Render mode selection (Phase 10.3)

The web client's gameplay floor element fetches **one** of the
three endpoints. Which one is selected at server-start time via
`NHC_RENDER_MODE`:

```
./server --render-mode=svg|png|wasm        # CLI flag
NHC_RENDER_MODE=png ./server               # env var equivalent
```

Default: `png`. The Dockerfile sets `ENV NHC_RENDER_MODE=png`
explicitly; runtime override via `docker run -e
NHC_RENDER_MODE=svg`. The server reads the env var at app init and
injects the value into the gameplay page template (e.g.
`<meta name="render-mode" content="png">`). The client reads the
injected value once at page load and `setFloorURL` picks the
matching endpoint extension.

No runtime client-side toggle, no admin UI control, no localStorage
persistence, no URL-parameter override. The mode is a server
property; performance comparison is a "stop server → restart with
different `--render-mode` → measure → repeat" workflow. That
matches the developer-facing measurement intent and removes a layer
of client-side complexity.

No fallback: if the configured mode's rasteriser fails on a given
floor, the floor doesn't render and the failure surfaces. The
transitional `404 → SVG fallback` branch in `setFloorURL` is
removed at Phase 10.3 (Phase 8.6 / 8.7 already eliminated the 404
class by completing IR coverage).

## 12. Phased plan

The migration is twelve phases (0 – 11). Phases 0 – 7 shipped during
the initial migration arc; Phases 8 – 11 are the closing arc that
brings every gameplay floor onto the IR pipeline and lights up
three switchable rasterisers.

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

### Phase 6 — Reserved (was the WASM Canvas slot)

Phase 6 was originally the WASM Canvas cutover. It moved to Phase
11 (after Phase 8's structural composites and Phase 9's procedural
cleanup) so the WASM port lands against a fully IR-described floor
set with no SVG-fallback path to maintain.

### Phase 7 — Deprecate legacy Python procedural code (per-op)

Procedural primitives that have ports in Phases 3 + 4 retire their
Python paint helpers as the IR-driven path takes over. `_decorators.py`
and `walk_and_paint` survive the phase because two callers remain
(terrain-detail decorators + the wood-floor short-circuit); both
port in Phase 9.

A ruff lint rule banning `import random` in `nhc/rendering/` makes
RNG-drift regressions impossible.

### Phase 8 — Structural composites through IR

Adds `RoofOp`, `EnclosureOp`, `BuildingExteriorWallOp`, and
`BuildingInteriorWallOp` to the schema. After Phase 8, every
gameplay floor (dungeon / cave / building / site) produces a
complete `FloorIR`; the `.png` endpoint returns 200 for everything;
the web-client SVG fallback for site surfaces and composite building
floors becomes unreachable.

Sub-phases:

- **8.0** — Layer rename `walls_and_floors` → `structural`.
  Mechanical rename of the layer key in `ir_to_svg.py:54-107`,
  parity harness `LANDED_PAIRS`, Rust dispatch keys, and §6 of this
  doc. Optionally folded with a pre-Phase-8 conversion of the
  existing 0.5 % / 0.7 % pixel-diff harness to the PSNR + structural
  contract from §9.4.
- **8.1** — `RoofOp` (schema 2.1). New op + `RoofStyle` enum +
  `RegionKind.Building / Site` emission. Floor primitives gain an
  emit-time building-footprint exclusion mask sourced from
  `Region(kind=Building)` polygons. Circular buildings (legacy
  `Circle → skip`) start receiving Simple-style pyramid roofs on
  their N-gon footprint. Synthetic-IR test only; existing dungeon
  fixtures unaffected.
- **8.2** — `EnclosureOp` (schema 2.2). New op + `EnclosureStyle` +
  `CornerStyle` + `Gate` table + `GateStyle` enum. Fortification
  gates gain a Wood gate-rect visual (legacy drew nothing); keep
  fixture's golden snapshot updates. Site fixture
  `seed7_town_palisade_surface` lands.
- **8.3** — `BuildingExteriorWallOp` + `BuildingInteriorWallOp`
  (schema 2.3). New ops + `WallMaterial` + `InteriorWallMaterial` +
  `TileCorner` enums + `InteriorEdge` struct. Building fixture
  `seed7_brick_building_floor0` lands.
- **8.4** — Site-surface emit-side wiring. `_emit_floor` learns the
  site context and emits the new ops alongside the existing layer
  set. The `level is site.surface` short-circuit in
  `_get_or_build_ir_artefacts` (around `app.py:1228`) drops.
- **8.5** — Building-floor emit-side wiring. Same shape:
  `building_id` + `floor_index` flow into emit; the `building_id is
  not None` short-circuit (around `app.py:1232`) drops.
  `seed7_town_brick_surface` fixture lands (brick enclosure
  variant).
- **8.6** — Codify §6.1 within-`structural` paint order in this
  doc. No code change; closes the design contract.

**Gate:** PSNR > 35 dB vs reference for every fixture across all
three rasterisers (Phase 11 modes calibrated when 11 lands).
Structural validation green for every fixture.

### Phase 9 — Retire walk_and_paint primitives

Last two procedural-Python primitives (terrain-detail decorators +
wood-floor short-circuit) port to Rust. Deletes the legacy
walk_and_paint dispatcher and tightens the architectural guard.

- **9.1** — `TerrainDetailOp` Rust port (schema 2.4 additive). Schema
  gains structured per-tile data fields next to the existing
  `room_groups` / `corridor_groups` passthroughs (deprecated). Rust
  port at `terrain_detail.rs` reads structured data; the legacy
  `walk_and_paint` driver path retires for terrain detail.
- **9.2** — Wood-floor Rust port (schema 2.5 additive). Schema
  gains structured per-room plank data fields next to
  `FloorDetailOp.wood_floor_groups` (deprecated). The
  `_floor_detail.py` short-circuit branch in the IR emitter folds
  into the new code.
- **9.3** — **Major bump 3.0.** Delete `wood_floor_groups`,
  `room_groups`, `corridor_groups` passthroughs. Delete
  `_decorators.py` and the `walk_and_paint` dispatcher. Tighten
  `tests/unit/test_no_import_random_in_rendering.py` to require zero
  `import random` in `nhc/rendering/`. The floor-artefact disk cache
  invalidates via the `(major, minor)` gate.

### Phase 10 — Three switchable IR-driven rasterisers

The legacy procedural Python composite emitters retire; the `.svg`
endpoint rewires through the IR pipeline. Render mode becomes a
server-side configuration; the parity harness pivots to PSNR +
structural.

- **10.1** — Rewire `.svg` endpoint to use
  `ir_to_svg(emit_floor(...))` instead of `render_floor_svg`. Same
  byte-equal SVG (parity harness already protects this), different
  code path.
- **10.2** — Drop `render_level_svg`, `render_site_surface_svg`,
  `render_building_floor_svg`, `render_floor_svg`. Python rendering
  surface contracts to `build_floor_ir` → emit FB → choose
  rasteriser.
- **10.3** — Server-side env-var render mode. `NHC_RENDER_MODE`
  with `--render-mode` CLI flag; default `png`. Template injection;
  `setFloorURL` reads the injected mode. Drop the `404 → SVG`
  fallback branch.
- **10.4** — Drop `resvg-py` `.[dev]` extra. Cross-rasteriser parity
  pivots to structural validation + PSNR > 35 dB vs reference image.
  The Rust `resvg` crate replaces `resvg-py` for SVG-mode pixel
  comparison.
- **10.5** — Update `design/map_ir.md` (this doc) and
  `CONTRIBUTING.md` to document the three switchable rasterisers as
  a first-class architectural feature. Mark Phase 10 complete in §1.

### Phase 11 — IR → Canvas via WASM

Per the original Phase 6 ladder. Now safer because every floor is
fully IR-described and the SVG path is alive as a measurement
peer.

- New crate `crates/nhc-render-wasm/` reusing `nhc-render` with the
  `wasm` feature. `wasm-pack build --target web`, `wasm-opt -Oz`,
  vendor under `nhc/web/static/wasm/`.
- `nhc/web/static/js/floor_ir_renderer.js` JS shim (~50 lines)
  loads WASM and dispatches Canvas2D commands.
- Template change: `<canvas id="floor-canvas">` becomes the
  gameplay floor element when `NHC_RENDER_MODE=wasm`.
  `setFloorURL` reads `.nir` instead of `.svg` / `.png` for that
  mode.
- Server emits no PNG / SVG on the gameplay hot path when wasm
  mode is active; expected ≥ 40 % CPU drop vs Phase 0 baseline on
  that mode.

**Gate:** PSNR > 30 dB (calibrated lower than the 35 dB SVG/PNG
threshold to absorb browser Canvas2D AA variance) vs reference
image, headless Chromium per fixture. Server CPU benchmark on the
gameplay hot path published against Phase 0 baseline.

## 13. Critical files

### Existing — modified

- `nhc/rendering/svg.py` — `render_floor_svg` becomes
  `ir = build_floor_ir(level, ...); return ir_to_svg(ir)`. Retired at
  Phase 10.2.
- `nhc/rendering/_render_context.py` — emits `RenderContext` flags
  into the IR `FeatureFlags` table.
- `nhc/rendering/_floor_layers.py` — each `*_paint` helper grows an
  `*_emit_ir` sibling; over Phases 1–4, paint helpers become thin
  shims that consume IR ops produced by the emit siblings. Phase 8
  extends with structural-composite emit helpers.
- `nhc/rendering/site_svg.py`, `nhc/rendering/building.py` — legacy
  composite emitters; retired at Phase 10.2 (replaced by emit-side
  ops in Phase 8.4 / 8.5).
- `nhc/rendering/ir_to_svg.py` — Phase 8.0 renames the
  `walls_and_floors` layer key to `structural` in `_LAYER_ORDER` /
  `_LAYER_OPS`. Phase 8.1 – 8.3 wire the new structural ops into
  `_LAYER_OPS`.
- `nhc/rendering/ir_emitter.py` — Phase 8.1 lights up
  `RegionKind.Building` and `RegionKind.Site` emission in
  `emit_regions`. Phase 8.4 / 8.5 drop the `level is site.surface`
  and `building_id is not None` short-circuits in
  `_get_or_build_ir_artefacts`.
- `nhc/web/app.py` — adds `.nir`, `.png`, `.json` floor routes;
  extends `save_svg_cache`. Phase 10.3 reads `NHC_RENDER_MODE` env
  var and injects into the gameplay page template.
- `nhc/web/templates/play.html` — Phase 11: gameplay floor element
  becomes `<canvas id="floor-canvas">` when render mode is `wasm`.
  Phase 10.3: receives the `<meta name="render-mode">` tag from
  server config.
- `nhc/web/static/js/map.js` — Phase 10.3: `setFloorURL` reads the
  injected render mode and picks the matching extension; drops the
  404 → SVG fallback. Phase 11: handles the `wasm` mode via
  `floor_ir_renderer.js`.
- `tests/samples/regenerate_fixtures.py` — Phase 8 extends with
  `SiteFixture` + `BuildingFixture` variants; new fixtures land
  per Phase 8 sub-phase.
- `tests/unit/test_ir_png_parity.py` — Phase 8.0 (or pre-8.0
  standalone) converts to PSNR + structural per §9.4.
- `crates/Cargo.toml` — workspace profile reserves `opt-level "z" →
  "3"` flip (~30 % build-time win) as deferred performance headroom.

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
   `(level, seed)`, assert `build_floor_ir(...)` matches a committed
   FB buffer + JSON dump under `tests/fixtures/floor_ir/`.
2. **`tests/unit/test_ir_to_svg.py`** — byte-equal parity (Phase 1
   through Phase 10.3). `ir_to_svg(ir) == render_floor_svg_legacy(...)`
   on every fixture. Stays as the guardrail until Phase 10.2 deletes
   the legacy emitters; afterwards the test mutates to check
   `ir_to_svg(emit_floor(level, seed)) == reference_svg_snapshot`.
3. **`tests/unit/test_ir_rng.py`** — splitmix64 vectors and Perlin
   vectors checked across Python and Rust (via PyO3) and JS (via
   WASM headless harness).
4. **`tests/unit/test_ir_canvas_parity.py`** (`slow`, Phase 11) —
   rasterise IR via `nhc_render.ir_to_png` (canonical reference) and
   via headless Chromium running the WASM Canvas renderer; PSNR > 30
   dB threshold (Phase 11 calibration).
5. **`tests/unit/test_ir_png_parity.py`** (`slow`, Phase 5+).
   Currently 0.5 % per-layer / 0.7 % whole-floor pixel-diff against
   `resvg-py` baseline. Phase 8.0 (or a dedicated standalone commit)
   converts to two-layer parity per §9.4: structural validation +
   PSNR > 35 dB vs canonical reference image. Phase 10.4 drops the
   `resvg-py` dependency entirely.
6. **`tests/unit/test_ir_perf.py`** (`slow`) — p95 budgets on
   `build_floor_ir`, `ir_to_svg`, `ir_to_png`, WASM Canvas paint.
   Soft target: cold-path p95 < 500 ms across all rasterisers (per
   §17 success metrics). The workspace `Cargo` profile reserves
   `opt-level "z" → "3"` (~30 % build-time gain) as deferred
   headroom.
7. **`tests/samples/regenerate_fixtures.py`** — IR-fixture
   regeneration tool; Phase 8 extends with `SiteFixture` +
   `BuildingFixture` variants alongside the existing dungeon fixture
   tuple. New fixtures land per Phase 8 sub-phase: palisade town
   (8.2), brick building (8.3), brick town (8.5).
8. **`tests/samples/generate_svg.py`** — visual inspection sample
   tool; renders human-eyeball SVGs for review. Distinct from the
   parity-harness fixture regenerator.

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
  `render_floor_svg` on every fixture. **Achieved.**
- **IR wire size (Phase 2):** p95 `floor.nir` < 12 KB raw, < 4 KB
  gzipped. **Achieved.**
- **PNG path (Phase 5):** server p95 ≤ 12 ms per floor at 1× scale
  on the deployment target (Intel Broadwell i5-5250U class, 2c/4t,
  AVX2, 15 GiB RAM); ≤ 60 ms at 2×. A datacenter-class CPU would
  comfortably halve those numbers — recalibrate if the server is
  ever upgraded. **Achieved (~360 ms p95 cold, ~ms warm on dev).**
- **Cold-path soft target (Phase 8 onward):** cold-path p95 < 500 ms
  across all rasterisers. New visual primitives that push p95 past
  the target should call out the budget impact in their commit body
  and either fit within budget or spend the workspace `opt-level
  "z" → "3"` reserve (~30 % build-time win) in the same commit.
  Soft goal, not a CI gate.
- **Cross-rasteriser parity (Phase 8 onward):** structural validation
  + PSNR > 35 dB vs canonical reference image per `(rasteriser,
  fixture)` pair (canvas mode threshold may be lower; calibrated at
  Phase 11).
- **Canvas path (Phase 11):** first-paint < 50 ms on a 2020-era
  laptop (Apple Silicon dev or comparable x86_64).
- **Server CPU (Phase 11, wasm mode):** per-floor render time on the
  gameplay hot path drops ≥ 40 % vs Phase 0 baseline (server stops
  rasterising on the wasm-mode hot path).
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
  lacks. **Resolved through Phase 5 — `tiny-skia` shipped as the
  production rasteriser.**
- **Should IR cover hex / overland?** Out of scope for this design.
  If hex rendering ever wants the same canonical-Rust treatment, it
  gets its own IR file (`hex_ir.fbs`) and a separate transformer
  pipeline. The crate's RNG / Perlin / tiny-skia infrastructure is
  reusable.
- **Do we want a "lossy fast mode" on the cold-path SVG?** Skip
  decoration entirely for `/admin` debug views when humans just need
  the structural skeleton. **Resolved — `?bare=1` query parameter
  ships in `ir_to_svg`.**
- **Fixture granularity.** Phase 5 settled at three fixtures (rect
  dungeon, octagon crypt, cave). Phase 8 adds three more (palisade
  town, brick town, brick building). Expand further if debugging
  demands.
- **Browser support floor.** WASM + canvas2d is universal across
  modern browsers. With three switchable rasteriser modes, the
  SVG and PNG modes serve as fallback paths for environments where
  WASM isn't desired. The server admin picks per deployment.
- **PSNR blindness to localised artifacts.** Open until empirical
  data from Phase 8 fixtures arrives. If false negatives appear,
  add per-region PSNR (4×4 tile min) or SSIM > 0.95 as a
  secondary gate. Phase 8 ships PSNR-only.
- **Per-corner enclosure styles.** Today `EnclosureOp.corner_style`
  is uniform across all polygon vertices. If mixed corners ever
  matter (towers at cardinals + plain merlons elsewhere), additively
  add `per_corner_styles: [CornerStyle]` in a later schema bump.
- **`GenericProceduralOp` fate.** Survives schema 3.0 as the
  reserved escape-hatch slot. Could retire if no future ops need
  it, but the cost of keeping a reserved variant is one byte per
  union tag and zero runtime cost.

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
