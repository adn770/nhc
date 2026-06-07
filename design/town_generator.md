# Town / Settlement Generator

Design document for NHC's settlement (hamlet / village / town / city) layout
generator, and the **BSP-neighbourhood redesign** of its building-placement core.

The settlement assembler lives in `nhc/sites/town.py` (`assemble_town`), with the
layout helpers in `nhc/sites/_town_layout.py` and the street network in
`nhc/sites/_town_streets.py`. It produces a walled surface `Level` (palisade
enclosure) populated with buildings; building *interiors* are a separate subsystem
(`design/building_interiors.md`). See also `design/sites.md` for how a settlement
plugs into the unified site dispatch.

> STATUS: ACCEPTED (2026-06-06). Sections 1–2 describe the current generator
> (status quo). Sections 3+ specify the redesign; decisions D1–D10 are locked
> (§6), with gap-review fixes B1–B4 / S1–S7 / N1–N4 and interview answers Q1–Q6
> folded in. Nothing is built yet — this is the spec to implement against.

---

## 1. Current generator (status quo)

`assemble_town(site_id, rng, size_class, biome)` runs, in order:

1. **Roll the building roster.** `n_buildings = rng.randint(*config.building_count_range)`
   (city ≈ 40–48), then per-building **roles** (`_roll_role_slots` — service roles
   first: smithy/shop, temple, inn, …; rest residential) and **sizes**
   (`_draw_size_for_role`).
2. **Probe-pack + reserve the centerpiece.** A first `_cluster_pack` probe pass
   produces a rough cluster bbox set; `_compute_centerpiece_origin` picks a patch
   at the **centroid of that set, nudged toward the dominant gate**, and reserves
   it as a `forbidden_rect`. This is today's single, roughly-centred plaza.
3. **Cluster-pack around the centerpiece** (`_cluster_pack` in `_town_layout.py`).
   Buildings are grouped into clusters of 1–4 with an **archetype** — `row`,
   `column`, `l_block`, `courtyard`, or `solo` — chosen from per-size-class weights
   (`CLUSTER_ARCHETYPE_WEIGHTS`). Each archetype lays its members in cluster-local
   coordinates (`_layout_row`/`_column`/`_l_block`/`_courtyard`).
4. **Place the clusters** (`_place_clusters` → `_try_place_plan`). For each cluster:
   50 random origin attempts, then a **shuffled full-grid scan** of the interior,
   testing the cluster bbox (footprint + 1-tile buffer) for overlap against all
   placed + forbidden rects with a `CLUSTER_BBOX_GAP` street gap. On failure the
   archetype **demotes** one step (`_DEMOTE_NEXT`: courtyard → row →
   split-into-solos) and retries.
5. **Build the buildings** (`_place_buildings` → `_build_town_building` →
   `build_floors_with_stairs`) — each building gets ground + upper floors
   (`Level.create_empty` grids), interiors partitioned later.
6. **Build the surface** (`_build_town_surface`) — palisade shell, gates,
   grass/field/pavement, the **centerpiece stamp** (`_stamp_centerpiece` paves a
   cobblestone patch + drops the well/fountain feature), then the **street network**
   (`compute_town_street_network` → `_route_path`, an A\* spine + side streets) and
   per-building door placement.

### 1.1 The performance problem

Profiling `assemble_site(city)` (≈153 ms dev M4 / ≈506 ms prod Broadwell) after the
2026-06-05 cluster-packing index + `Tile` slots work:

- **Cluster placement is the largest cost.** The full-grid fallback scan (step 4) is
  ~34 % of `assemble_site` (≈51 ms dev / ≈170 ms prod). It proves "no fit" by
  visiting the whole interior cell-by-cell, and re-derives the free space from
  scratch for every cluster.
- **Street A\*** (`_route_path`) is ~15 %.
- **`create_empty`** (building-floor tile grids) is ~25 % (already slotted).

Two attempts at a localized fix were measured and rejected: a **strided scan**
demotes clusters into more solos and ends up *slower* (170 ms); a **random-only**
placement (no scan) is ~20 % faster but **drops 10–20 % of buildings** (visibly
sparser cities). The packing search is structurally the wrong shape for the problem.

---

## 2. Why redesign instead of micro-optimise

The current pipeline is **bottom-up**: form clusters globally, then hunt the whole
interior for somewhere to drop each one, constantly testing overlap. The redesign is
**top-down**: carve the interior into a few neighbourhood **plots** first, then fill
each plot independently. Packing still happens — but bounded to one plot's free
space (a few clusters), not the whole city — so the ~34 % scan shrinks dramatically
instead of re-scanning the full grid per cluster.

This is the same BSP pattern the dungeon generator already uses
(`design/dungeon_generator.md` §1). It changes the cost class and the look:

- **Overlap testing shrinks to per-plot.** No full-grid fallback scan, no global
  free-space bookkeeping. Each plot packs only its own handful of clusters.
- **Result is more town-like.** A few neighbourhoods separated by streets reads like
  a real settlement, versus today's random scatter.

**BSP is a placement accelerator, not a street generator.** The medieval, organic
street feel comes from the A\* router (kept — see §3.6), *not* from a rigid gutter
grid. The partition is deliberately **shallow** (a few cuts) so plots stay big and
irregular; deep partitioning would push the layout back toward a grid.

Non-goal: byte-identical output. The owner has accepted a **new layout
look/distribution as the status quo**; fixtures are refreshed once. The preserved
invariant is *"a valid settlement of the same kind"* — same size-class character
(building-count band, service roles, walled enclosure, connected streets), different
arrangement.

---

## 3. The BSP-neighbourhood model

### 3.1 Shallow partition (D2)

Start with the interior rectangle (inside the palisade ring). Recursively split, but
only a **few times** — the partition is coarse on purpose:

| Size class | Neighbourhoods (leaves) | BSP cuts | clusters/plot |
|------------|-------------------------|----------|---------------|
| Hamlet     | 1 (no split)            | 0        | all           |
| Village    | 2                       | 1        | a few         |
| Town       | 3–4                     | 2–3      | several       |
| City       | 4–6                     | 3–5      | several       |

**Leaf count = cuts + 1** — each split adds exactly one leaf, so the cut column is
just `leaves − 1`. The counts stay shallow on purpose; even a city's 3–5 cuts keep
plots big and irregular (vs the grid §2 warns about). Plazas are **not** leaves —
they are carved *out of* a leaf (§3.2), so the neighbourhood count above is the
**building-plot count** and plazas never starve the building budget.

A **hamlet skips BSP entirely** — one plot = the whole interior, filled by today's
packing path (but it still reserves + stamps its small plaza, §3.9). Each leaf at
the larger classes is a **neighbourhood** holding *several* clusters, not a single
one.

Split rules:

- **Axis:** bias toward cutting the **longer** side (keeps plots from getting too
  elongated); `rng` breaks near-square ties.
- **Position:** a random cut in a central band — **40–60 %** of the side (initial
  value, tune at Phase 4) — so plots vary in size but avoid slivers.
- **Gutter:** reserve a `STREET_GUTTER` width at every cut (§3.6). The two children
  are the sub-rectangles on either side of the gutter.
- **Stop** when the leaf count for the size class is reached, or a further split
  would produce a child below the **minimum plot size**. Min plot size is *semantic*,
  not a magic number: **one max-cluster footprint + a 2-tile margin** — a leaf must be
  able to hold at least one real cluster, or the "neighbourhood holds several clusters"
  premise breaks.

### 3.2 Plazas reserved as initial partitions — big & small tiers (D7)

Plazas are **first-class regions reserved during partition** — not a post-hoc
centroid patch like today's centerpiece. They come in **two distinct tiers** so a
settlement reads as a civic heart plus quieter neighbourhood corners:

| Size class | Big plazas | Small plazas |
|------------|------------|--------------|
| Hamlet     | 0          | 1            |
| Village    | 1          | 0            |
| Town       | 1          | 1            |
| City       | 1          | 2            |

**Big plaza — the civic / market heart.**
- **Fountain** centre (the grand feature), sized by site: **7×7** fountain for a
  village/town, **11×11** large fountain for a city.
- A **full cobblestone** paved square (`SurfaceType.STREET`).
- **Service-role magnet** (§3.4): market/shop, temple, and inn bias strongly into the
  plots touching it.
- **Street hub**: the A\* main spine (gate → centre) terminates here and side streets
  radiate out (§3.6).
- Reserved first, roughly toward the interior but still **off-centre** (rng-jittered).

**Small plaza — a neighbourhood pocket / well-square.**
- **Well** centre (the humble feature), tight **5×5** patch.
- A modest surround — paved collar with a grass/earth apron and often a single tree —
  *not* a full civic square; visually quieter than the big plaza.
- **Residential** character: little or no service-role bias; a lone craft (smithy)
  may sit beside it, but markets/temples gravitate to the big plaza.
- **Side-street access only** — touched by lanes, never the main spine.
- Tucked into a quarter or toward the edges (off-centre, rng-placed).

Shared mechanics:
- **Carved out of a leaf, not a leaf (B2).** A plaza is a **rect reserved inside a
  chosen neighbourhood plot** — a `forbidden_rect` the plot's packer arranges
  buildings around (exactly today's centerpiece-as-forbidden-rect mechanism, but
  scoped per-plot). It is *not* a separate BSP leaf, so it never reduces the
  building-plot count (§3.1). The big plaza is reserved in a central leaf; small
  plazas in edge leaves.
- **Off-centre, random.** Plaza positions are drawn from `rng`, *not* snapped to the
  interior centroid — the key break from `_compute_centerpiece_origin`'s
  centre-of-mass placement. Within its host leaf, the plaza rect is jittered, not
  centred.
- **Open patch.** The plaza rect holds no buildings; it is paved open space + the
  centre feature.
- **Reuses the stamp machinery.** Both tiers stamp via `_stamp_centerpiece` /
  `_centerpiece_feature_tag` (biome-driven circle/square/cross variants). Introduce
  two specs in place of the per-size `_CENTERPIECE_PER_SIZE`: a **big** spec
  (fountain, 7×7 village/town, 11×11 city) and a **small** spec (well, 5×5).
- **Village re-tier (B3, intentional).** Today `_CENTERPIECE_PER_SIZE` gives a village
  a **5×5 well**; the two-tier model promotes the village to a **7×7 fountain** big
  plaza. This is a deliberate change, not a fixture refresh:
  `test_town_centerpiece.py` (asserts village `well` / town `fountain`) is
  **rewritten**, not just regenerated. Hamlet keeps its 5×5 well (now a small plaza);
  town keeps its 7×7 fountain; city keeps 11×11.
- **Village auto-shrink fallback (Q6, deterministic).** A 7×7 fountain square is large
  for a village (2 leaves, 5–7 buildings). If reserving the full 7×7 would push the
  village below its count tolerance band, the big plaza **deterministically shrinks
  7×7 → 5×5**, *keeping the fountain feature* (still a "big" plaza, just tighter) — it
  never silently drops buildings to fit the square. This protects the count invariant
  per-seed rather than hoping every village has room.
- **Supersedes the single centerpiece.** `_compute_centerpiece_origin` (centroid +
  gate nudge) and the probe-pass `_cluster_pack` that fed it are retired; plaza
  origins come from the partition. The surface/street API's single `centerpiece_rect`
  becomes a `plaza_rects: list[Rect]` (one branch routed per plaza, §3.6).

### 3.3 Partition-first fill (D4, D3)

Each leaf is filled **independently** (no global cluster pool):

1. **Budget split — area-proportional (D8).** Distribute the rolled roster across
   plots in proportion to **packable plot area** — the leaf rect *minus* its plaza
   rect (if any) *minus* the internal `CLUSTER_BBOX_GAP` buffer (N4); the inter-plot
   gutter is outside the leaf and already excluded. Bigger plot → more buildings,
   yielding a couple of dense blocks and a couple of sparser ones.
2. **Roster per plot.** Service-role anchoring is applied **per plot** (same intent
   as today's `_roll_role_slots`, scoped to the plot's share).
3. **Archetype fits plot aspect (D3) — softly.** Bias cluster archetypes toward the
   plot's shape: wide plot → `row`; tall plot → `column`; large square → `courtyard`
   or `l_block`; small plot → `solo` (reuse the `_layout_*` helpers, fed plot dims).
   The bias is deliberately **gentle**: a strong "tall → column" pull stacks tall
   column *towers* that eat a narrow plot's whole height and strand the rest of its
   buildings. The real anti-tower lever is **small clusters** (≈1.8 buildings/cluster)
   — they never tower and pack denser, which is what keeps the city's worst-case
   count at the historical floor.
4. **Local pack.** Pack the plot's clusters into the plot's free space (plaza rect is
   a per-plot `forbidden_rect`) — a small, bounded search (a few clusters), not the
   whole interior.
5. **Spill pool on overflow (B4).** A plot that can't seat its full share — even
   after archetype **demotes to solos** — returns the un-placed members to a **global
   remainder pool**. A second pass places the remainder into any plot with leftover
   slack. Only a member that fits *nowhere* after the second pass is dropped — so the
   final count lands in the **size-class tolerance band** (the asserted invariant,
   §4), matching today's contract rather than a stricter "zero drops" guarantee.
   Per-plot packing strands slack in the wrong plots more than the old whole-interior
   scan, so the remainder pool is the mechanism that keeps cities from reading sparse.
   **Drop priority (Q4): residential-first; service roles are protected.** When the
   remainder still won't fit, a service **evicts placed residential clusters** (whole,
   smallest / purest-residential first; a mixed cluster's residentials are dropped and
   its services re-placed) and retries in the freed space until it seats. Each eviction
   drops ≥1 residential, so it terminates. Only if the town has **no residential left
   to sacrifice and still no gap** is a service dropped — astronomically rare (never
   observed across 460 seeds after tuning), and a dropped service is a soft degrade,
   not a crash. Losing the only smithy/temple/inn would weaken the "service roles
   present" read, so residentials always yield first (a city of 38 buildings reads
   fine; a city missing its temple does not).
6. **Slack → gardens/yards (D8).** Leftover interstitial space inside a plot fills
   with **gardens / kitchen plots / fenced yards** (biome-appropriate: fields in
   farmland, scrub in arid), reusing the surface non-built fill. Keeps blocks looking
   lived-in.

### 3.4 Service-role bias — the big plaza is the magnet (D5)

Service roles gravitate to the **big plaza**, not to every plaza equally: **softly**
bias market/shop, temple, and inn into the plots touching the big plaza (the
civic/market heart). **Small plazas stay residential** — at most a lone craft (a
smithy by a well), never the market or temple. "Softly" = a draw weighting, not a
hard rule, so towns aren't mechanically identical. In a city the single big plaza
concentrates the high-value services while the two small plazas anchor quiet
residential quarters — a clear centre-vs-edges read.

### 3.5 Building massing — centrality gradient (D10)

Building footprint is today purely role-driven (`_draw_size_for_role` draws from
`ARCHETYPE_CONFIG[role].size_range`, location-blind — a cottage by the market is the
same band as one at the rim). Add **plot centrality** as a massing axis layered on
top of the role band, so the town silhouette reads centre-to-edge:

- **Core** — plots touching/near the **big plaza**: skew the size draw **high** (grand
  merchant houses, halls, the inn looming over the market). Steepest pull.
- **Pocket** — plots touching a **small plaza**: a **mild** lift above baseline, so a
  well-square block reads a touch nicer than the bare rim.
- **Edge** — plots against the palisade with no adjacent plaza: **smallest, densest**
  cottages. Baseline / skewed low.

Mechanics:
- Each plot gets a **massing tier** from its proximity to a plaza: big-plaza-adjacent
  → core, else small-plaza-adjacent → pocket, else edge. The tier biases the draw
  **within the role's own `size_range`** (not by widening it): **core** = `max` of two
  `randint(*size_range)` draws (skews high), **pocket** = a single draw (neutral),
  **edge** = `min` of two draws (skews low). Because the value never leaves the role's
  native band, no role grows into another's size band (a core residential stays 7–9,
  never reaching the shop band) and plot-fit is guaranteed (value ≤ existing max) —
  the collision the literal `+k` skew would cause simply can't happen.
- **Massing only** — it does *not* move service roles (those still pull only to the
  big plaza, D5). A core residential house is just a bigger house, not a shop.
- **Skew applies to residential, and the test is residential-only (S3).** Service
  roles are *already* the largest buildings (`ARCHETYPE_CONFIG`: inn 13–16, temple
  14–16, shop 10–12 vs residential 7–9) and D5 already clusters them at the big
  plaza — so a naïve "mean footprint core > edge" check would pass *trivially* from
  service magnetism even if the residential skew did nothing. The D10 invariant test
  **filters to residential buildings** so it measures the gradient itself: mean
  residential footprint core > pocket > edge.
- Pairs with the area-proportional budget (D8): core plots trend
  **fewer-but-bigger**, edge plots **more-but-smaller** — the two axes reinforce
  rather than fight.
- Deterministic per seed (tier is a function of partition geometry; the size draw
  from the site `rng`).

### 3.6 Streets — keep A\*, gutters as soft preferences (D1)

**The A\* router stays.** BSP does *not* generate streets; gutters-as-streets is
explicitly **out of scope** (it produced a chaotic, non-medieval grid feel). The
router (`_town_streets`) **does change** in Phase 4 (cost-map plumbing below), so the
earlier "stays intact" note is corrected: its *algorithm* stays, its inputs grow.

- **Gutter width:** 2 tiles for town/city, 1 tile for village (wider streets read as
  more urban; a village wants tight lanes). Plazas, being open, widen the streets
  around them naturally.
- **Gutters are soft A\* preferences via a positive cost map (S1).** `_route_path`
  already takes an `extra_cost` dict, but it is *positive-only* (a penalty) and no
  caller builds one today. Implement the preference with **all-positive** costs to
  keep A\* admissible: raise the default tile cost (e.g. 1.0) and give **gutter tiles
  a lower cost** (e.g. 0.5) so the router prefers them but can still shortcut. New
  plumbing (Phase 4): partitioner emits the gutter tile set → `compute_town_street_
  network` builds the cost map → thread it through all four `_route_path` call sites
  (`connect_doors_to_street_network`, `_route_spine_paths`, `_route_centerpiece_
  branch`, `_route_branches`).
- **The gate→big-plaza spine stays HARD-routed (S2).** Connectivity is *guaranteed by
  construction* only if the spine is a real A\* path, not a soft preference — so the
  spine is routed hard (gate → big plaza), and gutter cost-preferences apply to **side
  streets only**. With **2 gates**, the spine is `gate0 → big-plaza → gate1` (plaza a
  mandatory waypoint); with 1 gate, `gate → big-plaza` (S7). Side streets then radiate
  from the plaza to each plot and small plaza.
- **Connectivity is a real flood-fill invariant (S2).** §4's "every building reachable
  from a gate" is asserted by a flood-fill from a gate over STREET tiles reaching every
  door — *not* by the existing "isolated STREET stub" fallback, which tolerates
  disconnection. The per-plot door connectors (`connect_doors_to_street_network`) plus
  the hard spine must leave a single connected STREET component.
- **Small plazas are reached by side streets only,** reinforcing their quieter,
  neighbourhood character and the non-grid feel.

### 3.7 Street router speed — graph-router behind a knob (D9)

Once the 34 % packing scan is gone, A\* (~15 %) is the next-largest cost. The gutters
form a connected **skeleton of corridor segments** meeting at junctions, which a
coarse **graph-router** can exploit instead of tile-level A\* across the whole
interior:

- **Nodes** = gutter junctions + gates + plaza centres + per-building door anchors.
- **Edges** = gutter segments between junctions, weighted by length.
- Build the network as a shortest-path tree / minimum spanning structure over that
  graph (gate→plaza spine, then connect each door to the nearest gutter), then
  **rasterise** the chosen segments to tiles.

This collapses the search space from ~(interior tiles) to ~(a few dozen junction
nodes), potentially turning the 15 % into noise.

**Look tradeoff (N2):** BSP gutters are axis-aligned straight cuts, so rasterising
graph segments yields **straighter, more grid-like streets** than tile-A\*'s wobble —
the opposite of the organic feel D1 protects. This is a genuine perf-vs-look tradeoff
to A/B, *not* a free win; the knob exists precisely to judge whether the speed is
worth the regularity.

**Phasing & knob (D9):** the graph-router ships as a **separate follow-up commit**,
*after* the BSP placement work lands and is trusted. Both routers live behind a
**config knob** (`STREET_ROUTER = "astar" | "graph"`) so we can A/B measure perf and
compare visual results. Default stays **`astar`** (proven) until the graph-router is
validated.

### 3.8 Enclosure shapes (D4)

Town/city interiors are effectively rectangular (the palisade ring), so BSP on a
rectangle is clean. Any site kind with a non-rectangular interior would clip plots
against the enclosure polygon (drop/trim plots outside it). Out of scope for the
first cut — document if/when a non-rect settlement appears.

### 3.9 Edge cases & special paths (S5, S6)

- **Hamlet (1 plot, 0 cuts).** Skips BSP splitting, but is **not** "today's path
  unchanged": it still reserves its **small plaza** as a `forbidden_rect` in the
  single plot, packs around it, stamps the well, and routes a branch to it. Same
  fill/stamp/street code as the larger classes, just with one plot and no cut.
- **Non-palisade sizes (mountain lodge: `suppress_palisade`) → single-plot (Q2).**
  With no enclosing wall, gutters between plots would read as random gaps rather than
  streets. So non-palisade sites **skip BSP** and use the single-plot path (shared
  with hamlets): one plot = the full buildable rect, plaza reserved + stamped inside
  it, today's whole-plot packing (no global-scan cost saved is small here — these
  sites are tiny). Reads as an organic cluster on open ground, not gridded
  neighbourhoods.
- **`skew_small` biome clamp.** `skew_small` clamps `n_buildings` to the lower half
  *before* the area-proportional split, so plots get **proportionally sparser**; the
  slack → gardens/fields fill (D8) absorbs the difference. No special-casing — the
  budget split just distributes a smaller roster.
- **City courtyard-pave pass vs small-plaza apron (S5, Q1) → protect.**
  `_pave_courtyard_post_pass` converts GARDEN/FIELD → PAVEMENT inside a city palisade,
  which would pave over a small plaza's grass/earth apron + tree (§3.2). **Locked: the
  pave pass excludes small-plaza apron tiles** (a protected-tile set threaded in) so a
  city's small plazas stay green wells — visibly humbler than the fountain square,
  preserving the tier distinction exactly where cities have the most small plazas.
- **`_find_feature_tile_on` ambiguity (dormant).** With multiple wells/fountains, the
  row-major "first feature tile" lookup is ambiguous. Towns currently route via
  `_enter_walled_macro_site` and do **not** call `near_feature` population, so this is
  *latent*, not active — noted so any future town `near_feature` NPC is aware.

### 3.10 Courtyard gardens — cities (post-placement)

The city pave pass (§3.9) leaves a stone expanse between buildings. Immediately after
it, `_scatter_courtyard_gardens` **complements** that pavement with garden patches so
the open plaza reads as greened, not a stone desert. Cities only — gated on
`config.paved_courtyard`; runs after building placement, before the FIELD vegetation
scatter.

- **Complement, not replace.** Greens a `GARDEN_COURTYARD_COVERAGE` (≈18%) fraction of
  the open `PAVEMENT` tiles as non-overlapping `GARDEN` patches; most of the courtyard
  stays paved.
- **Patch mix.** Patches are `GARDEN_PATCH_MIN..MAX` (3–5) tiles. `GARDEN_FORMAL_CHANCE`
  (≈half) makes a patch a **formal** flower bed (centre tree, corner bushes, flowers
  between); the rest are **informal** (trees / bushes scattered per
  `GARDEN_PATCH_TREE/BUSH_CHANCE`).
- **Grass framing.** Every patch reserves its 1-tile outer ring as plain green grass —
  vegetation only lands on the interior, so each tree / bush / flower reads on a green
  patch and no canopy spills onto the surrounding pavement. (`Terrain.GRASS` +
  `SurfaceType.GARDEN`, same as the small-plaza apron §3.2.)
- **Clearances.** `STREET` tiles, building doors + their 4-ring, protected small-plaza
  aprons, and courtyard-cluster **working yards** (Q7, kept paved) are never gardened.
  Patches also keep ≥`GARDEN_WALL_MARGIN` paved tiles clear of the palisade wall, and
  patch trees skip building-adjacent tiles (canopy/roof overlap, mirrors the FIELD
  scatter Q16 rule).

`GARDEN` is a separate surface region from `PAVEMENT`, so the city renders a dappled
green-and-stone courtyard rather than one flat plaza. Invariants: no `FIELD` survives
inside a city palisade (the pave pass converts it; gardens are `GARDEN`, not `FIELD`),
and city bushes may now sit on `GARDEN` as well as `FIELD`.

---

## 4. Determinism, fixtures, invariants

- **Deterministic per seed.** All BSP choices (axis, position, plaza placement,
  budget split, archetype, in-plot packing) draw from the site `rng`, so a seed
  reproduces its town. The output *changes* from the current generator (new status
  quo); it is stable thereafter.
- **rng-reorder is internal (S4).** Reordering the partition draws shifts *other*
  within-town rolls that share the same `rng` (building material wood/stone, descent
  crypt rolls, floor count, villager placement) — so the "new status quo" changes more
  than layout. But the per-site `rng` is **seeded independently of the global game
  rng**, so item identification, encounters, and other sites are unaffected. Any
  aggregate material/descent distribution tests refresh alongside the visual fixtures.
- **Fixture refresh.** `seed7_town_surface`, `seed19_city_surface`, and the
  biome/site variants regenerate to the new layout (`regenerate_fixtures`), plus
  their WASM-canvas + PNG references. Byte-identity vs the old generator is
  explicitly *not* an invariant. `test_town_centerpiece.py` is **rewritten** (village
  well → fountain, B3), not just regenerated.
- **Machine-checkable invariants** (asserted, not byte-checked):
  - building count within the **size-class tolerance band** (matching today's
    contract; the spill pool minimises drops but does not guarantee zero — B4),
  - every building reachable from a gate via streets — **flood-fill from a gate over
    STREET tiles reaches every door** (S2); the isolated-stub fallback does not satisfy
    this,
  - no two building footprints overlap,
  - service roles present per size class — the spill pool drops residential-first and
    **never drops a service role** (Q4); a service role that fits nowhere is a hard
    test error, not a silent drop,
  - palisade encloses all plots,
  - plaza tiers per size class — big (fountain): hamlet 0 / village 1 / town 1 /
    city 1; small (well): hamlet 1 / village 0 / town 1 / city 2 — big plazas carry a
    fountain on a full cobblestone square, small plazas a well on a 5×5 patch,
  - **residential** massing gradient: mean residential footprint core > pocket > edge
    (D10, service roles filtered out — S3).
- **Visual-only gates** (N1, *not* machine-asserted — eyeball at Phase 4): "reads as a
  city", the civic centre-vs-edges silhouette (D5/D10), street organicness. Kept
  separate so Phase 4's "structural tests green" criterion is never blocked on a
  subjective check.

---

## 5. Risks & validation

- **Plot-too-small for its roster** → handled by the spill pool: per-plot overflow →
  global remainder → second-pass placement into any plot with slack → demote-to-solos;
  a member that fits nowhere drops, keeping the count in the tolerance band (B4, §3.3).
- **Street connectivity** — the **hard-routed** gate→big-plaza spine (S2) plus the
  per-door connectors must form one connected STREET component; validated by the
  flood-fill connectivity invariant. Gutter soft-preferences alone do *not* guarantee
  connectivity.
- **Over-elongated plots / slivers** — the longer-side axis bias + central-band cut +
  min-plot stop condition guard against these; tune the band per size class.
- **Plaza placement off-screen / overlapping the palisade** — plaza rects are
  reserved inside their host leaf within the buildable bounds; assert they fit before
  stamping.
- **Big plaza crowding a small interior** — a 7×7 village fountain square eats a large
  share of a village's interior (only 2 leaves). Mitigated deterministically by the
  **auto-shrink fallback** (Q6, §3.2): the big plaza drops 7×7 → 5×5 (fountain kept) if
  the full square would break the count tolerance band. Still gate on the count
  invariant + a visual render.
- **Look regression** — a city must still read as a city; gate with a **visual
  render** of several seeds plus the structural invariants above.
- **Blast radius** — `_town_layout` placement core is rewritten; the centerpiece
  origin path + probe-pass `_cluster_pack` are replaced by plaza reservation;
  `_town_streets` keeps its A\* algorithm but gains the gutter cost-map plumbing
  (Phase 4, S1) — it is *not* untouched. The graph-router is a later, knob-gated
  commit. Each phase is its own reviewed change with its own fixture refresh.

---

## 6. Locked decisions

| #  | decision | resolution |
|----|----------|------------|
| D1 | streets: gutters-as-streets vs keep A\* | **keep A\*** — gutters are soft routing preferences, never the street grid; gutters-as-streets dropped (§3.6) |
| D2 | partition depth | **shallow** — leaves = cuts+1: hamlet 1 leaf / village 2 / town 3–4 / city 4–6; plazas are carved from leaves, not extra leaves; leaves are neighbourhoods holding several clusters (§3.1) |
| D3 | archetype selection | **fit to plot aspect ratio** (§3.3) |
| D4 | enclosure shapes | rectangular only for the first cut; clip later if needed (§3.8) |
| D5 | service-role placement | **soft bias toward plaza-adjacent plots** → civic hub + residential edges (§3.4) |
| D6 | pipeline order | **partition-first fill** — each plot rostered & packed independently (§3.3) |
| D7 | plazas | **two tiers, carved out of a leaf** (not extra leaves), off-centre/random. **Big** (fountain, civic/market hub, main-spine terminus): hamlet 0 / village 1 / town 1 / city 1; village re-tiered well→fountain (B3). **Small** (well, residential pocket, side-street): hamlet 1 / village 0 / town 1 / city 2. Supersedes single centerpiece (§3.2) |
| D8 | budget split + slack | **area-proportional** on packable area; slack → gardens/yards/fields; overflow → **spill pool → tolerance band** (minimise drops, not zero-guarantee — B4) (§3.3) |
| D9 | street router speed | **graph-router as a separate follow-up behind a `STREET_ROUTER` knob**; default `astar` until validated (§3.7) |
| D10 | building massing | **centrality gradient** — plot massing tier biases the size draw: core (big-plaza) grand, pocket (small-plaza) mild lift, edge (palisade) smallest; massing only, no service move (§3.5) |

---

## 7. Implementation phasing

1. **BSP partitioner** (`_town_layout`): interior → shallow leaf plots (leaves =
   cuts+1) with reserved gutters; **plaza rects carved out of chosen leaves** (big in a
   central leaf, small in edge leaves). Unit tests: partition-of-unity (every interior
   tile in exactly one of {plot, plaza, gutter} — N3), min-size, leaf-count-per-class,
   plaza-count-and-tier-per-class, off-centre plaza placement, determinism.
2. **Plot fill**: area-proportional budget on **packable area** (leaf − plaza −
   buffer, N4), archetype-to-plot fitting, per-plot service anchoring + big-plaza bias,
   **massing-tier size skew (D10: core/pocket/edge)**, local pack, **spill pool →
   tolerance band (B4)**, slack → gardens. Replaces `_cluster_pack`/`_place_clusters`
   global flow. Invariants: no-overlap, count-in-band, service-mix, **residential-only**
   massing gradient (S3).
3. **Plazas**: stamp the two tiers via `_stamp_centerpiece` at the reserved
   (off-centre) origins; introduce big/small specs, retire `_compute_centerpiece_
   origin` + the probe-pass `_cluster_pack`; surface/street API takes `plaza_rects:
   list`. **Rewrite** `test_town_centerpiece.py` (village well→fountain, B3). Exclude
   small-plaza apron from the city courtyard-pave pass (S5).
4. **Wire into `assemble_town`** + **street cost-map plumbing**: gutter set →
   positive cost map (default 1.0, gutters 0.5 — S1) threaded through all four
   `_route_path` call sites; **hard-route the gate→big-plaza spine** (gate0→plaza→gate1
   for 2 gates — S2/S7), soft preferences for side streets; one branch per plaza.
   Flood-fill connectivity invariant. Refresh fixtures (new status quo) + aggregate
   material/descent tests (S4); structural site tests + visual render; profile
   `assemble_site(city)` (target: packing scan → small per-plot cost, `assemble_site`
   well under the current ~153 ms dev).
5. **Graph-router (separate follow-up)**: add the `STREET_ROUTER` knob, implement
   the coarse gutter-junction graph + rasterise, A/B measure perf + visuals (note the
   grid-look tradeoff — N2), default `astar` until validated; refresh fixtures if/when
   switched.

Each step is behaviour-changing (new layout) but gated on the §4 invariants + a
visual check, not byte-identity.
