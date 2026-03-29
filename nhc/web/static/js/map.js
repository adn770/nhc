/**
 * Map rendering: floor SVG + entity overlay canvas.
 *
 * Supports two tileset types:
 * - "text": Renders glyphs as colored text (classic terminal look)
 * - "image": Renders sprites from a PNG sprite sheet
 */
const GameMap = {
  canvas: null,
  ctx: null,
  cellSize: 32,  // must match SVG CELL constant
  padding: 16,   // must match SVG PADDING constant
  entities: [],
  fov: new Set(),
  tileset: null,
  tilesetImg: null,

  init() {
    this.canvas = document.getElementById("entity-canvas");
    this.ctx = this.canvas.getContext("2d");
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
        // Text-type tileset — no image to load
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
    this.draw();
  },

  /**
   * Resolve a color name to a CSS hex color.
   * Uses the tileset color map if available, otherwise returns as-is.
   */
  _resolveColor(colorName) {
    if (this.tileset && this.tileset.colors) {
      return this.tileset.colors[colorName] || colorName;
    }
    return colorName || "#FFFFFF";
  },

  draw() {
    const ctx = this.ctx;
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

      // Resolve color from tileset sprite definition or entity color
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
