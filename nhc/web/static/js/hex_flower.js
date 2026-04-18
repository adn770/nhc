/**
 * hex_flower.js — Sub-hex flower exploration renderer.
 *
 * Renders the 19-cell hex flower for sub-hex exploration.
 * Follows the same canvas stack pattern as hex_map.js:
 * base (tiles) → feature (rivers/roads) → fog → entity → debug.
 *
 * Constants are larger than hex_map.js because the flower fills
 * the viewport with only 19 hexes instead of ~400.
 */

/* global WS */

const HEX_FLOWER_SIZE = 92;
const HEX_FLOWER_WIDTH = 2 * HEX_FLOWER_SIZE;
const HEX_FLOWER_HEIGHT = Math.sqrt(3) * HEX_FLOWER_SIZE;
const HEX_FLOWER_MARGIN = HEX_FLOWER_SIZE;
const FLOWER_CANVAS_SCALE = 238 / HEX_FLOWER_WIDTH;

/* ------------------------------------------------------------------ */
/* Coordinate projection (flat-top axial, same as hex_map.js)         */
/* ------------------------------------------------------------------ */

let _flowerOriginX = 0;
let _flowerOriginY = 0;

function _flowerAxialToPixel(q, r) {
  const x = HEX_FLOWER_SIZE * 1.5 * q
    - _flowerOriginX + HEX_FLOWER_MARGIN + HEX_FLOWER_SIZE;
  const y = HEX_FLOWER_SIZE
    * (Math.sqrt(3) / 2 * q + Math.sqrt(3) * r)
    - _flowerOriginY + HEX_FLOWER_MARGIN + HEX_FLOWER_SIZE;
  return { x, y };
}

function _flowerHexVariant(q, r, n) {
  const h = ((q * 7919 + r * 104729) & 0x7FFFFFFF);
  return h % n;
}

/* ------------------------------------------------------------------ */
/* Biome colours (fallback when tiles are missing)                    */
/* ------------------------------------------------------------------ */

const _FLOWER_BIOME_COLORS = {
  greenlands: { bg: "#5b8c3e", fg: "#2d5a1e", c: "." },
  drylands:   { bg: "#c4a55a", fg: "#8a7a3a", c: ":" },
  sandlands:  { bg: "#e0c878", fg: "#b09848", c: "~" },
  icelands:   { bg: "#c0d8e8", fg: "#6090b0", c: "*" },
  deadlands:  { bg: "#5a4a4a", fg: "#3a2a2a", c: "%" },
  forest:     { bg: "#3a6b2e", fg: "#1a3a10", c: "T" },
  mountain:   { bg: "#8a8a8a", fg: "#4a4a4a", c: "^" },
  hills:      { bg: "#7a9a5a", fg: "#4a6a3a", c: "n" },
  marsh:      { bg: "#6a8a5a", fg: "#3a5a2a", c: "~" },
  swamp:      { bg: "#4a6a3a", fg: "#2a4a1a", c: "~" },
  water:      { bg: "#3070c0", fg: "#1040a0", c: "=" },
};

const _MINOR_FEATURE_GLYPHS = {  // kept for future use
  farm: "F", well: "W", shrine: "S", signpost: "+",
  campsite: "C", orchard: "O", cairn: "c", animal_den: "d",
  hollow_log: "l", mushroom_ring: "m", herb_patch: "h",
  bone_pile: "b", standing_stone: "s", lair: "L",
  nest: "N", burrow: "B", none: "",
};

/* ------------------------------------------------------------------ */
/* HexFlower singleton                                                */
/* ------------------------------------------------------------------ */

const HexFlower = {
  _staticDrawn: false,
  _punchedHexes: new Set(),
  _tileCache: {},
  _fogTile: undefined,
  _arrows: null,
  _playerPx: null,
  _arrowsVisible: false,
  _lastArrowCoord: null,

  /* ---- canvas management ---- */

  resize(pw, ph) {
    const lx = Math.ceil(pw + 2 * HEX_FLOWER_SIZE + 2 * HEX_FLOWER_MARGIN);
    const ly = Math.ceil(ph + 2 * HEX_FLOWER_SIZE + 2 * HEX_FLOWER_MARGIN);
    const cx = Math.ceil(lx * FLOWER_CANVAS_SCALE);
    const cy = Math.ceil(ly * FLOWER_CANVAS_SCALE);
    const container = document.getElementById("flower-container");
    const ids = [
      "flower-base-canvas", "flower-fog-canvas",
      "flower-feature-canvas", "flower-entity-canvas",
      "flower-debug-canvas",
    ];
    container.style.width = `${lx}px`;
    container.style.height = `${ly}px`;
    for (const id of ids) {
      const c = document.getElementById(id);
      if (!c) continue;
      c.width = cx;
      c.height = cy;
      c.style.width = `${lx}px`;
      c.style.height = `${ly}px`;
    }
  },

  resetStatic() {
    this._staticDrawn = false;
    this._punchedHexes = new Set();
    this._zoomApplied = false;
  },

  /* ---- hex drawing helpers ---- */

  _fillHex(ctx, cx, cy, size, color) {
    ctx.save();
    ctx.fillStyle = color;
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 180 * (60 * i);
      const px = cx + size * Math.cos(a);
      const py = cy + size * Math.sin(a);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
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
      const px = cx + HEX_FLOWER_SIZE * Math.cos(a);
      const py = cy + HEX_FLOWER_SIZE * Math.sin(a);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  },

  _drawPlayerAvatar(ctx, cx, cy) {
    ctx.save();
    ctx.font = `bold ${Math.round(HEX_FLOWER_SIZE * 0.6)}px monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#1a3a6b";
    ctx.lineJoin = "round";
    ctx.strokeText("@", cx, cy);
    ctx.fillStyle = "#999999";
    ctx.fillText("@", cx, cy);
    ctx.restore();
  },

  _drawGlyphFallback(ctx, cell, x, y) {
    const g = _FLOWER_BIOME_COLORS[cell.biome]
      || _FLOWER_BIOME_COLORS.greenlands;
    this._fillHex(ctx, x, y, HEX_FLOWER_SIZE, g.bg);
    let glyph = g.c;
    if (cell.major_feature && cell.major_feature !== "none") {
      glyph = cell.major_feature.charAt(0).toUpperCase();
    }
    ctx.fillStyle = g.fg;
    ctx.font = `bold ${Math.round(HEX_FLOWER_SIZE * 0.5)}px monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(glyph, x, y);
  },

  /* ---- edge segment drawing ---- */

  /**
   * Deterministic hash for jitter — same (q, r, i) always
   * produces the same pseudo-random offset.
   */
  _jitterHash(q, r, i) {
    let h = ((q * 7919 + r * 104729 + i * 34159) & 0x7FFFFFFF);
    // Mix bits a little more
    h = ((h >> 16) ^ h) * 0x45d9f3b;
    return ((h >> 16) ^ h) & 0x7FFFFFFF;
  },

  /**
   * Draw a river or road through sub-hex waypoints with organic
   * jitter and Catmull-Rom splines for C1-smooth curves.
   */
  _drawFlowerEdge(ctx, seg) {
    if (!seg.path || seg.path.length < 2) return;
    const R = HEX_FLOWER_SIZE;
    const JITTER = R * 0.35;
    const s3 = Math.sqrt(3);

    // Macro hex edge midpoints at 2.5 sub-hex radii from center,
    // so curves reach the flower boundary instead of stopping at
    // ring-2 sub-hex centers.
    // NEIGHBOR_OFFSETS: N, NE, SE, S, SW, NW
    const _DIRS = [[0,-1],[1,-1],[1,0],[0,1],[-1,1],[-1,0]];
    const _edgePt = (d) => {
      const [dq, dr] = _DIRS[d];
      return _flowerAxialToPixel(dq * 2.5, dr * 2.5);
    };

    // Project waypoints with per-point jitter (skip endpoints)
    const last = seg.path.length - 1;
    const raw = seg.path.map((p, i) => {
      const base = _flowerAxialToPixel(p.q, p.r);
      if (i === 0 || i === last) return base;
      const h1 = this._jitterHash(p.q, p.r, i * 2);
      const h2 = this._jitterHash(p.q, p.r, i * 2 + 1);
      const jx = ((h1 % 1000) / 500 - 1) * JITTER;
      const jy = ((h2 % 1000) / 500 - 1) * JITTER;
      return { x: base.x + jx, y: base.y + jy };
    });

    // Prepend/append edge boundary points
    const pts = [];
    if (seg.entry !== null && seg.entry !== undefined) {
      pts.push(_edgePt(seg.entry));
    }
    pts.push(...raw);
    if (seg.exit !== null && seg.exit !== undefined) {
      pts.push(_edgePt(seg.exit));
    }

    // Build single continuous path via Catmull-Rom → cubic Bezier
    const path2d = new Path2D();
    path2d.moveTo(pts[0].x, pts[0].y);
    const tension = 0.5;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[Math.min(pts.length - 1, i + 2)];
      const cp1x = p1.x + (p2.x - p0.x) / (6 * tension);
      const cp1y = p1.y + (p2.y - p0.y) / (6 * tension);
      const cp2x = p2.x - (p3.x - p1.x) / (6 * tension);
      const cp2y = p2.y - (p3.y - p1.y) / (6 * tension);
      path2d.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, p2.x, p2.y);
    }

    // Per-segment width from endpoint hash
    const isRiver = seg.type === "river";
    const sp0 = seg.path[0];
    const spN = seg.path[seg.path.length - 1];
    const wh = this._jitterHash(sp0.q + spN.q, sp0.r + spN.r, 31);
    const wVar = isRiver ? 6 : 4;
    const wOfs = ((wh % 1000) / 500 - 1) * wVar;

    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const baseOutline = isRiver ? 26 : 22;
    const baseFill = isRiver ? 18 : 14;

    for (let pass = 0; pass < 2; pass++) {
      const isOutline = pass === 0;
      if (isRiver) {
        ctx.strokeStyle = isOutline
          ? "rgba(15, 40, 100, 0.6)"
          : "rgba(40, 100, 200, 0.75)";
      } else {
        ctx.strokeStyle = isOutline
          ? "rgba(0, 0, 0, 0.5)"
          : "rgba(120, 80, 40, 0.7)";
        if (!isOutline) ctx.setLineDash([12, 10]);
        else ctx.setLineDash([]);
      }
      const baseW = isOutline ? baseOutline : baseFill;
      ctx.lineWidth = Math.max(2, baseW + wOfs);
      ctx.stroke(path2d);
    }
    ctx.restore();
  },

  /* ---- direction arrows ---- */

  _ensureArrows() {
    if (this._arrows) return this._arrows;
    const hud = document.getElementById("flower-hud");
    if (!hud) return [];
    const dirs = [
      { dq: 0, dr: -1, rot: 0, key: "8" },
      { dq: 1, dr: -1, rot: 60, key: "9" },
      { dq: 1, dr: 0, rot: 120, key: "3" },
      { dq: 0, dr: 1, rot: 180, key: "2" },
      { dq: -1, dr: 1, rot: 240, key: "1" },
      { dq: -1, dr: 0, rot: 300, key: "7" },
    ];
    const arrows = dirs.map(d => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hex-arrow";
      btn.innerHTML = `<svg viewBox="0 0 64 64" width="64" height="64">
        <g transform="rotate(${d.rot} 32 32)">
          <path d="M 32 4 L 58 58 L 32 44 L 6 58 Z"
                fill="rgba(200,180,120,0.7)"
                stroke="rgba(60,40,10,0.8)" stroke-width="2"/>
        </g>
        <text x="32" y="36" text-anchor="middle"
              dominant-baseline="central"
              fill="rgba(60,40,10,0.9)"
              font-size="16" font-weight="bold">${d.key}</text>
      </svg>`;
      btn.dataset.dq = String(d.dq);
      btn.dataset.dr = String(d.dr);
      btn.style.display = "none";
      btn.addEventListener("click", () => {
        if (typeof WS !== "undefined") {
          WS.send({
            type: "action",
            intent: "flower_step",
            data: [d.dq, d.dr],
          });
        }
      });
      hud.appendChild(btn);
      return btn;
    });
    const container = document.getElementById("flower-container");
    if (container) {
      container.addEventListener("mousemove", (ev) => {
        if (!this._playerPx) return;
        const rect = container.getBoundingClientRect();
        const mx = (ev.clientX - rect.left);
        const my = (ev.clientY - rect.top);
        const dx = mx - this._playerPx.x;
        const dy = my - this._playerPx.y;
        const near = (dx * dx + dy * dy)
          <= (HEX_FLOWER_SIZE * 4) * (HEX_FLOWER_SIZE * 4);
        for (const a of arrows) {
          a.style.display = near ? "" : "none";
        }
      });
      container.addEventListener("mouseleave", () => {
        for (const a of arrows) a.style.display = "none";
      });
    }
    this._arrows = arrows;
    return arrows;
  },

  _positionArrows(playerCoord, playerPx) {
    const arrows = this._ensureArrows();
    for (const btn of arrows) {
      const dq = parseInt(btn.dataset.dq, 10);
      const dr = parseInt(btn.dataset.dr, 10);
      const ox = HEX_FLOWER_SIZE * 1.5 * dq;
      const oy = HEX_FLOWER_SIZE
        * (Math.sqrt(3) / 2 * dq + Math.sqrt(3) * dr);
      btn.style.left = `${playerPx.x + 1.5 * ox}px`;
      btn.style.top = `${playerPx.y + 1.5 * oy}px`;
    }
    this._lastArrowCoord = { q: playerCoord.q, r: playerCoord.r };
  },

  /* ---- centering & auto-fit zoom ---- */

  _centerOnPlayer() {
    if (!this._playerPx) return;
    const zone = document.getElementById("map-zone");
    const container = document.getElementById("flower-container");
    if (!zone || !container) return;
    const scale = (typeof GameMap !== "undefined")
      ? (GameMap._zoomSteps[GameMap._zoomLevel] || 1) : 1;
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
    const container = document.getElementById("flower-container");
    if (!zone || !container || typeof GameMap === "undefined") return;
    // Use the actual hex content extent (pixel_width/height from
    // the state + one hex diameter for edge radii) instead of the
    // full padded container size — maximises the fit.
    const contentW = (this._contentW || 400) + HEX_FLOWER_WIDTH;
    const contentH = (this._contentH || 400) + HEX_FLOWER_HEIGHT;
    const zw = zone.clientWidth;
    const zh = zone.clientHeight;
    const fitScale = Math.min(zw / contentW, zh / contentH, 2.0);
    // Pick the largest zoom step that fits
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
        el.style.transformOrigin = "0 0";
        el.style.transform = `scale(${scale})`;
      }
    }
    // Flower uses center origin for horizontal centering
    const fc = document.getElementById("flower-container");
    if (fc) {
      fc.style.transformOrigin = "center top";
      fc.style.transform = `scale(${scale})`;
    }
    if (typeof Input !== "undefined") Input._updateZoomLabel();
  },

  /* ---- main render ---- */

  async render(state) {
    const base = document.getElementById("flower-base-canvas");
    const fog = document.getElementById("flower-fog-canvas");
    const feat = document.getElementById("flower-feature-canvas");
    const ent = document.getElementById("flower-entity-canvas");
    if (!base || !fog || !feat || !ent) return;
    const baseCtx = base.getContext("2d");
    const fogCtx = fog.getContext("2d");
    const featCtx = feat.getContext("2d");
    const entCtx = ent.getContext("2d");

    _flowerOriginX = state.pixel_origin_x || 0;
    _flowerOriginY = state.pixel_origin_y || 0;
    const pw = state.pixel_width || 0;
    const ph = state.pixel_height || 0;
    this._contentW = pw;
    this._contentH = ph;

    if (!this._staticDrawn) {
      this.resize(pw, ph);

      /* -- base layer: load tile PNGs (reuse hex_map.js globals) -- */
      const tileLoads = state.cells.map(cell => {
        // Use major_feature for tile lookup; minor features are
        const urls = tilePath(cell.biome, cell.tile_slot);
        return HexMap._loadTile(urls.primary, urls.fallback)
          .then(img => ({ cell, img }));
      });
      if (this._fogTile === undefined) {
        this._fogTile = null;
        tileLoads.push(
          HexMap._loadTile("/hextiles/27-foundation_fog.png")
            .then(img => { this._fogTile = img; return null; }),
        );
      }
      const placements = (await Promise.all(tileLoads)).filter(Boolean);

      baseCtx.save();
      baseCtx.scale(FLOWER_CANVAS_SCALE, FLOWER_CANVAS_SCALE);
      for (const { cell, img } of placements) {
        const { x, y } = _flowerAxialToPixel(cell.q, cell.r);
        if (img) {
          baseCtx.drawImage(
            img,
            x - HEX_FLOWER_WIDTH / 2, y - HEX_FLOWER_HEIGHT / 2,
            HEX_FLOWER_WIDTH, HEX_FLOWER_HEIGHT,
          );
        } else {
          this._drawGlyphFallback(baseCtx, cell, x, y);
        }
      }
      baseCtx.restore();

      /* -- feature layer: rivers/roads -- */
      featCtx.save();
      featCtx.scale(FLOWER_CANVAS_SCALE, FLOWER_CANVAS_SCALE);
      if (state.edges) {
        for (const seg of state.edges) {
          this._drawFlowerEdge(featCtx, seg);
        }
      }
      /* major feature labels on revealed cells */
      for (const cell of state.cells) {
        if (!cell.revealed) continue;
        if (!cell.major_feature || cell.major_feature === "none") continue;
        const { x, y } = _flowerAxialToPixel(cell.q, cell.r);
        const label = cell.major_feature.charAt(0).toUpperCase();
        featCtx.save();
        featCtx.font = `bold ${Math.round(HEX_FLOWER_SIZE * 0.35)}px monospace`;
        featCtx.textAlign = "center";
        featCtx.textBaseline = "middle";
        featCtx.fillStyle = "rgba(255,255,255,0.85)";
        featCtx.strokeStyle = "rgba(0,0,0,0.6)";
        featCtx.lineWidth = 2;
        featCtx.strokeText(label, x, y + HEX_FLOWER_SIZE * 0.25);
        featCtx.fillText(label, x, y + HEX_FLOWER_SIZE * 0.25);
        featCtx.restore();
      }
      featCtx.restore();

      /* -- fog layer -- */
      fogCtx.save();
      fogCtx.scale(FLOWER_CANVAS_SCALE, FLOWER_CANVAS_SCALE);
      fogCtx.fillStyle = "#87CEEB";
      fogCtx.fillRect(
        0, 0,
        fog.width / FLOWER_CANVAS_SCALE,
        fog.height / FLOWER_CANVAS_SCALE,
      );
      for (const { cell } of placements) {
        const { x, y } = _flowerAxialToPixel(cell.q, cell.r);
        if (this._fogTile) {
          fogCtx.drawImage(
            this._fogTile,
            x - HEX_FLOWER_WIDTH / 2, y - HEX_FLOWER_HEIGHT / 2,
            HEX_FLOWER_WIDTH, HEX_FLOWER_HEIGHT,
          );
        } else {
          this._fillHex(fogCtx, x, y, HEX_FLOWER_SIZE, "#5a7a9a");
        }
      }
      fogCtx.restore();

      this._staticDrawn = true;
    }

    /* -- incremental fog punch -- */
    fogCtx.save();
    fogCtx.scale(FLOWER_CANVAS_SCALE, FLOWER_CANVAS_SCALE);
    for (const cell of state.cells) {
      if (!cell.revealed) continue;
      const key = `${cell.q},${cell.r}`;
      if (this._punchedHexes.has(key)) continue;
      const { x, y } = _flowerAxialToPixel(cell.q, cell.r);
      this._punchHex(fogCtx, x, y);
      this._punchedHexes.add(key);
    }
    fogCtx.restore();

    /* -- entity layer -- */
    entCtx.save();
    entCtx.clearRect(0, 0, ent.width, ent.height);
    entCtx.scale(FLOWER_CANVAS_SCALE, FLOWER_CANVAS_SCALE);
    if (state.player) {
      const { x, y } = _flowerAxialToPixel(
        state.player.q, state.player.r,
      );
      this._playerPx = { x, y };
      this._drawPlayerAvatar(entCtx, x, y);
      this._positionArrows(state.player, this._playerPx);
    }
    entCtx.restore();

    // Auto-fit zoom on first render; center on every render.
    if (!this._zoomApplied) {
      this._autoFitZoom();
      this._zoomApplied = true;
    }
    this._centerOnPlayer();
  },
};

/* ---- WebSocket integration ---- */
if (typeof WS !== "undefined") {
  WS.on("state_flower", (msg) => {
    const hexC = document.getElementById("hex-container");
    const flowerC = document.getElementById("flower-container");
    const mapC = document.getElementById("map-container");
    const loginScreen = document.getElementById("login-screen");
    if (hexC) hexC.classList.add("hidden");
    if (mapC) mapC.classList.add("hidden");
    if (loginScreen) loginScreen.classList.add("hidden");
    if (flowerC) flowerC.classList.remove("hidden");
    /* eslint-disable no-undef */
    if (typeof FlowerInputActive !== "undefined") {
      FlowerInputActive = true;
      HexInputActive = false;
    }
    if (typeof HexGameActive !== "undefined") {
      HexGameActive = true;
    }
    /* eslint-enable no-undef */
    HexFlower.render(msg);
    // Dismiss the loading spinner (same as state_hex handler)
    if (typeof NHC !== "undefined") {
      NHC.waitingForFloor = false;
      NHC.hideLoading();
    }
  });

  WS.on("state_hex", () => {
    /* When we get a state_hex, hide the flower and show hex map. */
    const flowerC = document.getElementById("flower-container");
    if (flowerC && !flowerC.classList.contains("hidden")) {
      flowerC.classList.add("hidden");
      HexFlower.resetStatic();
      // Re-arm zoom + scroll so the hex map zooms to the player
      // tile when coming back from flower view.
      if (typeof HexMap !== "undefined") {
        HexMap._scrolledOnce = false;
      }
    }
    /* eslint-disable no-undef */
    if (typeof FlowerInputActive !== "undefined") {
      FlowerInputActive = false;
    }
    /* eslint-enable no-undef */
  });
}
