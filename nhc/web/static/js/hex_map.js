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

/** Map a HexFeatureType.value to the hextiles slot number.
 * See the biome × feature matrix in design/overland_hexcrawl.md §3. */
const FEATURE_SLOT = {
  village: 11,
  city: 12,
  tower: 13,
  keep: 22,
  cave: 15,
  ruin: 18,
  hole: 16,
  graveyard: 19,
  crystals: 24,
  stones: 25,
  wonder: 23,
  portal: 8,
  lake: 10,
  river: 7,
};

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
};

/** Biome base-tile slot: used when a hex has no feature. */
const BIOME_BASE_SLOT = {
  greenlands: 4,    // scattered trees
  drylands: 3,      // tundra-ish dryland
  sandlands: 3,
  icelands: 3,      // tundra
  deadlands: 17,    // dead trees
  forest: 2,        // dense forest
  mountain: 9,      // mountains
};

/** Biomes with a full 27-slot palette; used as the primary tile
 * URL. Any biome in PARTIAL_PALETTE_BIOMES may not have every
 * slot -- _loadTile falls back to the foundation tile at the
 * project root if the biome-specific path 404s. */
const PALETTE_BIOMES = new Set([
  "greenlands", "drylands", "sandlands", "icelands", "deadlands",
  "forest", "mountain",
]);
const PARTIAL_PALETTE_BIOMES = new Set(["forest", "mountain"]);

/** Fallback glyph when the hextile PNG can't be fetched. */
const BIOME_GLYPH = {
  greenlands: {fg: "#5a8a4e", bg: "#2a3a1e", c: "."},
  drylands: {fg: "#a08840", bg: "#3a3220", c: "."},
  sandlands: {fg: "#c0a868", bg: "#4a3e22", c: "."},
  icelands: {fg: "#a8c0d0", bg: "#283038", c: "~"},
  deadlands: {fg: "#6a6858", bg: "#2a2824", c: "x"},
  forest: {fg: "#3a7844", bg: "#1a2e22", c: "T"},
  mountain: {fg: "#8a8480", bg: "#2a2826", c: "^"},
};

/** biome + feature → {primary, fallback} /hextiles/ URLs. */
function tilePath(biome, feature) {
  let slot;
  if (feature && feature !== "none" && FEATURE_SLOT[feature]) {
    slot = FEATURE_SLOT[feature];
  } else {
    slot = BIOME_BASE_SLOT[biome] || 4;
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
      {dq: 0,  dr: -1, rot: 0,   title: "North (k)"},
      {dq: 1,  dr: -1, rot: 60,  title: "North-east (u)"},
      {dq: 1,  dr: 0,  rot: 120, title: "South-east (n)"},
      {dq: 0,  dr: 1,  rot: 180, title: "South (j)"},
      {dq: -1, dr: 1,  rot: 240, title: "South-west (b)"},
      {dq: -1, dr: 0,  rot: 300, title: "North-west (y)"},
    ];
    const svgMarkup = (rot) => (
      '<svg viewBox="0 0 64 64" width="64" height="64"' +
      ' xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
      `<g transform="rotate(${rot} 32 32)">` +
      // Outer delta with a V-notch cut at the back. Tip at top,
      // inset goes up into the shape between the two base corners.
      '<path d="M 32 4 L 58 58 L 32 44 L 6 58 Z"' +
      ' fill="#5c9cff" fill-opacity="0.28"' +
      ' stroke="#1b2f5c" stroke-width="2.5"' +
      ' stroke-linejoin="round"/>' +
      // Centre divider from the tip to the notch.
      '<path d="M 32 4 L 32 44"' +
      ' stroke="#1b2f5c" stroke-width="2" stroke-linecap="round"/>' +
      "</g></svg>"
    );
    const arrows = dirs.map(d => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hex-arrow";
      btn.innerHTML = svgMarkup(d.rot);
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
    const placements = await Promise.all(state.cells.map(cell => {
      const urls = tilePath(cell.biome, cell.feature);
      return this._loadTile(urls.primary, urls.fallback)
        .then(img => ({cell, img}));
    }));

    // One synchronous paint pass: clear → fog → tiles → fog punch
    // → labels. Nothing between the first clear and the final draw
    // yields to the event loop, so the browser only ever commits a
    // single complete frame.
    baseCtx.clearRect(0, 0, base.width, base.height);
    fogCtx.fillStyle = "#05070a";
    fogCtx.fillRect(0, 0, fog.width, fog.height);
    if (featCtx) featCtx.clearRect(0, 0, feat.width, feat.height);

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
      this._punchHex(fogCtx, x, y);
      if (featCtx && cell.feature && cell.feature !== "none") {
        this._drawFeatureLabel(featCtx, cell.feature, x, y);
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

    // Update the day/time HUD if present.
    const hud = document.getElementById("status-line1");
    if (hud) {
      const time = (state.time || "morning").replace(/^\w/,
        c => c.toUpperCase());
      hud.textContent = `Day ${state.day} · ${time} ·` +
        ` Hex (${state.player.q}, ${state.player.r})`;
    }
    // Describe the player's current hex on line 2 so bump-to-enter
    // is discoverable. Shows "<biome> – <feature>" when the hex has
    // a feature, otherwise just the biome.
    const hud2 = document.getElementById("status-line2");
    if (hud2) {
      const me = state.cells.find(
        c => c.q === state.player.q && c.r === state.player.r,
      );
      if (me) {
        const biomeTitle = me.biome.replace(/^\w/,
          c => c.toUpperCase());
        let line = biomeTitle;
        if (me.feature && me.feature !== "none") {
          line += ` — ${me.feature}`;
          line += "   (press 'e' to enter)";
        }
        hud2.textContent = line;
      } else {
        hud2.textContent = "";
      }
    }
    const hud3 = document.getElementById("status-line3");
    if (hud3) {
      hud3.textContent =
        "y/u NW/NE · b/n SW/SE · k N · j S · e enter · Shift-L leave · r rest";
    }
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
  "k": [0, -1],   // N
  "u": [1, -1],   // NE
  "n": [1, 0],    // SE
  "j": [0, 1],    // S
  "b": [-1, 1],   // SW
  "y": [-1, 0],   // NW
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
  if (lkey === "r") {
    WS.send({type: "action", intent: "hex_rest", data: null});
    ev.preventDefault();
    return;
  }
}

document.addEventListener("keydown", hexKeyHandler);

function _showHexOverland() {
  const dungeon = document.getElementById("floor-svg");
  const dungeonCanvases = document.querySelectorAll(
    "#door-canvas, #hatch-canvas, #fog-canvas, #entity-canvas, #debug-canvas");
  dungeonCanvases.forEach(c => c.classList.add("hidden"));
  if (dungeon) dungeon.classList.add("hidden");
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.remove("hidden");
  const hexHud = document.getElementById("hex-hud");
  if (hexHud) hexHud.classList.remove("hidden");
}

function _showDungeonView() {
  const dungeon = document.getElementById("floor-svg");
  const dungeonCanvases = document.querySelectorAll(
    "#door-canvas, #hatch-canvas, #fog-canvas, #entity-canvas, #debug-canvas");
  dungeonCanvases.forEach(c => c.classList.remove("hidden"));
  if (dungeon) dungeon.classList.remove("hidden");
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.add("hidden");
  const hexHud = document.getElementById("hex-hud");
  if (hexHud) hexHud.classList.add("hidden");
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
