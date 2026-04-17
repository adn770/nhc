/**
 * Overland hexcrawl renderer.
 *
 * Consumes ``state_hex`` WebSocket payloads and paints a five-layer
 * canvas stack (base → fog → features → entities → debug) above the
 * same map-container used by the dungeon view. Tile art is loaded
 * lazily from /hextiles/<biome>/<slot>-<biome>_<feature>.png; a
 * missing tile falls back to a solid colour cell plus a glyph.
 *
 * Conventions:
 * - Flat-top axial coords; q steps SE, r steps S.
 * - Pixel projection matches nhc/hexcrawl/coords.py:to_pixel:
 *     x = size * 1.5 * q
 *     y = size * (sqrt(3)/2 * q + sqrt(3) * r)
 */

const HEX_SIZE = 36;            // hex radius (centre → corner), logical px
const HEX_WIDTH = 2 * HEX_SIZE;                 // corner-to-corner
const HEX_HEIGHT = Math.sqrt(3) * HEX_SIZE;     // edge-to-edge
const HEX_MARGIN = HEX_SIZE;    // padding on all four sides

// Canvas resolution multiplier. Tile PNGs are 238x207; at
// HEX_WIDTH=72 that's ~3.3x downscale. Drawing at this factor
// makes tiles render at their native resolution. The CSS
// transform compensates so the visual size stays the same.
const CANVAS_SCALE = 238 / HEX_WIDTH;

/** Slot number to filename stem. The hextiles pack uses literal
 * (and quirky) casing / spelling -- match files on disk exactly.
 * See ls hextiles/greenlands/ for the source of truth. */
const SLOT_NAME = {
  1: "vulcano", 2: "forest", 3: "tundra", 4: "trees", 5: "water",
  6: "hills", 7: "river", 8: "portal", 9: "mountains", 10: "lake",
  11: "village", 12: "city", 13: "tower", 14: "community",
  15: "cave", 16: "hole", 17: "dead-Trees", 18: "ruins",
  19: "graveyard", 20: "swamp", 21: "floating-Island",
  22: "keep", 23: "wonder", 24: "cristals", 25: "stones",
  26: "farms", 27: "fog",
  // forestPack extensions (41-58)
  41: "dense-Forest", 42: "sparse-Trees", 43: "clearing",
  44: "rift", 45: "wild-Bushes", 46: "spider-Lair",
  47: "great-Tree", 48: "mushrooms", 49: "cave-Mouth",
  50: "hillock", 51: "standing-Stones", 52: "cottage",
  53: "hamlet", 54: "watchtower", 55: "overgrown-Ruins",
  56: "blast-Site", 57: "forest-Road", 58: "forest-Temple",
  // mountainPack extensions (61-80)
  61: "mountain-Range", 62: "scattered-Peaks", 63: "plateau",
  64: "active-Vulcano", 65: "mountain-Rift", 66: "foothills",
  67: "rock-Spikes", 68: "mountain-Gates", 69: "summit",
  70: "stone-Bridge", 71: "mountain-Cave", 72: "alpine-Forest",
  73: "obelisk", 74: "mountain-Lodge", 75: "mountain-Village",
  76: "mountain-Tower", 77: "mountain-Ruins", 78: "mountain-Blast",
  79: "mountain-Pass", 80: "mountain-Temple",
};

/** Biome base-tile slots: weighted [slot, weight] pairs for
 * visual variety on featureless hexes. The renderer picks one
 * per hex deterministically so the choice is stable across
 * repaints. Higher weight = more frequent. */
const BIOME_BASE_SLOTS = {
  greenlands: [
    [42, 20], [4, 18], [43, 15], [45, 12], [26, 10], [2, 8],
    [41, 5], [50, 4], [20, 3], [55, 3], [10, 2],
  ],
  forest: [
    [2, 20], [41, 18], [4, 15], [42, 12], [47, 8], [45, 7],
    [43, 5], [6, 4], [48, 3], [50, 3], [20, 3], [55, 2],
  ],
  mountain: [
    [9, 18], [61, 15], [62, 14], [69, 10], [66, 8], [79, 7],
    [67, 6], [63, 5], [6, 5], [72, 4], [65, 4], [70, 4],
  ],
  hills: [
    [6, 22], [45, 16], [50, 14], [4, 12], [42, 10], [3, 10],
    [43, 8], [9, 8],
  ],
  marsh: [
    [20, 25], [3, 18], [17, 14], [6, 12], [42, 9], [45, 7],
    [10, 6], [19, 5], [55, 4],
  ],
  swamp: [
    [20, 28], [17, 18], [3, 12], [45, 10], [42, 8], [10, 8],
    [6, 6], [55, 5], [19, 5],
  ],
  drylands: [
    [3, 30], [6, 20], [17, 15], [20, 12], [9, 10], [4, 8],
    [10, 5],
  ],
  sandlands: [
    [3, 30], [6, 20], [17, 15], [20, 12], [9, 10], [18, 5],
    [19, 4], [4, 4],
  ],
  icelands: [
    [3, 30], [6, 20], [17, 15], [20, 12], [27, 10], [9, 5],
    [10, 4], [18, 4],
  ],
  deadlands: [
    [3, 30], [6, 20], [20, 15], [9, 12], [17, 10], [18, 5],
    [19, 4], [1, 4],
  ],
  water: [[5, 1]],
};

/** Feature-tile variants: when a feature maps to multiple
 * candidate slots, the renderer picks one per hex. Gives visual
 * diversity to e.g. caves (slot 15 vs 49 cave-Mouth).
 *
 * Extended-pack slots (41-80) only exist for biomes with full
 * generated tile sets: greenlands, forest, mountain, hills,
 * marsh, swamp. The base 27-slot tiles exist for all biomes.
 * _EXTENDED_BIOMES gates which biomes may use the extra slots. */
const _EXTENDED_BIOMES = new Set([
  "greenlands", "forest", "mountain", "hills", "marsh", "swamp",
]);
const _FEATURE_BASE = {
  cave:     { base: [15], ext: [49] },     // cave, cave-Mouth
  ruin:     { base: [18], ext: [55] },     // ruins, overgrown-Ruins
  tower:    { base: [13], ext: [54] },     // tower, watchtower
  village:  { base: [11], ext: [53] },     // village, hamlet
  stones:   { base: [25], ext: [51] },     // stones, standing-Stones
  hole:     { base: [16], ext: [44] },     // hole, rift
  keep:     { base: [22], ext: [] },
  city:     { base: [12], ext: [] },
  graveyard:{ base: [19], ext: [] },
  crystals: { base: [24], ext: [] },
  wonder:   { base: [23], ext: [] },
  portal:   { base: [8],  ext: [] },
  lake:     { base: [10], ext: [] },
  river:    { base: [7],  ext: [] },
};
/** Return the variant slot array for a feature in a given biome. */
function featureVariants(feature, biome) {
  const entry = _FEATURE_BASE[feature];
  if (!entry) return null;
  if (_EXTENDED_BIOMES.has(biome) && entry.ext.length) {
    return entry.base.concat(entry.ext);
  }
  return entry.base;
}

/** Deterministic per-hex hash with good bit mixing. */
function _hexHash(q, r) {
  let h = ((q * 7919 + r * 104729) & 0x7FFFFFFF);
  h = ((h >> 16) ^ h) * 0x45d9f3b;
  return ((h >> 16) ^ h) & 0x7FFFFFFF;
}

/** Deterministic per-hex pick: (q, r) → index into a variant
 * array. Stable across renders so tiles don't flicker. */
function _hexVariant(q, r, n) {
  return _hexHash(q, r) % n;
}

/** Pick a slot from weighted [slot, weight] pairs using (q, r)
 * as a deterministic seed. */
function _weightedSlot(q, r, pairs) {
  if (pairs.length === 1) return pairs[0][0];
  let total = 0;
  for (const [, w] of pairs) total += w;
  const roll = _hexHash(q, r) % total;
  let acc = 0;
  for (const [slot, w] of pairs) {
    acc += w;
    if (roll < acc) return slot;
  }
  return pairs[pairs.length - 1][0];
}

/** Biomes with a full 27-slot palette; used as the primary tile
 * URL. Any biome in PARTIAL_PALETTE_BIOMES may not have every
 * slot -- _loadTile falls back to the foundation tile at the
 * project root if the biome-specific path 404s. */
const PALETTE_BIOMES = new Set([
  "greenlands", "drylands", "sandlands", "icelands", "deadlands",
  "forest", "mountain", "hills", "marsh", "swamp", "water",
]);
// Biomes whose tilesets don't cover every slot — the renderer
// falls back to the foundation tile when a biome-specific path
// 404s. All generated biomes are partial (they only have the
// slots the generate_missing_hextiles tool produced).
const PARTIAL_PALETTE_BIOMES = new Set([
  "greenlands", "drylands", "sandlands", "icelands", "deadlands",
  "forest", "mountain", "hills", "marsh", "swamp", "water",
]);

/** Fallback glyph when the hextile PNG can't be fetched. */
const BIOME_GLYPH = {
  greenlands: {fg: "#5a8a4e", bg: "#2a3a1e", c: "."},
  drylands:   {fg: "#a08840", bg: "#3a3220", c: "."},
  sandlands:  {fg: "#c0a868", bg: "#4a3e22", c: "."},
  icelands:   {fg: "#a8c0d0", bg: "#283038", c: "~"},
  deadlands:  {fg: "#6a6858", bg: "#2a2824", c: "x"},
  forest:     {fg: "#3a7844", bg: "#1a2e22", c: "T"},
  mountain:   {fg: "#8a8480", bg: "#2a2826", c: "^"},
  hills:      {fg: "#8a9a5a", bg: "#2a3020", c: "n"},
  marsh:      {fg: "#5a7a52", bg: "#1a2a1e", c: "~"},
  swamp:      {fg: "#3a4a34", bg: "#141e14", c: "="},
  water:      {fg: "#3c64a0", bg: "#102040", c: "≈"},
};

/** biome + feature + coord → {primary, fallback} /hextiles/ URLs.
 * The coord (q, r) drives deterministic tile variety: featureless
 * hexes pick from BIOME_BASE_SLOTS, feature hexes pick from
 * FEATURE_VARIANTS, both indexed by _hexVariant so the choice is
 * stable across repaints. */
function tilePath(biome, feature, q, r) {
  let slot;
  const variants = (feature && feature !== "none")
    ? featureVariants(feature, biome) : null;
  if (variants) {
    slot = variants[_hexVariant(q || 0, r || 0, variants.length)];
  } else {
    const bases = BIOME_BASE_SLOTS[biome] || [[4, 1]];
    slot = _weightedSlot(q || 0, r || 0, bases);
  }
  const stem = SLOT_NAME[slot];
  const foundationUrl = `/hextiles/${slot}-foundation_${stem}.png`;
  if (PALETTE_BIOMES.has(biome)) {
    const biomeUrl = `/hextiles/${biome}/${slot}-${biome}_${stem}.png`;
    // Forest / mountain cover only some of the 27 slots; the
    // others fall back to the foundation tile of the same slot.
    const fallback = PARTIAL_PALETTE_BIOMES.has(biome)
      ? foundationUrl
      : null;
    return {primary: biomeUrl, fallback};
  }
  return {primary: foundationUrl, fallback: null};
}

/** Raw axial → pixel without any canvas offset. */
function _rawAxialToPixel(q, r, size = HEX_SIZE) {
  return {
    x: size * 1.5 * q,
    y: size * (Math.sqrt(3) / 2 * q + Math.sqrt(3) * r),
  };
}

/** Pixel origin offset from the server (min_x, min_y of all hex
 * centres). Set on each render so axialToPixel produces canvas-
 * relative coords with uniform HEX_MARGIN padding. */
let _pixelOriginX = 0;
let _pixelOriginY = 0;

/** Current CSS zoom scale on the hex container. */
function _hexZoomScale() {
  if (typeof GameMap !== "undefined") {
    return GameMap._zoomSteps[GameMap._zoomLevel] || 1;
  }
  return 1;
}

/** Convert screen-relative mouse coords (from getBoundingClientRect)
 * to canvas-relative coords, accounting for CSS zoom scale. */
function _screenToCanvas(mx, my) {
  const s = _hexZoomScale();
  return {x: mx / s, y: my / s};
}

/** Axial (q, r) → pixel (x, y) for the centre of the hex,
 * offset so the top-left hex sits at (HEX_MARGIN, HEX_MARGIN). */
function axialToPixel(q, r, size = HEX_SIZE) {
  const raw = _rawAxialToPixel(q, r, size);
  return {
    x: raw.x - _pixelOriginX + HEX_MARGIN + HEX_SIZE,
    y: raw.y - _pixelOriginY + HEX_MARGIN + HEX_SIZE,
  };
}

const HexMap = {
  /** Image cache keyed by URL; prevents repeated fetches. */
  _tileCache: {},

  /** Cached fog tile image (27-foundation_fog.png). Loaded once
   * on first render; used to stamp the fog canvas. */
  _fogTile: undefined,

  /** Cached DOM references for the 6 direction arrow buttons. */
  _arrows: null,

  /** Last known player pixel + show state for the arrow ring. */
  _playerPx: null,
  _arrowsVisible: false,

  /** True while the pointer is over one of the arrow buttons.
   * Prevents the container's mouseleave from hiding the ring
   * mid-hover (the button captures pointer events so the
   * container thinks the cursor left it). */
  _pointerOnArrow: false,

  /** Scroll the player into view exactly once per hex-mode
   * session so the overland doesn't open with the player off to
   * one corner. Re-armed when the view leaves and returns. */
  _scrolledOnce: false,
  _lastState: null,

  /** True after the static layers (base, features, fog
   * background) have been drawn for this world. Reset on
   * game restart / dungeon re-entry. */
  _staticDrawn: false,

  /** Set of "(q,r)" keys for hexes already punched through
   * the fog canvas. Lets us punch incrementally instead of
   * redrawing the entire fog layer each turn. */
  _punchedHexes: new Set(),

  /** Hover threshold: arrows appear when the pointer lies inside
   * this many px of the player hex centre. The arrow centres sit
   * at 1.5 * neighbour_offset (i.e. the far edge of the next hex)
   * which is ~2.6 hex-radii away, so bump this a little to keep
   * them visible while the cursor is on them. */
  _HOVER_RADIUS: HEX_SIZE * 4.0,

  /** Last player coord the arrow ring was positioned for. Lets
   * us skip reposition work when the player hasn't moved. */
  _lastArrowCoord: null,




  /** Lazily build the six arrow button DOM nodes and attach the
   * mouse handlers once. Subsequent renders only update positions. */
  _ensureArrows() {
    if (this._arrows) return this._arrows;
    const hud = document.getElementById("hex-hud");
    const container = document.getElementById("hex-container");
    if (!hud || !container) return null;
    // Directions match NEIGHBOR_OFFSETS order in coords.py:
    //   N, NE, SE, S, SW, NW. rot is the CSS rotation applied
    //   inside the SVG so the base "up" shape points the right
    //   way. Rotation is 0 / 60 / 120 / 180 / 240 / 300 degrees
    //   for a flat-top hex grid.
    const dirs = [
      {dq: 0,  dr: -1, rot: 0,   key: "8", title: "North (8/k)"},
      {dq: 1,  dr: -1, rot: 60,  key: "9", title: "North-east (9/u)"},
      {dq: 1,  dr: 0,  rot: 120, key: "3", title: "South-east (3/n)"},
      {dq: 0,  dr: 1,  rot: 180, key: "2", title: "South (2/j)"},
      {dq: -1, dr: 1,  rot: 240, key: "1", title: "South-west (1/b)"},
      {dq: -1, dr: 0,  rot: 300, key: "7", title: "North-west (7/y)"},
    ];
    const svgMarkup = (rot, key) => (
      '<svg viewBox="0 0 64 64" width="64" height="64"' +
      ' xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
      `<g transform="rotate(${rot} 32 32)">` +
      '<path d="M 32 4 L 58 58 L 32 44 L 6 58 Z"' +
      ' fill="#5c9cff" fill-opacity="0.28"' +
      ' stroke="#1b2f5c" stroke-width="2.5"' +
      ' stroke-linejoin="round"/>' +
      '<path d="M 32 4 L 32 44"' +
      ' stroke="#1b2f5c" stroke-width="2" stroke-linecap="round"/>' +
      "</g>" +
      // Number label: counter-rotate so it stays upright
      // regardless of arrow direction. Positioned near the
      // centre of the delta shape.
      `<text x="32" y="36" text-anchor="middle"` +
      ` dominant-baseline="central"` +
      ` font-size="14" font-weight="bold" font-family="monospace"` +
      ` fill="#a0c4ff" fill-opacity="0.9"` +
      ` stroke="#0a1428" stroke-width="2" paint-order="stroke">` +
      `${key}</text></svg>`
    );
    const arrows = dirs.map(d => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hex-arrow";
      btn.innerHTML = svgMarkup(d.rot, d.key);
      btn.title = d.title;
      btn.dataset.dq = String(d.dq);
      btn.dataset.dr = String(d.dr);
      btn.style.display = "none";
      btn.addEventListener("click", ev => {
        ev.preventDefault();
        ev.stopPropagation();
        WS.send({
          type: "action", intent: "hex_step",
          data: [d.dq, d.dr],
        });
      });
      // While the pointer is on an arrow the button itself is
      // the target and the container's mousemove/mouseleave no
      // longer fire. Force the ring to stay visible through the
      // click.
      btn.addEventListener("mouseenter", () => {
        this._pointerOnArrow = true;
        this._setArrowsVisible(true);
      });
      btn.addEventListener("mouseleave", () => {
        this._pointerOnArrow = false;
        // Re-evaluate on the next container mousemove; if the
        // cursor lands back in the canvas area the proximity
        // check will decide. If it goes outside the container
        // entirely, the container's mouseleave below hides.
      });
      hud.appendChild(btn);
      return btn;
    });
    // Track pointer over the WHOLE container (canvas stack). The
    // hud overlay has pointer-events: none so it doesn't swallow
    // the mousemove; the buttons themselves re-enable pointer
    // events so their clicks still land.
    container.addEventListener("mousemove", ev => {
      if (!this._playerPx) return;
      const rect = container.getBoundingClientRect();
      const {x: mx, y: my} = _screenToCanvas(
        ev.clientX - rect.left, ev.clientY - rect.top);
      const dx = mx - this._playerPx.x;
      const dy = my - this._playerPx.y;
      const near = (dx * dx + dy * dy)
        <= (this._HOVER_RADIUS * this._HOVER_RADIUS);
      this._setArrowsVisible(near);
    });
    container.addEventListener("mouseleave", () => {
      // Keep the ring up while the cursor is hovering one of
      // the arrow buttons -- that counts as "near".
      if (this._pointerOnArrow) return;
      this._setArrowsVisible(false);
    });
    this._arrows = arrows;
    return arrows;
  },

  /** Scroll #map-zone so the player pixel lands in the middle of
   * the viewport. Called once on game start / reload. */
  _centerOnPlayer() {
    if (!this._playerPx) return;
    const zone = document.getElementById("map-zone");
    const container = document.getElementById("hex-container");
    if (!zone || !container) return;
    const scale = _hexZoomScale();
    // Player canvas coords → scaled screen coords.
    const px = this._playerPx.x * scale;
    const py = this._playerPx.y * scale;
    const z = zone.getBoundingClientRect();
    const c = container.getBoundingClientRect();
    const offsetX = (c.left - z.left) + zone.scrollLeft;
    const offsetY = (c.top - z.top) + zone.scrollTop;
    zone.scrollTo({
      left: Math.max(0, offsetX + px - zone.clientWidth / 2),
      top: Math.max(0, offsetY + py - zone.clientHeight / 2),
      behavior: "auto",
    });
  },

  _autoFitZoom() {
    const zone = document.getElementById("map-zone");
    const container = document.getElementById("hex-container");
    if (!zone || !container || typeof GameMap === "undefined") return;
    // Use hex content extent (without margin/padding) for fit calc
    const contentW = (this._contentW || 400) + HEX_WIDTH;
    const contentH = (this._contentH || 400) + HEX_HEIGHT;
    const zw = zone.clientWidth;
    const zh = zone.clientHeight;
    const fitScale = Math.min(zw / contentW, zh / contentH, 2.0);
    const steps = GameMap._zoomSteps;
    let best = 0;
    for (let i = 0; i < steps.length; i++) {
      if (steps[i] <= fitScale + 0.01) best = i;
    }
    GameMap._zoomLevel = best;
    const scale = steps[best];
    for (const id of ["map-container", "hex-container"]) {
      const el = document.getElementById(id);
      if (el) {
        el.style.transformOrigin = "center top";
        el.style.transform = `scale(${scale})`;
      }
    }
    const fc = document.getElementById("flower-container");
    if (fc) {
      fc.style.transformOrigin = "center top";
      fc.style.transform = `scale(${scale})`;
    }
    if (typeof Input !== "undefined") Input._updateZoomLabel();
  },

  _setArrowsVisible(on) {
    if (!this._arrows) return;
    if (this._arrowsVisible === on) return;
    this._arrowsVisible = on;
    for (const btn of this._arrows) {
      btn.style.display = on ? "flex" : "none";
    }
  },

  _positionArrows(playerCoord, playerPx) {
    // Skip the style writes when the player hasn't moved; the
    // arrows stay anchored to their HUD-relative pixel offsets
    // across canvas repaints.
    if (this._lastArrowCoord
        && this._lastArrowCoord.q === playerCoord.q
        && this._lastArrowCoord.r === playerCoord.r) {
      return;
    }
    const arrows = this._ensureArrows();
    if (!arrows) return;
    for (const btn of arrows) {
      const dq = parseInt(btn.dataset.dq, 10);
      const dr = parseInt(btn.dataset.dr, 10);
      // Place the arrow centre at the neighbour's far edge (the
      // edge of the next hex that is farther from the player).
      // 1.5x the per-axis pixel offset to the neighbour centre.
      const ox = HEX_SIZE * 1.5 * dq;
      const oy = HEX_SIZE * (Math.sqrt(3) / 2 * dq + Math.sqrt(3) * dr);
      btn.style.left = `${playerPx.x + 1.5 * ox}px`;
      btn.style.top = `${playerPx.y + 1.5 * oy}px`;
    }
    this._lastArrowCoord = {q: playerCoord.q, r: playerCoord.r};
  },

  /** Cached output of the last resize(); avoids assigning width/
   * height (a canvas reset that flashes the view) when the map
   * dimensions haven't changed. */
  _sizedTo: null,

  /** Resize all five hex canvases to ``pixelW × pixelH`` plus
   * hex-margin padding. No-op when the pixel box would be the
   * same as the last call -- assigning canvas.width even to the
   * same value clears the canvas. */
  resize(pixelW, pixelH) {
    // Logical dimensions (used for CSS container size).
    const lx = Math.ceil(pixelW + 2 * HEX_SIZE + 2 * HEX_MARGIN);
    const ly = Math.ceil(pixelH + 2 * HEX_SIZE + 2 * HEX_MARGIN);
    if (this._sizedTo
        && this._sizedTo.lx === lx
        && this._sizedTo.ly === ly) {
      return;
    }
    this._sizedTo = {lx, ly};
    // Canvas internal resolution: logical * CANVAS_SCALE so tiles
    // render at their native PNG resolution.
    const cx = Math.ceil(lx * CANVAS_SCALE);
    const cy = Math.ceil(ly * CANVAS_SCALE);
    const container = document.getElementById("hex-container");
    if (container) {
      container.style.width = `${lx}px`;
      container.style.height = `${ly}px`;
    }
    const canvases = [
      "hex-base-canvas", "hex-fog-canvas", "hex-feature-canvas",
      "hex-entity-canvas", "hex-debug-canvas",
    ];
    canvases.forEach(id => {
      const c = document.getElementById(id);
      if (!c) return;
      c.width = cx;
      c.height = cy;
      // CSS size matches logical size; the extra canvas pixels
      // give us higher resolution within the same visual area.
      c.style.width = `${lx}px`;
      c.style.height = `${ly}px`;
    });
  },

  /** Load and cache an image. Accepts a primary URL and an
   * optional fallback URL; tries primary first and on error
   * tries the fallback. The cache is keyed by the primary URL
   * so a second lookup for the same (biome, feature) hits the
   * cache regardless of which URL resolved. */
  _loadTile(primary, fallback = null) {
    if (primary in this._tileCache) {
      return Promise.resolve(this._tileCache[primary]);
    }
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => {
        this._tileCache[primary] = img;
        resolve(img);
      };
      img.onerror = () => {
        if (!fallback || fallback === primary) {
          this._tileCache[primary] = null;
          resolve(null);
          return;
        }
        const img2 = new Image();
        img2.onload = () => {
          this._tileCache[primary] = img2;
          resolve(img2);
        };
        img2.onerror = () => {
          this._tileCache[primary] = null;
          resolve(null);
        };
        img2.src = fallback;
      };
      img.src = primary;
    });
  },

  /** Main entry point, called on every state_hex payload.
   *
   * Static layers (base tiles, features, fog background) are
   * drawn only once on the first call. Subsequent calls just
   * punch newly-revealed hexes through the fog and reposition
   * the player glyph — no full redraw. */
  async render(state) {
    this._lastState = state;

    const base = document.getElementById("hex-base-canvas");
    const fog = document.getElementById("hex-fog-canvas");
    const ent = document.getElementById("hex-entity-canvas");
    if (!base || !fog || !ent) return;
    const baseCtx = base.getContext("2d");
    const fogCtx = fog.getContext("2d");
    const entCtx = ent.getContext("2d");
    if (!baseCtx || !fogCtx || !entCtx) return;

    _pixelOriginX = state.pixel_origin_x || 0;
    _pixelOriginY = state.pixel_origin_y || 0;
    const pw = state.pixel_width || 0;
    const ph = state.pixel_height || 0;
    this._contentW = pw;
    this._contentH = ph;

    // ── Static layers: drawn once per world ──
    if (!this._staticDrawn) {
      this.resize(pw, ph);

      const feat = document.getElementById("hex-feature-canvas");
      const featCtx = feat ? feat.getContext("2d") : null;

      // Load all tile images + fog tile in parallel.
      const tileLoads = state.cells.map(cell => {
        const urls = tilePath(cell.biome, cell.feature, cell.q, cell.r);
        return this._loadTile(urls.primary, urls.fallback)
          .then(img => ({cell, img}));
      });
      if (this._fogTile === undefined) {
        this._fogTile = null;
        tileLoads.push(
          this._loadTile("/hextiles/27-foundation_fog.png")
            .then(img => { this._fogTile = img; return null; }),
        );
      }
      const placements = (await Promise.all(tileLoads)).filter(Boolean);

      // All drawing uses logical coords (HEX_SIZE-based). The
      // CANVAS_SCALE transform makes them fill the high-res canvas.
      baseCtx.save();
      baseCtx.scale(CANVAS_SCALE, CANVAS_SCALE);
      for (const {cell, img} of placements) {
        const {x, y} = axialToPixel(cell.q, cell.r);
        if (img) {
          baseCtx.drawImage(
            img,
            x - HEX_WIDTH / 2, y - HEX_HEIGHT / 2,
            HEX_WIDTH, HEX_HEIGHT,
          );
        } else {
          this._drawGlyphFallback(baseCtx, cell, x, y);
        }
      }
      baseCtx.restore();

      // Feature canvas: rivers and paths.
      if (featCtx) {
        featCtx.save();
        featCtx.scale(CANVAS_SCALE, CANVAS_SCALE);
        for (const {cell} of placements) {
          if (!cell.edges) continue;
          const {x, y} = axialToPixel(cell.q, cell.r);
          for (const seg of cell.edges) {
            this._drawEdgeSegment(featCtx, x, y, cell.q, cell.r, seg);
          }
        }
        featCtx.restore();
      }

      // Fog canvas: blue fill + fog tile on every hex.
      fogCtx.save();
      fogCtx.scale(CANVAS_SCALE, CANVAS_SCALE);
      fogCtx.fillStyle = "#87CEEB";
      // fillRect in logical coords covers the full canvas
      // (scale transform maps it to real pixels).
      fogCtx.fillRect(0, 0,
        fog.width / CANVAS_SCALE, fog.height / CANVAS_SCALE);
      for (const {cell} of placements) {
        if (this._fogTile) {
          const {x, y} = axialToPixel(cell.q, cell.r);
          fogCtx.drawImage(
            this._fogTile,
            x - HEX_WIDTH / 2, y - HEX_HEIGHT / 2,
            HEX_WIDTH, HEX_HEIGHT,
          );
        }
      }
      fogCtx.restore();

      this._punchedHexes.clear();
      this._staticDrawn = true;
    }

    // ── Incremental fog: punch only newly-revealed hexes ──
    fogCtx.save();
    fogCtx.scale(CANVAS_SCALE, CANVAS_SCALE);
    for (const cell of state.cells) {
      if (!cell.revealed) continue;
      const key = `${cell.q},${cell.r}`;
      if (this._punchedHexes.has(key)) continue;
      const {x, y} = axialToPixel(cell.q, cell.r);
      this._punchHex(fogCtx, x, y);
      this._punchedHexes.add(key);
    }
    fogCtx.restore();

    // ── Entity layer: player glyph (redrawn each turn) ──
    entCtx.save();
    // clearRect needs real canvas pixels (no transform).
    entCtx.clearRect(0, 0, ent.width, ent.height);
    entCtx.scale(CANVAS_SCALE, CANVAS_SCALE);
    if (state.player) {
      const {x, y} = axialToPixel(state.player.q, state.player.r);
      this._playerPx = {x, y};
      this._drawPlayerAvatar(entCtx, x, y);
      this._positionArrows(state.player, this._playerPx);
      if (!this._scrolledOnce) {
        this._autoFitZoom();
        this._scrolledOnce = true;
      }
      this._centerOnPlayer();
    }
    entCtx.restore();
  },

  /** Draw the player "@" glyph on the entity canvas. */
  _drawPlayerAvatar(ctx, cx, cy) {
    ctx.save();
    ctx.font = "bold 32px monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    // Outline stroke
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#1a3a6b";
    ctx.lineJoin = "round";
    ctx.strokeText("@", cx, cy);
    // Fill
    ctx.fillStyle = "#999999";
    ctx.fillText("@", cx, cy);
    ctx.restore();
  },

  /** Edge midpoint for flat-top hex, indexed by NEIGHBOR_OFFSETS
   * direction (0=N, 1=NE, 2=SE, 3=S, 4=SW, 5=NW). Returns {x, y}
   * relative to hex centre. */
  _edgeMidpoint(edgeIndex, size) {
    const R = size;
    const s3 = Math.sqrt(3);
    const mids = [
      [0, -R * s3 / 2],              // 0: N
      [3 * R / 4, -R * s3 / 4],      // 1: NE
      [3 * R / 4,  R * s3 / 4],      // 2: SE
      [0,  R * s3 / 2],              // 3: S
      [-3 * R / 4,  R * s3 / 4],     // 4: SW
      [-3 * R / 4, -R * s3 / 4],     // 5: NW
    ];
    const [dx, dy] = mids[edgeIndex];
    return {x: dx, y: dy};
  },

  /** Draw a single river or path segment as a quadratic Bezier
   * curve between the entry and exit edge midpoints (or hex centre
   * for source/sink). Deterministic jitter from (q, r) keeps the
   * curve stable across repaints. */
  _drawEdgeSegment(ctx, cx, cy, q, r, seg) {
    // When sub-hex waypoints are available, use them for smoother
    // curves. The sub_path coords are local flower coords that map
    // into the macro hex at a fraction of HEX_SIZE.
    if (seg.sub_path && seg.sub_path.length >= 2) {
      this._drawSubPathCurve(ctx, cx, cy, seg);
      return;
    }

    // Fallback: single-control-point quadratic Bezier.
    let p0, p1;
    if (seg.entry !== null && seg.entry !== undefined) {
      const m = this._edgeMidpoint(seg.entry, HEX_SIZE);
      p0 = {x: cx + m.x, y: cy + m.y};
    } else if (seg.exit !== null && seg.exit !== undefined) {
      const m = this._edgeMidpoint(seg.exit, HEX_SIZE);
      p0 = {x: cx + m.x * 3 / 4, y: cy + m.y * 3 / 4};
    } else {
      p0 = {x: cx, y: cy};
    }
    if (seg.exit !== null && seg.exit !== undefined) {
      const m = this._edgeMidpoint(seg.exit, HEX_SIZE);
      p1 = {x: cx + m.x, y: cy + m.y};
    } else if (seg.entry !== null && seg.entry !== undefined) {
      const m = this._edgeMidpoint(seg.entry, HEX_SIZE);
      p1 = {x: cx + m.x * 3 / 4, y: cy + m.y * 3 / 4};
    } else {
      p1 = {x: cx, y: cy};
    }

    const h = ((q * 7919 + r * 104729) & 0x7FFFFFFF);
    const jx = ((h % 7) - 3) * 0.8;
    const jy = (((h >> 3) % 7) - 3) * 0.8;

    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    // Variable-thickness: split the Bezier into 3 sub-segments
    // with slightly different widths for organic feel.
    const isRiver = seg.type === "river";
    const baseOutline = isRiver ? 7 : 5.5;
    const baseFill = isRiver ? 4.5 : 3;
    const cp = { x: cx + jx, y: cy + jy };
    const subPts = [p0];
    for (let t = 1; t <= 3; t++) {
      const f = t / 3;
      // Quadratic Bezier interpolation at t=f
      const x = (1 - f) * (1 - f) * p0.x
        + 2 * (1 - f) * f * cp.x + f * f * p1.x;
      const y = (1 - f) * (1 - f) * p0.y
        + 2 * (1 - f) * f * cp.y + f * f * p1.y;
      subPts.push({ x, y });
    }

    for (let pass = 0; pass < 2; pass++) {
      const isOutline = pass === 0;
      if (isRiver) {
        ctx.strokeStyle = isOutline
          ? "rgba(15, 40, 100, 0.6)"
          : "rgba(40, 100, 200, 0.75)";
      } else {
        ctx.strokeStyle = isOutline
          ? "rgba(0, 0, 0, 0.6)"
          : "rgba(120, 80, 40, 0.7)";
        if (!isOutline) ctx.setLineDash([5, 4]);
        else ctx.setLineDash([]);
      }
      const baseW = isOutline ? baseOutline : baseFill;
      for (let i = 0; i < subPts.length - 1; i++) {
        const hw = this._jitterHash(q, r, i * 11 + pass);
        const v = ((hw % 1000) / 500 - 1) * 1.5;
        ctx.lineWidth = Math.max(1, baseW + v);
        const s = new Path2D();
        s.moveTo(subPts[i].x, subPts[i].y);
        s.lineTo(subPts[i + 1].x, subPts[i + 1].y);
        ctx.stroke(s);
      }
    }
    ctx.restore();
  },

  /**
   * Deterministic hash for jitter — same inputs always produce
   * the same pseudo-random value.
   */
  _jitterHash(a, b, c) {
    let h = ((a * 7919 + b * 104729 + c * 34159) & 0x7FFFFFFF);
    h = ((h >> 16) ^ h) * 0x45d9f3b;
    return ((h >> 16) ^ h) & 0x7FFFFFFF;
  },

  /**
   * Draw a river or road using sub-hex waypoints projected into
   * the macro hex with deterministic jitter and smooth curves.
   */
  _drawSubPathCurve(ctx, cx, cy, seg) {
    const scale = HEX_SIZE / 2.5;
    const s3 = Math.sqrt(3);
    const JITTER = HEX_SIZE * 0.12;
    const MID_JITTER = HEX_SIZE * 0.08;

    // Project waypoints with per-point jitter
    const raw = seg.sub_path.map((p, i) => {
      const bx = cx + scale * 1.5 * p.q;
      const by = cy + scale * (s3 / 2 * p.q + s3 * p.r);
      const h1 = this._jitterHash(p.q, p.r, i * 2);
      const h2 = this._jitterHash(p.q, p.r, i * 2 + 1);
      const jx = ((h1 % 1000) / 500 - 1) * JITTER;
      const jy = ((h2 % 1000) / 500 - 1) * JITTER;
      return { x: bx + jx, y: by + jy };
    });

    // Insert noisy midpoints between consecutive waypoints
    const pts = [raw[0]];
    for (let i = 1; i < raw.length; i++) {
      const a = raw[i - 1];
      const b = raw[i];
      const sp = seg.sub_path;
      const hm = this._jitterHash(
        sp[i - 1].q + sp[i].q, sp[i - 1].r + sp[i].r, i * 7,
      );
      const hm2 = this._jitterHash(sp[i].q, sp[i].r, i * 13);
      const mjx = ((hm % 1000) / 500 - 1) * MID_JITTER;
      const mjy = ((hm2 % 1000) / 500 - 1) * MID_JITTER;
      pts.push({
        x: (a.x + b.x) / 2 + mjx,
        y: (a.y + b.y) / 2 + mjy,
      });
      pts.push(b);
    }

    // Variable-thickness drawing: stroke short segments with
    // per-segment lineWidth for organic swelling/tapering.
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const isRiver = seg.type === "river";
    const baseOutline = isRiver ? 7 : 5.5;
    const baseFill = isRiver ? 4.5 : 3;
    const variance = isRiver ? 1.5 : 1;

    for (let pass = 0; pass < 2; pass++) {
      const isOutline = pass === 0;
      if (isRiver) {
        ctx.strokeStyle = isOutline
          ? "rgba(15, 40, 100, 0.6)"
          : "rgba(40, 100, 200, 0.75)";
      } else {
        ctx.strokeStyle = isOutline
          ? "rgba(0, 0, 0, 0.6)"
          : "rgba(120, 80, 40, 0.7)";
        if (!isOutline) ctx.setLineDash([5, 4]);
        else ctx.setLineDash([]);
      }
      const baseW = isOutline ? baseOutline : baseFill;
      for (let i = 0; i < pts.length - 1; i++) {
        const sp = seg.sub_path;
        const hw = this._jitterHash(
          sp[Math.min(i, sp.length - 1)].q,
          sp[Math.min(i, sp.length - 1)].r,
          i * 17 + pass,
        );
        const v = ((hw % 1000) / 500 - 1) * variance;
        ctx.lineWidth = Math.max(1, baseW + v);
        const s = new Path2D();
        s.moveTo(pts[i].x, pts[i].y);
        if (i + 2 < pts.length) {
          const xc = (pts[i + 1].x + pts[i + 2].x) / 2;
          const yc = (pts[i + 1].y + pts[i + 2].y) / 2;
          s.quadraticCurveTo(pts[i + 1].x, pts[i + 1].y, xc, yc);
        } else {
          s.lineTo(pts[i + 1].x, pts[i + 1].y);
        }
        ctx.stroke(s);
      }
    }
    ctx.restore();
  },

  _drawFeatureLabel(ctx, feature, cx, cy) {
    const label = feature.charAt(0).toUpperCase() + feature.slice(1);
    ctx.save();
    ctx.font = "bold 11px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const metrics = ctx.measureText(label);
    const pad = 3;
    const w = Math.ceil(metrics.width) + pad * 2;
    const h = 16;
    const labelY = cy + HEX_HEIGHT / 2 - 10;
    ctx.fillStyle = "rgba(8, 10, 14, 0.78)";
    ctx.fillRect(cx - w / 2, labelY - h / 2, w, h);
    ctx.fillStyle = "#f5dea2";
    ctx.fillText(label, cx, labelY);
    ctx.restore();
  },

  _drawGlyphFallback(ctx, cell, x, y) {
    const g = BIOME_GLYPH[cell.biome] || BIOME_GLYPH.greenlands;
    ctx.fillStyle = g.bg;
    this._fillHex(ctx, x, y, g.bg);
    ctx.fillStyle = g.fg;
    ctx.font = "bold 24px monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(g.c, x, y);
  },

  _fillHex(ctx, cx, cy, color) {
    ctx.save();
    ctx.fillStyle = color;
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 180 * (60 * i);
      const px = cx + HEX_SIZE * Math.cos(a);
      const py = cy + HEX_SIZE * Math.sin(a);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  },

  _punchHex(ctx, cx, cy) {
    ctx.save();
    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 180 * (60 * i);
      const px = cx + HEX_SIZE * Math.cos(a);
      const py = cy + HEX_SIZE * Math.sin(a);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  },
};

// Key bindings (standard hex-roguelike diagonals for flat-top hexes):
//   y = NW    k = N    u = NE
//   b = SW    j = S    n = SE
//   e = enter the feature on the current hex (settlement, dungeon)
//   l = leave the current dungeon back to the overland
//   r = rest (skip a day)
const HEX_KEY_TO_DIR = {
  // Vi keys
  "k": [0, -1],   // N
  "u": [1, -1],   // NE
  "n": [1, 0],    // SE
  "j": [0, 1],    // S
  "b": [-1, 1],   // SW
  "y": [-1, 0],   // NW
  // Numpad layout: 7=NW 8=N 9=NE / 1=SW 2=S 3=SE
  "7": [-1, 0],   // NW
  "8": [0, -1],   // N
  "9": [1, -1],   // NE
  "1": [-1, 1],   // SW
  "2": [0, 1],    // S
  "3": [1, 0],    // SE
};

// Two flags:
// - HexGameActive: true as soon as a state_hex has ever arrived;
//   never cleared until page reload. Gates the Escape-to-exit key.
// - HexInputActive: true only while the overland view is on screen
//   (i.e. the player is not inside a dungeon). Gates the movement
//   keybinds whose letters collide with dungeon bindings.
let HexGameActive = false;
let HexInputActive = false;
let FlowerInputActive = false;

function setHexInputActive(on) {
  HexInputActive = on;
}

function hexKeyHandler(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const tag = (ev.target?.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  const key = ev.key;

  // Shift-L (uppercase "L") always exits the current dungeon
  // when the game is in hex mode, regardless of whether the
  // overland is visible -- this is how the player leaves a
  // settlement / cave back to the overland. Fires while
  // HexInputActive is false so it works while the dungeon
  // canvases are in front. Lowercase "l" stays bound to the
  // dungeon's "move east" in input.js.
  if (HexGameActive && key === "L") {
    WS.send({type: "action", intent: "hex_exit", data: null});
    ev.preventDefault();
    return;
  }
  // Shift+F panic-flees a dungeon from anywhere at a HP/clock
  // cost. Mirrors the terminal binding in input.py so muscle
  // memory carries between frontends.
  if (HexGameActive && key === "F") {
    WS.send({type: "action", intent: "panic_flee", data: null});
    ev.preventDefault();
    return;
  }

  // Sub-hex flower mode: direction + action keys.
  if (FlowerInputActive) {
    const lkey = (key || "").toLowerCase();
    if (HEX_KEY_TO_DIR[lkey]) {
      const [dq, dr] = HEX_KEY_TO_DIR[lkey];
      WS.send({type: "action", intent: "flower_step", data: [dq, dr]});
      ev.preventDefault();
      return;
    }
    // x = explore/enter feature (drill down)
    if (lkey === "x" || lkey === "e") {
      WS.send({type: "action", intent: "hex_enter", data: null});
      ev.preventDefault();
      return;
    }
    if (lkey === "s") {
      WS.send({type: "action", intent: "flower_search", data: null});
      ev.preventDefault();
      return;
    }
    if (lkey === "f") {
      WS.send({type: "action", intent: "flower_forage", data: null});
      ev.preventDefault();
      return;
    }
    if (lkey === "r" || lkey === ".") {
      WS.send({type: "action", intent: "flower_rest", data: null});
      ev.preventDefault();
      return;
    }
    // L = leave to hexmap (go up)
    if (key === "L" || key === "Escape") {
      WS.send({type: "action", intent: "flower_exit", data: null});
      ev.preventDefault();
      return;
    }
    return;
  }

  // Every other hex bind is overland-only; inside a dungeon let
  // the dungeon keybinds in input.js handle them.
  if (!HexInputActive) return;
  const lkey = (key || "").toLowerCase();
  if (HEX_KEY_TO_DIR[lkey]) {
    const [dq, dr] = HEX_KEY_TO_DIR[lkey];
    WS.send({type: "action", intent: "hex_step", data: [dq, dr]});
    ev.preventDefault();
    return;
  }
  if (lkey === "e") {
    WS.send({type: "action", intent: "hex_enter", data: null});
    ev.preventDefault();
    return;
  }
  if (lkey === ".") {
    WS.send({type: "action", intent: "hex_rest", data: null});
    ev.preventDefault();
    return;
  }
  if (lkey === "x") {
    WS.send({type: "action", intent: "hex_explore", data: null});
    ev.preventDefault();
    return;
  }
}

document.addEventListener("keydown", hexKeyHandler);

function _showHexOverland() {
  const mapContainer = document.getElementById("map-container");
  if (mapContainer) mapContainer.classList.add("hidden");
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.remove("hidden");
  if (typeof Input !== "undefined") Input.setToolbarMode("hex");
}

function _showDungeonView() {
  const mapContainer = document.getElementById("map-container");
  if (mapContainer) mapContainer.classList.remove("hidden");
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.add("hidden");
  if (typeof Input !== "undefined") Input.setToolbarMode("dungeon");
}

// Wire the WS handler and toggle visibility of the hex vs dungeon
// containers when a ``state_hex`` arrives.
if (typeof WS !== "undefined") {
  WS.on("state_hex", (msg) => {
    HexGameActive = true;
    _showHexOverland();
    setHexInputActive(true);
    HexMap.render(msg);
    // Clear the "Generating dungeon…" overlay on the very first
    // hex frame. Hex mode never emits the dungeon "floor" message
    // that the dungeon pipeline uses to drop the overlay.
    if (typeof NHC !== "undefined") {
      NHC.waitingForFloor = false;
      NHC.hideLoading();
    }
  });
  // When the dungeon sends its own state, the player is inside a
  // dungeon; hex-movement keys should NOT fire (dungeon keybinds
  // would collide) and the SVG + dungeon canvases must be visible.
  const _showDungeonAndLockHex = () => {
    setHexInputActive(false);
    _showDungeonView();
    // Re-arm the static draw + scroll for the next time the
    // overland view comes back (canvas may have been resized
    // or cleared by the dungeon renderer).
    HexMap._scrolledOnce = false;
    HexMap._staticDrawn = false;
    HexMap._punchedHexes.clear();
  };
  WS.on("state_dungeon", _showDungeonAndLockHex);
  WS.on("state", _showDungeonAndLockHex);
}


// ── Hover tooltip for hex features ──────────────────────────────
// Shows a localized tooltip (biome + feature) when the cursor is
// over a revealed hex on the overland canvas. Replaces the old
// permanent feature labels that cluttered the map.

(function _initHexTooltip() {
  const container = document.getElementById("hex-container");
  if (!container) return;
  let tip = document.getElementById("hex-tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "hex-tooltip";
    tip.style.cssText =
      "position:absolute; pointer-events:none; display:none; " +
      "background:rgba(8,10,14,0.85); color:#f5dea2; " +
      "font:bold 11px system-ui,sans-serif; padding:3px 8px; " +
      "border-radius:4px; white-space:nowrap; z-index:200;";
    container.appendChild(tip);
  }

  container.addEventListener("mousemove", (ev) => {
    if (!HexMap._lastState) { tip.style.display = "none"; return; }
    const rect = container.getBoundingClientRect();
    const {x: mx, y: my} = _screenToCanvas(
      ev.clientX - rect.left, ev.clientY - rect.top);
    // Pixel → axial: inverse of axialToPixel, accounting for
    // the pixel origin offset + margin.
    const ox = mx - HEX_MARGIN - HEX_SIZE + _pixelOriginX;
    const oy = my - HEX_MARGIN - HEX_SIZE + _pixelOriginY;
    const q = Math.round(ox / (HEX_SIZE * 1.5));
    const r = Math.round(
      (oy - HEX_SIZE * Math.sqrt(3) / 2 * q)
        / (HEX_SIZE * Math.sqrt(3))
    );
    const cell = HexMap._lastState.cells.find(
      c => c.q === q && c.r === r,
    );
    if (!cell) { tip.style.display = "none"; return; }

    const L = NHC.labels || {};
    const biomeKey = `hex_biome_${cell.biome}`;
    const biome = L[biomeKey] || cell.biome;
    let text = biome;
    if (cell.feature && cell.feature !== "none") {
      const featKey = `hex_feature_${cell.feature}`;
      const feat = L[featKey] || cell.feature;
      text = `${feat} — ${biome}`;
    }
    tip.textContent = text;
    tip.style.display = "block";
    tip.style.left = `${mx + 14}px`;
    tip.style.top = `${my - 10}px`;
  });

  container.addEventListener("mouseleave", () => {
    tip.style.display = "none";
  });
})();
