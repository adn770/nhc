/**
 * NHC Web Frontend — main entry point.
 */
const NHC = {
  sessionId: null,
  labels: {},

  init() {
    UI.init();
    Input.init();

    document.getElementById("new-game-btn")
      .addEventListener("click", () => this.newGame(true));

    document.getElementById("continue-btn")
      .addEventListener("click", () => this.newGame(false));

    document.getElementById("help-btn")
      ?.addEventListener("click", () => UI.showHelp());

    // Show "Continue" button if a save exists
    this.checkSave();

    // Wire up WebSocket message handlers
    WS.on("state", (msg) => {
      console.log("state:", msg.entities.length, "entities,",
                  (msg.doors || []).length, "doors,",
                  (msg.fov || []).length, "fov tiles");
      GameMap.updateEntities(msg.entities, msg.doors);
      if (msg.fov || msg.fov_add || msg.fov_del) {
        GameMap.updateFOV(msg);
      }
      GameMap.flush();
      if (DebugPanel.enabled) DebugPanel.updateFovInfo();
    });

    WS.on("message", (msg) => {
      console.log("message:", msg.text);
      UI.addMessage(msg.text);
    });

    WS.on("narrative", (msg) => {
      UI.addNarrative(msg.chunk);
    });

    WS.on("stats_init", (msg) => {
      UI.setStaticStats(msg);
    });

    WS.on("stats", (msg) => {
      UI.updateStatus(msg);
    });

    WS.on("floor", async (msg) => {
      console.log("floor msg keys:", Object.keys(msg));
      // Reset client state for the new floor
      GameMap.fov = new Set();
      GameMap.explored = new Set();
      GameMap.walls = new Map();
      GameMap.exploredWalls = new Map();
      GameMap.doorInfo = new Map();
      GameMap.allDoors = new Map();
      GameMap.entities = [];
      GameMap.doors = [];
      // Store theme/feeling for future terrain canvas layer
      if (msg.theme) GameMap.theme = msg.theme;
      if (msg.feeling) GameMap.feeling = msg.feeling;
      // Load floor SVG via HTTP
      if (msg.floor_url) {
        const svg = await fetch(msg.floor_url).then(r => r.text());
        console.log("floor SVG loaded:", svg.length, "bytes");
        GameMap.setFloorSVG(svg);
      }
      if (msg.entities) {
        GameMap.updateEntities(msg.entities, msg.doors);
      }
      // Seed explored before loading the hatch pattern so the
      // onload handler can replay the full reveal in one pass.
      if (msg.explored) {
        GameMap.setExplored(msg.explored);
      }
      if (msg.fov) {
        GameMap.updateFOV(msg);
      }
      if (msg.hatch_url) {
        GameMap.loadHatchSVG(msg.hatch_url);
      }
      if (msg.entities || msg.fov) {
        GameMap.flush();
        // Ensure scroll happens after browser has laid out the new SVG
        requestAnimationFrame(() => GameMap.scrollToPlayer());
      }
      NHC.hideLoading();
    });

    WS.on("menu", async (msg) => {
      console.log("menu:", msg.title, msg.options.length, "options");
      const choice = await UI.showMenu(msg.title, msg.options);
      WS.send({ type: "menu_select", choice });
    });

    WS.on("game_over", (msg) => {
      UI.showGameOver(msg);
    });

    WS.on("help", () => {
      const L = NHC.labels;
      UI.addMessage(L.help_command || "--- Help: press ? for full help ---");
    });

    WS.on("shutdown", () => {
      this.returnToWelcome();
    });

    WS.on("farlook", () => {
      const L = NHC.labels;
      UI.addMessage(L.farlook_hint || "Farlook mode — click a tile to examine.");
      WS.send({ type: "action", intent: "farlook_done" });
    });

    WS.on("debug_url", (msg) => {
      if (DebugPanel.enabled && msg.url) {
        fetch(msg.url)
          .then(r => r.json())
          .then(data => DebugPanel.setDebugData(data))
          .catch(e => console.warn("Failed to load debug data:", e));
      }
    });
  },

  showLoading(text = "Generating dungeon...") {
    document.getElementById("loading-text").textContent = text;
    document.getElementById("loading-overlay").classList.remove("hidden");
  },

  hideLoading() {
    document.getElementById("loading-overlay").classList.add("hidden");
  },

  async newGame(reset = false) {
    const lang = document.getElementById("lang-select").value;
    const tileset = document.getElementById("tileset-select").value;

    const L = NHC.labels;
    this.showLoading(reset
      ? (L.loading_generate || "Generating dungeon...")
      : (L.loading_resume || "Loading game..."));

    const resp = await fetch("/api/game/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang, tileset, reset }),
    });

    if (!resp.ok) {
      this.hideLoading();
      const err = await resp.json();
      alert(err.error || "Failed to create game");
      return;
    }

    const data = await resp.json();
    this.sessionId = data.session_id;
    console.log("Game created:", data.session_id);

    // Load tileset
    await GameMap.loadTileset(tileset);

    // Clear message log from any previous game
    UI.clearLog();

    // Switch to game screen BEFORE connecting WS
    // so the canvas can get proper dimensions
    document.getElementById("login-screen").classList.add("hidden");
    document.getElementById("game-screen").classList.remove("hidden");

    // Init map now that the DOM is visible
    GameMap.init();

    // Load translated UI labels via HTTP
    fetch(`/api/game/${data.session_id}/labels.json`)
      .then(r => r.json())
      .then(labels => {
        NHC.labels = labels;
        Input.updateToolbarLabels(labels);
        UI.applyLabels(labels);
      })
      .catch(e => console.warn("Failed to load labels:", e));

    // Init debug panel if god mode
    if (data.god_mode) {
      DebugPanel.enabled = true;
      DebugPanel.init();
    }

    // Connect WebSocket
    WS.connect(this.sessionId);
  },

  async checkSave() {
    try {
      const resp = await fetch("/api/game/has_save");
      const data = await resp.json();
      const btn = document.getElementById("continue-btn");
      if (data.has_save) {
        btn.classList.remove("hidden");
      } else {
        btn.classList.add("hidden");
      }
    } catch {
      // Server not ready or no auth — hide button
    }
  },

  returnToWelcome() {
    if (WS.socket) WS.socket.close();
    // Reset client state
    GameMap.fov = new Set();
    GameMap.explored = new Set();
    GameMap.walls = new Map();
    GameMap.exploredWalls = new Map();
    GameMap.doorInfo = new Map();
    GameMap.allDoors = new Map();
    GameMap.entities = [];
    GameMap.doors = [];
    DebugPanel.visible = false;
    const panel = document.getElementById("debug-panel");
    if (panel) panel.remove();
    // Switch screens
    document.getElementById("game-screen").classList.add("hidden");
    document.getElementById("login-screen").classList.remove("hidden");
    this.sessionId = null;
    // Refresh continue button
    this.checkSave();
  },

  async restartGame() {
    const L = NHC.labels;
    const choice = await UI.showMenu(
      L.restart_confirm || "Restart game? Current progress will be lost.", [
        { id: "yes", name: L.restart_yes || "Yes, restart" },
        { id: "no",  name: L.restart_cancel || "Cancel" },
      ]);
    if (choice !== "yes") return;
    if (this.sessionId) {
      fetch(`/api/game/${this.sessionId}`, { method: "DELETE" })
        .catch(() => {});
    }
    this.returnToWelcome();
  },
};

document.addEventListener("DOMContentLoaded", () => NHC.init());
