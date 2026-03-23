# Dungeon Generator Improvement Plan

Inspired by Pixel Dungeon's generation system and adapted for NHC's
Knave ruleset, TTRPG narrative, and multilingual architecture.

---

## 1. Current State

The `ClassicGenerator` produces valid but basic dungeons:
- Random room placement with non-overlapping padding
- Sequential L-shaped corridors (room N → room N+1)
- Single up/down stairs in first/last rooms
- Automatic doors at corridor-room junctions
- Difficulty-tiered creature/item pools (4 tiers)

**Missing**: BSP subdivision, extra loops, special rooms, water/lava
generation, trap variety, encounter groups, boss rooms, difficulty
scaling, secret doors, dead-end handling.

---

## 2. Target Architecture

```
GenerationParams
       │
       ▼
┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│  1. LAYOUT   │───▶│  2. CONNECT    │───▶│  3. SPECIALIZE│
│  BSP rooms   │    │  Paths, loops  │    │  Room types   │
└──────────────┘    └────────────────┘    └──────────────┘
       │                                         │
       ▼                                         ▼
┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│  4. PAINT    │───▶│  5. TERRAIN    │───▶│  6. POPULATE  │
│  Room interiors│   │  Water, grass  │    │  Creatures,   │
│  Doors, traps │   │  Cellular auto │    │  items, loot  │
└──────────────┘    └────────────────┘    └──────────────┘
```

---

## 3. Phase 1 — BSP Room Layout

Replace random placement with recursive Binary Space Partitioning,
adapted from Pixel Dungeon's `split()` algorithm.

### Algorithm

```
split(rect, depth):
    if rect too small → create room (with margin)
    if probability check (minSize² / area) → create room
    else:
        choose split axis (horizontal if wide, vertical if tall)
        split at random point within inner 40-60%
        recurse both halves
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_room` | 5 | Minimum room dimension |
| `max_room` | 11 | Maximum room dimension |
| `padding` | 1 | Gap between rooms |
| `map_width` | 60 | Level width |
| `map_height` | 30 | Level height |

### Output
- List of `Room` objects with `Rect` bounds
- Minimum 6 rooms per level

### Files
- Implement in `nhc/dungeon/generators/bsp.py` (currently stub)
- Replaces `classic.py` random placement

---

## 4. Phase 2 — Room Connectivity

Currently rooms connect linearly (1→2→3→...). Pixel Dungeon builds
a **main path** plus **alternate paths** plus **random extra loops**.

### Algorithm

1. **Neighbor detection**: Two rooms are neighbors if their rects
   share a wall ≥3 tiles long (including 1-tile gap).

2. **Main path**: Shortest path from entrance to exit room using
   graph distance (BFS). This guarantees the level is solvable.

3. **Alternate path**: Second shortest path that diverges from main.
   Increases exploration surface and provides tactical options.

4. **Extra connections**: For `connectivity` fraction (default 0.6)
   of remaining unconnected neighbor pairs, add a corridor. Creates
   loops that make the dungeon feel less linear.

5. **Corridor carving**: For each connection, carve a corridor:
   - **Straight**: If rooms share an axis-aligned wall, single
     straight segment.
   - **L-shaped**: One horizontal + one vertical segment with
     random bend point.
   - **S-shaped** (organic): Two bends for longer distances.

### Door Placement

| Door type | Condition |
|-----------|-----------|
| Regular | Default at room-corridor junctions |
| Locked | On rooms tagged `vault`, `armory` |
| Hidden (secret) | `secret_doors` probability on dead-end rooms |
| Barricade | Random on non-critical path connections |

### Files
- `nhc/dungeon/connectivity.py` — neighbor detection, path building
- Updates to `nhc/dungeon/classic.py` or new `bsp.py`

---

## 5. Phase 3 — Room Specialization

Assign purpose to rooms based on position and connection count,
inspired by Pixel Dungeon's `assignRoomType()`.

### Room Types

| Type | Tags | Conditions | Contents |
|------|------|-----------|----------|
| **entrance** | `[entry, safe]` | First room, stairs up | Sign, starting items |
| **exit** | `[exit]` | Last room, stairs down | Stairs down |
| **standard** | `[combat]` | 2+ connections | Random creatures/items |
| **corridor** | — | 1 connection, narrow | Empty passage |
| **treasury** | `[treasure]` | Dead-end, locked door | Gold heaps, mimic chance |
| **armory** | `[treasure]` | Dead-end, locked door | Weapons, armor, shield |
| **library** | `[treasure]` | Dead-end | Scrolls (2-4) |
| **shrine** | `[water, puzzle]` | Any | Healing pool or buff well |
| **garden** | `[nature]` | Any | High grass, seeds, herbs |
| **trap_room** | `[danger]` | Dead-end | Dense traps + prize |
| **boss_lair** | `[boss, combat]` | Depth 5/10/15 | Boss creature, exit |
| **pool** | `[water, danger]` | Any | Water-filled, creatures |
| **crypt** | `[undead]` | Dead-end | Undead guardians, loot |
| **shop** | `[safe, shop]` | Depth 3/7/12 | Merchant NPC |

### Assignment Algorithm

1. Entrance and exit assigned first.
2. Dead-end rooms (1 connection) → 60% chance of special type.
3. Special type chosen by weighted random from available pool,
   influenced by depth and theme.
4. Remaining rooms → 50% standard, 50% corridor.
5. Minimum 3 standard rooms enforced.

### Room Painters

Each room type has a `paint()` function that fills interior tiles:

```python
# nhc/dungeon/painters/treasury.py
def paint_treasury(level, room, rng):
    """Fill treasury room with gold and optional mimic."""
    fill_floor(level, room)
    center = room.rect.center
    place_entity(level, "gold", center, dice="4d6")
    if rng.random() < 0.15:
        place_entity(level, "mimic", center)
```

### Files
- `nhc/dungeon/room_types.py` — type assignment logic
- `nhc/dungeon/painters/` — one file per room type
- `nhc/dungeon/painters/__init__.py` — painter registry

---

## 6. Phase 4 — Terrain Generation (Cellular Automata)

From Pixel Dungeon's `Patch.java` — use cellular automata to
generate organic water and vegetation patches.

### Algorithm

```
1. Seed grid: each cell ON with probability P
2. Repeat N iterations:
   - Cell ON if: (was OFF and ≥5 neighbors ON) or
                 (was ON and ≥4 neighbors ON)
3. Apply to level: ON cells become water/grass
```

### Parameters by Theme

| Theme | Water seed | Water iters | Grass seed | Grass iters |
|-------|-----------|------------|-----------|------------|
| crypt | 0.35 | 4 | 0.20 | 3 |
| cave | 0.45 | 6 | 0.35 | 3 |
| sewer | 0.50 | 5 | 0.40 | 4 |
| castle | 0.25 | 3 | 0.15 | 2 |
| forest | 0.30 | 4 | 0.55 | 5 |

### Constraints
- Water only on floor tiles (not corridors, walls, stairs)
- Water doesn't block main path (pathfind check after placement)
- Grass is cosmetic (maybe concealment bonus later)

### Level Feelings (10% chance per floor)

| Feeling | Effect |
|---------|--------|
| FLOODED | +50% water seed |
| OVERGROWN | +50% grass seed |
| BARREN | No water or grass |
| CHASM | Replace some floor with chasms |

### Files
- `nhc/dungeon/terrain.py` — cellular automata + feeling system
- `nhc/dungeon/generators/cellular.py` — terrain-only generator

---

## 7. Phase 5 — Enhanced Populator

Upgrade creature/item placement from individual random spawns to
designed encounters.

### Encounter Groups

Instead of placing lone creatures, place **encounter groups**:

| Group type | Size | Example |
|-----------|------|---------|
| Solo | 1 | Troll, Ogre |
| Pair | 2 | 2 Skeletons |
| Pack | 3-4 | Wolf pack, Goblin patrol |
| Swarm | 5-8 | Rat swarm, Insect swarm |
| Guard + minions | 1+2 | Hobgoblin + 2 Goblins |
| Ambush | 2-3 | Mimics + hidden creatures |

### Creature Placement Rules
- **Standard rooms**: 0-2 encounters based on difficulty
- **Boss lairs**: 1 boss + minions
- **Crypt rooms**: Undead only
- **Pool rooms**: Aquatic creatures
- **Treasure rooms**: Guardian creature
- **Corridors**: Patrol creatures (30% chance)
- Factions: rooms inherit level faction, creatures match

### Trap Variety

| Trap | Damage/Effect | DC |
|------|--------------|-----|
| Pit | 1d6 fall | 12 |
| Dart | 1d4 + poison | 13 |
| Fire | 2d4 burn | 14 |
| Alarm | Alert creatures in 20 tiles | 10 |
| Teleport | Random relocation | 15 |
| Web | Webbed 3 turns | 11 |
| Gas | Poison cloud 2 turns | 13 |

New trap entities needed in `nhc/entities/features/`.

### Loot Containers

| Container | Contents | Interaction |
|-----------|----------|-------------|
| Chest | Random item | Open (no key) |
| Locked chest | Better item | Requires key or lockpick |
| Barrel | Potion or gold | Break open |
| Bookshelf | Scroll | Search action |
| Weapon rack | Weapon | Take |

### Item Budget per Floor

| Depth | Items | Potions | Scrolls | Gold piles | Traps |
|-------|-------|---------|---------|------------|-------|
| 1 | 3-4 | 1-2 | 1 | 2-3 | 0-1 |
| 2-3 | 4-5 | 1-2 | 1-2 | 3-4 | 1-2 |
| 4-5 | 5-6 | 2-3 | 2-3 | 3-5 | 2-3 |
| 6+ | 6-8 | 2-3 | 2-3 | 4-6 | 3-5 |

### Files
- `nhc/dungeon/encounters.py` — encounter group definitions
- `nhc/dungeon/populator.py` — enhanced placement logic
- `nhc/entities/features/trap_*.py` — new trap types

---

## 8. Phase 6 — Multi-Floor Progression

Currently descending generates a fresh level with no memory.
Add floor persistence and progression.

### Depth Themes

| Depth | Theme | Creature focus | Ambient |
|-------|-------|---------------|---------|
| 1-3 | Crypt | Undead, vermin | Damp stone, decay |
| 4-6 | Cave | Beasts, oozes, fungi | Dripping water, echoes |
| 7-9 | Prison | Humanoids, constructs | Iron, torchlight |
| 10-12 | Castle | Elite humanoids, mages | Grandeur, dust |
| 13-15 | Abyss | Demons, chaos | Heat, red glow |

### Boss Floors (every 5th depth)
- Depth 5: **Mummy Lord** (undead boss)
- Depth 10: **Troll King** (regeneration, fire weakness)
- Depth 15: Final boss (TBD based on BEB)

### Floor Memory
- When ascending, restore previous floor state
- When descending to new floor, generate fresh
- Store up to 3 floors in memory (LRU)

### Files
- `nhc/dungeon/progression.py` — theme/boss selection
- `nhc/core/game.py` — floor stack management

---

## 9. Implementation Order

### Sprint 1 — BSP Layout + Connectivity (foundation)
1. Implement BSP room generation in `generators/bsp.py`
2. Implement neighbor detection and graph pathfinding
3. Build main path + extra connections
4. L-shaped and straight corridor carving
5. Door placement with type selection
6. Tests for layout validity

### Sprint 2 — Room Specialization + Painters
7. Room type assignment algorithm
8. Painters for: standard, treasury, armory, library, crypt
9. Shrine and garden painters
10. Trap room painter
11. Shop room with merchant NPC
12. Tests for room type distribution

### Sprint 3 — Terrain + Traps
13. Cellular automata for water/grass
14. Level feelings system
15. New trap types (dart, fire, alarm, web, gas, teleport)
16. Trap entity factories + i18n
17. Tests for terrain generation

### Sprint 4 — Enhanced Populator
18. Encounter group system
19. Faction-based creature placement
20. Loot container entities (chest, barrel, bookshelf)
21. Item budget per floor
22. Tests for encounter balance

### Sprint 5 — Multi-Floor + Bosses
23. Depth theme progression
24. Boss floor generation
25. Floor memory (ascending restores state)
26. Boss creature factories
27. Victory condition on final floor
28. Tests for floor transitions

---

## 10. Key Design Decisions

**BSP vs random placement**: BSP guarantees better space utilization
and more natural room distributions. Random placement wastes ~60% of
the map.

**Graph connectivity**: Building main + alternate paths ensures the
level is always solvable while creating exploration incentive. Extra
loops prevent the "long corridor back" problem.

**Cellular automata**: Cheaply generates organic water/grass patterns
that make levels feel alive. 5-6 iterations is the sweet spot.

**Encounter groups**: Solo creatures feel artificial. Groups of 2-4
with complementary abilities create tactical decisions.

**Room specialization**: Dead-end rooms as special rooms is elegant
— the player is rewarded for exploring off the main path with
unique loot/content, but must deal with the dead-end risk.

**Theme progression**: Changing creature types and room decorations
every 3-5 floors keeps the game fresh. Pixel Dungeon changes every
5 floors; we do every 3 for a shorter game.
