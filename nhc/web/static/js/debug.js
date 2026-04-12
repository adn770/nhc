/**
 * God mode debug panel — layer visibility, debug overlays, FOV info.
 *
 * Activated when the server reports god_mode=true. Adds a gear icon
 * to the toolbar that opens a floating tabbed dialog.
 */
const DebugPanel = {
  enabled: false,
  visible: false,
  debugData: null,
  debugCanvas: null,
  debugCtx: null,

  // Layer visibility state
  layers: {
    floor: true,
    doors: true,
    entities: true,
    hatch: true,
    fog: true,
  },

  // Debug overlay state
  overlays: {
    roomLabels: false,
    doorLabels: false,
    corridorLabels: false,
    tileCoords: false,
    secrets: false,
  },

  // Tab definitions — extensible
  _tabs: [
    { name: "Layers", buildFn: "_buildLayersTab" },
    { name: "Map Gen", buildFn: "_buildMapGenTab" },
    { name: "Export", buildFn: "_buildExportTab" },
  ],

  // Map Gen state
  _mapGenParams: null,
  _themeAuto: true,

  init() {
    this.debugCanvas = document.getElementById("debug-canvas");
    if (this.debugCanvas) {
      this.debugCtx = this.debugCanvas.getContext("2d");
    }
    this._createGearButton();
    this._onEsc = (e) => {
      if (e.key === "Escape" && this.visible) this._hidePanel();
    };
    document.addEventListener("keydown", this._onEsc);
  },

  setDebugData(data) {
    this.debugData = data;
    console.log("DebugPanel: received debug data —",
                data.rooms.length, "rooms,",
                data.corridors.length, "corridors,",
                data.doors.length, "doors");
    this._drawDebugOverlays();
  },

  // ── Gear button ──────────────────────────────────────────────

  _createGearButton() {
    const zone = document.getElementById("toolbar-zone");
    if (!zone) return;
    if (document.getElementById("god-mode-btn")) return;

    const dlBtn = document.createElement("button");
    dlBtn.id = "debug-bundle-btn";
    dlBtn.textContent = "\uD83D\uDCBE";
    dlBtn.title = "Download Debug Bundle";
    dlBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const sid = NHC.sessionId;
      if (sid) window.location.href = `/api/game/${sid}/export/bundle`;
    });
    zone.appendChild(dlBtn);

    const btn = document.createElement("button");
    btn.id = "god-mode-btn";
    btn.textContent = "\u2699";
    btn.title = "Debug Panel (God Mode)";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      this._togglePanel();
    });
    zone.appendChild(btn);
  },

  // ── Panel toggle ─────────────────────────────────────────────

  _togglePanel() {
    if (this.visible) {
      this._hidePanel();
    } else {
      this._showPanel();
    }
  },

  _showPanel() {
    if (document.getElementById("debug-panel")) return;
    const panel = this._buildPanel();
    document.body.appendChild(panel);
    this.visible = true;
    this._fetchHenchmen();

    // Dismiss on click outside
    this._onOutsideClick = (e) => {
      const panel = document.getElementById("debug-panel");
      const btn = document.getElementById("god-mode-btn");
      if (panel && !panel.contains(e.target)
          && btn && !btn.contains(e.target)) {
        this._hidePanel();
      }
    };
    setTimeout(() => {
      document.addEventListener("click", this._onOutsideClick);
    }, 0);
  },

  _hidePanel() {
    const panel = document.getElementById("debug-panel");
    if (panel) panel.remove();
    this.visible = false;
    if (this._onOutsideClick) {
      document.removeEventListener("click", this._onOutsideClick);
      this._onOutsideClick = null;
    }
  },

  // ── Drag support ─────────────────────────────────────────────

  _makeDraggable(panel, handle) {
    let startX, startY, startLeft, startTop;

    const onMouseMove = (e) => {
      panel.style.left = (startLeft + e.clientX - startX) + "px";
      panel.style.top = (startTop + e.clientY - startY) + "px";
    };

    const onMouseUp = () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    handle.addEventListener("mousedown", (e) => {
      // Only drag from the tab bar background, not from tab buttons
      if (e.target.tagName === "BUTTON") return;
      e.preventDefault();
      // Convert right-positioned panel to left-positioned on first drag
      if (panel.style.right || !panel.style.left) {
        const rect = panel.getBoundingClientRect();
        panel.style.left = rect.left + "px";
        panel.style.top = rect.top + "px";
        panel.style.right = "auto";
      }
      startX = e.clientX;
      startY = e.clientY;
      startLeft = parseInt(panel.style.left);
      startTop = parseInt(panel.style.top);
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  },

  // ── Panel construction ───────────────────────────────────────

  _buildPanel() {
    const panel = document.createElement("div");
    panel.id = "debug-panel";

    // Tab bar
    const tabBar = document.createElement("div");
    tabBar.className = "debug-tabs";

    const panes = [];
    this._panel = panel;
    this._tabBar = tabBar;
    this._panes = panes;

    this._tabs.forEach((tab, i) => {
      this._addTab(tab.name, this[tab.buildFn](), i === 0);
    });

    panel.appendChild(tabBar);
    panes.forEach((p) => panel.appendChild(p));

    // Drag via tab bar
    this._makeDraggable(panel, tabBar);

    return panel;
  },

  _addTab(name, content, makeActive) {
    const tabBar = this._tabBar;
    const panes = this._panes;
    const panel = this._panel;
    if (!tabBar || !panes || !panel) return null;

    const tabBtn = document.createElement("button");
    tabBtn.className = "debug-tab" + (makeActive ? " active" : "");
    tabBtn.textContent = name;

    const pane = document.createElement("div");
    pane.className = "debug-tab-content"
                     + (makeActive ? " active" : "");
    if (content) pane.appendChild(content);
    panes.push(pane);

    tabBtn.addEventListener("click", () => {
      tabBar.querySelectorAll(".debug-tab").forEach(
        (t) => t.classList.remove("active"));
      panes.forEach((p) => p.classList.remove("active"));
      tabBtn.classList.add("active");
      pane.classList.add("active");
    });

    tabBar.appendChild(tabBtn);
    panel.appendChild(pane);
    return { tabBtn, pane };
  },

  // ── Layers tab ───────────────────────────────────────────────

  _buildLayersTab() {
    const frag = document.createDocumentFragment();

    // Rendering layers section
    const renderHeader = this._sectionHeader("Rendering Layers");
    frag.appendChild(renderHeader);

    const renderLayers = [
      { key: "floor",    label: "Floor SVG",     el: "#floor-svg" },
      { key: "doors",    label: "Door Canvas",   el: "#door-canvas" },
      { key: "entities", label: "Entity Canvas", el: "#entity-canvas" },
      { key: "hatch",    label: "Hatch Canvas",  el: "#hatch-canvas" },
      { key: "fog",      label: "Fog Canvas",    el: "#fog-canvas" },
    ];

    renderLayers.forEach(({ key, label, el }) => {
      const row = this._checkboxRow(label, this.layers[key], (on) => {
        this.layers[key] = on;
        const target = document.querySelector(el);
        if (target) target.style.display = on ? "" : "none";
      });
      frag.appendChild(row);
    });

    // Debug overlays section
    const overlayHeader = this._sectionHeader("Debug Overlays");
    frag.appendChild(overlayHeader);

    const overlayLayers = [
      { key: "roomLabels",     label: "Room Labels" },
      { key: "doorLabels",     label: "Door Labels" },
      { key: "corridorLabels", label: "Corridor Labels" },
      { key: "tileCoords",     label: "Tile Coordinates" },
      { key: "secrets",        label: "Secrets" },
    ];

    overlayLayers.forEach(({ key, label }) => {
      const row = this._checkboxRow(
        label, this.overlays[key], (on) => {
          this.overlays[key] = on;
          this._drawDebugOverlays();
        });
      frag.appendChild(row);
    });

    // FOV / FOW info section
    const fovHeader = this._sectionHeader("FOV / FOW");
    frag.appendChild(fovHeader);

    const radius = this.debugData ? this.debugData.fov_radius : "?";
    frag.appendChild(this._infoRow("FOV Radius", radius));
    frag.appendChild(this._infoRow("Visible tiles",
                                   GameMap.fov.size, "fov-count"));
    frag.appendChild(this._infoRow("Explored tiles",
                                   GameMap.explored.size,
                                   "explored-count"));
    frag.appendChild(this._infoRow("Fog (unexplored)", "1.0"));
    frag.appendChild(this._infoRow("Fog (explored)", "0.7"));
    frag.appendChild(this._infoRow("Fog (visible)", "0.0"));

    return frag;
  },

  // ── DOM helpers ──────────────────────────────────────────────

  _sectionHeader(text) {
    const h = document.createElement("div");
    h.className = "debug-section-header";
    h.textContent = text;
    return h;
  },

  _checkboxRow(label, checked, onChange) {
    const row = document.createElement("label");
    row.className = "debug-layer-row";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = checked;
    cb.addEventListener("change", () => onChange(cb.checked));
    row.appendChild(cb);
    row.appendChild(document.createTextNode(label));
    return row;
  },

  _infoRow(label, value, valueId) {
    const row = document.createElement("div");
    row.className = "debug-info-row";
    const lbl = document.createElement("span");
    lbl.textContent = label;
    const val = document.createElement("span");
    val.className = "value";
    val.textContent = value;
    if (valueId) val.id = "debug-" + valueId;
    row.appendChild(lbl);
    row.appendChild(val);
    return row;
  },

  // ── Map Gen helpers ──────────────────────────────────────

  _themeForDepth(depth) {
    if (depth <= 4) return "dungeon";
    if (depth <= 8) return "crypt";
    if (depth <= 12) return "cave";
    if (depth <= 16) return "castle";
    return "abyss";
  },

  _numberInput(label, value, opts, onChange) {
    const row = document.createElement("div");
    row.className = "debug-number-row";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    const inp = document.createElement("input");
    inp.type = "number";
    inp.value = value;
    if (opts.min !== undefined) inp.min = opts.min;
    if (opts.max !== undefined) inp.max = opts.max;
    if (opts.step !== undefined) inp.step = opts.step;
    inp.addEventListener("change", () => onChange(Number(inp.value)));
    row.appendChild(lbl);
    row.appendChild(inp);
    return row;
  },

  _rangeInput(label, minVal, maxVal, opts, onChange) {
    const row = document.createElement("div");
    row.className = "debug-range-row";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    const wrap = document.createElement("span");
    wrap.className = "range-inputs";
    const minInp = document.createElement("input");
    minInp.type = "number";
    minInp.value = minVal;
    if (opts.min !== undefined) minInp.min = opts.min;
    if (opts.max !== undefined) minInp.max = opts.max;
    const sep = document.createElement("span");
    sep.className = "range-sep";
    sep.textContent = "\u2013";
    const maxInp = document.createElement("input");
    maxInp.type = "number";
    maxInp.value = maxVal;
    if (opts.min !== undefined) maxInp.min = opts.min;
    if (opts.max !== undefined) maxInp.max = opts.max;
    const fire = () => onChange(Number(minInp.value),
                                Number(maxInp.value));
    minInp.addEventListener("change", fire);
    maxInp.addEventListener("change", fire);
    wrap.appendChild(minInp);
    wrap.appendChild(sep);
    wrap.appendChild(maxInp);
    row.appendChild(lbl);
    row.appendChild(wrap);
    return row;
  },

  _selectRow(label, options, selected, onChange) {
    const row = document.createElement("div");
    row.className = "debug-select-row";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    const sel = document.createElement("select");
    for (const opt of options) {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt;
      if (opt === selected) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => onChange(sel.value));
    row.appendChild(lbl);
    row.appendChild(sel);
    return { row, select: sel };
  },

  // ── Map Gen tab ─────────────────────────────────────────

  _buildMapGenTab() {
    const frag = document.createDocumentFragment();
    const p = this._mapGenParams || {};

    // Section: Dimensions
    frag.appendChild(this._sectionHeader("Dimensions"));
    frag.appendChild(this._numberInput(
      "Width", p.width || 120, { min: 40, max: 200 },
      (v) => { this._mapGenParams.width = v; }));
    frag.appendChild(this._numberInput(
      "Height", p.height || 40, { min: 20, max: 80 },
      (v) => { this._mapGenParams.height = v; }));

    // Section: Depth & Theme
    frag.appendChild(this._sectionHeader("Depth & Theme"));

    const depthRow = this._numberInput(
      "Depth", p.depth || 1, { min: 1, max: 30 },
      (v) => {
        this._mapGenParams.depth = v;
        if (this._themeAuto && themeCtrl) {
          const auto = this._themeForDepth(v);
          themeCtrl.select.value = auto;
          this._mapGenParams.theme = auto;
          if (autoHint) autoHint.textContent = "(auto)";
        }
      });
    frag.appendChild(depthRow);

    const themes = [
      "dungeon", "crypt", "cave", "castle", "abyss",
      "forest", "sewer",
    ];
    const themeCtrl = this._selectRow(
      "Theme", themes, p.theme || "dungeon",
      (v) => {
        this._mapGenParams.theme = v;
        this._themeAuto = false;
        if (autoHint) autoHint.textContent = "(manual)";
      });
    const autoHint = document.createElement("span");
    autoHint.className = "auto-hint";
    autoHint.textContent = this._themeAuto ? "(auto)" : "(manual)";
    themeCtrl.row.appendChild(autoHint);
    frag.appendChild(themeCtrl.row);

    // Section: Rooms
    frag.appendChild(this._sectionHeader("Rooms"));
    const rc = p.room_count || { min: 5, max: 15 };
    frag.appendChild(this._rangeInput(
      "Room Count", rc.min, rc.max, { min: 1, max: 30 },
      (mn, mx) => {
        this._mapGenParams.room_count = { min: mn, max: mx };
      }));
    const rs = p.room_size || { min: 4, max: 12 };
    frag.appendChild(this._rangeInput(
      "Room Size", rs.min, rs.max, { min: 2, max: 20 },
      (mn, mx) => {
        this._mapGenParams.room_size = { min: mn, max: mx };
      }));
    frag.appendChild(this._numberInput(
      "Shape Variety", p.shape_variety || 0.0,
      { min: 0, max: 1, step: 0.05 },
      (v) => { this._mapGenParams.shape_variety = v; }));

    // Section: Corridors
    frag.appendChild(this._sectionHeader("Corridors"));
    const styles = ["straight", "bent", "organic"];
    const styleCtrl = this._selectRow(
      "Style", styles, p.corridor_style || "straight",
      (v) => { this._mapGenParams.corridor_style = v; });
    frag.appendChild(styleCtrl.row);
    frag.appendChild(this._numberInput(
      "Density", p.density || 0.4, { min: 0, max: 1, step: 0.05 },
      (v) => { this._mapGenParams.density = v; }));
    frag.appendChild(this._numberInput(
      "Connectivity", p.connectivity || 0.8,
      { min: 0, max: 1, step: 0.05 },
      (v) => { this._mapGenParams.connectivity = v; }));

    // Section: Features
    frag.appendChild(this._sectionHeader("Features"));
    frag.appendChild(this._checkboxRow(
      "Dead Ends", p.dead_ends !== false, (on) => {
        this._mapGenParams.dead_ends = on;
      }));
    frag.appendChild(this._numberInput(
      "Secret Doors", p.secret_doors || 0.1,
      { min: 0, max: 0.5, step: 0.05 },
      (v) => { this._mapGenParams.secret_doors = v; }));
    frag.appendChild(this._checkboxRow(
      "Water Features", p.water_features || false, (on) => {
        this._mapGenParams.water_features = on;
      }));
    frag.appendChild(this._checkboxRow(
      "Multiple Stairs", p.multiple_stairs || false, (on) => {
        this._mapGenParams.multiple_stairs = on;
      }));

    // Section: Seed
    frag.appendChild(this._sectionHeader("Seed"));
    const seedRow = document.createElement("div");
    seedRow.className = "debug-seed-row";
    const seedLbl = document.createElement("label");
    seedLbl.textContent = "Seed";
    const seedInp = document.createElement("input");
    seedInp.type = "text";
    seedInp.value = p.seed != null ? p.seed : "";
    seedInp.placeholder = "random";
    seedInp.addEventListener("change", () => {
      const v = seedInp.value.trim();
      this._mapGenParams.seed = v ? Number(v) : null;
    });
    const randBtn = document.createElement("button");
    randBtn.className = "seed-random-btn";
    randBtn.textContent = "Rnd";
    randBtn.title = "Use random seed";
    randBtn.addEventListener("click", () => {
      seedInp.value = "";
      this._mapGenParams.seed = null;
    });
    seedRow.appendChild(seedLbl);
    seedRow.appendChild(seedInp);
    seedRow.appendChild(randBtn);
    frag.appendChild(seedRow);

    // Regenerate button
    const regenBtn = document.createElement("button");
    regenBtn.className = "debug-regen-btn";
    regenBtn.textContent = "Regenerate Map";
    const statusEl = document.createElement("div");
    statusEl.className = "debug-regen-status";
    regenBtn.addEventListener("click", async () => {
      regenBtn.disabled = true;
      regenBtn.textContent = "Regenerating...";
      statusEl.textContent = "";
      try {
        const resp = await fetch(
          `/api/game/${NHC.sessionId}/regenerate`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(this._mapGenParams),
          },
        );
        const data = await resp.json();
        if (resp.ok) {
          statusEl.textContent = `Done — seed ${data.seed}, `
            + `${data.params.theme} d${data.params.depth}`;
          // Update params but clear seed so next regen is random
          this._mapGenParams = data.params;
          this._mapGenParams.seed = null;
          seedInp.value = "";
          seedInp.placeholder = `last: ${data.seed}`;
        } else {
          statusEl.textContent = `Error: ${data.error || "failed"}`;
        }
      } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
      }
      regenBtn.disabled = false;
      regenBtn.textContent = "Regenerate Map";
    });
    frag.appendChild(regenBtn);
    frag.appendChild(statusEl);

    // Fetch current params to populate
    if (!this._mapGenParams) {
      this._fetchParams(seedInp, themeCtrl.select, autoHint);
    }

    return frag;
  },

  async _fetchParams(seedInp, themeSel, autoHint) {
    try {
      const resp = await fetch(
        `/api/game/${NHC.sessionId}/generation_params`);
      if (resp.ok) {
        this._mapGenParams = await resp.json();
        // Update seed input if available
        if (seedInp && this._mapGenParams.seed != null) {
          seedInp.value = this._mapGenParams.seed;
        }
        // Check if theme matches auto
        const auto = this._themeForDepth(this._mapGenParams.depth);
        this._themeAuto = (this._mapGenParams.theme === auto);
        if (autoHint) {
          autoHint.textContent = this._themeAuto
            ? "(auto)" : "(manual)";
        }
      }
    } catch (e) {
      console.warn("Failed to fetch generation params:", e);
    }
  },

  // ── FOV info live updates ────────────────────────────────────

  updateFovInfo() {
    if (!this.visible) return;
    const fov = document.getElementById("debug-fov-count");
    const exp = document.getElementById("debug-explored-count");
    if (fov) fov.textContent = GameMap.fov.size;
    if (exp) exp.textContent = GameMap.explored.size;
  },

  // ── Debug overlay drawing ────────────────────────────────────

  _drawDebugOverlays() {
    const ctx = this.debugCtx;
    if (!ctx || !this.debugCanvas) return;
    ctx.clearRect(0, 0,
                  this.debugCanvas.width, this.debugCanvas.height);

    if (this.overlays.roomLabels) this._drawRoomLabels(ctx);
    if (this.overlays.doorLabels) this._drawDoorLabels(ctx);
    if (this.overlays.corridorLabels) this._drawCorridorLabels(ctx);
    if (this.overlays.tileCoords) this._drawTileCoords(ctx);
    if (this.overlays.secrets) this._drawSecrets(ctx);
  },

  _drawRoomLabels(ctx) {
    if (!this.debugData) return;
    const cs = GameMap.cellSize;
    const pad = GameMap.padding;

    for (const room of this.debugData.rooms) {
      const cx = pad + (room.x + room.w / 2) * cs;
      const cy = pad + (room.y + room.h / 2) * cs;

      // Background pill
      const bw = 120, bh = 44;
      ctx.fillStyle = "rgba(255,255,240,0.85)";
      ctx.strokeStyle = "#888";
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.roundRect(cx - bw / 2, cy - bh / 2, bw, bh, 4);
      ctx.fill();
      ctx.stroke();

      // Room number
      ctx.font = "bold 13px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#D32F2F";
      ctx.fillText(`#${room.index}`, cx, cy - 12);

      // Shape type
      ctx.font = "9px monospace";
      ctx.fillStyle = "#333";
      ctx.fillText(room.shape, cx, cy + 1);

      // Dimensions
      ctx.fillStyle = "#555";
      ctx.fillText(`${room.w}x${room.h}`, cx, cy + 13);
    }
  },

  _drawDoorLabels(ctx) {
    if (!this.debugData) return;
    const cs = GameMap.cellSize;
    const pad = GameMap.padding;

    for (const door of this.debugData.doors) {
      const cx = pad + door.x * cs + cs / 2;
      const cy = pad + door.y * cs + cs / 2;
      const label = `D${door.index} ${door.kind}`;

      // Background pill
      const bw = 36, bh = 14;
      ctx.fillStyle = "rgba(200,220,255,0.8)";
      ctx.strokeStyle = "#1565C0";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.roundRect(cx - bw / 2, cy - bh / 2, bw, bh, 2);
      ctx.fill();
      ctx.stroke();

      // Label
      ctx.font = "bold 10px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#0D47A1";
      ctx.fillText(label, cx, cy);
    }
  },

  _drawCorridorLabels(ctx) {
    if (!this.debugData) return;
    const cs = GameMap.cellSize;
    const pad = GameMap.padding;

    for (const cor of this.debugData.corridors) {
      const cx = pad + (cor.cx + 0.5) * cs;
      const cy = pad + (cor.cy + 0.5) * cs;
      const label = `C${cor.index}`;

      // Background pill
      const bw = 28, bh = 14;
      ctx.fillStyle = "rgba(220,240,220,0.85)";
      ctx.strokeStyle = "#4a7a4a";
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.roundRect(cx - bw / 2, cy - bh / 2, bw, bh, 3);
      ctx.fill();
      ctx.stroke();

      // Label
      ctx.font = "bold 9px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#2e5a2e";
      ctx.fillText(label, cx, cy);
    }
  },

  _drawTileCoords(ctx) {
    if (!this.debugData) return;
    const cs = GameMap.cellSize;
    const pad = GameMap.padding;
    const w = this.debugData.map_width;
    const h = this.debugData.map_height;

    ctx.save();
    ctx.globalAlpha = 0.45;
    ctx.font = "6px monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillStyle = "#333";

    for (const key of GameMap.explored) {
      const [x, y] = key.split(",").map(Number);
      if (x < 0 || x >= w || y < 0 || y >= h) continue;
      const px = pad + x * cs + 2;
      const py = pad + y * cs + 2;
      ctx.fillText(`${x},${y}`, px, py);
    }
    ctx.restore();
  },

  _drawSecrets(ctx) {
    if (!this.debugData || !this.debugData.secrets) return;
    const cs = GameMap.cellSize;
    const pad = GameMap.padding;
    const secrets = this.debugData.secrets;

    // Secret doors — magenta diamond
    for (const d of secrets.secret_doors) {
      const cx = pad + d.x * cs + cs / 2;
      const cy = pad + d.y * cs + cs / 2;
      const r = cs * 0.35;
      ctx.save();
      ctx.fillStyle = "rgba(200,0,200,0.45)";
      ctx.strokeStyle = "#c000c0";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx, cy - r);
      ctx.lineTo(cx + r, cy);
      ctx.lineTo(cx, cy + r);
      ctx.lineTo(cx - r, cy);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.font = "bold 8px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#fff";
      ctx.fillText("S", cx, cy);
      ctx.restore();
    }

    // Buried items — amber circle with count
    for (const b of secrets.buried) {
      const cx = pad + b.x * cs + cs / 2;
      const cy = pad + b.y * cs + cs / 2;
      const r = cs * 0.3;
      ctx.save();
      ctx.fillStyle = "rgba(255,180,0,0.5)";
      ctx.strokeStyle = "#c08000";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.font = "bold 9px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#fff";
      ctx.fillText(String(b.count), cx, cy);
      ctx.restore();
    }

    // Hidden traps — red triangle with effect initial
    for (const t of secrets.hidden_traps) {
      const cx = pad + t.x * cs + cs / 2;
      const cy = pad + t.y * cs + cs / 2;
      const r = cs * 0.35;
      ctx.save();
      ctx.fillStyle = "rgba(220,40,40,0.5)";
      ctx.strokeStyle = "#c00";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx, cy - r);
      ctx.lineTo(cx + r, cy + r * 0.7);
      ctx.lineTo(cx - r, cy + r * 0.7);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      const label = t.effect ? t.effect[0].toUpperCase() : "?";
      ctx.font = "bold 8px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#fff";
      ctx.fillText(label, cx, cy + 1);
      ctx.restore();
    }
  },

  // ── Henchman tabs ────────────────────────────────────────────

  async _fetchHenchmen() {
    const sid = NHC.sessionId;
    if (!sid) return;
    try {
      const resp = await fetch(`/api/game/${sid}/henchmen`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (!this.visible) return;
      (data.henchmen || []).forEach((sheet) => {
        const label = (sheet.short || sheet.name || `#${sheet.id}`)
          .split(" ")[0];
        this._addTab(label, this._buildHenchmanSheet(sheet), false);
      });
    } catch (e) {
      console.warn("Failed to fetch henchmen:", e);
    }
  },

  _buildHenchmanSheet(sheet) {
    const frag = document.createDocumentFragment();

    // Header: name + level
    const header = document.createElement("div");
    header.className = "henchman-header";
    const nameEl = document.createElement("div");
    nameEl.className = "henchman-name";
    nameEl.textContent = sheet.name || `Henchman #${sheet.id}`;
    const lvlEl = document.createElement("div");
    lvlEl.className = "henchman-sub";
    lvlEl.textContent = `Level ${sheet.level}`
      + `  ·  XP ${sheet.xp}/${sheet.xp_to_next}`;
    header.appendChild(nameEl);
    header.appendChild(lvlEl);
    frag.appendChild(header);

    // Vitals
    frag.appendChild(this._sectionHeader("Vitals"));
    const hp = sheet.hp != null
      ? `${sheet.hp}/${sheet.max_hp}` : "—";
    frag.appendChild(this._infoRow("HP", hp));

    // Stats grid
    if (sheet.stats) {
      frag.appendChild(this._sectionHeader("Abilities"));
      const grid = document.createElement("div");
      grid.className = "henchman-stats-grid";
      const order = [
        ["STR", "strength"], ["DEX", "dexterity"],
        ["CON", "constitution"], ["INT", "intelligence"],
        ["WIS", "wisdom"], ["CHA", "charisma"],
      ];
      for (const [label, key] of order) {
        const cell = document.createElement("div");
        cell.className = "henchman-stat";
        const lbl = document.createElement("span");
        lbl.className = "stat-label";
        lbl.textContent = label;
        const val = document.createElement("span");
        val.className = "stat-value";
        const v = sheet.stats[key];
        val.textContent = (v >= 0 ? `+${v}` : `${v}`);
        cell.appendChild(lbl);
        cell.appendChild(val);
        grid.appendChild(cell);
      }
      frag.appendChild(grid);
    }

    // Equipment
    frag.appendChild(this._sectionHeader("Equipment"));
    const eq = sheet.equipment || {};
    const slots = [
      ["weapon", "Weapon"], ["armor", "Armor"],
      ["shield", "Shield"], ["helmet", "Helmet"],
      ["ring_left", "Ring L"], ["ring_right", "Ring R"],
    ];
    for (const [key, label] of slots) {
      frag.appendChild(this._infoRow(label, this._itemLabel(eq[key])));
    }

    // Inventory
    const inv = sheet.inventory || [];
    const maxSlots = sheet.inventory_max_slots;
    const invHeader = `Inventory (${inv.length}`
      + (maxSlots != null ? `/${maxSlots}` : "") + ")";
    frag.appendChild(this._sectionHeader(invHeader));
    if (inv.length === 0) {
      const empty = document.createElement("div");
      empty.className = "henchman-empty";
      empty.textContent = "(empty)";
      frag.appendChild(empty);
    } else {
      const list = document.createElement("ul");
      list.className = "henchman-inventory";
      for (const item of inv) {
        const li = document.createElement("li");
        li.textContent = this._itemLabel(item);
        list.appendChild(li);
      }
      frag.appendChild(list);
    }

    return frag;
  },

  _itemLabel(item) {
    if (!item) return "—";
    let label = item.name || `#${item.id}`;
    const extras = [];
    if (item.damage) extras.push(item.damage);
    if (item.defense) extras.push(`AC ${item.defense}`);
    if (item.magic_bonus) extras.push(`+${item.magic_bonus}`);
    if (item.charges != null && item.max_charges != null) {
      extras.push(`${item.charges}/${item.max_charges}`);
    }
    if (item.effect) extras.push(item.effect);
    if (extras.length) label += `  (${extras.join(", ")})`;
    return label;
  },

  // ── Export tab ───────────────────────────────────────────────

  _buildExportTab() {
    const frag = document.createDocumentFragment();
    const header = this._sectionHeader("Export Data");
    frag.appendChild(header);

    const exports = [
      { label: "Game State", endpoint: "export/game_state" },
      { label: "Layer State", endpoint: "export/layer_state" },
      { label: "Map SVG", endpoint: "export/map_svg" },
    ];

    exports.forEach(({ label, endpoint }) => {
      frag.appendChild(this._exportButton(label, endpoint));
    });

    // Export All button
    const allBtn = document.createElement("button");
    allBtn.className = "debug-export-btn";
    allBtn.textContent = "Export All";
    allBtn.style.marginTop = "8px";
    allBtn.style.borderColor = "#e6c07b";
    allBtn.style.color = "#e6c07b";
    allBtn.addEventListener("click", async () => {
      allBtn.disabled = true;
      allBtn.textContent = "Exporting...";
      const sid = NHC.sessionId;
      const paths = [];
      for (const { endpoint } of exports) {
        try {
          const r = await fetch(
            `/api/game/${sid}/${endpoint}`, { method: "POST" });
          const d = await r.json();
          if (d.path) paths.push(d.path);
        } catch (e) {
          console.warn("Export failed:", endpoint, e);
        }
      }
      allBtn.disabled = false;
      allBtn.textContent = `Exported ${paths.length} files`;
      setTimeout(() => { allBtn.textContent = "Export All"; }, 3000);
    });
    frag.appendChild(allBtn);

    return frag;
  },

  _exportButton(label, endpoint) {
    const row = document.createElement("div");
    row.style.marginBottom = "4px";
    const btn = document.createElement("button");
    btn.className = "debug-export-btn";
    btn.textContent = label;
    const status = document.createElement("span");
    status.style.color = "#888";
    status.style.fontSize = "10px";
    status.style.marginLeft = "8px";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      status.textContent = "...";
      try {
        const r = await fetch(
          `/api/game/${NHC.sessionId}/${endpoint}`,
          { method: "POST" });
        const d = await r.json();
        status.textContent = d.path || "done";
      } catch (e) {
        status.textContent = "failed";
      }
      btn.disabled = false;
      setTimeout(() => { status.textContent = ""; }, 5000);
    });
    row.appendChild(btn);
    row.appendChild(status);
    return row;
  },
};
