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

/** Build tile URL from biome + slot (assigned by the backend).
 * Tile selection logic lives in nhc/hexcrawl/tiles.py — the
 * frontend just renders the slot it receives. */
function tilePath(biome, slot) {
  const stem = SLOT_NAME[slot];
  const biomeUrl = `/hextiles/${biome}/${slot}-${biome}_${stem}.png`;
  return {primary: biomeUrl, fallback: null};
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
    // User already has a remembered zoom for the hex view -- use
    // that instead of re-fitting (setActiveView will typically
    // have applied it already; keep this branch for direct
    // callers).
    if ("hex" in GameMap._zoomByView) {
      GameMap._applyScaleToContainer("hex", GameMap._zoomByView.hex);
      if (typeof Input !== "undefined") Input._updateZoomLabel();
      return;
    }
    // Zoom to 2.5x and center on the player so the current tile
    // is visible when switching from flower to hex map view.
    const steps = GameMap._zoomSteps;
    const targetScale = 2.5;
    let best = steps.length - 1;
    for (let i = 0; i < steps.length; i++) {
      if (steps[i] >= targetScale - 0.01) { best = i; break; }
    }
    GameMap._recordAutoFit("hex", best);
    GameMap._applyScaleToContainer("hex", best);
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
        const urls = tilePath(cell.biome, cell.tile_slot);
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
          // At junction hexes (2+ segments of the same type),
          // draw secondary segments thinner to reduce clutter.
          // At overlap hexes (river + road), offset road slightly.
          const typeCounts = {};
          for (const seg of cell.edges) {
            typeCounts[seg.type] = (typeCounts[seg.type] || 0) + 1;
          }
          const hasRiver = (typeCounts["river"] || 0) > 0;
          const hasRoad = (typeCounts["path"] || 0) > 0;
          const overlap = hasRiver && hasRoad;
          // Draw rivers first, then roads on top with offset.
          const sorted = [...cell.edges].sort((a, b) =>
            a.type === "river" ? -1 : b.type === "river" ? 1 : 0,
          );
          const drawn = {};
          for (const seg of sorted) {
            drawn[seg.type] = (drawn[seg.type] || 0) + 1;
            const isJunction = typeCounts[seg.type] > 1;
            const wScale = isJunction && drawn[seg.type] > 1
              ? 0.65 : 1.0;
            // Offset roads at overlap hexes so both are visible.
            const ox = overlap && seg.type !== "river" ? 3 : 0;
            const oy = overlap && seg.type !== "river" ? 2 : 0;
            this._drawEdgeSegment(
              featCtx, x + ox, y + oy, cell.q, cell.r, seg, wScale,
              isJunction,
            );
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
  _drawEdgeSegment(ctx, cx, cy, q, r, seg, widthScale = 1.0,
                   isJunction = false) {
    // When sub-hex waypoints are available, use them for smoother
    // curves. Skip for paths at junctions (flower sub-paths don't
    // match the junction layout) and at source/sink segments
    // (would cross over the feature icon).
    const isPathTerminus = seg.type !== "river"
        && (seg.entry == null || seg.exit == null);
    const useSubPath = seg.sub_path && seg.sub_path.length >= 2
        && !(isJunction && seg.type !== "river")
        && !isPathTerminus;
    if (useSubPath) {
      this._drawSubPathCurve(ctx, cx, cy, seg, widthScale);
      return;
    }

    // Fallback: single-control-point quadratic Bezier.
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
    // Source/sink: shorten the curve so it stops before the
    // feature icon. Pull the center-end 40% toward the edge.
    if (seg.entry === null || seg.entry === undefined) {
      if (seg.exit !== null && seg.exit !== undefined) {
        p0 = {x: cx + (p1.x - cx) * 0.40,
              y: cy + (p1.y - cy) * 0.40};
      }
    }
    if (seg.exit === null || seg.exit === undefined) {
      if (seg.entry !== null && seg.entry !== undefined) {
        p1 = {x: cx + (p0.x - cx) * 0.40,
              y: cy + (p0.y - cy) * 0.40};
      }
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
    const baseOutline = (isRiver ? 7 : 5.5) * widthScale;
    const baseFill = (isRiver ? 4.5 : 3) * widthScale;
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
   * the macro hex with deterministic jitter and Catmull-Rom splines
   * for smooth, C1-continuous curves.
   */
  _drawSubPathCurve(ctx, cx, cy, seg, widthScale = 1.0) {
    const scale = HEX_SIZE / 2.5;
    const s3 = Math.sqrt(3);
    const JITTER = HEX_SIZE * 0.20;

    // Edge midpoints for anchoring first/last curve points
    // so adjacent hex curves meet at hex boundaries.
    const R = HEX_SIZE;
    const mids = [
      [0, -R * s3 / 2],              // 0: N
      [3 * R / 4, -R * s3 / 4],      // 1: NE
      [3 * R / 4,  R * s3 / 4],      // 2: SE
      [0,  R * s3 / 2],              // 3: S
      [-3 * R / 4,  R * s3 / 4],     // 4: SW
      [-3 * R / 4, -R * s3 / 4],     // 5: NW
    ];
    const last = seg.sub_path.length - 1;

    // Project waypoints with per-point jitter, snapping
    // first/last to edge midpoints for cross-hex continuity.
    const pts = seg.sub_path.map((p, i) => {
      // First point: snap to entry edge midpoint
      if (i === 0 && seg.entry != null) {
        const [mx, my] = mids[seg.entry];
        return { x: cx + mx, y: cy + my };
      }
      // Last point: snap to exit edge midpoint
      if (i === last && seg.exit != null) {
        const [mx, my] = mids[seg.exit];
        return { x: cx + mx, y: cy + my };
      }
      let bx = cx + scale * 1.5 * p.q;
      let by = cy + scale * (s3 / 2 * p.q + s3 * p.r);
      // Source/sink points: no jitter
      if (i === 0 || i === last) {
        return { x: bx, y: by };
      }
      // Clamp interior points to stay inside the hex (max 60%
      // of radius from center) so curves don't bulge into
      // adjacent tiles.
      const ddx = bx - cx, ddy = by - cy;
      const dist = Math.sqrt(ddx * ddx + ddy * ddy);
      const maxR = HEX_SIZE * 0.60;
      if (dist > maxR) {
        const ratio = maxR / dist;
        bx = cx + ddx * ratio;
        by = cy + ddy * ratio;
      }
      const h1 = this._jitterHash(p.q, p.r, i * 2);
      const h2 = this._jitterHash(p.q, p.r, i * 2 + 1);
      const jx = ((h1 % 1000) / 500 - 1) * JITTER;
      const jy = ((h2 % 1000) / 500 - 1) * JITTER;
      return { x: bx + jx, y: by + jy };
    });
    // Drop interior points too close to their neighbour —
    // they create sharp kinks in the Catmull-Rom spline.
    const minGap = HEX_SIZE * 0.25;
    const filtered = pts.filter((pt, j) => {
      if (j === 0 || j === pts.length - 1) return true;
      const prev = pts[j - 1], nxt = pts[j + 1];
      const dPrev = Math.hypot(pt.x - prev.x, pt.y - prev.y);
      const dNxt = Math.hypot(pt.x - nxt.x, pt.y - nxt.y);
      return dPrev >= minGap && dNxt >= minGap;
    });
    const crPts = filtered.length >= 2 ? filtered : pts;
    if (crPts.length < 2) return;

    // Build a single continuous path using Catmull-Rom → cubic
    // Bezier conversion for C1-smooth tangents at each point.
    const path2d = new Path2D();
    path2d.moveTo(crPts[0].x, crPts[0].y);
    const tension = 0.5;
    for (let i = 0; i < crPts.length - 1; i++) {
      const p0 = crPts[Math.max(0, i - 1)];
      const p1 = crPts[i];
      const p2 = crPts[i + 1];
      const p3 = crPts[Math.min(crPts.length - 1, i + 2)];
      const cp1x = p1.x + (p2.x - p0.x) / (6 * tension);
      const cp1y = p1.y + (p2.y - p0.y) / (6 * tension);
      const cp2x = p2.x - (p3.x - p1.x) / (6 * tension);
      const cp2y = p2.y - (p3.y - p1.y) / (6 * tension);
      path2d.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, p2.x, p2.y);
    }

    // Determine per-segment line width from endpoint hash
    const isRiver = seg.type === "river";
    const sp0 = seg.sub_path[0];
    const spN = seg.sub_path[seg.sub_path.length - 1];
    const wh = this._jitterHash(sp0.q + spN.q, sp0.r + spN.r, 31);
    const wVar = isRiver ? 1.5 : 1;
    const wOfs = ((wh % 1000) / 500 - 1) * wVar;

    // Two-pass stroke: outline then fill, single path each
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const baseOutline = (isRiver ? 7 : 5.5) * widthScale;
    const baseFill = (isRiver ? 4.5 : 3) * widthScale;

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
      ctx.lineWidth = Math.max(1, baseW + wOfs * widthScale);
      ctx.stroke(path2d);
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

  // Shift-L ("L") routes by context: inside the flower it
  // returns to the overland; in a dungeon / settlement / cave it
  // exits back to the overland. Fires while HexInputActive is
  // false so it works with the dungeon canvases in front.
  // Lowercase "l" stays bound to the dungeon's "move east" in
  // input.js.
  if (HexGameActive && key === "L") {
    const intent = FlowerInputActive ? "flower_exit" : "hex_exit";
    WS.send({type: "action", intent, data: null});
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
    // x = enter feature (explore deeper into dungeon/city)
    if (lkey === "x") {
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
    // L = leave flower, return to hexmap
    if (key === "L") {
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
  if (lkey === ".") {
    WS.send({type: "action", intent: "hex_rest", data: null});
    ev.preventDefault();
    return;
  }
  // x = explore current hex (enter flower view)
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
  if (typeof GameMap !== "undefined") GameMap.setActiveView("hex");
  if (typeof Input !== "undefined") Input.setToolbarMode("hex");
}

function _showDungeonView() {
  const mapContainer = document.getElementById("map-container");
  if (mapContainer) mapContainer.classList.remove("hidden");
  const hexContainer = document.getElementById("hex-container");
  if (hexContainer) hexContainer.classList.add("hidden");
  // Also hide the flower container — entering a dungeon from
  // flower mode must dismiss the flower view.
  const flowerContainer = document.getElementById("flower-container");
  if (flowerContainer) flowerContainer.classList.add("hidden");
  if (typeof GameMap !== "undefined") GameMap.setActiveView("map");
  if (typeof Input !== "undefined") Input.setToolbarMode("dungeon");
}

// Wire the WS handler and toggle visibility of the hex vs dungeon
// containers when a ``state_hex`` arrives.
if (typeof WS !== "undefined") {
  WS.on("state_hex", (msg) => {
    HexGameActive = true;
    // Re-arm zoom + scroll when returning from flower or dungeon
    // view so the hex map auto-zooms and centers on the player.
    const flowerC = document.getElementById("flower-container");
    if (flowerC && !flowerC.classList.contains("hidden")) {
      HexMap._scrolledOnce = false;
    }
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
    /* eslint-disable no-undef */
    if (typeof FlowerInputActive !== "undefined") {
      FlowerInputActive = false;
    }
    /* eslint-enable no-undef */
    _showDungeonView();
    // Dungeon / site / building all share the "map" view -- their
    // zoom preference lives under that key and is restored by
    // _showDungeonView -> GameMap.setActiveView("map"). Default
    // for a fresh player is 1.0x, but once the user zooms we
    // honour that choice (previously we clobbered it back to 1x
    // on every dungeon entry).
    if (typeof GameMap !== "undefined"
        && !("map" in GameMap._zoomByView)) {
      const idx = GameMap._zoomSteps.indexOf(1.0);
      if (idx >= 0) GameMap._recordAutoFit("map", idx);
      GameMap._applyScaleToContainer("map", idx);
      if (typeof Input !== "undefined") Input._updateZoomLabel();
    }
    // Re-arm the static draw + scroll for the next time the
    // overland view comes back (canvas may have been resized
    // or cleared by the dungeon renderer).
    HexMap._scrolledOnce = false;
    HexMap._staticDrawn = false;
    HexMap._punchedHexes.clear();
  };
  WS.on("state_dungeon", _showDungeonAndLockHex);
  WS.on("state", _showDungeonAndLockHex);

  // Click on the player glyph in hex map → enter exploration.
  const _hexContainer = document.getElementById("hex-container");
  if (_hexContainer) {
    _hexContainer.addEventListener("click", (ev) => {
      if (!HexInputActive || !HexMap._playerPx) return;
      const rect = _hexContainer.getBoundingClientRect();
      const scale = _hexZoomScale();
      const mx = (ev.clientX - rect.left) / scale;
      const my = (ev.clientY - rect.top) / scale;
      const dx = mx - HexMap._playerPx.x;
      const dy = my - HexMap._playerPx.y;
      if (dx * dx + dy * dy <= HEX_SIZE * HEX_SIZE) {
        WS.send({type: "action", intent: "hex_explore", data: null});
      }
    });
  }
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
