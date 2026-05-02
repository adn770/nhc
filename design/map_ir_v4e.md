# Floor IR v4e — region-keyed pure-IR contract

**Status:** Proposed evolution of `design/map_ir_v4.md`. Same major
schema (4.x — `file_identifier "NIR4"`) reached through additive
minor bumps; replaces v4.md once v4e lands. Pre-4.0 contract in
`design/map_ir.md` remains the historical reference.

Two outcomes the v4 design does not reach but v4e does:

1. **Regions own geometry.** Every spatial primitive (room, cave,
   building, dungeon, site, enclosure) lives in `regions[]` with a
   single `Outline`. Paint ops reference regions by `region_ref`
   instead of carrying their own outline. The same octagon-room
   region drives hatch-around, floor fill, and wall stroke without
   duplicating its vertex list.
2. **No SVG fragment text crosses any boundary in the pipeline.**
   The IR carries no SVG strings (already true at 4.0). v4e removes
   the last carrier in the rendering crate: the per-primitive
   modules in `crates/nhc-render/src/primitives/` that today emit
   `Vec<String>` SVG fragments port to direct paint primitives via
   the `Painter` trait. Both `tiny_skia::Pixmap` and
   `String`-buffered SVG come out of the same primitive code path.

A third outcome falls out: clip envelopes (`<g clip-path>`,
`tiny_skia::Mask`) become a **renderer-internal concern**, never an
IR concept. The IR ships paint intent — "fill region R with style
S", "stroke region R's perimeter, breaking at cuts C", "hatch the
band outside region D" — and the renderer translates that into the
backend's clipping primitive on demand.

## 1. Goals

Three outcomes drive v4e:

1. **Pure structural IR.** No SVG fragment text in any field of
   any op. The schema's only string fields are structured
   identifiers (region IDs, theme names, hex colours).
2. **Regions own geometry; ops own paint intent.** Outline-bearing
   ops (`FloorOp`, `ExteriorWallOp`, `RoofOp`, `ShadowOp`)
   reference regions by `region_ref`. The renderer resolves the
   reference to fetch the outline and applies paint accordingly.
3. **All-Rust render through the `Painter` trait.** Both PNG and
   SVG emerge from the same `crates/nhc-render/src/primitives/`
   code path, parameterised by which `Painter` implementation
   drives the calls. The Python `ir_to_svg.py` painter retires;
   the SVG-fragment parser modules in `transform/png/` retire;
   the `crates/nhc-render/src/primitives/*.rs` `Vec<String>`
   return type changes to `&mut dyn Painter`.

A consequence: the rasteriser stays **flat** — a single dispatch
loop over `ops[]`, no layer envelopes, no offscreen scratch
buffers (except where `begin_group`/`end_group` requires one).

## 2. Principles

### Stamp model with region-keyed paint intent

The canvas starts as `Pixmap::fill(parchment_bg)`. Each op carries
"what to paint" (style + parameters) and "where to paint"
(`region_ref` or per-tile coords). The renderer dispatches each op
in array order, fetches the referenced region's geometry, and
calls into the active `Painter`:

```
canvas = Pixmap.fill(BG)
for op in fir.ops:
    handler = handlers[op.type]
    handler(op, canvas, fir.regions, painter)
canvas.encode_png() / painter.into_svg_string()
```

No per-op clip envelopes. No `<g opacity>` wrappers in the IR.
Hatch's outer-band predicate plus per-tile candidate filter
replaces the dungeon-clip envelope it used to ride in.

### Regions are the geometric source of truth

Every named area in `regions[]` carries an `Outline` — a single
descriptor that supports polygon vertices, multi-ring polygons
(for dungeon-with-holes cases), or parametric `Circle` / `Pill`
shapes. Multiple paint ops can reference the same region without
duplicating its vertex list:

| Octagon-room paint pass | Op kind         | Reads          |
| ----------------------- | --------------- | -------------- |
| Drop shadow             | `ShadowOp`      | region.outline |
| White floor fill        | `FloorOp`       | region.outline |
| Black perimeter stroke  | `ExteriorWallOp`| region.outline |
| Hatch around (outer)    | `HatchOp`       | region_out=dungeon, anti-region |

Walls add `cuts: [Cut]` directly on the wall op (door / gate
openings), not on the region. The same region might host an
ExteriorWallOp (stone perimeter) and an InteriorWallOp (wood
partition crossing the room interior) with completely different
cut patterns. Cuts are paint-op concerns; geometry is region
concerns.

### Ops are paint stamps

Each op carries:
- A reference to its target region (`region_ref`) **or** raw
  per-tile coordinates (`tiles[]`) when the op is tile-driven
  (hatch, terrain tints, floor grid, floor detail, decorator
  variants, terrain detail).
- Style enums (`WallStyle`, `FloorStyle`, `CutStyle`, `RoofStyle`).
- Op-specific parameters (`seed`, `theme`, `tint`, `cuts`,
  `corner_style`, `rng_seed`, …).

There is no shared world snapshot. Each op is self-contained when
combined with its referenced region. Detail ops keep small
structured tile lists; fixture ops carry placement coordinates.

### No SVG fragment text in the pipeline

The IR has no SVG-string fields. v4e additionally removes the SVG
fragment text that today flows between
`crates/nhc-render/src/primitives/` (Rust per-primitive emitters)
and `crates/nhc-render/src/transform/png/` (per-handler SVG
parsers + tiny-skia rasteriser):

- Today: each `primitives/*.rs` module returns `Vec<String>` of
  SVG fragments; `transform/png/` parses the fragments back into
  attributes (`extract_f32`, `parse_path_d`) and rasterises via
  tiny-skia.
- v4e: each `primitives/*.rs` module accepts `&mut dyn Painter`
  and calls `painter.fill_rect(…)`, `painter.stroke_path(…)`,
  `painter.begin_group(opacity)`, etc. The `Painter` trait has
  two implementations: `SkiaPainter` (drives tiny-skia directly)
  and `SvgPainter` (writes SVG element strings).

The fragment-parser modules
(`transform/png/{fragment, svg_attr, path_parser}.rs`) retire.
The Python `nhc/rendering/ir_to_svg.py` retires (SVG output now
comes from `nhc_render.ir_to_svg(buf)` PyO3 export).

### Minimal IR, consumer-derived geometry

Same principle as v4: when primary tile-membership data is enough
to reconstruct a visual deterministically, the IR ships primary
data only. The consumer derives visual artefacts at consume time.
v4e applications:

- **Cave perimeter geometry.** The cave region's outline carries
  the raw `unary_union` exterior ring of the merged cave-tile
  set. Both the `FloorOp` and the `ExteriorWallOp` referencing
  that region apply `buffer(0.3 × CELL) + jitter + smooth_closed_path`
  with `random.Random(base_seed + 0x5A17E5)` to reproduce the
  organic cave geometry. The IR carries no jittered coords.
- **Corridor walls.** `CorridorWallOp.tiles` is the tile list;
  the consumer derives wall edges by checking each tile's
  neighbours against the union of every `FloorOp`'s tile coverage
  (rect rooms cover their bbox; smooth rooms cover their polygon
  via `Region.outline.contains()`; corridors cover one tile each).

### Cross-language contract

The IR is a FlatBuffers binary blob with `file_identifier "NIR4"`.
Producer: `nhc/rendering/ir_emitter.py` (Python; the world /
dungeon generator's view-builder). Consumer: `nhc-render` Rust
crate, exposed via PyO3:

- `nhc_render.ir_to_png(buf, scale=1.0, layer=None) -> bytes`
- `nhc_render.ir_to_svg(buf, layer=None) -> str` (NEW after v4e)

A future `nhc-render-wasm` crate exposes equivalent entry points
to a browser Canvas2D backend (Phase 3 / Painter trait).

## 3. The IR (FlatBuffers schema 4.x)

```
namespace nhc.ir;

file_identifier "NIR4";          // NHC IR Floor v4 (minor versions
                                 // 0..N evolve within this identifier)
file_extension "nir";

// ── Geometric primitives ─────────────────────────────────────

table Vec2 { x: float; y: float; }

// PathRange — partitions a flat Vec2 list into rings for
// multi-ring polygons (e.g. dungeon-polygon with cave-wall holes).
struct PathRange { start: uint32; count: uint32; is_hole: bool; }

// Outline — single source of truth for any region or wall
// geometry. Three descriptor variants:
//
// - Polygon: vertices populated; rings empty for single-ring,
//   non-empty for multi-ring (dungeon, multi-room cave with
//   inner cavities).
// - Circle: cx, cy, rx populated (rx == ry expected).
// - Pill:   cx, cy, rx, ry populated.
//
// Outlines are pure geometry. Wall ops carry their own cuts list
// (see ExteriorWallOp / InteriorWallOp); regions never carry cuts.
enum OutlineKind : ubyte {
  Polygon = 0,
  Circle  = 1,
  Pill    = 2,
}

table Outline {
  vertices: [Vec2];               // polygon vertex list
  rings: [PathRange];             // multi-ring partitioning; empty == single ring
  closed: bool = true;            // false for open polylines (interior partitions)
  descriptor_kind: OutlineKind = Polygon;
  cx: float; cy: float;           // Circle / Pill descriptor centre
  rx: float; ry: float;           // Circle / Pill descriptor radii
}

// Cut — one opening on a wall outline. start / end are pixel-
// space coordinates on the perimeter; the wall renderer breaks
// the stroke between them. style picks the optional door / gate
// visual at the cut.
table Cut {
  start: Vec2;
  end: Vec2;
  style: CutStyle = None;
}

enum CutStyle : ubyte {
  None            = 0,            // bare gap, no door visual
  WoodGate        = 1,            // enclosure gate (wood)
  PortcullisGate  = 2,            // enclosure gate (portcullis)
  DoorWood        = 3,            // standard interior door
  DoorStone       = 4,            // dungeon stone door
  DoorIron        = 5,            // dungeon iron door
  DoorSecret      = 6,            // looks like wall on the static map
  // future: DoorArch, DoorPortcullis, …
}

// ── Region — named area with id, kind, outline ────────────────

enum RegionKind : ubyte {
  Dungeon   = 0,                  // dungeon walkable polygon (multi-ring with cave holes)
  Room      = 1,                  // single dungeon room
  Cave      = 2,                  // merged cave system (one per disjoint group)
  Building  = 3,                  // building footprint (site mode)
  Site      = 4,                  // overall site bounds
  Enclosure = 5,                  // palisade / fortification ring
}

table Region {
  id: string (key);               // "dungeon" | "room.<n>" | "cave.<n>" | "building.<n>" | "site" | "enclosure"
  kind: RegionKind;
  outline: Outline;               // geometry; pure (no cuts)
  parent_id: string;              // optional nesting: "room.5".parent = "dungeon"
  shape_tag: string;              // "rect" | "octagon" | "circle" | "pill" | "temple" | "L" | "cross" | "hybrid" | "cave"
}

// ── Paint style enums ────────────────────────────────────────

enum WallStyle : ubyte {
  DungeonInk          = 0,        // 5px black stroke, round joins
  CaveInk             = 1,        // black stroke; reserved for future divergence
  MasonryBrick        = 2,        // running-bond masonry, brick fill
  MasonryStone        = 3,        // running-bond masonry, stone fill
  PartitionStone      = 4,        // dressed-stone interior partition
  PartitionBrick      = 5,        // brick interior partition
  PartitionWood       = 6,        // wooden plank partition
  Palisade            = 7,        // staked wooden ring
  FortificationMerlon = 8,        // crenelated battlement
  // future: PartitionMarble, MasonrySandstone, ReinforcedIron, …
}

enum FloorStyle : ubyte {
  DungeonFloor   = 0,             // #FFFFFF
  CaveFloor      = 1,             // #F5EBD8
  WoodFloor      = 2,             // #B58B5A (building wood)
  // future: TempleFloor, CryptFloor, CobbledStreet, …
}

enum CornerStyle : byte {
  Merlon   = 0,
  Diamond  = 1,
  Tower    = 2,
}

// ── Outline-keyed paint ops (region_ref consumers) ───────────

table FloorOp {
  region_ref: string;             // → Region
  style: FloorStyle;
  // Cave / wood-floor variants paint the same outline with a
  // different fill colour. The cave consumer additionally runs
  // the buffer + jitter + smooth pipeline keyed off
  // base_seed + 0x5A17E5; FloorOp itself stays flat.
}

table ExteriorWallOp {
  region_ref: string;             // → Region
  cuts: [Cut];                    // door / gate openings on the perimeter
  style: WallStyle;
  corner_style: CornerStyle = Merlon;
  rng_seed: uint64;               // Masonry / Palisade / Fortification per-edge derivation
}

// Roofs reuse a Building region's geometry to shingle on top.
enum RoofStyle : ubyte {
  Simple  = 0,
  Pyramid = 1,
  Gable   = 2,
}

table RoofOp {
  region_ref: string;             // → Region(kind=Building)
  style: RoofStyle = Simple;
  tint: string;                   // hex colour
  rng_seed: uint64;
}

// ── Off-region wall ops (own outline) ────────────────────────

// InteriorWallOp targets a partition INSIDE a region (open or
// closed polyline drawn within the parent room). The outline
// lives on the op because it is not a region perimeter.
table InteriorWallOp {
  outline: Outline;               // open or closed polyline
  cuts: [Cut];                    // door openings on the partition
  style: WallStyle;
}

// CorridorWallOp ships only the corridor floor-tile coordinates;
// the consumer derives wall edges by checking each tile's four
// neighbours against the union of every FloorOp's tile coverage
// (resolved through Region.outline containment for smooth-room
// FloorOps). Edges facing walkable space become openings; edges
// facing void become walls.
table CorridorWallOp {
  tiles: [TileCoord];
  style: WallStyle = DungeonInk;
}

// ── Shadows ──────────────────────────────────────────────────

enum ShadowKind : ubyte { Room = 0, Corridor = 1 }

table ShadowOp {
  kind: ShadowKind;
  region_ref: string;             // for Room kind
  tiles: [TileCoord];             // for Corridor kind
  dx: float = 3.0;
  dy: float = 3.0;
  opacity: float = 0.08;
}

// ── Hatch — region-bounded outer-band ────────────────────────

enum HatchKind : ubyte { Room = 0, Hole = 1, Corridor = 2 }

table HatchOp {
  kind: HatchKind;
  region_ref_in: string;          // hatched area (e.g. cave region for Hole kind)
  region_ref_out: string;         // exclusion (e.g. dungeon polygon)
  tiles: [TileCoord];             // candidate tile list (filtered at emit time)
  is_outer: [bool];               // parallel to tiles[]; 10 % RNG skip on outer
  extent_tiles: float = 2.0;
  seed: uint64;
  hatch_underlay_color: string;
}

// ── Per-tile detail layers (region-clipped) ──────────────────

// All five detail layers carry a region_ref the renderer uses to
// clip painting. Tiles outside the region are not painted (the
// renderer composes a Painter clip / mask from the region's
// outline). Tile lists carry the per-tile classification needed
// for room/corridor bucket routing.

table TerrainTintTile { x: int; y: int; kind: TerrainKind; }
table RoomWash         { rect: RectRoom; color: string; opacity: float; }

enum TerrainKind : ubyte { Water = 0, Lava = 1, Chasm = 2 }

table TerrainTintOp {
  region_ref: string;             // dungeon/site clip
  tiles: [TerrainTintTile];
  room_washes: [RoomWash];
}

table FloorGridTile { x: int; y: int; is_corridor: bool; }

table FloorGridOp {
  region_ref: string;             // dungeon clip
  tiles: [FloorGridTile];
  seed: uint64;
  theme: string;
  scale: float = 1.0;
}

table FloorDetailOp {
  region_ref: string;
  tiles: [TileCoord];
  is_corridor: [bool];
  seed: uint64;
  theme: string;
  // Wood-floor specifics — used when interior_finish == "wood":
  wood_tiles: [TileCoord];
  wood_building_polygon: [Vec2];  // legacy; will retire once WoodFloor FloorOp covers all building shapes
  wood_rooms: [RectRoom];
}

table ThematicDetailOp {
  region_ref: string;
  tiles: [TileCoord];
  is_corridor: [bool];
  wall_corners: [ubyte];          // bitmap: 0x01 TL / 0x02 TR / 0x04 BL / 0x08 BR
  seed: uint64;
  theme: string;
}

table TerrainDetailTile {
  x: int;
  y: int;
  kind: TerrainKind;
  is_corridor: bool;
}

table TerrainDetailOp {
  region_ref: string;
  tiles: [TerrainDetailTile];
  seed: uint64;
  theme: string;
}

// ── Decorator pipeline (per-variant tile lists, region-clipped) ──

enum CobblePattern : ubyte { Herring = 0, Stack = 1, Ashlar = 2, Rubble = 3, Mosaic = 4 }

table CobblestoneVariant { tiles: [TileCoord]; pattern: CobblePattern; }
table BrickVariant       { tiles: [TileCoord]; }
table FlagstoneVariant   { tiles: [TileCoord]; }
table OpusRomanoVariant  { tiles: [TileCoord]; }
table FieldStoneVariant  { tiles: [TileCoord]; }
table CartTracksVariant  { tiles: [TileCoord]; is_horizontal: [bool]; }
table OreDepositVariant  { tiles: [TileCoord]; }

table DecoratorOp {
  region_ref: string;             // dungeon clip
  cobblestone: [CobblestoneVariant];
  brick: [BrickVariant];
  flagstone: [FlagstoneVariant];
  opus_romano: [OpusRomanoVariant];
  field_stone: [FieldStoneVariant];
  cart_tracks: [CartTracksVariant];
  ore_deposit: [OreDepositVariant];
  seed: uint64;
  theme: string;
}

// ── Stairs ───────────────────────────────────────────────────

enum StairDirection : byte { Up = 0, Down = 1 }
table StairTile { x: int; y: int; direction: StairDirection; }

table StairsOp {
  stairs: [StairTile];
  theme: string;
  fill_color: string;             // active when theme == "cave"
}

// ── Surface fixtures (placement, no region clip needed) ──────

enum WellShape     : byte { Round = 0, Square = 1 }
enum FountainShape : byte { Round = 0, Square = 1, LargeRound = 2, LargeSquare = 3, Cross = 4 }

table WellFeatureOp {
  tiles: [TileCoord];
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
  tiles: [TileCoord];
  grove_tiles: [TileCoord];
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
  FloorOp,
  InteriorWallOp,
  RoofOp,
  ExteriorWallOp,
  CorridorWallOp,
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
  // Reserved for future per-marker ops:
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

enum FloorKind : byte { Dungeon = 0, Cave = 1, Building = 2, Surface = 3 }

table TileCoord { x: int; y: int; tag: string; }
table RectRoom  { x: int; y: int; w: int; h: int; region_ref: string; }

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
  regions: [Region];              // canonical geometry registry
  ops: [Op];                      // emitter-sequenced; renderer dispatches in array order
}

root_type FloorIR;
```

### What changes from v4

v4e differences from `design/map_ir_v4.md` §3:

| v4 field / shape                           | v4e equivalent                                 |
| ------------------------------------------ | ---------------------------------------------- |
| `Region.polygon: Polygon` (multi-ring)     | `Region.outline: Outline` (multi-ring via `rings[]`, plus Circle / Pill descriptors) |
| `Outline.cuts: [Cut]`                      | moved to op (`ExteriorWallOp.cuts`, `InteriorWallOp.cuts`); `Outline` is now pure geometry |
| `FloorOp.outline: Outline`                 | `FloorOp.region_ref: string`                   |
| `ExteriorWallOp.outline: Outline`          | `ExteriorWallOp.region_ref: string` + `cuts: [Cut]` |
| `RoofOp.region_ref: string` (already)      | unchanged                                      |
| `ShadowOp.region_ref: string` (already)    | unchanged                                      |
| `HatchOp.region_in / region_out: string`   | renamed `region_ref_in / region_ref_out`; semantics unchanged |
| (new) clip discipline on per-tile ops      | `TerrainTintOp / FloorGridOp / FloorDetailOp / ThematicDetailOp / TerrainDetailOp / DecoratorOp` gain `region_ref: string` for paint clipping bounds |
| (new) `RegionKind`                         | `Dungeon, Room, Cave, Building, Site, Enclosure` (replaces v4's value list of the same name) |
| (new) `Region.parent_id: string`           | optional nesting metadata                      |

### What's preserved unchanged from v4

- `Vec2`, `Cut`, `CutStyle`, `OutlineKind`, `WallStyle`,
  `FloorStyle`, `CornerStyle`, `RoofStyle`, `HatchKind`,
  `ShadowKind`, `TerrainKind`, `CobblePattern`,
  `StairDirection`, `WellShape`, `FountainShape`, `RegionKind`,
  `FloorKind`.
- All op-specific style + parameter fields (`seed`, `theme`,
  `tint`, `is_outer`, `is_corridor`, `wall_corners`, etc.).
- `FeatureFlags`, `FloorIR` root structure, `TileCoord`,
  `RectRoom`.
- Determinism contract (RNG offsets per op kind — see §13).

## 4. Region system

### Naming convention

Every region has a stable string id. The id format depends on the
region kind:

| RegionKind  | id format               | example                |
| ----------- | ----------------------- | ---------------------- |
| `Dungeon`   | `"dungeon"`             | `"dungeon"`            |
| `Room`      | `"room.<level_room_id>"`| `"room.r1"`            |
| `Cave`      | `"cave.<i>"`            | `"cave.0"`             |
| `Building`  | `"building.<i>"`        | `"building.2"`         |
| `Site`      | `"site"`                | `"site"`               |
| `Enclosure` | `"enclosure"`           | `"enclosure"`          |

The level / dungeon generator's room ids ride into the IR
verbatim, so debug tooling can cross-reference IR ops back to the
generator's room dictionary.

### Nesting

`Region.parent_id` records the containment hierarchy. Typical
shapes:

- A dungeon-mode IR has `Dungeon` as the root region; every
  `Room` and `Cave` region carries `parent_id = "dungeon"`.
- A building-mode IR has the parent `Site` plus per `Building`,
  per partition (interior-wall outlines live on
  `InteriorWallOp` rather than the region table).
- A site-mode IR (overland sub-hex / macro) has `Site` as the
  root with each `Building` and (optionally) `Enclosure` as
  children.

`parent_id == ""` means "no parent registered" — root regions
(`Dungeon`, `Site`) leave it empty.

### Multi-ring polygons

`Region.outline.descriptor_kind = Polygon` with non-empty
`rings[]` describes a multi-ring polygon. The first ring is the
exterior; subsequent rings (with `is_hole = true`) are interior
holes. The dungeon polygon for a level with both a smooth-walled
room and a cave system has:

- ring 0: dungeon outer perimeter (exterior, `is_hole = false`).
- ring 1+: cave-wall holes inside the dungeon (`is_hole = true`).

The renderer uses `FillRule::EvenOdd` for multi-ring outlines,
mirroring SVG's `fill-rule="evenodd"`.

### Region geometry types per kind

| RegionKind  | typical OutlineKind | notes                                    |
| ----------- | ------------------- | ---------------------------------------- |
| `Dungeon`   | Polygon (multi-ring)| includes cave-wall holes if any          |
| `Room.rect` | Polygon (4 verts)   | axis-aligned                             |
| `Room.octagon` | Polygon (8 verts) | chamfered rect                           |
| `Room.l_shape` | Polygon (6 verts) | notched rect                             |
| `Room.temple`  | Polygon          | apse / chevet polyline                   |
| `Room.cross`   | Polygon (12 verts)| + outline                                |
| `Room.hybrid`  | Polygon          | tessellated arc + rect halves            |
| `Room.circle`  | Circle           | descriptor (cx, cy, r)                   |
| `Room.pill`    | Pill             | descriptor (cx, cy, rx, ry)              |
| `Cave`         | Polygon          | raw `unary_union` exterior ring          |
| `Building`     | Polygon          | rect / L / octagon / circle perimeter    |
| `Site`         | Polygon          | tile-bbox rectangle                      |
| `Enclosure`    | Polygon          | site-perimeter polyline                  |

## 5. Paint operations

Each op kind names a **what** (paint operation) and a **where**
(region or per-tile coords). The renderer fetches the where,
applies the what.

### Outline-keyed ops (region_ref)

- **`FloorOp`** — fills the referenced region's outline with
  `style`'s colour. For `CaveFloor`, the consumer additionally
  applies `buffer + jitter + smooth_closed_path` keyed off
  `base_seed + 0x5A17E5`. For `WoodFloor`, paints over previously
  drawn `DungeonFloor` ops in op order (building wood-floor
  covers room interiors).

- **`ExteriorWallOp`** — strokes the referenced region's outline
  with `style`'s paint, breaking the stroke at every entry in
  `cuts[]`. Door cuts keep the stroke visible at the door
  position (the door overlay paints separately); doorless gap
  cuts (smooth-room corridor abutments, rect-room corridor
  openings) leave a clean break. `corner_style` controls
  fortification / palisade corner geometry.

- **`InteriorWallOp`** — strokes the op's own `outline` (open or
  closed polyline within a parent region — typically a partition
  wall in a building). Cuts apply at door positions on the
  partition.

- **`RoofOp`** — shingles the referenced building region's
  outline with running-bond pattern + ridge lines. `tint` picks
  the mid-sunlit shade.

- **`ShadowOp`** — drop-shadow under a Room region (uses
  `region_ref`) or a corridor-tile set (uses `tiles[]`).

### Region-clipped per-tile ops

These ops carry per-tile data (the source of truth for which
tiles paint) plus `region_ref` for paint clipping bounds. The
renderer composes a clip from the region's outline and masks
painting accordingly.

- **`HatchOp`** — outer-band stones + lines outside `region_ref_out`
  (typically `"dungeon"`) and inside `region_ref_in` (typically
  `"site"` for surface mode, or `"dungeon"` for hole-style
  hatching).
- **`TerrainTintOp`** — water / lava / chasm tile tints inside
  the dungeon region.
- **`FloorGridOp`** — wobbly grid lines inside the dungeon
  region.
- **`FloorDetailOp`** — cracks / scratches / stones / clusters
  inside the dungeon region. Wood-floor tiles get the per-tile
  plank pattern (`wood_tiles`).
- **`ThematicDetailOp`** — webs / bones / skulls inside the
  dungeon region.
- **`TerrainDetailOp`** — water ripples / lava cracks / chasm
  hatch inside the dungeon region.
- **`DecoratorOp`** — cobblestone / brick / flagstone / etc.
  per-variant tile lists inside the dungeon region.

### Tile-only ops (no region_ref)

- **`StairsOp`** — fixture placement at specific tiles.
- **`WellFeatureOp` / `FountainFeatureOp` / `TreeFeatureOp` /
  `BushFeatureOp`** — fixtures at placement tiles.
- **`CorridorWallOp`** — corridor-floor tile coordinates; the
  consumer derives wall edges by checking each tile's neighbours.

## 6. Layer / paint ordering

Paint order is **emitter-enforced via op sequence in
`FloorIR.ops`**. The renderer is a flat dispatch loop:

| Slot | Op kind                       | Notes                                              |
| ---- | ----------------------------- | -------------------------------------------------- |
| 1    | `HatchOp`(s)                  | outer-band hatching (paints under the dungeon)     |
| 2    | `ShadowOp`(s)                 | drop-shadows under floors                          |
| 3    | `FloorOp`(s)                  | every floor area, all kinds (covers hatch where overlapping) |
| 4    | `InteriorWallOp`(s)           | partitions, smooth-room interior walls             |
| 5    | `RoofOp`(s)                   | building shingles                                  |
| 6    | `ExteriorWallOp`(s)           | rect-room / smooth-room / cave / building / enclosure outline walls |
| 6b   | `CorridorWallOp`              | corridor-side walls, derived from tile membership  |
| 7    | `TerrainTintOp`(s)            | water/lava/grass/chasm tints                       |
| 8    | `FloorGridOp`(s)              | wobbly-grid overlay                                |
| 9    | `FloorDetailOp`(s)            | cracks / scratches / stones / clusters              |
| 10   | `DecoratorOp`(s)              | cobblestone / brick / flagstone / etc.             |
| 11   | `ThematicDetailOp`(s)         | webs / bones / skulls                              |
| 12   | `TerrainDetailOp`(s)          | water ripples / lava cracks / chasm hatch          |
| 13   | `StairsOp`(s)                 | stair fixtures                                     |
| 14   | `WellFeatureOp` / `FountainFeatureOp` / `TreeFeatureOp` / `BushFeatureOp` | placeable fixtures |

### Why HatchOp moves to slot 1 (vs v4's slot 14)

The v4 design proposed `HatchOp` last on the rationale that
"hatch paints over everything the dungeon doesn't cover, so it
lands last". v4e places `HatchOp` **first** instead because:

1. The stamp model relies on paint order for clipping. If hatch
   paints last, it would overwrite floor / wall paint inside the
   dungeon at smooth-room corner tiles (where the per-tile
   candidate filter still includes the bbox-overlapping tile).
2. With hatch first, `FloorOp` paints over any hatch bleed inside
   the dungeon polygon. Walls paint over both. The visible
   composite has hatch bordering the dungeon exterior; floors and
   walls fully covering the interior.

This matches the current emitter's order (hatch already lives at
position 3 in `IR_STAGES` today, before walls/floors). v4e
formalises the rationale and elevates hatch to slot 1.

### Region-clip discipline for slots 7-12

These layers paint **after** floors and walls. Their `region_ref`
constrains painting to the named region; the renderer realises
the clip via:

- **SVG (`SvgPainter`)**: emits a `<defs><clipPath>` from the
  region's outline once at first use, re-references the
  `clip-path="url(#xxx)"` attribute on each painted element.
  Per-element clip-path attribute (not `<g clip-path>`
  envelope) — keeps the SVG flat and grep-friendly.
- **PNG (`SkiaPainter`)**: builds a `tiny_skia::Mask` from the
  region's outline once at first use, threads it through every
  fill / stroke call as the mask argument.

The IR carries `region_ref` (semantic intent); the renderer
chooses the clipping primitive (SVG attribute vs Skia Mask) based
on the active backend. The clip is **never** a fixed envelope in
the IR — it's a per-op rendering detail.

### Hatch's clip discipline

Hatch is special because it paints **outside** a region (the
outer band around the dungeon) rather than inside. v4e
implementation:

- Emitter pre-filters tile candidates via Perlin distance from
  the dungeon polygon boundary — the candidate list excludes
  tiles whose centres are deep inside the dungeon.
- Tile bboxes near the dungeon perimeter may bleed into the
  polygon interior at smooth-room corners; that bleed is covered
  by paint order (slot 3 `FloorOp` paints over slot 1 hatch
  inside the dungeon).
- No SVG `<g clip-path>` wrapper; no Skia Mask. The combination
  of emitter-side filter + paint order is sufficient.

## 7. The Painter trait

Phase 2 (after the IR redesign) introduces a `Painter` trait that
abstracts the rasteriser backend. `primitives::*` (Rust per-
primitive emitters in `crates/nhc-render/src/primitives/`) swap
their `Vec<String>` SVG-fragment output for `&mut dyn Painter`
calls; both backends implement the same trait surface.

```rust
pub trait Painter {
    // Style A — high-level shape primitives.
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
    fn begin_group(&mut self, opacity: f32);
    fn end_group(&mut self);

    // Clip scope — paints rendered between push_clip and pop_clip
    // are masked by the clip path. Used by region_ref consumers.
    fn push_clip(&mut self, path: &PathOps, fill_rule: FillRule);
    fn pop_clip(&mut self);
}

pub struct Paint  { pub color: Color }
pub struct Stroke { pub width: f32, pub line_cap: LineCap, pub line_join: LineJoin }
```

### Group-opacity scope (carryover from v4)

The `<g opacity>` envelope in SVG composites overlapping children
as one image at the group opacity, not by multiplying alpha per
child. The v4 design notes (§5) catalogue twelve primitives that
need group-opacity scope: `cobblestone`, `floor_detail`,
`cart_tracks`, `flagstone`, `brick`, `opus_romano`,
`field_stone`, `terrain_detail`, `thematic_detail`, `wood_floor`,
`hatch`, `shadow`. Each wraps its emit block in
`painter.begin_group(opacity); …; painter.end_group();`.

### Clip scope (new in v4e)

`push_clip(path, fill_rule)` activates a clipping region for
subsequent paint calls until the matching `pop_clip()`. Nested
clips intersect. Implementations:

- **`SkiaPainter`**: builds a `tiny_skia::Mask` from the path,
  pushes it onto a clip stack; subsequent paint calls pass the
  top-of-stack mask into `fill_path` / `stroke_path`. Pop pops the
  stack.
- **`SvgPainter`**: emits a `<clipPath id="auto-N">` def the first
  time a unique path is seen, then writes the matching
  `<g clip-path="url(#auto-N)">` envelope; pop closes the `</g>`.
  De-duplicates clip-path defs by hashing the path data.
- **`CanvasPainter`** (Phase 3): uses the Canvas2D `clip()` /
  `restore()` pair around a saved state.

Region-clipped per-tile ops use this trait surface:

```rust
fn draw_floor_grid_op(op: &FloorGridOp, regions: &[Region], painter: &mut dyn Painter) {
    let region = regions.find(op.region_ref).expect("region exists");
    let clip_path = build_outline_path(&region.outline);
    painter.push_clip(&clip_path, FillRule::EvenOdd);
    for tile in op.tiles {
        paint_grid_tile(tile, painter);
    }
    painter.pop_clip();
}
```

### SkiaPainter

Drives `tiny_skia::Pixmap`. Replaces `transform/png/fragment.rs`
and the per-handler tiny-skia calls scattered across
`transform/png/*.rs`. Lifts the existing
`paint_offscreen_group` mechanism for `begin_group` / `end_group`
and the existing `Mask::new()` mechanism for clip stack.

### SvgPainter

Writes a String buffer with semantic SVG elements. Each `Painter`
call appends one element. Replaces `nhc/rendering/ir_to_svg.py`
and the per-handler `_draw_*_from_ir` Python functions; replaces
`crates/nhc-render/src/transform/png/{svg_attr,path_parser}.rs`
because SVG fragments no longer need round-trip parsing.

### CanvasPainter (Phase 3 / WASM)

Drives an HTML5 Canvas2D context via `wasm-bindgen`. The 50-line
opcode emitter the parent migration plan pencilled in for a
Canvas backend becomes obsolete — Phase 2 already did the
abstraction work; CanvasPainter implements the trait directly.

## 8. Cross-rasteriser story

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
(`png/`, `svg/`, `canvas/`).

PyO3 exports:
- `nhc_render.ir_to_png(buf, scale=1.0, layer=None) -> bytes`
- `nhc_render.ir_to_svg(buf, layer=None) -> str` (NEW after v4e)
- `nhc_render.svg_to_png(svg) -> bytes` (existing; retained for
  parity testing only)

### Parity gate

`tests/unit/test_ir_png_parity.py` compares pixel-level output
between two paths: `ir_to_svg(buf) → svg_to_png(svg)` (Rust resvg
+ usvg under the hood) versus `ir_to_png(buf)` direct (Rust
tiny-skia). PSNR ≥ 35 dB at every fixture (50 dB for the cave
fixture per the existing `TINY_SKIA_PSNR_OVERRIDES`). Plus a
small set of structural sanity asserts on the SVG output
(envelope present, top-level structure matches expected layout,
no broken `viewBox`).

Byte-equal SVG is **not** gated — `SvgPainter` output is allowed
to drift from the legacy Python output.

## 9. Mapping from current 4.x state to v4e

The current `feat/pure-ir-v4` branch is at schema 3.1 with
parallel emission of v4-style ops alongside the legacy
`WallsAndFloorsOp` / `BuildingExteriorWallOp` / etc. The v4e
target diverges from v4's plan in the following places:

| Current state                                | v4e target                                       |
| -------------------------------------------- | ------------------------------------------------ |
| `FloorOp.outline: Outline`                   | `FloorOp.region_ref: string` (consumes Region)   |
| `ExteriorWallOp.outline: Outline` with cuts  | `ExteriorWallOp.region_ref + cuts: [Cut]` on op  |
| `Region.polygon: Polygon`                    | `Region.outline: Outline` with multi-ring support |
| Ops with `clipRegion`                        | Renamed `region_ref` for consistency (semantically same) |
| `crates/nhc-render/src/primitives/*.rs` returns `Vec<String>` | `&mut dyn Painter` calls       |
| `transform/png/{fragment, svg_attr, path_parser}.rs` parses SVG strings | retired (never needed) |
| `nhc/rendering/ir_to_svg.py`                 | retired; replaced by `nhc_render.ir_to_svg(buf)` PyO3 |
| `<g clip-path="url(#xxx)">{body}</g>` wrappers in SVG output | per-element `clip-path="url(#xxx)"` via `push_clip` / `pop_clip` |

### Schema bumps along the way

The migration ladders through additive minor bumps within the
4.x major:

- **4.0**: legacy ops drop, current v4 schema as documented in
  `design/map_ir_v4.md` ships. `file_identifier` advances to
  `"NIR4"`. Tag `ir-schema-4.0`.
- **4.1**: `Region.outline: Outline` added (additive parallel to
  `Region.polygon`). Emitter populates both.
- **4.2**: `FloorOp.region_ref: string` added. Emitter populates
  both `region_ref` and `outline`.
- **4.3**: `ExteriorWallOp.region_ref: string` added. Op-level
  `cuts: [Cut]` added (additive — `Outline.cuts` still populated).
- **4.4**: Per-tile ops add `region_ref: string` (additive
  parallel to `clipRegion`).
- **4.5**: Consumers prefer `region_ref` over embedded outline;
  emitters can stop populating the deprecated outlines (they
  remain in schema for back-compat).
- **4.6**: Schema clean-up — remove deprecated `FloorOp.outline`,
  `ExteriorWallOp.outline`, `Region.polygon`, `Outline.cuts`,
  `clipRegion` aliases. `file_identifier` stays `"NIR4"` (no
  major bump); minor advances to its final value.

Each schema bump comes with the matching emitter / consumer
change. See §10 for the per-bump execution ladder.

## 10. Phased migration

The IR cut from 3.1 to 4.x is the structural change; the v4e
work threads through Phase 1 minor bumps. Phase 2 (Painter trait)
and Phase 3 (WASM Canvas) are renderer-only refactors that don't
touch the schema.

| Phase    | Schema | Net work                                                  | Atomicity |
| -------- | ------ | --------------------------------------------------------- | --------- |
| **0**    | 3.1    | Dead-code cleanup (`FloorDetailOp.{room,corridor}_groups` reads, `GenericProceduralOp` dispatch). No fixture changes; pixel-equivalent. | additive, zero risk |
| **1.0–1.20c** | 3.1 | (current branch state) Outline + Cut + style enums + FloorOp / InteriorWallOp / ExteriorWallOp / CorridorWallOp parallel emission. WoodFloor migration. CrossShape / HybridShape migration. Building parity xfail closed. | additive, parallel emission |
| **1.21a** | 3.1   | Drop hatch clip envelope; paint order covers bleed. Already shipped at `7929cb3`. | additive, zero risk |
| **1.22** | 4.0    | Schema major cut. Drop legacy ops (`WallsAndFloorsOp`, `BuildingExteriorWallOp`, `BuildingInteriorWallOp`, `EnclosureOp`, `Gate`, `GenericProceduralOp`). `file_identifier` = `"NIR4"`. Tag `ir-schema-4.0`. | atomic break |
| **2**    | 4.1    | Add `Region.outline: Outline` (additive parallel to `Region.polygon`). Emitter populates both. Region table emits `Outline` with descriptor support per-region kind. | additive |
| **3**    | 4.2    | Add `FloorOp.region_ref`. Emitter populates both region_ref + outline. Consumer prefers region_ref. | additive |
| **4**    | 4.3    | Add `ExteriorWallOp.region_ref` + op-level `cuts`. Emitter populates both. Consumer prefers region_ref + op cuts. | additive |
| **5**    | 4.4    | Per-tile ops gain `region_ref` (renamed parallel of `clipRegion`). | additive |
| **6**    | 4.5    | Stop populating deprecated outlines and `clipRegion`. All consumers on region_ref path. Schema fields stay for back-compat. | non-additive (consumer change) |
| **7**    | 4.6    | Schema clean-up — drop deprecated outlines, `Region.polygon`, `Outline.cuts`, `clipRegion`. | breaking within 4.x major |
| **8**    | (no bump) | Define `Painter` trait. Implement `SkiaPainter`. Port `crates/nhc-render/src/primitives/*.rs` from `Vec<String>` to `&mut dyn Painter`. | renderer-only refactor |
| **9**    | (no bump) | Implement `SvgPainter`. Add `nhc_render.ir_to_svg(buf)` PyO3 export. Retire `nhc/rendering/ir_to_svg.py`. | renderer-only |
| **10**   | (no bump) | Drop `<g clip-path>` wrappers + `<defs><clipPath>` from SvgPainter output. Clip via `push_clip` / `pop_clip` per-element. | renderer-only |
| **11**   | (no bump) | `nhc-render-wasm` crate + `CanvasPainter` impl. ~50 lines of dispatcher + the trait impl. | renderer-only |

Phases 2-7 are independently shippable. Each phase ladder lands
multiple commits, one per op kind. Phases 8-11 are sequential
refactors that don't touch schema.

### Determinism contract through migration

`base_seed` and per-op seed offsets stay identical across all
phases. Schema bumps are additive with default-valued fields, so
3.1 caches can still parse 4.x readers (with default-zero values
for new fields). The autosave eviction gate
(`nhc/core/autosave.py`) fires once on the 4.0 cut (3.1 → 4.0)
and stays unchanged through the 4.x minor bumps.

## 11. Test strategy

### Fixtures

The 14 PSNR fixtures in `tests/fixtures/floor_ir/` regenerate
at every phase that changes pixel output. Each fixture's
`floor.json` (canonical IR JSON dump) and `reference.png` get
rebuilt from the post-phase emitter.

Existing fixtures cover:
- seed42 rect dungeon (rect rooms, no smooth shapes)
- seed7 octagon crypt (smooth-room outlines + gapped doors)
- seed99 cave cave (cave region + curved walls)
- seed1 dungeon, seed101 keep (buildings: exterior walls,
  partitions, roofs)
- seed_palisade, seed_fort (enclosures: palisade, fortification)
- seed7 brick_building (1.20b — wood-floor migration)

If a phase introduces shapes the existing fixtures don't
exercise, add new fixtures (`seed_circle_room`, `seed_pill_room`,
`seed_hybrid`, `seed_cross`).

### Parity gates

Per-fixture PSNR thresholds:
- ≥ 50 dB for the structured-only path vs. the prior baseline at
  every fixture (effectively byte-equal — the structured form
  rebuilds the same paths the SVG-fragment parser was
  reconstructing).
- ≥ 35 dB cross-rasteriser (Rust `ir_to_svg` →
  `nhc_render.svg_to_png` vs. Rust `nhc_render.ir_to_png`
  direct). Per-fixture overrides land in
  `tests/unit/test_ir_png_parity.py::TINY_SKIA_PSNR_OVERRIDES`
  for genuinely-divergent geometries (cave at 17 dB).

### Architectural guards

- `tests/unit/test_no_import_random_in_rendering.py` keeps
  `import random` out of the IR-emit shells.
- `tests/unit/test_no_svg_strings_in_ir.py` walks every op table
  at 4.0+ and asserts no field is typed as `[string]` carrying
  SVG markup.
- `tests/unit/test_no_svg_strings_in_primitives.rs` (NEW after
  Phase 8) walks every `crates/nhc-render/src/primitives/*.rs`
  function and asserts the return type is unit / direct paint
  primitive, not `Vec<String>`.
- `tests/unit/test_region_geometry_unique.py` asserts each
  `Region.id` resolves to one geometry and that paint ops with
  `region_ref` resolve to a known region.

## 12. Open questions / future evolution

- **TileGrid + B-state op-shrink.** When the per-tile ops grow
  expensive enough to justify a shared grid (or when WASM
  Canvas's bandwidth profile favours it), an additive bump adds
  `TileGrid` and lets ops shrink to `region_ref + params`.

- **Region-direct tile lists.** A `Region.tiles: [TileCoord]`
  optional field could replace per-op `tiles[]` for ops that
  filter by region. Not adopted in v4e because the per-tile ops
  still need cross-region queries (corridor-vs-room flag, etc.).

- **Per-marker ops.** `CampfireOp`, `DenMouthOp`,
  `TombEntranceOp` ride as `tile.feature` strings today. v4e
  leaves them in that state. Adding them as dedicated ops happens
  when typed gameplay's needs clarify their per-instance fields.

- **Floor with holes / pits.** Multi-ring `FloorOp.outline` (or
  multi-ring through `Region.outline.rings`) — supported in
  schema but no consumer needs it yet.

- **Animated visuals.** Water ripples, lava flows, etc., are
  static at 4.x (rendered once, no per-frame update). If
  animation needed: client-side WebGL on top of the static
  IR-rendered floor, or a parallel "animation IR" carrying
  per-op state-vs-frame.

- **DungeonCorridor region.** A dedicated `RegionKind::Corridor`
  that carries the corridor tile set as a tile list (no outline)
  could let `CorridorWallOp` and `FloorOp(corridor)` share data.
  Deferred — current minimal-IR approach (per-tile FloorOps + a
  single CorridorWallOp) works fine.

## 13. Critical files (post-v4e)

```
nhc/rendering/ir/
├── floor_ir.fbs                  # the schema (4.x)
├── _fb/                          # generated FB bindings (Python)
└── dump.py                       # IR → JSON for debug

nhc/rendering/
├── ir_emitter.py                 # Level → FloorIR translator
├── _floor_layers.py              # per-op _emit_*_ir helpers
├── _outline_helpers.py           # outline_from_<shape> + cuts_for_*
└── (ir_to_svg.py — RETIRED at Phase 9)

crates/nhc-render/
├── src/
│   ├── ir/                       # generated FB bindings (Rust)
│   ├── painter.rs                # Painter trait (NEW Phase 8)
│   ├── primitives/               # per-primitive emitters (call &mut dyn Painter)
│   ├── transform/
│   │   ├── png/                  # SkiaPainter dispatch (replaces fragment.rs)
│   │   ├── svg/                  # SvgPainter dispatch (NEW Phase 9)
│   │   └── canvas/               # CanvasPainter dispatch (NEW Phase 11)
│   └── geometry.rs               # outline / path utilities
└── Cargo.toml

crates/nhc-render-wasm/           # NEW Phase 11
└── (CanvasPainter glue)

tests/unit/
├── test_ir_png_parity.py         # PSNR gate
├── test_no_svg_strings_in_ir.py  # IR-purity guard
├── test_region_geometry_unique.py  # region_ref resolution guard
└── …
```

## 14. Determinism contract

Unchanged from v4 — the determinism contract is independent of
the region-keyed restructuring. RNG seed offsets per op kind:

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
| `ExteriorWallOp` (Masonry) | `+ 0xBE71 + edge_idx`   |
| `ExteriorWallOp` (Palisade / Fortification) | `+ 0xE101 + edge_idx`   |
| Cave consumer (buffer + jitter for `FloorOp { CaveFloor }` and `ExteriorWallOp { CaveInk }`) | `+ 0x5A17E5` |
| `WellFeatureOp` etc.      | per-feature offsets     |

Cross-rasteriser determinism: PSNR ≥ 50 dB at every fixture
between SkiaPainter and SvgPainter→resvg paths (after Phase 9).

## 15. Cross-references

- `design/map_ir.md` — pre-3.0 contract; historical reference.
  Slated for retirement once v4e ships.
- `design/map_ir_v4.md` — original v4 design. v4e supersedes;
  retire once v4e ships.
- `design/ir_primitives.md` — per-primitive determinism specs;
  needs section-level updates as primitives port to the Painter
  trait (Phase 8).
- `design/dungeon_generator.md` — door-position output; the
  generator continues to emit per-tile door features, the
  emitter resolves them to ExteriorWallOp cuts.
- `design/sites.md` — site / building / enclosure assembly.
  v4e's `Site`, `Building`, `Enclosure` regions correspond
  one-to-one with the assembler's outputs.
- `plans/nhc_pure_ir_plan.md` — execution plan; rewritten to
  match v4e's phase ladder.
