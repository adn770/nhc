/**
 * Map rendering: floor SVG + entity overlay canvas + fog-of-war canvas.
 *
 * Three layers stacked:
 * 1. Floor SVG (static dungeon geometry)
 * 2. Fog canvas (dark overlay on non-visible tiles)
 * 3. Entity canvas (player, creatures, items on top)
 *
 * The map viewport auto-scrolls to keep the player centered.
 */
const GameMap = {
  canvas: null,
  fogCanvas: null,
  ctx: null,
  fogCtx: null,
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

    // Create fog canvas dynamically
    this.fogCanvas = document.getElementById("fog-canvas");
    if (!this.fogCanvas) {
      this.fogCanvas = document.createElement("canvas");
      this.fogCanvas.id = "fog-canvas";
      this.fogCanvas.style.cssText =
        "position:absolute;top:0;left:0;pointer-events:none;";
      const container = document.getElementById("map-container");
      container.insertBefore(this.fogCanvas, this.canvas);
    }
    this.fogCtx = this.fogCanvas.getContext("2d");
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
      this.fogCanvas.width = w;
      this.fogCanvas.height = h;
      this.mapW = w;
      this.mapH = h;
      console.log("Floor SVG set:", w, "x", h);
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

  drawFog() {
    const ctx = this.fogCtx;
    if (!this.mapW || !this.mapH) return;

    ctx.clearRect(0, 0, this.mapW, this.mapH);

    // Cover everything in dark fog
    ctx.fillStyle = "rgba(0, 0, 0, 0.85)";
    ctx.fillRect(0, 0, this.mapW, this.mapH);

    // Clear visible tiles (fully transparent)
    for (const key of this.fov) {
      const [x, y] = key.split(",").map(Number);
      const px = x * this.cellSize + this.padding;
      const py = y * this.cellSize + this.padding;
      ctx.clearRect(px, py, this.cellSize, this.cellSize);
    }

    // Explored but not visible: dim overlay
    for (const key of this.explored) {
      if (this.fov.has(key)) continue;
      const [x, y] = key.split(",").map(Number);
      const px = x * this.cellSize + this.padding;
      const py = y * this.cellSize + this.padding;
      ctx.clearRect(px, py, this.cellSize, this.cellSize);
      ctx.fillStyle = "rgba(0, 0, 0, 0.5)";
      ctx.fillRect(px, py, this.cellSize, this.cellSize);
    }
  },

  draw() {
    const ctx = this.ctx;
    if (!this.canvas.width || !this.canvas.height) {
      return;
    }
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    // Draw doors first (behind entities)
    this._drawDoors(ctx);

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

      ctx.fillStyle = color;
      ctx.fillText(
        ent.glyph,
        px + this.cellSize / 2,
        py + this.cellSize / 2,
      );
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
    const wallLen = cs * 0.8;    // 80% of tile along wall
    const depth = cs * 0.25;     // 25% across passage
    const connLen = cs * 0.1;    // small wall connection stub
    const wallW = 4;             // match SVG WALL_WIDTH

    for (const door of this.doors) {
      // Secret doors are invisible (drawn as wall by SVG)
      if (door.state === "door_secret") continue;

      const px = door.x * cs + pad;
      const py = door.y * cs + pad;
      const cx = px + cs / 2;
      const cy = py + cs / 2;
      const fill = door.state === "door_open" ? "#FFFFFF" : "#000000";

      if (door.vertical) {
        // Wall runs top-bottom, passage left-right
        // Rectangle: tall (wallLen) and narrow (depth)
        const rx = cx - depth / 2;
        const ry = cy - wallLen / 2;

        // White background to clear any wall underneath
        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(rx - 2, ry - 2, depth + 4, wallLen + 4);

        // Door rectangle
        ctx.fillStyle = fill;
        ctx.fillRect(rx, ry, depth, wallLen);
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1;
        ctx.strokeRect(rx, ry, depth, wallLen);

        // Wall connection stubs (top and bottom)
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(cx, ry);
        ctx.lineTo(cx, ry - connLen);
        ctx.moveTo(cx, ry + wallLen);
        ctx.lineTo(cx, ry + wallLen + connLen);
        ctx.stroke();
      } else {
        // Wall runs left-right, passage top-bottom
        // Rectangle: wide (wallLen) and short (depth)
        const rx = cx - wallLen / 2;
        const ry = cy - depth / 2;

        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(rx - 2, ry - 2, wallLen + 4, depth + 4);

        ctx.fillStyle = fill;
        ctx.fillRect(rx, ry, wallLen, depth);
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 1;
        ctx.strokeRect(rx, ry, wallLen, depth);

        // Wall connection stubs (left and right)
        ctx.lineWidth = wallW;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(rx, cy);
        ctx.lineTo(rx - connLen, cy);
        ctx.moveTo(rx + wallLen, cy);
        ctx.lineTo(rx + wallLen + connLen, cy);
        ctx.stroke();
      }
    }
  },

  pixelToGrid(canvasX, canvasY) {
    const gx = Math.floor((canvasX - this.padding) / this.cellSize);
    const gy = Math.floor((canvasY - this.padding) / this.cellSize);
    return { x: gx, y: gy };
  },
};
