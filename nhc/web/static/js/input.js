/**
 * Input handling: keyboard shortcuts + text input + click.
 */
const Input = {
  inputEl: null,
  classicMode: true,
  autodig: false,  // toggled by right-click on the dig toolbar button
  autolook: false, // toggled by right-click on the farlook toolbar button
  farlookActive: false, // true while in farlook click mode
  menuPending: null,  // resolve function for active menu

  // Same key mapping as nhc/rendering/terminal/input.py
  KEY_MAP: {
    "ArrowUp":    { intent: "move", data: [0, -1] },
    "ArrowDown":  { intent: "move", data: [0, 1] },
    "ArrowLeft":  { intent: "move", data: [-1, 0] },
    "ArrowRight": { intent: "move", data: [1, 0] },
    "h": { intent: "move", data: [-1, 0] },
    "j": { intent: "move", data: [0, 1] },
    "k": { intent: "move", data: [0, -1] },
    "l": { intent: "move", data: [1, 0] },
    "y": { intent: "move", data: [-1, -1] },
    "u": { intent: "move", data: [1, -1] },
    "b": { intent: "move", data: [-1, 1] },
    "n": { intent: "move", data: [1, 1] },
    ".": { intent: "wait", data: null },
    "5": { intent: "wait", data: null },
    "g": { intent: "pickup", data: null },
    ",": { intent: "pickup", data: null },
    "i": { intent: "inventory", data: null },
    "a": { intent: "use_item", data: null },
    "q": { intent: "quaff", data: null },
    "e": { intent: "equip", data: null },
    "d": { intent: "drop", data: null },
    "t": { intent: "throw", data: null },
    "z": { intent: "zap", data: null },
    ":": { intent: "farlook", data: null },
    "s": { intent: "search", data: null },
    "p": { intent: "pick_lock", data: null },
    "f": { intent: "force_door", data: null },
    "c": { intent: "close_door", data: null },
    "D": { intent: "dig", data: null },
    ">": { intent: "descend", data: null },
    "<": { intent: "ascend", data: null },
    "?": { intent: "help", data: null },
    "[": { intent: "scroll_up", data: null },
    "]": { intent: "scroll_down", data: null },
    "G": { intent: "give_item", data: null },
    "P": { intent: "dismiss_henchman", data: null },
    "Q": { intent: "quit", data: null },
    "M": { intent: "reveal_map", data: null },
  },

  // Dungeon-mode toolbar actions (the full set).
  DUNGEON_TOOLBAR: [
    { icon: "👆", intent: "pickup",     labelKey: "toolbar_pickup" },
    { icon: "🎒", intent: "inventory",  labelKey: "toolbar_inventory" },
    { icon: "🧪", intent: "quaff",      labelKey: "toolbar_quaff" },
    { icon: "📜", intent: "use_item",   labelKey: "toolbar_use_item" },
    { icon: "⚔️", intent: "equip",      labelKey: "toolbar_equip" },
    { icon: "🗑️", intent: "drop",       labelKey: "toolbar_drop" },
    { icon: "🏹", intent: "throw",      labelKey: "toolbar_throw" },
    { icon: "✨", intent: "zap",        labelKey: "toolbar_zap" },
    { icon: "🔍", intent: "search",     labelKey: "toolbar_search" },
    { icon: "⏳", intent: "wait",       labelKey: "toolbar_wait" },
    { icon: "🔓", intent: "pick_lock",  labelKey: "toolbar_pick_lock" },
    { icon: "💪", intent: "force_door", labelKey: "toolbar_force_door" },
    { icon: "🚪", intent: "close_door", labelKey: "toolbar_close_door" },
    { icon: "⛏️", intent: "dig",        labelKey: "toolbar_dig" },
    { icon: "👁️", intent: "farlook",    labelKey: "toolbar_farlook" },
    { icon: "⬇️", intent: "descend",    labelKey: "toolbar_descend" },
    { icon: "⬆️", intent: "ascend",     labelKey: "toolbar_ascend" },
  ],

  // Hex overland toolbar — compact set relevant to the overland.
  // Inventory actions still useful (the player carries gear);
  // dungeon-specific actions (locks, doors, dig, stairs) dropped.
  HEX_TOOLBAR: [
    { icon: "🔍", intent: "hex_explore", labelKey: "toolbar_hex_explore" },
    { icon: "🏕", intent: "hex_rest",    labelKey: "toolbar_hex_rest" },
    { icon: "🎒", intent: "inventory",  labelKey: "toolbar_inventory" },
    { icon: "🧪", intent: "quaff",      labelKey: "toolbar_quaff" },
    { icon: "📜", intent: "use_item",   labelKey: "toolbar_use_item" },
    { icon: "⚔️", intent: "equip",      labelKey: "toolbar_equip" },
  ],

  // Flower exploration toolbar.
  FLOWER_TOOLBAR: [
    { icon: "🏠", intent: "hex_enter",    labelKey: "toolbar_flower_enter" },
    { icon: "🔍", intent: "flower_search", labelKey: "toolbar_flower_search" },
    { icon: "🌿", intent: "flower_forage", labelKey: "toolbar_flower_forage" },
    { icon: "🏕", intent: "flower_rest",   labelKey: "toolbar_flower_rest" },
    { icon: "🗺️", intent: "flower_exit",   labelKey: "toolbar_flower_exit" },
    { icon: "🎒", intent: "inventory",     labelKey: "toolbar_inventory" },
  ],

  // Which toolbar is currently rendered.
  _currentToolbarMode: "dungeon",

  // Alias for backward compat (debug.js etc. reads this).
  get TOOLBAR_ACTIONS() {
    if (this._currentToolbarMode === "hex") return this.HEX_TOOLBAR;
    if (this._currentToolbarMode === "flower") return this.FLOWER_TOOLBAR;
    return this.DUNGEON_TOOLBAR;
  },

  init() {
    this.inputEl = document.getElementById("game-input");
    this._initToolbar();

    // Text input: Enter submits
    this.inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const text = this.inputEl.value.trim();
        if (text) {
          WS.send({ type: "typed", text });
          this.inputEl.value = "";
        }
      }
      if (e.key === "Tab") {
        e.preventDefault();
        e.stopPropagation();
        this._switchToClassic();
      }
    });

    // Global keyboard: classic mode shortcuts
    document.addEventListener("keydown", (e) => {
      // Skip if typing in input field
      if (document.activeElement === this.inputEl) return;
      // Skip if menu is open
      if (document.getElementById("menu-overlay")) return;

      // Escape exits farlook mode
      if (this.farlookActive && e.key === "Escape") {
        e.preventDefault();
        this._exitFarlook();
        return;
      }

      const mapping = this.KEY_MAP[e.key];
      if (mapping) {
        e.preventDefault();
        if (mapping.intent === "inventory") {
          UI.showInventoryPanel();
        } else if (mapping.intent === "help") {
          UI.showHelp();
        } else {
          const sent = Input._maybeAutodig(mapping);
          if (!sent) {
            Input._beforeSendAction(mapping.intent);
            WS.send({
              type: "action",
              intent: mapping.intent,
              data: mapping.data,
            });
          }
        }
      }

      // Tab to switch to typed mode
      if (e.key === "Tab") {
        e.preventDefault();
        this._switchToTyped();
      }
    });

    // Map click handling
    const mapZone = document.getElementById("map-zone");
    mapZone.addEventListener("click", (e) => {
      const container = document.getElementById("map-container");
      const rect = container.getBoundingClientRect();
      const canvas = GameMap.screenToCanvas(
        e.clientX - rect.left, e.clientY - rect.top,
      );
      const grid = GameMap.pixelToGrid(canvas.x, canvas.y);
      if (this.farlookActive) {
        WS.send({ type: "farlook_click", x: grid.x, y: grid.y });
      } else {
        WS.send({ type: "click", x: grid.x, y: grid.y });
      }
    });

    this._updateModeIndicator();
  },

  setToolbarMode(mode) {
    if (mode === this._currentToolbarMode) return;
    this._currentToolbarMode = mode;
    this._initToolbar();
    // Re-apply translated tooltips to the rebuilt buttons.
    const labels = (typeof NHC !== "undefined" && NHC.labels) || {};
    this.updateToolbarLabels(labels);
    // Update debug panel tab visibility for the new mode.
    if (typeof DebugPanel !== "undefined" && DebugPanel.enabled) {
      DebugPanel.setMode(mode);
    }
  },

  _initToolbar() {
    const zone = document.getElementById("toolbar-zone");
    if (!zone) return;
    zone.innerHTML = "";
    this._toolbarButtons = [];
    const actions = this._currentToolbarMode === "hex"
      ? this.HEX_TOOLBAR
      : this._currentToolbarMode === "flower"
        ? this.FLOWER_TOOLBAR
        : this.DUNGEON_TOOLBAR;

    // ── Action buttons (mode-specific) ──
    actions.forEach(({ icon, intent, labelKey }) => {
      const btn = document.createElement("button");
      btn.textContent = icon;
      btn.dataset.labelKey = labelKey;
      btn.dataset.intent = intent;
      btn.title = labelKey;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (intent === "inventory") {
          UI.showInventoryPanel();
        } else {
          Input._beforeSendAction(intent);
          WS.send({ type: "action", intent, data: null });
        }
      });
      if (intent === "dig") {
        btn.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          Input._toggleAutodig();
        });
      }
      if (intent === "farlook") {
        btn.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          Input._toggleAutolook();
        });
      }
      zone.appendChild(btn);
      this._toolbarButtons.push(btn);
    });

    // ── Right-aligned utility group ──
    // margin-left:auto on zoom-out (via CSS) pushes the rest right.

    // Zoom
    const zoomOut = this._toolbarBtn(
      "\u2212", "zoom-out-btn", "toolbar_zoom_out", "Zoom Out",
      () => { GameMap.zoom(-1); this._updateZoomLabel(); },
    );
    zone.appendChild(zoomOut);

    const zoomLabel = document.createElement("span");
    zoomLabel.id = "zoom-label";
    zoomLabel.className = "zoom-label";
    zoomLabel.textContent = "1.0x";
    zone.appendChild(zoomLabel);

    const zoomIn = this._toolbarBtn(
      "+", "zoom-in-btn", "toolbar_zoom_in", "Zoom In",
      () => { GameMap.zoom(1); this._updateZoomLabel(); },
    );
    zone.appendChild(zoomIn);

    // TTS toggle (hidden until TTS.init checks availability)
    const ttsBtn = this._toolbarBtn(
      "\u{1F507}", "tts-btn", null, "Text to Speech",
      () => TTS.toggle(),
    );
    ttsBtn.classList.add("hidden");
    zone.appendChild(ttsBtn);

    // TTS volume slider (hidden until TTS enabled)
    const ttsVol = document.createElement("input");
    ttsVol.id = "tts-volume";
    ttsVol.type = "range";
    ttsVol.min = "0";
    ttsVol.max = "100";
    ttsVol.value = "80";
    ttsVol.title = "TTS Volume";
    ttsVol.classList.add("tts-volume", "hidden");
    ttsVol.addEventListener("input", (e) => {
      TTS.setVolume(parseInt(e.target.value, 10) / 100);
    });
    zone.appendChild(ttsVol);

    // Restart
    const restart = this._toolbarBtn(
      "\u{1F504}", "restart-btn", "toolbar_restart",
      "Restart Game", () => NHC.restartGame(),
    );
    zone.appendChild(restart);

    // God mode — only created when DebugPanel.enabled is set
    // (from window.NHC_GOD_MODE, embedded in the HTML by the
    // server before any JS runs).
    if (typeof DebugPanel !== "undefined" && DebugPanel.enabled) {
      const dlBtn = this._toolbarBtn(
        "\uD83D\uDCBE", "debug-bundle-btn", null,
        "Download Debug Bundle (incl. layer PNGs)",
        () => this._downloadDebugBundle(),
      );
      zone.appendChild(dlBtn);

      const gearBtn = this._toolbarBtn(
        "\u2699", "god-mode-btn", null,
        "Debug Panel (God Mode)",
        () => DebugPanel._togglePanel(),
      );
      zone.appendChild(gearBtn);
    }
  },

  /** Create a toolbar button with consistent styling. */
  _toolbarBtn(icon, id, labelKey, title, onClick) {
    const btn = document.createElement("button");
    btn.textContent = icon;
    if (id) btn.id = id;
    if (labelKey) btn.dataset.labelKey = labelKey;
    btn.title = title;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      onClick();
    });
    this._toolbarButtons.push(btn);
    return btn;
  },

  _updateZoomLabel() {
    const el = document.getElementById("zoom-label");
    if (!el || typeof GameMap === "undefined") return;
    const scale = GameMap._zoomSteps[GameMap._zoomLevel] || 1;
    el.textContent = `${scale.toFixed(scale % 1 ? 2 : 1)}x`;
  },

  /** Capture all canvas layers as PNGs and upload to the server.
   * Returns the number of layers captured. */
  async _captureAndUploadLayers() {
    const sid = NHC.sessionId;
    if (!sid) return 0;
    const canvases = [
      { name: "floor_svg",     el: "#floor-svg svg",      svg: true },
      { name: "door_canvas",   el: "#door-canvas" },
      { name: "hatch_canvas",  el: "#hatch-canvas" },
      { name: "fog_canvas",    el: "#fog-canvas" },
      { name: "entity_canvas", el: "#entity-canvas" },
      { name: "debug_canvas",  el: "#debug-canvas" },
      { name: "hex_base",      el: "#hex-base-canvas" },
      { name: "hex_feature",   el: "#hex-feature-canvas" },
      { name: "hex_fog",       el: "#hex-fog-canvas" },
      { name: "hex_entity",    el: "#hex-entity-canvas" },
      { name: "hex_debug",     el: "#hex-debug-canvas" },
      { name: "flower_base",    el: "#flower-base-canvas" },
      { name: "flower_feature", el: "#flower-feature-canvas" },
      { name: "flower_fog",     el: "#flower-fog-canvas" },
      { name: "flower_entity",  el: "#flower-entity-canvas" },
      { name: "flower_debug",   el: "#flower-debug-canvas" },
    ];
    const layers = {};
    for (const {name, el, svg} of canvases) {
      const target = document.querySelector(el);
      if (!target) continue;
      try {
        if (svg) {
          const s = new XMLSerializer().serializeToString(target);
          const blob = new Blob([s], {type: "image/svg+xml"});
          const url = URL.createObjectURL(blob);
          const img = await new Promise((resolve, reject) => {
            const i = new Image();
            i.onload = () => resolve(i);
            i.onerror = reject;
            i.src = url;
          });
          const c = document.createElement("canvas");
          c.width = img.naturalWidth;
          c.height = img.naturalHeight;
          c.getContext("2d").drawImage(img, 0, 0);
          URL.revokeObjectURL(url);
          layers[name] = c.toDataURL("image/png");
        } else {
          if (!target.width || !target.height) continue;
          // Export at CSS display size (not internal hi-res).
          const dw = target.clientWidth || target.width;
          const dh = target.clientHeight || target.height;
          if (dw === target.width && dh === target.height) {
            layers[name] = target.toDataURL("image/png");
          } else {
            const tmp = document.createElement("canvas");
            tmp.width = dw;
            tmp.height = dh;
            tmp.getContext("2d").drawImage(target, 0, 0, dw, dh);
            layers[name] = tmp.toDataURL("image/png");
          }
        }
      } catch (e) {
        console.warn("Layer capture failed:", name, e);
      }
    }
    // Composite view: stack visible layers in z-order to produce
    // a single PNG matching what the player sees. Layers hidden
    // via the debug panel are excluded.
    try {
      const isVisible = (id) => {
        const el = document.getElementById(id);
        return el && !el.classList.contains("hidden");
      };
      const flowerActive = isVisible("flower-container");
      const hexActive = !flowerActive && isVisible("hex-container");
      // Layer selectors in z-order, matching the CSS stacking.
      let layerDefs;
      let refSel;
      if (flowerActive) {
        layerDefs = [
          {sel: "#flower-base-canvas"},
          {sel: "#flower-feature-canvas"},
          {sel: "#flower-fog-canvas"},
          {sel: "#flower-entity-canvas"},
          {sel: "#flower-debug-canvas"},
        ];
        refSel = "#flower-base-canvas";
      } else if (hexActive) {
        layerDefs = [
          {sel: "#hex-base-canvas"},
          {sel: "#hex-feature-canvas"},
          {sel: "#hex-fog-canvas"},
          {sel: "#hex-entity-canvas"},
          {sel: "#hex-debug-canvas"},
        ];
        refSel = "#hex-base-canvas";
      } else {
        layerDefs = [
          {sel: "#floor-svg svg", svg: true},
          {sel: "#door-canvas"},
          {sel: "#hatch-canvas"},
          {sel: "#fog-canvas"},
          {sel: "#entity-canvas"},
          {sel: "#debug-canvas"},
        ];
        refSel = "#entity-canvas";
      }
      const ref = document.querySelector(refSel);
      if (ref && ref.width && ref.height) {
        const dw = ref.clientWidth || ref.width;
        const dh = ref.clientHeight || ref.height;
        const comp = document.createElement("canvas");
        comp.width = dw;
        comp.height = dh;
        const cctx = comp.getContext("2d");
        for (const {sel, svg} of layerDefs) {
          const src = document.querySelector(sel);
          if (!src) continue;
          // Skip layers hidden by the debug panel.
          if (src.style.display === "none") continue;
          // Also check the parent for floor-svg visibility.
          if (src.parentElement
              && src.parentElement.style.display === "none") continue;
          if (svg) {
            const s = new XMLSerializer().serializeToString(src);
            const blob = new Blob([s], {type: "image/svg+xml"});
            const url = URL.createObjectURL(blob);
            const img = await new Promise((resolve, reject) => {
              const i = new Image();
              i.onload = () => resolve(i);
              i.onerror = reject;
              i.src = url;
            });
            cctx.drawImage(img, 0, 0, dw, dh);
            URL.revokeObjectURL(url);
          } else if (src.width && src.height) {
            cctx.drawImage(src, 0, 0, dw, dh);
          }
        }
        layers["composite"] = comp.toDataURL("image/png");
      }
    } catch (e) {
      console.warn("Composite capture failed:", e);
    }

    // Include console log buffer.
    const consoleLog = (window._consoleBuf || []).join("\n");
    try {
      await fetch(`/api/game/${sid}/export/layer_pngs`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({layers, console_log: consoleLog}),
      });
    } catch (e) {
      console.warn("Layer PNG upload failed:", e);
    }
    return Object.keys(layers).length;
  },

  /** Capture layers + download the debug bundle. */
  async _downloadDebugBundle() {
    const sid = NHC.sessionId;
    if (!sid) return;
    const btn = document.getElementById("debug-bundle-btn");
    if (btn) { btn.disabled = true; btn.textContent = "\u231B"; }
    await this._captureAndUploadLayers();
    window.location.href = `/api/game/${sid}/export/bundle`;
    if (btn) {
      btn.disabled = false;
      btn.textContent = "\uD83D\uDCBE";
    }
  },

  /**
   * Update toolbar tooltips with translated labels from server.
   */
  updateToolbarLabels(labels) {
    if (!this._toolbarButtons) return;
    for (const btn of this._toolbarButtons) {
      const key = btn.dataset.labelKey;
      if (key && labels[key]) {
        btn.title = labels[key];
      }
    }
  },

  _switchToClassic() {
    this.classicMode = true;
    this.inputEl.blur();
    WS.send({ type: "action", intent: "toggle_mode", data: null });
    this._updateModeIndicator();
  },

  _switchToTyped() {
    this.classicMode = false;
    this.inputEl.focus();
    WS.send({ type: "action", intent: "toggle_mode", data: null });
    this._updateModeIndicator();
  },

  _updateModeIndicator() {
    const label = document.getElementById("mode-label");
    if (label) {
      const L = NHC.labels || {};
      label.textContent = this.classicMode
        ? (L.mode_classic_tag || "[classic]")
        : (L.mode_typed_tag || "[typed]");
    }
  },

  /**
   * Hook called for every outgoing action intent before it is sent
   * over the WebSocket.  Used to surface the shared loading overlay
   * during stair transitions so players get feedback while the
   * server (re)generates the next floor.  The overlay is cleared
   * by the "floor" WS handler on success, or by the stats/state
   * handlers if the transition never happened (invalid action).
   */
  _beforeSendAction(intent) {
    if (intent === "descend" || intent === "ascend") {
      const L = NHC.labels || {};
      const text = intent === "descend"
        ? (L.loading_descend || "Descending...")
        : (L.loading_ascend || "Climbing...");
      NHC.waitingForFloor = true;
      NHC.showLoading(text);
    }
  },

  /**
   * When autodig is on and the player moves toward a non-walkable
   * adjacent tile, swap the move intent for a directed dig so the
   * server tunnels through that exact tile.  Returns true if an
   * autodig action was sent (the caller should then skip the
   * normal move dispatch).
   */
  _maybeAutodig(mapping) {
    if (!this.autodig) return false;
    if (mapping.intent !== "move") return false;
    const d = mapping.data;
    if (!Array.isArray(d) || d.length !== 2) return false;
    // Only handle cardinal tunnelling — diagonals would require
    // digging two walls in one action which isn't supported.
    const [dx, dy] = d;
    if (dx !== 0 && dy !== 0) return false;
    // Bail out if we don't have a populated walk map yet — the
    // first frame after (re)connect may be empty and we must not
    // misread that as "everything is a wall".
    if (!GameMap.walls || GameMap.walls.size === 0) return false;
    const tx = GameMap.playerX + dx;
    const ty = GameMap.playerY + dy;
    // Walkable tiles are tracked in GameMap.walls; anything
    // absent is wall, void, or off-map — all valid dig targets
    // from the client's perspective.  The server still validates.
    if (GameMap.walls.has(`${tx},${ty}`)) return false;
    // Don't autodig through known doors — let the move turn into a
    // bump-open (or unlock prompt for locked doors).  Secret doors
    // aren't in doorInfo yet, so they remain valid dig targets.
    if (GameMap.doorInfo && GameMap.doorInfo.has(`${tx},${ty}`)) {
      return false;
    }
    WS.send({ type: "action", intent: "dig", data: [dx, dy] });
    return true;
  },

  _toggleAutodig() {
    this.autodig = !this.autodig;
    const btn = (this._toolbarButtons || []).find(
      (b) => b.dataset.intent === "dig",
    );
    if (btn) {
      btn.classList.toggle("autodig-active", this.autodig);
      // Drop keyboard focus so the browser's default focus ring
      // doesn't linger on the button — it looks like a residual
      // glow once the autodig pulse class is removed.
      btn.blur();
    }
    const L = NHC.labels || {};
    UI.addMessage(this.autodig
      ? (L.autodig_on || "Autodig: ON")
      : (L.autodig_off || "Autodig: OFF"));
  },

  _toggleAutolook() {
    this.autolook = !this.autolook;
    const btn = (this._toolbarButtons || []).find(
      (b) => b.dataset.intent === "farlook",
    );
    if (btn) {
      btn.classList.toggle("autolook-active", this.autolook);
      btn.blur();
    }
    const L = NHC.labels || {};
    UI.addMessage(this.autolook
      ? (L.autolook_on || "Autolook: ON")
      : (L.autolook_off || "Autolook: OFF"));
  },

  _enterFarlook() {
    this.farlookActive = true;
  },

  _exitFarlook() {
    this.farlookActive = false;
    WS.send({ type: "action", intent: "farlook_done" });
  },
};
