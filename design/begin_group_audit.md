# `begin_group` audit

Phase A scaffolding for `plans/wasm-render-caching.md`. Every
production `begin_group(opacity)` call site in `crates/nhc-render`
is classified here as **disjoint** (safe to eliminate by pre-
multiplying `opacity` into the fill colour) or **overlapping**
(the group envelope is load-bearing and must stay).

When a contributor adds a new `begin_group` call, append the site
to this table AND drop a matching `// audit: <verdict>` annotation
next to the call. The same audit grammar lives in three places to
keep them mutually visible:

- this design doc (the canonical table);
- the inline `// audit:` comments at every call site;
- the pointer comment at the top of
  `crates/nhc-render/src/painter/canvas.rs::begin_group`.

## Eligibility rule

The painter's `begin_group(opacity)` allocates a full-canvas-sized
offscreen pixmap, routes the enclosed paints there, and on
`end_group` blits the offscreen back at the group's `opacity`. The
allocation is ~40 MB on a 3456×2880 town canvas; with ~59 sites
firing across a render, the cumulative allocate + zero-fill cost
runs into 50–150 ms.

For paints whose pixels are **pairwise disjoint** inside the
group, the result of `(group composite at opacity)` is the same as
`(per-element fill at opacity)` because each pixel is covered
exactly once. Eliminating the group + `with_alpha(opacity)` on the
fill saves the offscreen allocation with zero pixel drift.

For paints that **overlap inside the group**, per-element
compositing over-darkens the overlap region — the SVG-spec
behaviour is "composite the group at opacity", not "composite each
element at opacity". The over-darken bug was the precipitating
issue Phase 5.10 of `plans/nhc_pure_ir_v5_migration_plan.md`
fixed; we don't reintroduce it.

The disjointness test is geometric, not statistical: a pattern is
disjoint when its layout makes overlap structurally impossible
(e.g. axis-aligned bricks on a grid with strictly positive mortar
gaps). When in doubt, classify as overlapping — the cost of a
mis-classified disjoint is a visible over-darken artifact; the
cost of a mis-classified overlapping is keeping an allocation we
could have removed.

## Classifications

### Stone family — `crates/nhc-render/src/painter/families/stone.rs`

| Line | Function                       | Opacity                       | Verdict     | Rationale                                                                                                                  |
|------|--------------------------------|-------------------------------|-------------|----------------------------------------------------------------------------------------------------------------------------|
| 348  | `paint_cobblestone_herringbone`| `COBBLE_GROUP_OPACITY`        | overlapping | Rotated 18×6 pavers at stride 9 — rotated bbox ~24×12 overlaps neighbours along both axes.                                |
| 389  | `paint_cobblestone_stack`      | `COBBLE_GROUP_OPACITY`        | **disjoint**| 12 px grid, paint rect 10×10 (1 px pad each side) → 2 px gap between cells; checkerboard `base`/`highlight` per parity.    |
| 442  | `paint_cobblestone_rubble`     | `COBBLE_GROUP_OPACITY`        | overlapping | Density 1 stone / 64 px²; random positions + fill + stroke same path → stroke overlaps fill, neighbour stones can overlap.|
| 484  | `paint_cobblestone_mosaic`     | `COBBLE_GROUP_OPACITY`        | overlapping | Adjacent quad corners share borders modulated by ±1.44 px jitter → adjacent fills can overlap.                            |
| 544  | `paint_brick_running_bond`     | `BRICK_GROUP_OPACITY`         | **disjoint**| Brick face `(BRICK_W − BRICK_GAP) × (BRICK_H − BRICK_GAP)` = 15.4 × 5.4 on `col_w × row_h` = 16.6 × 6.6 → 1.2 px mortar.   |
| 589  | `paint_brick_english_bond`     | `BRICK_GROUP_OPACITY`         | **disjoint**| Stretcher / header rows share the brick-face / spacing budget; per-row spacing ≥ face width + 1.2 px mortar.              |
| 650  | `paint_brick_flemish_bond`     | `BRICK_GROUP_OPACITY`         | **disjoint**| Each unit = stretcher + header + 2 × `BRICK_GAP`; rows offset by ½ unit, brick faces stay clear of adjacent unit bounds.   |
| 710  | `paint_brick_header_bond`      | `BRICK_GROUP_OPACITY`         | **disjoint**| Square brick faces (5.4 × 5.4) on `header_w × row_h` grid, half-header stagger per row; gaps preserved.                    |
| 759  | `paint_brick_stack_bond`       | `BRICK_GROUP_OPACITY`         | **disjoint**| Same `BRICK_W × BRICK_H` faces on `col_w × row_h` grid with no row offset; mortar gap preserved in both axes.             |
| 810  | `paint_flagstone`              | `FLAGSTONE_GROUP_OPACITY`     | overlapping | Pentagonal plate strokes on jittered borders — adjacent plate edges nearly coincide and stroke widths overlap at corners. |
| 917  | `paint_opus_romano`            | `OPUS_ROMANO_GROUP_OPACITY`   | **disjoint**| 4 inset rects per 32 px Versailles tile; intra-tile rects share edges only at inset margins (no overlap).                  |
| 977  | `paint_field_stone`            | `FIELD_STONE_GROUP_OPACITY`   | overlapping | ±20 % cell-centre jitter + fill + stroke same polygon; neighbour stones can overlap, stroke always overlaps fill.         |
| 1047 | `paint_pinwheel`               | `PINWHEEL_GROUP_OPACITY`      | **disjoint**| 5 axis-aligned rects per 16 × 16 unit; intra-unit rects mortared with `PINWHEEL_PAD`; no inter-unit overlap.              |
| 1172 | `paint_hopscotch`              | `HOPSCOTCH_GROUP_OPACITY`     | **disjoint**| 3 axis-aligned rects per 16 × 16 unit (12 × 12 + 4 × 12 + 16 × 4); rotation preserves disjointness within and across.     |
| 1230 | `paint_crazy_paving`           | `CRAZY_PAVING_GROUP_OPACITY`  | overlapping | Jittered quad corners (±1.5 px) on variable-size cells → adjacent quads can overlap at jittered boundaries.               |
| 1322 | `paint_ashlar_inner`           | `ASHLAR_GROUP_OPACITY`        | **disjoint**| `ASHLAR_W × ASHLAR_H = 18 × 8` cells with 0.3 px gap; staggered variant only shifts row x-offset, no overlap introduced.   |
| 1380 | `paint_opus_reticulatum`       | `RETICULATUM_GROUP_OPACITY`   | **disjoint**| Diamond pavers on diagonal pitch `2·d + 0.6`; adjacent diamond tips share the 0.6 px gap.                                  |
| 1430 | `paint_opus_spicatum`          | `SPICATUM_GROUP_OPACITY`      | overlapping | Rotated 12×4 herringbone bricks at stride 6 — rotated bbox ~16×8 overlaps neighbours along both axes.                     |

### Wood family — `crates/nhc-render/src/painter/families/wood.rs`

| Line | Function              | Opacity                | Verdict     | Rationale                                                                                                  |
|------|-----------------------|------------------------|-------------|------------------------------------------------------------------------------------------------------------|
| 350  | `paint_plank` (seams) | `WOOD_SEAM_OPACITY`    | overlapping | Vertical plank-end strokes meet horizontal row-boundary strokes at T-junctions → stroke pixels overlap.    |
| 384  | `paint_plank` (grain) | `WOOD_GRAIN_OPACITY`   | overlapping | Multiple grain strokes per plank with shared endpoint regions; round caps over-darken at coincident ends. |
| 419  | `paint_basket_weave`  | `WOOD_SEAM_OPACITY`    | overlapping | Cell-boundary strokes shared between adjacent cells → strokes paint the same border pixels twice.         |
| 502  | `paint_parquet`       | `WOOD_SEAM_OPACITY`    | overlapping | Panel-boundary strokes shared between adjacent panels; same shape as basket weave.                        |
| 592  | `paint_herringbone`   | `WOOD_SEAM_OPACITY`    | overlapping | Rotated rect outlines at stride < rotated extent; adjacent stroke paths overlap.                          |
| 640  | `paint_chevron`       | `WOOD_SEAM_OPACITY`    | overlapping | Same shape as herringbone, column-parity rotation only.                                                   |
| 687  | `paint_brick` (wood)  | `WOOD_SEAM_OPACITY`    | overlapping | Row-boundary horizontal strokes meet per-block vertical seams at T-junctions.                             |

### IR-op handlers

| File                                    | Line | Site                              | Opacity                | Verdict     | Rationale                                                                                            |
|-----------------------------------------|------|-----------------------------------|------------------------|-------------|------------------------------------------------------------------------------------------------------|
| `transform/png/fixture_op.rs`           | 144  | `paint_web_anchor` (per anchor)   | `WEB_OPACITY`          | overlapping | Radial spokes meet at the hub; ring loops cross spokes → strokes overlap at the hub centre.          |
| `transform/png/fixture_op.rs`           | 201  | `paint_skull_anchor`              | `SKULL_OPACITY`        | overlapping | Eye sockets sit inside cranium circle; jaw rect overlaps cranium silhouette at base.                 |
| `transform/png/fixture_op.rs`           | 236  | `paint_bone_anchor`               | `BONE_OPACITY`         | overlapping | Knuckle dots overlap stroke endpoints by design; multiple bones cross at the tile centre.            |
| `transform/png/fixture_op.rs`           | 275  | `paint_loose_stone_anchor`        | `LOOSE_STONE_OPACITY`  | overlapping | 1–3 random ellipses per anchor; fill + stroke same path always overlap.                              |
| `transform/png/fixture_op.rs`           | 559  | `paint_mushroom_cluster_patch`    | `MUSHROOM_PATCH_OPACITY`| overlapping| Adjacent cluster members' patches overlap (patch radius > half cell).                                |
| `transform/png/fixture_op.rs`           | 595  | `paint_gravestone_cluster_plot`   | `GRAVE_PLOT_OPACITY`   | disjoint    | Single `fill_path` rect; no overlap possible within the group. Marginal savings — defer elimination.|
| `transform/png/path_op.rs`              | 133  | `paint_rail_path`                 | `PATH_GROUP_OPACITY`   | overlapping | Tile-centre rail half-segments meet at shared tile boundaries between rail tiles.                    |
| `transform/png/path_op.rs`              | 191  | `paint_vines`                     | `PATH_GROUP_OPACITY`   | overlapping | Per-tile quadratic curves can join at tile boundaries; round caps overlap.                           |
| `transform/png/path_op.rs`              | 233  | `paint_root_system`               | `PATH_GROUP_OPACITY`   | overlapping | Multiple branches per tile share the centre point; stroke pixels overlap at the hub.                 |
| `transform/png/path_op.rs`              | 272  | `paint_river_bed`                 | `PATH_GROUP_OPACITY`   | overlapping | Per-tile substrate fill overlaps per-tile ripple stroke (different paths, same pixels).              |
| `transform/png/path_op.rs`              | 324  | `paint_lava_seam`                 | `PATH_GROUP_OPACITY`   | overlapping | Core stroke (1.6 px) painted on top of glow stroke (3.4 px) along the same path.                     |
| `transform/png/stamp_op.rs`             | 363  | `paint_per_tile_decorator`        | varies (`group_opacity`)| overlapping| Generic scaffold for Moss / Blood / Ash / Puddles / Ripples / LavaCracks — `paint_one` closure unbounded.|

### Primitive emitters — `crates/nhc-render/src/primitives/`

| File                  | Line | Site                           | Opacity                | Verdict     | Rationale                                                                                          |
|-----------------------|------|--------------------------------|------------------------|-------------|----------------------------------------------------------------------------------------------------|
| `floor_detail.rs`     | 252  | cracks bucket                  | `CRACKS_OPACITY`       | overlapping | Multiple cracks per tile can cross; stroke pixels overlap at intersections.                        |
| `floor_detail.rs`     | 259  | scratches bucket               | `SCRATCHES_OPACITY`    | overlapping | Same shape as cracks bucket.                                                                       |
| `floor_detail.rs`     | 266  | stones bucket                  | `STONES_OPACITY`       | overlapping | Dense small ellipses; tile-boundary stones can overlap neighbours.                                |
| `hatch.rs`            | 199  | tile_fills bucket              | `TILE_FILLS_OPACITY`   | **disjoint**| Whole-tile `fill_rect` per tile; tiles tile non-overlapping squares of the floor grid.            |
| `hatch.rs`            | 206  | hatch_lines bucket             | `HATCH_LINES_OPACITY`  | overlapping | Per-tile hatch strokes meet at tile boundaries.                                                    |
| `cobblestone.rs`      | 207  | grid strokes                   | `GRID_OPACITY`         | overlapping | Adjacent grid cells share stroked borders → strokes overlap.                                       |
| `cobblestone.rs`      | 237  | stones                         | `STONES_OPACITY`       | overlapping | Rotated ellipses per tile, fill + stroke same path; neighbour stones can overlap.                  |
| `terrain_detail.rs`   | 194  | water tiles                    | `WATER_OPACITY`        | overlapping | Per-tile ripple strokes + base fill overlap at tile centres.                                        |
| `terrain_detail.rs`   | 221  | lava tiles                     | `LAVA_OPACITY`         | overlapping | Per-tile crack strokes + ember fills overlap.                                                       |
| `terrain_detail.rs`   | 242  | chasm tiles                    | `CHASM_OPACITY`        | overlapping | Per-tile hatch lines meet at tile boundaries.                                                       |
| `cart_tracks.rs`      | 451  | rails                          | `RAIL_OPACITY`         | overlapping | Polyline rails can cross at junctions; round caps overlap.                                          |
| `cart_tracks.rs`      | 471  | ties                           | `TIE_OPACITY`          | overlapping | Tie strokes can cross rail strokes at intersections.                                                |
| `thematic_detail.rs`  | 469  | web fragment                   | `WEB_OPACITY`          | overlapping | Spokes meet at the hub — single-path strokes self-overlap.                                          |
| `thematic_detail.rs`  | 476  | bones fragment                 | `BONE_OPACITY`         | overlapping | Bone strokes + dots overlap.                                                                        |
| `thematic_detail.rs`  | 483  | skull fragment                 | `SKULL_OPACITY`        | overlapping | Cranium fill + eye fills overlap inside the silhouette.                                             |
| `flagstone.rs`        | 149  | flagstone primitives           | `FLAGSTONE_OPACITY`    | overlapping | Pentagonal-plate stroke borders nearly coincide on adjacent plates.                                 |
| `field_stone.rs`      | 145  | field-stone primitives         | `FIELD_STONE_OPACITY`  | overlapping | Polygon stones fill + stroke same path; neighbour stones can overlap on cell jitter.                |
| `opus_romano.rs`      | 156  | opus-romano stroke primitives  | `OPUS_ROMANO_OPACITY`  | overlapping | Adjacent tile borders coincide on the subdivision grid → adjacent strokes overlap.                  |
| `ore_deposit.rs`      | 142  | diamond ore primitives         | `ORE_DEPOSIT_OPACITY`  | overlapping | Diamond fill + stroke same path; neighbour diamonds can overlap.                                    |
| `brick.rs`            | 148  | brick primitives               | `BRICK_OPACITY`        | overlapping | Adjacent brick stroke borders coincide on shared edges → strokes overlap.                           |
| `wood_floor.rs`       | 269  | light grain strokes            | `WOOD_GRAIN_OPACITY`   | overlapping | Per-plank grain strokes can overlap at shared room boundaries.                                      |
| `wood_floor.rs`       | 278  | dark grain strokes             | `WOOD_GRAIN_OPACITY`   | overlapping | Same shape as light grain bucket.                                                                   |

## Summary

- **Disjoint (eliminate)**: 13 sites — 5 brick patterns +
  Cobblestone Stack + Hatch tile_fills + Opus Romano + Pinwheel +
  Hopscotch + Ashlar + Opus Reticulatum + grave plot.
- **Overlapping (keep)**: 46 sites.
- **Total**: 59.

The eliminations land in subsequent commits (B–E) so each commit
body cites only the sites it touches and the per-site disjointness
argument.

The grave-plot site is technically disjoint (one fill_path) but
the saving is one offscreen allocation for a single rectangle —
deferred unless follow-up profile shows residual win.

## Adding a new `begin_group` site

1. Drop a `// audit: disjoint` or `// audit: overlapping (<one-line reason>)`
   comment on the line above the `begin_group(...)` call.
2. Add a row to the table above with file, line, function /
   bucket name, opacity constant, and the same rationale.
3. If disjoint, file a follow-up to eliminate the group — pre-
   multiply the opacity into the fill colour via
   `Color::with_alpha(opacity)` and drop the
   `begin_group` / `end_group` pair.

The classification is geometric — the cost of a mis-classified
disjoint is a visible over-darken; the cost of a mis-classified
overlapping is one offscreen allocation we could have skipped.
When in doubt, classify as overlapping.
