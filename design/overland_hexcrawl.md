# NHC -- Overland Hexcrawl Mode: Design Document

Design document for adding a generic **overland hexcrawl mode** that
wraps the existing dungeon crawler. Players roam a hex map and enter
dungeons, caves, ruins, or settlements when they wish to explore a
hex feature, then return to the overland.

This document is a discussion reference for the engine and the first
content pack (a small procedurally generated test setting). Blackmarsh
ingestion lands in a later phase once the engine is proven.

---

## 1. Vision & Scope

NHC today is a single multi-floor dungeon crawler. Hex mode adds an
**expedition layer** on top: the player has a home base, plans
expeditions, travels overland, fights through dungeons, returns to
trade and rest, then heads out again.

What hex mode adds:

- An overland view with terrain-keyed hex tiles
- Per-hex stepping with a day clock and four time-of-day segments
- Roguelike fog of war, revealed hex by hex
- A rumor system (some true, some false) gathered at settlements
- A larger expedition party that selects down to the dungeon party
- A persistent world that remembers cleared dungeons and dead NPCs
  across sessions
- A death dialog with a "cheat death" option (in Easy difficulty)

What hex mode does **not** change:

- The dungeon crawler stays exactly as-is. Hex mode wraps it; both
  modes coexist.
- The action pipeline, ECS, save format extension (not rewrite),
  combat rules, and identification system are reused unchanged.

Non-goals for v1:

- Factions and reputation (deferred; lands with Blackmarsh)
- Weather and seasons (deferred)
- Supplies / rations / hunger (deferred)
- Mounts as a gameplay effect (component stub only)
- Typed (LLM) overland intent parsing (deferred; existing dungeon
  typed mode unaffected)
- Blackmarsh setting itself (deferred; engine ships with a small
  procedural test setting first)

---

## 2. Game Modes

Hex mode is **additive**, not a replacement. The new-game menu
gains two options alongside the existing classic dungeon crawl:

| Mode             | Start hex            | Starting gear   | On death           |
|------------------|----------------------|-----------------|--------------------|
| Classic Dungeon  | (no hex map)         | as today        | as today           |
| Hexcrawl Easy    | hub hex (revealed)   | extended kit    | dialog: permadeath or cheat death |
| Hexcrawl Survival| random non-feature hex (hub somewhere unrevealed) | minimum kit | permadeath only |

Other mechanics (encounter rates, fog-of-war strictness, autosave
cadence) are identical between Easy and Survival.

CLI:

```
./play --mode classic                  # current dungeon-only behavior
./play --mode hex-easy                 # overland, hub start
./play --mode hex-survival             # overland, random start
./play --mode hex-easy --pack testland # explicit content pack
```

Default pack is the bundled `testland` setting described in section 7.

---

## 3. Source Materials

### Hextiles

The repository ships with hex tile art under `hextiles/` (CC-licensed,
flat-top orientation, ~200x240 px PNGs). The directory is
`.gitignore`d -- the asset set is too large for git and is deployed
to production manually via `scp`. A runtime check on hex-mode startup
warns clearly if the directory is missing or incomplete and falls
back to a placeholder glyph.

The asset set covers five base biome variants (greenlands,
drylands, sandlands, icelands, deadlands) plus forest and
mountain specialty sets, with additional biomes (hills, marsh,
swamp, water) for a total of 11 `Biome` enum members. Each
biome variant uses a consistent 27-slot template:

| Slot | Feature      | Slot | Feature      | Slot | Feature        |
|------|--------------|------|--------------|------|----------------|
|  1   | volcano      | 10   | lake         | 19   | graveyard      |
|  2   | forest       | 11   | village      | 20   | swamp          |
|  3   | tundra       | 12   | city         | 21   | floating island|
|  4   | trees        | 13   | tower        | 22   | keep           |
|  5   | water        | 14   | community    | 23   | wonder         |
|  6   | hills        | 15   | cave         | 24   | crystals       |
|  7   | river        | 16   | hole         | 25   | stones         |
|  8   | portal       | 17   | dead trees   | 26   | farms          |
|  9   | mountains    | 18   | ruins        | 27   | fog            |

Lookup convention:

```
hextile_path(biome, feature)
  -> "hextiles/{biome}/{slot}-{biome}_{feature}.png"
```

Foundation tiles in the directory root provide neutral fallbacks.

### Blackmarsh (deferred)

Blackmarsh by Robert S. Conley (CC-BY 4.0) is the intended second
content pack. It provides ~30-40 keyed hexes including 8 settlements
and 7 dungeon sites, full English (`Blackmarsh Rev 5.pdf`) and
Spanish (`Marjalnegro.pdf`). Catalan would need a fresh translation.

Blackmarsh is **not** part of v1. The engine is designed so that
ingesting it in a later phase requires no engine changes -- only
content authoring and a few hand-keyed dungeon templates for
signature sites (Castle Blackmarsh, Mountain That Fell, Atacyl's
tomb). See section 11 for phasing.

### Localization

All hex-mode strings are authored in **EN, CA, and ES** from v1, in
the existing `nhc/i18n/locales/{en,ca,es}.yaml` files. The test
setting has a small string surface (a few dozen entries); the
discipline pays off once larger packs land.

Engine keys use the `hex.*` namespace; per-pack content keys use
`content.<pack_id>.*`:

```yaml
# en.yaml
hex:
  ui:
    day: "Day"
    morning: "Morning"
    flee_dungeon: "Flee Dungeon"
content:
  testland:
    pack:
      name: "The Testlands"
    hex:
      hub:
        name: "Stonecross"
        description: "A market town at a river crossing."
```

---

## 4. Data Model

### Coordinates

Flat-top hexes addressed by **axial coordinates** `(q, r)`. The
third cube coordinate is `s = -q - r`. Six neighbor offsets:

```
+q,  0       (east)
+q, -r       (north-east)
 0, -r       (north-west)
-q,  0       (west)
-q, +r       (south-west)
 0, +r       (south-east)
```

A small math module `nhc/hexcrawl/coords.py` provides
neighbors, distance, line-draw, ring-iteration, and pixel
conversion (for web rendering).

### Engine types

New module `nhc/hexcrawl/`:

```
nhc/hexcrawl/
+-- __init__.py
+-- coords.py            # axial math, neighbors, distance
+-- model.py             # HexCell, HexWorld, Rumor, Faction stub
+-- generator.py         # BSP region partitioning (test setting)
+-- pack.py              # YAML pack loader
+-- transitions.py       # mode switch helpers
+-- mode.py              # GameMode enum
```

Sketch:

```python
class GameMode(Enum):
    CLASSIC  = "classic"
    HEX_EASY = "hex-easy"
    HEX_SURV = "hex-survival"

class Biome(Enum):
    GREENLANDS, DRYLANDS, SANDLANDS, ICELANDS, DEADLANDS,
    FOREST, MOUNTAIN

class HexFeatureType(Enum):
    VILLAGE, CITY, TOWER, KEEP,
    CAVE, RUIN, HOLE, GRAVEYARD,
    CRYSTALS, STONES, WONDER, PORTAL,
    LAKE, RIVER, NONE

class TimeOfDay(Enum):
    MORNING, MIDDAY, EVENING, NIGHT

@dataclass(frozen=True)
class HexCoord:
    q: int
    r: int

@dataclass
class EdgeSegment:
    type: str              # "river" or "path"
    entry_edge: int | None # NEIGHBOR_OFFSETS index (0-5), None = source/sink
    exit_edge: int | None  # NEIGHBOR_OFFSETS index (0-5), None = source/sink

@dataclass
class HexCell:
    coord: HexCoord
    biome: Biome
    feature: HexFeatureType
    name_key: str | None        # i18n key, optional
    desc_key: str | None        # i18n key, optional
    dungeon: DungeonRef | None  # see below
    elevation: float = 0.0      # terrain height, used by river gen
    edges: list[EdgeSegment]    # river/path segments crossing this hex

@dataclass
class DungeonRef:
    template: str               # "procedural:cave",
                                # "scripted:castle_blackmarsh_upper"
    depth: int                  # how many floors deep
    cluster_id: HexCoord | None # cave cluster canonical coord

@dataclass
class Rumor:
    id: str
    text_key: str               # i18n key
    truth: bool                 # True or False
    reveals: HexCoord | None    # if true, may pin a hex on the map

class HexWorld:
    pack_id: str
    seed: int
    width: int
    height: int
    cells: dict[HexCoord, HexCell]
    revealed: set[HexCoord]
    visited: set[HexCoord]
    cleared: set[HexCoord]
    looted: set[HexCoord]
    day: int
    time: TimeOfDay
    last_hub: HexCoord
    active_rumors: list[Rumor]
    last_rumor_day: int = 0             # cooldown tracking
    expedition_party: list[EntityId]    # henchmen on the overland
    biome_costs: dict[Biome, int]       # per-pack travel costs
    cave_clusters: dict[HexCoord, list[HexCoord]]  # adjacent cave groups
    rivers: list[list[HexCoord]]        # river paths (source -> sink)
    paths: list[list[HexCoord]]         # settlement connection paths
```

A stub `Faction` type is included so save format reserves room. No
faction logic runs in v1.

A stub `Mount` ECS component is also added (id, kind, speed_mod) so
saves are forward-compatible. v1 does not consult speed_mod.

### Content pack format

Each pack lives under `content/<pack_id>/`:

```
content/testland/
+-- pack.yaml             # metadata, map size, generator params
+-- locale_keys.yaml      # what i18n keys this pack expects
+-- (no hex entries; map is generated)

content/blackmarsh/        # later phase
+-- pack.yaml
+-- hexes.yaml            # full keyed map
+-- npcs.yaml
+-- factions.yaml
+-- rumors.yaml
+-- dungeons/             # scripted templates
    +-- castle_blackmarsh_upper.yaml
    +-- mountain_that_fell.yaml
    +-- atacyl_tomb.yaml
```

Pack manifest sketch:

```yaml
# content/testland/pack.yaml
id: testland
version: 2
attribution: "NHC test setting (procedural)"
map:
  generator: bsp_regions       # or perlin_regions
  width: 25
  height: 16
  num_regions: 24
  region_min: 10
  region_max: 24
features:
  hub: 1
  village: { min: 2, max: 4 }
  dungeon: { min: 6, max: 10 }
  wonder: { min: 2, max: 4 }
rivers:
  max_rivers: 2                # mountain sources to trace
  min_length: 3                # discard rivers shorter than this
  bifurcation_chance: 0.03     # branch probability per step
paths:
  connect_towers: 0.5          # probability of connecting each tower
  connect_caves: 0.15          # probability of connecting each cave
```

### Save format

Hex mode extends the existing JSON manual save and binary autosave
with a `hex_world` section. The schema version is bumped; old
dungeon-only saves are **not** loaded (they are detected and
rejected with a clear message). This is acceptable pre-1.0.

The floor cache (`Game._floor_cache`) is re-keyed when in hex mode
from `depth` to `(hex_coord, depth)`. Each dungeon is its own cache
slice, so revisiting a dungeon hex restores its exact state.

```python
# Save shape (sketch)
{
  "schema_version": 2,                # bumped from 1 for hex_world section
  "mode": "hex-easy",
  "world": {...},                     # ECS dump
  "level": {...} | None,              # current dungeon floor or None
  "floor_cache": {                    # keyed by (q,r,depth)
    "(3,5,1)": {...},
    "(3,5,2)": {...},
    "(7,2,1)": {...}
  },
  "hex_world": {...}                  # full HexWorld dump
}
```

---

## 5. Gameplay Loop

```
                      +----------------------+
                      |  hub settlement      |
                      |  (town map)          |
                      |  shop / temple /     |
                      |  hire / rumors / rest|
                      +----------+-----------+
                                 |
                                 v
                      +----------------------+
   +----------------> |  overland hex view   | <----------------+
   |                  |  (fog of war,        |                  |
   |                  |   day clock,         |                  |
   |                  |   biome step costs)  |                  |
   |                  +----+--------+--------+                  |
   |                       |        |                           |
   |    encounter?         |        | feature hex               |
   |    fight/flee/talk    |        v                           |
   |                       |   +----+-------------+             |
   |                       |   | dungeon entry    |             |
   |                       |   | party selection  |             |
   |                       |   | dialog           |             |
   |                       |   +----+-------------+             |
   |                       |        |                           |
   |                       v        v                           |
   |                  +-----------------+    exit (entry tile)  |
   |                  |  dungeon mode   |  ---------------------+
   |                  |  (existing!)    |    or panic flee
   |                  +-----------------+      with cost
   |                                |
   +--------------------------------+
        return / new expedition
```

### Day clock

A single in-game clock tracks `day` (int) and `time`
(`TimeOfDay`). One day = four segments
(morning/midday/evening/night).

Each hex move advances the clock by a biome-dependent number of
segments:

| Biome       | Segments per step | Day cost |
|-------------|-------------------|----------|
| Greenlands  | 1                 | 0.25     |
| Drylands    | 1                 | 0.25     |
| Sandlands   | 2                 | 0.50     |
| Icelands    | 2                 | 0.50     |
| Forest      | 2                 | 0.50     |
| Deadlands   | 2                 | 0.50     |
| Hills       | 2                 | 0.50     |
| Marsh       | 3                 | 0.75     |
| Swamp       | 3                 | 0.75     |
| Mountain    | 4                 | 1.00     |
| Water       | 99 (impassable)   | N/A      |

Hills, marsh, swamp, and water are first-class `Biome` enum
members (not modifiers). The exact table lives in `pack.yaml`
`biome_costs:` so settings can override. Defaults above are
the engine's bundled values in `pack.py:DEFAULT_BIOME_COSTS`.

The clock is **frozen while inside a dungeon**. No bookkeeping
crosses the mode boundary. A dungeon visit, however long, returns
the player to the overland at the same time-of-day they entered.

### Rest action

In overland mode, the player can `Rest` to advance the clock by one
day (skipping straight to next morning) and restore HP. Resting
triggers an encounter check at higher weights for night segments.

### Fog of war

Roguelike-style with single-hex visibility. With 5-mile hexes
the player sees only the hex they occupy — there is no extended
field of view ring. Each hex move reveals the destination hex
only. ``visible_cells(center)`` returns ``{center}``.

The ``state_hex`` WebSocket payload ships **all** cells with a
per-cell ``revealed`` boolean. Fog of war is enforced purely
client-side: the fog canvas covers unrevealed hexes with a
sky-blue background stamped with the fog tile
(``27-foundation_fog.png``). Revealed hexes are punched through
the fog. Disabling the fog layer in the debug panel reveals the
entire map visually.

Rumors can pin a *named* distant hex on the map without revealing
intermediate terrain — a single highlighted unknown hex with a
known name, drawn through the fog.

### Rumor system

Each settlement has a rumor table. Talking to the innkeeper (in the
settlement's town map) yields one rumor per visit, with a
configurable cooldown.

Rumors come in two flavors:

- **True**: the rumor's reveal is honored; the named hex is pinned
  on the overland map.
- **False**: the rumor's reveal is ignored or, more devious, pins
  the wrong hex. The player has no way to tell which is which until
  they investigate.

Rumor authoring effort scales with pack size. The test setting
ships with a handful of pre-written rumors templated on biome and
feature type ("there's a dragon's hoard in the eastern hills" --
which may or may not be true).

### Settlement services

Settlements are small navigable town maps -- a single dungeon-style
floor with buildings instead of rooms (shop, temple, inn, stable,
training ground). The existing actions in
`nhc/core/actions/_shop.py`, `_temple.py`, and `_henchman.py` are
reused unchanged. The town map generator is a new minor variant of
the BSP generator (open question: whether to subclass BSP or write
a thin building-oriented generator).

The inn is the rumor source. The stable is a placeholder for the
future mount system. The training ground is a placeholder for
later expedition-party recruitment beyond the existing henchman
limit.

### Encounter flow

Per hex step, an encounter check rolls (frequency configurable per
biome, playtest-driven). On trigger, the player sees a prompt:

```
+--------------------------------------------------+
| A band of goblins blocks the path.               |
|                                                  |
|   [F]ight    [E]vade    [T]alk                   |
+--------------------------------------------------+
```

- **Fight** -- a biome-themed single-room mini-dungeon is generated
  (forest clearing, river crossing, swamp boardwalk) and pushed
  onto the floor cache as if it were a dungeon. The player resolves
  combat with the regular system; on victory or flight from the
  mini-dungeon, control returns to the overland.
- **Evade** -- the player remains on the overland, moves back one
  hex, and rolls for damage / time penalty (configurable).
- **Talk** -- routed through the existing typed-mode LLM pipeline
  (`nhc/narrative/gm.py`) with an encounter-specific context. The
  outcome can be peaceful resolution, demanded tribute, or a fight
  after all.

### Encounter creatures

Drawn from the existing 78-creature bestiary, filtered by biome and
time-of-day weights stored in the pack manifest. The creature
factory pipeline is unchanged.

### Rivers and paths

Rivers and paths are inter-hex connectivity features rendered
as thin overlay lines crossing hex edges on the web frontend.
Both are stored as `EdgeSegment` entries on each hex they cross.

#### Rivers

Generated **before** feature placement so settlements can
prefer river-adjacent hexes. Algorithm:

1. Pick mountain sources above `source_elevation_min`.
2. Walk downhill via weighted-random neighbour selection
   (prefer steeper descent, add jitter for organic shape).
3. Low-probability bifurcation spawns branches.
4. Terminate at WATER tiles or map edge.
5. Discard rivers shorter than `min_length`.

Each hex cell stores elevation (`HexCell.elevation`). The
Perlin generator uses the actual noise sample; BSP synthesises
from biome type plus per-cell jitter.

Hub and village placement soft-prefer hexes within distance 1
of a river cell, falling back to random selection when no
river-adjacent candidate exists.

Configuration via `pack.yaml`:

```yaml
rivers:
  max_rivers: 3              # default 3
  min_length: 4              # default 4
  bifurcation_chance: 0.05   # default 0.05
  source_elevation_min: 0.65 # default 0.65 (optional)
```

All fields are optional; defaults from ``RiverParams`` in
``pack.py`` apply when omitted.

#### Paths

Generated **after** feature placement so all connectable
features are present. Algorithm:

1. Build a minimum spanning tree (MST) over all settlements.
2. A* each MST edge using biome travel costs as weights.
3. Optionally connect towers/keeps and caves to the nearest
   settlement with configurable probability.

Configuration via `pack.yaml`:

```yaml
paths:
  connect_towers: 0.6
  connect_caves: 0.2
```

#### Rendering

Edge segments are drawn on the `hex-feature-canvas` (z-index 2)
as quadratic Bezier curves between entry/exit edge midpoints.
Rivers render as blue solid lines; paths as brown dashed lines.
Deterministic jitter from `(q, r)` keeps curves stable across
repaints.

---

## 6. Integration Architecture

### Game state

```python
class Game:
    mode: GameMode                 # CLASSIC | HEX_EASY | HEX_SURV
    hex_world: HexWorld | None     # None in CLASSIC mode
    level: Level | None            # current dungeon floor or town map
    _floor_cache: dict[
        int | tuple[int, int, int],   # depth (classic) or (q,r,depth)
        tuple[Level, dict]
    ]
```

When `mode == CLASSIC`, the engine behaves exactly as today.
`hex_world` is `None`, the floor cache uses `int` depth keys, and
no hex-related code paths run.

### Mode transitions

Hex <-> dungeon transitions reuse the existing floor cache pattern
(`nhc/core/game.py:1932` and `:2154`-`:2164`). Two new actions
mirror `DescendStairsAction` and `AscendStairsAction`:

| New action               | Mirrors             | Effect                         |
|--------------------------|---------------------|--------------------------------|
| `MoveHexAction`          | `MoveAction`        | step to neighbor hex           |
| `EnterHexFeatureAction`  | `DescendStairsAction`| push overland, load dungeon   |
| `ExitDungeonAction`      | `AscendStairsAction`| pop back to hex                |
| `FleeDungeonAction`      | (new)               | panic exit with cost           |
| `RestAction`             | (new)               | advance day, heal              |
| `ConsultMapAction`       | (new)               | show overland map overlay      |
| `SelectPartyAction`      | (new)               | dialog: pick henchmen for run  |
| `TalkEncounterAction`    | (new)               | route to LLM dialog            |
| `EvadeEncounterAction`   | (new)               | move back, take penalty        |
| `EnterSettlementAction`  | `EnterHexFeatureAction` (variant) | load town map     |

### Dungeon seeding

```python
def dungeon_seed(world_seed: int, coord: HexCoord, template: str) -> int:
    return hash((world_seed, coord.q, coord.r, template)) & 0xFFFFFFFF
```

Reproducibility property: the same world seed always generates the
same dungeon at hex `(q, r)` with the same template, on every
machine and replay.

### Death dialog

When the PC dies, a dialog opens (in any mode that supports it):

```
+--------------------------------------------------+
| You have died.                                   |
|                                                  |
|   [P]ermadeath -- end the game                   |
|   [C]heat death -- respawn at hub, lose          |
|       gold, carried equipment, hired henchmen    |
+--------------------------------------------------+
```

In **Survival** mode the dialog shows only the permadeath option
(cheating death is disabled). In **Easy** mode both options appear.
Picking cheat-death:

1. Drop all gold (set to 0)
2. Strip carried equipment (delete inventory entities)
3. Disband all hired henchmen (overland and dungeon)
4. Teleport PC to `hex_world.last_hub` on the overland
5. Restore HP to full, advance day clock by 1 day

Cleared dungeons stay cleared; revealed hexes stay revealed; named
NPCs killed earlier stay dead. Only the player's expedition state
is reset.

### Autosave

Autosave writes on every hex step (matching the existing
per-dungeon-turn cadence). Inside dungeons, the existing dungeon
autosave continues unchanged. Overland autosave bundles the full
`HexWorld`, the floor cache, and the World ECS dump.

### Expedition party

Hex mode raises the henchman cap to an **expedition size** (default
6, configurable per pack). Henchmen hired in settlements join
`hex_world.expedition_party`.

On dungeon entry, `SelectPartyAction` opens a dialog listing
expedition members; the player picks up to N (the existing dungeon
party cap) to take inside. Unselected henchmen wait at the hex
boundary -- they remain in the expedition party but don't
participate in dungeon combat or share dungeon loot.

---

## 7. Test Setting Generator

The bundled `testland` content pack ships an 8x8 hex map generated
by **BSP region partitioning**, mirroring the dungeon BSP pattern.

### Algorithm

1. **Subdivide** the 8x8 hex region into N regions (default 5)
   using axial-aware BSP. Each region gets ~6-16 hexes.
2. **Assign biomes** to regions from a weighted table based on
   region size, position (edges favor mountain/water), and
   adjacency (adjacent regions tend toward biome contrast for
   visual clarity).
3. **Assign modifiers** (hills, swamp) to a subset of hexes within
   regions based on biome (e.g. swamp modifier likely in
   greenlands near water).
4. **Place features** by rule:
   - Hub settlement: one hex in the largest greenlands region,
     toward the centroid.
   - Small villages: 1-2 in greenlands or drylands, distance >= 3
     from the hub.
   - Dungeon hexes: 3-5 placed by biome -- caves in mountain,
     ruins in swamp/forest, towers in any biome.
   - Wonder hexes: 1-3 placed in unusual biomes (icelands,
     deadlands) for variety.
5. **Validate**: every feature hex must be reachable from the hub
   (BFS over neighbors). If not, retry with a new seed.

### Reproducibility

Seeded by the world seed. Same seed -> same map. Useful for
playtesting balance and debugging.

### Why BSP regions and not noise

Two reasons:

- The team already understands BSP from `dungeon/generators/bsp.py`.
  Reusing the pattern keeps the engine surface small.
- Region partitioning gives **coherent biome blocks** ("a forest
  region", "a mountain range") rather than noisy speckle. The
  player can recognize zones at a glance.

A noise-based (Perlin simplex) generator was added as an
alternative (`perlin_regions`). It samples elevation + moisture
via two independent SimplexNoise fields and uses a Whittaker-
style biome lookup. The `testland-perlin` content pack
demonstrates this. Both generators use the shared feature-
placement pipeline so output contracts are identical; the
choice is made via `pack.yaml` `map.generator` field.

---

## 8. Rendering

### Web

A new view mode `hex` is added to the web client. WebSocket
messages gain a `mode` field; the server emits `state_hex` for
overland frames and the existing `state_dungeon` (renamed from
`state`) for dungeon frames.

Overland canvas stack (all inside ``#hex-container``):

| z-index | Canvas              | Contents                        |
|---------|---------------------|---------------------------------|
| 0       | `hex-base-canvas`   | hex tile PNGs (biome + feature) |
| 1       | `hex-feature-canvas`| edge segments (rivers, paths)   |
| 2       | `hex-fog-canvas`    | sky-blue + fog tile overlay     |
| 3       | `hex-entity-canvas` | player "@" glyph                |
| 4       | `hex-debug-canvas`  | debug overlays                  |
| 6       | `hex-hud`           | direction arrows (DOM)          |

Features sit below fog so unrevealed rivers/paths are hidden
by the fog layer without per-cell checks.

The HUD layer lives inside ``hex-container`` (not as a sibling)
so it inherits the CSS zoom transform. The player avatar is
drawn on the entity canvas, not the HUD.

#### High-resolution rendering

Canvases render at ``CANVAS_SCALE = 238 / HEX_WIDTH`` (~3.3x)
so tile PNGs paint at their native 238x207 resolution. All
drawing uses ``ctx.scale(CANVAS_SCALE)`` in logical coords
(``HEX_SIZE``-based); CSS ``width``/``height`` on each canvas
matches the logical size. Zoom is pure CSS ``transform:
scale(N)`` on the container.

#### Static-once drawing with incremental updates

Static layers (base tiles, features, fog background) are drawn
once on the first ``state_hex`` message and never redrawn.
Subsequent turns only:

- punch newly-revealed hexes through the fog (tracked via a
  ``Set`` of already-punched ``"q,r"`` keys)
- clear + redraw the entity canvas (player glyph)

Static layers are re-armed when leaving hex mode (entering a
dungeon) so they redraw on return.

#### God mode

God mode (``--god`` CLI or per-player registry flag) is
embedded in the HTML as ``window.NHC_GOD_MODE`` at page load.
It enables debug toolbar buttons and the debug panel but does
**not** auto-reveal the hex fog — use the debug panel's fog
layer toggle to see the full map visually. God mode disables
encounter rolls and marks all rumours truthful.

#### Debug bundle

The toolbar's debug-bundle button (or the ``./debug-bundle``
script with optional SSH tunnel) captures:

- game state JSON (ECS, hex world, stats)
- floor SVGs (dungeon depths)
- layer PNGs (all canvas layers, downscaled to CSS display
  size) plus a composite PNG reflecting the player's view
  (respects debug panel layer visibility toggles)
- browser console log (last 500 entries)
- autosave binary, server log

The ``./debug-bundle`` script sends a ``capture_layers``
WebSocket message to the browser, waits for the PNGs to
upload, then downloads the tarball.

Flat-top axial layout math:

```
HEX_SIZE  = 36              # hex radius (centre → corner)
HEX_WIDTH = 2 * HEX_SIZE    # 72 px corner-to-corner
HEX_HEIGHT = sqrt(3) * HEX_SIZE   # ~62 px edge-to-edge

x = HEX_SIZE * 1.5 * q - origin_x + margin
y = HEX_SIZE * (sqrt(3)/2 * q + sqrt(3) * r) - origin_y + margin
```

The server computes the pixel origin (min x/y of all hex
centres) and ships it in the ``state_hex`` payload so the
client offsets all positions for uniform margin padding.

### Terminal

The terminal client (`nhc/rendering/terminal/`) gains a hex view
using **staggered character cells**:

```
   [F]  [F]  [H]  [M]
     [G]  [@]  [H]  [M]
   [G]  [F]  [H]  [M]
     [S]  [F]  [G]  [H]
   [S]  [S]  [G]  [G]

   F=forest G=plains H=hills M=mountain S=swamp @=player
```

Odd rows are offset by two characters to approximate hex geometry.
Each cell is `[X]` where `X` is a glyph derived from biome (with
modifier overlay) and feature (overrides biome glyph).

A mini-map appears in the sidebar in dungeon mode (showing the hex
the player is currently exploring within). The sidebar also shows
day/time, expedition party roster, and known rumors.

### Shared

The `GameClient` abstraction (`nhc/rendering/client.py`) gains a
`render_hex(hex_world)` method alongside the existing `render()`.
Mode-aware dispatch in the game loop calls one or the other based
on `Game.mode` and `Game.hex_world is not None`.

---

## 9. Debug Tools

The MCP debug server (`nhc/debug_tools/mcp_server.py`,
`design/debug_tools.md`) gains a hex tool module reaching parity
with the existing dungeon tools:

| Tool                    | Effect                                  |
|-------------------------|-----------------------------------------|
| `reveal_all_hexes`      | reveal entire map                        |
| `teleport_hex`          | move PC to (q, r)                        |
| `force_encounter`       | trigger encounter at current hex         |
| `show_world_state`      | dump HexWorld (revealed/cleared/etc.)    |
| `advance_day_clock`     | jump N segments forward                  |
| `set_rumor_truth`       | flip a rumor's truth flag for testing    |
| `clear_dungeon_at`      | mark a hex's dungeon as cleared          |
| `seed_dungeon_at`       | preview the seed for a hex's dungeon     |

The admin web UI gains a "Hex" panel exposing the same operations
for live sessions.

God mode (``--god`` CLI or per-player registry flag) extends to
hex mode: invulnerability, all rumors marked truthful, no
encounter checks. Fog of war is **not** auto-revealed — use
the debug panel's fog layer toggle to see the full map.

---

## 10. Phasing

Each phase is independently playable -- no phase requires a future
phase to be useful.

### Phase 0 -- Engine foundations

- `nhc/hexcrawl/coords.py` (axial math, neighbors, distance)
- `nhc/hexcrawl/model.py` (HexCell, HexWorld)
- `nhc/hexcrawl/pack.py` (YAML pack loader)
- `nhc/hexcrawl/generator.py` (BSP region partitioning)
- Bundled `content/testland/` with `pack.yaml`
- Unit tests for axial math and the test-setting generator
- No game integration yet

### Phase 1 -- Traversal + transitions (web-first)

- `GameMode` enum and `--mode` CLI flag
- Web new-game menu offers Easy / Survival
- `MoveHexAction`, `EnterHexFeatureAction`, `ExitDungeonAction`
- Day clock with four segments and biome cost table
- Difficulty-mode start logic (hub vs random)
- Roguelike fog of war
- Save/load with `hex_world` section, schema bump
- Autosave on hex step
- Death dialog (cheat vs permadeath, mode-aware)
- One procedural dungeon hex (`procedural:cave`)
- Web rendering only (overland canvas stack)

### Phase 2 -- Settlements, encounters, expedition party (shipped)

- `nhc/hexcrawl/town.py` (25x20 fixed-slot town generator with
  shop / inn / temple / stable / training rooms, seed-shuffled
  building assignments)
- Town NPCs spawned on entry: merchant + priest + one hirable
  adventurer. Stable and training rooms stay empty as v1
  placeholders for mounts and XP-sink services
- `MAX_EXPEDITION = 6` raises the hex-mode party cap above the
  dungeon `MAX_HENCHMEN = 2`. Entering a cave / ruin pulls the
  first `MAX_HENCHMEN` hired henchmen in; the rest wait on the
  overland hex as left-behinds (`Position.level_id == "overland"`)
  until the player returns. Settlements have no cap -- the whole
  expedition comes inside. Interactive selection dialog is a UI
  polish pass on top of the deterministic first-N picker
- `nhc/hexcrawl/encounter.py` (single-room biome-themed "arena"
  generator with a west-side stairs_up entry) +
  `encounter_pipeline.py` (`roll_encounter`, `Encounter`,
  `EncounterChoice`). `Game.resolve_encounter` dispatches
  Fight (push arena) / Flee (1d4 damage) / Talk (peaceful pop)
- `nhc/hexcrawl/rumors.py` seeds mixed true / false rumor pools
  from the current world state; `gather_rumor_at` pops from
  `HexWorld.active_rumors` and reveals the target hex
- `Game.panic_flee()` exits the dungeon from anywhere at a cost:
  1d6 HP (floored so it never kills), plus one day-clock segment
- Covered end-to-end by `tests/unit/hexcrawl/test_phase2_smoke.py`

**Deferred to later milestones:** innkeeper NPC in the inn room,
a dedicated interactive henchman-selection dialog, LLM Talk
dialog, biome-tuned encounter rates.

### Phase 3 -- Terminal parity (shipped)

- `nhc/rendering/terminal/hex_renderer.py` emits the overland
  ASCII frame: odd-q staggered grid with single-char biome /
  feature glyphs, `@` for the player, trailing status line
  showing day / time / axial coord / biome / feature
- `TerminalRenderer.render_hex()` drops the frame above the
  usual message log + hint strip; a ``_hex_mode`` flag toggles
  the dispatch table in `get_input` so the hex-mode key
  bindings land only when the player is actually on the
  overland
- `HEX_KEY_MAP` / `map_key_to_hex_intent` translate vi
  (`y u k j b n`), numpad (`1-9`) and arrow keys into the six
  flat-top directions; `>` enters a feature, `.` / `5` rest,
  Shift+`L` exits to overland, Shift+`F` panic-flees
- CLI wiring complete: `./play --world hex-easy` launches the
  terminal directly onto the overland; `gamemode_from_args`
  is routed through the `Game` constructor in `nhc.py`

**Deferred to later milestones:** sidebar mini-map (the full
frame already fits a 25x16 world in ~50 cols × 32 rows), a
terminal henchman-selection dialog (cave entry uses the
deterministic first-N picker for now), terminal death dialog
(the dungeon one already fires; hex-mode permadeath follows
the same path).

### Phase 4 -- Debug tools + polish (shipped)

- `nhc/hexcrawl/debug.py` hosts eight pure helpers:
  `reveal_all_hexes`, `teleport_hex`, `force_encounter`,
  `show_world_state`, `advance_day_clock`, `set_rumor_truth`,
  `clear_dungeon_at`, `seed_dungeon_at`. Unit-tested in
  isolation plus through the MCP wrapper round-trip
- `nhc/debug_tools/tools/hex_tools.py` wraps each helper as an
  MCP tool; the wrappers load the HexWorld from an autosave via
  `read_autosave_payload`. Mutations run dry against the
  in-memory copy (no write-back) so a running session can't be
  surprised by an external edit
- `/api/admin/sessions/<sid>/hex/{state,reveal,teleport}`
  endpoints operate on the live session's HexWorld so the
  admin UI can see and poke what the player is looking at.
  The Active Sessions table on `/admin` gained Reveal / State
  per-row buttons
- God-mode now extends to hex: `set_god_mode(True)` lifts the
  fog over every in-shape cell, `Game.encounters_disabled`
  becomes True (a flag future auto-roll sites can consult),
  and `generate_rumors_god_mode` flips every rumor's truth
  field to True so the debug player never chases a false lead
- End-to-end smoke in `tests/unit/hexcrawl/test_phase4_smoke.py`
  proves the god-mode + MCP-tool round trip composes

**Deferred to later milestones:** write-back hooks so MCP
mutating tools apply to the live autosave under a cooperating
session, per-tool admin UI forms for the remaining operations
(force_encounter, set_rumor_truth, seed_dungeon_at,
clear_dungeon_at, advance_day_clock), dedicated log topics
for hex events.

### Phase 5 -- Blackmarsh content pack

- Ingest ~40 keyed Blackmarsh hexes to YAML (EN + ES from source)
- Faction system runtime (was deferred)
- Scripted dungeon templates for signature sites
- Catalan translation pass for Blackmarsh content
- Hand-tuned rumor table

### Phase 6 -- Post-v1 polish (as desired)

- Typed (LLM) overland intent parsing and travel narration
- Supplies and/or weather/seasons
- Mount gameplay effect (use the existing component stub)
- Town map authoring quality pass

---

## 11. Risks and Unknowns

- **Settlement map authoring quality.** Procedural town maps may
  feel samey across visits. Mitigation: a small library of building
  templates, themed by biome.
- **Save format complexity.** Full persistence means the
  serializer atomically captures `World` + `Level` + floor cache +
  `HexWorld`. Schema-versioning tests are written **before** the
  hex-mode features land.
- **ASCII hex rendering UX.** Staggered char cells are readable
  but compact; cell-count scaling on a typical terminal needs a
  spike. Mitigation: web-first ship; terminal in Phase 3.
- **Panic-flee balance.** Too cheap = exploit; too expensive =
  unused. Tuned by playtest in Phase 2.
- **Dungeon party selection UX in terminal.** Modal dialogs in
  blessed need care; reuse the existing menu widget patterns.
- **Test-setting biome variety on 8x8.** Five regions on 64 hexes
  may produce flat-feeling maps. Mitigation: tune region count and
  biome contrast, allow seed re-rolls.
- **Hextile distribution.** A production deploy that forgets the
  `scp` step renders the overland with placeholder glyphs only.
  Mitigation: startup check warns loudly.

---

## 12. Open Questions

Decisions deliberately deferred from v1, to be settled during
implementation phases or later:

 1. Exact biome-to-day-cost table (defaults proposed in section 5;
    final tuning in Phase 2 playtest).
 2. Encounter frequency per biome and time-of-day (playtest).
 3. Panic-flee cost (damage, dropped loot, day-clock penalty --
    which combination, how much).
 4. Town-map generator strategy (subclass BSP with building
    painter, or new building-oriented generator).
 5. Wonder-site event format (one-off Python scripts or YAML
    effect descriptors).
 6. Rumor-authoring volume and templates for the test setting.
 7. Catalan translation workflow for Blackmarsh (LLM-assisted
    first pass with human review, or fully manual).
 8. Scripted dungeon template format (YAML scripts, or Python
    factories with `@register_scripted_dungeon`).
 9. Starting gear and gold values per difficulty (balance pass).
10. Interactions between "visited", "cleared", and "revealed"
    once the faction layer lands.
11. Whether the expedition cap should scale with PC level or stay
    flat at 6.
12. Whether evading an encounter on a long-cost biome (mountain,
    swamp) advances the clock differently than on plains.

---

## 13. Cross-References

- `design/design.md` -- master architecture; authoritative for the
  dungeon layer that hex mode wraps.
- `design/dungeon_generator.md` -- BSP pipeline reused by the test
  setting's region partitioner and by mini-dungeon encounter maps.
- `design/web_client.md` -- Flask + WebSocket architecture; hosts
  the overland view alongside the dungeon view.
- `design/canvas_rendering.md` -- five-layer canvas pattern that
  the overland stack mirrors.
- `design/typed_gameplay.md` -- LLM pipeline reused for the
  encounter "Talk" branch and (in Phase 6) for typed overland.
- `design/debug_tools.md` -- MCP server architecture; extended in
  Phase 4 with hex tools.
- `design/magic_items.md` -- unchanged; rings/wands work the same
  in dungeons regardless of hex-mode wrapping.
