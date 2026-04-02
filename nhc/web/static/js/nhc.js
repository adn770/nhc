/**
 * NHC Web Frontend — main entry point.
 */
const NHC = {
  sessionId: null,

  init() {
    UI.init();
    Input.init();

    document.getElementById("new-game-btn")
      .addEventListener("click", () => this.newGame());

    document.getElementById("help-btn")
      ?.addEventListener("click", () => UI.showHelp());

    // Wire up WebSocket message handlers
    WS.on("state", (msg) => {
      console.log("state:", msg.entities.length, "entities,",
                  (msg.doors || []).length, "doors,",
                  (msg.fov || []).length, "fov tiles");
      GameMap.updateEntities(msg.entities, msg.doors);
      if (msg.fov || msg.fov_add || msg.fov_del) {
        GameMap.updateFOV(msg);
      }
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
      // Load floor SVG via HTTP
      if (msg.floor_url) {
        const svg = await fetch(msg.floor_url).then(r => r.text());
        console.log("floor SVG loaded:", svg.length, "bytes");
        GameMap.setFloorSVG(svg);
      }
      if (msg.hatch_url) {
        GameMap.loadHatchSVG(msg.hatch_url);
      }
      if (msg.entities) {
        GameMap.updateEntities(msg.entities, msg.doors);
      }
      if (msg.fov) {
        GameMap.updateFOV(msg);
      }
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
      UI.addMessage("--- Help: press ? for full help ---");
    });

    WS.on("shutdown", () => {
      UI.addMessage("Session ended.");
    });

    WS.on("farlook", () => {
      UI.addMessage("Farlook mode — click a tile to examine.");
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

  async newGame() {
    const lang = document.getElementById("lang-select").value;
    const tileset = document.getElementById("tileset-select").value;

    const resp = await fetch("/api/game/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang, tileset }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      alert(err.error || "Failed to create game");
      return;
    }

    const data = await resp.json();
    this.sessionId = data.session_id;
    console.log("Game created:", data.session_id);

    // Load tileset
    await GameMap.loadTileset(tileset);

    // Switch to game screen BEFORE connecting WS
    // so the canvas can get proper dimensions
    document.getElementById("login-screen").classList.add("hidden");
    document.getElementById("game-screen").classList.remove("hidden");

    // Init map now that the DOM is visible
    GameMap.init();

    // Load translated toolbar labels via HTTP
    fetch(`/api/game/${data.session_id}/labels.json`)
      .then(r => r.json())
      .then(labels => Input.updateToolbarLabels(labels))
      .catch(e => console.warn("Failed to load labels:", e));

    // Init debug panel if god mode
    if (data.god_mode) {
      DebugPanel.enabled = true;
      DebugPanel.init();
    }

    // Connect WebSocket
    WS.connect(this.sessionId);
  },

  async restartGame() {
    const choice = await UI.showMenu(
      "Restart game? Current progress will be lost.", [
        { id: "yes", name: "Yes, restart" },
        { id: "no",  name: "Cancel" },
      ]);
    if (choice !== "yes") return;
    // Close current WS, delete session, start fresh
    if (WS.socket) WS.socket.close();
    if (this.sessionId) {
      fetch(`/api/game/${this.sessionId}`, { method: "DELETE" })
        .catch(() => {});
    }
    // Reset client state
    GameMap.fov = new Set();
    GameMap.explored = new Set();
    GameMap.hatchClear = new Set();
    GameMap.doorInfo = new Map();
    GameMap.allDoors = new Map();
    GameMap.entities = [];
    GameMap.doors = [];
    DebugPanel.visible = false;
    const panel = document.getElementById("debug-panel");
    if (panel) panel.remove();
    // Go back to login screen
    document.getElementById("game-screen").classList.add("hidden");
    document.getElementById("login-screen").classList.remove("hidden");
  },
};

document.addEventListener("DOMContentLoaded", () => NHC.init());
