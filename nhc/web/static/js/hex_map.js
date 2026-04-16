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

/** Slot number to filename stem; the hextiles pack uses the slot's
 * English name in the filename (e.g. 11-greenlands_village.png). */
const SLOT_NAME = {
  1: "vulcano", 2: "forest", 3: "tundra", 4: "trees", 5: "water",
  6: "hills", 7: "river", 8: "portal", 9: "mountains", 10: "lake",
  11: "village", 12: "city", 13: "tower", 14: "community",
  15: "cave", 16: "hole", 17: "dead_trees", 18: "ruins",
  19: "graveyard", 20: "swamp", 21: "floating_island",
  22: "keep", 23: "wonder", 24: "crystals", 25: "stones",
  26: "farms", 27: "fog",
};

/** Biome base-tile slot: used when a hex has no feature. Each biome
 * picks a reasonable "empty" look from its 27-slot palette. */
const BIOME_BASE_SLOT = {
  greenlands: 4,    // scattered trees
  drylands: 3,      // tundra-ish dryland
  sandlands: 3,
  icelands: 3,      // tundra
  deadlands: 17,    // dead trees
  forest: 2,        // dense forest
  mountain: 9,      // mountains
};

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

/** biome + feature → /hextiles/ URL. */
function tilePath(biome, feature) {
  let slot;
  if (feature && feature !== "none" && FEATURE_SLOT[feature]) {
    slot = FEATURE_SLOT[feature];
  } else {
    slot = BIOME_BASE_SLOT[biome] || 4;
  }
  const stem = SLOT_NAME[slot];
  return `/hextiles/${biome}/${slot}-${biome}_${stem}.png`;
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

  /** Resize all five hex canvases to ``width × height`` (axial grid
   * dims) at the current HEX_SIZE, set an integer pixel backing
   * store, and clear any previous content. */
  resize(width, height) {
    const canvases = [
      "hex-base-canvas", "hex-fog-canvas", "hex-feature-canvas",
      "hex-entity-canvas", "hex-debug-canvas",
    ];
    // Bounding box: rightmost centre + HEX_SIZE; bottom-most centre
    // + HEX_SIZE; plus margin.
    const lastQ = width - 1;
    const lastR = height - 1;
    const last = axialToPixel(lastQ, lastR);
    const px = Math.ceil(last.x + HEX_SIZE + HEX_MARGIN);
    const py = Math.ceil(last.y + HEX_SIZE + HEX_MARGIN);
    const container = document.getElementById("hex-container");
    if (container) {
      container.style.width = `${px}px`;
      container.style.height = `${py}px`;
    }
    canvases.forEach(id => {
      const c = document.getElementById(id);
      if (!c) return;
      c.width = px;
      c.height = py;
      const ctx = c.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, c.width, c.height);
    });
  },

  /** Load and cache an image. Returns a Promise<HTMLImageElement|null>;
   * resolves with null if the tile is missing. */
  _loadTile(url) {
    if (this._tileCache[url]) {
      return Promise.resolve(this._tileCache[url]);
    }
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => { this._tileCache[url] = img; resolve(img); };
      img.onerror = () => { this._tileCache[url] = null; resolve(null); };
      img.src = url;
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

    this.resize(state.width, state.height);

    // Fog fills the whole grid solid; revealed hexes punch through.
    fogCtx.fillStyle = "#05070a";
    fogCtx.fillRect(0, 0, fog.width, fog.height);

    for (const cell of state.cells) {
      const {x, y} = axialToPixel(cell.q, cell.r);
      const url = tilePath(cell.biome, cell.feature);
      const img = await this._loadTile(url);
      if (img) {
        baseCtx.drawImage(
          img,
          x - HEX_WIDTH / 2, y - HEX_HEIGHT / 2,
          HEX_WIDTH, HEX_HEIGHT,
        );
      } else {
        this._drawGlyphFallback(baseCtx, cell, x, y);
      }
      // Punch the fog over this cell.
      this._punchHex(fogCtx, x, y);
    }

    // Player avatar.
    if (state.player) {
      const {x, y} = axialToPixel(state.player.q, state.player.r);
      entCtx.clearRect(0, 0, ent.width, ent.height);
      entCtx.fillStyle = "#ffd966";
      entCtx.font = "bold 28px monospace";
      entCtx.textAlign = "center";
      entCtx.textBaseline = "middle";
      entCtx.fillText("@", x, y);
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
        "y/u N/NE · b/n SW/SE · k N · j S · e enter · l leave · r rest";
    }
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

let HexInputActive = false;

function setHexInputActive(on) {
  HexInputActive = on;
}

function hexKeyHandler(ev) {
  if (!HexInputActive) return;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const tag = (ev.target?.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  const key = (ev.key || "").toLowerCase();
  if (HEX_KEY_TO_DIR[key]) {
    const [dq, dr] = HEX_KEY_TO_DIR[key];
    WS.send({type: "action", intent: "hex_step", data: [dq, dr]});
    ev.preventDefault();
    return;
  }
  if (key === "e") {
    WS.send({type: "action", intent: "hex_enter", data: null});
    ev.preventDefault();
    return;
  }
  if (key === "l") {
    WS.send({type: "action", intent: "hex_exit", data: null});
    ev.preventDefault();
    return;
  }
  if (key === "r") {
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
}

function _showDungeonView() {
  const dungeon = document.getElementById("floor-svg");
  const dungeonCanvases = document.querySelectorAll(
    "#door-canvas, #hatch-canvas, #fog-canvas, #entity-canvas, #debug-canvas");
  dungeonCanvases.forEach(c => c.classList.remove("hidden"));
  if (dungeon) dungeon.classList.remove("hidden");
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.add("hidden");
}

// Wire the WS handler and toggle visibility of the hex vs dungeon
// containers when a ``state_hex`` arrives.
if (typeof WS !== "undefined") {
  WS.on("state_hex", (msg) => {
    _showHexOverland();
    setHexInputActive(true);
    HexMap.render(msg);
  });
  // When the dungeon sends its own state, the player is inside a
  // dungeon; hex-movement keys should NOT fire (dungeon keybinds
  // would collide) and the SVG + dungeon canvases must be visible.
  const _showDungeonAndLockHex = () => {
    setHexInputActive(false);
    _showDungeonView();
  };
  WS.on("state_dungeon", _showDungeonAndLockHex);
  WS.on("state", _showDungeonAndLockHex);
}
