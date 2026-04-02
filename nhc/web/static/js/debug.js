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
  },

  // Tab definitions — extensible
  _tabs: [
    { name: "Layers", buildFn: "_buildLayersTab" },
    { name: "Export", buildFn: "_buildExportTab" },
  ],

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
  },

  // ── Gear button ──────────────────────────────────────────────

  _createGearButton() {
    const zone = document.getElementById("toolbar-zone");
    if (!zone) return;
    if (document.getElementById("god-mode-btn")) return;
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

  // ── Panel construction ───────────────────────────────────────

  _buildPanel() {
    const panel = document.createElement("div");
    panel.id = "debug-panel";

    // Tab bar
    const tabBar = document.createElement("div");
    tabBar.className = "debug-tabs";

    const panes = [];

    this._tabs.forEach((tab, i) => {
      const tabBtn = document.createElement("button");
      tabBtn.className = "debug-tab" + (i === 0 ? " active" : "");
      tabBtn.textContent = tab.name;

      const pane = document.createElement("div");
      pane.className = "debug-tab-content"
                       + (i === 0 ? " active" : "");
      pane.appendChild(this[tab.buildFn]());
      panes.push(pane);

      tabBtn.addEventListener("click", () => {
        tabBar.querySelectorAll(".debug-tab").forEach(
          (t) => t.classList.remove("active"));
        panes.forEach((p) => p.classList.remove("active"));
        tabBtn.classList.add("active");
        pane.classList.add("active");
      });

      tabBar.appendChild(tabBtn);
    });

    panel.appendChild(tabBar);
    panes.forEach((p) => panel.appendChild(p));
    return panel;
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
