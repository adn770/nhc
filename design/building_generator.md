# Building Generator

Design document for the **building generator** subsystem: a
reusable primitive that composes into several kinds of
exploration sites -- towers, farms, mansions, keeps, and
cities/towns (temples are deferred). A building is a
multi-floor structure with a shared base shape and interior
rooms/corridors connected by stairs.

## Principles

- **TDD discipline**: tests first for every functional change.
- **Commit per milestone**: each completed milestone gets its
  own commit with passing tests.
- **No save migration**: saved games may break freely during
  active development.
- **Reuse existing primitives**: BSP subdivision, RoomShape,
  StructuralTemplate, transforms, terrain_palette -- extend,
  don't duplicate.
- **Subsume old templates**: the new Building + Site model
  replaces the current single-level `procedural:keep` template
  and reframes the single-level settlement generator as a
  Building consumer (see `6. Migration`).

## Overview

The subsystem introduces three new primitives and a library of
site assemblers built on top of them:

1. **Building** -- multi-floor container with a shared base
   shape and a stair graph
2. **Floor** -- a single storey (reuses the existing `Level`
   with a back-reference to its Building)
3. **Site** -- a surface composition: one or more Buildings
   plus walkable terrain (streets, gardens, fields) plus an
   optional enclosure (fortification wall, palisade)

Sites are still reachable through the hexcrawl layer via
`DungeonRef`; the generator runs on-demand when the player
enters the hex.

---

## 1. Context

### Why this subsystem

- The existing dungeon generator models a single `Level`. It
  has no concept of vertical structure: towers, mansions, and
  keeps currently get flattened into one floor of rooms.
- The existing settlement generator produces a single-level
  district layout. It has no "building" primitive -- each
  building is just a room tagged with a district type.
- SVG rendering has no material vocabulary for exterior
  surfaces: walls are pure geometry, streets are the only
  non-dungeon walkable style (cobblestones, added in
  d893bcd's sister commit 06403ff).
- Surface-level sites (farms, villages, keeps, towns) need
  distinct visual language (brick, stone, palisade, fields,
  gardens) that the current theme palette cannot express.

### Goals

- One primitive -- `Building` -- that all rich site generators
  consume.
- First-class multi-floor support with cross-floor stairs and
  an optional descent into a subterranean dungeon at ground
  level.
- SVG rendering gains brick/stone wall materials, fortification
  and palisade enclosures, and new walkable-surface renderers
  (street, field, garden) plus a wood interior floor.
- A clean migration path: the current `procedural:keep`
  template and the current single-level settlement generator
  are subsumed, not replicated.

### Non-goals

- Temples (vertical open spaces, multi-stair upper-to-ground
  connections): deferred to a later pass. A stub section
  records the intent.
- Per-NPC interior dressing, furniture, or shop inventory:
  out of scope for the generator itself.
- Save migration: active-dev breakage is acceptable.

---

## 2. Vocabulary

| Term            | Meaning                                     |
|-----------------|---------------------------------------------|
| Site            | A hex-level exploration location composed   |
|                 | of Buildings, walkable surfaces, and an     |
|                 | optional enclosure                          |
| Building        | A multi-floor structure with a single base  |
|                 | shape shared across all floors              |
| Floor           | A single storey of a Building (a `Level`)   |
| Compound        | A Site with multiple adjacent Buildings     |
|                 | interconnected by doors or open passages    |
| Base shape      | The perimeter footprint shared by every     |
|                 | floor of a Building                         |
| Stair link      | A tile-pair connecting two adjacent floors  |
|                 | in the same Building                        |
| Descent         | A stair link whose `to_floor` is an         |
|                 | off-Building `DungeonRef` (cellar, crypt,   |
|                 | cave)                                       |
| Surface type    | The walkable-surface category of an         |
|                 | outdoor tile (STREET, FIELD, GARDEN, etc.)  |
| Wall material   | The rendered material of a perimeter edge   |
|                 | (brick, stone, palisade, fortification,     |
|                 | dungeon)                                    |
| Enclosure       | A site-level perimeter -- either a          |
|                 | fortification wall or a palisade            |

---

## 3. Core Abstractions

### Building

```python
# nhc/dungeon/building.py

@dataclass
class Building:
    id: str
    base_shape: RoomShape
    base_rect: Rect
    floors: list[Level]
    stair_links: list[StairLink]
    descent: DungeonRef | None = None
    wall_material: str = "brick"  # brick|stone|dungeon
    interior_floor: str = "stone"  # stone|wood

    @property
    def ground(self) -> Level:
        return self.floors[0]
```

Buildings own the multi-floor invariants (footprint, stair
graph, descent). `Level` is not modified structurally; it
gains a back-reference helper only:

```python
# nhc/dungeon/model.py (additive)

@dataclass
class Level:
    ...
    building_id: str | None = None   # None for dungeon levels
    floor_index: int | None = None   # 0 = ground
```

### Floor

A floor **is** a `Level`. The building generator drives one
BSP pass per floor against the shared `base_shape`/`base_rect`,
so the perimeter matches across floors while the interior
subdivision varies independently.

### StairLink

```python
@dataclass
class StairLink:
    from_floor: int              # floor_index
    to_floor: int | DungeonRef   # int = in-building floor,
                                 # DungeonRef = descent
    from_tile: tuple[int, int]   # x, y in ground-level coords
    to_tile: tuple[int, int]
```

Tiles on either side are marked with
`feature = "stairs_up"` / `"stairs_down"` as today; the
`stair_links` list on `Building` gives generators an O(1)
cross-floor lookup rather than scanning tiles.

### Base shapes

The existing RoomShape hierarchy (`nhc/dungeon/model.py`)
covers most needs:

| Shape        | Reused | Source                         |
|--------------|--------|--------------------------------|
| Rectangular  | yes    | `RectShape`                    |
| Square       | yes    | `RectShape(w == h)` constraint |
| Circular     | yes    | `CircleShape`                  |
| Octagonal    | yes    | `OctagonShape`                 |
| L-shaped     | **no** | `LShape` -- new class          |

Square is **not** a distinct class; it is enforced at template
level by requiring `w == h` when that shape is selected.

#### LShape (new)

```python
# nhc/dungeon/model.py

@dataclass
class LShape(RoomShape):
    notch: tuple[int, int, int, int]
    # (nx, ny, nw, nh) -- corner rect to REMOVE from base rect

    type_name: str = "l_shape"

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        tiles = RectShape().floor_tiles(rect)
        nx, ny, nw, nh = self.notch
        notch_rect = Rect(rect.x + nx, rect.y + ny, nw, nh)
        return tiles - RectShape().floor_tiles(notch_rect)
```

The notch is constrained to one of the four corners, sized to
~1/3 of the base rect on each axis, never overlapping the
rect centre. See `12. Test strategy` for invariants.

### Site

```python
# nhc/dungeon/site.py

@dataclass
class Site:
    id: str
    kind: str                    # tower|farm|mansion|keep|town
    buildings: list[Building]
    surface: Level               # outdoor walkable level
    enclosure: Enclosure | None = None

@dataclass
class Enclosure:
    kind: str                    # fortification|palisade
    polygon: list[tuple[int, int]]
    gates: list[tuple[int, int, int]]
    # each gate = (x, y, length_tiles)
```

The `surface` Level holds outdoor tiles (streets, gardens,
fields) and acts as the "ground you walk on outside of a
building". Interior traversal happens on each Building's
floors.

---

## 4. Multi-Floor Infrastructure

### Shared-footprint invariant

For every Building `B` with floors `f_0..f_n`:

- The perimeter tile set of every floor equals
  `B.base_shape.perimeter_tiles(B.base_rect)`.
- Exterior walls are rendered **once** at the Building level
  (one wall polygon per material, not one per floor).
- Interior BSP runs independently per floor; connections must
  not punch through the perimeter.

### Per-floor generation

```python
def generate_building(template: BuildingTemplate,
                      rng: Random) -> Building:
    shape = pick_base_shape(template, rng)
    rect = pick_base_rect(template, shape, rng)
    floors = []
    for idx in range(template.floor_count):
        params = template.floor_params(idx)
        level = generate_floor_interior(
            shape, rect, params, rng,
        )
        level.building_id = template.id
        level.floor_index = idx
        floors.append(level)
    stair_links = place_stair_links(floors, rng)
    descent = template.descent_ref   # optional
    return Building(..., floors=floors,
                    stair_links=stair_links, descent=descent)
```

`generate_floor_interior` is a thin wrapper around the
existing BSP pipeline, but it receives a **pre-carved
footprint** instead of carving its own outer rect. BSP then
subdivides only the interior space.

### Stair placement rules

- At least one `(stairs_up, stairs_down)` pair between every
  pair of adjacent floors.
- Upper-floor `stairs_up` must land on a non-perimeter,
  non-door floor tile; same for `stairs_down` on the floor
  below.
- Ground-floor `stairs_down` is optional and only exists when
  `Building.descent is not None`. In that case it is placed
  deterministically in a room tagged `"entrance"`.
- 20% chance of a second stair pair in towers with >= 4
  floors (mirrors the 15% existing dungeon stair policy for
  stability).

---

## 5. Site Types

All sites are generated through a pluggable site assembler
function:

```python
def assemble_site(kind: str, params: SiteParams,
                  rng: Random) -> Site: ...
```

### 5.1 Tower

- **Composition:** 1 Building, 2--6 floors.
- **Base shape:** circular, octagonal, or square (`w == h`).
- **Enclosure:** none.
- **Descent:** optional; 30% of towers have a cellar/crypt
  descent at the ground floor.
- **Interior:** stone floors by default; wood on the topmost
  floor if there are >= 3 floors.
- **Entry:** one door on the ground floor perimeter.

### 5.2 Farm

- **Composition:** 1--2 Buildings (farmhouse + optional
  barn), both small (1--2 floors).
- **Base shape:** rectangular or L-shaped.
- **Surface:** large `FIELD` region around the buildings,
  with a few `GARDEN` tiles adjacent to the farmhouse.
- **Enclosure:** none. Open to adjacent hex terrain.
- **Descent:** rare (cellar only, ~10%).
- **Interior:** wood.

### 5.3 Mansion

- **Composition:** 2--4 adjacent Buildings connected by
  interior doors (no outdoor passages between them).
- **Base shape:** mixed rect / L-shaped; each Building picks
  independently.
- **Surface:** `GARDEN` tiles surround the compound.
- **Enclosure:** none (mansions are not fortified; gardens
  act as a visual buffer).
- **Descent:** optional; 20% carry a cellar or small crypt.
- **Interior:** wood on upper floors, stone on ground.

### 5.4 Keep (subsumes old `procedural:keep`)

- **Composition:** one main compound of 2--3 adjacent main
  Buildings interconnected by doors **or** separated by open
  courtyard tiles that the player can walk through.
  Additional 2--4 smaller sparse Buildings (armoury,
  smithy, storehouse) placed around the inner courtyard.
- **Base shape:** main Buildings are rectangular or
  octagonal; sparse Buildings are small rect or square.
- **Enclosure:** **fortification wall** wrapping the entire
  compound, with 1--2 gates.
- **Surface:** inner area uses `STREET` surface (trampled
  courtyard); a ring of `GARDEN` against building walls is
  allowed.
- **Descent:** 40%; usually leads to a crypt or cellar under
  the main keep Building.
- **Interior:** stone on ground floors of main Buildings,
  stone elsewhere (keeps are cold).
- **Migration note:** the existing `procedural:keep`
  template is removed; its `add_battlements` and `add_gate`
  transforms are rewritten as `add_fortification_wall` and
  `add_fortification_gate` (see `7. Migration`).

### 5.5 Town / City (subsumes old single-level settlement)

- **Composition:** many Buildings (5--25 depending on
  `size_class`) organised into districts that already exist
  in the settlement generator (MARKET, RESIDENTIAL, TEMPLE,
  NOBLE, SLUMS, DOCKS, GARRISON).
- **Base shape:** per Building: rect, square, L-shaped, with
  a small fraction of octagonal for NOBLE/TEMPLE districts.
- **Enclosure:** **palisade** for village/town; optional
  fortification wall for city.
- **Surface:** `STREET` between Buildings, `GARDEN` around
  NOBLE mansions, no `FIELD`.
- **Descent:** rare (taverns, temples may descend).
- **Interior:** wood for RESIDENTIAL/MARKET, stone for
  TEMPLE/GARRISON.
- **Migration note:** the existing `SettlementGenerator`
  becomes an assembler that populates its district list with
  `Building` instances instead of emitting rooms directly.

### 5.6 Temple (deferred stub)

Open problems to resolve in a later doc:

- **Vertical open spaces:** sections of the interior where
  multiple floors share the same air column (a main hall
  visible from upper galleries). Requires per-tile
  "ceiling missing" metadata.
- **Multiple stair connections:** several stair pairs from
  upper floors to the ground floor, all landing in the main
  hall.
- **Altar layout and sightlines:** altar on ground floor
  must be visible from galleries above.

No code is planned this round; this section reserves the
name.

---

## 6. Migration

### Deprecations

| Removed                               | Replaced by                            |
|---------------------------------------|----------------------------------------|
| `procedural:keep` template            | `assemble_site("keep", ...)`           |
| `add_battlements` transform           | `add_fortification_wall` (wall-level)  |
| `add_gate` transform                  | `add_fortification_gate`               |
| `generate_settlement()` returning a   | `assemble_site("town", ...)` returning |
| single `Level`                        | a `Site` with `surface` + buildings    |

### Retained

- All shape classes (except `LShape` which is new).
- `StructuralTemplate` itself -- Building adds a sibling
  `BuildingTemplate` dataclass for per-floor params; sites
  get a `SiteTemplate` at the assembler level.
- `procedural:tower`, `procedural:mine`, `procedural:crypt`
  -- these stay as single-`Level` generators. Towers as
  *sites* (this doc) are new and go through the site
  assembler, not the old template.

### Call-site changes

- `nhc/hexcrawl/_features.py` (`enter_hex_feature`): when a
  hex has `kind in {TOWER, FARM, MANSION, KEEP, TOWN}`,
  route to `assemble_site()` and cache the returned `Site`.
  Other kinds (DUNGEON, CAVE) keep using the existing
  pipeline unchanged.

### FARM placement policy

`FARM` is promoted to a first-class `HexFeatureType` so the
farm assembler drives hex-level entry the same way Tower,
Mansion, Keep, and Town do. The pre-existing
`MinorFeatureType.FARM` is kept for sub-hex farmstead dressing
(a flavour message when the player finds a roadside farm inside
a flower) -- the two uses don't conflict because one lives on
`HexCell.feature` and the other on `SubHexCell.minor_feature`.
Reason: building a separate "enter minor feature" path for a
single kind would duplicate the `enter_hex_feature` pipeline
without adding anything the major-feature route can't.
- `nhc/core/game.py`: movement handlers already consume
  `Level`; the new code routes the active `Level` from
  `Site.surface` by default, switching to
  `Building.floors[i]` when the player steps onto a door or
  stair of a Building.

---

## 7. Rendering (SVG)

### 7.1 Exterior wall materials

Each Building's perimeter is rendered once, per material,
using the following pattern.

#### Brick (doc commits to this approach)

Each wall run (a straight perimeter segment) is rendered as
**three horizontal strip polygons**, one per course of
bricks, stacked vertically:

```
┌──────────────────────────────┐
│ ▯▯▯▯▯▯ ▯▯▯▯▯ ▯▯▯▯▯▯▯▯ │   strip A  (offset 0)
│▯▯▯▯ ▯▯▯▯▯▯▯▯▯▯ ▯▯▯▯▯▯ │   strip B  (offset +x)
│ ▯▯▯▯▯▯▯▯ ▯▯▯▯▯ ▯▯▯▯▯▯ │   strip C  (offset -x)
└──────────────────────────────┘
```

- Each strip is a single `<polygon>` filled with the base
  brick colour.
- Random **vertical cut lines** across the strip, jittered in
  position and width, produce brick divisions.
- Strips stagger by a per-strip offset so courses don't align
  (real brickwork).
- A small per-division probability (~5%) outputs a gap
  polygon (background colour overlay) instead of a brick --
  "missing brick" effect.
- All randomness seeded from `Building.id` so regeneration is
  stable.

Palette (draft, tunable during implementation):

| Element         | Hex        |
|-----------------|------------|
| Brick fill      | `#B4695A`  |
| Brick seam      | `#6A3A2A`  |
| Missing brick   | `#F5EDE0`  (background `BG`) |

Stroke width: ~1px for seams; strip polygon has no stroke.

Per-run strip count: exactly 3 (the doc explicitly fixes this;
future work may parameterise it).

#### Stone (variation of Brick)

Same 3-strip structure, but:

- Divisions use **rounded-corner rectangles** (a per-division
  `rx=1.2px, ry=1.2px`).
- Division width has a **wider distribution** (0.7x -- 1.6x
  the mean) to produce obviously irregular stones.
- Missing-stone probability is lower (~2%).
- Palette: fill `#9A8E80`, seam `#4A3E35`.

#### Dungeon (fallback, existing)

When a Building's `wall_material = "dungeon"` it uses the
current geometric wall renderer unchanged. Retained for
non-rendered outdoor walls (e.g., Site enclosures wrap
Buildings but Buildings keep their own wall material).

### 7.2 Site enclosures

#### Fortification wall

For `Enclosure.kind == "fortification"`:

- **Base stroke:** continuous black line along `polygon`,
  stroke `#1A1A1A`, stroke-width `6px`, round line-join.
- **Overlay:** second `<polyline>` along the same path with
  stroke `#FFFFFF`, stroke-width `3px`,
  stroke-dasharray `"8 6"` (8px painted, 6px gap).
- **Gates:** cut the polygon at each `(x, y, length_tiles)`;
  that segment is not stroked (base or overlay). Visually:
  clean gap. A door tile with `feature = "door_closed"` is
  placed at the gate mid-point on the surface level.

Z-order: enclosure renders **after** all Building exterior
walls and **before** any entities.

#### Palisade

For `Enclosure.kind == "palisade"`:

- A sequence of **filled circles** along the polygon path,
  stepping every `1.6px` (tunable):
  - fill `#8A5A2A`,
  - stroke `#4A2E1A`, stroke-width `1.5px`,
  - radius `3.0--4.0px` with `±0.3px` jitter per circle,
  - seed derived from `Site.id`.
- **Palisade gates:** at each gate, the circles are replaced
  by a single **brown rectangle** spanning 2--3 tiles along
  the wall axis:
  - fill `#8A5A2A`, stroke `#4A2E1A`, stroke-width `1.5px`,
  - rectangle perpendicular thickness matches the
    palisade-circle diameter,
  - a door tile with `feature = "door_closed"` at its
    mid-point.

### 7.3 Walkable surface renderers

New `_render_*()` functions in
`nhc/rendering/_floor_detail.py`, gated on
`tile.surface_type`. **All of these skip cracks and
scratches** (unlike stone dungeon floors).

| Surface | Visual                                          |
|---------|-------------------------------------------------|
| STREET  | Subtle brown grid (~`#8A7A6A` @ 0.15 opacity)   |
|         | + sparse stones like cave stones                |
|         | (reuse `_floor_stone`, lower probability)       |
| FIELD   | Subtle green tint (~`#6B8A56` @ 0.15) + stones  |
| GARDEN  | Subtle green tint + dungeon-style lines (the    |
|         | existing grid line style from `_wobbly_grid_seg`)|

`PALISADE` and `FORTIFICATION` tiles are non-walkable
perimeter markers; they are not rendered by the surface
renderers (the enclosure renderer handles them).

`CORRIDOR` and `TRACK` keep their current renderers.

### 7.4 Interior floor renderers

Interior floors dispatch on `Building.interior_floor`:

#### Stone (existing behaviour reused)

White fill with `_floor_grid`, `_tile_detail` (cracks,
stones, scratches). No change.

#### Wood (new)

- Fill: `#B58B5A`.
- Planks: rectangular strips aligned to the room's major
  axis (longer side of the room's bounding rect). For
  circular or octagonal rooms, default to horizontal planks.
- Plank width: 3 tiles worth of pixels, with ±10% jitter.
- Seams between planks: stroke `#8A5A2A`, width `0.8px`,
  slight Perlin wobble via `_wobbly_grid_seg`.
- No cracks, no scratches, no stones.

### 7.5 Tunable constants

All hex colours, strokes, probabilities, and pixel sizes in
this section are **initial values** declared as module-level
`Final` constants in the relevant rendering files, so they
can be tuned during implementation without touching the
design doc. Single home per group:

| Constants group                | Module                            |
|--------------------------------|-----------------------------------|
| Brick / stone colours + seam   | `nhc/rendering/_building_walls.py`|
| Strip count, offset, missing-  | `nhc/rendering/_building_walls.py`|
| brick / missing-stone probs    |                                   |
| Fortification base + overlay   | `nhc/rendering/_enclosures.py`    |
| stroke, dash-array             |                                   |
| Palisade circle step, radius,  | `nhc/rendering/_enclosures.py`    |
| jitter, stroke, fill           |                                   |
| Street / field / garden tint,  | `nhc/rendering/_floor_detail.py`  |
| opacity, stone probability     |                                   |
| Wood fill, seam, plank width,  | `nhc/rendering/_floor_detail.py`  |
| jitter                         |                                   |

The doc's quoted values (e.g. `#B4695A`, `stroke-width 6px`,
`5%` missing-brick probability, `3` strip count, `3.0--4.0px`
palisade radius) are the starting point. Revise freely in the
constants module during milestone review; do not re-edit this
doc for every palette tweak.

---

## 8. Model Changes

### Tile

```python
# nhc/dungeon/model.py (Tile)

class SurfaceType(Enum):
    NONE          = "none"          # plain floor
    CORRIDOR      = "corridor"      # migrated from is_corridor
    TRACK         = "track"         # migrated from is_track
    STREET        = "street"        # migrated from is_street
    FIELD         = "field"         # new
    GARDEN        = "garden"        # new
    PALISADE      = "palisade"      # new, non-walkable
    FORTIFICATION = "fortification" # new, non-walkable

@dataclass
class Tile:
    ...
    surface_type: SurfaceType = SurfaceType.NONE
    # is_corridor, is_street, is_track REMOVED
```

Migration: existing `is_corridor`/`is_street`/`is_track`
bool-setting call-sites are rewritten to set
`surface_type`. Rendering checks switch from
`tile.is_street` to `tile.surface_type == SurfaceType.STREET`.

### Wall segment material

Wall material is a **per-perimeter-edge** attribute, not
per-tile. Stored on the `Building`'s cached wall polygon in a
parallel list:

```python
@dataclass
class WallSegment:
    polygon: list[tuple[int, int]]
    material: str  # brick|stone|palisade|fortification|dungeon
```

A Building emits one `WallSegment` for its exterior; a Site
emits one `WallSegment` for its enclosure.

### Building / Site / StairLink

See `3. Core Abstractions` for full dataclasses.

### DungeonRef

```python
# nhc/hexcrawl/model.py (DungeonRef)  -- additive
@dataclass
class DungeonRef:
    ...
    site_kind: str | None = None  # tower|farm|mansion|keep|town
```

`template` stays for single-level dungeons (cave, crypt,
mine). `site_kind` routes to the new site assembler instead.

---

## 9. Files

| Action | Path                                    |
|--------|-----------------------------------------|
| Create | `nhc/dungeon/building.py`               |
| Create | `nhc/dungeon/site.py`                   |
| Create | `nhc/dungeon/sites/tower.py`            |
| Create | `nhc/dungeon/sites/farm.py`             |
| Create | `nhc/dungeon/sites/mansion.py`          |
| Create | `nhc/dungeon/sites/keep.py`             |
| Create | `nhc/dungeon/sites/town.py`             |
| Modify | `nhc/dungeon/model.py` (Tile, Level,    |
|        | LShape)                                 |
| Modify | `nhc/dungeon/generators/_stairs.py`     |
|        | (cross-floor stair links)               |
| Modify | `nhc/dungeon/transforms.py`             |
|        | (add_fortification_wall,                |
|        | add_fortification_gate, add_palisade,   |
|        | add_gardens, add_farm_fields,           |
|        | add_wood_interior; remove               |
|        | add_battlements, add_gate)              |
| Modify | `nhc/dungeon/templates.py`              |
|        | (remove `procedural:keep`)              |
| Modify | `nhc/dungeon/generators/settlement.py`  |
|        | (consume Building)                      |
| Modify | `nhc/hexcrawl/model.py` (DungeonRef)    |
| Modify | `nhc/hexcrawl/_features.py` (site route)|
| Modify | `nhc/core/game.py` (Site <-> Building   |
|        | navigation)                             |
| Create | `nhc/rendering/_building_walls.py`      |
|        | (brick, stone strip rendering)          |
| Create | `nhc/rendering/_enclosures.py`          |
|        | (fortification, palisade)               |
| Modify | `nhc/rendering/_floor_detail.py`        |
|        | (field, garden, wood surface renderers) |
| Modify | `nhc/rendering/_walls_floors.py`        |
|        | (material dispatch)                     |
| Modify | `nhc/rendering/terrain_palette.py`      |
|        | (new palette entries)                   |

---

## 10. Integration with Existing Subsystems

### StructuralTemplate

`StructuralTemplate` is retained for single-`Level` dungeon
generation. Buildings use a sibling dataclass at the
floor-params level:

```python
# nhc/dungeon/building.py

@dataclass
class BuildingTemplate:
    id: str
    floor_count_range: Range
    base_shape_choices: list[str]  # rect|square|l|circle|octagon
    shape_weights: list[float] | None = None
    size_range: tuple[Range, Range]  # (width, height)
    floor_params_per_index: Callable[[int], GenerationParams]
    wall_material: str = "brick"
    interior_floor: str = "stone"
    descent_probability: float = 0.0
```

### Site assembler

```python
# nhc/dungeon/site.py

def assemble_site(kind: str, params: SiteParams,
                  rng: Random) -> Site:
    if kind == "tower":  return _assemble_tower(params, rng)
    if kind == "farm":   return _assemble_farm(params, rng)
    if kind == "mansion":return _assemble_mansion(params, rng)
    if kind == "keep":   return _assemble_keep(params, rng)
    if kind == "town":   return _assemble_town(params, rng)
    raise ValueError(f"unknown site kind: {kind}")
```

### HexFeatureType

Additions:

| Feature | site_kind |
|---------|-----------|
| TOWER   | tower     |
| FARM    | farm      |
| MANSION | mansion   |
| KEEP    | keep      (was: dungeon template) |
| TOWN    | town      (was: settlement generator) |

---

## 11. TDD Test Strategy

Tests first for every functional change, per project rules.

### Shape tests

- `LShape.floor_tiles(rect)` returns the rect minus the
  notch; notch stays within rect; removed-tile count matches
  `notch_w * notch_h`.
- Perimeter is still a single connected polygon (no islands).
- LShape's `cardinal_walls()` returns the concave corner as a
  reflex vertex (for door-candidate constraints).

### Building invariants

- Every floor of a Building has identical perimeter tile set.
- Every stair link connects adjacent floors
  (`abs(from - to) == 1`).
- `stairs_up` on floor N+1 matches `stairs_down` on floor N
  coordinate-for-coordinate.
- Descent ref, if set, is only reachable from the ground
  floor.

### Per-site integration tests

- **Tower:** 2--6 floors, single entry, no enclosure, all
  floors reachable from ground via stairs.
- **Farm:** 1--2 buildings, surrounding FIELD tiles >= 30% of
  surface area, no enclosure.
- **Mansion:** 2--4 buildings, each adjacent pair shares at
  least one interior door, no outdoor path between them,
  GARDEN ring around compound.
- **Keep:** single fortification polygon encloses every
  Building; at least 1, at most 2 gates; inner surface area
  is STREET or GARDEN only.
- **Town:** palisade forms a closed polygon with 1--2 gates;
  district tags assigned; streets connect every district.

### SVG golden-render tests

One baseline per material and per surface:

- `test_brick_wall_rendering` -- fixed seed, assert polygon
  count, strip count, missing-brick count within expected
  range.
- `test_stone_wall_rendering` -- same shape, rounded corners
  present.
- `test_fortification_enclosure` -- base + dashed overlay
  strokes both present, gate gap visible.
- `test_palisade_enclosure` -- circle count, jitter bounded,
  gate rectangle present.
- `test_street_surface`, `test_field_surface`,
  `test_garden_surface`, `test_wood_interior` -- per-tile
  decorations present, cracks/scratches absent where
  required.

Each golden test runs with a fixed seed and compares against
a committed baseline; visual review during first
implementation locks in the baseline.

### Migration tests

- Existing `procedural:keep` callers error with a clear
  message (or are rewritten; no silent fallback).
- Tile migration: loading an old save blob either succeeds
  with `SurfaceType.*` fields populated, or fails loudly.
  Active-dev: failing loudly is acceptable (no save
  migration).

---

## 12. Milestones

One commit per milestone, tests passing at every commit.
M1--M3 are pure model/infrastructure; M4--M10 are rendering;
M11--M14 wire end-to-end sites.

| # | Milestone                                        |
|---|--------------------------------------------------|
| M1 | `LShape` class + shape tests + perimeter tests  |
| M2 | `Building` / `Floor` / `StairLink` dataclasses; |
|    | `Tile.surface_type` enum migration; invariant   |
|    | tests                                           |
| M3 | Cross-floor stair linking + tests               |
| M4 | Brick wall SVG renderer (3-strip polygon) +     |
|    | golden tests                                    |
| M5 | Stone wall SVG renderer + golden tests          |
| M6 | Fortification wall renderer + gate gap +        |
|    | golden test                                     |
| M7 | Palisade renderer (circles + jitter) + door     |
|    | rectangle + golden test                         |
| M8 | Street surface renderer + golden test (migrate  |
|    | existing cobblestone style)                     |
| M9 | Farm FIELD + GARDEN surface renderers + golden  |
|    | tests                                           |
| M10| Wood interior floor renderer + golden test      |
| M11| Tower site assembler end-to-end                 |
| M12| Farm site assembler end-to-end                  |
| M13| Mansion site assembler end-to-end               |
| M14| Keep site assembler end-to-end (supersedes old  |
|    | `procedural:keep`)                              |
| M15| Town site assembler end-to-end (supersedes old  |
|    | single-level settlement generator)              |
| M16| (deferred) Temple stub -- vertical open spaces  |

---

## 13. Verification

After each milestone:

1. `.venv/bin/pytest -n auto --dist worksteal -m "not slow"`
   stays green.
2. `./server` and visit the web frontend; seed-stable
   regeneration of the site under test.
3. MCP debug tools:
   - `get_tile_map` at a Site hex -- surface_type values
     correct.
   - `get_svg_room_walls` / `get_svg_tile_elements` --
     material, surface renderers active.
   - `get_room_info` on each interior Room -- building_id /
     floor_index populated.
4. Visual diff: committed golden SVG per site type; run
   `./play -G --seed 12345` into each site and compare.

---

## Appendix A: Per-brick primitives (alternative)

The doc body commits to 3-strip polygons with random
divisions for simplicity and SVG node count. If we later need
finer control -- specifically per-brick rounded corners, or
per-brick colour jitter -- the alternative is to emit each
brick as its own SVG primitive.

Sketch:

```python
for course in range(3):
    offset = course_offset[course]
    for brick_i, brick in enumerate(bricks_in_run(run, ...)):
        x, y, w, h = brick_rect(run, course, brick_i, offset)
        if rng.random() < MISSING_P: continue
        if material == "stone":
            emit_rect(x, y, w, h, rx=1.2, ry=1.2,
                      fill=stone_fill, stroke=stone_seam)
        else:
            emit_rect(x, y, w, h,
                      fill=brick_fill, stroke=brick_seam)
```

Trade-offs:

- **Pros:** per-brick control, cleaner rounded corners on
  stone, easier to per-brick jitter colour/tilt.
- **Cons:** many more SVG nodes per wall run (a 30-tile wall
  with 3 courses and 10 bricks per course = 900 `<rect>`
  elements), slower client-side parsing; strip polygon only
  produces O(run_length) nodes.

Recommendation stands: ship Alternative A (3-strip polygon)
first; revisit if visual feedback demands per-brick
precision.

---

## Appendix B: Temple -- open problems

The elaborate temple (vertical open halls, multi-stair landings,
altar sightlines through upper floors) is deferred to milestone
M16. A **minimal temple site assembler** lands earlier to
support the mountain / forest `TEMPLE` hex feature; see
`design/biome_features.md` §6 for that spec. The minimal
assembler produces a single stone building with a priest
placement and no vertical tricks, drop-in replaceable by M16.

Open problems still reserved for M16:

- **Multi-floor open spaces:** some `(x, y)` columns span
  several floors with no intermediate ceiling. Requires an
  additional per-tile field (e.g., `open_above: bool`) and
  rendering logic to skip the upper floor's wall/floor for
  those columns.
- **Multiple stair pairs from upper floors to ground:** each
  upper floor may have several `stairs_down` all landing in
  the main hall. Stair placement algorithm needs to target a
  specific room (the hall) instead of any open tile.
- **Altar + sightlines:** the altar should be rendered on
  the ground floor and remain visible from upper floors --
  implies the web client needs a "current floor + visible
  tiles below" mode.


## Appendix C: Cottage (small forest site)

The `COTTAGE` hex feature (forest only) routes through a tiny
single-building site. Full spec lives in
`design/biome_features.md` §6 alongside the temple:

- One ~5x5 wood-interior building, brick walls, single floor.
- No NPCs in v1 (placeholder for future hermit / squatter /
  abandoned content).
- Forest-floor GARDEN surface ring; no palisade or enclosure.
- Standard door-crossing handler applies so the player enters
  the cottage via the perimeter door like any other site.


## Appendix D: Building interiors (M16+)

Lands milestones M16-M20 of the building-interiors plan; the
authoritative design document is `design/building_interiors.md`.
This appendix summarises the changes that ship against
`design/building_generator.md`'s vocabulary so a reader who
only has this file still sees the shape of the work.

- **Shell composer (M1):** perimeter wall stamping moves from
  each `_build_*_floor()` into `nhc/dungeon/sites/_shell.py`.
  Site assemblers carve footprints, run a partitioner, stamp
  the plan, then call `compose_shell()` to close the exterior.
- **Partitioner protocol (M2):** every building floor now
  goes through a partitioner (`SingleRoomPartitioner`,
  `DividedPartitioner`, `RectBSPPartitioner` with doorway /
  corridor modes, `SectorPartitioner` with simple / enriched
  modes, `TemplePartitioner`, `LShapePartitioner`). Partitioners
  return a `LayoutPlan`; sites stamp the plan.
- **Per-link stair alignment (M5):** `build_floors_with_stairs()`
  interleaves floor partitioning with stair picks — each
  link's tile is threaded into the next floor's partitioner
  via `required_walkable` so the upper floor keeps that tile
  walkable.
- **Interior wall material + SVG (M7):** Buildings carry an
  `interior_wall_material` (wood / stone / brick). The
  building renderer emits one `<line>` per straight run of
  interior-wall tiles, colored by material.
- **ARCHETYPE_CONFIG (M13-M14):** `nhc/dungeon/interior/
  registry.py` holds every per-archetype knob (size range,
  shape pool, partitioner, BSP / sector mode, corridor width,
  interior wall material, locked-door rate). Every site
  assembler reads from it via `build_building_floor()`.
- **InteriorDoorLink (M15):** `Site.interior_door_links` is a
  list of typed links between two buildings on the same floor;
  `sync_linked_door_state()` propagates open / closed / tick
  state across a link so both sides never drift.
- **Safe NPC placement (M16):** `nhc/dungeon/sites/_placement.py`
  exports `safe_floor_near()` — BFS-based fallback when the
  natural room center lands on a wall / door. Town NPCs
  (merchant, priest, innkeeper, adventurer) route through it.
- **Shop locked doors (M17):** `_lock_shop_doors()` converts
  one interior door to `door_locked` on shop-role buildings at
  the configured rate, preferring the door adjacent to the
  smallest room (BSP-style leaf).
- **Mage residence (M19):** new site kind wired through
  `assemble_mage_residence()`. Octagon / circle footprint
  partitioned by the enriched sector partitioner (rotating
  "main" sector, one door omitted on alternating floors).
- **Pickle compat (M20):** `Building.__setstate__` fills
  defaults for fields added in M7+ so older save snapshots
  continue to load. `StairLink` serialization is unchanged.
