# NHC web canvas rendering — deep dive

Here is the full end-to-end walkthrough of the web client's map rendering, with the
dimming pipeline in focus.

> **Scope note.** This document describes the four canvas overlay layers (door / hatch / fog /
> entity) that compose **above** the floor image. The floor itself is currently a static SVG,
> and is on a path to become a Canvas paint driven by a FlatBuffers IR — see
> `design/map_ir.md`. The overlay logic below is **unchanged** by that migration: the same
> canvas stack composites on top of either an inlined SVG or a Canvas-painted floor.

## 1. The layer stack

The map is not one image; it is five stacked layers inside `#map-container`, a
`position: relative` box. Each sibling fills the same pixel box and is scrolled/zoomed
as a unit.

```
  ┌─────────────────────────────────────────┐  z=4  debug-canvas    (dev overlay)
  │  ┌───────────────────────────────────┐  │  z=3  entity-canvas   (glyphs, @, monsters)
  │  │  ┌─────────────────────────────┐  │  │  z=2  fog-canvas      (visibility darkening)
  │  │  │  ┌───────────────────────┐  │  │  │  z=1  hatch-canvas    (unexplored mask)
  │  │  │  │  ┌─────────────────┐  │  │  │  │  z=0  door-canvas     (doors above floor)
  │  │  │  │  │   floor-svg     │  │  │  │  │  (no z — DOM flow)
  │  │  │  │  │  (static geom)  │  │  │  │  │
  │  │  │  │  └─────────────────┘  │  │  │  │
  │  │  │  └───────────────────────┘  │  │  │
  │  │  └─────────────────────────────┘  │  │
  │  └───────────────────────────────────┘  │
  └─────────────────────────────────────────┘
```

- **floor-svg** is rendered once per floor by the server (`render_floor_svg` in
  `nhc/rendering/svg.py`), cached on disk, and dropped into `#floor-svg` in
  `GameMap.setFloorSVG`. It contains walls, floor tiles, features, water, stairs —
  all the static geometry at a fixed cell size of **32 px** with **32 px** outer
  padding.
- **door-canvas** draws every door the player has ever discovered (`allDoors` map).
  Sits *under* hatch so unexplored doors are correctly hidden.
- **hatch-canvas** is the "never seen" mask. It is filled with a repeating hatch
  pattern and then *holes are punched through it* as the player explores.
- **fog-canvas** is the *current visibility* darkening layer — this is where distance
  dimming lives.
- **entity-canvas** draws glyphs at full brightness, no dimming (deliberate —
  monsters are always legible).
- **debug-canvas** for god-mode overlays.

Each canvas has `width/height` set from the parsed `<svg>` dimensions in
`setFloorSVG`, so they all share the same coordinate system and a tile at grid
`(x,y)` maps to pixel rect `(x*32 + 32, y*32 + 32, 32, 32)` on every layer.

## 2. Per-turn data flow

`WS` receives a `state` message, which is handed to `GameMap.updateEntities()` and
`GameMap.updateFOV()`, then `GameMap.flush()` redraws.

```
  server (WebClient)                    client (GameMap)
  ────────────────                      ─────────────
  _gather_entities()  ──entities──▶  updateEntities()  ▶ this.entities
  _gather_doors()     ──doors─────▶                      this.doorInfo, this.allDoors
  _gather_fov()       ──fov (full/   updateFOV()       ▶ this.fov  (Set<"x,y">)
                         delta)                          this.explored += fov
  _gather_walk()      ──walk (full/                      this.walls  (Map<"x,y", mask>)
                         delta)                          this.exploredWalls += walk

                                      flush() {
                                        clearHatch(walls)   // z=1
                                        drawFog()           // z=2
                                        draw()              // z=3 (entities)
                                        scrollToPlayer()
                                      }
```

Five pieces of state matter for distance/dimming:

| name | type | meaning |
|---|---|---|
| `fov` | `Set<"x,y">` | tiles **currently visible** this turn |
| `explored` | `Set<"x,y">` | union of every tile ever in `fov` |
| `walls` / `exploredWalls` | `Map<"x,y", mask4>` | walkable tiles with a 4-bit wall-edge mask (N=1, E=2, S=4, W=8) |
| `lastSeen` | `Map<"x,y", turn>` | turn each tile was last in `fov`; feeds the recency boost (4e) |
| `turn` | `int` | current turn counter; used as the reference for `age = turn − lastSeen[key]` |

## 3. The hatch layer (memory mask)

The hatch is **accumulating, not per-turn**. It is stamped once when `loadHatchSVG()`
finishes:

```
  ┌─ hatch-canvas ───────────┐
  │ ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱ │   fillStyle = pattern(hatch.svg)
  │ ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱ │   fillRect(0,0,W,H)
  │ ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱ │
  └──────────────────────────┘
```

Every turn, `clearHatch(walls)` traces the polygonal perimeter of the **currently
walkable-visible** set and punches it through the hatch via
`globalCompositeOperation = "destination-out"`:

```
  step 1: _buildTileSetPolygons(walls)
  ─────────────────────────────────
       per tile in walls: emit 4 directed edges
       where the neighbour is NOT in walls, each
       edge tagged {ax,ay,bx,by,wall: bit set in mask}

  step 2: stitch edges by shared endpoint → closed loops
  step 3: _offsetLoop(loop, +2px) along outward normal,
          but ONLY for edges marked wall=true
          → non-wall boundary edges stay on the tile grid
            so a torch cutoff across open floor does not
            bleed the hole sideways
  step 4: destination-out fill over all loops
```

Why "only wall edges inflate by 2 px"? The SVG's wall lines have a ~4 px width
centered on the tile boundary. Without the 2 px outward nudge, the hatch fill would
clip the wall's outer half and you'd see a hairline notch where hatch meets wall. The
inflation is purely cosmetic — it is not distance-dependent, and it does **not**
apply to torch boundaries.

```
   wall edge (tile<->void):           non-wall edge (tile<->tile):
                                      (FOV boundary across floor)
   ╱╱╱╱╱╱╱╱╱ <- hatch                 ╱╱╱╱╱╱╱╱╱
   ╱╱╱────── <- inflated by +2px      ╱╱╱──────
           │                                  │
       wall│floor                        floor│floor (this tile
           │                                  │ not walkable yet)
```

Because the canvas accumulates, once a cell has been revealed its hole persists
forever. On floor re-entry or WS reconnect, `loadHatchSVG` re-stamps the whole
pattern and then runs **one bulk** `clearHatch(exploredWalls)` — which is why the
server sends the explored set eagerly.

Important: **the hatch layer has no distance awareness and no alpha gradient.** It
is binary: either a hole (seen once) or opaque hatch (never seen). All the visible
distance effects live one layer up, on the fog canvas.

## 4. The fog canvas — where distance dimming lives

`drawFog()` rebuilds the fog layer from scratch every `flush()`. There is no
accumulation here.

### 4a. Start fully dark

```js
ctx.clearRect(0, 0, mapW, mapH);
ctx.fillStyle = "rgba(0, 0, 0, 1.0)";
ctx.fillRect(0, 0, mapW, mapH);
```

```
  ┌─ fog-canvas ─────────────┐
  │ ███████████████████████  │   α = 1.0 everywhere
  │ ███████████████████████  │
  │ ███████████████████████  │
  └──────────────────────────┘
```

### 4b. Dynamic radii from current FOV extent

The clever distance bit: the torch is sized **to this turn's actual visible extent**,
not a constant. The JS loops over every FOV tile and measures pixel distance from
the player's tile center to each visible tile's center:

```js
let maxDist = 0;
for (const key of this.fov) {
  const tx = x * cs + padding + half;
  const ty = y * cs + padding + half;
  const d = Math.hypot(tx - cx, ty - cy);
  if (d > maxDist) maxDist = d;
}
maxDist += cs;

const innerR = maxDist * 0.2 + half;   // bright core
const outerR = maxDist + cs;           // gradient reaches beyond FOV edge
```

So in a tight corridor `maxDist` might be ~4 tiles; in a large open room it might be
~10 tiles. The torch scales to match. `innerR` is always 20 % of the current reach,
`outerR` is one tile beyond it.

```
                    player
                      @
                      ·
            ┌── innerR ──┐      (20% of maxDist + half)
     ┌──────── outerR ────────┐ (maxDist + one tile)
```

### 4c. Radial gradient: transparent core → dim edge

The gradient is **subtractive** — it punches transparency into the black fog —
implemented as two passes to get both a crisp outer circle and a smooth interior
fade:

```js
// pass 1: punch a hard-edged disc of radius outerR, fully clearing
//         the fog inside. Uses destination-out + white fill.
ctx.globalCompositeOperation = "destination-out";
ctx.arc(cx, cy, outerR, 0, 2*π);  fill "white"

// pass 2: paint the gradient in source-over on top of the cleared
//         disc. The gradient re-introduces darkening as you move
//         away from the center.
ctx.globalCompositeOperation = "source-over";
ctx.fillStyle = radialGradient(
  (0.00, "rgba(0,0,0,0.00)"),                  // center: transparent
  (innerR/outerR,            "rgba(0,0,0,0.00)"),  // bright-zone edge: still 0
  ((innerR+half)/outerR ≲ 0.95, "rgba(0,0,0,0.30)"), // kicker band ~0.3
  (1.00,                     "rgba(0,0,0,dimAlpha)") // outer rim (dimAlpha=0.7)
);
ctx.arc(cx, cy, outerR, 0, 2*π);  fill gradient
```

The four color stops give a curve that looks like:

```
  α
 0.70 ┤                                  ·••••  <- outer rim (dimAlpha)
      │                              ·•••
      │                         ·••••
 0.30 ┤                   ·•••·                 <- smooth transition
      │              ·•••
      │         ·•••
 0.00 ┤·········                                <- bright core
      └──────┬──────────┬───────────────────┬──►  r
             0       innerR               outerR
           (0%)      (20%)                (100%)
             ↑          ↑                   ↑
          fully      end of             gradient
        transparent  bright             rim (dim)
                     zone
```

The outer rim of the gradient is **not** the same value as the memory tiles
outside `outerR`. The rim is a single fixed `dimAlpha = 0.7`, while memory
tiles use the distance-scaled `memFloor → memCeil` curve described in 4d. The
two paths can therefore disagree by up to ±0.15 alpha at the seam, but the
disagreement is smooth in distance, so the eye reads the boundary as continuous
falloff rather than a step.

Read it as three distance bands:

| band | r range | fog α | reading |
|---|---|---|---|
| **core** | 0 → innerR | 0 | adjacent tiles are fully lit |
| **falloff** | innerR → ~innerR+half | 0 → 0.3 | slight tint |
| **torch edge** | ~innerR+half → outerR | 0.3 → 0.7 | steadily dimmer |
| (beyond outerR, see 4d) | | | |

Put the whole thing together visually (player at `@`, darkness at `█`, shades of
visibility in between):

```
                                        outside FOV (explored):
                                            α ∈ [0.45, 0.75] (see 4e)
                    ░░░░░░░░░░░             — distance + recency
                ░▒▒▒▒▒▒▒▒▒▒▒▒▒░░░         outside FOV (not explored):
              ░▒▒...........▒▒▒░░           α = 1.00  (untouched black)
             ░▒..............▒▒░░
            ░▒.......@.......▒▒░░ ← bright core (α = 0)
             ░▒..............▒▒░░           falloff band (α ≈ 0.3)
              ░▒▒..........▒▒▒░░            torch edge (α → 0.7)
                ░▒▒▒▒▒▒▒▒▒▒▒▒▒░
                    ░░░░░░░░░░░             memory α ∈ [0.55, 0.75] (see 4d)
```

The gradient center is pinned to the player's pixel center, so if the player is near
a wall and the FOV is lopsided (more reach to one side), the gradient is still
circular and centred on the player — one side bottoms out at full dim before the
other does. The `maxDist` math uses the *farthest* visible tile, so the wide side
gets a smooth falloff and the short side sits in the still-transparent core. No
artifacts.

### 4d. FOV tiles outside the gradient disc

Because FOV is computed via symmetric shadowcasting, a rare FOV tile can sit
*outside* `outerR` (e.g., visible through a chain of doors that let the polygon
reach further than its bounding disc). A tail loop fixes those up: any FOV tile
whose center's squared distance exceeds `outerR²` gets its 32×32 cell manually
cleared and refilled at a **distance-scaled** memory dim level rather than a
flat shade — so the falloff blends smoothly with the gradient instead of forming
a visible slab where the disc ends:

```js
const memFloor = 0.55;          // brightest memory tile (close to player)
const memCeil  = 0.75;          // darkest memory tile (far from player)
const memReach = outerR * 1.5;  // distance where alpha saturates at memCeil

for (const key of this.fov) {
  if (d² > outerR²) {
    const d = Math.sqrt(d²);
    const t = Math.min(d / memReach, 1);
    const a = memFloor + (memCeil - memFloor) * t;  // 0.55 → 0.75 lerp
    ctx.clearRect(px, py, cs, cs);
    ctx.fillStyle = `rgba(0,0,0,${a})`;
    ctx.fillRect(px, py, cs, cs);
  }
}
```

The result is a per-tile hard rectangle (no within-cell gradient), but the
*chosen* alpha for each tile lerps from `memFloor=0.55` near the player to
`memCeil=0.75` once distance reaches `1.5 × outerR`. Past `memReach` the alpha
saturates so very distant FOV tiles never go fully black.

### 4e. Explored-but-not-visible ("memory")

The `explored \ fov` difference uses the **same** distance-scaled memory formula
as 4d, plus a small **recency boost**: tiles the player has seen within the
last 30 turns are drawn a touch brighter, with the boost decaying linearly to
zero over that window.

```js
const recencyWindow = 30;

for (const key of this.explored) {
  if (this.fov.has(key)) continue;
  const d = Math.hypot(tx - cx, ty - cy);
  const t = Math.min(d / memReach, 1);
  let a = memFloor + (memCeil - memFloor) * t;   // 0.55 → 0.75 by distance

  const seen = this.lastSeen.get(key);
  if (seen !== undefined) {
    const age = Math.max(0, this.turn - seen);
    const recency = Math.max(0, 1 - age / recencyWindow);
    a -= 0.10 * recency;     // up to -0.10 for freshly-left tiles
  }

  ctx.clearRect(px, py, cs, cs);
  ctx.fillStyle = `rgba(0,0,0,${a})`;
  ctx.fillRect(px, py, cs, cs);
}
```

The `clearRect` before the fill is critical: without it the rectangle would
composite on top of whatever the gradient left in that cell, double-darkening it.
Clearing first guarantees exactly the chosen alpha.

Two perceptual effects fall out of this:

- **Distance grading**: rooms close to the player stay brighter in memory than
  rooms two corridors over, even if both were last visited the same turn.
- **Recency afterglow**: a tile the player just stepped off is at most 0.10
  alpha brighter than its base, fading back to the distance-only level over 30
  turns. This is what makes the floor "remember" the path you just walked.

Note that `dimAlpha = 0.7` is now used **only** as the gradient's outer stop in
4c — it is no longer the universal memory level the way the source comment on
that constant suggests. Memory tiles run on the `memFloor`/`memCeil` curve, not
on `dimAlpha`.

### 4f. Zero-FOV fallback (player blinded or off-map)

If `this.fov` is empty for the turn — for example the player is blinded, or the
state message arrived before the first FOV update — the gradient pass and both
distance loops are skipped entirely. Instead a single fallback loop fills every
explored tile at a flat dim level:

```js
if (this.fov.size === 0) {
  for (const key of this.explored) {
    ctx.clearRect(px, py, cs, cs);
    ctx.fillStyle = "rgba(0,0,0,0.75)";
    ctx.fillRect(px, py, cs, cs);
  }
}
```

This branch deliberately skips both the distance lerp and the recency boost —
neither makes sense without a player viewpoint to measure from — and just lands
on the memory ceiling so the map stays legible at uniform dimness.

## 5. Full per-tile decision table

Combining hatch (z=1) and fog (z=2) with the floor SVG and doors beneath:

```
  tile status              │ hatch    │ fog α          │ resulting look
  ─────────────────────────┼──────────┼────────────────┼───────────────────────
  never explored           │ ╱╱╱╱╱    │ 1.00           │ pure black (fog wins;
                           │          │                │  hatch would show if
                           │          │                │  fog were thinner)
  explored, not in FOV     │ cleared  │ 0.45 → 0.75    │ dim SVG + faint doors
   (no FOV this turn)      │          │ flat 0.75      │  (zero-FOV fallback)
   (recently left)         │          │ −0.10 boost    │  brief afterglow
  in FOV, r > outerR       │ cleared  │ 0.55 → 0.75    │ dim (distance lerp)
  in FOV, torch edge       │ cleared  │ ~0.5           │ dim-ish (gradient)
  in FOV, falloff band     │ cleared  │ ~0.2           │ mostly lit
  in FOV, bright core      │ cleared  │ 0.00           │ fully lit SVG
```

Two distinct dim curves coexist:

- **Inside `outerR`** (gradient zone) the alpha follows the radial gradient
  stops `0 → 0.3 → 0.7` defined in 4c.
- **Outside `outerR`** (FOV tail in 4d, memory tiles in 4e, fallback in 4f)
  the alpha follows the linear `memFloor → memCeil` curve over `memReach`,
  optionally adjusted by the recency boost on the memory path.

And entities on z=3 render at full alpha *unconditionally*, so the `@`, creatures,
and items are always at their true color regardless of the fog under them. A mob at
the torch edge still reads as crisp white/red text on a dim floor.

## 6. Why this layered approach

The split between hatch and fog pays off in three ways:

1. **Hatch is accumulating (cheap)**, fog is rebuilt from scratch (correct).
   Rebuilding the hatch every turn would require re-rasterising the whole pattern;
   instead, the hatch is stamped once per floor and touched via destination-out only
   at new reveals. Fog is simple enough to redraw each turn and needs to be — it
   tracks this-turn visibility exactly.
2. **"Never seen" vs "seen but dim" are visually distinct.** Hatch gives unexplored
   areas a pattern, fog gives dim areas a flat shade. If fog did both, unexplored
   and explored-dim would look identical.
3. **Distance math stays on one layer.** All the `Math.hypot`, gradient stops, and
   `d² > outerR²` logic lives in `drawFog()`. Hatch never needs to know about radii.

## 7. Constants and knobs in one place

If you ever want to retune the look, everything is in `drawFog()`:

```js
// Geometry — must match the SVG renderer
cellSize         = 32                    // tile size
padding          = 32                    // outer border

// Gradient zone (inside outerR) — section 4c
innerR           = maxDist * 0.2 + 16    // bright core radius
outerR           = maxDist + 32          // gradient reach (one tile past FOV)
dimAlpha         = 0.7                   // gradient outer rim only
gradient stops   = [(0, 0),              // center: transparent
                    (innerR/outerR, 0),  // bright core ends
                    (~0.95, 0.3),        // kicker band
                    (1.0, dimAlpha)]     // outer rim

// Memory zone (outside outerR + explored\fov) — sections 4d, 4e
memFloor         = 0.55                  // brightest memory tile (close)
memCeil          = 0.75                  // darkest memory tile (far)
memReach         = outerR * 1.5          // distance where alpha saturates

// Recency boost on the explored\fov path — section 4e
recencyWindow    = 30                    // turns over which the boost decays
recencyBoostMax  = 0.10                  // alpha subtracted for fresh tiles

// Zero-FOV fallback — section 4f
fallbackAlpha    = 0.75                  // flat dim when fov is empty
```

`maxDist` is the only dynamic input — it makes the whole system follow the
player's current line of sight instead of using a constant lantern radius. That
is what makes torchlight feel "right" whether you are in a corridor or a large
room. `memReach` derives from `maxDist` indirectly (via `outerR`), so the
memory falloff also tracks the FOV scale: in a wide room the player will see
more graded memory levels than in a tight corridor.
