# BSP Dungeon Generator

Design document for NHC's procedural dungeon generation system.
Covers the full pipeline from BSP subdivision through entity
population.

---

## 1. Generation Pipeline Overview

Each dungeon level is produced by the following stages, executed
in order:

 1. **BSP subdivision** -- recursive binary partitioning of the
    map area, then room placement within each leaf.
 2. **Room carving** -- floor tiles laid down according to each
    room's shape (rect, circle, octagon, cross, or hybrid).
 3. **Wall building** -- 8-neighbor WALL border around all room
    floor tiles. Corridors get VOID sides, not walls.
 4. **Connectivity** -- main path via BFS from entrance to
    farthest room, extra loop corridors, and a reachability
    guarantee that reconnects any isolated rooms.
 5. **Corridor carving** -- L-shaped two-segment corridors
    through VOID. Force-carve mode punches through walls when
    reconnecting disconnected rooms.
 6. **Dead-end handling** -- iterative pruning of corridor stubs,
    secret door placement on remaining dead ends, and orphaned
    door removal.
 7. **Stairs placement** -- stairs_up in a random entry room,
    stairs_down at distance, optional second stairs_down.
 8. **Door cleanup** -- door side computation (cardinal direction
    toward adjacent room), door harmonization (adjacent doors
    unified to same type), and removal of doors on non-straight
    wall sections (arcs, diagonals).
 9. **Room type assignment + painting** -- special room types
    assigned based on connectivity, then painted with thematic
    entities (`room_types.py`).
10. **Terrain generation** -- cellular automata water patches
    applied to room floors (`terrain.py`).
11. **Entity population** -- creatures, items, traps, gold, and
    chests placed using difficulty-tiered pools and encounter
    groups (`populator.py`).

Steps 1-8 are handled by `BSPGenerator.generate()` in
`nhc/dungeon/generators/bsp.py`. Steps 9-11 are called by the
game loop after the generator returns.

---

## 2. BSP Algorithm

The map area (excluding a 1-tile border) is recursively split
into rectangular leaves via binary space partitioning.

### Constants

| Constant   | Value | Purpose                             |
|------------|-------|-------------------------------------|
| `MIN_LEAF` | 9     | Minimum leaf dimension              |
| `MAX_ROOM` | 10    | Maximum room dimension              |
| `MIN_ROOM` | 4     | Minimum room dimension              |
| `PADDING`  | 2     | Margin between room edge and leaf   |

### Splitting Rules

- A leaf is split if at least one dimension is >= `MIN_LEAF * 2`.
- **Axis selection**: split along the longer dimension when the
  aspect ratio exceeds 1.25; random choice if nearly square.
- **Split point**: random integer between `MIN_LEAF` and
  `dimension - MIN_LEAF`, ensuring both children are large
  enough.
- Recursion continues until no leaf can be split further.

### Room Placement

Each leaf gets one room:
- Width: random in `[MIN_ROOM, min(MAX_ROOM, leaf_w - 2*PADDING)]`
- Height: random in `[MIN_ROOM, min(MAX_ROOM, leaf_h - 2*PADDING)]`
- Position: random within the leaf, respecting `PADDING` margin
  on all sides.

The padding ensures a VOID gap between adjacent rooms' walls,
preventing rooms from visually merging.

If the BSP produces fewer than 3 rooms, the generator falls back
to `ClassicGenerator` as a safety net.

---

## 3. Room Shapes

Five shape types control which tiles become floor within a room's
bounding rectangle.

### RectShape

All tiles in the bounding rectangle. The default shape.

### CircleShape

A true circle inscribed in the bounding rect.
- Diameter = `min(width, height)`, forced to odd for clean
  cardinal wall positions.
- Only tiles within the circle radius become floor.
- Four cardinal wall positions (N, S, E, W) are computed for
  door placement.

### OctagonShape

A rectangle with 45-degree clipped corners.
- Clip size = `max(1, min(width, height) // 3)`.
- Each corner has a triangular region excluded from floor.

### CrossShape

Two overlapping bars (horizontal + vertical).
- Bar width approximately 1/3 of each dimension, minimum 2 tiles.
- Creates a plus-sign shaped room.

### HybridShape

Two sub-shapes joined at a vertical or horizontal split line.
- One tile of overlap at the seam ensures connectivity.
- 16 hybrid presets exist (e.g., circle+rect, octagon+rect).
- In practice, the generator creates circle+rect hybrids: the
  circle half occupies the shorter axis, the rect half the rest.

### Shape Selection

Controlled by the `shape_variety` parameter (0.0 to 1.0):
- At `shape_variety = 0.0`, all rooms are rectangular.
- Higher values increase the probability of non-rect shapes.
- Rooms with `min(width, height) < 5` always get RectShape.
- 20% chance of hybrid when `max_dim >= 7`.
- Remaining candidates: OctagonShape, CrossShape, and
  CircleShape (only for near-square rooms with odd dimensions).

---

## 4. Connectivity

### Neighbor Detection

Room pairs are considered potential neighbors when the Manhattan
distance between their centers is <= 25.

### Main Path

1. BFS from the entrance room (index 0) computes distances to
   all other rooms in the neighbor graph.
2. The farthest room becomes the exit.
3. BFS finds the shortest path from entrance to exit.
4. All edges on this path are carved as corridors.

### Extra Loops

Each unused neighbor pair has a `50% * connectivity` chance of
being connected (default connectivity = 0.8, so 40% per pair).
This creates alternate routes and loops in the dungeon.

### Reachability Guarantee (Graph Level)

After carving the main path and extra loops:
1. BFS from entrance identifies all reachable rooms.
2. Any unreachable room is force-connected to the nearest
   reachable room (by center Manhattan distance).
3. The adjacency graph is updated and the check repeats until
   all rooms are reachable.

### Reachability Guarantee (Tile Level)

After dead-end pruning, a second verification runs at the tile
level:
1. Flood-fill from the entrance room's center across FLOOR tiles.
2. Any room whose center is not in the reachable set gets a
   force-carved corridor to the nearest reachable room.
3. Repeats until all rooms are tile-reachable.

---

## 5. Corridors

### L-Shaped Carving

Each corridor consists of two perpendicular line segments:
1. Find a wall tile on each room facing the other room.
2. Convert wall tiles to doors.
3. Step one tile outward into VOID (the corridor start/end).
4. Carve an L-shaped path: randomly choose horizontal-first or
   vertical-first orientation.

### Wall Entry Finding

For each room, the generator scans the perimeter walls and
selects the tile with the best facing score (dot product of
wall direction and target direction), avoiding tiles adjacent
to existing doors. Circular rooms restrict entry to 4 cardinal
wall positions.

### Normal vs Force Carving

- **Normal**: only replaces VOID tiles with FLOOR (corridor).
  Used for the main path and extra loops.
- **Force**: also replaces WALL tiles with FLOOR + `door_closed`.
  Used during tile-level reconnection to guarantee connectivity.

---

## 6. Door System

### Door Types

| Type          | Base Probability                     |
|---------------|--------------------------------------|
| `door_closed` | Remainder after secret and locked    |
| `door_secret` | 10%                                  |
| `door_locked` | 5% + depth * 2% (7% at D1, 15% D5)  |

### Door Harmonization

Adjacent doors (cardinal neighbors) are unified to the same type.
This runs twice: once during initial corridor carving and once
after tile-level reconnection.

### Door Side Assignment

Each door gets a `door_side` (north, south, east, west) based on
the direction of the adjacent room floor tile. The renderer uses
this to orient the door glyph correctly.

### Non-Straight Door Removal

Doors placed on curved wall sections (octagon diagonals, cross
indentations, circle arcs) are converted to plain corridor floor.
A door is considered "straight" only when the room outline runs
parallel to the bounding rect boundary at the door position and
at least 3 floor tiles span the wall direction -- indicating a
flat side, not a corner or curve.

---

## 7. Dead-End Handling

### Phase 1: Iterative Pruning

Corridor tiles with <= 1 floor cardinal neighbor are removed
(set to VOID), iterating until no more dead ends exist. Tiles
adjacent to doors are never pruned.

### Phase 2: Selective Treatment

Remaining dead-end corridor tiles are handled individually:
- **30%**: place a secret door on an adjacent wall tile.
- **30%**: keep as atmospheric dead end.
- **40%**: prune (set to VOID), then re-scan for new dead ends.

### Orphaned Door Removal

After all pruning, doors that have a room side but no corridor
side are reverted to WALL. This cleans up doors whose corridors
were pruned away.

---

## 8. Stairs

- **Entry room**: chosen randomly from all rooms. Gets
  `stairs_up` at its center.
- **Exit room**: chosen from rooms at >= 50% of the maximum BFS
  distance from the entry room. Gets `stairs_down` at center.
- **Second stairs_down**: 15% chance, placed in another room
  that also meets the distance threshold.

Entry and exit rooms are tagged accordingly for room type
assignment (both always become "standard").

---

## 9. Room Types

Defined in `nhc/dungeon/room_types.py`.

### Assignment Rules

- Entry and exit rooms are always "standard".
- Dead-end rooms (1 connection): 70% chance of special type
  (decreasing by 15% per special already placed), max 3.
- Any room: 15% chance of general special type, max 4 total.
- Rooms with >= 2 connections or 60% random chance: "standard".
- Remaining rooms: "corridor" (pass-through).
- Minimum 3 standard rooms enforced (corridor rooms promoted).

### Special Room Types

| Type       | Category | Contents                           |
|------------|----------|------------------------------------|
| treasury   | special  | 2-4 gold, 1-2 chests, 20% mimic   |
| armory     | special  | 2-3 weapons, 50% shield            |
| library    | special  | 2-4 scrolls                        |
| crypt      | special  | 1-2 undead, gold                   |
| trap_room  | special  | 2-4 pit traps + 1 prize item       |
| shrine     | general  | Water patch + healing potion        |
| garden     | general  | Healing potion                     |

Special types (treasury, armory, library, crypt, trap_room)
prefer dead-end rooms. General types (shrine, garden) can go
in any room.

Each type has a `paint()` function that places `EntityPlacement`
entries in the room's interior tiles.

---

## 10. Terrain

Defined in `nhc/dungeon/terrain.py`. Uses cellular automata
adapted from Pixel Dungeon's Patch algorithm.

### Algorithm

1. Seed a boolean grid with random values at `seed_probability`.
2. Run N iterations of cellular automata:
   - OFF cell turns ON if >= 5 cardinal+diagonal neighbors are ON.
   - ON cell stays ON if >= 4 neighbors are ON.
3. Apply the resulting mask: water tiles on matching floor tiles.

### Theme Parameters

| Theme   | Water Seed | Water Iters | Grass Seed | Grass Iters |
|---------|------------|-------------|------------|-------------|
| crypt   | 0.35       | 4           | 0.20       | 3           |
| cave    | 0.45       | 6           | 0.35       | 3           |
| sewer   | 0.50       | 5           | 0.40       | 4           |
| castle  | 0.25       | 3           | 0.15       | 2           |
| forest  | 0.30       | 4           | 0.55       | 5           |
| dungeon | 0.35       | 4           | 0.25       | 3           |

### Level Feelings

10% chance on depth > 1. Modifies terrain generation:
- **flooded**: +15% water seed probability.
- **barren**: no terrain features at all.
- **overgrown**: (reserved, currently same as normal).
- **normal**: default parameters.

### Placement Rules

Water tiles are only placed on FLOOR tiles that are not
corridors, stairs, doors, or traps.

---

## 11. Populator

Defined in `nhc/dungeon/populator.py`. Places creatures, items,
traps, gold, and chests in rooms.

### Difficulty Tiers

Tier = `clamp(depth, 1, 4)`. Each tier defines weighted pools
of creature types (9-17 per tier) and item types (17-32 per tier).

### Entity Count Scaling

| Entity    | Formula                                      |
|-----------|----------------------------------------------|
| Creatures | `2 + depth + randint(0, 2)`                  |
| Items     | `3 + randint(0, depth)`                      |
| Traps     | `max(0, depth - 1) + randint(0, 1)`         |
| Gold      | `randint(2, 3 + depth)`                      |
| Chests    | `randint(0, 1 + depth // 2)`                |

### Encounter Groups

Creatures are placed in encounter groups for tactical variety:

| Pattern | Size  |
|---------|-------|
| solo    | 1     |
| pair    | 2     |
| pack    | 3-4   |

Each group uses a single creature type, selected by weighted
random from the tier's pool. Groups are placed in non-special
combat rooms, avoiding the entry room.

### Trap Placement

All traps are placed hidden. Trap type is selected uniformly
from 12 trap types (pit, fire, poison, paralysis, alarm,
teleport, summoning, gripping, arrow, darts, falling stone,
spores).

### Single-Tile Corridor Population

Corridor segments exactly 1 tile long get special treatment:
- **50%**: nothing.
- **30%**: one creature from the tier pool.
- **20%**: one item from the tier pool.

---

## 12. Generation Parameters

Defined in `GenerationParams` (`nhc/dungeon/generator.py`):

| Parameter       | Default | Description                       |
|-----------------|---------|-----------------------------------|
| `width`         | 120     | Map width in tiles                |
| `height`        | 40      | Map height in tiles               |
| `depth`         | 1       | Dungeon floor number              |
| `connectivity`  | 0.8     | Extra corridor probability factor |
| `theme`         | dungeon | Terrain theme (6 options)         |
| `seed`          | None    | RNG seed for reproducibility      |
| `shape_variety` | 0.0     | Non-rect room probability (0-1)  |
| `secret_doors`  | 0.1     | Base secret door probability      |
| `room_count`    | 5-15    | Target room count range           |
| `room_size`     | 4-12    | Target room size range            |

The `shape_variety` parameter typically scales with depth in the
game loop, producing more complex room shapes on deeper floors.

---

## Source Files

| File                              | Role                          |
|-----------------------------------|-------------------------------|
| `nhc/dungeon/generators/bsp.py`  | BSP subdivision + generation  |
| `nhc/dungeon/generator.py`       | Abstract interface + params   |
| `nhc/dungeon/model.py`           | Level, Room, Tile, shapes     |
| `nhc/dungeon/room_types.py`      | Room type assignment + paint  |
| `nhc/dungeon/terrain.py`         | Cellular automata terrain     |
| `nhc/dungeon/populator.py`       | Entity population             |
