# Building Interiors — Design

Extends `design/building_generator.md`. That document covers today's
multi-floor building infrastructure (M1–M15): shared footprint,
perimeter walls, cross-floor stair alignment, SVG materials, entry
doors, service roles. This document adds the next layer — interior
partitioning, shared walls between adjacent buildings, and
archetype-driven layouts.

## Context

Every building floor today is a single open room with a perimeter
wall and a central stair. Walking into a tavern or a keep reads as
flat — there are no rooms, no interior doors, no corridors. The
downstream systems (pathfinding, FOV, movement, save/load, web SVG
rendering) are layout-agnostic, so the limiting factor is the
generator, not the engine.

This design lifts that limit: building floors become multi-room
interiors with doors and optional corridors, per-archetype layouts,
and adjacent buildings can share walls or doors when the site wants
a row-house terrace or a tavern-inn passage.

## Goals

- Multi-room interiors with interior doors and optional corridors.
- Per-archetype layouts (tavern/shop doorways; temple nave + chapels;
  keep/mansion central corridor; tower sectors around a central hub).
- **Interior walls are axis-aligned edges between tiles**, not
  WALL tiles. Rooms keep every tile they draw; walls live on the
  grid edges and render as thin lines. `Tile.terrain = WALL` is
  reserved for the site-level perimeter shell.
- Strict cross-floor stair alignment preserved — redefined as a
  per-link invariant.
- Shared walls and optional connecting doors between adjacent
  buildings.
- No change to the existing BSP dungeon generator; reuse its
  utilities via parameterization rather than forking them.

## Non-Goals

- Per-floor archetype semantics (tavern ground = common hall +
  kitchen; upper = bedrooms). Rooms get generic `interior_room`
  labels in this phase; semantic labels are a Phase 2 extension.
- Secret doors in interiors.
- Decorated / box-drawn interior walls — interior walls use a
  deliberately simpler visual (see Interior wall rendering).
- Terminal TUI work — web-only focus.
- Migration of existing saves. Old saves are discarded with this
  change. Going forward, building structure is deterministic from
  `(seed, hex, building_id)`; interior door open/closed state and
  NPC identities are not tracked across hex re-entries.

## Architecture

### Site-level shell composition

Perimeter wall stamping moves out of building generators and into a
site-level shell composer. Today each `_build_*_floor()` couples
interior layout (building-owned) with the boundary between a building
and its neighbors (site-owned). Separating them enables shared walls
between adjacent buildings, simpler partitioner math (full-rect
footprints are fully walkable), and a cleaner building contract
(interior only).

```python
# nhc/dungeon/sites/_shell.py
def compose_shell(
    level: Level,
    building_footprints: Mapping[str, Rect],
    entry_doors: Mapping[str, list[tuple[int, int, str]]],
    shared_doors: list[tuple[str, str, tuple[int, int]]] = (),
) -> None:
    """
    Stamp WALL at every tile adjacent to a building footprint.
    Building-A to building-B shared edges get a single WALL (not
    two). Entry doors stamp onto exterior-wall tiles per building.
    shared_doors replace one shared-edge tile with door_closed.
    """
```

Pipeline per floor:

1. Site assembler chooses footprints, archetypes, roles.
2. Each building floor carves its footprint as FLOOR and runs its
   partitioner; no perimeter stamping.
3. Site assembler calls `compose_shell()` for that floor level.
4. `place_cross_floor_stairs()` runs per-link after shell composition.

Shared walls & connecting doors are opt-in per site. The town
assembler enables them for specific role pairs (e.g. tavern↔inn,
residential↔residential row houses) via `SHARED_DOOR_PAIRS` in the
archetype config.

### Cross-building door links (all floors)

Buildings are not composed onto a shared Level — each floor of each
building is its own `Level`. A "shared wall" between adjacent
buildings is therefore not a real shared tile, but a pair of
mirrored perimeter tiles (one on each building's floor) that the
engine teleports between. This mirrors how surface entry doors work
today (see `Site.building_doors`) and how `StairLink` pairs a
tile on one floor with a tile on the next.

A new link primitive generalizes the existing mansion-only
`Site.interior_doors` from ground-floor to **any floor**:

```python
@dataclass
class InteriorDoorLink:
    from_building: str
    to_building:   str
    floor:         int                  # invariant: same on both sides
    from_tile:     tuple[int, int]      # on from_building.floors[floor]
    to_tile:       tuple[int, int]      # on to_building.floors[floor]
```

Invariants:

- `floor < min(len(A.floors), len(B.floors))`. A link exists only
  where both buildings reach that level. A 3-floor tavern adjacent
  to a 2-floor inn can link at floor 0 and floor 1; floor 2 of the
  tavern has no neighbor to link to.
- `from_tile` sits on `from_building`'s perimeter at a tile
  adjacent (across the shared edge) to `to_tile` on `to_building`'s
  perimeter. The shell composer stamps WALL at both sides; the
  feature on both tiles is set to `door_closed`, with `door_side`
  pointing across the shared edge.
- Stepping onto one tile teleports to the other (same mechanism
  as surface entry doors).

`Site.interior_doors` becomes a list of `InteriorDoorLink`. The
town assembler decides which role pairs get linked and on which
floors, analogous to how the tower assembler decides stair
placement. Typical patterns:

- tavern↔inn: link on ground floor (common passage) and floor 1
  (shared upstairs hallway).
- row-house residentials: one link per shared edge on ground
  floor only (neighbors typically don't share upstairs).
- mansion wings: ground-floor link (current behavior, preserved).

### Shape invariant

`Building.base_shape` is a single shape shared by every floor in the
building. The walkable set `shape.floor_tiles(rect)` is therefore
constant across floors. Callers that pass `required_walkable` tiles
(the per-link stair placer; any future caller) MUST pick tiles from
the shape-walkable set. Partitioners treat `required_walkable` as a
pre-validated hard constraint and assert if any tile lies outside
the shape's walkable set — that's a caller bug, not a runtime
recoverable condition.

### Interior wall primitive (edge walls)

Interior walls are **axis-aligned edges between tiles**, not WALL
tiles. An edge is a triple `(x, y, side)` with `side ∈ {"north",
"west"}`. Canonical form: the north edge of `(x, y)` is the same
physical wall as the south edge of `(x, y-1)`; the set stores the
`"north"` form only. Same for west / east. A small
`canonicalize(x, y, side)` helper normalizes every read and write
so the engine has one truth per edge.

```python
# nhc/dungeon/model.py
@dataclass
class Level:
    ...
    interior_edges: set[tuple[int, int, str]] = field(
        default_factory=set,
    )
```

Why edges and not tiles:

- A BSP split between two rooms used to eat a full row/column of
  WALL tiles. A 9×8 building became two 9×3 rooms with a 9-tile
  wall row in between. Edge walls give two 9×4 rooms with the
  wall on the boundary — both rooms keep every tile they draw.
- Renderers draw the wall directly from the data model — no
  "scan for contiguous WALL tiles, then draw a line" heuristic.
- `Tile.terrain = WALL` is reserved exclusively for the site
  perimeter shell. Nothing in the interior ever produces a WALL
  tile. One wall primitive per "owner" (shell vs partitioner),
  both consumed by the engine without ambiguity.

Interior walls are **always axis-aligned**, including inside
circle / octagon / L-shape footprints. A circle is split by a
single vertical edge at the centre, or by a `(+)` cross, or by an
off-centre split — the interior grammar is the same regardless of
the footprint shape. Edges are intersected with the footprint's
walkable set so they never dangle over VOID tiles.

### Doors and edge walls

Doors stay on tiles (no change to the action system). An edge in
`interior_edges` is **suppressed** when an adjacent tile has a
door feature (`door_closed`, `door_open`, `door_locked`) with
`door_side` pointing across that edge. The partitioner emits the
full edge run and the door tile; the engine treats the door as the
gap.

This keeps `OpenDoorAction`, `CloseDoorAction`, `PickLockAction`,
`ForceDoorAction`, `DoorOpened` / `DoorClosed`, `sync_linked_door_
state`, `tick_doors`, and save-load of doors exactly as they are.

### Partitioner API

Partitioners return a layout description. The site floor builder
stamps tiles. This keeps partitioners trivially testable with no
`Level` fixture and matches how `place_cross_floor_stairs()` already
composes with the generator.

```python
# nhc/dungeon/interior/protocol.py
@dataclass(frozen=True)
class PartitionerConfig:
    footprint: Rect
    shape: RoomShape                       # Rect / Circle / Octagon / L
    floor_index: int
    n_floors: int
    required_walkable: frozenset[tuple[int, int]] = frozenset()
    rng: random.Random
    archetype: str
    min_room: int = 3
    padding: int = 1

@dataclass
class InteriorDoor:
    x: int
    y: int
    side: str                              # "north"/"south"/"east"/"west"
    feature: str                           # "door_closed" | "door_locked"

@dataclass
class LayoutPlan:
    rooms: list[Room]
    interior_edges: set[tuple[int, int, str]]   # canonical, axis-aligned
    corridor_tiles: set[tuple[int, int]]
    doors: list[InteriorDoor]
    # Disjointness contract (checked in tests):
    #   every edge is in canonical form (side ∈ {"north","west"})
    #   every edge lies between two footprint-walkable tiles
    #   door_edges ⊆ interior_edges    # doors sit on an emitted
    #                                   # edge; engine suppresses them
    #   corridor_tiles ∩ cfg.required_walkable == ∅  # corridor tiles
    #                                                 # stay FLOOR
    #   {d.xy for d in doors} ∩ cfg.required_walkable == ∅
    # required_walkable tiles must land on FLOOR inside some room.

class Partitioner(Protocol):
    def plan(self, cfg: PartitionerConfig) -> LayoutPlan: ...
```

Footprints are the full building rect — all tiles walkable when the
partitioner runs. Interior walls are strictly inside the footprint;
the shell composer owns every footprint-edge tile.

Concrete partitioners:

| partitioner | use |
|---|---|
| `SingleRoomPartitioner` | ruin, small stable, fallback |
| `DividedPartitioner` | residential, cottage, small farm, square tower |
| `RectBSPPartitioner` (doorway mode) | tavern, shop, training |
| `RectBSPPartitioner` (corridor mode) | keep, mansion |
| `SectorPartitioner` (simple mode) | circle tower — axis splits (vertical / horizontal / cross) inside circle footprint |
| `SectorPartitioner` (enriched mode) | mage residence — axis split rotates per floor, stair picker favours diagonally opposite leaves to force "spiral" traversal |
| `TemplePartitioner` | temple nave + flanking chapels |
| `LShapePartitioner` | L-shape footprints — splits at inner corner, one junction door |

### Stair alignment invariant

Alignment is per-link, not per-building. A `StairLink` between floor
N and floor N+1 reserves a single `(x, y)` tile shared between both
floors. A middle floor in a 3+ floor building carries two stair
tiles — one per link — at potentially different coords.

Propagation is through `PartitionerConfig.required_walkable`:

1. Ground floor partitions freely.
2. `place_cross_floor_stairs()` picks a walkable tile for the link
   to floor 1 and records it as the link's shared tile.
3. Floor 1 partitions with `required_walkable = {shared_tile_01}`.
   The partitioner must leave that tile walkable (FLOOR, not a wall,
   not a door).
4. The same pattern repeats upward.

A **"spiral stairwell" pattern** emerges when the link picker
places consecutive floors' shared tiles in diagonally opposite
leaves of the partition — stair-up on one side, stair-down on the
other. With ≥ 2 rooms per floor and an interior door between
them, the player has to cross the floor to progress. Mage
residences lean into this to read as chaotic / labyrinthine.
Towers that pick the same coord for every link produce a
"central stairwell" instead; both are optional patterns, not
invariants.

### Interior wall rendering

Interior walls use a simple thick-line material, distinct from the
stylized perimeter rendering. Three categories:

| material | color | typical archetypes |
|---|---|---|
| wood | `#7a4e2c` | tavern, residential, stable, cottage, farm |
| stone | `#707070` | keep, mansion, temple, tower, mage residence |
| brick | `#c4651d` | shop, training, urban service buildings |

`Building.interior_wall_material` chooses per building. The SVG
renderer iterates `level.interior_edges` directly:

```python
for (x, y, side) in level.interior_edges:
    if edge_has_door(level, x, y, side):
        continue
    draw_line_on_edge(x, y, side, building.interior_wall_material)
```

Optional coalescing collapses colinear edges into one `<line>`
element for smaller SVGs — purely a rendering concern; the data
model stays per-edge. Perimeter walls use the separate tile-based
stylized pass stamped by `compose_shell()`. No heuristic scanning
of WALL tile runs.

Interior doors render via the existing door SVG, keyed by
`door_side`.

## Per-archetype strategy

| archetype | footprint | partitioner | notes |
|---|---|---|---|
| tavern / inn | 13–16 | RectBSP (doorway) | 3–5 rooms, no corridor |
| shop | 10–12 | RectBSP / Divided | backroom may be locked |
| temple | 14–16 | Temple | big nave + 2 chapels |
| training | 9–11 | RectBSP (doorway) | main hall + armory / instructor (2–3 rooms) |
| residential | 7–9 | Divided | 2 rooms, 1 door |
| stable | 5–7 | SingleRoom | stalls via content, not walls |
| cottage | 7–9 | Divided | 2 rooms |
| keep | existing large | RectBSP (corridor) | central corridor + rooms |
| mansion | existing large | RectBSP (corridor) | central corridor + rooms |
| tower (square) | 7–11 | Divided | 2 rooms per floor |
| tower (circle) | 7–11 | Sector (simple) | pie slices around a hub |
| mage residence | 9–13 | Sector (enriched) | octagon/exotic shapes, spiral via rotating main sector |
| ruin | existing | SingleRoom | rubble, no carving |
| farm main | 7–10 | Divided | 2 rooms |

## Declarative archetype config

Every per-archetype knob lives in a single dict in
`nhc/dungeon/interior/registry.py`. This is the tuning surface:
adjust values, rerun tests.

```python
ARCHETYPE_CONFIG: dict[str, ArchetypeSpec] = {
    "tavern":   ArchetypeSpec(
        size_range=(13, 16), shape_pool=("rect", "l"),
        partitioner="rect_bsp", bsp_mode="doorway",
        min_room=3, padding=1, interior_wall_material="wood",
    ),
    "shop":     ArchetypeSpec(
        size_range=(10, 12), shape_pool=("rect",),
        partitioner="rect_bsp", bsp_mode="doorway",
        min_room=3, padding=1, interior_wall_material="brick",
        locked_door_rate=0.08,
    ),
    "temple":   ArchetypeSpec(
        size_range=(14, 16), shape_pool=("rect",),
        partitioner="temple",
        interior_wall_material="stone",
    ),
    "training": ArchetypeSpec(
        size_range=(9, 11), shape_pool=("rect", "l"),
        partitioner="rect_bsp", bsp_mode="doorway",
        min_room=3, padding=1, interior_wall_material="brick",
    ),
    "residential": ArchetypeSpec(
        size_range=(7, 9), shape_pool=("rect", "l"),
        partitioner="divided", interior_wall_material="wood",
    ),
    "stable":   ArchetypeSpec(
        size_range=(5, 7), shape_pool=("rect",),
        partitioner="single_room", interior_wall_material="wood",
    ),
    "cottage":  ArchetypeSpec(
        size_range=(7, 9), shape_pool=("rect", "l"),
        partitioner="divided", interior_wall_material="wood",
    ),
    "keep":     ArchetypeSpec(
        partitioner="rect_bsp", bsp_mode="corridor",
        min_room=3, padding=1, corridor_width=2,
        interior_wall_material="stone",
    ),
    "mansion":  ArchetypeSpec(
        partitioner="rect_bsp", bsp_mode="corridor",
        min_room=3, padding=1, corridor_width=2,
        interior_wall_material="stone",
    ),
    "tower_square":  ArchetypeSpec(
        size_range=(7, 11), shape_pool=("rect",),
        partitioner="divided", interior_wall_material="stone",
    ),
    "tower_circle":  ArchetypeSpec(
        size_range=(7, 11), shape_pool=("circle",),
        partitioner="sector", sector_mode="simple",
        interior_wall_material="stone",
    ),
    "mage_residence": ArchetypeSpec(
        size_range=(9, 13), shape_pool=("octagon", "circle"),
        partitioner="sector", sector_mode="enriched",
        interior_wall_material="stone",
    ),
    "ruin":        ArchetypeSpec(
        partitioner="single_room", interior_wall_material="stone",
    ),
    "farm_main":   ArchetypeSpec(
        size_range=(7, 10), shape_pool=("rect", "l"),
        partitioner="divided", interior_wall_material="wood",
    ),
}

SHARED_DOOR_PAIRS: list[tuple[str, str]] = [
    ("tavern", "inn"),
    ("residential", "residential"),   # row-house terraces
]
```

Unset fields default sensibly (partitioner → `single_room`, material
→ `stone`, `corridor_width` → 1). Site assemblers read from this
dict; they do not hardcode archetype choices. The `corridor_width`
knob is honored by `RectBSPPartitioner` in corridor mode — 1-tile
default matches the dungeon style; mansion and keep default to 2
for a grand-hall feel, tunable post-ship without code changes.

**Miss behavior**: an archetype string that isn't a key in
`ARCHETYPE_CONFIG` raises `KeyError` immediately. No silent
fallback. Tests assert that every archetype name referenced by any
site assembler resolves in the config. Silent defaulting would hide
typos and half-wired roles; this codebase favors loud failure over
graceful degradation until modding is an explicit goal.

## Sizing principles

- Tiered by role. Small residential / stable stay small; service
  buildings (tavern, shop, temple) grow; mansion / keep already
  large. Tower footprints unchanged.
- Town density reduced to fit larger service buildings. Rough
  targets:

  | size | buildings | surface (w×h) |
  |---|---|---|
  | hamlet | 3–4 | 36×26 |
  | village | 5–7 | 58×34 |
  | town | 8–10 | 72×42 |
  | city | 10–13 | 84×50 |

- Site assemblers switch from two fixed rows to a greedy pack using
  per-building width + spacing while preserving gate-y / main-street
  anchors.

## Door rules (interior)

- Default: `door_closed`.
- Locked: capped at one per building, only for the `shop` role, only
  on the door separating the smallest BSP leaf. Rate configured per
  archetype in `ARCHETYPE_CONFIG`.
- No secret doors.
- Interior doors never sit at footprint-edge tiles. Entry doors
  (exterior) and connecting doors (shared-wall) are stamped by
  `compose_shell()` after partitioning.
- `door_side` filled by `_compute_door_sides()` post-pass (reused
  from the BSP dungeon generator).
- Connectivity invariant: every adjacent room pair has ≥ 1 door
  between them.

### Auto-close rule (shared with dungeons)

Interior doors and cross-building link doors participate in the
existing global auto-close tick. `tick_doors()` in
`nhc/core/game_ticks.py` runs every turn, iterates `game.level`,
and closes any `door_open` tile that has been open for ≥
`DOOR_CLOSE_TURNS` (= 20) turns and is unoccupied. No new
mechanism is introduced — interior doors inherit the rule for free
as long as they use the standard `door_closed` / `door_open`
features and the open action sets `Tile.opened_at_turn`.

`InteriorDoorLink` doors require **symmetric state** across the
pair. The open action, the close action, and the auto-close tick
must all propagate to the mirrored tile on the other building's
floor Level. When a player opens the tavern side of a
tavern↔inn link, the inn-side tile also flips to `door_open` with
the same `opened_at_turn`; when 20 turns pass (and both tiles are
unoccupied), both close in the same tick. Without this, sides
drift — one open, one closed — which breaks both visual
consistency and pathfinding symmetry.

## Reuse vs. duplication

- `_bsp_tree.py` (dungeon generator) — extract the recursive split
  into a function parameterized by `min_leaf / min_room / padding`;
  keep the module-level defaults so dungeon callers are unaffected.
  Building partitioners pass tighter values (`5 / 3 / 1`).
- `_corridors._carve_line` — reuse unchanged for corridor mode.
- `_doors._compute_door_sides()` — reuse as a post-pass after
  stamping to tag `door_side` on every interior door.
- `_walls._build_walls` — not needed; partitioner emits interior
  edges directly and the shell composer handles the perimeter.

## FOV and movement with edge walls

Both subsystems gain one per-step check that consults
`level.interior_edges` and the door-suppression rule. Closed
doors continue to block via the tile-feature check; they're
independent of the edge primitive.

```python
def edge_blocks_sight(level, from_xy, to_xy) -> bool:
    edge = edge_between(from_xy, to_xy)
    if edge not in level.interior_edges:
        return False
    return not edge_has_open_door(level, edge)

def edge_blocks_movement(level, from_xy, to_xy) -> bool:
    # Symmetric to edge_blocks_sight; closed doors still block
    # via the tile-feature path, not via this check.
    ...
```

FOV's raycast adds one call per step; A* adds one call per
neighbour expansion. Both are O(1) set lookups after
canonicalization.

## Risks and tradeoffs

- **L-shape partitioning**: splitting at the inner corner is a
  bespoke geometry. Each arm runs its own sub-partitioner; a
  junction door at the inner corner ensures connectivity.
- **Partitioner obligation to honor `required_walkable`**: tiles
  passed in must land on FLOOR inside a room, never under an
  interior wall or door. Tests enforce this on every partitioner.
- **Town resize disrupts seeded golden-file tests**: door / NPC
  coordinates shift under the new layout. A dedicated fixture
  refresh is required after the resize milestone.
- **Declarative grammar alternative**: a single partitioner driven
  by a per-archetype declarative adjacency spec is more flexible
  long-term. The concrete-class approach here lands faster and can
  be swapped later without touching site code — everything goes
  through the `Partitioner` protocol.

## Open questions for future phases

- Per-floor semantic labels (Phase 2): tavern ground = `"common"`,
  `"kitchen"`, `"bar"`; upper = `"bedroom"`.
- Furniture and content placement tied to semantic labels (barkeep
  behind the bar, merchant behind the shop counter).
- Secret doors and adventure hooks.
- Tapered towers (upper floors smaller than ground).
