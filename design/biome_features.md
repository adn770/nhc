# Biome Features & Settlement Placement

**Status:** proposal, reviewed 2026-04-19 (6 Q/A rounds), not yet
implemented.

This document captures the biome-aware settlement + site layout
agreed in conversation: which features may appear on which biomes,
which hex-tile art renders each feature on each biome, how world
generation places them, and which site assembler each new feature
routes through.

Scope spans three subsystems:

- **Overland feature placement** — `nhc/hexcrawl/_features.py`.
- **Tile-art lookup** — `nhc/hexcrawl/tiles.py`.
- **Site assemblers** — `nhc/dungeon/sites/*.py`
  (consumed through `nhc/dungeon/site.py::assemble_site`).

See `design/building_generator.md` for the broader building-
generator design. This doc is the biome / feature taxonomy that
feeds it.

---

## 1. Goals

1. Let the overland visibly communicate "what kind of settlement
   is this?" via four distinct settlement icons (`city`,
   `village`, `community`, `farms`), plus biome-themed variants
   on forest and mountain.
2. Place settlements where they make sense per biome — cities
   only on greenlands/hills, farms only on greenlands, communities
   and villages broadly, temples on wilderness biomes (mountain /
   forest) plus *mysterious out-of-place* variants on sandlands
   and icelands for narrative intrigue.
3. Route every new feature through the existing site-assembler
   pipeline so door-crossing, descent, stair navigation, and
   entity spawning all keep working without special cases.
4. Biome tweaks the site assembler's defaults (e.g. mountain
   village = stone-only, no palisade) without proliferating
   new `HexFeatureType` values.
5. Reframe **ruins** as *abandoned* multi-floor dungeon
   entrances (surface layer + mandatory 3-floor descent) so the
   keep↔ruin pair reads as *inhabited fortified compound vs
   abandoned dungeon gate* — two related but distinct feature
   types.

Non-goals:

- Rich per-biome encounter tables. This doc is about placement
  and geometry; hostile / NPC mix stays on the existing populator
  path.
- Temple gameplay beyond "priest services." The elaborate
  temple design (vertical open halls, sightline tricks) stays
  deferred to building-generator milestone M16.
- Inhabited-keep NPCs. "Keeps are inhabited" is the semantic
  pair for "ruins are abandoned", but actually populating keep
  surfaces with NPCs is follow-up work (see §8).

---

## 2. Feature taxonomy

### New `HexFeatureType` values

Three new values on the enum:

```python
class HexFeatureType(Enum):
    ...existing...
    COMMUNITY = "community"   # hamlet-scale settlement
    TEMPLE    = "temple"      # standalone temple (mountain/forest)
    COTTAGE   = "cottage"     # tiny one-building forest site
```

### Feature → site_kind mapping

`_site_kind_for` in `nhc/hexcrawl/_features.py` gets three new
entries:

```python
HexFeatureType.COMMUNITY: "town",     # town assembler,
                                      # size_class="hamlet"
HexFeatureType.TEMPLE:    "temple",   # new temple assembler
HexFeatureType.COTTAGE:   "cottage",  # new cottage assembler
```

### Feature → size_class

For features that route to the town assembler, the `size_class`
is **pinned by the feature type**, not rolled:

| Feature   | size_class for town assembler |
|-----------|-------------------------------|
| CITY      | `city`                        |
| VILLAGE   | `village`                     |
| COMMUNITY | `hamlet`                      |

The current `_pick_village_size_class` roll goes away. A VILLAGE
hex is always village-sized; a COMMUNITY hex is always
hamlet-sized. This keeps the overland icon honest about the site
scale the player will see.

---

## 3. Biome eligibility matrix

Legend: `✓` standard variant, `⊗` mysterious out-of-place
variant (temple only — see note below). Empty cell means the
feature cannot spawn on that biome.

<!-- markdownlint-disable MD013 -->
| Feature   | Greenlands | Hills | Sandlands | Drylands | Marsh | Mountain | Forest | Icelands | Deadlands |
|-----------|:----------:|:-----:|:---------:|:--------:|:-----:|:--------:|:------:|:--------:|:---------:|
| CITY      |     ✓      |   ✓   |           |          |       |          |        |          |           |
| VILLAGE   |     ✓      |   ✓   |     ✓     |    ✓     |   ✓   |    ✓     |        |          |           |
| COMMUNITY |     ✓      |   ✓   |     ✓     |    ✓     |   ✓   |    ✓     |   ✓    |          |           |
| FARM      |     ✓      |       |           |          |       |          |        |          |           |
| MANSION   |     ✓      |   ✓   |           |          |   ✓   |          |        |          |           |
| COTTAGE   |            |       |           |          |       |          |   ✓    |          |           |
| TEMPLE    |            |       |     ⊗     |          |       |    ✓     |   ✓    |    ⊗     |           |
| RUIN      |            |       |     ✓     |          |   ✓   |          |   ✓    |    ✓     |     ✓     |
<!-- markdownlint-enable MD013 -->

Features **unchanged** from the current placement rules (listed
here so the matrix stays self-contained):

- **TOWER** — broad placement; every biome except `water`.
- **KEEP** — `greenlands`, `hills`, `drylands`.
- **CAVE** — `mountain`.
- **GRAVEYARD** — `deadlands`, `icelands`, `swamp`, `marsh`.
- **WONDER / CRYSTALS / STONES / PORTAL** — `icelands`,
  `deadlands` (random wonder-type pool).

TEMPLE on sandlands and icelands is a **mysterious out-of-place
site** — the tile art hints at ruins or the unknown, and the
temple assembler picks a weathered / half-buried variant (see
§6). Mountain and forest temples are the "expected" kind: a
priest at a shrine on the wilderness road.

RUIN doubles its biome pool from the current `{forest,
deadlands}` to `{forest, deadlands, marsh, sandlands, icelands}`
and is reframed as an **abandoned multi-floor dungeon entrance**
rather than a single-floor BSP dungeon. See §6 for the ruin site
assembler spec and §7 for the surface / descent layout.

Encoded as:

```python
FEATURE_BIOMES: dict[HexFeatureType, tuple[Biome, ...]] = {
    HexFeatureType.CITY:      (Biome.GREENLANDS, Biome.HILLS),
    HexFeatureType.VILLAGE:   (
        Biome.GREENLANDS, Biome.HILLS, Biome.SANDLANDS,
        Biome.DRYLANDS,   Biome.MARSH, Biome.MOUNTAIN,
    ),
    HexFeatureType.COMMUNITY: (
        Biome.GREENLANDS, Biome.HILLS, Biome.SANDLANDS,
        Biome.DRYLANDS,   Biome.MARSH, Biome.MOUNTAIN,
        Biome.FOREST,
    ),
    HexFeatureType.FARM:      (Biome.GREENLANDS,),
    HexFeatureType.MANSION:   (
        Biome.GREENLANDS, Biome.HILLS, Biome.MARSH,
    ),
    HexFeatureType.COTTAGE:   (Biome.FOREST,),
    HexFeatureType.TEMPLE:    (
        Biome.MOUNTAIN, Biome.FOREST,
        Biome.SANDLANDS, Biome.ICELANDS,  # mysterious variants
    ),
    HexFeatureType.RUIN:      (
        Biome.FOREST,    Biome.DEADLANDS,   # unchanged
        Biome.MARSH,     Biome.SANDLANDS,   # NEW
        Biome.ICELANDS,                     # NEW
    ),
    # ...others unchanged
}
```

This table becomes the single source of truth for
`place_dungeons` and `place_features` biome pools.

---

## 4. Tile art lookup

`tiles.py` currently uses a single `(base_slots, extended_slots)`
tuple per feature. We replace that with a biome-keyed lookup:

```python
# feature name -> biome -> list of tile slot candidates.
_FEATURE_TILES: dict[str, dict[str, list[int]]] = {
    "city":      {"greenlands": [12], "hills": [12]},
    "village":   {"greenlands": [11], "hills": [11],
                  "sandlands": [11], "drylands": [11],
                  "marsh": [11], "mountain": [75]},
    "community": {"greenlands": [14], "hills": [14],
                  "sandlands": [14], "drylands": [14],
                  "marsh": [14], "mountain": [74],
                  "forest": [53]},
    "farm":      {"greenlands": [26]},
    "mansion":   {"greenlands": [52], "hills": [52],
                  "marsh": [52]},
    "cottage":   {"forest": [52]},
    "temple":    {"mountain":  [80], "forest":   [58],
                  "sandlands": [80],   # stone mountain-Temple
                                       # overlaid on sand — ancient
                                       # desert shrine
                  "icelands":  [58]},  # forest-Temple overlaid on
                                       # frozen grey — mossy temple
                                       # stranded in the ice
    "ruin":      {"forest":    [18, 55],   # 55 = overgrown-Ruins
                  "deadlands": [18],
                  "marsh":     [18],
                  "sandlands": [18],
                  "icelands":  [18]},
    "tower":     {"greenlands": [13], "hills": [13],
                  "sandlands": [13], "drylands": [13],
                  "marsh": [13], "mountain": [76],
                  "forest": [54],
                  # fallbacks for other biomes:
                  "icelands": [13], "deadlands": [13],
                  "swamp": [13]},
    "keep":      {"greenlands": [22], "hills": [22],
                  "drylands": [22]},
    # unchanged dungeon features keep their current multi-slot
    # mappings (cave, ruin, hole, graveyard, stones, etc.)
}
```

### Slot numbers reference

From `SLOT_NAME` in `nhc/hexcrawl/tiles.py`:

- `11` village, `12` city, `13` tower, `14` community, `18` ruins,
  `22` keep, `26` farms
- `52` cottage, `53` hamlet, `54` watchtower, `58` forest-Temple
- `74` mountain-Lodge, `75` mountain-Village, `76` mountain-Tower,
  `80` mountain-Temple

### New tile generations (mysterious temples)

Two biome-specific temple variants don't ship as hand-drawn
PNGs and are generated from foundation tiles by
`tools/generate_missing_hextiles.py`:

- `hextiles/icelands/58-icelands_forest-Temple.png` — the
  forest-Temple foundation composed over the pale-grey icelands
  background. Renders as a mossy stone temple stranded in
  frozen tundra.
- `hextiles/sandlands/80-sandlands_mountain-Temple.png` — the
  mountain-Temple foundation composed over the sand-coloured
  sandlands background. Renders as an ancient stone shrine
  rising from the dunes.

The tool has an `EXTRA_PAIRS` table that drives these; adding
more (biome, slot) crossovers in the future is one tuple per
entry. See `tools/generate_missing_hextiles.py`.

### Lookup rules

1. `_FEATURE_TILES[feature][biome]` → list of slot candidates.
2. Use `hex_hash(q, r) % len(candidates)` to pick one
   deterministically (same hex → same slot across reloads).
3. If the biome isn't in the feature's dict, fall back to the
   first greenlands / hills slot, or raise if neither exists —
   this mirrors the current "extended slots only on extended
   biomes" behaviour but with explicit entries instead of the
   implicit `_EXTENDED_BIOMES` frozenset.
4. `_EXTENDED_BIOMES` and the base/extended split in
   `_FEATURE_BASE` get deleted.

### Deterministic hex hashing

No change. Same `hex_hash(q, r)` feeds selection.

---

## 5. World-gen placement

### Pack schema

`PackMeta.features` gains one field:

```python
@dataclass
class FeatureCounts:
    dungeon: Range = Range(6, 10)
    village: Range = Range(3, 6)
    community: Range = Range(0, 0)   # NEW, default off
    wonder: Range = Range(2, 4)
    patterns: tuple[str, ...] = ()
```

Existing packs keep their current feel until they opt into
communities. The testland pack gets `community: Range(2, 5)` so
development worlds actually exercise the new feature.

### Placement order in `place_features`

Same overall flow, just with one extra loop:

1. **Hub (CITY)** — pick from `FEATURE_BIOMES[CITY]`
   (greenlands → hills fallback; no drylands fallback anymore
   because drylands isn't eligible for CITY).
2. **Villages** — place `n_villages` hexes from the VILLAGE
   biome pool, honouring `_adjacent_to_settlement`. `size_class`
   is pinned to `"village"`; no roll.
3. **Communities (new)** — place `n_community` hexes the same
   way from the COMMUNITY biome pool. Still subject to
   `_adjacent_to_settlement` so villages / communities don't
   cluster. `size_class="hamlet"`.
4. Feature patterns (unchanged).
5. **Dungeons** — `place_dungeons` recipes updated: existing
   features unchanged, plus new recipes for TEMPLE and COTTAGE
   keyed to `FEATURE_BIOMES`. MANSION's biome pool shrinks from
   the current `{greenlands, hills, forest}` to the new
   `{greenlands, hills, marsh}` per the matrix.
6. Wonders (unchanged).

### `place_dungeons` recipe updates

New table:

```python
RECIPES: list[tuple[HexFeatureType, tuple[Biome, ...]]] = [
    (HexFeatureType.CAVE,      (Biome.MOUNTAIN,)),
    (HexFeatureType.RUIN,      (Biome.FOREST, Biome.DEADLANDS)),
    (HexFeatureType.GRAVEYARD, (Biome.DEADLANDS, Biome.ICELANDS,
                                Biome.SWAMP, Biome.MARSH)),
    (HexFeatureType.KEEP,      FEATURE_BIOMES[HexFeatureType.KEEP]),
    (HexFeatureType.MANSION,   FEATURE_BIOMES[HexFeatureType.MANSION]),
    (HexFeatureType.FARM,      FEATURE_BIOMES[HexFeatureType.FARM]),
    (HexFeatureType.COTTAGE,   FEATURE_BIOMES[HexFeatureType.COTTAGE]),
    (HexFeatureType.TEMPLE,    FEATURE_BIOMES[HexFeatureType.TEMPLE]),
    (HexFeatureType.TOWER,     tuple(
        b for b in Biome if b is not Biome.WATER
    )),
]
```

The first-pass-variety loop still tries to place one of each
before round-robin filling the remaining budget.

---

## 6. Site assemblers

### Town assembler — new `biome` parameter

`assemble_town(site_id, rng, size_class="village", biome=None)`.

`biome` is an optional `Biome` enum (or string). When set, it
overrides defaults:

| Biome       | Override                                    |
|-------------|---------------------------------------------|
| `mountain`  | `wall_material="stone"` for every building; `has_palisade=False` regardless of `size_class`; building count skew to smaller |
| other       | current defaults                            |

This keeps the feature taxonomy flat (no `MOUNTAIN_VILLAGE` /
`MOUNTAIN_LODGE` enum values) while letting the assembler respond
to biome when it matters.

Signature is threaded through `assemble_site(kind, site_id, rng,
size_class=None, biome=None)` and `_enter_walled_site` in
`nhc/core/game.py`, which already passes `size_class` from the
`DungeonRef`; `biome` comes from `cell.biome`.

### Temple assembler — new

`nhc/dungeon/sites/temple.py`, `assemble_temple(site_id, rng,
biome=None)`:

- One building with the `temple` role tag.
- `base_rect` ~8x8 (between farm and mansion scale).
- No palisade / enclosure.
- No descent stairs in v1.
- Priest NPC placement on ground-floor room centre, same
  `EntityPlacement` shape as the town assembler's temple role
  (TEMPLE_SERVICES_DEFAULT + TEMPLE_STOCK_DEFAULT). Even the
  mysterious variants have a priest — a hermit tending the
  forgotten shrine. (Leaving them uninhabited would make the
  hex a dead-end for the player; keep services reachable.)

Per-biome tweaks drive identity (all routed through the same
assembler + `biome` parameter):

| Biome       | Variant   | Shape         | Walls       | Surface ring         |
|-------------|-----------|---------------|-------------|----------------------|
| `mountain`  | expected  | `OctagonShape`| stone       | bare FLOOR (mountain path) |
| `forest`    | expected  | `RectShape`   | stone       | GARDEN ring (tended approach) |
| `sandlands` | mysterious| `OctagonShape`| stone, *partial* | bare FLOOR, minimal; no garden |
| `icelands`  | mysterious| `OctagonShape`| stone, *partial* | bare FLOOR, minimal; no garden |

*Partial walls* for the mysterious variants: a handful of
perimeter wall tiles are dropped at random, so the building
reads as ruined / half-collapsed from the outside while still
enclosing enough interior to walk around. Implementation detail:
after the normal wall ring is painted, pick 2–4 perimeter tiles
(excluding the door + its neighbours) and swap them back to VOID.

This is a deliberately minimal implementation — M16 will
redesign temple layouts with vertical open halls / multi-stair
landings. Nothing persisted refers to temple internals, so the
redesign is a drop-in swap. The mysterious variants will keep
their partial-wall flavour in M16 as a regional theme.

### Cottage assembler — new

`nhc/dungeon/sites/cottage.py`, `assemble_cottage(site_id, rng,
biome=None)`:

- One tiny building (`base_rect` ~5x5), single floor.
- Wood interior, brick walls.
- No service NPC placement in v1. Could host a hermit / hostile
  squatter later via the normal populator path; that's a future
  pass.
- No palisade, no descent.
- Surface: a tiny forest-floor GARDEN ring around the building
  so the door-crossing handler has a walkable surface tile.
- **Empty in v1.** No `populate_level` call on the cottage
  surface or interior. The cottage reads as genuinely abandoned
  — no hostile squatters, no service NPCs. A `TODO` comment at
  the expected populator-hook point flags the v2 extension
  (cottage creature / loot / hermit content).

### Ruin assembler — new (reframes the existing `RUIN` feature)

`nhc/dungeon/sites/ruin.py`, `assemble_ruin(site_id, rng,
biome=None)`. Ruins are **abandoned dungeon entrances** —
contrast with keeps, which are inhabited fortified compounds.

**Surface layer (what the player first sees):**

- 1–2 partial buildings inside a **broken enclosure** — a
  collapsed palisade or fortification with a missing gate and
  2–4 dropped wall segments. Reuses the mysterious-temple
  partial-wall trick: paint the normal ring, then swap a few
  perimeter tiles back to VOID. The broken wall reads as
  "something used to guard this."
- Buildings are smaller than a keep's (2–3 rooms each, single
  floor on surface), with perimeter walls also partially
  collapsed. Interior floor is stone.
- No civilian NPCs. The site is abandoned — no merchant, no
  priest, no innkeeper.
- Surface is compact — ~18x14 footprint.
- Surface tiles use the biome's default walkable surface:
  forest → GARDEN / FIELD ring, marsh → FIELD, sandlands → bare
  FLOOR, icelands → bare FLOOR, deadlands → bare FLOOR.
- **Mandatory descent.** One of the ruin's buildings has
  `descent = DungeonRef(template="procedural:ruin", depth=3)`
  attached to its ground floor. Unlike keep descents (which
  roll 40% per building), ruin descent is always present — the
  ruin exists *as* the dungeon entrance.
- **Populator runs on the surface.** After assembly the site
  calls `populate_level(surface, faction=...)` so hostile
  creatures spawn in the surface rooms. This matches how cave
  Floor 1 is populated today and reuses existing creature-pool
  infrastructure.
- **v1 faction source: shared humanoid pool.** All ruins draw
  from the existing Caves-of-Chaos humanoid pool (`goblin`,
  `orc`, `kobold`, `gnoll`, `bugbear`, `ogre`) regardless of
  biome. This is the simplest thing that ships with zero new
  creature content. See §8 for the planned v2 extension that
  adds biome-specific faction pools.

**Descent (the real dungeon):**

- `RUIN_DESCENT_FLOORS = 3` (module-level tunable constant).
  All floors generate via the `procedural:ruin` template (the
  existing template, previously the single-floor ruin path).
- Each floor runs the standard populator: faction-themed
  creatures distributed across BSP rooms.
- Cross-floor stairs linking floor N to N+1, standard dungeon
  convention (DescendStairs takes you deeper).
- Ascending from descent Floor 1 returns to the ruin surface at
  the building-ground `stairs_down` tile — the same pattern
  `_exit_building_descent` uses for tower / keep / mansion
  cellars.

**MVP tunables (module-level constants):**

```python
RUIN_BUILDING_COUNT_RANGE = (1, 1)     # single partial building
                                       # (bump to (1, 2) or (2, 2)
                                       # later without logic change)
RUIN_ENCLOSURE_KIND       = "fortification"  # stone reads as
                                             # ancient / mysterious;
                                             # later swap to a
                                             # dict[biome, kind] for
                                             # biome-specific styles
RUIN_DESCENT_FLOORS       = 3
RUIN_DESCENT_TEMPLATE     = "procedural:ruin"
```

**Biome identity (surface flavour only — structural layout
shared):**

| Biome      | Surface flavour                              |
|------------|----------------------------------------------|
| `forest`   | Overgrown stone, GARDEN ring (ivy / moss)    |
| `deadlands`| Blasted stone on bare ground                 |
| `marsh`    | Sinking stone, FIELD ring (waterlogged)      |
| `sandlands`| Half-buried stone on pale sand, bare floor   |
| `icelands` | Frost-cracked stone on snowy ground          |

All five biomes use the same layout recipe, same enclosure
kind, same descent depth, same faction pool (in v1). Only the
surface ring style differs.

**Migration note:** the existing `procedural:ruin` template is
**kept** (not deleted like `procedural:keep` was) because it now
drives every descent floor. What changes is that single-floor
ruin hexes — the legacy `enter_hex_feature` fallthrough that
generated one BSP dungeon — route through the site assembler
instead. Tests that exercised `template="procedural:ruin"` via
direct `generate_level` calls stay valid (the template still
produces a level); tests that entered a ruin hex and expected a
flat single-level dungeon need rewriting.

### Assembler dispatcher updates

`SITE_KINDS` becomes `("tower", "farm", "mansion", "keep",
"town", "temple", "cottage", "ruin")`. The `assemble_site`
dispatcher adds three deferred-import branches (temple, cottage,
ruin).

`_site_kind_for(HexFeatureType.RUIN) = "ruin"` so the dispatch
routes ruin hexes through `_enter_walled_site`. A ruin's
`RUIN_ENCLOSURE_KIND = "fortification"` gives the site an
`Enclosure` (with a broken gate), which is exactly what
`_enter_walled_site` expects — the "broken" aspect is a
rendering / tile-state choice, not a dispatch-level one. No new
entry helper needed.

---

## 7. Milestones / implementation order

I expect roughly 7 commits:

1. **Taxonomy** — add `COMMUNITY`, `TEMPLE`, `COTTAGE` to
   `HexFeatureType`; add `community` knob to `PackMeta`; update
   `_site_kind_for` / `_template_for`. `RUIN` stays as-is in the
   enum but gets `site_kind="ruin"`. Tests: enum existence,
   pack parsing.
2. **Tile art** — rewrite `_FEATURE_BASE` into the biome-keyed
   `_FEATURE_TILES`; delete `_EXTENDED_BIOMES`; update
   `feature_variants` and `assign_tile_slot`. Tests: each
   (feature, biome) pair returns an expected slot.
3. **Placement** — encode `FEATURE_BIOMES`; rewrite
   `place_features` / `place_dungeons` to consult it; pin
   `size_class` by feature type; hub fallback drops drylands;
   RUIN biome pool expands to `{forest, deadlands, marsh,
   sandlands, icelands}`. Tests: biome pool per feature,
   community placement respects `_adjacent_to_settlement`, pack
   count honoured.
4. **Town biome parameter** — thread `biome` through
   `assemble_site` and `assemble_town`; mountain override for
   stone-only + no palisade. Tests: a mountain village is
   palisade-less and stone.
5. **Temple + cottage assemblers** — new files, dispatcher
   entries, one end-to-end test per feature (enter hex, verify
   active level has expected `building_id` / entities). Temple
   tests cover all four biomes (mountain / forest / sandlands /
   icelands) and assert the mysterious variants have at least
   one VOID tile on the perimeter where a wall tile was dropped.
6. **Ruin assembler (surface layer)** — new
   `nhc/dungeon/sites/ruin.py` with 1–2 partial buildings in a
   broken enclosure, surface populator integration. Dispatcher
   entry `"ruin"`. Tests: entering a ruin hex lands on a surface
   with hostile creatures and a `stairs_down` tile on one
   building's ground floor.
7. **Ruin descent wiring** — hook the ruin's mandatory descent
   through the existing `_enter_building_descent` path with
   depth=3 and `procedural:ruin` template throughout. Tests:
   ascending from descent Floor 1 returns to the ruin surface;
   descending from surface stairs reaches all 3 floors; populator
   themes match the hex's faction.

Each commit stands alone and keeps the full test suite green;
taxonomy and tile art land first so later commits have clean
state to build on. Ruins are last because they depend on both
the biome matrix (step 3) and the site-descent infrastructure
already in place from the tower/keep work.

---

## 8. Open items / future work

- **Pack schemas beyond testland.** Only testland is wired today.
  When future packs land, they can declare `community` counts
  and biome feels (e.g. a "highlands" pack with more
  communities and no cities).
- **Temple redesign (M16).** Vertical open halls and
  multi-stair landings are still out of scope. The minimal
  temple here will be swapped at M16 without API churn.
- **Cottage NPC pool.** A v2 could roll a hermit (friendly) /
  witch (hostile) / abandoned (empty, but with loot) on cottage
  entry. Current plan is empty + door-crossing works; content
  comes later.
- **Biome-aware town assembler overrides beyond mountain.**
  Drylands ("adobe walls"), marsh ("stilted wood"), etc. could
  get their own tweaks when we have tile art and palette
  choices to back it up. Scope-deferred.
- **Mysterious temple flavour richness.** v1 tags sandlands /
  icelands temples with a partial-wall ruin aesthetic but keeps
  their priest / services / prices *identical* to mountain and
  forest temples (Q: "biome variants beyond town are cosmetic
  in v1"). A v2 could add biome-specific lore hooks (a cursed
  altar in the frozen variant, a buried relic in the sand
  variant), priest-variant creatures (hermit vs. full priest),
  or differentiated services via the narrative / rumor /
  creature-registry systems. The structural work is done; what
  remains is content.
- **Biome-tile tower gameplay variants.** Mountain-Tower (slot
  76) and forest watchtower (slot 54) are visual-only in v1 —
  same tower assembler, same floor count range, same shape
  pool. v2 could branch the tower assembler on biome (forest
  watchtower = mandatory 2-floor max with a wood-ceiling upper
  floor; mountain tower = stone-only) once those mechanics have
  content to support them.
- **Biome-specific ruin faction pools.** v1 ships every ruin
  with the shared Caves-of-Chaos humanoid pool (`goblin`,
  `orc`, `kobold`, `gnoll`, `bugbear`, `ogre`). v2 swaps this
  for biome-keyed pools per the Q&A (option b):

  | Biome       | Faction pool                            |
  |-------------|-----------------------------------------|
  | `forest`    | `{bandit, beast, cultist}`              |
  | `deadlands` | `{undead, cultist}`                     |
  | `marsh`     | `{lizardman, beast}`                    |
  | `sandlands` | `{gnoll, undead}`                       |
  | `icelands`  | `{frozen_dead, yeti, cultist}`          |

  Implementing v2 requires registering `lizardman`, `yeti`,
  `frozen_dead`, and `cultist` as creature factories if any
  are missing, plus wiring each biome→pool lookup into
  `place_dungeons` so the `DungeonRef.faction` is rolled from
  the right pool on placement.
- **Inhabited keeps.** The keep↔ruin contrast makes "keeps are
  inhabited" a design claim the implementation doesn't yet back
  up — keep surfaces today have zero NPCs. Follow-up: run the
  populator (or a specialised NPC table) on keep surfaces so
  guards / quartermasters / commanders appear. Same
  populator-on-surface hook the ruin assembler uses.
- **Ruin boss rooms.** The deepest floor of a ruin (Floor 3 of
  the descent) is a natural home for a themed boss encounter —
  undead champion in deadlands, giant spider in forest, desert
  djinn in sandlands, etc. v1 places creatures via the faction
  populator without a boss-room convention; v2 could tag one
  room on Floor 3 as `boss` and lean on the populator to place
  a leader unit.
- **Deprecating `_pick_village_size_class`.** Once COMMUNITY
  replaces hamlet-rolls for VILLAGE, this function can be
  deleted. The migration commit (#3 above) does that deletion
  in-place.
