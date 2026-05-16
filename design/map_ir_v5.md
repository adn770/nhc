# Floor IR v5 — material-driven, region-keyed, generic-paint contract

**Status:** Canonical design contract for schema 5.0. Supersedes
`design/map_ir_v4e.md` once the atomic NIR4 → NIR5 cut ships.
Until that point, v4e remains the live contract on the codebase
and v5 is the target.

The v5 design generalises v4e along three axes: every paintable
surface (dungeon level, cave, site, building interior, surface
view) shares the same op vocabulary; floor finishes become
first-class **Material** objects with a uniform family-style-tone
shape; "decorators" split into texture overlays, discrete objects,
and connected paths, each with its own op kind.

Predecessors stay as historical reference: `design/map_ir_v4e.md`
(v4e contract — region-keyed but op-typed), `design/map_ir_v4.md`
(pre-region-keyed v4 prep), `design/map_ir.md` (the original
pre-v4 contract).

## 1. Goals

Three outcomes drive v5 beyond v4e:

1. **Materials are first-class.** Floors, walls, doors, and roofs
   carry structured `(family, style, sub_pattern, tone, seed)`
   tuples instead of closed style enums. The same painter pipeline
   handles oak floors, opus-romano stone floors, granite cave
   floors, dirt road floors — dispatched through one Material
   abstraction. New material families and styles ship as painter
   table extensions, never schema bumps.

2. **The op union shrinks from 18 to 8.** Generic ops (`PaintOp`,
   `StampOp`, `PathOp`, `FixtureOp`, `StrokeOp`) absorb every
   variant-typed op v4e split per concept. The painter dispatches
   on op data (Material's family, FixtureKind, PathStyle,
   decorator mask bits), never on op type.

3. **The painter is the deterministic source of truth.** The IR
   ships fully resolved intent — pre-decided per-region species,
   pre-decided decorator bits, pre-resolved tile lists — and the
   painter renders without theme strings, kind enums, or palette
   late-binding. Per-pixel and per-tile variation comes from
   explicit per-op seeds the painter feeds into deterministic
   hashes.

A consequence: there are **no animations**. v5 is fully static —
the painter has no time, phase, or frame parameters. Decorator
bits like `Ripples` or `LavaCracks` paint static visual texture
that *looks like* surface motion, not animated frames. The IR is
a complete one-shot description.

## 2. Principles

### 2.1 Region-keyed paint dispatch

Every Region in `regions[]` carries an `Outline` (the geometric
source of truth). Paint ops reference geometry via `region_ref`;
they never carry their own outline (interior partitions in
`StrokeOp` are the single exception, since interior partition
geometry is not a region perimeter).

### 2.2 Material on the op, not on the region

Region is pure geometry. Materials, decorator masks, path styles,
fixture kinds, and wall treatments live on the paint ops. The
same region can host multiple paint ops with different materials
to express layering (a flagstone temple with a marble central aisle
is one Region("temple.5") + one PaintOp(Material.Stone-Flagstone)
+ one Region("temple.5.aisle") + one PaintOp(Material.Stone-Marble)).

### 2.3 Sub-zones are first-class regions

Any nameable area is a Region: rooms, sub-rooms, aisles, plinths,
inlays, courtyards. Sub-zones nest via `parent_id`. Region IDs
encode role by naming convention; there is no `Region.kind` enum.

### 2.4 Anti-geometry: two complementary expressions

- **Multi-ring outlines** for stable structural truth. The dungeon
  polygon's outline carries an outer ring (perimeter) plus inner
  rings (cave system footprints as holes). Even-odd fill paints
  the band between rings. Geometry that's "born this way" lives
  here.

- **Op-level subtract lists** for paint-event-specific exclusions.
  `PaintOp.subtract_region_refs: [string]` lets one paint event
  omit specific sub-regions without baking the omission into
  geometry. The same dungeon Region can be painted with different
  subtractions in different ops.

The convention: stable / canonical exclusions (caves cut into
dungeon) ride in geometry; ad-hoc / op-specific exclusions
(this paint event omits these spots) ride on the op.

### 2.5 Strict op-array order

The painter walks `ops[]` linearly. Earlier ops paint first; later
ops paint on top. Z-order is array-index. The emitter is
responsible for emitting ops in the right sequence; the painter
contains no layering logic and no implicit op-type-to-layer map.

### 2.6 Cuts follow geometry

Cuts (door / gate / opening positions on a wall outline) live
wherever their geometry lives:

- On the **Region** when a paint op targets a region perimeter
  (`StrokeOp.region_ref` reads cuts from `Region.cuts`).
- On the **op** when a paint op carries its own outline
  (`StrokeOp.outline` for interior partitions carries
  `StrokeOp.cuts`).

The principle "wherever the shape is, that's also where its
openings are." Other ops (Shadow, Hatch, Stamp) read cuts from
whichever piece of geometry owns them, so shadows can break at
doorways, hatching can skip openings, and decorators can avoid
piling up in thresholds.

### 2.7 Per-op explicit seeds

Every op (and `Material` / `WallMaterial` instance) carries its
own `seed: uint64`. The emitter resolves seeds explicitly
(typically `base_seed + per_op_offset`); the painter consumes
them directly without derivation. IRs are robust against op
reordering because seeds are absolute, not derived from op-array
position.

### 2.8 Palette in the painter

The IR ships compact indices (`family: enum`, `style: uint8`,
`sub_pattern: uint8`, `tone: uint8`). The painter holds the
hard-coded palette tables that map indices to colours, layout
algorithms, and per-bit baseline densities. Adding a new style
or sub-pattern requires painter code changes (in three backends
— Skia, SVG, Canvas) but no schema bump.

### 2.9 No theme strings, no kind enums in painter dispatch

Eliminated from the IR: `theme: string` (was per-op),
`Region.kind`, `FloorIR.floor_kind`, `FloorIR.flags.*`. Anything
that needed theme/kind dispatch is pre-resolved by the emitter
into specific Material values, decorator-mask bits, or specific
ops. The painter never branches on a theme string or a kind
enum.

### 2.10 Painter trait abstraction (carried from v4e Phase 2)

The Rust `Painter` trait surface (`fill_polygon`, `push_clip` /
`pop_clip`, `begin_group(opacity)` / `end_group`, `push_transform`
/ `pop_transform`) is unchanged from v4e Phase 2. v5 changes the
op-to-primitive dispatch layer above the trait; the trait itself
stays stable. Phase 3 (WASM Canvas) lands a `CanvasPainter` impl
on the same trait surface.

## 3. The IR (FlatBuffers schema 5.0)

```fbs
namespace nhc.ir;

file_identifier "NIR5";          // single atomic 5.0 cut
file_extension "nir";
```

```fbs
table FloorIR {
  major: uint32;                  // = 5
  minor: uint32;                  // additive bumps post-cut
  width_tiles: uint32;
  height_tiles: uint32;
  cell: uint32 = 32;
  padding: uint32 = 32;
  base_seed: uint64;
  regions: [Region];
  ops: [OpEntry];
}

root_type FloorIR;
```

The root carries no `floor_kind`, no `theme`, no `flags`. Tooling
infers floor type from region IDs ("dungeon" / "cave" / "site" /
"building.interior").

### 3.1 Geometric primitives

```fbs
table Vec2 { x: float; y: float; }

struct PathRange { start: uint32; count: uint32; is_hole: bool; }

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
```

Outline carries no cuts. Cuts ride alongside the geometry on
either Region or the op (see §2.6).

### 3.2 Region

```fbs
table Region {
  id: string (key);               // see §10.1 for naming
  outline: Outline;
  parent_id: string;              // optional nesting; empty == top-level
  cuts: [Cut];                    // openings on the perimeter
  shape_tag: string;              // "rect" | "octagon" | "circle" | "pill" |
                                  //  "temple" | "L" | "cross" | "hybrid" | "cave"
}
```

Region carries no `kind` enum. The painter reads `shape_tag` to
dispatch geometry construction (octagon vs circle vs hybrid
chamfering, roof-shape pyramid vs gable). Tooling reads `id` to
infer floor / role.

### 3.3 Cut

```fbs
table Cut {
  start: Vec2;
  end: Vec2;
  style: CutStyle;
}

enum CutStyle : ubyte {
  None            = 0,            // bare gap, no door visual
  WoodGate        = 1,            // enclosure gate (wood double-door)
  PortcullisGate  = 2,            // enclosure gate (vertical iron lattice)
  DoorWood        = 3,            // standard interior door (wooden)
  DoorStone       = 4,            // dungeon stone door
  DoorIron        = 5,            // dungeon iron door
  DoorSecret      = 6,            // looks like wall on the static map
  // future additive: Archway, DoorBronze, DoorMagical, DoorIronBanded, ...
}
```

`CutStyle` is a fat enum: one slot per door / gate variant. New
variants are additive minor schema bumps with corresponding
painter implementations. There is no per-door seed (doors of the
same style render identically — see Q13).

### 3.4 Material model

```fbs
enum MaterialFamily : ubyte {
  Plain   = 0,
  Cave    = 1,
  Wood    = 2,
  Stone   = 3,
  Earth   = 4,
  Liquid  = 5,
  Special = 6,
}

table Material {
  family       : MaterialFamily;
  style        : uint8;           // family-specific palette index
  sub_pattern  : uint8;           // family-specific layout (0 when family has none)
  tone         : uint8;           // family-specific tonal axis (0 when family has none)
  seed         : uint64;          // per-instance procedural variation
}

enum WallTreatment : ubyte {
  PlainStroke   = 0,              // single dark line; substance picks colour
  Masonry       = 1,              // running-bond stones / bricks visible along perimeter
  Partition     = 2,              // interior thin-wall, dressed
  Palisade      = 3,              // vertical stake-poles at intervals
  Fortification = 4,              // thick wall + crenelated battlement
}

enum CornerStyle : ubyte {
  Merlon  = 0,                    // axis-aligned crenellation (default)
  Diamond = 1,                    // 45° rotated
  Tower   = 2,                    // forward-compat slot
}

table WallMaterial {
  family       : MaterialFamily;  // reuses MaterialFamily for substance consistency
  style        : uint8;           // family-specific
  treatment    : WallTreatment;
  corner_style : CornerStyle = Merlon;
  tone         : uint8;
  seed         : uint64;
}
```

`Material` and `WallMaterial` share `family / style / tone / seed`
by convention so a stone-cobble floor and a stone-cobble wall
draw from the same palette. `WallMaterial` has no `sub_pattern`
(walls' layout is determined by `treatment`); `Material` has no
`treatment` or `corner_style` (floors don't have those concepts).

The full taxonomy of family / style / sub_pattern / tone values
is in §4.

### 3.5 Op tables

#### PaintOp — region-wide floor / surface fill

```fbs
table PaintOp {
  region_ref: string;
  subtract_region_refs: [string];
  material: Material;
}
```

Paints `region_ref`'s outline (minus any `subtract_region_refs[]`)
with the given Material. Folds today's `FloorOp` and absorbs
TerrainOp's water/lava/chasm via `Liquid` and `Special` families.

#### StampOp — per-region surface texture overlays

```fbs
table StampOp {
  region_ref: string;
  subtract_region_refs: [string];
  decorator_mask: uint32;         // OR of bits from §5
  density: uint8 = 128;           // 0 = none, 128 = baseline, 255 = max
  seed: uint64;
}
```

The painter walks tiles in the region, runs per-bit gates
(painter-side baselines × `density / 128`), stamps each enabled
bit's texture per tile. Replaces today's `FloorGridOp`,
`FloorDetailOp`, `ThematicDetailOp` (scatter parts), the scatter
bits of `DecoratorOp`, and `TerrainDetailOp` (static texture
parts).

For per-bit density divergence (e.g. heavy blood + sparse
moss), the emitter emits multiple StampOps targeting the same
region with different `decorator_mask` / `density` values. The
painter sums their effects in op-array order.

#### PathOp — connected tile networks with style-driven topology

```fbs
table PathOp {
  region_ref: string;
  tiles: [TileCoord];             // unordered network
  style: PathStyle;
  seed: uint64;
}

enum PathStyle : ubyte {
  CartTracks = 0,                 // twin-rut wear marks; 4-neighbour topology
  OreVein    = 1,                 // mineral seam; vein-flow contour
}
```

The painter derives topology (4-neighbour connectivity, L-corner
/ T-junction / cross piece dispatch for CartTracks; vein contour
for OreVein) from the unordered tile set. Replaces today's
`DecoratorOp.cart_tracks` and `DecoratorOp.ore_deposit` variants.

PathStyle is additive — new styles (RailLine, Vines, RootSystem,
etc.) ship as additive minor bumps with painter implementations.

#### FixtureOp — discrete decorative objects with anchors

```fbs
table FixtureOp {
  region_ref: string;             // optional clip; empty == no clip
  kind: FixtureKind;
  anchors: [Anchor];
  seed: uint64;
}

enum FixtureKind : ubyte {
  Web         = 0,
  Skull       = 1,
  Bone        = 2,
  LooseStone  = 3,
  Tree        = 4,
  Bush        = 5,
  Well        = 6,
  Fountain    = 7,
  Stair       = 8,
  Gravestone  = 9,
  Sign        = 10,
  Mushroom    = 11,
}

struct Anchor {
  x: int32;
  y: int32;
  variant: uint8;                 // kind-specific sub-style
  orientation: uint8;             // kind-specific direction / corner (0 = unused)
  scale: uint8;                   // kind-specific size (0 = default)
  group_id: uint32;               // 0 = standalone; shared = fusion group
}
```

Each anchor is one instance of the kind. The painter dispatches
on `(kind, variant, orientation, scale)` to render. Anchors with
the same `group_id` fuse (Tree groves, Mushroom clusters,
Gravestone clusters) — the painter unions their canopies /
patches into one fragment.

Replaces today's `WellFeatureOp`, `FountainFeatureOp`,
`TreeFeatureOp`, `BushFeatureOp`, `StairsOp`, plus the
ThematicDetailOp scatter bits that were really object placements
(Webs, Skulls, Bones, LooseStones).

#### StrokeOp — wall stroke along outline

```fbs
table StrokeOp {
  region_ref: string;             // OR
  outline: Outline;               // (one of)
  wall_material: WallMaterial;
  cuts: [Cut];                    // populated when using `outline`; reads from
                                  // Region.cuts when using `region_ref`
}
```

When `region_ref` is set, the painter reads geometry from
`Region.outline` and openings from `Region.cuts`. When `outline`
is set (interior partitions, free-standing walls), the painter
reads geometry from the op's outline and openings from
`StrokeOp.cuts`.

Replaces today's `ExteriorWallOp`, `InteriorWallOp`,
`CorridorWallOp`. The CorridorWall consumer logic (deriving wall
edges from per-tile coverage of `FloorOp` tiles) is handled
implicitly by the painter when the corridor's region is referenced.

#### ShadowOp — drop-shadow band

```fbs
table ShadowOp {
  kind: ShadowKind;
  region_ref: string;             // for Room kind
  tiles: [TileCoord];             // for Corridor kind
  dx: float = 3.0;
  dy: float = 3.0;
  opacity: float = 0.08;
}

enum ShadowKind : ubyte { Room = 0, Corridor = 1 }
```

Carries over from v4e unchanged. The painter reads `Region.cuts`
from the referenced region (when `kind=Room`) to break the shadow
at doorways.

#### HatchOp — hatched outer band

```fbs
table HatchOp {
  kind: HatchKind;
  region_ref: string;             // hatched region (e.g. cave for Hole kind)
  subtract_region_refs: [string]; // exclusion (e.g. dungeon polygon for Hole)
  tiles: [TileCoord];             // candidate tile list (filtered at emit time)
  is_outer: [bool];               // parallel to tiles[]; 10% RNG skip on outer
  extent_tiles: float = 2.0;
  seed: uint64;
  hatch_underlay_color: string;
}

enum HatchKind : ubyte { Room = 0, Hole = 1, Corridor = 2 }
```

Adopts the v5 anti-geometry convention: `region_ref +
subtract_region_refs[]` instead of v4e's `region_ref_in /
region_ref_out`. Mechanical translation; painter behaviour
unchanged.

#### RoofOp — projection-geometry shingled roof

```fbs
table RoofOp {
  region_ref: string;             // → building Region
  style: RoofStyle = Simple;
  tone: uint8;                    // tonal axis on the painter palette
  tint: string;                   // explicit hex override; empty == use palette
  seed: uint64;
}

enum RoofStyle : ubyte {
  Simple  = 0,
  Pyramid = 1,
  Gable   = 2,
  Dome    = 3,
}
```

Stays as its own op (not folded into PaintOp) because the
projection geometry (2D footprint → 2.5D pyramid / gable spine)
diverges enough from "fill region with material" that pushing
through PaintOp's dispatch would require special-case branching.

The painter looks up `region_ref` in `regions[]`, dispatches
geometry from the building region's `shape_tag` (rect-non-square /
L → gable; octagon / square / circle → pyramid on N-gon
footprint), picks the shingle palette from `tone`, and uses
`seed` for shingle running-bond layout variation.

### 3.6 Op union and root

```fbs
union Op {
  PaintOp   = 1,
  StampOp   = 2,
  PathOp    = 3,
  FixtureOp = 4,
  StrokeOp  = 5,
  ShadowOp  = 6,
  HatchOp   = 7,
  RoofOp    = 8,
}

table OpEntry { op: Op; }
```

Op slot numbers are stable across the schema 5.x cycle. Adding a
new op variant (post-cut) is an additive minor bump with a slot
number greater than 8.

## 4. Material family taxonomy

The painter holds the per-family palette tables. The IR ships
indices; the painter knows what `(family=Wood, style=Oak, tone=Medium)`
looks like. Adding a style or tone is a painter table extension
that needs implementation in three backends (Skia, SVG, Canvas)
but no schema change.

### 4.1 Plain

| axis | values |
| --- | --- |
| style | `Default = 0` |
| sub_pattern | unused (0) |
| tone | unused (0) |

The parchment-white background fill (`#FFFFFF`). Used for any
region that should paint as the default canvas (most dungeon
rooms, most surface void areas).

### 4.2 Cave

| axis | values |
| --- | --- |
| style | `Limestone = 0`, `Granite = 1`, `Sandstone = 2`, `Basalt = 3` |
| sub_pattern | unused (0) |
| tone | unused (0) |

Cave geometry is organic (the painter buffers + jitters + smooths
the outline). Each style picks a distinct palette. Crystal /
Coral / Ice / Lava-rock deferred for additive expansion when
specific biome work needs them.

### 4.3 Wood

| axis | values |
| --- | --- |
| style (species) | `Oak = 0`, `Walnut = 1`, `Cherry = 2`, `Pine = 3`, `Weathered = 4` |
| sub_pattern (layout) | `Plank = 0`, `BasketWeave = 1`, `Parquet = 2`, `Herringbone = 3` |
| tone | `Light = 0`, `Medium = 1`, `Dark = 2`, `Charred = 3` |

5 species × 4 sub-patterns × 4 tones = 80 wood combinations. The
painter palette has 5 species × 4 tones × 3 colour roles
(base / highlight / shadow) = 60 colour entries. Layout
sub-patterns are algorithm-side, not palette-side.

### 4.4 Stone

| axis | values |
| --- | --- |
| style | `Cobblestone = 0`, `Brick = 1`, `Flagstone = 2`, `OpusRomano = 3`, `FieldStone = 4`, `Pinwheel = 5`, `Hopscotch = 6`, `CrazyPaving = 7`, `Ashlar = 8` |
| sub_pattern (per-style) | see below |
| tone | (per-style; typically Light / Medium / Dark) |

Per-style sub-pattern axes:

- `Cobblestone`: `Herringbone = 0`, `Stack = 1`, `Rubble = 2`,
  `Mosaic = 3` (4 sub-patterns)
- `Brick`: `RunningBond = 0`, `EnglishBond = 1`, `FlemishBond = 2`
  (3 sub-patterns)
- `Ashlar`: `EvenJoint = 0`, `StaggeredJoint = 1` (2 sub-patterns)
- `Flagstone`, `OpusRomano`, `FieldStone`, `Pinwheel`, `Hopscotch`,
  `CrazyPaving`: no sub-patterns (`sub_pattern = 0` always; painter
  ignores).

The per-style sub-pattern semantics are painter-baked: for
Cobblestone, sub_pattern=0 means Herringbone; for Brick, it means
RunningBond. The painter dispatches on the (style, sub_pattern)
pair.

OpusReticulatum and OpusSpicatum deferred.

### 4.5 Earth

| axis | values |
| --- | --- |
| style | `Dirt = 0`, `Grass = 1`, `Sand = 2`, `Mud = 3` |
| sub_pattern | unused (0) |
| tone | unused (0) |

Snow / Gravel / Cobbledirt / Cropfield deferred for additive
expansion.

### 4.6 Liquid

| axis | values |
| --- | --- |
| style | `Water = 0`, `Lava = 1` |
| sub_pattern | unused (0) |
| tone | unused (0) |

Replaces today's `TerrainOp` for water and lava substrates.
Surface motion (ripples, lava cracks) is a static decorator
overlay (see §5), not animated.

### 4.7 Special

| axis | values |
| --- | --- |
| style | `Chasm = 0`, `Pit = 1`, `Abyss = 2`, `Void = 3` |
| sub_pattern | unused (0) |
| tone | unused (0) |

Substrate materials for hazards and absent floor. The painter
applies depth / parallax / dark vignette effects automatically
based on the style — no decorator bit needed.

### 4.8 Roof styles

`RoofStyle` enum (on `RoofOp`, not via Material because RoofOp
stays distinct):

| value | meaning |
| --- | --- |
| `Simple` | flat tint over the building footprint (catalog default) |
| `Pyramid` | central spine peaks at the centroid; N-gon footprints |
| `Gable` | linear ridge along longer axis; rect / L footprints |
| `Dome` | concentric tonal rings (top-down hemisphere) |

The emit pipeline (`nhc/rendering/emit/roof.py::_pick_style`)
picks `Pyramid` for square / octagon / circle and `Gable` for
wide-rect / L-shape so production roofs read as the legacy
shape-driven dispatch. `Simple` / `Dome` are catalog-only today
— generators have to opt into them explicitly. (`WitchHat` was
retired; forest watchtowers take the Pyramid default.)

Tonal axis is `RoofOp.tone: uint8` (`Light = 0`, `Medium = 1`,
`Dark = 2`, `Aged = 3`). The painter palette resolves tone to
shingle base + highlight + shadow colours.

`RoofOp.sub_pattern: RoofTilePattern` is an optional tile-pattern
overlay layered on top of the geometry chosen by `style`:

| value | meaning |
| --- | --- |
| `Shingle` | organic running-bond; the default (enum 0) |
| `Fishscale` | overlapping scallop tiles in offset rows |
| `Thatch` | short randomised vertical strands |
| `Slate` | small rectangular tiles in a tight running-bond |
| `Staggered` | staggered-butt shakes; jagged per-course butt line |

Every roof carries a real texture — `Plain` was retired (Shingle
is the default) and the confusing `Pantile` S-curve was later
dropped. Pattern dispatch is orthogonal to geometry: `(style,
sub_pattern)` is a 4×5 matrix. The overlay paints over the
polygon clip envelope so the geometry's silhouette stays intact;
each pattern is oriented in the geometry's plane-local frame.

### 4.9 WallMaterial: WallTreatment + CornerStyle

WallTreatment enum is locked at 5 values for v1 (PlainStroke,
Masonry, Partition, Palisade, Fortification). CornerStyle is
locked at 3 (Merlon, Diamond, Tower-reserved). Drystone, Adobe,
WattleAndDaub, Iron treatments deferred. Round, Crow corner
styles deferred.

Each `(family, style, treatment)` combination needs a painter
implementation. The painter dispatches on `treatment` for the
drawing algorithm and reads `family + style + tone` for the
substance palette.

## 5. Decorator-bit registry

`StampOp.decorator_mask: uint32` carries OR-able bits. v5 ships
9 bits (stable-sort numbered):

| bit | name | meaning |
| --- | --- | --- |
| 0 | `GridLines` | wobbly Perlin grid (today's FloorGridOp folded in) |
| 1 | `Cracks` | fine line fractures |
| 2 | `Scratches` | faint surface marks |
| 3 | `Ripples` | static concentric ring patterns; for Liquid:Water |
| 4 | `LavaCracks` | static angular crack network with bright seams; for Liquid:Lava |
| 5 | `Moss` | green tufts |
| 6 | `Blood` | red splatters / stains |
| 7 | `Ash` | grey dusting |
| 8 | `Puddles` | dark wet spots |

Bits 9–31 reserved for additive future bits (Frost, Mold, Leaves,
Snow, SandDrift, Pollen, Stains, Inscriptions, surface-Footprints,
…). New bits ship as additive minor bumps with painter
implementations.

The painter holds per-bit baseline densities (e.g. GridLines
~100%, Cracks ~30%, Blood ~5%) documented in the painter source.
StampOp.density (uint8, 128 = baseline) scales them all
uniformly. For per-bit divergence the emitter emits multiple
StampOps with different masks + densities.

## 6. PathStyle registry

Locked at 2 values for v1: `CartTracks = 0`, `OreVein = 1`.
RailLine, Vines, RootSystem, RiverBed, LavaSeam deferred.

## 7. FixtureKind registry

Locked at 12 values for v1: `Web = 0`, `Skull = 1`, `Bone = 2`,
`LooseStone = 3`, `Tree = 4`, `Bush = 5`, `Well = 6`,
`Fountain = 7`, `Stair = 8`, `Gravestone = 9`, `Sign = 10`,
`Mushroom = 11`.

Per-kind interpretation of Anchor fields:

| kind | variant | orientation | scale | group_id |
| --- | --- | --- | --- | --- |
| Web | web-pattern type | corner (0=NW, 1=NE, 2=SE, 3=SW) | size (0–2) | unused |
| Skull | skull species (human, orc, dragon, …) | facing (0–7) | unused | unused |
| Bone | pile arrangement | unused | unused | unused |
| LooseStone | cluster shape | unused | unused | unused |
| Tree | species (oak, pine, dead, …) | unused | size (0–2) | grove fusion |
| Bush | species | unused | unused | unused |
| Well | shape (round, square) | unused | unused | unused |
| Fountain | shape (5 variants) | unused | unused | unused |
| Stair | style | direction (0=up, 1=down) | unused | unused |
| Gravestone | shape (cross, slab, celtic) | facing (0–7) | unused | cluster fusion |
| Sign | type (post, billboard) | facing (0–7) | unused | unused |
| Mushroom | species (red, blue, giant, …) | unused | size (0–2) | cluster fusion |

The exact `variant` enum values per kind live in the painter
source, not the schema. Adding new variants is painter-only.

Chest / Crate / Barrel / Altar / Brazier / Statue / Pillar /
Pedestal / Ladder / Trapdoor / Footprint / ChalkCircle deferred.

## 8. CutStyle registry

Locked at 7 values (carries over from v4e):
`None | WoodGate | PortcullisGate | DoorWood | DoorStone |
DoorIron | DoorSecret`. Door material variation (oak vs walnut
wood, plain vs banded iron) is deliberately *not* axis-split;
new variants ship as additive enum entries (`DoorWoodOak`,
`DoorIronBanded`, …) with painter implementations.

## 9. Painter contract

### 9.1 Painter trait

The Rust `Painter` trait surface (in
`crates/nhc-render/src/painter/{mod,skia,svg}.rs`) is unchanged
from v4e Phase 2. v5 adds two new backends:

- `transform/canvas/` (Phase 3 — WASM Canvas via `CanvasPainter`)
- (no schema involvement; the trait dispatches the same regardless
  of backend)

### 9.2 Per-family palette tables

Each `(family, style, tone)` triple resolves to a colour palette
the painter holds in source. The palette covers base, highlight,
and shadow colours for the substance, plus per-style auxiliary
colours where needed (e.g. Wood-Cherry-Light has a base
`#C4805C`, highlight `#D9986F`, shadow `#9F6149`; Stone-Granite
has a base / highlight / shadow tied to the style only since
tone is unused).

Palettes for the v5 family list need painter implementations.
That work is painter-side, additive on schema 5.0; see the
migration plan for sequencing.

### 9.3 Dispatch model

For PaintOp:
1. Resolve `Region.outline` from `region_ref`.
2. Resolve subtraction outlines from `subtract_region_refs[]`.
3. Compose clip mask (positive minus subtractions, even-odd rule
   for multi-ring outlines).
4. Dispatch on `material.family`:
   - `Plain`: `painter.fill_path(region_path, paint=#FFFFFF)`.
   - `Cave`: `painter.fill_path(buffered_jittered_smoothed_path, paint=cave_palette[style])`.
   - `Wood`: dispatch to the wood-floor pipeline (per-region
     species/tone/sub_pattern hash from seed; per-plank grain
     noise; basket-weave / herringbone / parquet layout).
   - `Stone`: dispatch on `(style, sub_pattern)` to the
     appropriate stone-laying algorithm; tone modulates palette.
   - `Earth`, `Liquid`, `Special`: respective pipelines.

For StampOp, FixtureOp, PathOp, StrokeOp, ShadowOp, HatchOp,
RoofOp: parallel structure — resolve geometry, dispatch on
op-specific identifiers, paint via Painter trait calls.

### 9.4 Group-opacity envelope (carries over)

Per-element alpha re-introduces the over-darken bug Phase 5.10
of the parent IR migration plan fixed. Decorator overlays that
should composite as a group (multiple `<g opacity>` children
overlapping) MUST use `painter.begin_group(opacity); …;
painter.end_group()`. The painter implementations inherit this
contract from v4e Phase 2.

## 10. Conventions

### 10.1 Region ID naming

```
Top-level (per-kind):
  "dungeon"            top-level dungeon walkable polygon
  "cave"               top-level cave-floor walkable polygon
  "site"               top-level site bounds
  "building.interior"  top-level building-interior walkable polygon

Sub-regions (stable index):
  "room.<n>"           single dungeon room
  "cave.<n>"           merged cave system (one per disjoint group)
  "corridor.<n>"       corridor segment
  "building.<n>"       building footprint on a site
  "enclosure"          palisade / fortification ring (typically singleton)

Sub-zones (flat IDs + parent_id chain):
  id="aisle.1", parent_id="temple.5"
  id="plinth.0", parent_id="aisle.1"
```

`<n>` is a stable index driven by world-gen RNG (not iteration
order), so debug tools and saved metadata can reference rooms
across IR regenerations.

### 10.2 parent_id and lineage

Sub-zones nest via `parent_id`. The painter rarely walks the
chain (per-op data is self-contained); tooling walks it on demand
("which regions live inside building.2?"). Empty `parent_id`
denotes a top-level region.

### 10.3 Anti-geometry: multi-ring vs subtract

- Stable / canonical exclusions live in geometry: the dungeon
  polygon's `Region("dungeon").outline` is multi-ring (outer
  perimeter + cave footprints as holes). Even-odd fill paints
  the band.
- Op-specific exclusions live on the op:
  `PaintOp.subtract_region_refs = ["altar.0"]` lets one paint
  event omit the altar pedestal without baking it into the temple
  region's geometry.

### 10.4 Op-array ordering

The emitter emits `ops[]` in the visual order the painter walks
linearly. There is no Z-field, no layer enum, no implicit
op-type-to-layer map. Conventional emit order:

```
[ShadowOp]                              (background drop-shadows)
[PaintOp …]                             (region material fills, in nesting order)
[StampOp …]                             (texture overlays per region)
[PathOp …]                              (cart-tracks, ore-veins on top of fills)
[FixtureOp …]                           (anchored objects: webs, skulls, trees, …)
[StrokeOp …]                            (walls; perimeter + partition strokes)
[RoofOp …]                              (building roofs over walls)
[HatchOp …]                             (hatched outer band, last)
```

Within a layer, order is emitter's choice. The painter walks
linearly; reordering at the same layer typically doesn't change
pixels (modulo overlap edge cases).

### 10.5 Cut placement

- `Region.cuts: [Cut]` — openings on the region's perimeter.
  Read by any op targeting `region_ref` (StrokeOp for the wall
  visual, ShadowOp for shadow breaks at doorways, HatchOp for
  hatch skips at openings, StampOp for decorator gaps near
  thresholds).
- `StrokeOp.cuts: [Cut]` — when StrokeOp uses its own `outline`
  (interior partitions, free-standing walls). The op's outline +
  op's cuts travel together.

### 10.6 Seeds

Per-op explicit seeds (uint64 each). Resolution happens at emit
time; the painter consumes without derivation. Conventional
offset scheme (matches v4e):

```
Material.seed:        base_seed + 0x?? (per region / per op)
WallMaterial.seed:    base_seed + 0x?? (per stroke op)
StampOp.seed:         base_seed + 0x?? (per region / per stamp)
PathOp.seed:          base_seed + 0x?? (per path)
FixtureOp.seed:       base_seed + 0x?? (per fixture op)
ShadowOp:             no seed (deterministic from geometry + dx/dy)
HatchOp.seed:         base_seed + 0x?? (per hatch op)
RoofOp.seed:          base_seed + 0xCAFE + building_index
```

The exact offsets are documented in the emitter source; the
painter never derives them.

## 11. Invariants

- **Static rendering only.** No animation, no time / phase /
  frame parameters anywhere in the IR or the painter. v5 produces
  static battlemap images.
- **Deterministic at painting time.** Given an IR, the painter
  produces identical pixels every render. All randomness is
  seed-driven; all per-tile placements are pre-resolved or
  derived from explicit seeds.
- **One IR = one floor / one surface.** Multi-floor structures
  (towers, mansions with cellars) emit multiple IRs, one per
  level. Cross-floor connections are game-level concerns, not
  IR concerns.
- **Strict op-array order.** No layer enum on ops; emitter holds
  the visual ordering contract.
- **No theme strings, no kind enums in painter dispatch.** All
  visual decisions resolved by the emitter into specific Material
  values, decorator-mask bits, op-specific data.
- **Region IDs are stable across regenerations** (driven by
  world-gen RNG).
- **Adding a Material style or Decorator bit is painter-only.**
  No schema bump; ships as a painter table extension across three
  backends (Skia, SVG, Canvas).

## 12. Eliminations from v4e

- `theme: string` (was per-op; painter resolved palette by name)
- `Region.kind` (was per-region; painter dispatched per kind)
- `FloorIR.floor_kind` (was per-IR; painter dispatched per kind)
- `FloorIR.flags.{shadows_enabled,hatching_enabled,atmospherics_enabled,macabre_detail,vegetation_enabled,interior_finish}`
- `FloorOp` (folded into `PaintOp`)
- `ExteriorWallOp` (folded into `StrokeOp`)
- `InteriorWallOp` (folded into `StrokeOp`)
- `CorridorWallOp` (folded into `StrokeOp` via implicit derivation)
- `FloorGridOp` (folded into `StampOp` as bit `GridLines`)
- `FloorDetailOp` (folded into `StampOp` for cracks/scratches; into
  `FixtureOp` for loose-stones)
- `ThematicDetailOp` (folded into `FixtureOp` for webs/skulls/bones)
- `TerrainTintOp`, `TerrainDetailOp` (folded into `PaintOp` via
  `Liquid`/`Special` families + `StampOp` for ripples/lava-cracks)
- `DecoratorOp` (split: stone styles → `Material.family=Stone`
  styles; cart-tracks/ore-deposit → `PathOp`)
- `WellFeatureOp`, `FountainFeatureOp`, `TreeFeatureOp`,
  `BushFeatureOp`, `StairsOp` (folded into `FixtureOp`)

Op union: 18 → 8.

## 13. Cross-language contract

- **Producer:** `nhc/rendering/ir_emitter.py` (Python; world /
  dungeon / site generator's view-builder).
- **Consumer:** `nhc-render` Rust crate, exposed via PyO3 +
  WASM:
  - `nhc_render.ir_to_png(buf, scale=1.0, layer=None) -> bytes`
  - `nhc_render.ir_to_svg(buf, layer=None) -> str`
  - `nhc_render_wasm.render_ir_to_canvas(buf, ctx, ...)` (Phase 3)
- **File format:** FlatBuffers binary blob with
  `file_identifier "NIR5"`, file extension `.nir`.
- **Schema version:** `SCHEMA_MAJOR = 5`, `SCHEMA_MINOR = 0` at
  the atomic cut. Additive minors land post-cut for new families,
  styles, decorator bits, path styles, fixture kinds, etc.

## 14. References

- `design/map_ir_v4e.md` — predecessor; v4e contract (region-keyed
  but op-typed). Historical reference once v5 ships.
- `design/map_ir_v4.md` — v4 prep contract.
- `design/map_ir.md` — pre-v4 contract.
- `design/ir_primitives.md` — per-primitive determinism specs;
  needs section-level updates as v5 lands.
- `plans/nhc_pure_ir_plan.md` — full Phase 1 (v4e) historical
  ladder; canonical for understanding why v4e looks the way it
  does.
- `plans/nhc_pure_ir_v5_migration_plan.md` — v5 atomic-cut
  migration plan (ephemeral execution doc).
- `plans/nhc_pure_ir_phase3_plan.md` — Phase 3 WASM Canvas plan
  (ephemeral; folds into v5 plan as the post-cut canvas-painter
  step).
- `crates/nhc-render/src/painter/{mod,skia,svg}.rs` — Painter
  trait surface (carries over from v4e Phase 2 unchanged).
- `nhc/CLAUDE.md` — strict TDD discipline.
