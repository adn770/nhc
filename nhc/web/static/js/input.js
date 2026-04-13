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
    { icon: "🚪", intent: "close_door", labelKey: "toolbar_close_door" },
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

  _initToolbar() {
    const zone = document.getElementById("toolbar-zone");
    if (!zone) return;
    zone.innerHTML = "";
    this._toolbarButtons = [];
    this.TOOLBAR_ACTIONS.forEach(({ icon, intent, labelKey }) => {
      const btn = document.createElement("button");
      btn.textContent = icon;
      btn.dataset.labelKey = labelKey;
      btn.dataset.intent = intent;
      btn.title = labelKey;  // fallback until translations arrive
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

    // TTS toggle button (hidden until TTS.init checks availability)
    const ttsBtn = document.createElement("button");
    ttsBtn.id = "tts-btn";
    ttsBtn.textContent = "\u{1F507}";
    ttsBtn.title = "Text to Speech";
    ttsBtn.classList.add("hidden");
    ttsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      TTS.toggle();
    });
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
