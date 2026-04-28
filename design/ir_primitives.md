# Floor IR — primitive determinism spec

The companion to `design/map_ir.md`. Where `map_ir.md` describes
the *shape* of the IR (FlatBuffers schema, op union, layer
ordering), this doc pins down the *behaviour* of each op:

- The exact RNG seed expression (offset from `base_seed`).
- The first few RNG calls in declaration order — the prefix the
  Rust port must reproduce to keep byte-equal SVG parity through
  Phase 1.
- Every Perlin call (`pnoise2(x, y, base=N)`) the op makes,
  with its base value.
- The SVG element shape one would see after the renderer runs
  (one example per op).
- Known discrepancies between code, design, and test fixtures.

This doc is the contract the Rust ports in
`crates/nhc-render/src/primitives/*` must honour. PRs that change
an RNG / Perlin sequence on the Python side MUST update the
corresponding section here in the same PR — that is what the
per-PR checklist in `CONTRIBUTING.md` and
`plans/nhc_ir_migration_plan.md` *Determinism discipline* gates
on.

The audit at `debug/floor_ir_emitter_audit.md` (gitignored, in
scratch) was the source of the call sequences below. Refresh it
when porting an op so the Rust author has a fresh source.

---

## 1. Conventions

- **`base_seed`**: the IR root's `FloorIR.base_seed: uint64`.
  Every op-level seed is derived from this so a single floor
  seed determines the entire floor.
- **`rng = random.Random(seed_expr)`**: the legacy Python
  pattern. The Rust port uses `SplitMix64::from_seed(seed_expr)`
  (see `crates/nhc-render/src/rng.rs`). The two streams are
  *not* numerically equivalent at the bit level — what matters
  is that the Rust port matches the Python *output strokes*
  byte-for-byte by replicating the `random.Random` algorithm
  via the `getrandbits`-equivalent state machine. The fixture
  parity gate (`tests/fixtures/floor_ir/`) is what verifies this.
- **`pnoise2(x, y, base=N)`**: the vendored shim at
  `nhc/rendering/_perlin.py`. The Rust port at
  `crates/nhc-render/src/perlin.rs` reads from
  `tests/fixtures/perlin/pnoise2_vectors.json` for its
  determinism contract.
- **First three RNG calls**: the documented prefix. The full
  call sequence per op can grow into the dozens; this doc keeps
  the prefix that diagnoses the *first* divergence point in a
  parity break.
- **SVG output shape**: one canonical example per op. Numerical
  attributes are abstracted as `...`; class names and structural
  elements are concrete.

---

## 2. Per-op contracts

### 2.1 ShadowOp

Layer 100. Drop-shadows for rooms (smooth + rect) and corridor
tiles. **No RNG, no Perlin.** Pure geometry pass.

- **Reference (Python):** `nhc/rendering/_shadows.py` —
  `_room_shadow_svg(room)`, `_render_corridor_shadows(svg, level)`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/shadow.rs` (Phase 4).
- **Seed:** none.
- **Perlin:** none.
- **SVG shape:**

  ```xml
  <!-- smooth-shape rooms -->
  <g transform="translate(3,3)">
    <path d="M..." fill="#000000" opacity="0.08"/>
  </g>
  <!-- rect rooms + corridor tiles -->
  <rect x="..." y="..." width="..." height="..."
        fill="#000000" opacity="0.08"/>
  ```

### 2.2 HatchOp

Layer 200. Three sub-kinds: Room (perimeter halo), Corridor,
Hole (interior cave hole). Each kind seeds independently from
`base_seed`.

- **Reference (Python):** `nhc/rendering/_hatching.py` —
  `_render_hatching` (Room), `_render_corridor_hatching`
  (Corridor), `_render_hole_hatching` (Hole).
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/hatch.rs` (Phase 4 — heaviest
  primitive, ports first).
- **Seed:**
  - `kind=Room`     → `random.Random(base_seed)`
  - `kind=Corridor` → `random.Random(base_seed + 7)`
  - `kind=Hole`     → `random.Random(base_seed + 777)`
- **First three RNG calls (Room):**
  1. `rng.choices([0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15])`
  2. `rng.uniform(0.15, 0.85)`
  3. `rng.uniform(2, CELL * 0.25)`
- **First three RNG calls (Corridor):** identical pattern with
  `weights=[0.5, 0.35, 0.15]` on the first call (one fewer
  bucket).
- **First three RNG calls (Hole):** identical to Room.
- **Perlin (Room + Corridor):**
  - `pnoise2(gx * 0.3, gy * 0.3, base=50)` — irregular contour.
  - `pnoise2(gx * 0.5, gy * 0.5, base=1)` — anchor X jitter.
  - `pnoise2(gx * 0.5, gy * 0.5, base=2)` — anchor Y jitter.
  - `pnoise2(p1[0] * 0.1, p1[1] * 0.1, base=10)` — wobble p1.x.
  - `pnoise2(p1[0] * 0.1, p1[1] * 0.1, base=11)` — wobble p1.y.
  - `pnoise2(p2[0] * 0.1, p2[1] * 0.1, base=12)` — wobble p2.x.
  - `pnoise2(p2[0] * 0.1, p2[1] * 0.1, base=13)` — wobble p2.y.
- **Perlin (Hole):** none in the Hole kind itself — the wobble
  is inherited from the perimeter pass.
- **SVG shape:**

  ```xml
  <defs><clipPath id="hatch-clip"><path d="..." clip-rule="evenodd"/></clipPath></defs>
  <g clip-path="url(#hatch-clip)">
    <g opacity="0.3"><rect x="..." y="..." width="32" height="32" fill="#D0D0D0"/></g>
    <g opacity="0.5"><line x1="..." y1="..." x2="..." y2="..."
                            stroke="#000000" stroke-linecap="round"/></g>
    <g><ellipse cx="..." cy="..." rx="..." ry="..."
                fill="#D0D0D0" stroke="#666666"/></g>
  </g>
  ```

- **Open issues:** Hole's `+777` offset is undocumented in the
  audit's design column; this doc canonicalises it.

### 2.3 WallsAndFloorsOp

Layer 300. Filled outlines + rect-room fills + corridor tiles +
cave region + combined wall-segment path. **No RNG, no Perlin.**
Structural geometry passes through unchanged.

- **Reference (Python):** `nhc/rendering/_walls_floors.py` —
  `_render_walls_and_floors`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/walls.rs` (Phase 4 — only
  stroke emission ports; structural geometry stays in Python
  per `map_ir.md` §8).
- **Seed:** none.
- **Perlin:** none.
- **SVG shape:**

  ```xml
  <path d="M..." fill="#FFFFFF" stroke="none"/>            <!-- smooth rooms -->
  <rect x="..." y="..." width="..." height="..."
        fill="#FFFFFF" stroke="none"/>                       <!-- rect rooms / corridors -->
  <path d="..." fill="#F5EBD8" stroke="none" fill-rule="evenodd"/>  <!-- cave region -->
  <path d="M... L... M... L..." fill="none"
        stroke="#000000" stroke-width="5.0"
        stroke-linecap="round" stroke-linejoin="round"/>     <!-- wall segments -->
  ```

### 2.4 TerrainTintOp

Layer 350. Per-tile colour rect tints (water/grass/lava/chasm) +
room-type washes. **No RNG, no Perlin.**

- **Reference (Python):** `nhc/rendering/_terrain_detail.py` —
  `_render_terrain_tints`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/terrain.rs` (Phase 4, with
  `TerrainDetailOp`).
- **Seed:** none.
- **Perlin:** none.
- **SVG shape:**

  ```xml
  <rect x="..." y="..." width="32" height="32"
        fill="#3F6E9A" opacity="0.30"/>                  <!-- per-tile tint -->
  <rect x="..." y="..." width="..." height="..."
        fill="#..." opacity="..."/>                        <!-- room-type wash -->
  ```

### 2.5 FloorGridOp

Layer 400. Wobbly grid (Perlin-displaced) at `cell`-tile spacing.

- **Reference (Python):** `nhc/rendering/_floor_detail.py:
  _render_floor_grid`, helper at
  `nhc/rendering/_svg_helpers.py:_wobbly_grid_seg`. Phase 3 left
  the helpers in place but unused on the IR path; Phase 4 / 7
  delete them.
- **Reference (Rust):** Phase 3 canary, **live** —
  `crates/nhc-render/src/primitives/floor_grid.rs`. The Python
  handler at `ir_to_svg.py:_draw_floor_grid_from_ir` calls into
  `nhc_render.draw_floor_grid` and only owns the SVG envelope
  (clip-path defs, `<path>` wrapping); the RNG-sensitive segment
  generator is Rust.
- **Seed:** `random.Random(41)` — **fixed constant, NOT
  base_seed-derived.** The IR emitter (Phase 1) sets
  `FloorGridOp.seed = 41` to keep parity with this. Future
  cleanup can promote to `base_seed + N` once a major schema
  bump is on the table. Rust uses `python_random::PyRandom` (a
  byte-compat reproduction of CPython's `random.Random`) so the
  MT19937 stream replays identically.
- **First three RNG calls (per segment, via `_wobbly_grid_seg`):**
  1. `rng.randint(1, n_sub - 1)` — sub-segment break.
  2. `rng.random() < 0.25` — break-vs-continue gate.
  3. `rng.randint(1, n_sub - 1)` — next segment break.
- **Perlin:**
  - `pnoise2(noise_x + t * 0.5, noise_y, base=20)` — right-edge
    grid wobble (or `base=24` for bottom edge).
  - `pnoise2(noise_x + t * 0.5, noise_y, base=base+4)` —
    Python computes this companion sample and then overwrites it
    in both branches. Perlin is pure, so the Rust port omits the
    discarded sample without affecting output. If a Phase 4
    cleanup ever uses the second sample, this contract changes.
- **SVG shape:**

  ```xml
  <path d="M... L... M... L..." fill="none" stroke="#000000"
        stroke-width="0.3" opacity="0.7" stroke-linecap="round"
        clip-path="url(#grid-clip)"/>                  <!-- room grid -->
  <path d="M... L... M... L..." fill="none" stroke="#000000"
        stroke-width="0.3" opacity="0.7" stroke-linecap="round"/>  <!-- corridor -->
  ```

- **Open issue:** Theme-scaled grid (`scale: float` in the FB
  table, per-theme value from `_DETAIL_SCALE`) is encoded in the
  schema but the legacy code applies the scale only at the
  Perlin-multiplier site — i.e. theme variation is implicit via
  the cell layout, not via a free scale parameter. The Phase 3
  Rust port should preserve the implicit behaviour and ignore
  `FloorGridOp.scale` until a Phase 4 cleanup makes the
  parameter explicit.

### 2.6 FloorDetailOp

Layer 500a. Per-tile cracks, scratches, stones, clusters.

- **Reference (Python):** `nhc/rendering/_floor_detail.py` —
  `_render_floor_detail`, `_tile_detail`, `_floor_stone`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/floor_detail.rs` (Phase 4,
  second-heaviest primitive).
- **Seed:** `random.Random(base_seed + 99)`.
- **First three RNG calls (per tile, via `_tile_detail`):**
  1. `rng.random()` — gates the crack roll.
  2. `rng.randint(0, 3)` — corner pick for cracks.
  3. `rng.uniform(CELL * 0.15, CELL * 0.4)` — stroke length.
- **Perlin:** none.
- **Per-tile probabilities:** crack 0.08 (0.32 cave) × theme
  scale; scratch 0.05 (0.01); stone 0.06 (0.10); cluster 0.03
  (0.06). Theme scale lives in `_DETAIL_SCALE` keyed on theme
  name.
- **SVG shape:**

  ```xml
  <g opacity="0.5">                                  <!-- crack -->
    <line x1="..." y1="..." x2="..." y2="..."
          stroke="#000000" stroke-width="0.5" stroke-linecap="round"/>
  </g>
  <g opacity="0.8">                                  <!-- stone -->
    <ellipse cx="..." cy="..." rx="..." ry="..."
             fill="#E8D5B8" stroke="#666666"/>
  </g>
  <g class="y-scratch" opacity="0.45">               <!-- scratch -->
    <path d="..." fill="none" stroke="#000000" stroke-linecap="round"/>
  </g>
  ```

### 2.7 ThematicDetailOp

Layer 500b. Per-tile webs, bone piles, skulls.

- **Reference (Python):** `nhc/rendering/_floor_detail.py` —
  `_tile_thematic_detail`, `_web_detail`, `_bone_detail`,
  `_skull_detail`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/floor_detail.rs` (shares
  module with `FloorDetailOp` because the two share the seed —
  see open issue below).
- **Seed:** `random.Random(base_seed + 99)` — **same as
  FloorDetailOp.** The two share an RNG stream.
- **First three RNG calls (per tile, via
  `_tile_thematic_detail`):**
  1. `rng.random() < probs.get("web", 0)` — web roll.
  2. `rng.choice(wall_corners)` — anchor pick (web prefers
     wall-corner tiles).
  3. `rng.random() < probs.get("bones", 0)` — bones roll.
- **Per-theme probabilities:** stored in
  `_THEMATIC_DETAIL_PROBS`, keyed by theme. Crypt has high web +
  high bones; cave has medium webs; dungeon defaults are low.
- **Perlin:** none.
- **SVG shape:**

  ```xml
  <g class="detail-webs"><path d="..." stroke="#000000"
                                stroke-linecap="round" opacity="0.35"/></g>
  <g class="detail-bones"><g opacity="0.4"><line/><ellipse/></g></g>
  <g class="detail-skulls"><g opacity="0.45"><path/><ellipse/></g></g>
  ```

- **Open issue:** Design intent (`map_ir.md` §7.7) calls for
  `+199` to give thematic detail its own RNG stream; the legacy
  code reuses `+99` so the two streams are entangled. Phase 4
  Rust port preserves the legacy behaviour for parity. The
  reconciliation is a separate decision tied to a major schema
  bump.

### 2.8 TerrainDetailOp

Layer 600. Per-tile water ripples, lava cracks, chasm hatch.
Grass-blade emission was dropped (commit `35660d6`); grass shows
only the flat `TerrainTintOp` tint.

- **Reference (Python):** `nhc/rendering/_terrain_detail.py` —
  `_render_terrain_detail`, `_water_detail`, `_lava_detail`,
  `_chasm_detail`.
- **Reference (Rust):** TBD — same module as the tints in
  Phase 4.
- **Seed:** `random.Random(base_seed + 200)` — derived inside
  the decorator pipeline.
- **First three RNG calls (water):**
  1. `rng.randint(2, 3)` — `n_waves`.
  2. `rng.uniform(-CELL * 0.06, CELL * 0.06)` — y jitter.
  3. `rng.uniform(0.4, 0.8)` — stroke width.
- **Perlin:** none.
- **SVG shape:**

  ```xml
  <g class="terrain-water" opacity="0.5"
     stroke="#3F6E9A" stroke-linecap="round">
    <path d="M... L..." fill="none"/>
  </g>
  <g class="terrain-lava" opacity="0.5" stroke-linecap="round">
    <line x1="..." y1="..." x2="..." y2="..."/>
    <circle cx="..." cy="..." r="..." fill="#000000"
            opacity="0.4"/>
  </g>
  <g class="terrain-chasm" opacity="0.5"
     stroke="#000000" stroke-linecap="round">
    <line x1="..." y1="..." x2="..." y2="..."/>
  </g>
  ```

### 2.9 StairsOp

Layer 700. Tapering wedges + per-direction step lines + optional
cave fill (when `theme == "cave"`). **No RNG, no Perlin.**

- **Reference (Python):** `nhc/rendering/_stairs_svg.py` —
  `_render_stairs`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/stairs.rs` (Phase 4 —
  small port).
- **Seed:** none.
- **Perlin:** none.
- **SVG shape:**

  ```xml
  <polygon points="..." fill="#E0E0E0" stroke="none"/>  <!-- cave fill -->
  <line x1="..." y1="..." x2="..." y2="..."
        stroke="#000000" stroke-width="1.5"
        stroke-linecap="round"/>                          <!-- top rail -->
  <line x1="..." y1="..." x2="..." y2="..."
        stroke="#000000" stroke-width="1.0"
        stroke-linecap="round"/>                          <!-- step line -->
  ```

### 2.10 CobblestoneOp

Layer 500c. Five cobblestone variants — only four implemented
today (`Cobble`, `Brick`, `Flagstone`, `OpusReticulatum`);
`Herringbone` and `Versailles4` are forward-compat in the
`CobblePattern` enum.

- **Reference (Python):** `nhc/rendering/_floor_detail.py` —
  `_cobblestone_paint`, `_brick_paint`, `_flagstone_paint`,
  `_opus_romano_paint`, all wired through `walk_and_paint` in
  `_decorators.py`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/cobblestone.rs` (Phase 4 —
  single module covering all variants).
- **Seed:** `random.Random(base_seed + 333)` — set by the
  decorator pipeline.
- **First three RNG calls (Cobble 3×3):**
  1. `rng.uniform(-cw * 0.1, cw * 0.1)` — jx.
  2. `rng.uniform(-ch * 0.1, ch * 0.1)` — jy.
  3. `rng.uniform(-cw * 0.08, cw * 0.08)` — jw.
- **First three RNG calls (Brick 4×2):**
  1. `rng.uniform(-bw * 0.06, bw * 0.06)` — jx.
  2. `rng.uniform(-bh * 0.06, bh * 0.06)` — jy.
  3. `rng.uniform(-bw * 0.06, bw * 0.06)` — jw.
- **First three RNG calls (Flagstone 2×2):**
  1. `rng.uniform(-half * 0.07, half * 0.07)` × 3 (different
     pentagon vertices).
- **OpusReticulatum:** deterministic; rotation derived from tile
  grid coordinates, no RNG.
- **Perlin:** none.
- **SVG shape (representative):**

  ```xml
  <rect x="..." y="..." width="..." height="..." rx="1"/>
  ```

  Per-variant ` rx ` differs (1.0 for cobble, 0.5 for brick, 0.4
  for opus); flagstone is `<polygon points="..."/>`.

### 2.11 WoodFloorOp

Layer 500d. Wood-grain plank fill, gated on
`flags.interior_finish == "wood"`. Clipped to `building_polygon`
when present so planks reach the chamfer diagonal.

- **Reference (Python):** `nhc/rendering/_floor_detail.py` —
  `_render_wood_floor`, `_parquet_seams_for_room`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/wood_floor.rs` (Phase 4).
- **Seed:** Inherited from `_render_floor_detail`'s
  `base_seed + 99` stream (continues consuming after
  FloorDetailOp + ThematicDetailOp).
- **First three RNG calls (within a parquet pass):**
  1. `rng.uniform(-0.1, 0.1)` — seam jitter.
  2. `rng.uniform(...)` — grain position jitter.
  3. continuation of parquet geometry.
- **Perlin:** none.
- **SVG shape:**

  ```xml
  <rect x="..." y="..." width="..." height="..." fill="#B58B5A"
        clip-path="url(#wood-bldg-clip)"/>
  <g opacity="0.35" stroke="#C4A076" stroke-width="0.4">
    <path d="..."/>                                     <!-- light grain -->
  </g>
  <g opacity="0.35" stroke="#8F6540" stroke-width="0.4">
    <path d="..."/>                                     <!-- dark grain -->
  </g>
  <g fill="none" stroke="#8A5A2A" stroke-width="0.8">
    <path d="M... L... M... L..."/>                     <!-- parquet seams -->
  </g>
  ```

### 2.12 GardenOverlayOp / FieldOverlayOp

Layer 500e (surface overlays). Garden currently emits only the
flat tint (commit `4499326` dropped the decorator); Field emits
scattered stones via `FIELD_STONE`.

- **Reference (Python):** `nhc/rendering/_floor_detail.py` —
  `_field_stone_paint` for Field. Garden has no decorator today.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/overlays.rs`.
- **Seed:** Decorator-pipeline derived; exact offset undocumented
  (audit flagged this as an open issue).
- **First three RNG calls (Field stone):**
  1. `rng.random() >= FIELD_STONE_PROBABILITY` (0.10).
  2. `rng.uniform(CELL * 0.2, CELL * 0.8)` — cx.
  3. `rng.uniform(CELL * 0.2, CELL * 0.8)` — cy.
- **Perlin:** none.
- **SVG shape (Field stone):**

  ```xml
  <ellipse cx="..." cy="..." rx="..." ry="..."
           fill="#8A9A6A" stroke="#4A5A3A" stroke-width="0.5"/>
  ```

- **Open issue:** the FB schema includes both ops as full tables,
  but `GardenOverlayOp` will not be emitted by Phase 1 until
  garden gains a decorator (or the schema removes the op at a
  major bump). The schema-emit-but-do-not-render behaviour is
  forward-compat noise the Phase 1 emitter will skip.

### 2.13 CartTracksOp / OreDepositsOp

Layer 500f (surface overlays). Decorator-driven; the audit ran
out of file budget before the helper bodies but the layer
pipeline references them explicitly.

- **Reference (Python):** `nhc/rendering/_floor_detail.py` —
  `CART_TRACK_RAILS`, `CART_TRACK_TIES`, `ORE_DEPOSIT` decorators
  registered in the layer pipeline (~line 710–720).
- **Reference (Rust):** TBD — Phase 4 (small ports).
- **Seed:** Decorator-pipeline derived; exact offset undocumented.
- **First three RNG calls / Perlin:** TBD — fill in when porting.
- **SVG shape:** TBD — fill in when porting.

### 2.14 TreeFeatureOp / BushFeatureOp

Layer 800. Cartographer-style vegetation. Trees: layered canopy
with per-tile hue jitter + grove merging (Shapely union for 3+
adjacent trees, baked into `groves: [GrovePolygon]` so the Rust
renderer does no Shapely work). Bushes: smaller canopy, no trunk.

- **Reference (Python):** `nhc/rendering/_features_svg.py` —
  `TREE_FEATURE`, `BUSH_FEATURE`, `_connected_tree_groves`,
  `_grove_fragment`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/vegetation.rs` (Phase 4).
- **Seed:** Decorator-pipeline derived; the per-tile seed
  derives from `(tx, ty)` — vegetation is positionally
  deterministic, not seed-derived. The same (tx, ty) always gets
  the same canopy.
- **First three RNG calls / Perlin:** TBD — fill in when porting.
- **SVG shape:** layered canopy strokes; document during port.

### 2.15 WellFeatureOp / FountainFeatureOp

Layer 800. Wells in two shapes (Round, Square); fountains in
five (Round, Square, LargeRound, LargeSquare, Cross). Per-tile
seeded rolls drive stone-shape jitter.

- **Reference (Python):** `nhc/rendering/_features_svg.py` —
  `WELL_FEATURE`, `WELL_SQUARE_FEATURE`, `FOUNTAIN_FEATURE`,
  `FOUNTAIN_SQUARE_FEATURE`, `FOUNTAIN_LARGE_FEATURE`,
  `FOUNTAIN_LARGE_SQUARE_FEATURE`, `FOUNTAIN_CROSS_FEATURE`.
- **Reference (Rust):** TBD —
  `crates/nhc-render/src/primitives/{well,fountain}.rs`
  (Phase 4).
- **Seed:** Deterministic by `(tx, ty)` — same pattern as
  vegetation. The per-tile seeded rolls vary stone-shape jitter
  but the input is positional, not RNG-streamed.
- **First three RNG calls / Perlin:** TBD per variant — fill in
  during port.
- **SVG shape (round well):**

  ```xml
  <g id="well-{tx}-{ty}" class="well-feature" stroke-linejoin="round">
    <circle cx="..." cy="..." r="..." fill="none" stroke="#000000"/>
    <path class="well-keystone" d="..." fill="#EFE4D2" stroke="#000000"/>
    <circle class="well-water" cx="..." cy="..." r="..."
            fill="#3F6E9A" stroke="#22466B"/>
    <path class="well-water-movement" d="..." fill="none"
          stroke="#FFFFFF" stroke-dasharray="2 2"/>
  </g>
  ```

### 2.16 GenericProceduralOp (escape hatch)

For new primitives that haven't yet earned a dedicated table.
`(name: string, tiles, seed, params: [KV])`. Renderers dispatch
on `name` to a registered handler. Use sparingly — promote to a
real op + bump the major schema once the primitive stabilises.

---

## 3. RNG offset registry

Single-source-of-truth for "what offset does this op derive from
`base_seed`?" When porting an op or adding a new one, update this
table in the same PR.

| Op                  | Seed expression          | Source     |
|---------------------|--------------------------|------------|
| ShadowOp            | (none)                   | n/a        |
| HatchOp.Room        | `base_seed`              | code       |
| HatchOp.Corridor    | `base_seed + 7`          | code       |
| HatchOp.Hole        | `base_seed + 777`        | code       |
| WallsAndFloorsOp    | (none)                   | n/a        |
| TerrainTintOp       | (none)                   | n/a        |
| FloorGridOp         | `41` (constant)          | code       |
| FloorDetailOp       | `base_seed + 99`         | code       |
| ThematicDetailOp    | `base_seed + 99` (shared)| code       |
| TerrainDetailOp     | `base_seed + 200`        | code       |
| StairsOp            | (none)                   | n/a        |
| CobblestoneOp       | `base_seed + 333`        | decorator  |
| WoodFloorOp         | `base_seed + 99` (shared with FloorDetail) | inherited  |
| GardenOverlayOp     | TBD — port to fill       | decorator  |
| FieldOverlayOp      | TBD — port to fill       | decorator  |
| CartTracksOp        | TBD — port to fill       | decorator  |
| OreDepositsOp       | TBD — port to fill       | decorator  |
| TreeFeatureOp       | derived from (tx, ty)    | positional |
| BushFeatureOp       | derived from (tx, ty)    | positional |
| WellFeatureOp       | derived from (tx, ty)    | positional |
| FountainFeatureOp   | derived from (tx, ty)    | positional |

**Reserved offsets** (do not use for new ops without a major
schema bump): `0, 7, 41, 99, 199, 200, 333, 777`. Pick a fresh
prime not already in this column for new primitives.

---

## 4. Perlin base registry

Single-source-of-truth for "what `pnoise2(..., base=N)` calls
exist?" The fixture at
`tests/fixtures/perlin/pnoise2_vectors.json` covers every base in
this table; adding a new base means bumping `_BASES` in
`tests/samples/regenerate_perlin_vectors.py` and regenerating.

| Base | Op             | Purpose                              | Spatial scale |
|------|----------------|--------------------------------------|---------------|
| 1    | HatchOp        | anchor X jitter                      | `gx * 0.5`    |
| 2    | HatchOp        | anchor Y jitter                      | `gy * 0.5`    |
| 10   | HatchOp        | line wobble — p1.x                   | `p[0] * 0.1`  |
| 11   | HatchOp        | line wobble — p1.y                   | `p[1] * 0.1`  |
| 12   | HatchOp        | line wobble — p2.x                   | `p[0] * 0.1`  |
| 13   | HatchOp        | line wobble — p2.y                   | `p[1] * 0.1`  |
| 20   | FloorGridOp    | right-edge grid wobble               | varied        |
| 24   | FloorGridOp    | bottom-edge grid wobble              | varied        |
| 24+4 | FloorGridOp    | second sample paired with `base=24`  | varied        |
| 50   | HatchOp        | irregular contour                    | `g * 0.3`     |
| 77   | (helpers)      | y-scratch wobble                     | `m * 0.15`    |

**Reserved bases**: `0, 1, 2, 10–13, 20, 24, 50, 77`. Pick a
fresh integer not already in this column for new Perlin samples.

---

## 5. SVG output conventions

Cross-cutting attributes a renderer emits the same way for every
op:

- Stroke colours are 6-digit lowercase hex (`#000000`,
  `#3f6e9a`).
- `stroke-linecap="round"` is the default for hand-drawn-style
  emitters; `stroke-linejoin="round"` ditto for filled paths.
- Numeric attributes are rendered with up to 3 decimals; the
  renderer trims trailing zeros (`0.50` → `0.5`). The Rust port
  must replicate this trimming for byte-equal parity.
- Class names are stable: `terrain-water`, `terrain-lava`,
  `terrain-chasm`, `detail-webs`, `detail-bones`, `detail-skulls`,
  `well-feature`, `y-scratch`, `well-keystone`,
  `well-water`, `well-water-movement`. The web client and
  /admin tooling key off these.

---

## 6. Open issues — tracked, not blocking

These deferred questions don't block Phase 1 (every op above
has a working Python implementation that the IR emitter can
consume), but they will need decisions before a major schema
bump.

1. **Hole hatching's `+777` offset** vs design's silence — Phase 1
   commits to `+777`; document is now canonical.
2. **Floor grid's fixed seed `41`** vs design's
   `seed: uint64`-flavoured field — Phase 1 commits to the
   constant; see §2.5 open issue.
3. **Thematic detail sharing FloorDetail's `+99` offset** instead
   of design's `+199` — Phase 1 commits to the shared offset for
   parity; future major bump may split.
4. **Garden has no decorator** — `GardenOverlayOp` is forward-
   compat schema noise; the Phase 1 emitter omits it.
5. **Cobblestone variants** — design lists 5 (`Cobble`, `Brick`,
   `Flagstone`, `OpusReticulatum`, `Herringbone`, `Versailles4`);
   only 4 implemented today. The schema enum has all 6 (with
   `Cobble` for the 3x3 default); `Herringbone` and `Versailles4`
   will not be emitted until Phase 4 implements them.
6. **Decorator-pipeline seeding** is implicit in
   `_decorators.py:walk_and_paint`. Promoting offsets to explicit
   per-op constants would help readability — defer to the Rust
   port.

---

## 7. Rust port methodology — Phase 3+ recipe

The Phase 3 canary (`floor_grid`) settled the per-primitive
shape that Phase 4 follows verbatim. The bar each port has to
clear is **byte-equal SVG output across every committed
parity fixture** — there is no ULP tolerance, no "close enough"
mode, no parity-gate relaxation. The recipe:

### 7.1 Pre-flight: own the determinism contract first

Before any Rust file is touched, the relevant entries in §2 / §3
/ §4 / §5 of this document must be honest. If a discrepancy is
discovered while reading the Python source, file it under §6
and reconcile *before* porting — porting against an inaccurate
contract bakes the inaccuracy into the canonical Rust source.

For each primitive about to port, audit:

- Every `random.Random(...)` call site reachable from the Python
  helper. The seed source (`base_seed + N`, fixed constant, or
  derived) and the per-call sequence both go in §2. The first
  three calls are the load-bearing summary; later calls fall
  out from "same order as the loop".
- Every `pnoise2(...)` call site. The base value is the
  determinism handle; document it in §4.
- Every f-string in the SVG output. `:.1f` / `:.2f` / `:.3f` —
  Rust's `{:.N}` matches Python's `:.N` for IEEE 754 f64
  on every input the rendering pipeline produces, but if a
  primitive uses a custom formatter (the `:.3f`-with-trailing-
  zero-trim convention in §5), the Rust port has to replicate it.

### 7.2 RNG ownership — port `random.Random` to Rust, never bridge

The legacy primitives drive `random.Random(seed)` directly. The
Rust ports use `python_random::PyRandom` (in
`crates/nhc-render/src/python_random.rs`) — a byte-compat
reproduction of CPython's `random.Random` covering only the
methods the procedural primitives reach (`random()`,
`randint()`, `getrandbits()`). Anything else is intentionally
absent so the `import random` ban that lands at the end of
Phase 4 doesn't sneak back in through this struct.

**Do not** pass rng-derived values from Python into Rust as
parameters — that defeats the point of porting and leaves Python
holding the determinism contract. The PyO3 boundary should
take only IR data (tile lists, seeds, polygons); the primitive
materialises a fresh RNG inside Rust.

The MT19937 + seed-from-int + `random()` mantissa construction
is locked down by inline `cargo test` vectors against
`random.Random(<seed>)` outputs from CPython 3.14 (see the test
block in `python_random.rs`). When porting a primitive that
uses a different seed, capture three vectors (`getrandbits(32)`,
`random()`, `randint(...)`) from CPython and add an inline test
— `cargo test` then catches a determinism break before the
maturin wheel rebuilds.

### 7.3 Perlin — `pnoise2` is the cross-language gate

Phase 3.1 already established this: the Rust Perlin lives at
`crates/nhc-render/src/perlin.rs` with `f64` throughout (Python
`float` is f64; the test-fixture asserts exact equality).
Per-primitive ports just call `crate::perlin::pnoise2` — there
is no per-primitive Perlin. If a port needs a feature `pnoise2`
doesn't have (3D, octaves, …), extend the shared module.

### 7.4 Primitive shape

Each primitive lives at `crates/nhc-render/src/primitives/<op>.rs`
and exposes one or two functions:

- A *layer-level driver* (e.g. `draw_floor_grid`) that owns the
  RNG, walks the IR's pre-classified data, and returns the
  SVG-fragment data the Python handler needs.
- One or more *helpers* mirroring the legacy `_<thing>` helpers
  (e.g. `wobbly_grid_seg`). Helpers stay private — the FFI shim
  only exposes drivers.

The PyO3 shim in `ffi/pyo3.rs` is a one-liner per primitive:
unwrap the Python tuple, call the driver, return the result.
Any logic in the shim is wrong — the shim is a thin marshaller.

### 7.5 What stays Python-side

The plan's Phase 3 sketch named `dungeon_polygon` and `theme` as
parameters; in practice neither is RNG-sensitive and both stay
Python-side:

- **Clip envelopes** (`<defs><clipPath>...`) read the IR's
  region polygon and emit deterministic SVG. The Python handler
  owns these — moving them to Rust adds an FFI hop without
  buying determinism (they were already deterministic).
- **`<path>` element wrapping** — `fill="none" stroke="..."` etc.
  Keep these in Python until Phase 5 routes the whole layer
  through `tiny-skia` and the SVG envelope disappears.

Rule of thumb: if the bytes don't change with `random.Random()`
or `pnoise2()` output, they don't need to be in Rust today.

### 7.6 Parity gate — never relax

The per-layer parity test (e.g.
`tests/unit/test_emit_floor_grid_parity.py`) is the contract.
When a port goes red:

1. Diff the legacy and IR-emitted SVG fragments. The first
   divergent byte tells you which segment / sub-segment / value
   misses.
2. Walk the RNG / Perlin / formatter call sequence for that
   segment. The bug is almost always a missing call (Perlin
   sample skipped where the legacy had one), an off-by-one
   loop bound, or a formatter mismatch (`:.1f` rounding edge
   case at a half-bit boundary).
3. Fix the Rust port. **Do not** edit the parity gate, regenerate
   fixtures, or add a tolerance — every escape hatch buys today's
   primitive a green CI but blocks every later primitive that
   builds on the same RNG / Perlin contract.

Phase 3's canary (`floor_grid`) shipped without ever needing to
revisit the gate; expect Phase 4 ports to clear the same bar.
