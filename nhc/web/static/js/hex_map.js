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

const HEX_SIZE = 36;            // hex radius (centre → corner), px
const HEX_WIDTH = 2 * HEX_SIZE;                 // corner-to-corner
const HEX_HEIGHT = Math.sqrt(3) * HEX_SIZE;     // edge-to-edge
const HEX_MARGIN = HEX_SIZE;    // padding on all four sides

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

/** Biome base-tile slots: arrays of candidate slots for visual
 * variety on featureless hexes. The renderer picks one per hex
 * deterministically from (q + r) so the choice is stable across
 * repaints but varies tile-to-tile. */
const BIOME_BASE_SLOTS = {
  greenlands: [4, 42, 43, 26],      // trees, sparse, clearing, farms
  drylands:   [3, 25],              // tundra, stones
  sandlands:  [3, 25],
  icelands:   [3],
  deadlands:  [17, 25],             // dead trees, stones
  forest:     [2, 41, 42, 47],      // forest, dense, sparse, great tree
  mountain:   [9, 62, 63, 66, 69],  // mountains, peaks, plateau, foothills, summit
  hills:      [6, 50, 45],          // hills, hillock, wild bushes
  marsh:      [20, 45, 48],         // swamp, wild bushes, mushrooms
  swamp:      [20, 41, 48],         // swamp, dense forest, mushrooms
  water:      [5],                  // single water tile
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

/** Deterministic per-hex pick: (q, r) → index into a variant
 * array. Stable across renders so tiles don't flicker. */
function _hexVariant(q, r, n) {
  // Simple hash to avoid modular patterns on small maps.
  const h = ((q * 7919 + r * 104729) & 0x7FFFFFFF);
  return h % n;
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
    const bases = BIOME_BASE_SLOTS[biome] || [4];
    slot = bases[_hexVariant(q || 0, r || 0, bases.length)];
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

/** Axial (q, r) → pixel (x, y) for the centre of the hex. */
function axialToPixel(q, r, size = HEX_SIZE) {
  const x = size * 1.5 * q + HEX_MARGIN + HEX_SIZE;
  const y = size * (Math.sqrt(3) / 2 * q + Math.sqrt(3) * r)
          + HEX_MARGIN + HEX_SIZE;
  return {x, y};
}

const HexMap = {
  /** Image cache keyed by URL; prevents repeated fetches. */
  _tileCache: {},

  /** Cached fog tile image (27-foundation_fog.png). Loaded once
   * on first render; used to stamp the fog canvas. */
  _fogTile: undefined,

  /** Cached DOM references for the 6 direction arrow buttons. */
  _arrows: null,

  /** DOM element (SVG inside a div) for the player avatar. Lives
   * in the HUD layer so it never participates in canvas clears. */
  _avatar: null,

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

  /** Hover threshold: arrows appear when the pointer lies inside
   * this many px of the player hex centre. The arrow centres sit
   * at 1.5 * neighbour_offset (i.e. the far edge of the next hex)
   * which is ~2.6 hex-radii away, so bump this a little to keep
   * them visible while the cursor is on them. */
  _HOVER_RADIUS: HEX_SIZE * 4.0,

  /** Last player coord the arrow ring was positioned for. Lets
   * us skip reposition work when the player hasn't moved. */
  _lastArrowCoord: null,

  /** Sync the #hex-hud DOM overlay to sit exactly over
   * #hex-container. Called when the canvas pixel box changes; a
   * no-op on frames where the map dimensions match the last call. */
  _syncHudBox() {
    const hud = document.getElementById("hex-hud");
    const container = document.getElementById("hex-container");
    const zone = document.getElementById("map-zone");
    if (!hud || !container || !zone) return;
    const c = container.getBoundingClientRect();
    const z = zone.getBoundingClientRect();
    hud.style.left = `${c.left - z.left + zone.scrollLeft}px`;
    hud.style.top = `${c.top - z.top + zone.scrollTop}px`;
    hud.style.width = `${c.width}px`;
    hud.style.height = `${c.height}px`;
  },

  /** Lazily build the player avatar DOM node. Uses the same
   * outline (#1a3a6b) and fill (dark_grey -> #999999) that the
   * dungeon entity renderer applies to the "@" glyph. */
  _ensureAvatar() {
    if (this._avatar) return this._avatar;
    const hud = document.getElementById("hex-hud");
    if (!hud) return null;
    const div = document.createElement("div");
    div.id = "hex-player-avatar";
    div.className = "hex-avatar";
    div.innerHTML = (
      '<svg viewBox="0 0 48 48" width="48" height="48"' +
      ' xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
      '<text x="24" y="32" text-anchor="middle"' +
      ' font-family="monospace" font-size="32" font-weight="bold"' +
      ' stroke="#1a3a6b" stroke-width="2"' +
      ' stroke-linejoin="round" paint-order="stroke"' +
      ' fill="#999999">@</text>' +
      "</svg>"
    );
    // Left-click on the avatar = enter the hex feature (same as
    // pressing 'e'). Convenient for touch / mouse-only play.
    div.style.cursor = "pointer";
    div.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      WS.send({type: "action", intent: "hex_enter", data: null});
    });
    hud.appendChild(div);
    this._avatar = div;
    return div;
  },

  _positionAvatar(playerPx) {
    const el = this._ensureAvatar();
    if (!el) return;
    el.style.left = `${playerPx.x}px`;
    el.style.top = `${playerPx.y}px`;
  },

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
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
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
    // The container can be offset inside map-zone if the zone has
    // flex centering; measure its real position and add the
    // player pixel on top.
    const z = zone.getBoundingClientRect();
    const c = container.getBoundingClientRect();
    const offsetX = (c.left - z.left) + zone.scrollLeft;
    const offsetY = (c.top - z.top) + zone.scrollTop;
    const targetLeft = offsetX + this._playerPx.x - zone.clientWidth / 2;
    const targetTop = offsetY + this._playerPx.y - zone.clientHeight / 2;
    zone.scrollTo({
      left: Math.max(0, targetLeft),
      top: Math.max(0, targetTop),
      behavior: "auto",
    });
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
    const px = Math.ceil(pixelW + HEX_SIZE + 2 * HEX_MARGIN);
    const py = Math.ceil(pixelH + HEX_SIZE + 2 * HEX_MARGIN);
    if (this._sizedTo
        && this._sizedTo.px === px
        && this._sizedTo.py === py) {
      return;
    }
    this._sizedTo = {px, py};
    const container = document.getElementById("hex-container");
    if (container) {
      container.style.width = `${px}px`;
      container.style.height = `${py}px`;
    }
    const canvases = [
      "hex-base-canvas", "hex-fog-canvas", "hex-feature-canvas",
      "hex-entity-canvas", "hex-debug-canvas",
    ];
    canvases.forEach(id => {
      const c = document.getElementById(id);
      if (!c) return;
      c.width = px;
      c.height = py;
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

  /** Main entry point, called on every state_hex payload. */
  async render(state) {
    // Stash the latest state so the hover tooltip can look up
    // cells by axial coord without a re-render.
    this._lastState = state;

    const base = document.getElementById("hex-base-canvas");
    const fog = document.getElementById("hex-fog-canvas");
    const ent = document.getElementById("hex-entity-canvas");
    if (!base || !fog || !ent) return;
    const baseCtx = base.getContext("2d");
    const fogCtx = fog.getContext("2d");
    const entCtx = ent.getContext("2d");
    if (!baseCtx || !fogCtx || !entCtx) return;

    // Pixel box comes from the server (computed from populated
    // cells); fall back to axial-rect sizing for older payloads.
    const pw = state.pixel_width !== undefined
      ? state.pixel_width
      : axialToPixel(state.width - 1, state.height - 1).x;
    const ph = state.pixel_height !== undefined
      ? state.pixel_height
      : axialToPixel(state.width - 1, state.height - 1).y;
    this.resize(pw, ph);

    const feat = document.getElementById("hex-feature-canvas");
    const featCtx = feat ? feat.getContext("2d") : null;

    // Fetch every tile image in parallel BEFORE we start painting.
    // Awaiting each draw individually caused the browser to paint
    // the cleared canvas between microtasks, flashing the view on
    // every state_hex frame. With one await up front, the draw
    // loop below is synchronous.
    const tileLoads = state.cells.map(cell => {
      const urls = tilePath(cell.biome, cell.feature, cell.q, cell.r);
      return this._loadTile(urls.primary, urls.fallback)
        .then(img => ({cell, img}));
    });
    // Also load the fog tile if not cached yet.
    if (this._fogTile === undefined) {
      this._fogTile = null;  // mark as loading
      tileLoads.push(
        this._loadTile("/hextiles/27-foundation_fog.png")
          .then(img => { this._fogTile = img; return null; }),
      );
    }
    const placements = (await Promise.all(tileLoads)).filter(Boolean);

    // One synchronous paint pass: clear → fog → tiles → fog punch.
    // Nothing between the first clear and the final draw yields to
    // the event loop, so the browser only commits a single frame.
    baseCtx.clearRect(0, 0, base.width, base.height);
    if (featCtx) featCtx.clearRect(0, 0, feat.width, feat.height);

    // Fog canvas: sky-blue background + fog tile stamped over
    // every hex position. Revealed hexes are punched through.
    fogCtx.fillStyle = "#87CEEB";
    fogCtx.fillRect(0, 0, fog.width, fog.height);

    // Draw ALL tiles on the base canvas (fog covers unrevealed).
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
      // Stamp fog tile on every hex (unrevealed stay fogged).
      if (this._fogTile) {
        fogCtx.drawImage(
          this._fogTile,
          x - HEX_WIDTH / 2, y - HEX_HEIGHT / 2,
          HEX_WIDTH, HEX_HEIGHT,
        );
      }
      // Punch revealed hexes through the fog.
      if (cell.revealed) {
        this._punchHex(fogCtx, x, y);
      }
    }

    // River/path edge segments on the feature canvas (z-index 1,
    // below fog). Unrevealed segments are hidden by the fog layer.
    if (featCtx) {
      for (const {cell} of placements) {
        if (!cell.edges) continue;
        const {x, y} = axialToPixel(cell.q, cell.r);
        for (const seg of cell.edges) {
          this._drawEdgeSegment(featCtx, x, y, cell.q, cell.r, seg);
        }
      }
    }

    // Player avatar (HUD) + direction arrow ring (HUD). Canvas
    // draws ABOVE are purely terrain + fog + labels; the avatar
    // and arrows are DOM-backed on the HUD layer so they don't
    // flicker on repaint.
    entCtx.clearRect(0, 0, ent.width, ent.height);
    if (state.player) {
      const {x, y} = axialToPixel(state.player.q, state.player.r);
      this._playerPx = {x, y};
      this._syncHudBox();
      this._positionAvatar(this._playerPx);
      this._positionArrows(state.player, this._playerPx);
      if (!this._scrolledOnce) {
        this._centerOnPlayer();
        this._scrolledOnce = true;
      }
    }

    // Status bar is now filled by UI.updateStatus via the
    // stats/stats_init WebSocket messages sent alongside
    // state_hex. No direct status-line writes needed here.
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
    // Start/end points: edge midpoint or hex centre.
    let p0, p1;
    if (seg.entry !== null && seg.entry !== undefined) {
      const m = this._edgeMidpoint(seg.entry, HEX_SIZE);
      p0 = {x: cx + m.x, y: cy + m.y};
    } else {
      p0 = {x: cx, y: cy};
    }
    if (seg.exit !== null && seg.exit !== undefined) {
      const m = this._edgeMidpoint(seg.exit, HEX_SIZE);
      p1 = {x: cx + m.x, y: cy + m.y};
    } else {
      p1 = {x: cx, y: cy};
    }

    // Deterministic jitter for organic curve (seeded from coords).
    const h = ((q * 7919 + r * 104729) & 0x7FFFFFFF);
    const jx = ((h % 7) - 3) * 0.8;
    const jy = (((h >> 3) % 7) - 3) * 0.8;

    ctx.save();
    if (seg.type === "river") {
      ctx.strokeStyle = "rgba(60, 120, 200, 0.55)";
      ctx.lineWidth = 2.5;
      ctx.setLineDash([]);
    } else {
      ctx.strokeStyle = "rgba(140, 100, 60, 0.45)";
      ctx.lineWidth = 1.8;
      ctx.setLineDash([4, 3]);
    }
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(p0.x, p0.y);
    ctx.quadraticCurveTo(cx + jx, cy + jy, p1.x, p1.y);
    ctx.stroke();
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
}

document.addEventListener("keydown", hexKeyHandler);

function _showHexOverland() {
  // Hide the entire dungeon container (not individual canvases).
  const mapContainer = document.getElementById("map-container");
  if (mapContainer) mapContainer.classList.add("hidden");
  // Show the hex container + HUD.
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.remove("hidden");
  const hexHud = document.getElementById("hex-hud");
  if (hexHud) hexHud.classList.remove("hidden");
  if (typeof Input !== "undefined") Input.setToolbarMode("hex");
}

function _showDungeonView() {
  // Show the dungeon container.
  const mapContainer = document.getElementById("map-container");
  if (mapContainer) mapContainer.classList.remove("hidden");
  // Hide hex container + HUD.
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.add("hidden");
  const hexHud = document.getElementById("hex-hud");
  if (hexHud) hexHud.classList.add("hidden");
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
    // Re-arm the centre-on-player scroll for the next time the
    // overland view comes back.
    HexMap._scrolledOnce = false;
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
    const mx = ev.clientX - rect.left + container.scrollLeft;
    const my = ev.clientY - rect.top + container.scrollTop;
    // Pixel → axial: inverse of the flat-top layout math.
    const q = Math.round((mx - HEX_SIZE) / (HEX_SIZE * 1.5));
    const r = Math.round(
      (my - HEX_SIZE * Math.sqrt(3) / 2 - q * HEX_SIZE * Math.sqrt(3) / 2)
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
