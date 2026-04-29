/**
 * NHC Web Frontend — main entry point.
 */
const NHC = {
  sessionId: null,
  labels: {},
  waitingForFloor: false,

  init() {
    UI.init();
    // Activate god-mode debug tools from the flag embedded in the
    // HTML by the server (player registry or --god CLI flag). Done
    // before Input.init so the first toolbar build includes the
    // god-mode buttons.
    if (window.NHC_GOD_MODE) {
      DebugPanel.enabled = true;
    }
    Input.init();
    TTS.initWelcome();

    document.getElementById("new-game-btn")
      .addEventListener("click", () => this.newGame(true));

    document.getElementById("continue-btn")
      .addEventListener("click", () => this.newGame(false));

    document.getElementById("ranking-btn")
      ?.addEventListener("click", () => UI.showRanking());

    // Welcome toggle-button groups: click toggles .welcome-active
    for (const group of document.querySelectorAll(".welcome-btns")) {
      for (const btn of group.querySelectorAll(".welcome-btn")) {
        btn.addEventListener("click", () => {
          for (const sib of group.querySelectorAll(".welcome-btn")) {
            sib.classList.remove("welcome-active");
          }
          btn.classList.add("welcome-active");
        });
      }
    }

    document.getElementById("help-btn")
      ?.addEventListener("click", () => UI.showHelp());

    // Show "Continue" button if a save exists
    this.checkSave();

    // Wire up WebSocket message handlers. The per-tick entity /
    // FOV / doors payload is identical across the three tile-
    // layer views (site / structure / dungeon) -- only the
    // message *type* differs so the view-switch handlers in
    // hex_map.js can route the first frame after a view
    // transition to the right toolbar + zoom memory. See
    // design/views.md for the five-view wire protocol. The
    // state_hex / state_flower payloads are handled by their
    // own modules (hex_map.js / hex_flower.js).
    const _applyTileStateFrame = (msg) => {
      console.log("[state] entities:", msg.entities.length,
                  "doors:", (msg.doors || []).length,
                  "fov:", (msg.fov || []).length,
                  "mapW:", GameMap.mapW, "mapH:", GameMap.mapH);
      if (msg.turn !== undefined) GameMap.turn = msg.turn;
      GameMap.updateEntities(msg.entities, msg.doors, msg.dug);
      if (msg.fov || msg.fov_add || msg.fov_del) {
        GameMap.updateFOV(msg);
      }
      GameMap.flush();
      if (DebugPanel.enabled) DebugPanel.updateFovInfo();
      // Safety: a post-action state update with no preceding
      // floor message means the stair action was rejected (e.g.
      // the player wasn't standing on stairs).  Clear the overlay
      // so we don't leave it stuck.
      if (NHC.waitingForFloor) {
        NHC.waitingForFloor = false;
        NHC.hideLoading();
      }
    };
    WS.on("state_site", _applyTileStateFrame);
    WS.on("state_structure", _applyTileStateFrame);
    WS.on("state_dungeon", _applyTileStateFrame);

    WS.on("message", (msg) => {
      console.log("message:", msg.text);
      UI.addMessage(msg.text);
      TTS.enqueue(msg.text);
    });

    WS.on("narrative", (msg) => {
      UI.addNarrative(msg.chunk);
      TTS.enqueue(msg.chunk);
    });

    WS.on("effect", (msg) => {
      GameMap.playEffect(msg.effect, msg.x, msg.y);
    });

    WS.on("stats_init", (msg) => {
      UI.setStaticStats(msg);
    });

    WS.on("stats", (msg) => {
      UI.updateStatus(msg);
    });

    WS.on("floor", async (msg) => {
      console.log("[floor] msg keys:", Object.keys(msg),
                  "entities:", (msg.entities||[]).length,
                  "fov:", (msg.fov||[]).length,
                  "explored:", (msg.explored||[]).length,
                  "theme:", msg.theme,
                  "prerevealed:", msg.prerevealed,
                  "floor_url:", msg.floor_url);
      // Reset client state for the new floor
      GameMap.fov = new Set();
      GameMap.explored = new Set();
      GameMap.walls = new Map();
      GameMap.exploredWalls = new Map();
      GameMap.doorInfo = new Map();
      GameMap.allDoors = new Map();
      GameMap.dugTiles = new Map();
      GameMap.lastSeen = new Map();
      GameMap.entities = [];
      GameMap.doors = [];
      if (msg.turn !== undefined) GameMap.turn = msg.turn;
      // Store theme/feeling for future terrain canvas layer
      if (msg.theme) GameMap.theme = msg.theme;
      if (msg.feeling) GameMap.feeling = msg.feeling;
      GameMap.prerevealed = !!msg.prerevealed;
      // Load floor PNG (or SVG fallback) via HTTP. The server
      // emits the .png URL by default; on 404 (composite SVGs
      // without resvg-py installed) the client falls back to the
      // sibling .svg endpoint and the legacy inline-SVG path.
      if (msg.floor_url) {
        console.log("[floor] loading from:", msg.floor_url);
        await GameMap.setFloorURL(msg.floor_url);
        console.log("[floor] after setFloorURL: mapW=",
                    GameMap.mapW, "mapH=", GameMap.mapH,
                    "canvas=", GameMap.canvas?.width, "x",
                    GameMap.canvas?.height);
      }
      if (msg.entities) {
        GameMap.updateEntities(msg.entities, msg.doors, msg.dug);
        console.log("[floor] updateEntities done:",
                    GameMap.entities.length, "entities");
      }
      if (msg.explored) {
        GameMap.setExplored(msg.explored);
        console.log("[floor] setExplored:", msg.explored.length);
      }
      if (msg.fov) {
        GameMap.updateFOV(msg);
        console.log("[floor] updateFOV:", msg.fov.length, "tiles");
      }
      if (msg.hatch_url) {
        GameMap.loadHatchSVG(msg.hatch_url);
      }
      const mapContainer = document.getElementById("map-container");
      const hexContainer = document.getElementById("hex-container");
      const flowerContainer = document.getElementById("flower-container");
      console.log("[floor] visibility: map-container=",
                  mapContainer && !mapContainer.classList.contains("hidden"),
                  "hex-container=",
                  hexContainer && !hexContainer.classList.contains("hidden"),
                  "flower-container=",
                  flowerContainer && !flowerContainer.classList.contains("hidden"));
      console.log("[floor] map-container transform:",
                  mapContainer?.style.transform,
                  "origin:", mapContainer?.style.transformOrigin);
      if (msg.entities || msg.fov) {
        // Defer rendering to give the browser time to lay out
        // the SVG and resize canvases.
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            console.log("[floor] deferred flush: mapW=",
                        GameMap.mapW, "mapH=", GameMap.mapH,
                        "canvas=", GameMap.canvas?.width, "x",
                        GameMap.canvas?.height,
                        "fov size=", GameMap.fov?.size,
                        "entities=", GameMap.entities?.length);
            GameMap.flush();
            GameMap.scrollToPlayer();
            console.log("[floor] flush+scroll done, playerX=",
                        GameMap.playerX, "playerY=", GameMap.playerY);
          });
        });
      } else {
        console.log("[floor] NO entities/fov — skipping flush");
      }
      NHC.waitingForFloor = false;
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
      Input._enterFarlook();
    });

    WS.on("farlook_desc", (msg) => {
      UI.addMessage(msg.desc || "");
      // Single-look: exit after first description
      if (!Input.autolook) {
        Input._exitFarlook();
      }
    });

    WS.on("debug_url", (msg) => {
      if (DebugPanel.enabled && msg.url) {
        fetch(msg.url)
          .then(r => r.json())
          .then(data => DebugPanel.setDebugData(data))
          .catch(e => console.warn("Failed to load debug data:", e));
      }
    });

    // Server-triggered layer capture (for remote debug-bundle).
    WS.on("capture_layers", async () => {
      const n = await Input._captureAndUploadLayers();
      console.log(`[capture_layers] uploaded ${n} layers`);
    });
  },

  showLoading(text = "Generating dungeon...") {
    document.getElementById("loading-text").textContent = text;
    document.getElementById("loading-overlay").classList.remove("hidden");
  },

  hideLoading() {
    document.getElementById("loading-overlay").classList.add("hidden");
  },

  _getWelcomeSelection(groupId, fallback) {
    const btns = document.querySelectorAll(
      `#${groupId} .welcome-btn.welcome-active`,
    );
    if (btns.length > 0) return btns[0].dataset.value;
    return fallback;
  },

  async newGame(reset = false) {
    const lang = document.getElementById("lang-select").value;
    const tileset = document.getElementById("tileset-select").value;
    const world = this._getWelcomeSelection("world-btns", "hexcrawl");
    const difficulty = this._getWelcomeSelection("diff-btns", "medium");

    const L = NHC.labels;
    let loadingText;
    if (reset) {
      loadingText = (world === "hexcrawl")
        ? (L.loading_generate_world || "Generating world...")
        : (L.loading_generate || "Generating dungeon...");
    } else {
      loadingText = L.loading_resume || "Loading game...";
    }
    this.showLoading(loadingText);

    const resp = await fetch("/api/game/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang, tileset, reset, world, difficulty }),
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

    // Initialize TTS with the selected language
    TTS.init(lang);

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

    // Init debug panel canvases now that DOM is visible.
    if (DebugPanel.enabled) {
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
    TTS.skip();
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
