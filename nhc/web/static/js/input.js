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
    ">": { intent: "descend", data: null },
    "<": { intent: "ascend", data: null },
    "?": { intent: "help", data: null },
    "[": { intent: "scroll_up", data: null },
    "]": { intent: "scroll_down", data: null },
    "Q": { intent: "quit", data: null },
    "M": { intent: "reveal_map", data: null },
  },

  TOOLBAR_ACTIONS: [
    { icon: "👆", intent: "pickup",     label: "Pickup (g)" },
    { icon: "🎒", intent: "inventory",  label: "Inventory (i)" },
    { icon: "🧪", intent: "quaff",      label: "Quaff (q)" },
    { icon: "📜", intent: "use_item",   label: "Use Item (a)" },
    { icon: "⚔️", intent: "equip",      label: "Equip (e)" },
    { icon: "🗑️", intent: "drop",       label: "Drop (d)" },
    { icon: "🏹", intent: "throw",      label: "Throw (t)" },
    { icon: "✨", intent: "zap",        label: "Zap (z)" },
    { icon: "🔍", intent: "search",     label: "Search (s)" },
    { icon: "⏳", intent: "wait",       label: "Wait (.)" },
    { icon: "🔓", intent: "pick_lock",  label: "Pick Lock (p)" },
    { icon: "💪", intent: "force_door", label: "Force Door (f)" },
    { icon: "👁️", intent: "farlook",    label: "Farlook (x)" },
    { icon: "⬇️", intent: "descend",    label: "Descend (>)" },
    { icon: "⬆️", intent: "ascend",     label: "Ascend (<)" },
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
    this.TOOLBAR_ACTIONS.forEach(({ icon, intent, label }) => {
      const btn = document.createElement("button");
      btn.textContent = icon;
      btn.title = label;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (intent === "inventory") {
          UI.showInventoryPanel();
        } else {
          WS.send({ type: "action", intent, data: null });
        }
      });
      zone.appendChild(btn);
    });
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
      label.textContent = this.classicMode ? "[classic]" : "[typed]";
    }
  },
};
