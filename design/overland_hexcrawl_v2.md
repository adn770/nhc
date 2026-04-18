# NHC -- Overland Hexcrawl V2: Continental World Generator

Design document for a geologically-inspired world map generator
that replaces the BSP and Perlin generators. Produces organic
continents, tectonic mountain ranges, erosion-carved drainage
basins, and terrain-aware placement of rivers, settlements, and
roads.

This document supersedes the generator sections (7, rivers, and
paths) of `overland_hexcrawl.md` once the implementation is
proven. All other sections of the v1 document (vision, game
modes, data model, gameplay loop, rendering, debug tools, and
phasing) remain authoritative.

---

## 1. Overview

### 1.1 Problem

The BSP generator produces blocky regions with synthetic
elevation. The Perlin generator produces organic landforms but
with blobby coastlines and no geological coherence -- mountain
ranges appear as scattered peaks, rivers follow arbitrary
downhill walks, and settlements are placed randomly within biome
pools.

### 1.2 Solution

A nine-stage linear pipeline that builds terrain the way a
planet does: continental crust, tectonic plates, erosion, then
life (biomes, rivers, civilisation). Each stage is a pure
function with well-defined inputs and outputs, independently
testable.

### 1.3 Deprecation Plan

1. Implement the v2 generator as `continental_v2` alongside the
   existing `bsp_regions` and `perlin_regions` generators.
2. Create a new `testland-v2` content pack that uses the v2
   generator.
3. Once playtested and stable, switch the default pack to v2.
4. Mark BSP and Perlin generators as deprecated in code.
5. Remove deprecated generators in a later release.

---

## 2. Pipeline Architecture

### 2.1 Stage Contract

Every stage is a function with the signature:

```
stage_X(ctx: PipelineContext, rng: Random) -> StageResult
```

`PipelineContext` is a frozen dataclass that accumulates the
results from prior stages. Each stage reads only the fields it
needs and returns a new result dataclass. The pipeline runner
threads context forward.

```
Continental Shape  ->  elevation draft
       |
Tectonic Plates    ->  plate assignment, boundaries
       |
Domain Warping     ->  warped elevation + tectonic boost
       |
Hydraulic Erosion  ->  eroded elevation, flow graph, drainage basins
       |
Biome Assignment   ->  cells with biomes, hexes_by_biome
       |
Rivers             ->  river paths, edge segments, lakes
       |
Settlements        ->  scored placement of towns and cities
       |
Roads              ->  road paths, dead-end towers/keeps
       |
Flowers + Tiles    ->  sub-hex flowers, tile slots, edge continuity
       |
       v
   HexWorld
```

### 2.2 Orchestrator

```python
def generate_continental_world(
    seed: int,
    pack: PackMeta,
    max_attempts: int = 10,
) -> HexWorld:
```

Registered as `"continental_v2"` in `KNOWN_GENERATORS`. The
retry loop guards against the rare case where the full pipeline
produces a world that fails feature-placement validation.

### 2.3 Pack Configuration

New `continental` block in `pack.yaml`:

```yaml
map:
  generator: continental_v2
  width: 25
  height: 16
  continental:
    # Stage 1: Continental shape
    continent_frequency: 0.06
    continent_octaves: 3
    island_falloff: 0.8       # radial edge falloff strength
    sea_level: -0.25

    # Stage 2: Tectonic plates
    plate_count: 6

    # Stage 3: Domain warping
    warp_amplitude: 0.4
    warp_frequency: 0.15

    # Stage 4: Erosion
    erosion_iterations: 4
    erosion_rate: 0.15
    deposit_rate: 0.3

    # Stage 6: Rivers (extends existing RiverParams)
    lake_chance: 0.3          # chance a river ends in a lake
```

Parsed into a `ContinentalParams` dataclass in `pack.py`. The
existing `RiverParams`, `PathParams`, and `biome_costs` fields
on `PackMeta` are reused unchanged for stages 6-8.

---

## 3. Stage 1: Continental Shape

**Purpose**: Define where the oceans and continents are using
low-frequency simplex noise with an island mask.

### 3.1 Algorithm

1. Instantiate `SimplexNoise(seed=rng.randrange(1 << 30))` for
   the continent field.
2. For every valid hex `(q, r)` in the rectangular odd-q shape,
   compute planar coordinates:
   ```
   fx = q * continent_frequency
   fy = (r + q * 0.5) * continent_frequency
   ```
3. Sample `noise.fractal(fx, fy, octaves=continent_octaves)` to
   get a raw continent value in `[-1, 1]`.
4. Apply an island mask to push edges toward ocean:
   ```
   cx = (q - width/2) / (width/2)
   cy = (r - height/2) / (height/2)
   dist = sqrt(cx^2 + cy^2) / sqrt(2)
   mask = 1.0 - (dist * island_falloff)^2
   continent_value *= max(mask, 0)
   ```
5. Values above `sea_level` are land; below are ocean.

### 3.2 Output

`continent_field: dict[HexCoord, float]` -- raw continental
elevation for every hex, range `[-1, 1]`.

### 3.3 Tests

- Field is bounded in `[-1, 1]`.
- Island mask keeps edge hexes lower than center hexes on
  average.
- Different seeds produce different land/sea ratios.
- Same seed reproduces identically.

---

## 4. Stage 2: Tectonic Plates

**Purpose**: Define "plates" via Voronoi tessellation on the hex
grid. Plate boundaries determine where mountain ranges form.

### 4.1 Algorithm

1. **Site placement**: Pick `plate_count` (5-8) sites uniformly
   at random from valid hex coordinates. Bias 1-2 sites toward
   the center to ensure at least one interior plate.

2. **Cell assignment**: For each hex, compute hex distance
   (`coords.distance()`) to every site. Assign to the nearest
   site. With ~400 hexes and 6-8 sites, this is O(N*K) -- under
   a millisecond.

3. **Plate properties**:
   - `drift_vector: (float, float)` -- random in `[-1, 1]^2`
   - `is_oceanic: bool` -- true if centroid falls below
     `sea_level` in the continent field

4. **Boundary detection**: A hex is a plate boundary if any of
   its 6 neighbours belongs to a different plate.

5. **Boundary classification**: For each boundary hex, compute
   relative motion of the two plates:
   - **Convergent** (vectors converge): mountain uplift
   - **Divergent** (vectors diverge): rift/depression
   - **Transform** (vectors parallel): hills/neutral

   Classification uses the dot product of the relative drift
   vector with the boundary normal (vector from one plate
   centroid to the other):
   ```
   relative = drift_a - drift_b
   normal = normalize(centroid_b - centroid_a)
   dot = relative . normal
   if dot < -threshold:  convergent
   elif dot > threshold: divergent
   else:                 transform
   ```

### 4.2 Output

```python
@dataclass(frozen=True)
class PlateResult:
    plate_of: dict[HexCoord, int]          # hex -> plate id
    boundaries: set[HexCoord]              # all boundary hexes
    convergent: set[HexCoord]              # mountain boundaries
    divergent: set[HexCoord]               # rift boundaries
    transform: set[HexCoord]               # neutral boundaries
```

### 4.3 Tests

- Every hex is assigned to exactly one plate.
- Boundary hexes have at least one cross-plate neighbour.
- Convergent, divergent, and transform sets are disjoint subsets
  of boundaries.
- Plate count matches `plate_count` parameter.

---

## 5. Stage 3: Domain Warping

**Purpose**: Warp the noise sampling coordinates so coastlines
look organic and non-circular. Combine with tectonic elevation
to produce the pre-erosion heightmap.

### 5.1 Algorithm

1. Create two `SimplexNoise` instances (`warp_x_noise`,
   `warp_y_noise`) with independent seeds.

2. For each hex `(q, r)`, compute the warp displacement:
   ```
   warp_dx = warp_x.fractal(fx * warp_freq, fy * warp_freq,
                             octaves=2) * warp_amplitude
   warp_dy = warp_y.fractal(fx * warp_freq, fy * warp_freq,
                             octaves=2) * warp_amplitude
   ```

3. Re-sample the continent noise at warped coordinates:
   ```
   warped_elev = continent_noise.fractal(
       fx + warp_dx, fy + warp_dy,
       octaves=continent_octaves,
   )
   ```
   Re-apply the island mask after warping.

4. Combine with tectonic plate data:
   - **Convergent boundaries**: elevation boost `+0.3` to
     `+0.5`, smoothed by distance (linear ramp over 2-3 hexes).
   - **Divergent boundaries**: depression `-0.1`.
   - **Transform boundaries**: small hill boost `+0.1`.
   ```
   for hex in boundaries:
       if hex in convergent:
           boost = uniform(0.3, 0.5)
       elif hex in divergent:
           boost = -0.1
       else:
           boost = 0.1
       elevation[hex] += boost
       # Fade the boost into neighbouring hexes
       for dist in [1, 2]:
           for nbr in ring(hex, dist):
               if nbr in elevation:
                   elevation[nbr] += boost * (1 - dist / 3)
   ```

5. Clamp all elevations to `[-1, 1]`.

### 5.2 Output

`elevation_field: dict[HexCoord, float]` -- the combined
continental shape + tectonic influence + domain warping.

### 5.3 Tests

- Warped coastlines differ from unwarped ones (different
  land/sea hex counts for the same seed with warp on vs off).
- Convergent boundary hexes have higher elevation than their
  plate interiors on average.
- All values clamped to `[-1, 1]`.
- Deterministic across runs with the same seed.

---

## 6. Stage 4: Hydraulic Erosion

**Purpose**: Simulate water flow to carve mountain peaks, fill
valleys, and create natural drainage basins. Adapted for the
~400-cell hex grid (too coarse for individual droplets).

### 6.1 Algorithm: Iterative Flow Accumulation

Traditional particle erosion requires thousands of cells to
produce visible results. At hex-grid scale, an iterative
flow-accumulation approach is more effective:

1. **Moisture noise**: Create a `SimplexNoise` instance for
   moisture. Sample for every hex to get `moisture_field`.

2. **Iterate** `erosion_iterations` times (3-5):

   a. **Flow direction**: For each land hex, find the
      steepest-descent neighbour (lowest elevation among hex
      neighbours). Build `flow_to: dict[HexCoord, HexCoord | None]`.

   b. **Flow accumulation**: Starting from every hex, walk the
      flow graph downstream, incrementing
      `flow_count: dict[HexCoord, int]` at each step visited.
      Cap walk length at 30 to prevent infinite loops on flat
      terrain.

   c. **Erosion**: Reduce elevation proportionally to flow:
      ```
      elev[h] -= erosion_rate * log(1 + flow_count[h])
      ```
      The logarithm dampens the effect so high-flow cells don't
      collapse to zero.

   d. **Deposition**: Where flow slows (flow_count decreases
      from upstream to downstream), increase elevation:
      ```
      if flow_count[h] < flow_count[upstream]:
          elev[h] += deposit_rate * (
              flow_count[upstream] - flow_count[h]
          ) * 0.01
      ```

   e. Clamp elevations to `[-1, 1]`.

3. **Drainage basin identification**: After erosion, compute
   connected components of the flow graph. Each tree rooted at
   a local minimum (no downhill neighbour, or flows to sea) is a
   drainage basin. Store `basins: dict[HexCoord, int]`.

4. **Moisture enhancement**: Increase moisture in high-flow
   hexes to create naturally wet river valleys:
   ```
   moisture[h] += 0.2 * log(1 + flow_count[h]) / log(1 + max_flow)
   ```

### 6.2 Output

```python
@dataclass(frozen=True)
class ErosionResult:
    elevation: dict[HexCoord, float]
    moisture: dict[HexCoord, float]
    flow_to: dict[HexCoord, HexCoord | None]
    flow_count: dict[HexCoord, int]
    basins: dict[HexCoord, int]    # hex -> basin id
```

### 6.3 Tests

- Elevation is bounded in `[-1, 1]`.
- Total elevation sum decreases after erosion (net material
  removal).
- Flow accumulation is monotonically non-decreasing downstream.
- Drainage basins cover all land hexes.
- High-flow hexes have higher moisture than surrounding hexes.

---

## 7. Stage 5: Biome Assignment

**Purpose**: Map the post-erosion elevation and moisture fields
to biomes using a Whittaker-style lookup, with tectonic plate
data for mountain range coherence.

### 7.1 Algorithm

Reuse and extend the existing `_biome_from_em` Whittaker lookup:

```
elevation >= 0.55              -> MOUNTAIN
0.35 <= e < 0.55, m >= 0.20   -> HILLS
0.35 <= e < 0.55, m < 0.20    -> DRYLANDS
0.20 <= e < 0.35, m >= 0.50   -> FOREST
0.20 <= e < 0.35, m >= -0.20  -> GREENLANDS
0.20 <= e < 0.35, m < -0.20   -> DRYLANDS
-0.10 <= e < 0.20, m >= 0.60  -> SWAMP
-0.10 <= e < 0.20, m >= 0.20  -> MARSH
-0.10 <= e < 0.20, m >= -0.30 -> SANDLANDS
-0.10 <= e < 0.20, m < -0.30  -> DEADLANDS
e < sea_level                  -> WATER
otherwise                      -> ICELANDS
```

Modifications from the current implementation:

1. **Sea level from config**: WATER assigned below `sea_level`
   (configurable, not hardcoded `-0.35`).

2. **Mountain range coherence**: Convergent plate boundaries get
   MOUNTAIN biome even if elevation is only moderately high
   (threshold lowered to `0.45` at convergent boundaries). This
   prevents scattered peaks and creates coherent ranges.

3. **Essential biome repair**: Reuse `_repair_essentials` from
   the current generator to guarantee GREENLANDS, MOUNTAIN,
   FOREST, and ICELANDS are present on every seed.

### 7.2 Output

- `cells: dict[HexCoord, HexCell]` with biome and elevation.
- `hexes_by_biome: dict[Biome, list[HexCoord]]`.

### 7.3 Tests

- Every essential biome is present.
- Mountain hexes cluster along plate boundaries (>50% of
  mountain hexes should be within 2 hexes of a convergent
  boundary).
- Biome diversity: at least 6 distinct biomes per seed.
- No WATER hexes above sea level; no land hexes below it (after
  repair).

---

## 8. Stage 6: Rivers

**Purpose**: Trace rivers from mountain sources to low-elevation
sinks (lakes, sea) following natural drainage patterns. Rivers
interact with the micro-tile system for forest routing and dense
forest adjacency.

### 8.1 Source Selection

Mountain hexes with `elevation >= source_elevation_min` (from
`RiverParams`). Prefer sources at the headwaters of the largest
drainage basins (highest flow accumulation among mountain hexes).

### 8.2 Macro-Level Routing

Extend the existing downhill-walk algorithm:

1. **Forest crossing allowed**: Remove FOREST from
   `avoided_biomes`. Rivers CAN cross forest macro-tiles, but
   the step cost is higher (weight multiplier 0.5x for forest
   neighbours, making them less preferred but not blocked).

2. **Drylands/sandlands termination**: If a river enters a
   drylands or sandlands hex, it terminates. The river dries up.
   It does not route around these biomes.

3. **Lake creation**: When a river reaches a low-elevation hex
   (elevation < 0.15) in greenlands or marsh, roll against
   `lake_chance` (default 0.3). On success, place a
   `HexFeatureType.LAKE` feature and terminate the river. This
   creates natural inland lakes at drainage convergence points.

4. **Sea termination**: Rivers reaching a WATER hex terminate
   normally (existing behaviour).

5. **Edge segments**: Same `_stamp_edges` as current.

### 8.3 Micro-Level Routing (Flower Integration)

Within each macro hex's 19-cell flower:

1. **Forest biome micro-routing**: The existing
   `route_river_through_flower` already penalises forest
   sub-hexes (cost 5.0). The river naturally routes through
   clearings and low-density sub-hexes.

2. **Dense forest adjacency**: After the river path is routed
   through a forest-biome flower, mark sub-hexes adjacent to the
   river path (within 1 hex of any river sub-hex) as dense
   forest. Implementation:
   ```python
   for river_cell in river_sub_path:
       for nbr in flower_neighbors(river_cell):
           if nbr in flower.cells and nbr not in river_sub_path:
               flower.cells[nbr].biome = Biome.FOREST
               # Use a dense-canopy tile slot
   ```
   This creates the natural pattern of thick vegetation along
   riverbanks in forested areas.

### 8.4 Configuration

Extends existing `RiverParams` with:

```python
lake_chance: float = 0.3         # chance of lake at convergence
lake_elevation_max: float = 0.15 # only create lakes below this
```

### 8.5 Tests

- Rivers start at mountain hexes (existing test, preserved).
- Rivers terminate in drylands/sandlands (new test).
- Rivers can cross forest macro-tiles (new test -- reverses
  current behaviour).
- Lake features appear at low-elevation termination points.
- Edge segment entry/exit indices are consistent.
- Dense forest sub-hexes flank river paths in forest flowers.

---

## 9. Stage 7: Settlement Placement

**Purpose**: Place towns, cities, and the hub using a scoring
function that prefers geographically advantageous locations:
biome borders, river proximity, and lake proximity.

### 9.1 Scoring Function

For each candidate hex:

```python
def settlement_score(coord, cells) -> float:
    score = 0.0
    cell = cells[coord]

    # 1. Biome border bonus: +3 per distinct neighbour biome
    neighbor_biomes = {
        cells[n].biome for n in neighbors(coord) if n in cells
    }
    score += 3.0 * len(neighbor_biomes - {cell.biome})

    # 2. River proximity: +5 if on a river, +3 if adjacent
    has_river = any(s.type == "river" for s in cell.edges)
    if has_river:
        score += 5.0
    elif any(
        any(s.type == "river" for s in cells[n].edges)
        for n in neighbors(coord) if n in cells
    ):
        score += 3.0

    # 3. Lake proximity: +4 if adjacent to a lake
    for n in neighbors(coord):
        if n in cells and cells[n].feature == HexFeatureType.LAKE:
            score += 4.0
            break

    # 4. Biome suitability
    _BIOME_BONUS = {
        Biome.GREENLANDS: 2.0,
        Biome.HILLS: 1.5,
        Biome.FOREST: 0.5,
        Biome.DRYLANDS: 0.5,
        Biome.SANDLANDS: -1.0,
        Biome.MARSH: -1.0,
        Biome.SWAMP: -2.0,
    }
    score += _BIOME_BONUS.get(cell.biome, 0.0)

    # 5. Elevation preference: mid-elevation is best
    if 0.15 <= cell.elevation <= 0.45:
        score += 1.0

    return score
```

### 9.2 Candidate Biomes

Settlements may appear in: GREENLANDS, HILLS, FOREST, DRYLANDS,
SANDLANDS (border only), MARSH (border only), SWAMP (border
only).

Settlements may NOT appear in: MOUNTAIN, WATER, ICELANDS,
DEADLANDS.

### 9.3 Placement Algorithm

1. Score all candidate hexes.
2. Sort by score descending.
3. Place greedily, enforcing minimum spacing (no two settlements
   adjacent -- reuse existing `_adjacent_to_settlement` check).
4. The hub is placed at the highest-scoring GREENLANDS hex.
5. Cities are placed at the next highest-scoring hexes. Villages
   fill remaining slots.

### 9.4 Tests

- River-adjacent + border hexes score higher than inland +
  single-biome hexes.
- Settlement spacing is maintained (no adjacent settlements).
- Hub is always in GREENLANDS.
- Settlement count falls within pack targets.

---

## 10. Stage 8: Roads

**Purpose**: Connect settlements via terrain-aware A* routing.
Dead-end roads get defensive structures. Roads cross rivers
perpendicularly. Cave entrances connect to the nearest road.

### 10.1 Macro-Level Routing

Reuse the existing A* infrastructure (`hex_astar`) with modified
cost weights:

```python
_ROAD_COSTS = {
    Biome.GREENLANDS: 1,
    Biome.HILLS: 2,
    Biome.DRYLANDS: 3,
    Biome.MARSH: 3,
    Biome.SWAMP: 4,
    Biome.FOREST: 6,        # high cost, not blocked
    Biome.SANDLANDS: 15,    # heavily penalised
    Biome.DEADLANDS: 15,    # heavily penalised
    Biome.MOUNTAIN: 8,      # passable but expensive
    Biome.ICELANDS: 5,
    Biome.WATER: 99,        # impassable
}
```

Dense-forest micro-tiles are blocked at the sub-hex routing
level, not the macro level (roads can cross forest macro-tiles
via clearings, just like rivers).

### 10.2 Settlement Connectivity

1. Build MST over all settlements using hex distance (reuse
   `_settlement_mst`).
2. A* each MST edge to get the terrain route.
3. Optionally connect towers/keeps to nearest settlement (reuse
   existing `connect_towers` probability).

### 10.3 Dead-End Detection and Tower/Keep Placement

After generating all roads, scan for road endpoints that are not
settlements:

```python
for path in paths:
    for endpoint in [path[0], path[-1]]:
        if cells[endpoint].feature not in _SETTLEMENT_FEATURES:
            if cells[endpoint].feature is HexFeatureType.NONE:
                cells[endpoint].feature = rng.choice(
                    [HexFeatureType.TOWER, HexFeatureType.KEEP]
                )
```

### 10.4 Cave Path Bifurcation

Cave entrances connect to the **nearest existing road** (not
the nearest settlement):

1. For each cave hex, find the closest hex that carries a path
   edge segment.
2. A* from the cave to that hex.
3. At the junction, the existing edge segment system handles the
   overlap naturally (the junction hex gets two path segments).

### 10.5 Perpendicular River Crossing (Micro-Level)

When a macro hex has both a road and a river, the micro-level
routing ensures they cross at roughly right angles:

1. During flower generation, route the river first (it has
   natural priority -- water doesn't care about roads).
2. When routing the road through the same flower, identify the
   river's local direction at each sub-hex it occupies.
3. Choose road entry/exit edge sub-hexes (from `EDGE_TO_RING2`)
   that maximise the crossing angle with the river direction.
   On a hex grid, the minimum crossing angle between two paths
   is 60 degrees, which is inherently close to perpendicular.
4. The A* cost function gives a small bonus to sub-hexes that
   cross the river path at wider angles:
   ```python
   if sub_hex in river_path_cells:
       # Compute angle between road direction and river direction
       angle = abs(road_dir - river_dir)
       if angle >= 60:  # degrees
           cost *= 0.5  # bonus for perpendicular crossing
   ```

### 10.6 Tests

- Roads avoid sandlands and deadlands (or take expensive
  detours).
- Dead-end road endpoints have TOWER or KEEP features.
- Road-river crossings exist in hexes with both segment types.
- Cave paths join existing roads, not just settlements.

---

## 11. Stage 9: Edge-Point Continuity (Macro + Micro)

**Purpose**: Ensure rivers and roads don't have visual breaks at
hex boundaries. Random crossing points along hex edges replace
the fixed midpoints, but adjacent hexes share the same point so
lines connect seamlessly. This applies at both the macro
(overland map) and micro (flower sub-hex) levels.

### 11.1 Macro-Level Edge Points

Currently, macro rendering draws curves to/from the fixed edge
midpoint of each hex side. The v2 system replaces midpoints with
random points along the edge, shared between adjacent hexes.

**Data model**: The `EdgeSegment` dataclass gains offset fields:

```python
@dataclass
class EdgeSegment:
    type: str                                  # "river" | "path"
    entry_edge: int | None                     # 0-5 or None
    exit_edge: int | None                      # 0-5 or None
    entry_offset: float | None = None          # NEW: -0.4..+0.4
    exit_offset: float | None = None           # NEW: -0.4..+0.4
```

The offset is a signed fraction along the hex edge, where 0.0
is the midpoint and the range `[-0.4, +0.4]` keeps points away
from vertices. The sign convention follows the edge direction
(clockwise around the hex).

**Allocation**: After edge stamping (rivers and roads), a
registry pass assigns offsets to every shared edge:

```python
# Canonical key: (min(a, b), max(a, b), edge_type)
# so both hexes look up the same value.
def _assign_macro_offsets(
    cells: dict[HexCoord, HexCell],
) -> None:
    seen: dict[tuple[HexCoord, HexCoord, str], float] = {}
    for coord, cell in cells.items():
        for seg in cell.edges:
            for edge, attr in [
                (seg.entry_edge, "entry_offset"),
                (seg.exit_edge, "exit_offset"),
            ]:
                if edge is None:
                    continue
                nbr = neighbors(coord)[edge]
                key = (min(coord, nbr), max(coord, nbr),
                       seg.type)
                if key not in seen:
                    h = _edge_hash(key)
                    seen[key] = ((h % 81) - 40) / 100  # -0.4..+0.4
                setattr(seg, attr, seen[key])
```

**Rendering**: Both JS (`hex_map.js`) and Python
(`generate_hexmap.py`) renderers convert the offset to a pixel
displacement along the edge vector:

```python
# Edge midpoint + offset along edge tangent
mid = edge_midpoints[edge_idx]
tangent = edge_tangents[edge_idx]  # unit vector along edge
point = (mid[0] + offset * tangent[0] * edge_length,
         mid[1] + offset * tangent[1] * edge_length)
```

The edge tangent vectors for a flat-top hex (6 edges):

```
Edge 0 (N):  tangent = (1, 0)        # horizontal top edge
Edge 1 (NE): tangent = (0.5, s3/2)   # angled down-right
Edge 2 (SE): tangent = (-0.5, s3/2)  # angled down-left
Edge 3 (S):  tangent = (-1, 0)       # horizontal bottom edge
Edge 4 (SW): tangent = (-0.5, -s3/2) # angled up-left
Edge 5 (NW): tangent = (0.5, -s3/2)  # angled up-right
```

**Serialisation**: `web_client.py` includes the offsets in the
`state_hex` payload:

```json
"edges": [{
    "type": "river",
    "entry": 2,
    "exit": 4,
    "entry_offset": 0.15,
    "exit_offset": -0.22,
    "sub_path": [...]
}]
```

### 11.2 Micro-Level Edge Points (Flower Sub-Hex)

Before generating any flowers, pre-allocate a fixed sub-hex for
every shared edge between adjacent hexes that carry a river or
road:

```python
@dataclass(frozen=True)
class MicroEdgePoint:
    sub_hex: HexCoord             # ring-2 sub-hex at the edge
    offset: tuple[float, float]   # pixel offset within sub-hex
```

```python
# Key: canonical pair (coord_a, coord_b) where a < b
micro_edge_registry: dict[
    tuple[HexCoord, HexCoord],
    MicroEdgePoint,
]
```

**Allocation algorithm**: For each pair of adjacent hexes
sharing a river or road segment:

1. Determine the macro edge index for the shared edge.
2. From `EDGE_TO_RING2[edge]`, there are 2 candidate sub-hexes
   on each side.
3. Pick one randomly using a hash of the pair's coordinates
   (deterministic, no RNG state consumed):
   ```python
   h = _edge_hash((min(a, b), max(a, b)))
   idx = h % 2
   ```
4. The chosen sub-hex on side A becomes the exit point; its
   mirror on side B becomes the entry point.

**Pixel-level offset within sub-hex**: For visual variation,
each micro edge point gets a small random displacement:

```python
offset_x = ((h >> 8) % 5 - 2) * 0.15   # [-0.3, 0.3]
offset_y = ((h >> 16) % 5 - 2) * 0.15
```

### 11.3 Shared Hash Function

Both macro and micro registries use the same deterministic hash
so no RNG state is consumed:

```python
def _edge_hash(key: tuple) -> int:
    """Deterministic hash for edge-point allocation."""
    a, b = key[0], key[1]
    h = (a.q * 7919 + a.r * 104729
         + b.q * 34159 + b.r * 65537) & 0x7FFFFFFF
    h = ((h >> 16) ^ h) * 0x45D9F3B
    return ((h >> 16) ^ h) & 0x7FFFFFFF
```

This mirrors the `_jitter_hash` used by both renderers, keeping
all hash-based randomness in the same family.

### 11.4 Flower Routing Integration

The existing `route_river_through_flower` and
`route_road_through_flower` functions gain optional parameters:

```python
def route_river_through_flower(
    flower: HexFlower,
    ...,
    forced_entry: HexCoord | None = None,
    forced_exit: HexCoord | None = None,
) -> ...:
```

When `forced_entry` or `forced_exit` is provided, the routing
uses that sub-hex instead of randomly selecting from
`EDGE_TO_RING2`.

### 11.5 Data Model Changes

**Macro `EdgeSegment`** gains offset fields:

```python
@dataclass
class EdgeSegment:
    type: str
    entry_edge: int | None
    exit_edge: int | None
    entry_offset: float | None = None     # NEW
    exit_offset: float | None = None      # NEW
```

**Micro `SubHexEdgeSegment`** gains offset fields:

```python
@dataclass
class SubHexEdgeSegment:
    type: str
    path: list[HexCoord]
    entry_macro_edge: int | None
    exit_macro_edge: int | None
    entry_offset: tuple[float, float] | None = None  # NEW
    exit_offset: tuple[float, float] | None = None    # NEW
```

### 11.6 Tests

**Macro continuity:**
- For every pair of adjacent hexes sharing a segment, the exit
  offset on hex A equals the entry offset on hex B (same
  physical point on the shared edge).
- Offsets are bounded in `[-0.4, +0.4]`.
- Offsets are deterministic given the same coordinates.

**Micro continuity:**
- For every pair of adjacent hexes sharing a segment, the exit
  sub-hex of hex A and the entry sub-hex of hex B correspond to
  the same edge position.
- Sub-hex pixel offsets are deterministic given the same seed.

**Cross-renderer:**
- The JS renderer and Python sample renderer produce the same
  crossing point for a known `(coord_a, coord_b, edge)` triple
  (verified by a shared test vector table).

**Visual:**
- No visible breaks in river/road lines at hex boundaries
  (manual inspection via debug renderer and web view).

---

## 12. File Layout

### 12.1 New Modules

```
nhc/hexcrawl/
    _gen_v2.py          # pipeline runner + stages 1-5
    _rivers_v2.py       # stage 6: enhanced river generation
    _features_v2.py     # stage 7: scored settlement placement
    _paths_v2.py        # stage 8: enhanced road generation

tests/unit/hexcrawl/
    test_gen_v2.py       # pipeline and stage tests
    test_rivers_v2.py    # river-specific tests
    test_features_v2.py  # settlement scoring tests
    test_paths_v2.py     # road-specific tests
```

### 12.2 Modified Modules

- `nhc/hexcrawl/pack.py` -- add `ContinentalParams` dataclass,
  `"continental_v2"` to `KNOWN_GENERATORS`, parser.
- `nhc/hexcrawl/generator.py` -- add
  `generate_continental_world` dispatch function.
- `nhc/hexcrawl/_flowers.py` -- add `forced_entry`/`forced_exit`
  parameters to routing functions; add dense-forest adjacency
  logic after river routing in forest biomes.
- `nhc/hexcrawl/model.py` -- add `entry_offset`/`exit_offset`
  fields to `SubHexEdgeSegment`.
- `nhc/rendering/web_client.py` -- serialise new offset fields.
- `nhc/web/static/js/hex_map.js` -- consume offset fields in
  `_drawEdgeSegment`.

### 12.3 New Content Pack

```
content/testland-v2/
    pack.yaml           # generator: continental_v2
```

### 12.4 Reused As-Is

- `nhc/hexcrawl/noise.py` -- `SimplexNoise` is used by all
  stages that need noise fields. No changes needed.
- `nhc/hexcrawl/coords.py` -- hex math, neighbours, distance,
  rings.
- `nhc/hexcrawl/tiles.py` -- tile slot assignment (runs after
  the pipeline, same as current).
- `nhc/hexcrawl/model.py` -- `HexCell`, `HexWorld`,
  `EdgeSegment`, `Biome`, `HexFeatureType` (all preserved).

---

## 13. Development Discipline

### 13.1 TDD: Tests First, Always

Every pipeline stage follows strict TDD. The workflow for each
stage is:

1. **Write failing tests** for the stage's contract (inputs,
   outputs, invariants) before writing any production code.
2. **Implement** the minimum code to make the tests pass.
3. **Refactor** if needed, keeping tests green.
4. **Commit** the stage (tests + implementation together).

No stage is considered complete without its test suite passing.
Tests live alongside the code they exercise:

| Stage | Test file |
|-------|-----------|
| 1-5 (terrain pipeline) | `tests/unit/hexcrawl/test_gen_v2.py` |
| 6 (rivers) | `tests/unit/hexcrawl/test_rivers_v2.py` |
| 7 (settlements) | `tests/unit/hexcrawl/test_features_v2.py` |
| 8 (roads) | `tests/unit/hexcrawl/test_paths_v2.py` |
| 9 (edge continuity) | `tests/unit/hexcrawl/test_gen_v2.py` |
| Integration | `tests/unit/hexcrawl/test_gen_v2.py` |

Run the full suite before every commit:

```bash
.venv/bin/pytest -n auto --dist worksteal -m "not slow"
```

### 13.2 Three Renderers Must Stay in Sync

There are three rendering paths for hex maps. Any change to
edge segment data, sub-hex path format, jitter hashing, or
spline drawing must be updated in **all three** simultaneously:

| Renderer | File | Role |
|----------|------|------|
| JS (web) | `nhc/web/static/js/hex_map.js` | Live game canvas |
| Python (sample) | `tests/samples/generate_hexmap.py` | Offline PNG for visual QA |
| Backend (serialiser) | `nhc/rendering/web_client.py` | WebSocket payload shape |

**What must stay in sync:**

- **Edge midpoint formulas** -- the 6 flat-top hex edge midpoints
  used to anchor river/road curves. Both JS (`mids` array) and
  Python (`_fallback_curve` midpoints, flower `_edge_midpoints`)
  must use the identical formula relative to hex radius.

- **Jitter hash** -- `_jitterHash` in JS and `_jitter_hash` in
  Python must produce the same output for the same `(a, b, c)`
  inputs. A cross-language test should verify a set of known
  `(a, b, c) -> hash` pairs.

- **Catmull-Rom spline** -- the `_drawSubPathCurve` function in
  JS and `_catmull_rom_points` in Python must use the same
  tension parameter and cubic Bezier conversion so curves look
  identical in the browser and in sample PNGs.

- **Sub-path projection** -- local flower coords projected into
  macro hex pixel space at `HEX_SIZE / 2.5` scale. Both
  renderers must agree on this constant.

- **Segment payload shape** -- the WebSocket `state_hex` and
  `state_flower` messages define the JSON keys the JS renderer
  reads (`type`, `entry`, `exit`, `sub_path`, and the new
  `entry_offset`/`exit_offset`). Changes to `web_client.py`
  must be mirrored in `hex_map.js`.

**Verification workflow:**

After any rendering change, generate a sample PNG and compare
against the live web view for the same seed:

```bash
python -m tests.samples.generate_hexmap \
    --seed 42 --generator continental_v2
./server
# Open the game with seed 42, compare visually
```

The `generate_hexmap.py` tool must be extended to support the
`continental_v2` generator (add `--generator continental_v2`
choice and wire to `generate_continental_world`).

### 13.3 Commits at Each Milestone

Each implementation phase produces one or more atomic commits.
A commit is made when a milestone is complete: tests pass, code
is clean, no trailing whitespace.

| Commit | Scope | Gate |
|--------|-------|------|
| A1 | `ContinentalParams` in `pack.py`, pack loading test | `test_pack` green |
| A2 | Stage 1: continental shape + tests | `test_gen_v2::test_continental_shape_*` green |
| A3 | Stage 2: Voronoi plates + tests | `test_gen_v2::test_plates_*` green |
| A4 | Stage 3: domain warping + tests | `test_gen_v2::test_warping_*` green |
| B1 | Stage 4: erosion + tests | `test_gen_v2::test_erosion_*` green |
| B2 | Stage 5: biome assignment + tests | `test_gen_v2::test_biome_*` green |
| C1 | Stage 6: rivers + tests | `test_rivers_v2` green |
| C2 | Stage 7: settlement scoring + tests | `test_features_v2` green |
| C3 | Stage 8: roads + tests | `test_paths_v2` green |
| D1 | Stage 9: edge continuity + tests | `test_gen_v2::test_edge_*` green |
| D2 | Pipeline wiring + integration test | full `test_gen_v2` green |
| D3 | `generate_hexmap.py` v2 support, visual QA | sample PNGs match web |
| D4 | `testland-v2` content pack | playtest pass |
| E1 | Default pack switch | all existing tests still green |
| E2 | Deprecation markers on BSP/Perlin | no regressions |

Commit message style follows the project convention:

```
hexcrawl: add continental shape stage with island mask

Implement Stage 1 of the v2 generator pipeline. Low-frequency
simplex noise defines ocean/land boundaries, with a radial
island mask to keep map edges oceanic. Includes unit tests for
bounds, determinism, and island mask effect.
```

**No commit without green tests.** If a stage's tests fail, fix
before committing. If an earlier stage's tests break, fix the
regression before moving forward.

---

## 14. Implementation Phases

Commits follow the milestone table in section 13.3. Each phase
ends with all prior tests green and a clean commit.

### Phase A: Foundation (Stages 1-3)

No gameplay impact. Can be developed and tested in isolation.

1. Add `ContinentalParams` to `pack.py`, add
   `"continental_v2"` to `KNOWN_GENERATORS`. Tests: pack
   loading.
2. Implement Stage 1 (continental shape). Tests: bounds,
   determinism, island mask.
3. Implement Stage 2 (Voronoi plates). Tests: coverage,
   boundaries.
4. Implement Stage 3 (domain warping). Tests: coastline
   variation.

### Phase B: Terrain (Stages 4-5)

5. Implement Stage 4 (flow-accumulation erosion). Tests:
   elevation bounds, flow monotonicity, drainage basins.
6. Implement Stage 5 (biome assignment). Tests: essential
   biomes, mountain coherence, diversity.

### Phase C: Features (Stages 6-8)

7. Implement Stage 6 (rivers). Tests: forest crossing,
   drylands termination, lake creation, dense forest adjacency.
8. Implement Stage 7 (settlement scoring). Tests: scoring
   function, spacing, hub placement.
9. Implement Stage 8 (roads). Tests: dead-end towers,
   perpendicular crossing, cave bifurcation.

### Phase D: Polish (Stage 9)

10. Implement Stage 9 (edge-point registry). Tests: cross-hex
    consistency, offset determinism.
11. Wire up the pipeline runner and game dispatcher. Integration
    test: full world generation with the v2 pack.
12. Create `testland-v2` content pack. Playtest.

### Phase E: Transition

13. Switch default pack to `testland-v2`.
14. Mark BSP and Perlin generators as deprecated.
15. Remove deprecated generators after one release cycle.

---

## 15. Verification

**Note:** The `generate_hexmap.py` visual QA tool is a critical
part of verification. It must be updated at commit D3 to support
`--generator continental_v2`. Until then, use the web server for
visual inspection.

### 15.1 Automated Tests

Each stage has unit tests (see per-stage test sections above).
Integration test generates a full world and verifies:
- All cells have biomes, elevations, and tile slots.
- Rivers start at mountains and end at water/lakes/drylands.
- Roads connect all settlements (MST property).
- No visual breaks in edge segments (entry/exit consistency).
- Flower sub-hex counts are 19 per macro hex.
- Deterministic: same seed produces identical world.

### 15.2 Visual Inspection

Run the web server and inspect the generated map:

```bash
./server
# Navigate to hex map view
```

Check for:
- Organic coastlines (not circular blobs).
- Mountain ranges along plate boundaries (not scattered).
- Rivers following drainage basins (not arbitrary paths).
- Dense forest flanking rivers in forested areas.
- Settlements clustered near rivers and biome borders.
- Roads avoiding sandlands/deadlands.
- No broken river/road lines at hex boundaries.

### 15.3 Debug Tools

Use the MCP debug tools to inspect individual cells:

- `get_tile_info(q, r)` -- verify biome, elevation, edges.
- `get_tile_map` -- verify overall biome distribution.
- `get_room_info` -- verify flower sub-hex structure.

### 15.4 Comparison Render

Generate the same seed with both Perlin and V2 generators. Save
screenshots to `debug/` for side-by-side comparison of terrain
quality.
