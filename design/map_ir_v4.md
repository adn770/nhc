# Floor IR v4 — pure-IR contract with all-Rust rendering

**Status:** Proposed design for schema 4.0. Supersedes
`design/map_ir.md` §5 (FlatBuffers schema), §6 (Layer ordering),
§7 (Op catalogue) once 4.0 ships. The pre-4.0 contract in
`map_ir.md` remains the authoritative reference until the cut
lands.

## 1. Goals

Two outcomes drive the v4 redesign:

1. **The FlatBuffers IR carries zero SVG fragment text.** Every
   visual primitive is structured. The IR is the sole contract
   between the world / dungeon generator and the rasterisers.
2. **All rasterisers are Rust.** Both the `.png` and `.svg`
   endpoints flow through Rust transforms via PyO3. The Python
   `ir_to_svg.py` painter retires; the SVG-fragment parser
   modules in `transform/png/` retire; the renderer pipeline
   collapses to a single Rust path with two output targets.

A third outcome falls out: the rasteriser is **flat** — a
single dispatch loop over `ops[]` with no layer envelopes, no
clip masks, no offscreen group buffers. Paint order is
emitter-enforced via op sequence in the IR.

## 2. Principles

### Stamp model

The canvas starts as a single `Pixmap::fill(parchment_bg)`. Each
op stamps onto it. Overlaps are allowed and intentional —
that's how decorations layer correctly. The emitter sequences
ops so paint order is implicit:

```
canvas = Pixmap.fill(BG)
for op in fir.ops:
    handlers[op.type](op, canvas, fir)   // paint in place
canvas.encode_png() / canvas.into_svg_string()
```

No per-op clip envelopes. No `<g opacity>` wrappers. No
offscreen scratch buffers. Hatch's outer-band predicate
replaces the dungeon-clip envelope it used to ride in.

### One geometric primitive for walls and floors

`Outline` describes any closed or open polyline with optional
openings (cuts). Every wall-bearing structure (rooms,
buildings, palisades, partitions, caves) and every floor-area
stamp uses an `Outline`. Floors get cuts: [] (no openings);
walls populate cuts with doors / gates / smooth-room gaps.

### Ops are paint stamps

Each op carries:
- One `Outline` (for floor/wall ops) or structured
  per-instance data (for fixtures and detail ops),
- Style enums (`WallStyle`, `FloorStyle`, `CutStyle`, …),
- An `Op`-specific parameter block (seed, theme, kind, …).

There is no shared world snapshot. Each op is self-contained.
Detail / hatch ops keep small structured tile lists (lookup
table for the renderer to iterate); fixture ops carry placement
coordinates; structural ops carry outlines.

### Cross-language contract

The IR is a FlatBuffers binary blob with `file_identifier "NIR4"`.
Producer: `nhc/rendering/ir_emitter.py` (Python; the world /
dungeon generator's view-builder). Consumer: `nhc-render` Rust
crate, exposed via PyO3 (`nhc_render.ir_to_png(buf, …)` /
`nhc_render.ir_to_svg(buf)`) and via `wasm-pack` for browser
canvas rendering.

## 3. The IR (FlatBuffers schema 4.0)

```
namespace nhc.ir;

file_identifier "NIR4";          // NHC IR Floor v4
file_extension "nir";

// ── Geometric primitives ─────────────────────────────────────

table Vec2 { x: float; y: float; }

// Polygon — multi-ring closed area description. Used for
// `Region.polygon` and any consumer that needs hole-aware
// containment tests (hatch's region_in / region_out predicates).
table Polygon {
  paths: [Vec2];                // flat list, partitioned by rings
  rings: [PathRange];
}

struct PathRange { start: uint32; count: uint32; is_hole: bool; }

// Outline — single-ring polyline with optional openings, used
// for every wall and floor stamp. `descriptor_kind` discriminates
// between vertex-defined polygons and parametric Circle / Pill
// shapes (the renderer reproduces those via its native primitives
// rather than pre-tessellating).
enum OutlineKind : ubyte {
  Polygon = 0,                  // vertices is the source of truth
  Circle  = 1,                  // (cx, cy, rx) — rx == ry expected
  Pill    = 2,                  // (cx, cy, rx, ry) rounded rect
}

table Outline {
  vertices: [Vec2];             // populated when descriptor_kind == Polygon
  cuts: [Cut];                  // openings; [] for floors
  closed: bool = true;          // false for open polylines (interior partitions)
  descriptor_kind: OutlineKind = Polygon;
  cx: float; cy: float;         // Circle / Pill descriptor center
  rx: float; ry: float;         // Circle / Pill descriptor radii
}

// Cut — one opening on an Outline. start / end are pixel-space
// coordinates on the outline's perimeter; the wall renderer
// breaks the stroke between them. style picks an optional
// visual at the cut (door / gate visuals); None = bare gap.
table Cut {
  start: Vec2;
  end: Vec2;
  style: CutStyle = None;
}

enum CutStyle : ubyte {
  None            = 0,          // bare gap, no visual at the cut
  WoodGate        = 1,          // enclosure gate (wood)
  PortcullisGate  = 2,          // enclosure gate (portcullis)
  DoorWood        = 3,          // standard interior door
  DoorStone       = 4,          // dungeon stone door
  DoorIron        = 5,          // dungeon iron door
  DoorSecret      = 6,          // looks like wall on the static map
  // future: DoorArch, DoorPortcullis, …
}

// ── Region — area description with id and shape tag ──────────

enum RegionKind : byte {
  Dungeon = 0,
  Cave    = 1,
  Room    = 2,
  Building = 3,
  Site    = 4,
}

table Region {
  id: string (key);
  kind: RegionKind;
  polygon: Polygon;             // multi-ring; supports holes
  shape_tag: string;            // "rect" | "octagon" | "circle" | "pill" | "temple" | "cave" | "L" | "hybrid"
}

// ── Paint style enums ────────────────────────────────────────

enum WallStyle : ubyte {
  DungeonInk          = 0,      // 5px black stroke, round joins
  CaveInk             = 1,      // same paint as DungeonInk; reserved for future divergence
  MasonryBrick        = 2,      // running-bond masonry, brick fill
  MasonryStone        = 3,      // running-bond masonry, stone fill
  PartitionStone      = 4,      // dressed-stone interior partition
  PartitionBrick      = 5,      // brick interior partition
  PartitionWood       = 6,      // wooden plank partition
  Palisade            = 7,      // staked wooden ring
  FortificationMerlon = 8,      // crenelated battlement
  // future: PartitionMarble, MasonrySandstone, ReinforcedIron, …
}

enum FloorStyle : ubyte {
  DungeonFloor   = 0,           // #FFFFFF (today's FLOOR_COLOR)
  CaveFloor      = 1,           // #F5EBD8 (today's CAVE_FLOOR_COLOR)
  // future: TempleFloor, CryptFloor, …
}

enum CornerStyle : ubyte {
  Merlon = 0,                   // crenelated corner block (Fortification only)
  Flat   = 1,                   // flat corner (Palisade and others)
}

// ── Floor / wall ops — Outline-based stamps ──────────────────

table FloorOp {
  outline: Outline;             // closed; cuts ignored / always empty
  style: FloorStyle;
}

table InteriorWallOp {
  outline: Outline;             // open or closed; cuts = doors
  style: WallStyle;             // PartitionWood / PartitionStone / DungeonInk / …
}

table ExteriorWallOp {
  outline: Outline;             // closed; cuts = doors / gates
  style: WallStyle;              // DungeonInk / MasonryBrick / Palisade / FortificationMerlon / …
  corner_style: CornerStyle = Merlon;
}

// ── Roofs (separate paint slot) ──────────────────────────────

enum RoofStyle : ubyte {
  Simple = 0,                   // flat shingle pattern (today's default)
  Pyramid = 1,                  // octagon / square / circle building
  Gable = 2,                    // rect / L building
}

table RoofOp {
  region_ref: string;           // → Region(kind=Building)
  style: RoofStyle = Simple;
  tint: string;                 // CSS hex, mid-sunlit shade
  rng_seed: uint64;
}

// ── Shadows ──────────────────────────────────────────────────

enum ShadowKind : ubyte { Room = 0, Corridor = 1 }

table ShadowOp {
  kind: ShadowKind;
  region_ref: string;           // for Room kind
  tiles: [TileCoord];           // for Corridor kind
  dx: float = 3.0;
  dy: float = 3.0;
  opacity: float = 0.08;
}

// ── Hatching (outer-band, replaces clip envelope) ────────────

enum HatchKind : ubyte { Room = 0, Hole = 1, Corridor = 2 }

table HatchOp {
  kind: HatchKind;
  region_in: string;            // hatched area (e.g. cave region for Hole kind)
  region_out: string;           // exclusion (e.g. dungeon polygon)
  tiles: [TileCoord];           // for Corridor kind
  is_outer: [bool];             // parallel array; outer-band classification
  extent_tiles: float = 2.0;
  seed: uint64;                 // base_seed + 77 (room) | + 7 (corridor) | hole-specific
  hatch_underlay_color: string;
}

// ── Per-tile detail layers (kept structured-as-today) ────────

table FloorDetailOp {
  tiles: [TileCoord];
  is_corridor: [bool];          // parallel: corridor / room bucket routing
  seed: uint64;                 // base_seed + 99
  theme: string;
  // Wood-floor short-circuit (interior_finish == "wood"):
  wood_tiles: [TileCoord];
  wood_building_polygon: [Vec2];
  wood_rooms: [RectRoom];
}

table ThematicDetailOp {
  tiles: [TileCoord];
  is_corridor: [bool];
  wall_corners: [ubyte];        // bitmap: 0x01 TL / 0x02 TR / 0x04 BL / 0x08 BR
  seed: uint64;                 // base_seed + 199
  theme: string;
}

enum TerrainKind : ubyte { Water = 0, Lava = 1, Chasm = 2 }

table TerrainDetailTile {
  x: int;
  y: int;
  kind: TerrainKind;
  is_corridor: bool;
}

table TerrainDetailOp {
  tiles: [TerrainDetailTile];
  seed: uint64;                 // base_seed + 200
  theme: string;
}

// ── Terrain tints + floor grid (kept structured-as-today) ────

table TerrainTintTile { x: int; y: int; kind: TerrainKind; }
table RoomWash { rect: RectRoom; color: string; opacity: float; }

table TerrainTintOp {
  tiles: [TerrainTintTile];
  room_washes: [RoomWash];
}

table FloorGridTile {
  x: int;
  y: int;
  is_corridor: bool;
}

table FloorGridOp {
  tiles: [FloorGridTile];
  seed: uint64;
  theme: string;
  scale: float = 1.0;           // _DETAIL_SCALE[theme]
}

// ── Decorator pipeline (per-variant tile lists, unchanged) ───

enum CobblePattern : ubyte { Herring = 0, Stack = 1, Ashlar = 2, Rubble = 3, Mosaic = 4 }

table CobblestoneVariant { tiles: [TileCoord]; pattern: CobblePattern; }
table BrickVariant       { tiles: [TileCoord]; }
table FlagstoneVariant   { tiles: [TileCoord]; }
table OpusRomanoVariant  { tiles: [TileCoord]; }
table FieldStoneVariant  { tiles: [TileCoord]; }
table CartTracksVariant  { tiles: [TileCoord]; is_horizontal: [bool]; }
table OreDepositVariant  { tiles: [TileCoord]; }

table DecoratorOp {
  cobblestone: [CobblestoneVariant];
  brick: [BrickVariant];
  flagstone: [FlagstoneVariant];
  opus_romano: [OpusRomanoVariant];
  field_stone: [FieldStoneVariant];
  cart_tracks: [CartTracksVariant];
  ore_deposit: [OreDepositVariant];
  seed: uint64;                 // base_seed + 333
  theme: string;
}

// ── Stairs ───────────────────────────────────────────────────

enum StairDirection : byte { Up = 0, Down = 1 }
table StairTile { x: int; y: int; direction: StairDirection; }

table StairsOp {
  stairs: [StairTile];
  theme: string;
  fill_color: string;           // active when theme == "cave"
}

// ── Surface fixtures (placement + variant params, unchanged) ─

enum WellShape : byte { Round = 0, Square = 1 }
enum FountainShape : byte { Round = 0, Square = 1, LargeRound = 2, LargeSquare = 3, Cross = 4 }

table WellFeatureOp {
  tiles: [TileCoord];           // anchor per fixture
  shape: WellShape;
  seed: uint64;
  theme: string;
}

table FountainFeatureOp {
  tiles: [TileCoord];
  shape: FountainShape;
  seed: uint64;
  theme: string;
}

table TreeFeatureOp {
  tiles: [TileCoord];           // free trees
  grove_tiles: [TileCoord];     // ≥3-tile groves; partitioned by grove_sizes
  grove_sizes: [uint32];
  seed: uint64;
  theme: string;
}

table BushFeatureOp {
  tiles: [TileCoord];
  seed: uint64;
  theme: string;
}

// ── Op union + root ──────────────────────────────────────────

union Op {
  ShadowOp,
  HatchOp,
  FloorOp,                      // NEW (replaces WallsAndFloorsOp's floor portion)
  InteriorWallOp,               // NEW (replaces BuildingInteriorWallOp + smooth-room interior walls)
  RoofOp,
  ExteriorWallOp,               // NEW (replaces BuildingExteriorWallOp + EnclosureOp + dungeon-perimeter walls)
  TerrainTintOp,
  FloorGridOp,
  FloorDetailOp,
  ThematicDetailOp,
  TerrainDetailOp,
  StairsOp,
  WellFeatureOp,
  FountainFeatureOp,
  TreeFeatureOp,
  BushFeatureOp,
  DecoratorOp,
  // Reserved for Phase 3 / post-4.0:
  // CampfireOp, DenMouthOp, TombEntranceOp,
}

table FeatureFlags {
  shadows_enabled: bool = true;
  hatching_enabled: bool = true;
  atmospherics_enabled: bool = true;
  macabre_detail: bool = false;
  vegetation_enabled: bool = true;
  interior_finish: string;
}

table FloorIR {
  major: uint32;
  minor: uint32;
  width_tiles: uint32;
  height_tiles: uint32;
  cell: uint32 = 32;
  padding: uint32 = 32;
  floor_kind: FloorKind;
  theme: string;
  base_seed: uint64;
  flags: FeatureFlags;
  regions: [Region];
  ops: [Op];                    // emitter-sequenced; renderer dispatches in order
}

enum FloorKind : byte { Dungeon = 0, Cave = 1, Building = 2, Surface = 3 }

table TileCoord { x: int; y: int; tag: string; }
table RectRoom  { x: int; y: int; w: int; h: int; region_ref: string; }

root_type FloorIR;
```

### What disappears at 4.0

Removed tables and op-union variants:

- `WallsAndFloorsOp` — replaced by `FloorOp` + `ExteriorWallOp`
- `BuildingExteriorWallOp` — folded into `ExteriorWallOp` with
  `WallStyle ∈ {MasonryBrick, MasonryStone}`
- `BuildingInteriorWallOp` — folded into `InteriorWallOp` with
  `WallStyle ∈ {PartitionStone, PartitionBrick, PartitionWood}`
- `EnclosureOp` — folded into `ExteriorWallOp` with
  `WallStyle ∈ {Palisade, FortificationMerlon}` plus
  `corner_style`
- `Gate` — folded into `Cut` with door / gate styles in
  `CutStyle`
- `GenericProceduralOp` — escape hatch retires (was unused
  since Phase 1 transitional period)
- All SVG-string fields:
  - `WallsAndFloorsOp.{wall_segments, wall_extensions_d, smooth_fill_svg, smooth_wall_svg, cave_region}`
  - `FloorDetailOp.{room_groups, corridor_groups}`
  - `TerrainDetailOp.{room_groups, corridor_groups}` (already
    dropped at 3.0)

Removed enums (subsumed by `WallStyle` / `CutStyle`):
- `EnclosureStyle`
- `WallMaterial`
- `InteriorWallMaterial`
- `GateStyle` (renamed → `CutStyle`)

### What's preserved unchanged

- `Polygon` table (multi-ring) — still used for `Region.polygon`
  and hatch's containment-test predicates
- `Region` table and `regions[]`
- `ShadowOp`, `HatchOp`, `TerrainTintOp`, `FloorGridOp`,
  `FloorDetailOp`, `ThematicDetailOp`, `TerrainDetailOp`,
  `StairsOp`, `DecoratorOp`, the four `*FeatureOp` ops —
  schemas substantially unchanged (some clip_region fields
  drop because clip envelopes go away)
- `FeatureFlags` and `FloorIR` root structure
- Determinism contract (same seeds, same RNG offsets per op)

## 4. Layer / paint ordering

Paint order is **emitter-enforced via op sequence in `FloorIR.ops`**.
The renderer is a flat dispatch loop with no layer envelopes.

The emitter populates `ops[]` in this sequence (by IR kind):

| Slot | Op kind                       | Notes                                              |
| ---- | ----------------------------- | -------------------------------------------------- |
| 1    | `ShadowOp`(s)                 | drop-shadows under floors                          |
| 2    | `FloorOp`(s)                  | every floor area, all kinds (dungeon, cave, building, corridor) |
| 3    | `InteriorWallOp`(s)           | partitions, smooth-room interior walls             |
| 4    | `RoofOp`(s)                   | building shingles                                  |
| 5    | `ExteriorWallOp`(s)           | dungeon perimeter, building exteriors, palisades, fortifications |
| 6    | `TerrainTintOp`(s)            | water/lava/grass/chasm tints                       |
| 7    | `FloorGridOp`(s)              | wobbly-grid overlay                                |
| 8    | `FloorDetailOp`(s)            | cracks / scratches / stones / clusters              |
| 9    | `DecoratorOp`(s)              | cobblestone / brick / flagstone / etc.             |
| 10   | `ThematicDetailOp`(s)         | webs / bones / skulls                              |
| 11   | `TerrainDetailOp`(s)          | water ripples / lava cracks / chasm hatch          |
| 12   | `StairsOp`(s)                 | stair fixtures                                     |
| 13   | `WellFeatureOp` / `FountainFeatureOp` / `TreeFeatureOp` / `BushFeatureOp` | placeable fixtures |
| 14   | `HatchOp`(s)                  | outer-band hatching (last, overlays everything outside dungeon) |

The previous "layers 100 / 200 / 300 / 350 / …" gap-numbering
goes away — paint order is now explicitly the array order. The
renderer's dispatch table maps `op.type → handler`, and ops fire
in array order.

`HatchOp` moves to the end of the sequence because its
outer-band classification replaces the old clip-envelope
mechanism; with the stamp model, hatch paints over everything
the dungeon doesn't cover, so it lands last.

## 5. The Painter trait (Phase 2)

Phase 2 introduces a `Painter` trait that abstracts the
rasteriser backend. `primitives::*` (Rust per-primitive emitters
in `crates/nhc-render/src/primitives/`) swap their `Vec<String>`
SVG-fragment output for `&mut dyn Painter` calls; both
backends — `SkiaPainter` (drives tiny-skia) and `SvgPainter`
(writes SVG text) — implement the same trait surface.

```rust
trait Painter {
    // Style A — high-level shape primitives. Each method maps
    // cleanly to one SVG element on the SvgPainter side and
    // builds a tiny-skia path on the SkiaPainter side.

    fn fill_rect(&mut self, rect: Rect, paint: &Paint);
    fn stroke_rect(&mut self, rect: Rect, paint: &Paint, stroke: &Stroke);
    fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint);
    fn fill_ellipse(&mut self, cx: f32, cy: f32, rx: f32, ry: f32, paint: &Paint);
    fn fill_polygon(&mut self, vertices: &[Vec2], paint: &Paint, fill_rule: FillRule);
    fn stroke_polyline(&mut self, vertices: &[Vec2], paint: &Paint, stroke: &Stroke);
    fn fill_path(&mut self, path: &PathOps, paint: &Paint, fill_rule: FillRule);
    fn stroke_path(&mut self, path: &PathOps, paint: &Paint, stroke: &Stroke);

    // Group-opacity scope — paints rendered between begin_group
    // and end_group composite as one unit at the group's opacity.
    // Required for SVG-spec-compliant compositing of overlapping
    // children inside a `<g opacity="…">` envelope. See note
    // below on why per-element alpha is insufficient.
    fn begin_group(&mut self, opacity: f32);
    fn end_group(&mut self);
}

struct Paint { color: Color }
struct Stroke { width: f32, line_cap: LineCap, line_join: LineJoin }
```

### Why group-opacity ops are required (and per-element alpha is not enough)

An earlier draft of this design omitted `begin_group` /
`end_group` on the reasoning that the stamp model with
flat dispatch means each op stamps independently and per-
element alpha covers any opacity need. **That reasoning is
wrong.** Phase 5.10 of the parent IR migration plan
(`plans/nhc_ir_migration_plan.md`, commit `8de4f57`)
specifically replaced per-element alpha with offscreen-buffer
compositing in `crates/nhc-render/src/transform/png/fragment.rs`
because per-element alpha **over-darkens overlapping children
inside a `<g opacity>` envelope** — the SVG spec composites the
whole group as one image at the group opacity, not by
multiplying alpha per child. Phase 5.10's bisect named the
seed99 cave `terrain_detail` layer (water ripple paths overlap)
as the worst offender; per-element alpha drifted the layer's
parity gate by 0.66 % and the offscreen-buffer fix brought it to
0.013 %.

Twelve primitives in `crates/nhc-render/src/primitives/` emit
`<g opacity>` envelopes today: `cobblestone`, `floor_detail`,
`cart_tracks`, `flagstone`, `brick`, `opus_romano`,
`field_stone`, `terrain_detail`, `thematic_detail`, `wood_floor`,
`hatch`, `shadow`. The Painter port for each of these in
Phase 2 wraps the relevant emit block in
`painter.begin_group(opacity); ...; painter.end_group();`.
Primitives that use only per-element opacity (`stairs`, `well`,
`tree`, `bush`, `terrain_tints`) need no group calls.

### SkiaPainter

Drives `tiny_skia::Pixmap`. Replaces the per-handler tiny-skia
calls scattered across `transform/png/*.rs`; replaces
`paint_fragment` and `transform/png/{fragment, svg_attr,
path_parser}.rs` (which all retire because their only caller
was the SVG-fragment round-trip).

`begin_group` / `end_group` lift the existing
`transform/png/fragment.rs::paint_offscreen_group` mechanism:
allocate one same-size scratch pixmap once at
`floor_ir_to_png` entry; `begin_group` pushes the active
pixmap onto a stack and swaps to the scratch (cleared);
`end_group` blits the scratch onto the previously-active
pixmap via `Pixmap::draw_pixmap(0, 0, scratch, &PixmapPaint
{ opacity, blend_mode: SourceOver, .. })` and pops the
stack. Nested groups use a shallow Vec-based stack — the
emitter never nests beyond one level today, but the mechanism
supports it.

### SvgPainter

Writes a String buffer with semantic SVG elements. Each
`Painter` call appends one element (e.g. `fill_rect` → `<rect
x="…" y="…" …/>`, `fill_circle` → `<circle cx="…" cy="…" …/>`).
Replaces `nhc/rendering/ir_to_svg.py` and the per-handler
`_draw_*_from_ir` Python functions.

`begin_group(opacity)` writes `<g opacity="X">`; `end_group`
writes `</g>`. Trivial — SVG carries the group-opacity
semantics natively.

### CanvasPainter (Phase 3 / WASM)

Drives an HTML5 Canvas2D context via `wasm-bindgen`. The
roughly-50-lines body the parent migration plan's Phase 11
pencilled in for a Canvas opcode emitter becomes obsolete —
Phase 2 already did the abstraction work; CanvasPainter
implements the trait directly.

`begin_group` / `end_group` use an `OffscreenCanvas` (also
exposed via wasm-bindgen): redirect drawing to the offscreen
context inside the group; `end_group` runs `ctx.drawImage(
offscreen, 0, 0)` with `ctx.globalAlpha = opacity` against the
parent context. Same shape as the Skia offscreen pattern, just
with Canvas2D primitives.

## 6. Cross-rasteriser story

Three transforms, one IR:

```
                ┌──────────────────────────┐
                │  FloorIR FlatBuffer      │
                │  (the contract)          │
                └────────────┬─────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
 ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
 │ ir_to_png    │    │ ir_to_svg    │    │ ir_to_canvas │
 │ (Rust)       │    │ (Rust)       │    │ (Rust→WASM)  │
 │              │    │              │    │              │
 │ tiny-skia +  │    │ String       │    │ Canvas2D ctx │
 │ SkiaPainter  │    │ + SvgPainter │    │ + Canvas-    │
 │              │    │              │    │   Painter    │
 └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
        │                   │                   │
        ▼                   ▼                   ▼
   PNG bytes         SVG string         Canvas pixels
```

All three backends share `crates/nhc-render/src/primitives/`
(per-primitive emitters that call into the `Painter` trait).
The IR → primitive dispatch lives in
`crates/nhc-render/src/transform/` with one module per backend
(`png/`, `svg/`, `canvas/` — the latter is Phase 3 WASM).

PyO3 exports:
- `nhc_render.ir_to_png(buf, scale=1.0, layer=None) -> bytes`
- `nhc_render.ir_to_svg(buf) -> str` (NEW at Phase 2)
- `nhc_render.svg_to_png(svg) -> bytes` (existing, used for
  parity testing only)

### Parity gate

`tests/unit/test_ir_png_parity.py` compares pixel-level output
between two paths: `ir_to_svg(buf) → svg_to_png(svg)` (Rust resvg
+ usvg under the hood) versus `ir_to_png(buf)` direct (Rust
tiny-skia). PSNR ≥ 30 dB at every fixture. Plus a small set of
structural sanity asserts on the SVG output (envelope present,
top-level structure matches expected layout, no broken
`viewBox`, etc.). Byte-equal SVG is not gated — `SvgPainter`
output is allowed to drift from the legacy Python output.

## 7. Mapping from 3.0 to 4.0

Reference table for migrating emitter and consumer code:

| 3.0 op / field                                       | 4.0 equivalent                                         |
| ---------------------------------------------------- | ------------------------------------------------------ |
| `WallsAndFloorsOp.rect_rooms`                        | one `FloorOp { outline: rect-poly, style: DungeonFloor }` per room + `ExteriorWallOp { outline: rect-poly, style: DungeonInk, cuts: doors }` per room |
| `WallsAndFloorsOp.corridor_tiles`                    | one `FloorOp` per corridor stretch (or per tile)       |
| `WallsAndFloorsOp.smooth_room_regions` + `smooth_fill_svg` | per-room `FloorOp { outline: smooth-poly / circle / pill descriptor, style: DungeonFloor }` |
| `WallsAndFloorsOp.smooth_wall_svg` + `wall_extensions_d` | per-room `ExteriorWallOp { outline: smooth-poly / circle / pill, cuts: door + opening cuts, style: DungeonInk }` |
| `WallsAndFloorsOp.cave_region`                        | `FloorOp { outline: cave-poly, style: CaveFloor }` + `ExteriorWallOp { outline: cave-poly, style: DungeonInk }` |
| `WallsAndFloorsOp.wall_segments`                      | included in the per-room `ExteriorWallOp` outlines (rect-room outlines walked instead of per-tile edges) |
| `BuildingExteriorWallOp { region_ref, wall_material }` | `ExteriorWallOp { outline: building-poly, style: MasonryBrick \| MasonryStone, cuts: doors }` |
| `BuildingInteriorWallOp { lines, material }`          | one `InteriorWallOp` per partition: `{ outline: open-polyline, style: PartitionWood \| PartitionStone \| PartitionBrick, cuts: doors }` |
| `EnclosureOp { polygon, style, gates, corner_style }` | `ExteriorWallOp { outline: enclosure-poly, style: Palisade \| FortificationMerlon, cuts: gates, corner_style }` |
| `Gate { edge_idx, t_center, half_px, style: GateStyle }` | `Cut { start: Vec2, end: Vec2, style: CutStyle (mapped) }` — emitter resolves `(edge_idx, t_center)` to absolute pixel coords |
| `GenericProceduralOp`                                  | retires entirely                                       |
| `tile.feature == "door_*"`                            | `Cut` on the enclosing room's `ExteriorWallOp`         |
| `tile.feature == "trap" / "teleporter"`               | not in IR (frontend overlay)                           |
| `tile.feature == "well" / "fountain" / "tree" / "bush" / "stairs_up" / "stairs_down"` | already on dedicated ops; unchanged           |
| `tile.feature == "ore_deposit"`                       | `DecoratorOp.ore_deposit[]` (already structured)       |
| `tile.feature == "campfire" / "den_mouth" / "tomb_entrance"` | not in 4.0 IR; ops added later (see §8)         |

## 8. What's NOT in 4.0 (deferred)

These were considered during the design pass and deferred:

- **`TileGrid` (shared per-tile world snapshot).** A flat
  packed array of (terrain × zone × decorator) per tile. Would
  unblock B-state op-shrinks where ops carry only `region_ref`
  and the renderer derives tiles. Dropped because the four
  ops that genuinely need per-tile classification (`HatchOp`,
  `FloorDetailOp`, `ThematicDetailOp`, `TerrainDetailOp`)
  already carry small structured tile lists; the marginal gain
  of moving them to a shared grid doesn't justify the schema
  cost. Adding `TileGrid` later is a non-breaking additive
  change.

- **Per-marker ops (`CampfireOp`, `DenMouthOp`, `TombEntranceOp`).**
  These are typed-gameplay narrative markers
  (campfires, beast-lair entrances, sealed tombs). Today they
  ride as `tile.feature` strings; 4.0 leaves them in that
  state. Adding them as dedicated ops happens when typed
  gameplay's needs clarify their per-instance fields (lit
  state for campfires, seal type for tombs, etc.).

- **Region-direct tile membership.** `Region.tiles: [TileCoord]`
  per-region tile lists. Could replace per-op `tiles[]` for
  ops that filter by region. Not adopted because the
  hatch / detail ops would then need cross-region queries
  ("FLOOR tiles in any room") that are easier to express via
  per-op tile lists than via per-region membership.

- **Higher-level intent ops (full B-state).** Ops like
  `HatchOp { region_in, region_out, style, seed }` where the
  renderer derives every tile-level decision from regions and
  a tile grid. Foundational work for that (TileGrid,
  region_ref dispatch) is not in 4.0; adding it later is a
  minor schema bump (additive new fields) rather than a major
  one.

- **Floor area / pit holes.** `FloorOp.outline` is single-ring
  (`Outline.cuts: []`). A floor with a hole carved out (a pit
  in the dungeon floor) would need either multi-ring outlines
  or a separate "void" `FloorOp` stamp painted on top. The
  current world generator doesn't produce floors with holes,
  so this is deferred.

## 9. Phased migration

The IR cut from 3.0 to 4.0 is the structural change; Phase 2
(Painter trait) and Phase 3 (WASM Canvas) are renderer-only
refactors that don't touch the schema.

| Phase | Schema | Net work | Atomicity |
| ----- | ------ | -------- | --------- |
| **0** — Dead-code cleanup | 3.1 | Drop `FloorDetailOp.{room,corridor}_groups` consumer reads, drop `GenericProceduralOp` from live dispatch. No fixture changes; pixel-equivalent. | additive, zero risk |
| **1** — IR redesign       | 4.0 | Outline + Cut + CutStyle + WallStyle + FloorStyle. FloorOp / InteriorWallOp / RoofOp / ExteriorWallOp. Doors as `Cut` entries. Drop WallsAndFloorsOp / BuildingExteriorWallOp / BuildingInteriorWallOp / EnclosureOp / GenericProceduralOp / all SVG-string fields. Stamp model with flat dispatch. Tag `ir-schema-4.0`. | atomic break (one cut) |
| **2** — Painter trait + all-Rust render | (no bump) | Define `Painter` trait. Implement `SkiaPainter` (replaces `transform/png/fragment.rs`). Write `SvgPainter`; add `nhc_render.ir_to_svg(buf)` PyO3 export. Port `primitives::*` from `Vec<String>` to `&mut dyn Painter`. Retire `nhc/rendering/ir_to_svg.py`, `transform/png/{fragment,svg_attr,path_parser}.rs`. | renderer-only refactor |
| **3** — WASM Canvas       | (no bump) | `nhc-render-wasm` crate + `CanvasPainter` impl. ~50 lines of dispatcher + the trait impl. The parent migration plan's Phase 11 op-stream design becomes obsolete. | renderer-only |

Each phase is independently shippable. The 4.0 cut forces one
disk-cache regeneration via the `(major, minor)` gate in
`nhc/core/autosave.py` (same behaviour as 1.x → 2.0 and
2.x → 3.0 cuts).

### Open question for Phase 1 sequencing

Door-as-`Cut` lands at 4.0 (decided as "unified" timing — see
the design conversation). This requires:
- The world generator to produce door positions in a form the
  emitter can resolve to outline cut coordinates (today it sets
  `tile.feature = "door_*"`).
- The frontend overlay to consume door state from the world
  state directly (it already does; the overlay reads from
  `level.tiles[y][x].feature`, not from the IR).

The static IR's renderer does NOT distinguish closed / open /
locked door states — every door cut paints the same way (a wall
break with the door visual at the cut location, picked from
`CutStyle`). Door state is dynamic and frontend-only.

### Door-state vs door-static separation

The frontend's door visual today comes from
`nhc/web/static/js/...` reading `level.tiles[y][x].feature` and
overlaying door sprites. After 4.0:
- The IR encodes door **locations** (as outline `Cut`s) and
  **types** (`CutStyle::DoorWood`, `DoorStone`, `DoorIron`,
  `DoorSecret`).
- The frontend reads door **state** (open / closed / locked)
  from the world state (the same `level.tiles[y][x].feature`
  source it already uses).
- The static map shows wall + door visual at the cut position;
  the frontend overlays the dynamic state on top.

`CutStyle::DoorSecret` is a special case: the static renderer
treats it as `CutStyle::None` (paints the wall continuous, no
door visual) so the player can't see secret doors on the
static map. The frontend handles discovery transitions by
swapping the rendered chunk after the player searches.

## 10. Test strategy

### Fixtures

The 14 PSNR fixtures in `tests/fixtures/floor_ir/` regenerate
at the 4.0 cut. Each fixture's `floor.json` (canonical IR JSON
dump) and `floor.png` (reference PNG) get rebuilt from the
post-4.0 emitter via `tests/samples/regenerate_fixtures.py`.

Existing fixtures cover:
- seed42 rect dungeon (rect rooms, no smooth shapes)
- seed7 octagon crypt (smooth-room outlines + gapped doors)
- seed99 cave cave (cave region + curved walls)
- seed1 dungeon, seed101 keep (buildings: exterior walls,
  partitions, roofs)
- seed_palisade, seed_fort (enclosures: palisade,
  fortification)

If 4.0 introduces shapes the existing fixtures don't exercise,
add new fixtures (`seed_circle_room`, `seed_pill_room`).

### Parity

Per-fixture PSNR thresholds:
- ≥ 50 dB for the structured-only path vs. the prior 3.0
  baseline at every fixture (effectively byte-equal — the
  structured form rebuilds the same paths the SVG-fragment
  parser was reconstructing).
- ≥ 30 dB cross-rasteriser (Rust `ir_to_svg` →
  `nhc_render.svg_to_png` vs. Rust `nhc_render.ir_to_png`
  direct). Loosened from byte-equal because `SvgPainter`
  output is allowed to drift from the legacy Python output.

### Architectural guards

- `tests/unit/test_no_import_random_in_rendering.py` keeps
  `import random` out of the IR-emit shells. The structured
  IR carries no per-tile RNG state — every randomised primitive
  derives its own seed from `op.seed`.
- A new test (`test_no_svg_strings_in_ir.py`) walks every op
  table at 4.0+ and asserts no field is typed as `[string]`
  carrying SVG markup. The schema's remaining string fields
  (`region_ref`, `theme`, hex colour fields, `id`, `key`,
  `value`) are structured identifiers / metadata, not drawing
  commands.

## 11. Open questions / future evolution

These are out of scope for 4.0 but worth flagging for future
plans:

- **TileGrid + B-state op-shrink.** When the four detail / hatch
  ops grow expensive enough to justify a shared grid (or when
  WASM Canvas's bandwidth profile favours it), an additive
  bump adds `TileGrid` and lets ops shrink to `region_ref` +
  params.

- **Region-direct tile lists.** As above — additive future
  field on `Region`.

- **Per-instance fixture state.** Campfire `lit: bool`, tomb
  entrance `sealed: bool`, etc. Each fixture op grows
  per-instance fields as typed gameplay needs them.

- **Floor with holes / pits.** Multi-ring `Outline` (or "void"
  `FloorOp` stamps).

- **Animated visuals.** Water ripples, lava flows, etc., are
  static at 4.0 (rendered once, no per-frame update). If
  animation needed: either client-side WebGL on top of the
  static IR-rendered floor, or a parallel "animation IR"
  carrying per-op state vs frame.

## 12. Critical files (post-4.0)

```
nhc/rendering/ir/
├── floor_ir.fbs                  # the schema (4.0)
├── _fb/                          # generated FB bindings (Python)
└── dump.py                       # IR → JSON for debug

nhc/rendering/
├── ir_emitter.py                 # Level → FloorIR translator
├── _floor_layers.py              # per-op _emit_*_ir helpers
└── (ir_to_svg.py — RETIRED at Phase 2)

crates/nhc-render/
├── src/
│   ├── ir/                       # generated FB bindings (Rust)
│   ├── primitives/               # per-primitive emitters (call &mut dyn Painter)
│   ├── transform/
│   │   ├── png/                  # SkiaPainter dispatch
│   │   ├── svg/                  # SvgPainter dispatch (NEW Phase 2)
│   │   └── canvas/               # CanvasPainter dispatch (NEW Phase 3)
│   └── painter.rs                # the Painter trait
└── Cargo.toml

crates/nhc-render-wasm/           # NEW Phase 3
└── (CanvasPainter glue)
```

## 13. Determinism contract

Unchanged from 3.0:
- `base_seed` is the FloorIR root field.
- Each randomised op carries its own `seed` field, computed as
  `base_seed + offset` (offsets in the table below).
- Each primitive's RNG is a Rust `rand_pcg::Pcg64Mcg` seeded
  with the op's seed.
- Per-tile rolls use the same RNG offsets as 3.0:

| Op                        | Offset                  |
| ------------------------- | ----------------------- |
| `HatchOp` (room)          | `+ 77`                  |
| `HatchOp` (corridor)      | `+ 7`                   |
| `HatchOp` (hole)          | shape-derived           |
| `FloorDetailOp`           | `+ 99`                  |
| `ThematicDetailOp`        | `+ 199`                 |
| `TerrainDetailOp`         | `+ 200`                 |
| `DecoratorOp`             | `+ 333`                 |
| `RoofOp`                  | `+ 0xCAFE + bldg_idx`   |
| `EnclosureOp` (legacy)    | `+ 0xE101 + edge_idx`   |
| `WellFeatureOp` etc.      | per-feature offsets     |

Cross-rasteriser determinism: PSNR ≥ 50 dB at every fixture
between SkiaPainter and SvgPainter→resvg paths.

## 14. Cross-references

- `design/map_ir.md` — pre-4.0 contract; this doc supersedes
  §5 / §6 / §7 once 4.0 lands.
- `design/ir_primitives.md` — per-primitive determinism specs;
  needs section-level updates at 4.0 to reflect retired ops.
- `design/dungeon_generator.md` — door-position output; the
  generator continues to emit per-tile door features, the
  4.0 emitter resolves them to outline cuts.
- `plans/nhc_ir_migration_plan.md` — the parent migration plan
  through Phases 0 – 10. This v4 design closes out Phase 1's
  "transitional storage" comments and absorbs the parent plan's
  Phase 11 (WASM Canvas) into Phase 3 of this document via the
  Painter trait.
