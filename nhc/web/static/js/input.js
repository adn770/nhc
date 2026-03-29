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
  },

  init() {
    this.inputEl = document.getElementById("game-input");

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
        this.classicMode = !this.classicMode;
        if (this.classicMode) {
          this.inputEl.blur();
        } else {
          this.inputEl.focus();
        }
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
        WS.send({
          type: "action",
          intent: mapping.intent,
          data: mapping.data,
        });
      }

      // Tab to switch to typed mode
      if (e.key === "Tab") {
        e.preventDefault();
        this.classicMode = false;
        this.inputEl.focus();
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
  },
};
