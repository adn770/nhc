# Town / Settlement Generator

Design document for NHC's settlement (hamlet / village / town / city) layout
generator, and the proposed **BSP-neighbourhood redesign** of its
building-placement core.

The settlement assembler lives in `nhc/sites/town.py` (`assemble_town`),
with the layout helpers in `nhc/sites/_town_layout.py` and the street
network in `nhc/sites/_town_streets.py`. It produces a walled surface
`Level` (palisade enclosure) populated with buildings; building *interiors*
are a separate subsystem (`design/building_interiors.md`). See also
`design/sites.md` for how a settlement plugs into the unified site dispatch.

> STATUS: PROPOSED (2026-06-05). Sections 1–2 describe the current
> generator (status quo). Sections 3+ specify the redesign and the
> decisions to lock before implementation. Nothing here is built yet.

---

## 1. Current generator (status quo)

`assemble_town(site_id, rng, size_class, biome)` runs, in order:

1. **Roll the building roster.** `n_buildings = rng.randint(*config.building_count_range)`
   (city ≈ 36–44), then per-building **roles** (`_roll_role_slots` — service
   roles first: smithy, temple, inn, …; rest residential) and **sizes**
   (`_draw_size_for_role`).
2. **Cluster the roster** (`_cluster_pack` in `_town_layout.py`). Buildings
   are grouped into clusters of 1–4 with an **archetype** — `row`, `column`,
   `l_block`, `courtyard`, or `solo` — chosen from per-size-class weights
   (`CLUSTER_ARCHETYPE_WEIGHTS`). Target cluster count per tier is
   `CLUSTER_COUNT_RANGE` (city = 12–16). Each archetype lays its members in
   cluster-local coordinates (`_layout_row`/`_column`/`_l_block`/`_courtyard`).
3. **Place the clusters** (`_place_clusters` → `_try_place_plan`). For each
   cluster: 50 random origin attempts, then a **shuffled full-grid scan** of
   the interior, testing the cluster bbox (footprint + 1-tile buffer) for
   overlap against all placed + forbidden rects with a `CLUSTER_BBOX_GAP`
   street gap. On failure the archetype **demotes** one step
   (`_DEMOTE_NEXT`: courtyard → row → split-into-solos) and retries.
4. **Build the buildings** (`_place_buildings` → `_build_town_building` →
   `build_floors_with_stairs`) — each building gets ground + upper floors
   (`Level.create_empty` grids), interiors partitioned later.
5. **Build the surface** (`_build_town_surface`) — palisade shell, gates,
   grass/field/pavement, then the **street network**
   (`compute_town_street_network` → `_route_path`, an A* spine + side
   streets) and per-building door placement.

### 1.1 The performance problem

Profiling `assemble_site(city)` (≈153 ms dev M4 / ≈506 ms prod Broadwell)
after the 2026-06-05 cluster-packing index + `Tile` slots work:

- **Cluster placement is the largest cost.** The full-grid fallback scan
  (step 3) is ~34 % of `assemble_site` (≈51 ms dev / ≈170 ms prod). It proves
  "no fit" by visiting the whole interior cell-by-cell, and re-derives the
  free space from scratch for every cluster.
- **Street A\*** (`_route_path`) is ~15 %.
- **`create_empty`** (building-floor tile grids) is ~25 % (already slotted).

Two attempts at a localized fix were measured and rejected: a **strided
scan** demotes clusters into more solos and ends up *slower* (170 ms); a
**random-only** placement (no scan) is ~20 % faster but **drops 10–20 % of
buildings** (visibly sparser cities). The packing search is structurally the
wrong shape for the problem.

---

## 2. Why redesign instead of micro-optimise

The current pipeline is **bottom-up**: form clusters, then hunt for somewhere
to drop each one, constantly testing overlap. The redesign is **top-down**:
carve the interior into neighbourhood **plots** first, then build inside each.

This is the same BSP pattern the dungeon generator already uses
(`design/dungeon_generator.md` §1) and it changes the cost class:

- **Overlap testing disappears.** Plots are disjoint by construction, so the
  207k overlap checks, the full-grid scan, and any free-space bookkeeping all
  vanish. Placement becomes O(plots), no overlap tests at all.
- **Streets can fall out of the partition.** The gutters left at each BSP cut
  form a connected street grid for free, potentially subsuming the A* router.
- **Result is more town-like.** Blocks/neighbourhoods separated by streets is
  how real settlements read, versus today's random scatter.

Non-goal: byte-identical output. The owner has accepted a **new layout
look/distribution as the status quo**; fixtures are refreshed once. The
preserved invariant is *"a valid settlement of the same kind"* — same
size-class character (building count band, service roles, walled enclosure,
connected streets), different arrangement.

---

## 3. The BSP-neighbourhood model

### 3.1 Partition

Start with the interior rectangle (inside the palisade ring). Recursively
split:

- **Axis:** bias toward cutting the **longer** side (keeps plots from getting
  too elongated); `rng` breaks near-square ties.
- **Position:** a random cut in a central band (e.g. 35–65 % of the side) so
  plots vary in size but avoid slivers.
- **Gutter:** reserve a `STREET_GUTTER` width (1–2 tiles) at every cut. The
  two children are the sub-rectangles on either side of the gutter.
- **Recurse** on both children.

### 3.2 Stop conditions → leaves = neighbourhoods

Stop splitting a region when **any** holds:

- it is small enough for a single cluster's plot (≈ a max-cluster footprint +
  margin), or
- the target **leaf count** for the size class is reached (drives building
  count — see §3.5), or
- a further split would produce a child below the minimum plot size.

Each leaf is a **neighbourhood plot**. Leaf count ≈ cluster count
(`CLUSTER_COUNT_RANGE`).

### 3.3 Filling a plot

For each leaf, choose a cluster **archetype that fits the plot's shape**
rather than pre-forming clusters blindly:

- wide plot → `row`; tall plot → `column`; large square → `courtyard` or
  `l_block`; small plot → `solo`.
- Lay 1–4 buildings inside the plot with an interior margin, reusing the
  existing `_layout_*` helpers (now fed the plot dims).
- **Service-role anchoring** is preserved: distribute the rolled service
  roles one-per-plot first, residentials fill the rest (same intent as
  today's `_roll_role_slots`, applied per plot).

Because the cluster is sized to its own plot, it always fits — **no overlap
test, no demotion-to-solo cascade, no dropped buildings**.

### 3.4 Streets — DECISION (recommended: phased)

The gutters form a connected grid (every cut meets its parent's gutters).
Two end-states were considered; the recommendation is to **phase** them:

- **Phase A (ship first):** BSP does partition + placement only. Gutters are
  **reserved** as street corridors, but the existing `_town_streets` A* still
  routes/classifies streets and places doors *through* the reserved gutters.
  Lower risk, reuses proven street/door code, and already removes the ~34 %
  packing scan. Leaves the ~15 % A* cost.
- **Phase B (later):** gutters **become** the streets directly (mark gutter
  tiles `STREET`, place doors where a building edge meets a gutter), retiring
  most of the A* router and its ~15 %. Cleaner and more coherent, but touches
  street + door + surface-classification code.

Rationale: Phase A banks the big win at low risk and validates the partition
model in production; Phase B is a follow-up once the neighbourhood layout is
trusted.

### 3.5 Building count — DECISION (recommended: target-matched)

Keep the size-class character by **driving the partition from the rolled
target**, not letting count drift freely:

1. Roll `n_buildings` and the role/size roster as today.
2. Partition to a leaf count near the target cluster count
   (`CLUSTER_COUNT_RANGE`), using the stop conditions in §3.2.
3. **Reconcile:** distribute the roster across leaves (1–4 per plot). If
   there are more buildings than plots can hold at ≤4 each, split a large
   plot further; if fewer, leave some plots as gardens/empty or merge. The
   result lands in the size-class band, so cities stay ~36–44 buildings.

This preserves the "same kind of site" invariant (count + service mix) while
letting the *arrangement* be partition-driven.

### 3.6 Enclosure shapes

Town/city interiors are effectively rectangular (the palisade ring), so BSP
on a rectangle is clean. Any site kind with a non-rectangular interior would
clip plots against the enclosure polygon (drop/trim plots outside it). Out of
scope for the first cut — document if/when a non-rect settlement appears.

---

## 4. Determinism, fixtures, invariants

- **Deterministic per seed.** All BSP choices (axis, position, archetype,
  in-plot placement) draw from the site `rng`, so a seed reproduces its town.
  The output *changes* from the current generator (new status quo); it is
  stable thereafter.
- **Fixture refresh.** `seed7_town_surface`, `seed19_city_surface`, and the
  biome/site variants regenerate to the new layout (`regenerate_fixtures`),
  plus their WASM-canvas + PNG references. Byte-identity vs the old generator
  is explicitly *not* an invariant.
- **Preserved invariants** (asserted, not byte-checked):
  - building count within the size-class band (no dropped buildings),
  - every building reachable from a gate via streets (connectivity),
  - no two building footprints overlap,
  - service roles present per size class,
  - palisade encloses all plots.

---

## 5. Risks & validation

- **Plot-too-small for its roster** → handle by splitting/merging in §3.5
  reconciliation; never silently drop a building.
- **Street connectivity** (Phase A) — gutters must actually connect to gates;
  validated by the connectivity invariant test.
- **Over-elongated plots / slivers** — the central-band cut + min-plot stop
  condition guard against these; tune the band per size class.
- **Look regression** — a city must still read as a city; gate with a
  **visual render** of several seeds plus the structural invariants above.
- **Blast radius** — `_town_layout` placement core is rewritten; Phase A
  leaves `_town_streets` intact, Phase B rewrites it. Each phase is its own
  reviewed change with its own fixture refresh.

---

## 6. Decisions to lock before implementation

| # | decision | recommendation |
|---|----------|----------------|
| D1 | streets: gutters-as-streets vs keep A* | **phased** — A* via reserved gutters first, gutters-as-streets later (§3.4) |
| D2 | building count: emergent vs target-matched | **target-matched** (§3.5) |
| D3 | archetype selection | **fit to plot aspect ratio** (§3.3) |
| D4 | enclosure shapes | rectangular only for the first cut; clip later if needed |
| D5 | gutter width | 1–2 tiles (matches `CLUSTER_BBOX_GAP` street width); tune per size class |

---

## 7. Implementation phasing (proposed)

1. **BSP partitioner** (`_town_layout`): interior → leaf plots with reserved
   gutters; unit tests for disjointness, coverage, min-size, determinism.
2. **Plot fill**: archetype-to-plot fitting + service-role distribution;
   replaces `_cluster_pack`/`_place_clusters`. No-overlap + count invariants.
3. **Wire into `assemble_town`**; refresh fixtures (new status quo); structural
   site tests + visual render; profile `assemble_site(city)` (target: packing
   scan → ~0, assemble_site well under the current ~153 ms dev).
4. **Phase B (optional, later)**: gutters-as-streets, retire most of
   `_town_streets`; refresh fixtures again.

Each step is behaviour-changing (new layout) but gated on the §4 invariants +
a visual check, not byte-identity.
