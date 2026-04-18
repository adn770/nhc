# Dungeon Map IR — SVG rendering redesign

Design for replacing NHC's direct SVG emission of dungeon floors with a compact
intermediate representation (IR) plus pluggable transformers: server-side IR→SVG,
client-side IR→Canvas, optional server-side IR→PNG.

This is a future-facing reference. Implementation is **deferred until
world-expansion Phase 6** (Caves of Chaos) lands — see `design/world_expansion.md`.
Doing the IR work after world-expansion primitives settle means the schema is
designed against the final vocabulary, not a moving target.

## Principles

- **Structural vs procedural separation.** The IR carries computed geometry
  (polygons) explicitly. Decorative detail is expressed as seeded procedural
  commands; the renderer regenerates the detail deterministically.
- **Bit-exact determinism across runtimes.** Same IR → same pixels in Python
  and JS. Splitmix64 replaces Python's Mersenne Twister in the rendering
  subpackage; a matching JS implementation ships with the Canvas renderer.
- **Pixel-faithful port.** The Canvas renderer reproduces the full Dyson-style
  look. All ~15 procedural primitives are ported to JS.
- **Gameplay hot path offloads to client.** After the Canvas renderer ships,
  the server stops emitting decoration SVG for gameplay requests. IR→SVG stays
  available for cold paths (export, share, `/admin` debug, tests).
- **Strict TDD.** Every change is gated by a parity test.

## Problem

Two pain points motivate the rework:

1. **Payload size.** Per-floor SVG is 60–250 KB (logged at
   `nhc/rendering/web_client.py:1309`); a separate ~100 KB hatch pattern is
   fetched once per session. The bulk of a floor's bytes are procedurally
   generated decoration — Perlin-wobbled grid lines, cross-hatch coordinates,
   floor stones, cracks, grass blades — baked into long `<path d="...">`
   attributes.
2. **Generation speed.** Shapely polygon unions (cave geometry, dungeon
   polygon) and Python-side procedural detail (wobble paths, floor stones,
   hatching) run on every floor change.

Neither is fixed by IR alone. Shapely still runs regardless. What IR enables is
**skipping decoration stringification on the gameplay hot path** once the
client renders it from IR directly. That is where the real server-side speedup
lands, and it is also what shrinks the wire payload to a few KB.

**Zero-cost check before any IR work.** Confirm the Flask endpoint at
`nhc/web/app.py:996–1009` is gzipped by Caddy/gunicorn. SVG compresses 3–5×
with gzip alone. If that is off, turning it on is a partial win that coexists
with everything below.

## Decisions

| Decision | Choice |
|---|---|
| Target scope | Full stack → frontend Canvas (Phases 1–3; Phase 4 PNG deferred) |
| PRNG strategy | Bit-exact, swap to splitmix64 both sides |
| Visual fidelity | Pixel-faithful: port all ~15 procedural primitives to JS |
| SVG role post-Phase-3 | Canvas-only for gameplay; server IR→SVG for cold paths |
| Canvas first-paint | Monolithic single-pass (matches current SVG behaviour) |
| Phase 1 parity gate | Byte-equal SVG (drop to visual parity once Phase 2 changes output) |
| Schedule | After world-expansion Phase 6 |
| IR format | JSON (debuggable; gzip at HTTP closes the size gap) |
| IR scope | Dungeon floor rendering only; hex / overland stay on current path |

## Current state (context)

Phase 0b of the world-expansion plan is complete: `svg.py` is 349 lines with
ten extracted helper modules that map almost 1:1 onto IR primitives. That
modularization is a significant accelerator when IR work begins.

Relevant modules under `nhc/rendering/`:

- `svg.py` — entry point `render_floor_svg(level, seed, hatch_distance)`
- `_shadows.py`, `_hatching.py`, `_walls_floors.py`, `_terrain_detail.py`,
  `_floor_detail.py`, `_stairs_svg.py` — layer renderers
- `_room_outlines.py`, `_cave_geometry.py`, `_dungeon_polygon.py` —
  structural geometry (Shapely)
- `_svg_helpers.py` — low-level primitives (`_wobbly_grid_seg`, `_y_scratch`,
  constants like `CELL=32`, `PADDING=32`, `INK`, `FLOOR_COLOR`)

Web flow: the client fetches the SVG at `/api/game/<sid>/floor/<svg_id>.svg`
(content-type `image/svg+xml`, 7-day cache), inlines it into DOM via
`container.innerHTML = svgString` at `nhc/web/static/js/map.js:103`, then
composites canvas layers (door / hatch / fog / entity) on top. The SVG is a
static background — there is no SVG DOM manipulation client-side.

## 1. IR design

### Two classes of commands

1. **Structural ops.** Concrete geometry computed by Shapely on the server —
   polygon outlines for rooms, caves, corridors, the dungeon polygon (for
   clipping), wall segments. Stored as coordinate arrays. These *are* baked
   because recomputing `shapely.ops.unary_union` in JS is prohibitive. They
   are small: a 50-room level needs a few KB of polygon data.
2. **Procedural ops.** Decoration with `(region_ref, seed, params)`. The
   renderer (Python or JS) reproduces detail deterministically via
   `nhc.rendering.ir_rng` (splitmix64). Each op carries its own seed derived
   from `base_seed + op_salt`, matching current salts (`+77` hatching, `+99`
   detail, `+0x5A17E5` cave jitter, etc.).

### Schema sketch

```json
{
  "version": "1.0",
  "size": {"w": 80, "h": 60, "cell": 32, "padding": 32},
  "theme": "dungeon",
  "seed": 42,
  "regions": {
    "dungeon": {"type": "polygon", "paths": [...], "holes": [...]},
    "cave_0":  {"type": "polygon", "paths": [...]},
    "room_3":  {"type": "polygon", "paths": [...], "shape": "octagon"}
  },
  "ops": [
    {"op": "shadow",         "region": "dungeon", "dx": 2, "dy": 2, "opacity": 0.08},
    {"op": "hatch",          "region_out": "dungeon", "seed": 119, "extent_tiles": 2.0},
    {"op": "walls_floors",   "room_regions": ["room_3", ...], "rect_rooms": [...],
                             "corridor_tiles": [...], "cave_region": "cave_0",
                             "wall_segments": ["M10,20 L42,20", ...]},
    {"op": "terrain_tint",   "tiles": [[x, y, "water"], ...]},
    {"op": "floor_grid",     "clip": "dungeon", "seed": 41, "theme": "dungeon"},
    {"op": "floor_detail",   "tiles": [...], "seed": 141, "theme": "dungeon"},
    {"op": "thematic_detail","tiles": [...], "seed": 199, "theme": "dungeon"},
    {"op": "terrain_detail", "tiles": [...], "seed": 242, "theme": "dungeon"},
    {"op": "cobblestone",    "tiles": [...], "seed": 333},
    {"op": "stairs",         "tiles": [[x, y, "up|down"], ...], "theme": "cave"}
  ]
}
```

Themes travel as a parameter on relevant ops — no per-theme op variants.

### IR size budget

Estimated for a typical 80×60 level with ~50 rooms:

| Component | Bytes (raw) |
|---|---|
| regions (polygons) | 3–6 KB |
| shadow / walls_floors / wall_segments | 2–4 KB |
| hatch (tile sets + seeds) | 1–2 KB |
| terrain_tint + terrain_detail (tile lists) | 0.5–1.5 KB |
| floor_grid / floor_detail / thematic_detail | 0.5 KB each |
| cobblestone / stairs | 0.2 KB each |
| **Total** | **~8–15 KB raw, ~3–5 KB gzipped** |

Current SVG: 60–250 KB raw, ~20–70 KB gzipped.

### PRNG (splitmix64)

Both runtimes go through a thin `ir_rng` wrapper. Python side replaces current
`random.Random(seed)` calls inside `nhc/rendering/`. JS side ships a matching
implementation. Effect on existing seeds: the dungeon *layout* is unchanged
(that uses separate RNG streams in `nhc/dungeon/` — unaffected), but cosmetic
detail (grid wobble, stone placement, etc.) shifts for a given seed. Running
games are safe because SVG caches on disk continue to serve.

Perlin noise (`noise.pnoise2`) gets the same treatment: port a matching JS
implementation, or bake Perlin-dependent coordinates into structural IR when
they affect silhouettes (cave jitter — already server-side).

### Hatching pattern

Stays a shared global asset (`/api/hatch.svg`) fetched once per session and
rasterised into a Canvas `createPattern()` on the client. It is
seed-independent and identical across floors. No need to port hatch pattern
generation to JS — the SVG asset plus a one-time rasterisation is simpler and
equivalent.

## 2. Op schemas

Each op has a JSON shape, a deterministic contract (what is seeded, what
parameters drive output), and a reference implementation. Units: SVG pixel
space; `CELL = 32`, `PADDING = 32`.

### Structural regions

```json
"regions": {
  "<region_id>": {
    "type": "polygon",
    "paths":  [[[x, y], ...], ...],   // one or more closed outer rings
    "holes":  [[[x, y], ...], ...],   // interior exclusions (cave islands)
    "shape":  "octagon"               // optional tag for renderer
  }
}
```

Producers: `_dungeon_polygon.py::_build_dungeon_polygon`,
`_cave_geometry.py::_build_cave_wall_geometry`,
`_room_outlines.py::_room_svg_outline` (shape-aware). The `dungeon`,
`cave_0..n`, and `room_0..n` regions are always emitted.

### 1. shadow

```json
{"op": "shadow", "kind": "room|corridor|per-tile",
 "region": "<region_id>", "dx": 3, "dy": 3, "opacity": 0.08}
```

- `room`: use the room outline polygon, translate by `(dx, dy)`, fill `INK` at
  `opacity`.
- `corridor`: per-tile; the op carries `tiles: [[x, y]]`.
- Reference: `_shadows.py::_room_shadow_svg`, `_render_corridor_shadows`.

### 2. walls_floors

```json
{"op": "walls_floors",
 "room_regions": ["room_3", ...],            // smooth-shape rooms
 "rect_rooms":   [{"x": 4, "y": 5, "w": 8, "h": 6}, ...],
 "corridor_tiles": [[x, y], ...],
 "cave_region":  "cave_0",
 "wall_segments": ["M10,20 L42,20", ...],   // tile-edge segments
 "fill": "FLOOR_COLOR", "cave_fill": "CAVE_FLOOR_COLOR",
 "wall_color": "INK", "wall_width": 2.0}
```

- Smooth rooms: filled outline + stroke pass.
- Rect rooms: filled rect.
- Corridors: per-tile floor rects.
- Cave region: filled polygon (from the baked jittered ring) + stroke.
- Wall segments: a single `<path>` combining every tile-edge wall segment
  (rect rooms + corridors + non-street tiles).
- Reference: `_walls_floors.py::_render_walls_and_floors`.

### 3. hatch

```json
{"op": "hatch", "kind": "room|corridor|hole",
 "region_out": "dungeon",    // area to exclude
 "region_in":  "cave_0",     // area to hatch inside (for holes)
 "extent_tiles": 2.0,
 "seed": 119,
 "stride": 0.5,
 "tiles": [[x, y], ...]       // corridor kind only
}
```

- Renderer fills the target region with: grey underlay rect/tile, 0–2 seeded
  stones per tile, and section-partitioned cross-hatch lines with per-section
  perpendicular direction and Perlin-jittered stroke.
- Section boundaries come from `_dungeon_polygon.py::_build_sections` and must
  be deterministic given the region geometry + seed.
- Reference: `_hatching.py::_render_hatching`, `_render_corridor_hatching`,
  `_render_hole_hatching`.

### 4. terrain_tint

```json
{"op": "terrain_tint",
 "tiles": [[x, y, "water"], ...],
 "room_washes": [{"rect": [x, y, w, h], "color": "#...", "opacity": 0.08}],
 "clip": "dungeon"}
```

- Per-tile coloured rects clipped to dungeon interior.
- Room-type washes derived from `room.tags` against `ROOM_TYPE_TINTS`.
- Reference: `_terrain_detail.py::_render_terrain_tints`.

### 5. terrain_detail

```json
{"op": "terrain_detail",
 "tiles": [[x, y, "water|grass|lava|chasm", is_corridor], ...],
 "seed": 242,
 "theme": "dungeon",
 "clip": "dungeon"}
```

Per-tile sub-generators:

- `water`: 2–3 wavy horizontal polylines + 10% chance of ripple circle.
- `grass`: 3–6 angled blade strokes + 15% chance of tuft cluster.
- `lava`: 1–2 crack lines + 20% chance of ember dot.
- `chasm`: 2–3 jittered diagonal lines.

Room tiles clipped to dungeon interior; corridor tiles not clipped. Reference:
`_terrain_detail.py::_render_terrain_detail` + `_water_detail` / `_grass_detail`
/ `_lava_detail` / `_chasm_detail`.

### 6. floor_grid

```json
{"op": "floor_grid",
 "clip": "dungeon",
 "seed": 41,
 "theme": "dungeon",
 "scale": 1.0}
```

- Wobbly grid: horizontal + vertical lines at `CELL` intervals, displacement
  via Perlin noise, stroke width `GRID_WIDTH`, opacity 0.7.
- Per-theme scale: dungeon=1.0, crypt=2.0, cave=2.0, sewer=1.0, castle=0.8,
  forest=0.6, abyss=1.5 (from `_floor_detail.py::_DETAIL_SCALE`).
- Reference: `_floor_detail.py::_render_floor_grid`,
  `_svg_helpers.py::_wobbly_grid_seg`.

### 7. floor_detail

```json
{"op": "floor_detail",
 "tiles": [[x, y], ...],
 "seed": 141,
 "theme": "dungeon"}
```

Per-tile rolls produce:

- crack (probability 0.08 dungeon / 0.32 cave, times theme scale): line from a
  tile corner, two endpoints near the edges.
- scratch (probability 0.05 / 0.01): stylised Y-mark via
  `_svg_helpers.py::_y_scratch`.
- stone (probability 0.06 / 0.10): single ellipse,
  `_floor_detail.py::_floor_stone`.
- cluster (probability 0.03 / 0.06): 3 small stones near centre.

Stone colours: `FLOOR_STONE_FILL`, `FLOOR_STONE_STROKE`. Reference:
`_floor_detail.py::_render_floor_detail`, `_tile_detail`, `_floor_stone`.

### 8. thematic_detail

```json
{"op": "thematic_detail",
 "tiles": [[x, y], ...],
 "seed": 199,
 "theme": "dungeon"}
```

- Per-tile rolls produce webs, bone piles, skulls. Probabilities from
  `_THEMATIC_DETAIL_PROBS` (e.g. crypt = web 0.08, bones 0.10, skull 0.06).
- Webs placed only in tile corners whose two adjacent neighbours are non-floor
  (wall corners). Renderer picks a wall corner with `rng.choice`.
- Bones: 2–3 crossed line+end-circle bones centred randomly.
- Skulls: small rounded-rect cranium + oval jaw.
- Reference: `_floor_detail.py::_tile_thematic_detail`, `_web_detail`,
  `_bone_detail`, `_skull_detail`.

### 9. cobblestone (street tiles)

```json
{"op": "cobblestone",
 "tiles": [[x, y], ...],
 "seed": 333,
 "theme": "settlement"}
```

Per-street-tile: pack 6–10 small stones (`_street_stone`) in a soft hex-offset
pattern. Reference: `_floor_detail.py::_render_street_cobblestone`,
`_cobblestone_tile`, `_street_stone`.

### 10. stairs

```json
{"op": "stairs",
 "tiles": [[x, y, "up|down"], ...],
 "theme": "cave"}
```

- Per stair tile: tapering wedge, 5 step lines, rail stroke 1.5, step stroke
  1.0. `down` tapers left→right; `up` tapers right→left.
- `theme == "cave"`: emit a filled polygon (colour `STAIR_FILL = "#E0E0E0"`)
  beneath the lines so stairs stand out on cave floor.
- Reference: `_stairs_svg.py::_render_stairs`.

### Layer ordering

Ops are emitted in the same sequence as the current SVG layers so the Phase 1
byte-equal parity holds:

1. `shadow` (rooms, then corridors)
2. `hatch` (rooms, holes, then corridors)
3. `walls_floors`
4. `terrain_tint`
5. `floor_grid`
6. `floor_detail`
7. `thematic_detail`
8. `terrain_detail`
9. `cobblestone`
10. `stairs`

### Determinism contract

- Every `seed` field is the full seed value (not an offset); the renderer
  instantiates `ir_rng.from_seed(seed)` directly.
- The emitter derives op seeds from the base seed as `base + salt`, matching
  current salts (`+7` corridor hatch, `+77` room hatch, `+99` floor detail,
  `+199` thematic, `+200` terrain detail, `+0x5A17E5` cave jitter, etc.).
- The order in which the renderer calls `rng.random()` / `rng.uniform` /
  `rng.choices` / `rng.randint` inside each op must match between Python and
  JS. `design/ir_primitives.md` will enumerate the exact call sequence for
  each primitive when the time comes.

## 3. Phased plan

### Phase 1 — IR emitter behind existing signature

Keep `render_floor_svg(level, seed, hatch_distance) -> str` as the public
entry point. Internally:

```python
def render_floor_svg(level, seed=0, hatch_distance=2.0) -> str:
    ir = build_floor_ir(level, seed, hatch_distance)
    return ir_to_svg(ir)
```

Each existing `_render_*` in the ten helper modules grows a sibling
`_emit_*_ir` that appends IR ops; existing SVG string-building moves into
`_draw_*_from_ir` dispatched by `ir_to_svg`. Zero behaviour change.

**Gate:** byte-equal parity between old `render_floor_svg` and new
`ir_to_svg(build_floor_ir(...))` on fixture levels.

### Phase 2 — Procedural ops + IR endpoint

Convert decoration layers (`floor_detail`, `floor_grid`, `hatch`,
`terrain_detail`, `corridors`) to procedural ops carrying `(region, seed,
tile_list, theme)`. The IR→SVG transformer still regenerates equivalent SVG
at serialize time, but via procedural replay through `ir_rng`. Introduce
`ir_rng.py` (splitmix64) and migrate all rendering-side RNG calls.

Expose `/api/game/<sid>/floor/<id>.ir.json` alongside the existing `.svg`
endpoint. Extend autosave `save_svg_cache` to cache IR.

**Gate:** IR→SVG output matches a Phase-1 baseline regenerated under the new
PRNG. Wire-size measurement logged.

### Phase 3 — Frontend IR→Canvas renderer

Ship `nhc/web/static/js/floor_ir_renderer.js` and `ir_rng.js` (+ Perlin
port). Template swap: `<div id="floor-svg">` → `<canvas id="floor-canvas">`.
`map.js`: `setFloorSVG` → `setFloorIR`. Canvas fog / hatch / door / entity
layers are unaffected — they already composite on top, oblivious to how
floor was drawn.

Rendering is **monolithic**: iterate IR ops linearly, paint each. Same
latency characteristics as current SVG inlining.

The server changes its emission strategy for the gameplay path: when the
client fetches `.ir.json`, the server builds IR and returns it without
calling `ir_to_svg` — skipping all decoration stringification. When the
client (or an export endpoint, or a test, or admin debug) fetches `.svg`,
the server goes IR→SVG as normal.

**Gate:** rasterised Canvas output (headless Chromium on fixtures) vs Python
IR→SVG rasterised via resvg-py, pixel-diff ≤0.5%. Server CPU on a canonical
floor: expect 40–60% drop vs Phase 1 baseline.

### Phase 4 — Optional server IR→PNG (deferred)

If share-a-map or archival use cases emerge, wire `IR → SVG → resvg-py →
PNG`. `resvg-py` is a single-binary Rust rasterizer with ARM wheels and
deterministic output. PNG adds ~28 MB transient memory per raster on the SBC
(3456×2048×4) — survivable but not free. Skip until actually needed.

## 4. Critical files

**Refactored (Phase 1):**

- `nhc/rendering/svg.py` — `render_floor_svg` becomes a shim.
- `nhc/rendering/_walls_floors.py`, `_floor_detail.py`, `_hatching.py`,
  `_terrain_detail.py`, `_shadows.py`, `_stairs_svg.py` — each `_render_*`
  gets an IR-emitter sibling; string-building moves into `_draw_*_from_ir`.
- `nhc/rendering/_cave_geometry.py`, `_dungeon_polygon.py`,
  `_room_outlines.py` — unchanged structurally, but polygon outputs become
  IR `regions` entries.

**New (Phase 1/2):**

- `nhc/rendering/ir.py` — dataclasses for `FloorIR`, `Region`, `Op` variants;
  JSON (de)serialisation; version handling.
- `nhc/rendering/ir_emitter.py` — `build_floor_ir(level, seed, hatch_distance)
  -> FloorIR`.
- `nhc/rendering/ir_to_svg.py` — `ir_to_svg(ir) -> str`.
- `nhc/rendering/ir_rng.py` — deterministic splitmix64 PRNG wrapper.
- `nhc/web/app.py` — add `/api/game/<sid>/floor/<id>.ir.json` route; extend
  `save_svg_cache` to cache IR alongside SVG.
- `design/ir_primitives.md` — normative spec for each procedural primitive
  (required for Python/JS parity).

**New (Phase 3):**

- `nhc/web/static/js/floor_ir_renderer.js` — canvas IR renderer.
- `nhc/web/static/js/ir_rng.js` — JS splitmix64 + matching Perlin.
- `nhc/web/templates/play.html` — swap floor-svg div for floor-canvas.
- `nhc/web/static/js/map.js` — `setFloorSVG` → `setFloorIR`.

**Unchanged:** `nhc/dungeon/model.py`, all generators, `map.js` door / hatch /
fog / entity layers.

## 5. MCP debug tool interaction

Existing `get_svg_room_walls`, `get_svg_tile_elements` MCP tools return SVG
fragments for offline debug. Once IR lands, add parallel `get_ir_region`,
`get_ir_ops` tools that return IR slices. Keep the SVG-returning tools for
backward compatibility but document the IR tools as preferred.

## 6. Testing (strict TDD)

1. **`tests/unit/test_floor_ir.py`** — golden IR tests. For fixed
   `(level, seed)`, assert emitted IR matches a committed JSON fixture under
   `tests/fixtures/ir/`.
2. **`tests/unit/test_ir_to_svg.py`** — byte-equal parity test (Phase 1). For
   the same fixtures, assert `ir_to_svg(ir) == render_floor_svg_legacy(...)`.
   This is the guardrail that keeps every later change honest.
3. **`tests/unit/test_ir_rng.py`** — splitmix64 determinism + Python/JS
   cross-port parity (checked-in expected output vectors).
4. **`tests/unit/test_ir_canvas_parity.py`** (`slow`, Phase 3) — rasterise IR
   via Python (`resvg` for IR→SVG→PNG) and via headless Chromium running the
   JS Canvas renderer; pixel-diff ≤0.5%.
5. **`tests/unit/test_ir_perf.py`** (`slow`) — p95 budget on `build_floor_ir`
   and `ir_to_svg` for 5 canonical levels.
6. **`tests/samples/generate_svg.py`** — extend to emit `.ir.json` alongside
   `.svg` for visual inspection.

JS-side tests run via headless Chromium under pytest-playwright (or a small
Node harness) so CI can enforce Python/JS parity without a live browser.

## 7. Verification end-to-end

- **Phase 1 complete:** `.venv/bin/pytest -n auto --dist worksteal -m "not
  slow"` green with new parity tests. `./server` serves byte-equal SVG.
- **Phase 2 complete:** `curl /api/.../floor/<id>.ir.json | wc -c` shows
  target wire size; gzip-over-HTTP further reduces. `ir_to_svg` rasterisation
  matches post-splitmix64 fixtures.
- **Phase 3 complete:** load `./server`, play through a dungeon, visual
  parity with old SVG (spot-check a cave level, an octagon room, a
  settlement). Network tab shows `.ir.json` fetched, no `.svg` on gameplay
  path, payload 3–15 KB gzipped. MCP `get_layer_state` inspects the canvas
  layer correctly.
- **Performance:** `build_floor_ir` alone vs current `render_floor_svg` p95
  (expect modestly faster — less string concat). Full win: with client on
  Canvas path, per-floor server CPU drops 40–60% because decoration is no
  longer stringified.

## 8. Success metrics

- **SVG path (Phase 1–2):** IR→SVG byte-equal (Phase 1) / semantically equal
  post-splitmix64 (Phase 2) to legacy.
- **IR wire size (Phase 2):** p95 `floor.ir.json` < 20 KB; gzipped < 5 KB.
- **Server speedup (Phase 3):** on gameplay hot path, per-floor render time
  drops 40–60% (no decoration stringification).
- **Canvas first-paint (Phase 3):** monolithic paint within ~50 ms on a
  2020-era laptop; SBC-class clients within ~300 ms.

## 9. Risks

- **PRNG wrapper reach.** Every `random.Random` call in `nhc/rendering/` must
  route through `ir_rng`. Missing one means Python/JS divergence. Mitigation:
  a lint rule (ruff ban on `import random` in that subpackage after
  migration) + dedicated parity tests per primitive.
- **Perlin noise port drift.** JS Perlin must match Python `noise.pnoise2`
  output. Mitigation: ship fixture vectors checked in both languages; the
  parity test is the first JS test written.
- **World-expansion features added to SVG between now and IR start.**
  Expected — Phases 2–6 will add new primitives. Mitigation: the IR design
  allows adding ops without changing existing ones. Each new world-expansion
  module extracted from `svg.py` keeps the same pattern, so IR extraction
  remains mechanical when the time comes.
- **Tests churn on fixture regeneration.** Golden IR fixtures tend to change
  as primitives evolve. Mitigation: regen script + reviewable diffs; keep
  fixtures small (one per shape × theme combination, not per-seed matrix).
- **SVG cache incompatibility post-splitmix64.** Existing disk-cached SVGs
  were produced under MT19937. Mitigation: bump cache version key so old
  caches are invalidated, not served alongside new renderers.

## 10. Extensibility patterns

World-expansion will add primitives as Phases 2–6 land: battlements, gate
rooms, city-wall panels, district boundary strokes, faction sigils,
biome-specific terrain detail (underworld ooze, Chaos runes). The IR must
absorb these without forcing rewrites.

### Versioning policy

- **Minor bump (`1.x → 1.y`)** — additive changes only: new ops, new
  optional fields on existing ops, new theme values, new region types. Old
  renderers ignore unknown ops (with a console warning) and render the rest.
  Ship freely.
- **Major bump (`1.x → 2.0`)** — breaking changes: renamed ops, removed
  fields, changed semantics, changed op ordering. Both transformers (IR→SVG
  and IR→Canvas) must accept both versions for one release cycle.
- The `version` field at the top of every IR document is `"major.minor"`
  (string). Renderers dispatch on major version.
- Cache keys in `save_svg_cache` include the IR version so old caches
  invalidate cleanly on version bumps.

### Adding a new op

Checklist for the world-expansion PR that adds a new primitive:

1. **Spec first** — append a section to `design/ir_primitives.md` with JSON
   shape, determinism contract, and reference implementation path. PR does
   not land without the spec.
2. **Python emitter** — add `_emit_<name>_ir` alongside the existing
   `_render_<name>` in the relevant helper module. Register with
   `ir_emitter.py`.
3. **IR→SVG transformer** — add `_draw_<name>_from_ir` in `ir_to_svg.py`.
   For a world-expansion PR that only needs the cold path, this is the
   minimum viable change.
4. **IR→Canvas transformer** — add a JS function in `floor_ir_renderer.js`
   with matching determinism (same rng.* call sequence as Python). Requires
   a cross-port parity fixture.
5. **Tests** — golden IR fixture + byte-equal SVG parity + (if new JS
   support) cross-runtime pixel-diff.
6. **Minor version bump** unless the op conflicts with existing semantics
   (rare).

### Adding a new theme

Themes travel as a string parameter on ops that accept them (`floor_grid`,
`floor_detail`, `thematic_detail`, `terrain_detail`, `stairs`, `cobblestone`).
To add a theme:

1. Add entry to `_DETAIL_SCALE` and `_THEMATIC_DETAIL_PROBS` in
   `_floor_detail.py` (Python side) and mirror in JS.
2. Add entry to `get_palette()` in `terrain_palette.py` for terrain colour
   overrides.
3. Add fixtures for the new theme × representative shapes combination.
4. Minor version bump.

Renderers treat unknown themes as `"dungeon"` (default fallback) — this lets
old clients render new-theme levels without crashing.

### Adding a new structural region type

Currently `{"type": "polygon", ...}`. If world-expansion needs richer
structures (e.g. a 3D mine shaft with stratified layers, or a settlement
district with named sub-regions), extend the region schema:

```json
"regions": {
  "district_market": {
    "type": "district",
    "outer": [[x, y], ...],
    "streets": ["street_0", "street_1"],
    "subregions": ["stall_0", "stall_1", ...]
  }
}
```

Renderers dispatch on `type`. Unknown types fall back to "render as empty
polygon" so Canvas still paints something plausible.

### Adding a new room shape

Room shapes live in `_room_outlines.py` today. To add a new shape (e.g.
`PentagonShape`):

1. Add the shape class to `nhc/dungeon/model.py`.
2. Add `_pentagon_vertices` to `_room_outlines.py` and dispatch in
   `_room_svg_outline`.
3. The IR emitter automatically produces the new shape's polygon as a
   `region`; no IR schema change.
4. The `walls_floors` op handles it via the existing `room_regions`
   dispatch.
5. Canvas renderer: if the polygon comes through correctly (it will, since
   it is just coordinates), no JS change needed.

This is the cleanest extension path — new shapes need *zero* IR schema
changes because shape is encoded as a polygon in `regions`.

### Hook points in the emitter

`ir_emitter.build_floor_ir()` should be structured as a pipeline of stage
functions so world-expansion phases can inject new stages:

```python
def build_floor_ir(level, seed, hatch_distance):
    ir = FloorIR(version="1.0", ...)
    for stage in IR_STAGES:
        stage(ir, level, seed)
    return ir

IR_STAGES = [
    _emit_regions,        # polygons
    _emit_shadows,
    _emit_hatch,
    _emit_walls_floors,
    _emit_terrain_tint,
    _emit_floor_grid,
    _emit_floor_detail,
    _emit_thematic_detail,
    _emit_terrain_detail,
    _emit_cobblestone,
    _emit_stairs,
]
```

World-expansion adds new stages by appending (or inserting at the correct
layer index) in its own PR. Order is preserved for byte-equal parity;
inserting out of order needs a layer-ordering update and new fixtures.

### Theme-specific variants on existing ops

Some primitives may gain theme-specific rendering (e.g. "altar" rooms get a
pentagram floor overlay in abyss-theme only). Preferred approach:

- **If shape is the same but parameters differ**, extend the existing op
  with optional theme-keyed fields. E.g. `{"op": "floor_detail", ...,
  "overlay": "pentagram"}`.
- **If it is structurally different**, add a new op (e.g. `{"op":
  "altar_overlay", "region": "room_9", "pattern": "pentagram"}`).

Prefer new ops over overloaded existing ones when in doubt — determinism
contracts are harder to preserve on overloaded ops.

### Deprecation

To remove an op (e.g. world-expansion replaces `cobblestone` with a richer
`street` op):

1. Add the new op in version `1.x`.
2. Emitter produces both for one release cycle.
3. Transformers accept both but log deprecation for the old op.
4. Remove the old op and bump major version.
5. Regenerate all fixtures.

## 11. Open questions at implementation time

- Whether to ship Phase 4 (server IR→PNG) at all — likely driven by a future
  share-a-map / archival feature request, not built speculatively.
- Whether `ir_to_svg` on the cold path should offer a lossy fast mode for
  admin debug (skip decoration for faster rendering when humans just need
  structural view).
- Fixture granularity: one IR fixture per room shape × theme × seed, or one
  per shape × theme? Current guess: shape × theme (≈45 fixtures); expand if
  debugging demands it.
