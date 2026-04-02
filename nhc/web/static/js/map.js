/**
 * Map rendering: floor SVG + hatch mask + fog-of-war + entity overlay.
 *
 * Four layers stacked:
 * 1. Floor SVG (static dungeon geometry)
 * 2. Hatch canvas (masks unexplored tiles to hide SVG bleed)
 * 3. Fog canvas (dark overlay on non-visible tiles)
 * 4. Entity canvas (player, creatures, items on top)
 *
 * The map viewport auto-scrolls to keep the player centered.
 */
const GameMap = {
  canvas: null,
  fogCanvas: null,
  hatchCanvas: null,
  ctx: null,
  fogCtx: null,
  hatchCtx: null,
  cellSize: 32,  // must match SVG CELL constant
  padding: 32,   // must match SVG PADDING constant
  entities: [],
  doors: [],
  fov: new Set(),
  explored: new Set(),
  tileset: null,
  tilesetImg: null,
  mapW: 0,
  mapH: 0,
  playerX: 0,
  playerY: 0,

  init() {
    this.canvas = document.getElementById("entity-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.fogCanvas = document.getElementById("fog-canvas");
    this.fogCtx = this.fogCanvas.getContext("2d");
    this.hatchCanvas = document.getElementById("hatch-canvas");
    this.hatchCtx = this.hatchCanvas.getContext("2d");
    console.log("GameMap.init(): canvas=", this.canvas,
                "fog=", this.fogCanvas, "hatch=", this.hatchCanvas);
    this.initTooltip();
  },

  setFloorSVG(svgString) {
    const container = document.getElementById("floor-svg");
    container.innerHTML = svgString;
    const svg = container.querySelector("svg");
    if (svg) {
      const w = parseInt(svg.getAttribute("width"));
      const h = parseInt(svg.getAttribute("height"));
      this.canvas.width = w;
      this.canvas.height = h;
      if (this.fogCanvas) {
        this.fogCanvas.width = w;
        this.fogCanvas.height = h;
      }
      if (this.hatchCanvas) {
        this.hatchCanvas.width = w;
        this.hatchCanvas.height = h;
      }
      const debugCanvas = document.getElementById("debug-canvas");
      if (debugCanvas) {
        debugCanvas.width = w;
        debugCanvas.height = h;
      }
      this.mapW = w;
      this.mapH = h;
      console.log("Floor SVG set:", w, "x", h,
                   "canvas:", this.canvas.width, this.canvas.height,
                   "fog:", this.fogCanvas?.width, this.fogCanvas?.height);
    } else {
      console.warn("No <svg> found in floor SVG string");
    }
  },

  loadTileset(name) {
    return fetch(`/static/tilesets/${name}/manifest.json`)
      .then(r => r.json())
      .then(manifest => {
        this.tileset = manifest;
        if (manifest.type === "image" && manifest.image) {
          this.tilesetImg = new Image();
          this.tilesetImg.src =
            `/static/tilesets/${name}/${manifest.image}`;
          return new Promise(resolve => {
            this.tilesetImg.onload = resolve;
          });
        }
        this.tilesetImg = null;
      })
      .catch(() => {
        this.tileset = null;
        this.tilesetImg = null;
      });
  },

  updateEntities(entities, doors) {
    this.entities = entities;
    if (doors) this.doors = doors;
    // Track player position for auto-scroll
    const player = entities.find(e => e.glyph === "@");
    if (player) {
      this.playerX = player.x;
      this.playerY = player.y;
    }
    this.draw();
    this.scrollToPlayer();
  },

  updateFOV(fovList) {
    this.fov = new Set(fovList.map(([x, y]) => `${x},${y}`));
    for (const key of this.fov) {
      this.explored.add(key);
    }
    this.drawHatch();
    this.drawFog();
    this.draw();
  },

  /**
   * Scroll the map viewport to center on the player.
   */
  scrollToPlayer() {
    const zone = document.getElementById("map-zone");
    if (!zone) return;

    const px = this.playerX * this.cellSize + this.padding
               + this.cellSize / 2;
    const py = this.playerY * this.cellSize + this.padding
               + this.cellSize / 2;

    const targetLeft = px - zone.clientWidth / 2;
    const targetTop = py - zone.clientHeight / 2;

    zone.scrollTo({
      left: Math.max(0, targetLeft),
      top: Math.max(0, targetTop),
      behavior: "smooth",
    });
  },

  _resolveColor(colorName) {
    if (this.tileset && this.tileset.colors) {
      return this.tileset.colors[colorName] || colorName;
    }
    return colorName || "#FFFFFF";
  },

  /**
   * Load a small hatching SVG patch, create a repeating pattern,
   * and fill the full hatch canvas with it.
   */
  loadHatchSVG(url) {
    console.log("loadHatchSVG:", url, "ctx=", !!this.hatchCtx);
    if (!this.hatchCtx || !url) {
      console.warn("loadHatchSVG SKIPPED: no ctx or url");
      return;
    }
    const img = new Image();
    img.onload = () => {
      console.log("Hatch patch loaded:", img.width, "x", img.height);
      // Render SVG patch to an offscreen canvas
      const patch = document.createElement("canvas");
      patch.width = img.width;
      patch.height = img.height;
      const pctx = patch.getContext("2d");
      pctx.drawImage(img, 0, 0);
      // Create repeating pattern and fill the hatch canvas
      const pattern = this.hatchCtx.createPattern(patch, "repeat");
      this.hatchCtx.fillStyle = pattern;
      this.hatchCtx.fillRect(
        0, 0, this.hatchCanvas.width, this.hatchCanvas.height);
      // Verify something was drawn
      const sample = this.hatchCtx.getImageData(
        this.padding + 16, this.padding + 16, 1, 1).data;
      console.log("Hatch sample pixel:",
                  `rgba(${sample[0]},${sample[1]},${sample[2]},${sample[3]})`);
      // Re-clear already explored tiles
      this.drawHatch();
      console.log("Hatch stamped, cleared", this.explored.size,
                  "explored tiles");
    };
    img.onerror = (e) => {
      console.error("Hatch patch FAILED to load:", e);
    };
    img.src = url;
  },

  /**
   * Clear explored tiles from the hatch canvas.
   * Called whenever FOV updates to reveal new tiles.
   */
  drawHatch() {
    const ctx = this.hatchCtx;
    if (!ctx) return;
    const expand = this.cellSize * 0.1;
    console.log("drawHatch:", this.explored.size, "explored tiles,",
                "canvas:", this.hatchCanvas.width, "x",
                this.hatchCanvas.height);
    for (const key of this.explored) {
      const [x, y] = key.split(",").map(Number);
      const px = x * this.cellSize + this.padding - expand;
      const py = y * this.cellSize + this.padding - expand;
      ctx.clearRect(px, py,
                    this.cellSize + 2 * expand,
                    this.cellSize + 2 * expand);
    }
  },

  drawFog() {
    const ctx = this.fogCtx;
    if (!ctx || !this.mapW || !this.mapH) {
      console.warn("drawFog skipped: ctx=", !!ctx,
                    "mapW=", this.mapW, "mapH=", this.mapH);
      return;
    }
    console.log("drawFog:", this.fov.size, "visible,",
                this.explored.size, "explored");

    ctx.clearRect(0, 0, this.mapW, this.mapH);

    // Cover everything in fully opaque black — unexplored is hidden
    ctx.fillStyle = "rgba(0, 0, 0, 1.0)";
    ctx.fillRect(0, 0, this.mapW, this.mapH);

    // Clear visible tiles (fully transparent)
    for (const key of this.fov) {
      const [x, y] = key.split(",").map(Number);
      const px = x * this.cellSize + this.padding;
      const py = y * this.cellSize + this.padding;
      ctx.clearRect(px, py, this.cellSize, this.cellSize);
    }

    // Explored but not visible: clear then apply heavy dim
    for (const key of this.explored) {
      if (this.fov.has(key)) continue;
      const [x, y] = key.split(",").map(Number);
      const px = x * this.cellSize + this.padding;
      const py = y * this.cellSize + this.padding;
      ctx.clearRect(px, py, this.cellSize, this.cellSize);
      ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
      ctx.fillRect(px, py, this.cellSize, this.cellSize);
    }
  },

  draw() {
    const ctx = this.ctx;
    if (!this.canvas.width || !this.canvas.height) {
      console.warn("draw skipped: zero canvas size");
      return;
    }
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    // Draw doors first (behind entities)
    this._drawDoors(ctx);
    console.log("draw:", this.entities.length, "entities,",
                this.doors.length, "doors");

    for (const ent of this.entities) {
      const px = ent.x * this.cellSize + this.padding;
      const py = ent.y * this.cellSize + this.padding;

      // Image-type tileset: draw from sprite sheet
      if (this.tileset && this.tileset.type === "image"
          && this.tilesetImg) {
        const sprite = this.tileset.sprites[ent.glyph];
        if (sprite && sprite.x !== undefined) {
          ctx.drawImage(
            this.tilesetImg,
            sprite.x, sprite.y,
            this.tileset.tile_size, this.tileset.tile_size,
            px, py,
            this.cellSize, this.cellSize,
          );
          continue;
        }
      }

      // Text-type tileset or fallback: draw glyph as text
      const font = (this.tileset && this.tileset.font)
        || `bold ${this.cellSize - 4}px monospace`;
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      let color = ent.color || "#FFFFFF";
      if (this.tileset && this.tileset.sprites) {
        const sprite = this.tileset.sprites[ent.glyph];
        if (sprite && sprite.color) {
          color = this._resolveColor(sprite.color);
        } else {
          color = this._resolveColor(color);
        }
      }

      const cx = px + this.cellSize / 2;
      const cy = py + this.cellSize / 2;
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#000000";
      ctx.strokeText(ent.glyph, cx, cy);
      ctx.fillStyle = color;
      ctx.fillText(ent.glyph, cx, cy);
    }
  },

  /**
   * Draw doors on the entity canvas.
   *
   * - door_secret (undiscovered): not drawn (invisible wall)
   * - door_closed / door_locked: black-filled rectangle on the wall
   *   line, 80% tile in wall direction, ~25% across passage, with
   *   small wall connection lines on each side
   * - door_open: same rectangle but white-filled
   */
  _drawDoors(ctx) {
    const cs = this.cellSize;
    const pad = this.padding;
    const wallW = 4;             // match SVG WALL_WIDTH
    const doorLen = cs * 0.8;    // 80% of tile along wall
    const doorDepth = wallW * 2; // twice wall thickness
    const connLen = cs * 0.1;    // wall connection stub

    for (const door of this.doors) {
      const px = door.x * cs + pad;
      const py = door.y * cs + pad;
      const cx = px + cs / 2;
      const cy = py + cs / 2;

      // Secret doors: draw a wall segment on the door edge
      if (door.state === "door_secret") {
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        if (door.edge === "left") {
          ctx.moveTo(px, py); ctx.lineTo(px, py + cs);
        } else if (door.edge === "right") {
          ctx.moveTo(px + cs, py); ctx.lineTo(px + cs, py + cs);
        } else if (door.edge === "top") {
          ctx.moveTo(px, py); ctx.lineTo(px + cs, py);
        } else {
          ctx.moveTo(px, py + cs); ctx.lineTo(px + cs, py + cs);
        }
        ctx.stroke();
        continue;
      }

      const fill = door.state === "door_open" ? "#FFFFFF" : "#888888";

      // Position door on the correct wall edge
      let wallX, wallY;
      if (door.edge === "left")        { wallX = px;      wallY = cy; }
      else if (door.edge === "right")  { wallX = px + cs; wallY = cy; }
      else if (door.edge === "top")    { wallX = cx;      wallY = py; }
      else /* bottom */                { wallX = cx;      wallY = py + cs; }

      if (door.vertical) {
        // Wall runs top-bottom, door is a tall narrow rect on the edge
        const dx = wallX - doorDepth / 2;
        const dy = py + (cs - doorLen) / 2;

        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(dx - 2, dy - 2, doorDepth + 4, doorLen + 4);

        ctx.fillStyle = fill;
        ctx.fillRect(dx, dy, doorDepth, doorLen);
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1;
        ctx.strokeRect(dx, dy, doorDepth, doorLen);

        // Wall stubs above and below
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(wallX, dy);
        ctx.lineTo(wallX, dy - connLen);
        ctx.moveTo(wallX, dy + doorLen);
        ctx.lineTo(wallX, dy + doorLen + connLen);
        ctx.stroke();
      } else {
        // Wall runs left-right, door is a wide short rect on the edge
        const dx = px + (cs - doorLen) / 2;
        const dy = wallY - doorDepth / 2;

        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(dx - 2, dy - 2, doorLen + 4, doorDepth + 4);

        ctx.fillStyle = fill;
        ctx.fillRect(dx, dy, doorLen, doorDepth);
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1;
        ctx.strokeRect(dx, dy, doorLen, doorDepth);

        // Wall stubs left and right
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(dx, wallY);
        ctx.lineTo(dx - connLen, wallY);
        ctx.moveTo(dx + doorLen, wallY);
        ctx.lineTo(dx + doorLen + connLen, wallY);
        ctx.stroke();
      }
    }
  },

  pixelToGrid(canvasX, canvasY) {
    const gx = Math.floor((canvasX - this.padding) / this.cellSize);
    const gy = Math.floor((canvasY - this.padding) / this.cellSize);
    return { x: gx, y: gy };
  },

  initTooltip() {
    const zone = document.getElementById("map-zone");
    if (!zone) return;
    this._tooltip = document.createElement("div");
    this._tooltip.id = "map-tooltip";
    this._tooltip.className = "hidden";
    document.body.appendChild(this._tooltip);
    this._tooltipEntity = null;

    zone.addEventListener("mousemove", (e) => {
      const container = document.getElementById("map-container");
      const rect = container.getBoundingClientRect();
      const canvasX = e.clientX - rect.left + zone.scrollLeft;
      const canvasY = e.clientY - rect.top + zone.scrollTop;
      const grid = this.pixelToGrid(canvasX, canvasY);

      const ent = this.entities.find(
        en => en.x === grid.x && en.y === grid.y && en.glyph !== "@"
      );
      if (ent && ent.name) {
        let text = ent.name;
        if (ent.hp !== undefined && ent.max_hp !== undefined) {
          text += ` (${ent.hp}/${ent.max_hp} HP)`;
        }
        this._tooltip.textContent = text;
        this._tooltip.style.left = (e.clientX + 12) + "px";
        this._tooltip.style.top = (e.clientY - 8) + "px";
        this._tooltip.classList.remove("hidden");
        this._tooltipEntity = ent.id;
      } else {
        this._tooltip.classList.add("hidden");
        this._tooltipEntity = null;
      }
    });

    zone.addEventListener("mouseleave", () => {
      this._tooltip.classList.add("hidden");
      this._tooltipEntity = null;
    });
  },
};
