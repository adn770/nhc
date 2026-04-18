# World Generation Expansion

Design documents for expanding NHC's world generation system
with thematic dungeon variants, richer settlements, Moria-scale
underworld regions, and Caves of Chaos patterns.

## Principles

- **TDD discipline**: tests first for every functional change.
- **Commit per milestone**: each completed milestone gets its
  own commit with passing tests.
- **No save migration**: saved games may break freely during
  active development. No backward-compat shims.
- **Refactor first**: modularize BSP generator and SVG renderer
  before extending them, not after.

## Overview

Eight phases organized as seven design documents (plus the
building generator as a dedicated follow-on doc):

1. **BSP Generator Modularization** -- foundational refactor
2. **SVG Renderer Modularization** -- foundational refactor
3. **Generator Architecture** -- StructuralTemplate system
4. **Settlement Generator** -- District-based cities
5. **Mega-Dungeon / Underworld** -- Multi-level cave regions
6. **Caves of Chaos Pattern** -- Keep + faction lairs
7. **SVG Rendering Extensions** -- Visual support for all above
8. **Building Generator** (see `building_generator.md`) --
   multi-floor building primitive + site assemblers (tower,
   farm, mansion, keep, town); subsumes the single-level
   `procedural:keep` template and reframes the settlement
   generator as a Building consumer

## Current State

- `DungeonGenerator` ABC with BSP, Cellular, Classic variants
- Theme is cosmetic: palette + entity pools, no structural effect
- BSPGenerator is 1412 lines in a single file
- SVG renderer is 4095 lines in a single file
- Cave clusters: BFS-grouped adjacent CAVE hexes, shared Floor 2
- Town: fixed 25x20 layout, ~5 hardcoded buildings
- 7 SVG theme palettes, room shape dispatch via isinstance()

---

## 1. BSP Generator Modularization

### Problem

`bsp.py` is 1412 lines with door placement, BSP tree logic,
connectivity, corridor carving, dead-end handling, stairs,
vaults, and post-processing all in one file. Adding layout
strategies to this monolith risks compounding complexity.
Modularize first so each concern lives in its own module.

### Target Structure

```
nhc/dungeon/generators/
  bsp.py              # BSPGenerator class, orchestration only
  _bsp_tree.py        # _Node, _split(), _place_room()
  _connectivity.py    # _center_dist, _find_neighbors, _bfs,
                      # _bfs_dist, reachability verification
  _corridors.py       # _carve_corridor, _carve_corridor_force,
                      # _carve_line, _wall_entry, _outward
  _doors.py           # _door_candidates, _hybrid_door_ok,
                      # _compute_door_sides,
                      # _remove_non_straight_doors
  _dead_ends.py       # dead-end pruning, secret door placement,
                      # orphaned door removal, harmonization
  _vaults.py          # _place_vaults
  _stairs.py          # _place_stairs
  _walls.py           # _build_walls, _fix_walled_corridors
  _shapes.py          # _pick_shape, _carve_room
```

### Module Boundaries

Based on analysis of the current code:

**_bsp_tree.py** (~60 lines)
- `_Node` dataclass (rect, children, room)
- `_split(node, rng)` -- recursive BSP subdivision
- `_place_room(leaf, rng)` -- room sizing within leaf
- Constants: MIN_LEAF, MAX_ROOM, MIN_ROOM, PADDING
- Pure tree operations, no level interaction

**_connectivity.py** (~150 lines)
- `_center_dist(a, b)` -- Manhattan distance
- `_find_neighbors(rects, max_dist)` -- adjacency pairs
- `_bfs(adj, start, end)` -- path between rooms
- `_bfs_dist(adj, start)` -- distances from room
- `_flood_reachable(level, start)` -- tile reachability
- Pure graph operations on room indices

**_corridors.py** (~150 lines)
- `_carve_corridor(level, r1, r2, rng)` -- L-shaped
- `_carve_corridor_force(level, r1, r2, rng)` -- through walls
- `_carve_line(level, x1, y1, x2, y2, force)` -- straight
- `_wall_entry(level, room, tx, ty)` -- wall-facing target
- `_outward(room, wx, wy)` -- step away from room
- Operates on level tiles, depends on _doors for candidates

**_doors.py** (~350 lines)
- `_door_candidates(room)` -- valid door positions
- `_hybrid_door_ok(room, dx, dy, side)` -- hybrid validation
- `_compute_door_sides(level)` -- cardinal side assignment
- `_remove_non_straight_doors(level)` -- curved wall cleanup
- Geometric operations on room shapes

**_dead_ends.py** (~100 lines)
- Dead-end tile detection (<=1 floor cardinal neighbor)
- Iterative pruning loop
- Secret door placement (30%), keep (30%), prune (40%)
- Orphaned door removal
- Door harmonization (adjacent doors unified)

**_vaults.py** (~80 lines)
- `_place_vaults(level, rng, params)` -- hidden 2x2/3x2 rooms
- Scans VOID space after connectivity, no BSP adjacency

**_stairs.py** (~70 lines)
- `_place_stairs(level, rects, adj, rng)` -- entry/exit
- Tags rooms with "entry"/"exit"
- 15% chance second stairs_down

**_walls.py** (~80 lines)
- `_build_walls(level)` -- 8-neighbor WALL placement
- `_fix_walled_corridors(level)` -- strip walled tunnels

**_shapes.py** (~60 lines)
- `_pick_shape(rect, variety, rng)` -- shape selection
- `_carve_room(level, rect, shape)` -- tile placement

### BSPGenerator After Refactor

The main class becomes a thin orchestrator (~200 lines):

```python
class BSPGenerator(DungeonGenerator):
    def generate(self, params, rng=None):
        # 1. BSP subdivision + room placement
        root = _build_tree(params, rng)
        rooms = _place_rooms(root, rng)
        # 2. Shape selection + carving
        _select_and_carve_shapes(level, rooms, params, rng)
        # 3. Wall building
        _build_walls(level)
        # 4. Connectivity + corridor carving
        _connect_rooms(level, rooms, params, rng)
        # 5. Dead-end handling
        _handle_dead_ends(level, params, rng)
        # 6. Door cleanup
        _cleanup_doors(level)
        # 7. Reachability verification
        _verify_reachability(level, rooms, rng)
        # 8. Vaults + stairs
        _place_vaults(level, rng, params)
        _place_stairs(level, rooms, adj, rng)
        # 9. Final door processing
        _compute_door_sides(level)
        _remove_non_straight_doors(level)
        return level
```

### Milestones and Commits

Each milestone: extract module, update imports, tests pass.

1. Extract `_bsp_tree.py` -- tree and room placement
2. Extract `_connectivity.py` -- graph operations
3. Extract `_corridors.py` -- corridor carving
4. Extract `_doors.py` -- door logic
5. Extract `_dead_ends.py` -- dead-end handling
6. Extract `_walls.py` -- wall building
7. Extract `_vaults.py` + `_stairs.py` -- placement
8. Extract `_shapes.py` -- shape selection
9. Final: BSPGenerator as thin orchestrator

### Testing

Existing tests in `test_bsp_generator.py` must pass after
each extraction. No new tests needed for pure refactoring --
behavior is unchanged. Run full suite after each milestone:
```bash
.venv/bin/pytest -n auto --dist worksteal -m "not slow"
```

### Files

| Action | Path                             |
|--------|----------------------------------|
| Modify | `nhc/dungeon/generators/bsp.py`  |
| Create | `nhc/dungeon/generators/_bsp_tree.py` |
| Create | `nhc/dungeon/generators/_connectivity.py` |
| Create | `nhc/dungeon/generators/_corridors.py` |
| Create | `nhc/dungeon/generators/_doors.py` |
| Create | `nhc/dungeon/generators/_dead_ends.py` |
| Create | `nhc/dungeon/generators/_walls.py` |
| Create | `nhc/dungeon/generators/_vaults.py` |
| Create | `nhc/dungeon/generators/_stairs.py` |
| Create | `nhc/dungeon/generators/_shapes.py` |

---

## 2. SVG Renderer Modularization

### Problem

`svg.py` is 4095 lines with room outlines, cave geometry,
hatching, floor detail, terrain detail, walls/floors, stairs,
shadows, and dungeon polygon logic all in one file. The
isinstance() dispatch chain for room shapes is already long
and adding new types will compound it. Modularize into focused
modules before extending.

### Target Structure

```
nhc/rendering/
  svg.py               # render_floor_svg, render_hatch_svg
                       # orchestration only
  _room_outlines.py    # per-shape SVG outline generation,
                       # gap insertion, intersection math
  _cave_geometry.py    # cave boundary tracing, Shapely union,
                       # Catmull-Rom smoothing, jitter
  _dungeon_polygon.py  # room-to-Shapely conversion,
                       # SVG path parsing, dungeon boundary
  _shadows.py          # room + corridor shadow rendering
  _hatching.py         # exterior + corridor + hole hatching,
                       # section partitioning
  _walls_floors.py     # wall/floor fill rendering, tile-edge
                       # wall segments, corridor rects
  _floor_detail.py     # floor grid, stone patterns, cracks,
                       # thematic detail (webs, bones, skulls)
  _terrain_detail.py   # per-terrain renderers (water, grass,
                       # lava, chasm), terrain tints
  _stairs.py           # stair wedge rendering
  _svg_helpers.py      # shared predicates (_is_floor,
                       # _is_door, _find_doorless_openings),
                       # _wobbly_grid_seg, geometry utils
```

### Module Boundaries

Based on analysis of the current code:

**_room_outlines.py** (~900 lines)
- `_room_svg_outline(room)` -- shape dispatch
- Per-shape outline functions: circle, pill, octagon,
  temple, cross, hybrid
- `_polygon_vertices()`, `_pill_vertices()`,
  `_temple_vertices()`, `_hybrid_vertices()`
- Gap insertion: `_outline_with_gaps()`,
  `_intersect_outline()`, `_intersect_circle()`,
  `_intersect_line_seg()`, `_intersect_hybrid()`
- `_circle_with_gaps()`, `_polygon_with_gaps()`
- `_hybrid_svg_outline()`, `_half_outline()`
- Extensibility point: new shapes add cases here only

**_cave_geometry.py** (~550 lines)
- `_cave_svg_outline(room)` -- cave floor path
- `_trace_cave_boundary_coords(tiles)` -- Shapely union
- `_smooth_closed_path()`, `_smooth_open_path()` --
  Catmull-Rom to Bezier
- `_centripetal_bezier_cps()` -- control points
- `_collect_cave_region()`, `_build_cave_polygon()`
- `_densify_ring()`, `_jitter_ring_outward()`
- `_ring_to_subpath()`, `_build_cave_wall_geometry()`
- Shapely-heavy, independent pipeline

**_dungeon_polygon.py** (~270 lines)
- `_room_shapely_polygon(room)` -- outline to Shapely
- `_svg_path_to_polygon(svg_el)` -- SVG path parsing
- `_approximate_arc()` -- arc to segments
- `_build_dungeon_polygon(level, cave_poly, cave_tiles)`
- Section partitioning: `_pick_section_points()`,
  `_get_edge_index()`, `_build_sections()`
- Used by hatching and terrain for clip boundaries

**_shadows.py** (~50 lines)
- `_room_shadow_svg(room)` -- shadow polygon
- `_render_room_shadows(svg, level)`
- `_render_corridor_shadows(svg, level)`

**_hatching.py** (~400 lines)
- `_render_hatching()` -- exterior perimeter hatching
- `_render_hole_hatching()` -- interior holes
- `_render_corridor_hatching()` -- corridor adjacency
- Perlin noise displacement, distance limiting
- Section-based cross-hatching angles

**_walls_floors.py** (~200 lines)
- `_render_walls_and_floors()` -- master coordinator
- Corridor + door tile rects
- Rect room fills
- Smooth room outline + stroke
- Cave region floor + wall
- Wall extensions + tile-edge segments

**_floor_detail.py** (~400 lines)
- `_render_floor_detail()`, `_render_floor_grid()`
- `_tile_detail()`, `_tile_thematic_detail()`
- `_emit_detail()`, `_emit_thematic_detail()`
- `_floor_stone()`, `_web_detail()`,
  `_bone_detail()`, `_skull_detail()`

**_terrain_detail.py** (~400 lines)
- `_render_terrain_detail()` -- per-terrain dispatch
- `_water_detail()`, `_grass_detail()`,
  `_lava_detail()`, `_chasm_detail()`
- `_render_terrain_tints()` -- color washes
- `_dungeon_interior_clip()` -- clip path
- Extensibility point: new terrains add renderers here

**_stairs.py** (~120 lines)
- `_render_stairs()` -- wedge + step lines
- Theme-aware (cave vs dungeon fill)

**_svg_helpers.py** (~100 lines)
- `_is_floor()`, `_is_door()`, `_find_doorless_openings()`
- `_wobbly_grid_seg()` -- hand-drawn grid line
- `_wobble_line()`, `_edge_point()`, `_y_scratch()`
- Shared geometry utilities

### SVG Renderer After Refactor

`svg.py` becomes a thin orchestrator (~100 lines):

```python
def render_floor_svg(level, seed=0, hatch_distance=2.0):
    # Pre-compute cave geometry once
    cave_path, cave_poly, cave_tiles = (
        build_cave_wall_geometry(level, rng)
        if has_caves else (None, None, set())
    )
    dungeon_poly = build_dungeon_polygon(
        level, cave_poly, cave_tiles,
    )
    # 7-layer pipeline
    render_shadows(svg, level)
    render_hatching(svg, level, seed, dungeon_poly, ...)
    render_walls_and_floors(svg, level, cave_path, ...)
    render_terrain_tints(svg, level, dungeon_poly)
    render_floor_grid(svg, level, dungeon_poly)
    render_floor_detail(svg, level, seed, dungeon_poly)
    render_terrain_detail(svg, level, seed, dungeon_poly)
    render_stairs(svg, level)
    return svg
```

### Milestones and Commits

Each milestone: extract module, update imports, tests pass.

1. Extract `_svg_helpers.py` -- shared predicates/utils
2. Extract `_shadows.py` -- shadow rendering
3. Extract `_stairs.py` -- stair rendering
4. Extract `_dungeon_polygon.py` -- geometry computation
5. Extract `_cave_geometry.py` -- cave pipeline
6. Extract `_room_outlines.py` -- shape outlines
7. Extract `_hatching.py` -- cross-hatching
8. Extract `_floor_detail.py` -- floor patterns
9. Extract `_terrain_detail.py` -- terrain rendering
10. Extract `_walls_floors.py` -- wall/floor coordinator
11. Final: `svg.py` as thin orchestrator

### Testing

Existing rendering tests must pass. Additionally, generate
a dungeon with `./play -G --seed 12345` and visually compare
SVG output before/after each extraction to confirm pixel-
identical rendering.

### Files

| Action | Path                               |
|--------|------------------------------------|
| Modify | `nhc/rendering/svg.py`             |
| Create | `nhc/rendering/_room_outlines.py`  |
| Create | `nhc/rendering/_cave_geometry.py`  |
| Create | `nhc/rendering/_dungeon_polygon.py`|
| Create | `nhc/rendering/_shadows.py`        |
| Create | `nhc/rendering/_hatching.py`       |
| Create | `nhc/rendering/_walls_floors.py`   |
| Create | `nhc/rendering/_floor_detail.py`   |
| Create | `nhc/rendering/_terrain_detail.py` |
| Create | `nhc/rendering/_stairs.py`         |
| Create | `nhc/rendering/_svg_helpers.py`    |

---

## 3. Generator Architecture Refactoring

### Problem

Theme controls visuals but not structure. New variants need
structural differences (tower: small circular floors, keep:
outer walls, mine: long tunnels) while sharing 80% of core BSP
logic (subdivision, corridors, doors, stairs).

### Solution: StructuralTemplate

Data-driven composition layer over existing generators.

```python
# nhc/dungeon/templates.py

@dataclass
class StructuralTemplate:
    name: str
    base_generator: str          # "bsp" or "cellular"
    preferred_shapes: list[str]
    shape_weights: list[float] | None = None
    room_size_override: Range | None = None
    room_count_override: Range | None = None
    layout_strategy: str = "default"
    outer_wall: bool = False
    courtyard: bool = False
    forced_connectivity: float | None = None
    transforms: list[str] = field(default_factory=list)
    theme: str = "dungeon"
    entity_pool_override: str | None = None
```

### Template Definitions

| Template            | Shapes          | Layout   | Special                |
|---------------------|-----------------|----------|------------------------|
| procedural:tower    | circle, octagon | radial   | small rooms (4-7)      |
| procedural:keep     | rect, octagon   | walled   | outer wall, courtyard  |
| procedural:crypt    | rect, pill      | default  | narrow (3-6), low conn |
| procedural:mine     | rect            | linear   | cart tracks, ore       |

### Layout Strategies

Implemented as pluggable functions in the modularized BSP
(enabled by Phase 1 refactor):

- **default**: unchanged BSP behavior
- **radial**: central hub + surrounding rooms radially
- **linear**: long trunk with short side branches
- **walled**: 2-tile outer wall, BSP interior, gate rooms
- **district**: 3-5 large regions, independently subdivided

### Post-Generation Transforms

Pure functions in `nhc/dungeon/transforms.py`:
- `add_cart_tracks(level, rng)` -- mine rail lines
- `narrow_corridors(level, rng)` -- crypt-style passages
- `add_battlements(level, rng)` -- keep wall decorations
- `add_gate(level, rng)` -- fortified entry points
- `add_ore_deposits(level, rng)` -- mine resource markers

### Pipeline Changes

```python
def generate_level(
    params: GenerationParams,
    template: str | None = None,
) -> Level:
    tmpl = TEMPLATES.get(template) if template else None
    if tmpl:
        effective = _apply_template(params, tmpl)
        generator = _generator_for(tmpl.base_generator)
    elif params.theme == "cave":
        effective, generator = params, CellularGenerator()
    else:
        effective, generator = params, BSPGenerator()
    ...
```

### Model Changes

- `GenerationParams`: add `template: str | None = None`
- `DungeonGenerator.generate()`: add optional `template` param

### Files

| Action | Path                          |
|--------|-------------------------------|
| Create | `nhc/dungeon/templates.py`    |
| Create | `nhc/dungeon/transforms.py`   |
| Modify | `nhc/dungeon/generator.py`    |
| Modify | `nhc/dungeon/pipeline.py`     |
| Modify | `nhc/dungeon/generators/bsp.py` |

---

## 4. Settlement Generator

### Problem

Current town is 25x20, ~5 hardcoded buildings. Need variable
sizes (hamlet to city), districts, streets, walls.

### Solution: SettlementGenerator

New generator class returning `Level`. Buildings = rooms,
streets = corridors, city walls = outer boundary.

### Size Classes

| Size    | Map   | Buildings | Districts | Walls |
|---------|-------|-----------|-----------|-------|
| Hamlet  | 25x20 | 3-4       | 1         | No    |
| Village | 40x30 | 5-8       | 1-2       | No    |
| Town    | 60x40 | 10-15     | 2-3       | Yes   |
| City    | 80x50 | 15-25     | 3-5       | Yes   |

### District Types

- MARKET: shops, warehouses, trading posts
- RESIDENTIAL: houses, small gardens
- TEMPLE: shrine, hospice, graveyard
- NOBLE: mansions, gardens, guard posts
- SLUMS: hovels, alleyways
- DOCKS: warehouses, taverns (if near water)
- GARRISON: barracks, armory, training yard

### Street System

- Main streets: 2-3 tile wide corridors between districts
- Side streets: 1-tile alleys within districts
- Marked with `is_street = True` on Tile for rendering

### City Walls

Town/city sizes get contiguous wall perimeter with 1-2 gate
rooms. Gates are the only entry points.

### Integration

- Existing `generate_town()` stays for hamlet size
- New generator handles village, town, city
- `DungeonRef.size_class` set from HexFeatureType

### Files

| Action | Path                                  |
|--------|---------------------------------------|
| Create | `nhc/dungeon/generators/settlement.py`|
| Modify | `nhc/dungeon/model.py` (Tile)         |
| Modify | `nhc/hexcrawl/model.py` (DungeonRef)  |
| Modify | `nhc/hexcrawl/_features.py`           |

---

## 5. Mega-Dungeon / Underworld System

### Problem

Cave clusters share a single Floor 2. Need multi-level
connected regions: underground travel between hexes, different
underground biomes, Moria-scale scope.

### Solution: UnderworldRegion

```python
# nhc/hexcrawl/underworld.py

@dataclass
class UnderworldRegion:
    canonical_coord: HexCoord
    member_coords: list[HexCoord]
    max_depth: int
    biome: str      # dwarven_mine, fungal_cavern, etc.
    name_key: str | None = None
```

### Depth Scaling

| Cluster Size | Max Depth | Classification |
|-------------|-----------|----------------|
| 1 cave      | 2         | Cave           |
| 2-3 caves   | 3         | Cave Complex   |
| 4-6 caves   | 4         | Underworld     |
| 7+ caves    | 5         | Moria-scale    |

### Underground Biome Progression

| Floor | Theme           | Terrain              |
|-------|-----------------|----------------------|
| 1-2   | Cave            | Current behavior     |
| 3     | Fungal Cavern   | Heavy grass, mushrooms |
| 4     | Lava Chamber    | Lava, embers         |
| 5     | Underground Lake | Water, island rooms  |

### Floor Generation

Single `Level` per floor, scaling with members:
- Width: `50 + n*15 + (depth-1)*10`
- Height: `30 + n*10 + (depth-1)*5`

Deeper floors use `"procedural:mine"` template for
connecting tunnels between sectors.

### Lateral Connections

On shared floors, the level is partitioned into sectors
(one per member hex). Each sector has stairs_up to its
surface entrance. Walking between sectors = underground
hex-to-hex travel. Same Level, no loading screen.

### Floor Cache

Key: `(canonical_q, canonical_r, depth)` for all depths
>= 2. Extends existing `_active_cave_cluster` pattern.

### Game Loop Changes

`_generate_cave_floor2` generalizes to
`_generate_underworld_floor(depth)`. The game tracks
`_active_underworld_region` (replacing or extending
`_active_cave_cluster`).

### Files

| Action | Path                             |
|--------|----------------------------------|
| Create | `nhc/hexcrawl/underworld.py`     |
| Modify | `nhc/hexcrawl/model.py` (HexWorld) |
| Modify | `nhc/hexcrawl/_features.py`      |
| Modify | `nhc/core/game.py`               |
| Modify | `nhc/rendering/terrain_palette.py` |

---

## 6. Caves of Chaos / Keep Pattern

### Problem

Generate classic B2 module layout: fortified keep near
wilderness with multiple faction cave lairs, some connecting
at depth.

### Solution: Pattern-Based Feature Clusters

Hex-level placement recipe, not a generator change.

```python
# nhc/hexcrawl/patterns.py

@dataclass
class FeaturePattern:
    name: str
    anchor_feature: HexFeatureType
    anchor_biomes: tuple[Biome, ...]
    satellite_features: list[SatelliteSpec]

@dataclass
class SatelliteSpec:
    feature: HexFeatureType
    distance: int
    count: Range
    biomes: tuple[Biome, ...]
    template_override: str | None = None
    faction_pool: list[str] | None = None
```

### Caves of Chaos Definition

- Anchor: KEEP in greenlands/hills
- Satellites: 3-5 CAVE hexes within distance 2
- Each cave gets a unique faction (goblin, orc, kobold,
  gnoll, bugbear, ogre)
- Caves interconnect at depth via cave cluster BFS

### Faction System

- `DungeonRef.faction` stores assigned faction string
- Populator checks `level.metadata.faction` for creature pool
- Shared deep floor places faction borders at chokepoints

### Keep as Safe Base

Uses `"procedural:keep"` template. Rooms tagged "safe" to
suppress hostile spawns. Player's home base.

### Placement Integration

`place_patterns()` runs after basic feature placement,
consuming from the dungeon budget. Pack YAML enables/disables
patterns.

### Files

| Action | Path                          |
|--------|-------------------------------|
| Create | `nhc/hexcrawl/patterns.py`    |
| Modify | `nhc/hexcrawl/model.py`       |
| Modify | `nhc/hexcrawl/_features.py`   |
| Modify | `nhc/dungeon/populator.py`    |
| Modify | `nhc/hexcrawl/pack.py`        |

---

## 7. SVG Rendering Extensions

### New Theme Palettes

| Theme            | Tone                         |
|------------------|------------------------------|
| tower            | Cool stone greys, steel blue |
| mine             | Brown/rust, ore glints       |
| settlement       | Warm light, clean lines      |
| fungal           | Dim green, bioluminescence   |
| lava_chamber     | Deep red/orange, embers      |
| underground_lake | Deep blue, reflective        |

### New Visual Elements

- **Keep walls**: 2x thick outer walls + battlement notches
- **Streets**: cobblestone pattern (small random rectangles)
- **Cart tracks**: parallel lines + cross-ties
- **Cave mouth tiles**: cliff face with dark openings (PNG)

Note: floor labels (tower level numbers, etc.) belong in
the debug overlay, not in player-facing SVG. Location is
already reported in the status bar.

### Model Additions

```python
# Tile
is_street: bool = False
is_track: bool = False
```

### New Room Type Tints

```python
barracks:    #C0B0A0 @ 0.06
courtyard:   #D0E0C0 @ 0.06
gate:        #B0A090 @ 0.06
market:      #E0D0B0 @ 0.06
residential: #D8D0C0 @ 0.06
```

### Files

After Phase 2 modularization, extensions go into the
appropriate sub-module rather than the monolithic svg.py:

| Module              | Extension                   |
|---------------------|-----------------------------|
| `_room_outlines.py` | New shape outline cases     |
| `_terrain_detail.py`| New terrain renderers       |
| `_floor_detail.py`  | Cobblestone, track patterns |
| `_walls_floors.py`  | Thick keep walls, battlements |
| `terrain_palette.py`| New palette entries         |

---

## 8. Building Generator

### Problem

Current generators model a single `Level`. Towers, mansions,
and keeps collapse into one floor of rooms. The settlement
generator has no "building" primitive -- each building is a
room tagged with a district. SVG rendering has no material
vocabulary for exterior walls (brick, stone), site enclosures
(fortification wall, palisade), or surface types (field,
garden, street beyond cobblestone).

### Solution: Building + Site

A new `Building` dataclass owns a list of `Level` floors that
share a base shape. A `Site` composes Buildings with walkable
surface and an optional enclosure. Site assemblers
(`tower`, `farm`, `mansion`, `keep`, `town`) replace the
current `procedural:keep` template and the single-level
settlement generator.

### Scope

Full design lives in `design/building_generator.md`. Summary
of model changes, rendering additions, and 16 milestones
there.

### Subsumption

- `procedural:keep` template and its `add_battlements` /
  `add_gate` transforms are removed. The new keep site
  assembler uses `add_fortification_wall` +
  `add_fortification_gate` instead.
- The existing settlement generator is reframed as the
  `town` site assembler, producing `Building` instances per
  district instead of single-level rooms.
- `Tile.is_corridor` / `is_street` / `is_track` booleans are
  migrated into a single `Tile.surface_type` enum (adds
  FIELD, GARDEN, PALISADE, FORTIFICATION).

### Files (overview -- full table in the dedicated doc)

| Action | Path                                    |
|--------|-----------------------------------------|
| Create | `nhc/dungeon/building.py`               |
| Create | `nhc/dungeon/site.py`                   |
| Create | `nhc/dungeon/sites/{tower,farm,         |
|        | mansion,keep,town}.py`                  |
| Create | `nhc/rendering/_building_walls.py`      |
| Create | `nhc/rendering/_enclosures.py`          |
| Modify | `nhc/dungeon/model.py` (Tile,           |
|        | LShape, Level back-refs)                |
| Modify | `nhc/dungeon/transforms.py` (replace    |
|        | battlements/gate with fortification)    |
| Modify | `nhc/dungeon/generators/settlement.py`  |
| Modify | `nhc/rendering/_floor_detail.py`        |
| Modify | `nhc/hexcrawl/model.py` (DungeonRef     |
|        | site_kind)                              |

---

## Implementation Phases

```
Phase 0a: BSP Modularization ──┐
Phase 0b: SVG Modularization ──┤ (can run in parallel)
                               │
Phase 1: Foundation ───────────┘
  │
  ├── Phase 2: Variants (tower/crypt/mine)
  │     │
  │     └── Phase 3: Keep (walled layout)   ── subsumed
  │           │                                 by Phase 8
  │     Phase 4: Settlements (parallel with 2-3) ── subsumed
  │           │                                    by Phase 8
  │     Phase 5: Underworld
  │           │
  │           └── Phase 6: Caves of Chaos
  │
  └── Phase 8: Building Generator (see building_generator.md)
```

Phase 3 (Keep) and Phase 4 (Settlements) remain useful as
early spikes but are superseded by Phase 8 once the Building
primitive lands. The site assemblers in Phase 8 replace the
single-level `procedural:keep` template and reframe the
settlement generator as a Building consumer.

### Phase 0a: BSP Generator Modularization

Pure refactoring. Extract 9 modules from `bsp.py`. One
commit per module extraction. All existing tests pass
after each commit.

### Phase 0b: SVG Renderer Modularization

Pure refactoring. Extract 11 modules from `svg.py`. One
commit per module extraction. Visual comparison confirms
identical rendering.

### Phase 1: Foundation

- Add `template` field to `GenerationParams`
- Create `nhc/dungeon/templates.py` with registry
- Modify `pipeline.py` for template routing
- Extend `DungeonRef` with `size_class` and `faction`
- Add `is_street` and `is_track` to `Tile`
- Tests: round-trip serialization, template resolution
- Commit: foundation plumbing

### Phase 2: Structural Variants (Tower, Crypt, Mine)

- Implement layout strategies: radial, linear
- Implement post-generation transforms
- Wire templates through `enter_hex_feature`
- Add theme palettes for tower, mine
- Tests: generate with each template, assert structural
  properties (room shapes, corridor patterns)
- Commit per variant

### Phase 3: Keep / Walled Layout

- Implement walled layout strategy
- Keep template with battlements transform
- SVG thick outer wall rendering
- New room types: barracks, courtyard, gate
- Tests: walled layout has contiguous border, gate room
- Commit: keep generator + rendering

### Phase 4: Settlement Generator

- District-based layout generator
- District types and building pools
- Street carving and city wall generation
- SVG street rendering (cobblestone in `_floor_detail.py`)
- Tests: rooms tagged with districts, streets connect,
  city-size has walls
- Commit per milestone (generator, rendering)

### Phase 5: Mega-Dungeon / Underworld

- UnderworldRegion dataclass
- Extend cave cluster assignment
- Generalize floor 2 to N floors
- Underground biome themes and palettes
- Lateral connections between sectors
- Tests: depth scales with cluster, cache keys resolve
- Commit per milestone

### Phase 6: Caves of Chaos Pattern

- FeaturePattern placement system
- Caves of Chaos definition
- Faction-per-cave wiring to populator
- Pack YAML schema for patterns
- Tests: pattern places keep + caves, distinct factions
- Commit per milestone

### Phase 8: Building Generator

See `design/building_generator.md` for the full design, test
strategy, and 16-milestone implementation plan. One commit
per milestone. Supersedes Phase 3 (`procedural:keep`
template) and Phase 4 (single-level settlement generator).

---

## Verification

After each phase:

1. Run `.venv/bin/pytest -n auto --dist worksteal -m "not slow"`
2. Start web server (`./server`), generate hex world,
   visually verify new dungeon types render correctly
3. Enter each new dungeon variant and confirm playability
4. Use MCP debug tools (`get_game_snapshot`, `get_room_info`)
   to inspect generated structure
