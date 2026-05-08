/**
 * Map rendering: floor SVG + hatch mask + fog-of-war + entity overlay.
 *
 * Four layers stacked:
 * 1. Floor SVG (static dungeon geometry)
 * 2. Hatch canvas (masks unexplored tiles to hide SVG bleed)
 * 3. Fog canvas (dark overlay on non-visible tiles)
 * 4. Entity canvas (player, creatures, items on top)
 *
 * The hatch canvas is an accumulator: each FOV update punches a
 * slightly-inflated polygon of the currently visible tiles through
 * the hatch pattern via destination-out compositing. Previously
 * revealed areas persist on the canvas until the pattern is
 * re-stamped on a new floor.
 *
 * The map viewport auto-scrolls to keep the player centered.
 */
const GameMap = {
  canvas: null,
  doorCanvas: null,
  fogCanvas: null,
  hatchCanvas: null,
  ctx: null,
  doorCtx: null,
  fogCtx: null,
  hatchCtx: null,
  cellSize: 32,  // must match SVG CELL constant
  padding: 32,   // must match SVG PADDING constant
  entities: [],
  doors: [],
  allDoors: new Map(),  // "x,y" → {x, y, edge, state, vertical}
  fov: new Set(),
  explored: new Set(),
  lastSeen: new Map(),  // "x,y" → turn number when tile was last in FOV
  turn: 0,
  // Walkable-visible tiles with their 4-bit wall masks: bit 0=N,
  // 1=E, 2=S, 3=W. A bit is set iff the tile-edge in that
  // direction sits on a wall line. Drives clearHatch.
  walls: new Map(),
  // Cumulative walkable-explored tiles with wall masks, used by
  // loadHatchSVG to replay the full reveal in one bulk clear.
  exploredWalls: new Map(),
  _hatchReady: false,
  doorInfo: new Map(),  // "x,y" → {edge, state}
  dugTiles: new Map(),  // "x,y" → {x, y, edges}
  tileset: null,
  tilesetImg: null,
  mapW: 0,
  mapH: 0,
  playerX: 0,
  playerY: 0,
  _zoomLevel: 2,  // mirror of _zoomByView[_activeView]; read by UI
  _zoomSteps: [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0],
  // Per-view zoom memory. One entry per canonical view:
  // "hex" | "flower" | "site" | "structure" | "dungeon".
  // See design/views.md for the five-view model. "site",
  // "structure" and "dungeon" share the #map-container element
  // but remain distinct views so each can remember its own zoom
  // and drive its own toolbar. A view is absent from the map
  // until either the user explicitly zooms while in that view
  // or the view's auto-fit runs for the first time in this
  // browser. Persisted to localStorage; key is bumped when the
  // view set changes so stale indices can't leak through.
  _activeView: "dungeon",
  _zoomByView: {},
  _ZOOM_STORAGE_KEY: "nhc.zoom.byView.v2",
  _VALID_VIEWS: ["hex", "flower", "site", "structure", "dungeon"],
  // Storage groups -- views that share a zoom slot. Site +
  // structure (the building interior accessed by walking
  // through a door from the site surface) deliberately share
  // so the player gets no zoom flicker when crossing into a
  // building. Hex / flower / dungeon each keep their own slot.
  _ZOOM_GROUPS: { site: "site", structure: "site" },
  _glowAnimId: null,  // requestAnimationFrame ID for detected glow

  init() {
    this.canvas = document.getElementById("entity-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.doorCanvas = document.getElementById("door-canvas");
    this.doorCtx = this.doorCanvas.getContext("2d");
    this.fogCanvas = document.getElementById("fog-canvas");
    this.fogCtx = this.fogCanvas.getContext("2d");
    this.hatchCanvas = document.getElementById("hatch-canvas");
    this.hatchCtx = this.hatchCanvas.getContext("2d");

    // Reset all client-side state from any previous game
    this.entities = [];
    this.doors = [];
    this.allDoors = new Map();
    this.dugTiles = new Map();
    this.fov = new Set();
    this.explored = new Set();
    this.lastSeen = new Map();
    this.turn = 0;
    this.walls = new Map();
    this.exploredWalls = new Map();
    this._hatchReady = false;
    this.doorInfo = new Map();
    this.mapW = 0;
    this.mapH = 0;
    this.playerX = 0;
    this.playerY = 0;

    // Clear the floor SVG container
    const floorSvg = document.getElementById("floor-svg");
    if (floorSvg) floorSvg.innerHTML = "";

    // Clear all canvas layers
    for (const cvs of [this.canvas, this.doorCanvas,
                        this.fogCanvas, this.hatchCanvas]) {
      if (cvs) {
        cvs.getContext("2d").clearRect(0, 0, cvs.width, cvs.height);
      }
    }

    console.log("GameMap.init(): canvas=", this.canvas,
                "fog=", this.fogCanvas, "hatch=", this.hatchCanvas);
    this._loadZoomPrefs();
    this.initTooltip();
  },

  /**
   * Load per-view zoom preferences from localStorage. Silently
   * ignores missing / malformed data; out-of-range indices are
   * dropped. Runs once during GameMap.init().
   */
  _loadZoomPrefs() {
    this._zoomByView = {};
    let raw;
    try {
      raw = localStorage.getItem(this._ZOOM_STORAGE_KEY);
    } catch (e) {
      return;
    }
    if (!raw) return;
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      return;
    }
    if (!parsed || typeof parsed !== "object") return;
    const maxIdx = this._zoomSteps.length - 1;
    // Accept any group key plus the legacy per-view keys (so a
    // payload from before the site/structure merge still loads).
    const validKeys = new Set([
      ...this._VALID_VIEWS,
      ...Object.values(this._ZOOM_GROUPS),
    ]);
    for (const key of validKeys) {
      const v = parsed[key];
      if (Number.isInteger(v) && v >= 0 && v <= maxIdx) {
        this._zoomByView[key] = v;
      }
    }
  },

  /** Storage-group key for ``view``. Views that don't appear in
   * ``_ZOOM_GROUPS`` map to themselves. */
  _zoomGroupForView(view) {
    return this._ZOOM_GROUPS[view] || view;
  },

  /** Persist _zoomByView to localStorage. Best-effort. */
  _saveZoomPrefs() {
    try {
      localStorage.setItem(
        this._ZOOM_STORAGE_KEY,
        JSON.stringify(this._zoomByView),
      );
    } catch (e) {
      // ignore: quota exceeded / localStorage disabled
    }
  },

  /**
   * Return the DOM container element that hosts the given view's
   * rendered content, or null if the container is missing. The
   * three tile-layer views (site / structure / dungeon) all ride
   * on #map-container -- they remain distinct *views* but reuse
   * one *element*.
   */
  _containerForView(view) {
    const id = view === "hex" ? "hex-container"
      : view === "flower" ? "flower-container"
      : "map-container";  // site / structure / dungeon
    return document.getElementById(id);
  },

  /** Transform-origin convention per view. Hex + flower use
   * center-top for horizontal centering; the three tile-layer
   * views anchor at 0,0 so the floor SVG aligns with the
   * dungeon canvases. */
  _originForView(view) {
    return (view === "hex" || view === "flower")
      ? "center top" : "0 0";
  },

  /** Apply the scale corresponding to zoom level ``idx`` to the
   * given view's container. Does nothing if the container is not
   * in the DOM. */
  _applyScaleToContainer(view, idx) {
    const el = this._containerForView(view);
    if (!el) return;
    const scale = this._zoomSteps[idx];
    el.style.transformOrigin = this._originForView(view);
    el.style.transform = `scale(${scale})`;
  },

  /**
   * Declare which view is now active.
   *
   * Sets _zoomLevel to either the view's remembered zoom (if any)
   * or the 1.0x default, then applies that scale to the new
   * view's container and resyncs the toolbar label. The default
   * fallback prevents _zoomLevel from carrying over stale values
   * from the previous view (e.g. hex's auto-fit 2.5x leaking into
   * the flower toolbar before the flower's own auto-fit resolves);
   * for views with auto-fit (hex, flower) the recorded fit value
   * overwrites this default in the same render() pass, so the
   * 1.0x is at most a one-frame transient.
   */
  setActiveView(view) {
    if (!this._VALID_VIEWS.includes(view)) return;
    this._activeView = view;
    const defaultIdx = this._zoomSteps.indexOf(1.0);
    const groupKey = this._zoomGroupForView(view);
    const idx = (groupKey in this._zoomByView)
      ? this._zoomByView[groupKey]
      : (defaultIdx >= 0 ? defaultIdx : 0);
    this._zoomLevel = idx;
    this._applyScaleToContainer(view, idx);
    if (typeof Input !== "undefined") Input._updateZoomLabel();
  },

  /**
   * Record the initial zoom chosen by a view's auto-fit so later
   * entries to the same view skip re-fitting and restore this
   * value instead. Called by HexMap / HexFlower auto-fit helpers
   * and by :meth:`_autoFitMapView`.
   */
  _recordAutoFit(view, idx) {
    this._zoomByView[this._zoomGroupForView(view)] = idx;
    this._zoomLevel = idx;
    this._saveZoomPrefs();
  },

  /**
   * Pick the largest zoom step where the floor SVG fits the
   * visible map-zone, then record + apply it. Returns the chosen
   * index (or null when prerequisites aren't satisfied).
   *
   * Callable on site / structure / dungeon -- the active view's
   * group decides the storage slot, so a site auto-fit also
   * pre-stamps the zoom for any structure entered through the
   * site's doors.
   */
  _autoFitMapView(view) {
    const zone = document.getElementById("map-zone");
    if (!zone || !this.mapW || !this.mapH) return null;
    const zw = zone.clientWidth;
    const zh = zone.clientHeight;
    if (zw <= 0 || zh <= 0) return null;
    // Cap at 4.0x so a tiny TINY-tier surface doesn't pixel-art
    // itself across the whole viewport.
    const fitScale = Math.min(zw / this.mapW, zh / this.mapH, 4.0);
    const steps = this._zoomSteps;
    let best = 0;
    for (let i = 0; i < steps.length; i++) {
      if (steps[i] <= fitScale + 0.01) best = i;
    }
    this._recordAutoFit(view, best);
    this._applyScaleToContainer(view, best);
    if (typeof Input !== "undefined") Input._updateZoomLabel();
    return best;
  },

  /**
   * Load a floor from the server. Prefers PNG (the Phase 5
   * tiny-skia path); falls back to inline SVG when the .png
   * endpoint returns non-200 — typically composite SVGs from
   * building / site-surface floors that wrap a non-IR overlay
   * around an IR base.
   *
   * The container `<div id="floor-svg">` keeps its ID even when
   * it now holds an `<img>` instead of an `<svg>` — the existing
   * CSS rules + debug toggle key off the container, not the
   * inner element.
   */
  async setFloorURL(url) {
    if (!url) return;
    const mode = this._renderMode();
    if (mode === "svg") {
      await this._loadFloorSVG(url + ".svg");
      return;
    }
    if (mode === "wasm") {
      try {
        await this._loadFloorWASM(url + ".nir");
        return;
      } catch (err) {
        // Phase 5.4 dispatcher errors fall back to PNG so a
        // broken bundle / missing route doesn't strand the
        // player on a blank screen during dev. Log once at
        // warn so the regression surfaces.
        console.warn("[setFloorURL] wasm path failed, falling "
                     + "back to PNG:", err);
      }
    }
    await this._loadFloorPNG(url + ".png");
  },

  _renderMode() {
    if (this._cachedRenderMode) return this._cachedRenderMode;
    const meta = document.querySelector('meta[name="render-mode"]');
    const value = meta ? meta.getAttribute("content") : null;
    this._cachedRenderMode = value || "png";
    return this._cachedRenderMode;
  },

  async _loadFloorPNG(url) {
    try {
      const resp = await fetch(url);
      if (!resp.ok) {
        console.warn("[setFloorURL] PNG fetch returned", resp.status,
                     "for", url);
        return;
      }
      const blob = await resp.blob();
      const objUrl = URL.createObjectURL(blob);
      try {
        const img = new Image();
        img.id = "floor-img";
        img.alt = "";
        img.draggable = false;
        img.src = objUrl;
        await img.decode();
        const w = img.naturalWidth;
        const h = img.naturalHeight;
        if (!w || !h) {
          console.warn("[setFloorURL] PNG decoded with 0 dimensions");
          return;
        }
        const container = document.getElementById("floor-svg");
        container.replaceChildren(img);
        this._installFloorDimensions(w, h, "PNG");
      } finally {
        // Revoke after decode completes; the <img> keeps an
        // internal reference so the blob is held until the next
        // setFloorURL replaces it.
        URL.revokeObjectURL(objUrl);
      }
    } catch (err) {
      console.error("[setFloorURL] PNG path failed:", err);
    }
  },

  async _loadFloorWASM(url) {
    // Phase 5.4 dispatcher entry. Imports the dispatcher
    // module lazily so the (~150 KB gzipped) wasm bundle isn't
    // requested when the page is in PNG / SVG mode. Throws on
    // fetch / init / render failure — the caller in
    // setFloorURL catches and falls back to PNG.
    const mod = await import(
      "/static/js/floor_ir_renderer.js?v="
      + (document.querySelector('meta[name="static-version"]')
         ?.getAttribute("content") || "0")
    );
    const { canvas, width, height } = await mod.fetchAndRender(url);
    const container = document.getElementById("floor-svg");
    container.replaceChildren(canvas);
    this._installFloorDimensions(width, height, "WASM");
  },

  async _loadFloorSVG(url) {
    try {
      const svgString = await fetch(url).then(r => {
        if (!r.ok) throw new Error(`SVG fetch ${r.status}`);
        return r.text();
      });
      this.setFloorSVG(svgString);
    } catch (err) {
      console.error("[setFloorURL] SVG path failed:", err);
    }
  },

  setFloorSVG(svgString) {
    const container = document.getElementById("floor-svg");
    const prevSvg = container.querySelector("svg");
    const prevW = prevSvg ? parseInt(prevSvg.getAttribute("width")) : 0;
    const prevH = prevSvg ? parseInt(prevSvg.getAttribute("height")) : 0;
    console.log("[setFloorSVG] replacing: prev=",
                prevW, "x", prevH, "new length=", svgString.length);
    container.innerHTML = svgString;
    const svg = container.querySelector("svg");
    if (!svg) {
      console.warn("No <svg> found in floor SVG string");
      return;
    }
    const w = parseInt(svg.getAttribute("width"));
    const h = parseInt(svg.getAttribute("height"));
    this._installFloorDimensions(w, h, "SVG");
  },

  /**
   * Common post-install path shared by setFloorURL (PNG branch)
   * and setFloorSVG: size every overlay canvas to the floor
   * pixel dimensions and trigger the per-view auto-fit.
   */
  _installFloorDimensions(w, h, kind) {
    console.log(`[setFloor${kind}] installed: new=`, w, "x", h,
                "prerevealed=", this.prerevealed);
    this.canvas.width = w;
    this.canvas.height = h;
    if (this.doorCanvas) {
      this.doorCanvas.width = w;
      this.doorCanvas.height = h;
    }
    if (this.fogCanvas) {
      this.fogCanvas.width = w;
      this.fogCanvas.height = h;
    }
    if (this.hatchCanvas) {
      this.hatchCanvas.width = w;
      this.hatchCanvas.height = h;
    }
    const debugCanvas = document.getElementById("debug-canvas");
    if (debugCanvas) {
      debugCanvas.width = w;
      debugCanvas.height = h;
    }
    this.mapW = w;
    this.mapH = h;
    console.log(`Floor ${kind} set:`, w, "x", h,
                 "canvas:", this.canvas.width, this.canvas.height,
                 "fog:", this.fogCanvas?.width, this.fogCanvas?.height);
    // Auto-fit on first entry to a tile-layer view (site /
    // structure / dungeon). The site + structure share a
    // storage slot via _ZOOM_GROUPS, so the surface fit also
    // pre-stamps the zoom for any building the player walks
    // into. Once the user zooms manually the saved value
    // takes over and the auto-fit becomes a no-op.
    const view = this._activeView;
    if (view === "site" || view === "structure"
        || view === "dungeon") {
      const groupKey = this._zoomGroupForView(view);
      if (!(groupKey in this._zoomByView)) {
        // The map-zone may not have its final clientWidth /
        // clientHeight until the browser lays out the just-
        // installed floor element; defer to the next frame so
        // the measurement reflects the post-mount state.
        requestAnimationFrame(() => {
          this._autoFitMapView(view);
        });
      }
    }
  },

  loadTileset(name) {
    return fetch(`/static/tilesets/${name}/manifest.json`)
      .then(r => r.json())
      .then(manifest => {
        this.tileset = manifest;
        if (manifest.type === "image" && manifest.image) {
          this.tilesetImg = new Image();
          this.tilesetImg.src =
            `/static/tilesets/${name}/${manifest.image}`;
          return new Promise(resolve => {
            this.tilesetImg.onload = resolve;
          });
        }
        this.tilesetImg = null;
      })
      .catch(() => {
        this.tileset = null;
        this.tilesetImg = null;
      });
  },

  updateEntities(entities, doors, dug) {
    this.entities = entities;
    if (doors) {
      this.doors = doors;
      for (const d of doors) {
        const key = `${d.x},${d.y}`;
        this.doorInfo.set(key, { edge: d.edge, state: d.state });
        this.allDoors.set(key, { ...d });
      }
      this.drawDoors();
    }
    if (dug) {
      for (const d of dug) {
        this.dugTiles.set(`${d.x},${d.y}`, d);
      }
      this.drawDoors();  // redraws doors + dug on same canvas
    }
    // Track player position for auto-scroll
    const player = entities.find(e => e.glyph === "@");
    if (player) {
      this.playerX = player.x;
      this.playerY = player.y;
    }
  },

  /**
   * Update FOV and walkable-FOV from full list or delta.
   * Full: msg.fov = [[x,y], ...], msg.walk = [[x,y,mask], ...]
   * Delta: msg.fov_add / msg.fov_del plus msg.walk_add /
   * msg.walk_del. Walkable entries carry a 4-bit wall mask used
   * by clearHatch to decide which edges should be inflated.
   */
  updateFOV(msg) {
    if (msg.fov) {
      this.fov = new Set(msg.fov.map(([x, y]) => `${x},${y}`));
    } else {
      if (msg.fov_del) {
        for (const [x, y] of msg.fov_del) {
          this.fov.delete(`${x},${y}`);
        }
      }
      if (msg.fov_add) {
        for (const [x, y] of msg.fov_add) {
          this.fov.add(`${x},${y}`);
        }
      }
    }
    for (const key of this.fov) {
      this.explored.add(key);
      this.lastSeen.set(key, this.turn);
    }

    if (msg.walk) {
      this.walls = new Map();
      for (const [x, y, mask] of msg.walk) {
        const k = `${x},${y}`;
        this.walls.set(k, mask);
        this.exploredWalls.set(k, mask);
      }
    } else {
      if (msg.walk_del) {
        for (const [x, y] of msg.walk_del) {
          this.walls.delete(`${x},${y}`);
        }
      }
      if (msg.walk_add) {
        for (const [x, y, mask] of msg.walk_add) {
          const k = `${x},${y}`;
          this.walls.set(k, mask);
          this.exploredWalls.set(k, mask);
        }
      }
    }
  },

  /**
   * Seed the explored set from a server-provided list. Used on
   * floor init / reconnect so the hatch clear can be replayed in
   * bulk before normal per-turn FOV updates take over.
   *
   * Each entry is [x, y, mask]: mask >= 0 is the wall-edge
   * bitmask for a walkable tile (also seeded into
   * exploredWalls for the bulk clearHatch), mask == -1 marks a
   * non-walkable tile that only contributes to drawFog's
   * memory-dim set.
   */
  setExplored(tiles) {
    if (!tiles) return;
    for (const [x, y, mask] of tiles) {
      const k = `${x},${y}`;
      this.explored.add(k);
      if (mask !== undefined && mask >= 0) {
        this.exploredWalls.set(k, mask);
      }
    }
  },

  /**
   * Redraw all visual layers and scroll to player in one pass.
   * Called after both entities and FOV data have been updated
   * so that fog, hatch, entities, and viewport stay in sync.
   */
  flush() {
    // Skip if the floor SVG hasn't loaded yet — canvas
    // dimensions are 0 and nothing would be visible. The
    // floor handler will call flush() again after loading.
    if (!this.mapW || !this.mapH) {
      console.log("[flush] SKIP: mapW=", this.mapW,
                  "mapH=", this.mapH);
      return;
    }
    console.log("[flush] rendering: mapW=", this.mapW,
                "mapH=", this.mapH,
                "canvas=", this.canvas?.width, "x",
                this.canvas?.height,
                "entities=", this.entities?.length,
                "fov=", this.fov?.size);
    this.clearHatch(this.walls);
    this.drawFog();
    this.draw();
    this.scrollToPlayer();
    this._startGlowLoop();
  },

  /**
   * Animate pulsating glow for detected entities.
   * Runs a requestAnimationFrame loop while any detected entities exist.
   */
  _startGlowLoop() {
    if (this._glowAnimId) return;  // already running
    if (!this.entities.some(e => e.detected)) return;
    const loop = () => {
      if (!this.entities.some(e => e.detected)) {
        this._glowAnimId = null;
        return;
      }
      this.draw();
      this._glowAnimId = requestAnimationFrame(loop);
    };
    this._glowAnimId = requestAnimationFrame(loop);
  },

  /**
   * Scroll the map viewport to center on the player.
   */
  scrollToPlayer() {
    const zone = document.getElementById("map-zone");
    if (!zone) return;

    const scale = this._zoomSteps[this._zoomLevel] || 1.0;
    const px = (this.playerX * this.cellSize + this.padding
               + this.cellSize / 2) * scale;
    const py = (this.playerY * this.cellSize + this.padding
               + this.cellSize / 2) * scale;

    const targetLeft = px - zone.clientWidth / 2;
    const targetTop = py - zone.clientHeight / 2;

    zone.scrollTo({
      left: Math.max(0, targetLeft),
      top: Math.max(0, targetTop),
      behavior: "auto",
    });
  },

  /**
   * Zoom the currently active view. Mutates only that view's
   * stored zoom and scales only that view's container; the other
   * views keep their own remembered zoom. Persists to localStorage.
   * @param {number} dir — +1 to zoom in, -1 to zoom out
   */
  zoom(dir) {
    const cur = this._zoomLevel;
    const newLevel = Math.max(0, Math.min(
      this._zoomSteps.length - 1, cur + dir));
    if (newLevel === cur) return;
    this._zoomLevel = newLevel;
    this._zoomByView[this._zoomGroupForView(this._activeView)] = newLevel;
    this._saveZoomPrefs();
    this._applyScaleToContainer(this._activeView, newLevel);
    // Centre on the player in the active view.
    if (this._activeView === "flower"
        && typeof HexFlower !== "undefined"
        && HexFlower._centerOnPlayer) {
      HexFlower._centerOnPlayer();
    } else if (this._activeView === "hex"
        && typeof HexMap !== "undefined"
        && HexMap._centerOnPlayer) {
      HexMap._centerOnPlayer();
    } else {
      this.scrollToPlayer();
    }
  },

  _resolveColor(colorName) {
    if (this.tileset && this.tileset.colors) {
      return this.tileset.colors[colorName] || colorName;
    }
    return colorName || "#FFFFFF";
  },

  /**
   * Load a small hatching SVG patch, create a repeating pattern,
   * and fill the full hatch canvas with it. Once the pattern is
   * stamped, replay the accumulated explored set as a one-shot
   * bulk clear so reconnects and floor transitions preserve the
   * visual exploration memory.
   */
  loadHatchSVG(url) {
    console.log("loadHatchSVG:", url, "ctx=", !!this.hatchCtx);
    if (!this.hatchCtx || !url) {
      console.warn("loadHatchSVG SKIPPED: no ctx or url");
      return;
    }
    this._hatchReady = false;
    // Prerevealed surfaces (town / keep / ruin / cottage / temple
    // courtyards) render without any hatching at all so the SVG
    // rooftops and enclosure stay visible. Skip the pattern stamp
    // and leave the canvas transparent.
    if (this.prerevealed) {
      this.hatchCtx.clearRect(
        0, 0, this.hatchCanvas.width, this.hatchCanvas.height);
      this._hatchReady = true;
      return;
    }
    const img = new Image();
    img.onload = () => {
      console.log("Hatch patch loaded:", img.width, "x", img.height);
      // Render SVG patch to an offscreen canvas
      const patch = document.createElement("canvas");
      patch.width = img.width;
      patch.height = img.height;
      const pctx = patch.getContext("2d");
      pctx.drawImage(img, 0, 0);
      // Create repeating pattern and fill the hatch canvas
      const pattern = this.hatchCtx.createPattern(patch, "repeat");
      this.hatchCtx.fillStyle = pattern;
      this.hatchCtx.fillRect(
        0, 0, this.hatchCanvas.width, this.hatchCanvas.height);
      this._hatchReady = true;
      // Bulk reveal everything explored so far (includes current
      // FOV on floor entry and the server-restored set on reconnect).
      this.clearHatch(this.exploredWalls);
      console.log("Hatch stamped, cleared",
                  this.exploredWalls.size, "explored tiles");
    };
    img.onerror = (e) => {
      console.error("Hatch patch FAILED to load:", e);
    };
    img.src = url;
  },

  /**
   * Punch a polygonal hole through the hatch pattern for the
   * given walkable-tile map. Traces the perimeter of the tiles,
   * inflates only the edges that sit on a wall line (per the
   * per-tile wall mask) by 2 pixels along each edge's outward
   * normal, and fills via destination-out compositing. Non-wall
   * boundary edges stay exactly on the tile edge so a torch
   * radius cutting across open floor does not bleed.
   *
   * The canvas itself accumulates clears across turns — the
   * caller should pass the current walkable FOV each turn and
   * the hole will grow naturally as the player explores.
   */
  clearHatch(wallsMap) {
    const ctx = this.hatchCtx;
    if (!ctx || !this._hatchReady) return;
    if (!wallsMap || wallsMap.size === 0) return;

    const loops = this._buildTileSetPolygons(wallsMap);
    if (loops.length === 0) return;

    const offset = 2;
    ctx.save();
    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath();
    for (const loop of loops) {
      const scaled = this._offsetLoop(loop, offset);
      if (scaled.length < 3) continue;
      ctx.moveTo(scaled[0].x, scaled[0].y);
      for (let i = 1; i < scaled.length; i++) {
        ctx.lineTo(scaled[i].x, scaled[i].y);
      }
      ctx.closePath();
    }
    ctx.fillStyle = "#000";
    ctx.fill();
    ctx.restore();
  },

  /**
   * Trace closed perimeter polygons around a Map<"x,y", mask>
   * of walkable tiles, tagging each emitted edge with whether
   * it sits on a wall line. Returns an array of loops; each
   * loop is an array of directed edges
   * `{ax, ay, bx, by, wall}` in clockwise order for outer
   * boundaries (counter-clockwise for holes, via the non-zero
   * fill rule). Handles multiple disjoint components naturally.
   *
   * The wall flag per edge comes from the tile's own wall mask
   * rather than FOV membership: an edge is a wall iff the tile
   * in that direction would not be walkable in the SVG world.
   */
  _buildTileSetPolygons(wallsMap) {
    const cs = this.cellSize;
    const pad = this.padding;
    // Wall-mask bits: 1=N, 2=E, 4=S, 8=W (matches backend).
    const WALL_N = 1, WALL_E = 2, WALL_S = 4, WALL_W = 8;

    // For each corner pixel-coordinate, record the outgoing
    // directed edges along with their wall flag.
    const outgoing = new Map();  // "px,py" → Array<{x,y,wall}>
    const pushEdge = (ax, ay, bx, by, wall) => {
      const k = `${ax},${ay}`;
      let list = outgoing.get(k);
      if (!list) { list = []; outgoing.set(k, list); }
      list.push({ x: bx, y: by, wall });
    };

    for (const [key, mask] of wallsMap) {
      const [tx, ty] = key.split(",").map(Number);
      const x0 = tx * cs + pad;
      const y0 = ty * cs + pad;
      const x1 = x0 + cs;
      const y1 = y0 + cs;
      if (!wallsMap.has(`${tx},${ty - 1}`)) {
        pushEdge(x0, y0, x1, y0, (mask & WALL_N) !== 0);
      }
      if (!wallsMap.has(`${tx + 1},${ty}`)) {
        pushEdge(x1, y0, x1, y1, (mask & WALL_E) !== 0);
      }
      if (!wallsMap.has(`${tx},${ty + 1}`)) {
        pushEdge(x1, y1, x0, y1, (mask & WALL_S) !== 0);
      }
      if (!wallsMap.has(`${tx - 1},${ty}`)) {
        pushEdge(x0, y1, x0, y0, (mask & WALL_W) !== 0);
      }
    }

    // Stitch edges into closed loops. The loop is built as a
    // raw list of 1-cell directed segments first, then runs of
    // colinear segments sharing the same wall flag are merged
    // into single edges for a clean offset pass.
    const loops = [];
    let safety = 0;
    const maxIters = wallsMap.size * 4 + 16;
    while (outgoing.size > 0 && safety++ < maxIters) {
      const startKey = outgoing.keys().next().value;
      const [sx, sy] = startKey.split(",").map(Number);
      const raw = [];  // list of {ax, ay, bx, by, wall}
      let cx = sx, cy = sy;

      while (true) {
        const k = `${cx},${cy}`;
        const list = outgoing.get(k);
        if (!list || list.length === 0) break;
        const next = list.shift();
        if (list.length === 0) outgoing.delete(k);
        raw.push({
          ax: cx, ay: cy, bx: next.x, by: next.y, wall: next.wall,
        });
        cx = next.x;
        cy = next.y;
        if (cx === sx && cy === sy) break;
        if (raw.length > maxIters) break;
      }
      if (raw.length < 3) continue;

      // Merge colinear runs with matching wall flag. A run of
      // several 1-cell segments along the same direction and
      // with the same wall flag collapses to one edge.
      const merged = [];
      for (const e of raw) {
        const last = merged[merged.length - 1];
        if (last) {
          const ldx = last.bx - last.ax;
          const ldy = last.by - last.ay;
          const edx = e.bx - e.ax;
          const edy = e.by - e.ay;
          if (ldx * edy === ldy * edx
              && last.wall === e.wall
              && last.bx === e.ax && last.by === e.ay) {
            last.bx = e.bx;
            last.by = e.by;
            continue;
          }
        }
        merged.push({ ...e });
      }
      // Last-to-first colinear stitch: if the loop closes with
      // a colinear same-flag pair at the seam, fold the first
      // edge into the last.
      if (merged.length >= 2) {
        const first = merged[0];
        const last = merged[merged.length - 1];
        const ldx = last.bx - last.ax;
        const ldy = last.by - last.ay;
        const fdx = first.bx - first.ax;
        const fdy = first.by - first.ay;
        if (ldx * fdy === ldy * fdx
            && last.wall === first.wall
            && last.bx === first.ax && last.by === first.ay) {
          first.ax = last.ax;
          first.ay = last.ay;
          merged.pop();
        }
      }
      if (merged.length >= 3) loops.push(merged);
    }
    return loops;
  },

  /**
   * Offset a closed loop of directed edges outward along each
   * edge's left-hand normal (outward for clockwise winding in
   * screen coordinates). Only edges with `wall === true` are
   * pushed by `dist`; non-wall edges stay on their original
   * line. Vertices are recomputed as the intersection of the
   * offset lines of consecutive edges, so wall↔non-wall corners
   * produce an L-shaped notch with the wall side sticking out
   * and the open side flush with the tile boundary.
   *
   * At colinear junctions with a flag transition (wall run
   * turning into a non-wall run along the same direction), the
   * two offset lines are parallel; we emit a perpendicular
   * bridge (the end of the previous offset edge then the start
   * of the current) so the polygon steps cleanly between them.
   */
  _offsetLoop(loop, dist) {
    const n = loop.length;
    if (n < 3) return [];

    // Compute the offset line endpoints for each edge.
    const lines = [];
    for (let i = 0; i < n; i++) {
      const e = loop[i];
      const dx = e.bx - e.ax;
      const dy = e.by - e.ay;
      const len = Math.hypot(dx, dy);
      if (len === 0) continue;
      const d = e.wall ? dist : 0;
      // Left-hand (outward) normal in screen coords: (dy, -dx).
      const nx = dy / len;
      const ny = -dx / len;
      lines.push({
        ax: e.ax + nx * d, ay: e.ay + ny * d,
        bx: e.bx + nx * d, by: e.by + ny * d,
      });
    }

    const m = lines.length;
    if (m < 3) return [];

    const out = [];
    for (let i = 0; i < m; i++) {
      const p = lines[(i - 1 + m) % m];
      const c = lines[i];
      const denom = (p.ax - p.bx) * (c.ay - c.by)
                  - (p.ay - p.by) * (c.ax - c.bx);
      if (Math.abs(denom) < 1e-9) {
        // Parallel offset lines — happens at a colinear
        // wall↔non-wall transition. Emit a perpendicular bridge
        // between the end of the previous offset edge and the
        // start of the current one.
        out.push({ x: p.bx, y: p.by });
        out.push({ x: c.ax, y: c.ay });
        continue;
      }
      const t = ((p.ax - c.ax) * (c.ay - c.by)
               - (p.ay - c.ay) * (c.ax - c.bx)) / denom;
      out.push({
        x: p.ax + t * (p.bx - p.ax),
        y: p.ay + t * (p.by - p.ay),
      });
    }
    return out;
  },

  drawFog() {
    const ctx = this.fogCtx;
    if (!ctx || !this.mapW || !this.mapH) return;

    ctx.clearRect(0, 0, this.mapW, this.mapH);

    // Prerevealed surfaces (town / keep / ruin / cottage / temple
    // courtyards) render without fog of war so the player can
    // see the structure on arrival. Entities and secrets stay
    // gated by the separate FOV-driven entity list.
    if (this.prerevealed) return;

    // Cover everything in fully opaque black
    ctx.fillStyle = "rgba(0, 0, 0, 1.0)";
    ctx.fillRect(0, 0, this.mapW, this.mapH);

    const cs = this.cellSize;
    const half = cs / 2;

    // Player pixel center
    const cx = this.playerX * cs + this.padding + half;
    const cy = this.playerY * cs + this.padding + half;

    // Compute the max distance from player to any FOV tile edge
    // to size the radii dynamically to the actual FOV extent.
    let maxDist = 0;
    for (const key of this.fov) {
      const [x, y] = key.split(",").map(Number);
      const tx = x * cs + this.padding + half;
      const ty = y * cs + this.padding + half;
      const d = Math.hypot(tx - cx, ty - cy);
      if (d > maxDist) maxDist = d;
    }
    maxDist += cs;

    // Two torch zones: bright inner, dim outer.
    // The gradient is one tile shorter than the FOV for a tight
    // torch feel. FOV tiles beyond the gradient get the memory
    // dim level so they never go fully black.
    const dimAlpha = 0.7;  // gradient outer rim only — memory tiles use memFloor/memCeil
    const innerR = maxDist * 0.2 + half;
    const outerR = maxDist + cs;

    if (this.fov.size > 0) {
      // Radial gradient: transparent center → dim edge (memory level)
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, outerR);
      grad.addColorStop(0, "rgba(0, 0, 0, 0)");
      grad.addColorStop(innerR / outerR, "rgba(0, 0, 0, 0)");
      grad.addColorStop(Math.min((innerR + half) / outerR, 0.95),
                        "rgba(0, 0, 0, 0.3)");
      grad.addColorStop(1, `rgba(0, 0, 0, ${dimAlpha})`);

      // Punch a gradient circle into the black fog
      ctx.save();
      ctx.globalCompositeOperation = "destination-out";
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
      ctx.fillStyle = "white";
      ctx.fill();
      ctx.restore();

      // Paint the gradient on top
      ctx.save();
      ctx.globalCompositeOperation = "source-over";
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.restore();

      // FOV tiles beyond the gradient: radial dim instead of black.
      // Alpha scales with distance so the falloff blends smoothly
      // with the gradient rather than forming a flat slab.
      const outerR2 = outerR * outerR;
      const memFloor = 0.55;       // brightest memory tile (nearby)
      const memCeil  = 0.75;       // darkest memory tile (far)
      const memReach = outerR * 1.5;  // distance where alpha saturates

      for (const key of this.fov) {
        const [x, y] = key.split(",").map(Number);
        const tx = x * cs + this.padding + half;
        const ty = y * cs + this.padding + half;
        const d2 = (tx - cx) * (tx - cx) + (ty - cy) * (ty - cy);
        if (d2 > outerR2) {
          const d = Math.sqrt(d2);
          const t = Math.min(d / memReach, 1);
          const a = memFloor + (memCeil - memFloor) * t;
          const px = x * cs + this.padding;
          const py = y * cs + this.padding;
          ctx.clearRect(px, py, cs, cs);
          ctx.fillStyle = `rgba(0, 0, 0, ${a.toFixed(3)})`;
          ctx.fillRect(px, py, cs, cs);
        }
      }

      // Explored but not visible: radial dim with recency bias.
      // Distance from the player controls base alpha (memFloor →
      // memCeil), and tiles seen more recently get a small
      // brightness boost that fades over ~30 turns.
      const recencyWindow = 30;

      for (const key of this.explored) {
        if (this.fov.has(key)) continue;
        const [x, y] = key.split(",").map(Number);
        const tx = x * cs + this.padding + half;
        const ty = y * cs + this.padding + half;
        const d = Math.hypot(tx - cx, ty - cy);
        const t = Math.min(d / memReach, 1);
        let a = memFloor + (memCeil - memFloor) * t;

        // Recency: recently-seen tiles are slightly brighter
        const seen = this.lastSeen.get(key);
        if (seen !== undefined) {
          const age = Math.max(0, this.turn - seen);
          // boost decays linearly over recencyWindow turns
          const recency = Math.max(0, 1 - age / recencyWindow);
          // reduce alpha by up to 0.10 for freshly-left tiles
          a -= 0.10 * recency;
        }

        const px = x * cs + this.padding;
        const py = y * cs + this.padding;
        ctx.clearRect(px, py, cs, cs);
        ctx.fillStyle = `rgba(0, 0, 0, ${a.toFixed(3)})`;
        ctx.fillRect(px, py, cs, cs);
      }
    } else {
      // No FOV at all — still show explored tiles at flat dim
      for (const key of this.explored) {
        const [x, y] = key.split(",").map(Number);
        const px = x * cs + this.padding;
        const py = y * cs + this.padding;
        ctx.clearRect(px, py, cs, cs);
        ctx.fillStyle = `rgba(0, 0, 0, 0.75)`;
        ctx.fillRect(px, py, cs, cs);
      }
    }
  },

  /**
   * Draw all accumulated doors on the door canvas.
   * Doors persist in the dimmed view when out of sight.
   */
  drawDoors() {
    const ctx = this.doorCtx;
    if (!ctx || !this.doorCanvas.width) return;
    ctx.clearRect(0, 0, this.doorCanvas.width,
                  this.doorCanvas.height);
    this._drawDoors(ctx, this.allDoors.values());
    this._drawDugTiles(ctx);
  },

  /**
   * Draw dug tile overlays on the door canvas.
   *
   * - dug_wall: soft brown fill covering the tile and extending
   *   into adjacent wall edges (room walls connected to the
   *   dug corridor).
   * - dug_floor: radial gradient disk (soft brown center fading
   *   to dark brown at the edge).
   */
  _drawDugTiles(ctx) {
    const cs = this.cellSize;
    const pad = this.padding;
    const wallW = 4;
    const brown = "rgb(139, 90, 43)";
    const edgeBrown = "rgba(139, 90, 43, 0.45)";

    for (const tile of this.dugTiles.values()) {
      const px = tile.x * cs + pad;
      const py = tile.y * cs + pad;
      const cx = px + cs / 2;
      const cy = py + cs / 2;

      if (tile.type === "wall") {
        // Fill tile with soft brown
        ctx.fillStyle = brown;
        ctx.fillRect(px, py, cs, cs);

        // Extend brown into adjacent wall edges
        ctx.fillStyle = edgeBrown;
        for (const edge of tile.edges) {
          if (edge === "top") {
            ctx.fillRect(px, py - wallW, cs, wallW);
          } else if (edge === "bottom") {
            ctx.fillRect(px, py + cs, cs, wallW);
          } else if (edge === "left") {
            ctx.fillRect(px - wallW, py, wallW, cs);
          } else if (edge === "right") {
            ctx.fillRect(px + cs, py, wallW, cs);
          }
        }
      } else {
        // Dug floor: radial gradient disk with quadratic falloff.
        // Dark brown center fading to soft brown at the edge.
        // Simulate quadratic curve with multiple color stops:
        //   alpha(t) = a_max * (1 - t^2)
        const r = cs * 0.35;
        const grad = ctx.createRadialGradient(
          cx, cy, 0, cx, cy, r,
        );
        const steps = 8;
        for (let i = 0; i <= steps; i++) {
          const t = i / steps;
          const q = 1 - t * t;  // quadratic falloff
          const rd = Math.round(80 + 80 * t);
          const g = Math.round(45 + 55 * t);
          const b = Math.round(20 + 30 * t);
          const a = (0.50 * q).toFixed(3);
          grad.addColorStop(t, `rgba(${rd},${g},${b},${a})`);
        }
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  },

  draw() {
    const ctx = this.ctx;
    if (!this.canvas.width || !this.canvas.height) {
      console.warn("draw skipped: zero canvas size");
      return;
    }
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    console.log("draw:", this.entities.length, "entities");

    for (const ent of this.entities) {
      const px = ent.x * this.cellSize + this.padding;
      const py = ent.y * this.cellSize + this.padding;

      // Detected entities: pulsating glow + fade
      if (ent.detected) {
        const pulse = 0.7 + 0.3 * Math.sin(Date.now() / 300);
        const alpha = (ent.glow_alpha || 1.0) * pulse;
        ctx.save();
        ctx.shadowColor = ent.glow_color || "#00CCFF";
        ctx.shadowBlur = 14 * alpha;
        ctx.globalAlpha = 0.5 + 0.5 * (ent.glow_alpha || 1.0);
      }

      // Image-type tileset: draw from sprite sheet
      if (this.tileset && this.tileset.type === "image"
          && this.tilesetImg) {
        const sprite = this.tileset.sprites[ent.glyph];
        if (sprite && sprite.x !== undefined) {
          ctx.drawImage(
            this.tilesetImg,
            sprite.x, sprite.y,
            this.tileset.tile_size, this.tileset.tile_size,
            px, py,
            this.cellSize, this.cellSize,
          );
          if (ent.detected) ctx.restore();
          continue;
        }
      }

      // Text-type tileset or fallback: draw glyph as text
      const font = (this.tileset && this.tileset.font)
        || `bold ${this.cellSize - 4}px monospace`;
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      let color = ent.color || "#FFFFFF";
      if (this.tileset && this.tileset.sprites) {
        const sprite = this.tileset.sprites[ent.glyph];
        // Entity color takes priority over sprite default —
        // allows same glyph (e.g. @) to differ per entity.
        if (ent.color) {
          color = this._resolveColor(ent.color);
        } else if (sprite && sprite.color) {
          color = this._resolveColor(sprite.color);
        } else {
          color = this._resolveColor(color);
        }
      }

      const cx = px + this.cellSize / 2;
      const cy = py + this.cellSize / 2;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.strokeStyle = ent.is_player ? "#1a3a6b" : "#000000";
      ctx.strokeText(ent.glyph, cx, cy);
      ctx.fillStyle = color;
      ctx.fillText(ent.glyph, cx, cy);

      if (ent.detected) ctx.restore();
    }
  },

  /**
   * Draw doors on the entity canvas.
   *
   * - door_secret (undiscovered): not drawn (invisible wall)
   * - door_closed / door_locked: black-filled rectangle on the wall
   *   line, 80% tile in wall direction, ~25% across passage, with
   *   small wall connection lines on each side
   * - door_open: same rectangle but white-filled
   */
  _drawDoors(ctx, doorIter) {
    const cs = this.cellSize;
    const pad = this.padding;
    const wallW = 4;             // match SVG WALL_WIDTH
    const doorLen = cs * 0.75;   // 75% of tile along wall
    const doorDepth = wallW * 2; // twice wall thickness
    const connLen = cs * 0.1;    // wall connection stub

    for (const door of doorIter) {
      const px = door.x * cs + pad;
      const py = door.y * cs + pad;
      const cx = px + cs / 2;
      const cy = py + cs / 2;

      // Secret doors: draw a wall segment on the door edge
      if (door.state === "door_secret") {
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        if (door.edge === "left") {
          ctx.moveTo(px, py); ctx.lineTo(px, py + cs);
        } else if (door.edge === "right") {
          ctx.moveTo(px + cs, py); ctx.lineTo(px + cs, py + cs);
        } else if (door.edge === "top") {
          ctx.moveTo(px, py); ctx.lineTo(px + cs, py);
        } else {
          ctx.moveTo(px, py + cs); ctx.lineTo(px + cs, py + cs);
        }
        ctx.stroke();
        continue;
      }

      const fill = door.state === "door_open" ? "#FFFFFF" : "#5C3A1E";

      // Position door on the correct wall edge
      let wallX, wallY;
      if (door.edge === "left")        { wallX = px;      wallY = cy; }
      else if (door.edge === "right")  { wallX = px + cs; wallY = cy; }
      else if (door.edge === "top")    { wallX = cx;      wallY = py; }
      else /* bottom */                { wallX = cx;      wallY = py + cs; }

      if (door.vertical) {
        // Wall runs top-bottom, door is a tall narrow rect on the edge
        const dx = wallX - doorDepth / 2;
        const dy = py + (cs - doorLen) / 2;

        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(dx - 2, dy - 2, doorDepth + 4, doorLen + 4);

        ctx.fillStyle = fill;
        ctx.fillRect(dx, dy, doorDepth, doorLen);
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1;
        ctx.strokeRect(dx, dy, doorDepth, doorLen);

        // Wall stubs above and below
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(wallX, dy);
        ctx.lineTo(wallX, dy - connLen);
        ctx.moveTo(wallX, dy + doorLen);
        ctx.lineTo(wallX, dy + doorLen + connLen);
        ctx.stroke();
      } else {
        // Wall runs left-right, door is a wide short rect on the edge
        const dx = px + (cs - doorLen) / 2;
        const dy = wallY - doorDepth / 2;

        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(dx - 2, dy - 2, doorLen + 4, doorDepth + 4);

        ctx.fillStyle = fill;
        ctx.fillRect(dx, dy, doorLen, doorDepth);
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1;
        ctx.strokeRect(dx, dy, doorLen, doorDepth);

        // Wall stubs left and right
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(dx, wallY);
        ctx.lineTo(dx - connLen, wallY);
        ctx.moveTo(dx + doorLen, wallY);
        ctx.lineTo(dx + doorLen + connLen, wallY);
        ctx.stroke();
      }
    }
  },

  pixelToGrid(canvasX, canvasY) {
    const gx = Math.floor((canvasX - this.padding) / this.cellSize);
    const gy = Math.floor((canvasY - this.padding) / this.cellSize);
    return { x: gx, y: gy };
  },

  /**
   * Convert a screen-space click position (relative to
   * map-container's getBoundingClientRect) into unscaled canvas
   * coordinates, accounting for CSS transform scale.
   *
   * getBoundingClientRect already accounts for scroll position,
   * so no scroll offset should be added by the caller.
   */
  screenToCanvas(screenX, screenY) {
    const scale = this._zoomSteps[this._zoomLevel] || 1.0;
    return {
      x: screenX / scale,
      y: screenY / scale,
    };
  },

  initTooltip() {
    const zone = document.getElementById("map-zone");
    if (!zone) return;
    this._tooltip = document.createElement("div");
    this._tooltip.id = "map-tooltip";
    this._tooltip.className = "hidden";
    document.body.appendChild(this._tooltip);
    this._tooltipEntity = null;

    zone.addEventListener("mousemove", (e) => {
      const container = document.getElementById("map-container");
      const rect = container.getBoundingClientRect();
      const canvas = this.screenToCanvas(
        e.clientX - rect.left, e.clientY - rect.top,
      );
      const grid = this.pixelToGrid(canvas.x, canvas.y);

      const ent = this.entities.find(
        en => en.x === grid.x && en.y === grid.y && en.glyph !== "@"
      );
      if (ent && ent.name) {
        let text = ent.name;
        if (ent.hp !== undefined && ent.max_hp !== undefined) {
          text += ` (${ent.hp}/${ent.max_hp} HP)`;
        }
        this._tooltip.textContent = text;
        this._tooltip.style.left = (e.clientX + 12) + "px";
        this._tooltip.style.top = (e.clientY - 8) + "px";
        this._tooltip.classList.remove("hidden");
        this._tooltipEntity = ent.id;
      } else {
        this._tooltip.classList.add("hidden");
        this._tooltipEntity = null;
      }
    });

    zone.addEventListener("mouseleave", () => {
      this._tooltip.classList.add("hidden");
      this._tooltipEntity = null;
    });
  },

  /**
   * Play a transient visual effect on a tile.
   * "dig_treasure" — fading-to-black circle.
   * "dig_hole"     — fading-to-black square.
   */
  playEffect(effect, gx, gy) {
    const cs = this.cellSize;
    const pad = this.padding;
    const cx = gx * cs + pad + cs / 2;
    const cy = gy * cs + pad + cs / 2;
    const ctx = this.ctx;
    const duration = 500;
    const start = performance.now();

    const animate = (now) => {
      const t = Math.min((now - start) / duration, 1);
      // Redraw entities first so the effect overlays cleanly
      this.draw();

      ctx.save();
      ctx.globalAlpha = t;
      ctx.fillStyle = "#000";

      if (effect === "dig_treasure") {
        const r = cs * 0.38;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();
      } else if (effect === "dig_hole") {
        const half = cs * 0.44;
        ctx.fillRect(cx - half, cy - half, half * 2, half * 2);
      }

      ctx.restore();

      if (t < 1) {
        requestAnimationFrame(animate);
      }
    };

    requestAnimationFrame(animate);
  },
};

/* ------------------------------------------------------------------ */
/* Two-finger gestures on the map viewport                            */
/* ------------------------------------------------------------------ */

(function initMapGestures() {
  const zone = document.getElementById("map-zone");
  if (!zone) return;

  // ── Wheel zoom (Ctrl+wheel or trackpad pinch) ──
  // Without Ctrl the wheel scrolls the viewport normally.
  zone.addEventListener("wheel", (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const dir = e.deltaY < 0 ? 1 : -1;
    GameMap.zoom(dir);
    if (typeof Input !== "undefined") Input._updateZoomLabel();
  }, { passive: false });

  // ── Touch pinch-to-zoom + two-finger pan ──
  let _touches = [];
  let _lastPinchDist = 0;
  let _lastPanX = 0;
  let _lastPanY = 0;

  function _touchDist(t) {
    const dx = t[0].clientX - t[1].clientX;
    const dy = t[0].clientY - t[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function _touchCenter(t) {
    return {
      x: (t[0].clientX + t[1].clientX) / 2,
      y: (t[0].clientY + t[1].clientY) / 2,
    };
  }

  zone.addEventListener("touchstart", (e) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      _touches = Array.from(e.touches);
      _lastPinchDist = _touchDist(_touches);
      const c = _touchCenter(_touches);
      _lastPanX = c.x;
      _lastPanY = c.y;
    }
  }, { passive: false });

  zone.addEventListener("touchmove", (e) => {
    if (e.touches.length !== 2) return;
    e.preventDefault();
    const cur = Array.from(e.touches);
    const dist = _touchDist(cur);
    const center = _touchCenter(cur);

    // Pinch zoom: threshold of 30px change per step
    const delta = dist - _lastPinchDist;
    if (Math.abs(delta) > 30) {
      GameMap.zoom(delta > 0 ? 1 : -1);
      if (typeof Input !== "undefined") Input._updateZoomLabel();
      _lastPinchDist = dist;
    }

    // Two-finger pan: scroll the viewport
    const panDx = _lastPanX - center.x;
    const panDy = _lastPanY - center.y;
    zone.scrollLeft += panDx;
    zone.scrollTop += panDy;
    _lastPanX = center.x;
    _lastPanY = center.y;
  }, { passive: false });

  zone.addEventListener("touchend", () => {
    _touches = [];
    _lastPinchDist = 0;
  });
})();
