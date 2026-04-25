# World Generation Expansion — Remaining Phases

Design notes for the **two unbuilt phases** of NHC's world
generation expansion: a multi-floor underworld system and a
faction-pattern hex placement (Caves of Chaos).

The earlier phases of this plan have all landed and now live
in dedicated docs:

| Phase                                   | Now lives in                            |
|-----------------------------------------|-----------------------------------------|
| 0a — BSP generator modularization       | `nhc/dungeon/generators/`               |
| 0b — SVG renderer modularization        | `nhc/rendering/`                        |
| 1 — `StructuralTemplate` foundation     | `nhc/dungeon/templates.py` + tests      |
| 2 — Structural variants (tower / mine)  | `nhc/sites/tower.py`, `nhc/sites/mage_residence.py` |
| 3 — Keep / walled layout                | `design/building_generator.md` (Phase 8 subsumed it)|
| 4 — Settlement generator                | `design/building_generator.md` + `nhc/sites/town.py`|
| 7 — SVG rendering extensions            | `nhc/rendering/_floor_detail.py` + theme palettes   |
| 8 — Building generator + site assemblers| `design/building_generator.md`, `design/sites.md`   |

This file used to carry all of those (~930 lines) — they have
been pruned because they are no longer aspirational. What
remains is the truly unbuilt material: phases 5 and 6.

## Principles

- **TDD discipline**: tests first for every functional change.
- **Commit per milestone**: each completed milestone gets its
  own commit with passing tests.
- **No save migration**: saved games may break freely during
  active development. No backward-compat shims.
- **One cache for sites; dungeons stay separate.** The site
  subsystem (`design/sites.md`) owns surface caching with
  `SiteCacheManager`. Underworld floors belong to the dungeon
  system and continue to use `_floor_cache` keyed off
  `_active_cave_cluster` (which Phase 5 generalises into
  `_active_underworld_region`).

---

## Phase 5. Mega-Dungeon / Underworld System

### Problem

Cave clusters today share a single Floor 2. Need multi-level
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

### Cave entry, post-M6c

Caves and holes route through `Game.enter_dungeon` (the
post-M6c rename of `enter_hex_feature` for the cave / hole
path). Phase 5 plugs the underworld pipeline into that path:
the existing cave Floor 1 generator stays the same, but
descents to Floor 2+ swap from the per-cluster Floor 2 builder
to the new `_generate_underworld_floor(depth)`. The site
subsystem is not affected — Phase 5 lives entirely in the
dungeon-system half.

### Files

| Action | Path                             |
|--------|----------------------------------|
| Create | `nhc/hexcrawl/underworld.py`     |
| Modify | `nhc/hexcrawl/model.py` (HexWorld) |
| Modify | `nhc/hexcrawl/_features.py`      |
| Modify | `nhc/core/game.py`               |
| Modify | `nhc/rendering/terrain_palette.py` |

---

## Phase 6. Caves of Chaos / Keep Pattern

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
- Caves interconnect at depth via cave cluster BFS (or, once
  Phase 5 lands, via the shared `UnderworldRegion`).

### Faction System

- `DungeonRef.faction` stores assigned faction string
- Populator checks `level.metadata.faction` for creature pool
- Shared deep floor places faction borders at chokepoints

### Keep as Safe Base

Routes through the unified site dispatcher
(`Game.enter_site(kind="keep", tier=MEDIUM, …)` per M6c).
Rooms tagged "safe" suppress hostile spawns. Player's home base.

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

## Implementation Phases

```
Phase 5: Underworld
  │
  └── Phase 6: Caves of Chaos
```

Phase 6 builds on Phase 5: the Caves of Chaos pattern wants its
satellite caves to interconnect at depth, which is exactly the
`UnderworldRegion` shared floor that Phase 5 introduces.

### Phase 5: Mega-Dungeon / Underworld

- `UnderworldRegion` dataclass
- Extend cave cluster assignment
- Generalize floor 2 to N floors
- Underground biome themes and palettes
- Lateral connections between sectors
- Tests: depth scales with cluster, cache keys resolve
- Commit per milestone

### Phase 6: Caves of Chaos Pattern

- `FeaturePattern` placement system
- Caves of Chaos definition
- Faction-per-cave wiring to populator
- Pack YAML schema for patterns
- Tests: pattern places keep + caves, distinct factions
- Commit per milestone

---

## Verification

After each phase:

1. Run `.venv/bin/pytest -n auto --dist worksteal -m "not slow"`
2. Start web server (`./server`), generate hex world,
   visually verify new dungeon types render correctly
3. Enter each new dungeon variant and confirm playability
4. Use MCP debug tools (`get_game_snapshot`, `get_room_info`)
   to inspect generated structure
