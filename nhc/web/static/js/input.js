/**
 * Input handling: keyboard shortcuts + text input + click.
 */
const Input = {
  inputEl: null,
  classicMode: true,
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
    "x": { intent: "farlook", data: null },
    "s": { intent: "search", data: null },
    "p": { intent: "pick_lock", data: null },
    "f": { intent: "force_door", data: null },
    "D": { intent: "dig", data: null },
    ">": { intent: "descend", data: null },
    "<": { intent: "ascend", data: null },
    "?": { intent: "help", data: null },
    "[": { intent: "scroll_up", data: null },
    "]": { intent: "scroll_down", data: null },
    "Q": { intent: "quit", data: null },
    "M": { intent: "reveal_map", data: null },
  },

  TOOLBAR_ACTIONS: [
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
    { icon: "⛏️", intent: "dig",        labelKey: "toolbar_dig" },
    { icon: "👁️", intent: "farlook",    labelKey: "toolbar_farlook" },
    { icon: "⬇️", intent: "descend",    labelKey: "toolbar_descend" },
    { icon: "⬆️", intent: "ascend",     labelKey: "toolbar_ascend" },
  ],

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

      const mapping = this.KEY_MAP[e.key];
      if (mapping) {
        e.preventDefault();
        if (mapping.intent === "inventory") {
          UI.showInventoryPanel();
        } else if (mapping.intent === "help") {
          UI.showHelp();
        } else {
          WS.send({
            type: "action",
            intent: mapping.intent,
            data: mapping.data,
          });
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
      const canvasX = e.clientX - rect.left + mapZone.scrollLeft;
      const canvasY = e.clientY - rect.top + mapZone.scrollTop;
      const grid = GameMap.pixelToGrid(canvasX, canvasY);
      WS.send({ type: "click", x: grid.x, y: grid.y });
    });

    this._updateModeIndicator();
  },

  _initToolbar() {
    const zone = document.getElementById("toolbar-zone");
    if (!zone) return;
    zone.innerHTML = "";
    this._toolbarButtons = [];
    this.TOOLBAR_ACTIONS.forEach(({ icon, intent, labelKey }) => {
      const btn = document.createElement("button");
      btn.textContent = icon;
      btn.dataset.labelKey = labelKey;
      btn.title = labelKey;  // fallback until translations arrive
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (intent === "inventory") {
          UI.showInventoryPanel();
        } else {
          WS.send({ type: "action", intent, data: null });
        }
      });
      zone.appendChild(btn);
      this._toolbarButtons.push(btn);
    });

    // Zoom buttons
    const zoomOut = document.createElement("button");
    zoomOut.id = "zoom-out-btn";
    zoomOut.textContent = "\u2212";
    zoomOut.dataset.labelKey = "toolbar_zoom_out";
    zoomOut.title = "Zoom Out";
    zoomOut.addEventListener("click", (e) => {
      e.stopPropagation();
      GameMap.zoom(-1);
    });
    zone.appendChild(zoomOut);
    this._toolbarButtons.push(zoomOut);

    const zoomIn = document.createElement("button");
    zoomIn.id = "zoom-in-btn";
    zoomIn.textContent = "+";
    zoomIn.dataset.labelKey = "toolbar_zoom_in";
    zoomIn.title = "Zoom In";
    zoomIn.addEventListener("click", (e) => {
      e.stopPropagation();
      GameMap.zoom(1);
    });
    zone.appendChild(zoomIn);
    this._toolbarButtons.push(zoomIn);

    // Restart button — pushed to the right
    const restart = document.createElement("button");
    restart.id = "restart-btn";
    restart.textContent = "\u{1F504}";
    restart.dataset.labelKey = "toolbar_restart";
    restart.title = "Restart Game";
    restart.addEventListener("click", (e) => {
      e.stopPropagation();
      NHC.restartGame();
    });
    zone.appendChild(restart);
    this._toolbarButtons.push(restart);
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
};
