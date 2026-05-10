# Level surface layout — uniform 1-tile-margin contract

**Status:** Canonical reference. Adopted on `feat/pure-ir-v4` after
the `assemble_town` palisade-overflow investigation surfaced a
broader pattern: several generators allocate the level surface
independently from where the renderable content lands, producing
either negative-coord overflow (bug) or excess VOID columns at
the right / bottom edges (cosmetic). This document specifies the
contract every level-producing generator follows; the matching
execution plan is `~/src/plans/level_surface_layout_refactor.md`.

## 1. Principle

> **The world IS the canvas.** Every renderable element fits
> inside the level grid the renderer paints onto. Visible whitespace
> around content is encoded as VOID tiles in `level.tiles`, not as
> renderer-side padding. The renderer's `IR.padding` field stays at
> its current 1-cell value (`PADDING = 32 px`); a generator that
> produces a level with content that needs more breathing room
> grows `level.width / height` to make room.

Two consequences fall out:

1. **No negative-coord paint ops.** Polygons that today extend
   past `y=0` (palisade dipping above the top row, etc.) become
   bugs the contract test catches.
2. **No silent over-allocation.** Surface dimensions are derived
   from the renderable bbox; assemblers no longer pre-allocate a
   "size_class surface" larger than they end up using.

## 2. The contract

Every level produced by a generator entry point — site assembler,
dungeon generator, template, underworld biome, or building floor
— satisfies:

> The **renderable bounding box** is contained within the open
> interior of the level grid:
>
> ```
> bbox.min_x ≥ 1
> bbox.min_y ≥ 1
> bbox.max_x ≤ level.width - 2
> bbox.max_y ≤ level.height - 2
> ```
>
> i.e. there is exactly one tile of VOID buffer between any
> renderable element and the canvas edge on every side.

The renderable bbox is the union of:

1. **Non-VOID tiles.** Every `(x, y)` whose
   `level.tiles[y][x].terrain` is not `Terrain.VOID`.
2. **Enclosure polygon.** When `site.enclosure is not None`,
   every vertex of `site.enclosure.polygon` (palisade /
   fortification outer ring).
3. **Building base_rects.** Every `building.base_rect` on the
   site (when the level is a site surface).
4. **Decoration overhang pad.** Every building rect grows by 1
   tile on each side before joining the bbox. Captures roof
   eaves, vegetation overhang, etc. without forcing each
   primitive's overhang amount into the contract.

Anything else the renderer paints (shadows at +3 px offset,
hatch halo within 2 tiles of the dungeon polygon, decorator
fills inside non-VOID tiles) lives within these four bbox
contributors and inherits the margin automatically.

## 3. Per-generator implications

### Site assemblers

Top-down sizing — flow becomes:

1. Pick **palisade outer dimensions** (or, for non-enclosure
   sites, the **buildable area** dimensions) from the size_class
   config.
2. Reserve the inner buildable area = palisade outer minus the
   enclosure inner pad (`TOWN_PALISADE_PADDING = 3` for town,
   `KEEP_FORTIFICATION_PADDING` for keep, etc.).
3. Place clusters / buildings inside the inner buildable area.
   Building placements honour the 1-tile decoration overhang —
   no building's bbox+1 extends past the inner buildable area.
4. Allocate the surface as `palisade_outer + 2` (1 tile of VOID
   margin on each side; surface origin is at `(0, 0)`, palisade
   outer rect lives at `(1, 1)` to `(palisade_w + 1,
   palisade_h + 1)`).
5. Site-relative coords (rooms, building rects, palisade
   polygon, gates, interior_door_links, etc.) all reference the
   surface coord system directly — no post-placement shift.

For non-enclosure sites (`tower / farm / mansion / temple /
cottage / mage_residence`), drop step 2's enclosure inner pad
and skip the palisade in step 4.

**Site surface relaxation:** the strict 1-tile VOID margin is
intentionally relaxed for `site:*` surfaces. Settlements and
sub-hex feature sites use the canvas edge for the outer grass
ring (`nhc/sites/_site.py::paint_outer_grass_ring`,
`town.py::config.grass_ring_width`) so the surface reads "site
sits in countryside" rather than "framed art on paper".
`tests/unit/test_level_surface_invariant.py` opts site-prefixed
entries into `_RELAX_BBOX_TO_CANVAS_EDGE`; dungeon / template /
theme / building-floor levels keep the strict invariant. See
`design/sites.md` §"Settlement architecture" for the full
settlement allocation model.

### Dungeon / template / underworld generators

These already place rooms inside a pre-sized grid; the bug here
is over-allocation rather than overflow. Audit each generator:

1. Pick **buildable area dimensions** from generator params.
2. Place rooms / corridors / cave tiles inside the inner area
   (offset by 1 from each canvas edge).
3. Allocate the surface as `buildable_area + 2`.

The BSP partitioner currently reserves boundary tiles; the
audit may reveal it's already compliant on most cases.

### Building floor levels

Building interiors are individual `Level` objects. The
"renderable bbox" for a building floor is the floor's interior
walls + tiles. The contract holds: 1-tile VOID margin between
the outer wall and the canvas edge.

Most building floors are generated at exact interior dimensions
(no over-allocation); compliance check is one walk per
assembler. Probably a no-op refactor.

## 4. Tests

`tests/unit/test_level_surface_invariant.py` parameterises
every generator entry point and asserts the contract:

```python
@pytest.mark.parametrize("generator,seed", _ALL_GENERATORS)
def test_level_surface_invariant(generator, seed):
    level, site = generator(seed)
    bbox = compute_renderable_bbox(level, site)
    assert bbox.min_x >= 1 and bbox.min_y >= 1
    assert bbox.max_x <= level.width - 2
    assert bbox.max_y <= level.height - 2
```

Generators that don't yet comply ship the test with an
`xfail(strict=True)` marker. Each refactor commit removes its
own xfail.

## 5. Implementation discipline

- **Strict TDD per nhc/CLAUDE.md.** Each generator refactor
  writes the contract-conformance test FIRST (or removes the
  xfail FIRST), runs it failing, then ships the implementation
  that makes it pass.
- **One commit per generator** for bisect granularity. The
  trigger case (`assemble_town`) ships first; subsequent
  commits chip at the xfail list.
- **Test fixture cascade:** existing tests that assert specific
  coords get rewritten as structural assertions where possible;
  byte-snapshot trip-wires regenerate. Mixed strategy per
  `~/src/plans/level_surface_layout_refactor.md`.

## 6. References

- `~/src/plans/level_surface_layout_refactor.md` — the execution
  plan with the per-commit ladder.
- `nhc/sites/town.py:_build_palisade` — the site-side helper
  whose post-placement bbox computation produced the negative-
  coord palisade that triggered this refactor.
- `nhc/rendering/ir_emitter.py:FloorIRBuilder.finish` — the IR
  packer; sets `fir.padding = PADDING (32 px)` unchanged. The
  contract pushes the margin down to the level grid; the
  renderer doesn't get padding overrides.
- `tests/samples/_samples/_core.py` — the sample-tool render
  path; verifies the contract holds on every catalog entry.
