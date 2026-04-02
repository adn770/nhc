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
      if (msg.fov) GameMap.updateFOV(msg.fov);
      if (DebugPanel.enabled) DebugPanel.updateFovInfo();
    });

    WS.on("message", (msg) => {
      console.log("message:", msg.text);
      UI.addMessage(msg.text);
    });

    WS.on("narrative", (msg) => {
      UI.addNarrative(msg.chunk);
    });

    WS.on("stats", (msg) => {
      UI.updateStatus(msg);
    });

    WS.on("floor", (msg) => {
      console.log("floor msg keys:", Object.keys(msg));
      console.log("floor SVG received:", msg.svg.length, "bytes");
      console.log("hatch_url:", msg.hatch_url || "MISSING");
      GameMap.setFloorSVG(msg.svg);
      if (msg.hatch_url) {
        GameMap.loadHatchSVG(msg.hatch_url);
      } else {
        console.warn("No hatch_url in floor message!");
      }
      if (msg.entities) {
        GameMap.updateEntities(msg.entities, msg.doors);
      }
      if (msg.fov) {
        GameMap.updateFOV(msg.fov);
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

    WS.on("debug_data", (msg) => {
      if (DebugPanel.enabled) {
        DebugPanel.setDebugData(msg);
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

    // Init debug panel if god mode
    if (data.god_mode) {
      DebugPanel.enabled = true;
      DebugPanel.init();
    }

    // Connect WebSocket
    WS.connect(this.sessionId);
  },
};

document.addEventListener("DOMContentLoaded", () => NHC.init());
