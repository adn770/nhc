/**
 * NHC Web Frontend — main entry point.
 *
 * Orchestrates login, game creation, WebSocket connection,
 * and wires up all message handlers.
 */
const NHC = {
  sessionId: null,

  init() {
    UI.init();
    GameMap.init();
    Input.init();

    document.getElementById("new-game-btn")
      .addEventListener("click", () => this.newGame());

    // Wire up WebSocket message handlers
    WS.on("state", (msg) => {
      GameMap.updateEntities(msg.entities);
      if (msg.fov) GameMap.updateFOV(msg.fov);
    });

    WS.on("message", (msg) => {
      UI.addMessage(msg.text);
    });

    WS.on("narrative", (msg) => {
      UI.addNarrative(msg.chunk);
    });

    WS.on("stats", (msg) => {
      UI.updateStatus(msg);
    });

    WS.on("floor", (msg) => {
      GameMap.setFloorSVG(msg.svg);
      GameMap.updateEntities(msg.entities || []);
      if (msg.fov) GameMap.updateFOV(msg.fov);
    });

    WS.on("menu", async (msg) => {
      const choice = await UI.showMenu(msg.title, msg.options);
      WS.send({ type: "menu_select", choice });
    });

    WS.on("game_over", (msg) => {
      UI.showGameOver(msg);
    });

    WS.on("help", () => {
      UI.addMessage("--- Help: press ? in terminal mode for full help ---");
    });

    WS.on("shutdown", () => {
      UI.addMessage("Session ended.");
    });

    WS.on("farlook", () => {
      UI.addMessage("Farlook mode — click a tile to examine.");
      // In web mode, clicking already sends coordinates
      WS.send({ type: "action", intent: "farlook_done" });
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

    // Load tileset
    await GameMap.loadTileset(tileset);

    // Switch to game screen
    document.getElementById("login-screen").classList.add("hidden");
    document.getElementById("game-screen").classList.remove("hidden");

    // Connect WebSocket
    WS.connect(this.sessionId);
  },
};

// Start when DOM is ready
document.addEventListener("DOMContentLoaded", () => NHC.init());
