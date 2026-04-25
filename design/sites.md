# Sites

A **site** is a player-walkable surface Level reached from the
flower view. Every flower-feature hex with a feature (sub-hex
minor or macro major, except CAVE / HOLE) leads to a site;
caves / holes lead straight into the dungeon system instead.

This document is the single source of truth for the site
subsystem: what counts as a site, how sites are assembled, how
they are dispatched, and how their state persists. It is
written for the post-M6 unified architecture; older shapes
("bespoke vs family", `enter_hex_feature` for sites, separate
`SubHexCacheManager`) are gone.

## What a site is

A site is any of:

- A walled or unwalled enclosure with **0, 1, or N buildings**
  on a single surface Level.
- Buildings are optional and tier-driven; the same mechanics
  govern a wayside well (zero buildings), a sub-hex farm (one
  small farmhouse), and a city (a dozen structures inside a
  palisade).
- The macro hex's "feature" is a *visual summary* of whatever
  site lives at the flower's `feature_cell`. The macro tile is
  not a separate place; it is a label pointing at the flower.

Sites live in `nhc/sites/`:

```
nhc/sites/
  _types.py         # SiteTier, SiteCacheManager keys, SubHexSite, SubHexPopulation
  _site.py          # Site dataclass, assemble_site dispatcher, paint_surface_doors helpers
  _placement.py     # Shared placement helpers (smallest leaf door, etc.)
  _shell.py         # Shared enclosure / wall stamping
  campsite.py       # assemble_campsite (sub-hex)
  clearing.py       # assemble_clearing (mushroom_ring / herb_patch / hollow_log / bone_pile)
  cottage.py        # assemble_cottage (macro)
  den.py            # assemble_den (animal_den / lair / nest / burrow)
  farm.py           # assemble_farm (sub-hex TINY + macro SMALL)
  graveyard.py      # assemble_graveyard + pick_undead_population
  keep.py           # assemble_keep (macro)
  mage_residence.py # assemble_mage_residence (macro)
  mansion.py        # assemble_mansion (macro)
  orchard.py        # assemble_orchard (sub-hex)
  ruin.py           # assemble_ruin (macro)
  sacred.py         # assemble_sacred (shrine / cairn / standing_stone / crystals / portal)
  temple.py         # assemble_temple (macro)
  tower.py          # assemble_tower (macro)
  town.py           # assemble_town (macro, hamlet / village / town / city size_classes)
  wayside.py        # assemble_wayside (well / signpost)
```

## Tiers

`SiteTier` is the canonical scale for a site's footprint. Five
values, each with a default dim in `SITE_TIER_DIMS`:

| tier   | dims    | typical kinds                                                |
|--------|---------|--------------------------------------------------------------|
| TINY   |  15×10  | wayside, clearing, sub-hex farm, cottage, ruin, tower, mage_residence |
| SMALL  |  30×22  | sacred (shrine / cairn / crystals), den, graveyard, campsite, orchard, macro farm, temple |
| MEDIUM |  48×44  | mansion, keep, town/hamlet                                   |
| LARGE  |  72×58  | town/village                                                 |
| HUGE   | 104×86  | town/city (and the middle "town" size_class)                 |

Each per-kind assembler keeps its own footprint table when the
generator has detail beyond a flat rectangle (e.g.
`FARM_*_BY_TIER` carries farmhouse + barn rects per tier). The
table dims should agree with `SITE_TIER_DIMS` for the same
tier — `tests/unit/sites/test_types.py` pins this contract.

Today most macros support exactly one tier; passing a different
tier raises `ValueError`. Adding a second tier is a one-line
extension of the kind's per-tier table.

## Dispatch pipeline

```
hex_session.hex_enter
       │
       ▼
resolve_sub_hex_entry(sub_cell)
       │
       ├─► ("non-enterable", reason)  ──► render rejection
       │
       ├─► ("dungeon", template)      ──► Game.enter_dungeon()
       │                                  (cellular Floor 1 + cluster)
       │
       └─► ("site", kind, tier)       ──► Game.enter_site(macro, sub, kind, tier,
                                                           feature=…, biome=…)
                                          │
                                          ├─► sub-hex kinds   ─► _enter_sub_hex_assembled
                                          │   (wayside, clearing, sacred, den,
                                          │    graveyard, campsite, orchard,
                                          │    farm at TINY)
                                          │
                                          └─► macro kinds     ─► _enter_walled_site
                                                                 _enter_tower_site
                                                                 _enter_mansion_site
                                                                 _enter_farm_site
```

### Resolver shape (`nhc/core/sub_hex_entry.py`)

`resolve_sub_hex_entry(sub_cell)` returns one of four values:

- `("site", kind, tier)` — every site (sub-hex or macro). Kind
  is the assembler key (e.g. `"wayside"`, `"keep"`, `"town"`);
  tier is a `SiteTier` enum value derived from per-kind tables
  or, for towns, from `sub_cell.dungeon.size_class`.
- `("dungeon", template)` — `CAVE` / `HOLE` macros. The caller
  routes to `Game.enter_dungeon()`; no surface site is built.
- `("non-enterable", reason)` — `LAKE` / `RIVER`.
- `None` — sub-hex is empty; "nothing to enter here."

The resolver is a pure function of the sub-hex's
`major_feature`, `minor_feature`, and (for towns) `dungeon`. It
reads from the *flower's* feature_cell sub-hex, not from the
macro `HexCell` — the data model is flower-primary.

### Dispatcher (`Game.enter_site`)

`Game.enter_site(macro, sub, kind, tier, *, feature=None,
biome=None)` is the single public entry point for sites. It
switches on `kind`:

- **Sub-hex kinds** (`wayside`, `clearing`, `sacred`, `den`,
  `graveyard`, `campsite`, `orchard`, plus `farm` when
  `tier is SiteTier.TINY`) flow through
  `_enter_sub_hex_assembled` — a shared helper that handles the
  cache check, fresh assemble, mutation replay, populator,
  player placement, and FOV.
- **Macro kinds** (`farm` at SMALL+, `tower`, `mansion`, `keep`,
  `town`, `temple`, `cottage`, `ruin`) flow through the
  pre-existing `_enter_*_site` helpers. M6c added the macro
  branches; M6d migrates their cache wiring onto
  `SiteCacheManager`.

Farm is the only ambiguous kind: TINY tier → sub-hex farm path,
SMALL tier → macro farm path. The legacy
`enter_sub_hex_family_site` shim coerces farm to TINY so older
test invocations land on the sub-hex path.

### Caves and holes (`Game.enter_dungeon`)

Caves and holes intentionally bypass the site layer. The
dispatcher routes them through `enter_dungeon`, which
generates a procedural cellular Floor 1 directly from the
macro hex's `DungeonRef`. Cave clusters share Floor 2 via
`_active_cave_cluster` — that mechanism is unchanged.

`enter_dungeon` is a thin alias of the legacy
`enter_hex_feature` method; the alias preserves the cave / hole
path while the production dispatcher in `hex_session.py` no
longer triggers `enter_hex_feature` for sites. The macro
routing inside `enter_hex_feature` is dead code reachable only
from direct test invocation; a future cleanup can prune it.

## Cache + mutation persistence

Every site surface lives on the `SiteCacheManager`
(`nhc/core/site_cache.py`):

- **In-memory LRU**: bounded at 32 entries. Promoting on access,
  evicting the oldest. Keeps memory proportional to "places the
  player has visited recently."
- **On-disk mutation log**: when an entry is evicted, its sparse
  mutation record (looted tiles, killed creatures, opened
  doors, dug walls) serialises to
  `<save_dir>/players/<pid>/sub_hex_cache/<key>.json`. Re-entry
  regenerates the layout from the deterministic seed and replays
  the persisted mutations.
- **Two key shapes**:
    - `("sub", macro_q, macro_r, sub_q, sub_r, depth)` — sub-hex
      sites; on-disk filename `<mq>_<mr>_<sq>_<sr>.json` (kept
      from the pre-M6d era so old saves still load).
    - `("site", q, r, depth)` — macro sites (M6d-3 owns the
      population of this key shape); on-disk filename
      `site_<q>_<r>.json`.

The on-disk subdirectory is named `sub_hex_cache` for back-compat
with pre-M6d saves; the manager class itself is the unified
`SiteCacheManager`.

Building floors (depth ≥ 2 inside a site's buildings), cave
Floor 1, shared cluster Floor 2, and building descents stay on
the unbounded in-memory `_floor_cache` — the dungeon system the
user kept separate from the site cache.

### Mutation handlers

The `_on_sub_hex_*` event handlers on `Game`
(`_on_sub_hex_creature_died`, `_on_sub_hex_item_picked`,
`_on_sub_hex_door_opened`, `_on_sub_hex_terrain_changed`)
record player-induced changes onto the active site's mutation
dict. They guard on `_active_site_sub is not None` today; M6d-3
extends the guard to also fire for macro sites once
`_active_site_macro` is wired up.

Replay on cache miss runs through
`_apply_sub_hex_mutations_to_level` (door / terrain) plus the
populator's mutation-aware re-spawn (looted / killed). The
populator (`nhc/core/sub_hex_populator.py::populate_sub_hex_site`)
is shared by every sub-hex assembler; macro entries can adopt
it once they migrate their populator-style spawning.

## Active markers and view classification

`Game` tracks "what site is the player in" through three fields:

- `_active_site: Site | None` — the assembled site dataclass.
  Set on entry to any site, cleared on exit. Used by
  `current_view`, `_is_site_edge_exit`, and
  `_leave_site_narration_key`.
- `_active_site_sub: HexCoord | None` — the sub-hex coord for a
  sub-hex site entry. Replaces the pre-M5 `_active_sub_hex`
  field. None for macro entries (until M6d-3 introduces
  `_active_site_macro` for the macro discriminator).
- `_active_descent_building` / `_active_descent_return_tile` /
  `_active_cave_cluster` — separate dungeon-system markers,
  unchanged by the site unification.

`Game.current_view()` (canonical implementation) now reads
purely from `_active_site` for the site classification —
M5 collapsed the legacy "_active_sub_hex" branch since every
site (sub-hex or macro) parks itself on `_active_site`.

See `design/views.md` for the full classification rules and the
five-view UX vocabulary.

## Data model: flower-primary

The macro's `cell.feature` and `cell.dungeon` are *derived from*
`flower.cells[feature_cell]`. The macro tile in the overland
hexmap is a visual summary of whichever site sits at the
flower's feature_cell.

Today (post-M6c) the data is *duplicated* — generators write
the feature + DungeonRef onto both the macro `HexCell` and the
flower's feature_cell sub-hex at generation time
(`nhc/hexcrawl/_flowers.py:833-844`). M6e turns
`HexCell.feature` and `HexCell.dungeon` into `@property`-derived
accessors that read from the feature_cell, completing the
flower-primary migration.

## How a sub-hex site is built (the canonical path)

The shared helper is `Game._enter_sub_hex_assembled` in
`nhc/core/game.py`. It runs:

1. Set active markers (`_active_site_sub = sub`, clear cluster
   / descent markers).
2. Compute cache key via `_cache_key(depth=1)` which returns
   the `("sub", ...)` shape for sub-hex entries.
3. Cache check — `_site_cache_manager.get(key)`. On hit:
   restore Level + active Site, place player, return.
4. Cache miss: derive seed via `dungeon_seed(seed, macro,
   template, sub=sub)`, instantiate per-kind RNG, call the
   per-kind `assemble_*` closure passing `feature` / `tier` /
   `biome` as needed.
5. Apply persisted mutations onto the freshly assembled
   surface; store in the LRU manager.
6. Build a `SubHexSite` shim and pass to
   `populate_sub_hex_site` so killed / looted / spawned
   entities round-trip correctly.
7. Place player on the canonical entry tile, recompute FOV,
   notify the renderer.

Each per-kind branch in `enter_site` provides:

- `seed_template` — string mixed into the deterministic seed.
- `site_id_suffix` — for the assembled Site's id.
- `assemble` — a `(site_id, rng) → Site` closure that calls the
  matching `assemble_*`.
- `feature_tags` — the tile-tag tuple `_find_feature_tile_on`
  scans for the centerpiece.
- `build_population` — optional `(rng, site, feature_xy) →
  SubHexPopulation` closure.
- `faction` — optional creature-faction override.

Macro kinds fall through to the legacy `_enter_*_site` helpers
today; once M6d-3 lands they will share the same pattern.

## What the player sees

End-to-end UX flow for entering a town:

1. Player on the macro map. Bumps a CITY hex → `hex_explore`
   transitions to the flower view, landing on the entry-edge
   sub-hex (or the cell the player crossed from on a prior
   visit, via `last_sub_hex_by_macro`).
2. Player is on the flower. Walks to the feature_cell (the
   sub-hex carrying the CITY tag), bumps `x` → `hex_enter`.
3. Resolver returns `("site", "town", SiteTier.HUGE)`. Dispatcher
   calls `Game.enter_site(macro, sub, "town", HUGE, …)`.
4. `enter_site` routes to `_enter_walled_site(macro, "town")`.
   Cache miss → `assemble_site("town", site_id, rng,
   size_class="city", biome=…)` builds a 104×86 town surface
   with palisade, multiple buildings, NPCs.
5. Player on the surface. Walks around, bumps a building door
   → `_active_site.building_doors[(x,y)]` looks up the building
   floor → engine swaps `Game.level` to the building's ground
   floor (`view = structure`). Stairs from there can lead to a
   descent dungeon (`view = dungeon`).
6. Player presses **L** on the surface → `_is_site_edge_exit` /
   `LeaveSiteAction` → `_exit_to_overland_sync` clears active
   markers, returns the player to the flower at the feature_cell.

For a sub-hex feature (e.g. WELL on a non-feature_cell sub-hex)
the flow is identical except the resolver returns
`("site", "wayside", SiteTier.TINY)` and `enter_site` routes
through `_enter_sub_hex_assembled`.

## Rough timeline

- **M1–M4f**: relocate sites under `nhc/sites/`; collapse the
  legacy sub-hex family generators onto per-kind assemblers
  (wayside, clearing, sacred, den, graveyard, campsite,
  orchard, sub-hex farm).
- **M5 / M5b** (`2054350`, `e32233a`): unified
  `_enter_sub_hex_assembled` helper; sub-hex farm surface
  migrated onto `SubHexCacheManager`.
- **M6a** (`45ff3c4`): `SiteTier` 3 → 5 values
  (TINY/SMALL/MEDIUM/LARGE/HUGE).
- **M6b** (`045aa6d`): every macro assembler accepts `tier`.
- **M6c** (`c68d9a9`): resolver returns `("site", kind, tier)` /
  `("dungeon", template)`; `enter_site` grew macro branches.
- **M6d-1 / M6d-2** (`e36855e`, `6148e0a`):
  `SubHexCacheManager` → `SiteCacheManager`; manager accepts
  `("sub", …)` and `("site", …)` keys.
- **M6d-3** (in progress): macro entries write their surface to
  `SiteCacheManager` with `_active_site_macro` discriminator.
- **M6e** (planned): flower-primary data migration; macro
  `cell.feature` / `cell.dungeon` become `@property`-derived.

The full handover plan for M6d-3 / M6d-4 / M6e lives at
`~/src/nhc_sites_unification_m6_remaining.md`.

## See also

- `design/views.md` — five-view UX vocabulary, `current_view`
  classification rules.
- `design/building_generator.md` — Building / Site primitives,
  per-kind assembler details (footprints, buildings, decoration).
- `design/biome_features.md` — biome-driven content per site
  kind (cottage / temple / ruin variants by biome).
- `design/overland_hexcrawl.md` — overland map, day clock,
  flower view mechanics.
- `nhc/sites/` — the assemblers themselves.
- `nhc/core/sub_hex_entry.py` — resolver.
- `nhc/core/site_cache.py` — `SiteCacheManager`.
- `nhc/core/game.py` — `enter_site`, `enter_dungeon`,
  `_enter_sub_hex_assembled`, the `_enter_*_site` macro helpers.
