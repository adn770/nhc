/**
 * Map rendering: floor SVG + entity overlay canvas + fog-of-war canvas.
 *
 * Three layers stacked:
 * 1. Floor SVG (static dungeon geometry)
 * 2. Fog canvas (dark overlay on non-visible tiles)
 * 3. Entity canvas (player, creatures, items on top)
 */
const GameMap = {
  canvas: null,
  fogCanvas: null,
  ctx: null,
  fogCtx: null,
  cellSize: 32,  // must match SVG CELL constant
  padding: 32,   // must match SVG PADDING constant
  entities: [],
  fov: new Set(),
  explored: new Set(),
  tileset: null,
  tilesetImg: null,
  mapW: 0,
  mapH: 0,

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
      // Insert fog between SVG and entity canvas
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

  updateEntities(entities) {
    this.entities = entities;
    this.draw();
  },

  updateFOV(fovList) {
    this.fov = new Set(fovList.map(([x, y]) => `${x},${y}`));
    // Track explored tiles (union of all FOV seen so far)
    for (const key of this.fov) {
      this.explored.add(key);
    }
    this.drawFog();
    this.draw();
  },

  /**
   * Resolve a color name to a CSS hex color.
   */
  _resolveColor(colorName) {
    if (this.tileset && this.tileset.colors) {
      return this.tileset.colors[colorName] || colorName;
    }
    return colorName || "#FFFFFF";
  },

  /**
   * Draw fog-of-war: dark overlay on non-visible tiles,
   * dim overlay on explored-but-not-visible tiles.
   */
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
      console.warn("draw() skipped: canvas has zero size");
      return;
    }
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

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
   * Convert canvas pixel coordinates to grid coordinates.
   */
  pixelToGrid(canvasX, canvasY) {
    const gx = Math.floor((canvasX - this.padding) / this.cellSize);
    const gy = Math.floor((canvasY - this.padding) / this.cellSize);
    return { x: gx, y: gy };
  },
};
