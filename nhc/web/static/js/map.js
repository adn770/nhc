/**
 * Map rendering: floor SVG + entity overlay canvas.
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
    return fetch(`/api/tileset/${name}/manifest.json`)
      .then(r => r.json())
      .then(manifest => {
        this.tileset = manifest;
        this.tilesetImg = new Image();
        this.tilesetImg.src = `/api/tileset/${name}/${manifest.image}`;
        return new Promise(resolve => {
          this.tilesetImg.onload = resolve;
        });
      })
      .catch(() => {
        // Tileset not available yet — use text fallback
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

  draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    for (const ent of this.entities) {
      const px = ent.x * this.cellSize + this.padding;
      const py = ent.y * this.cellSize + this.padding;

      if (this.tileset && this.tilesetImg) {
        const sprite = this.tileset.sprites[ent.glyph];
        if (sprite) {
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

      // Fallback: draw glyph as text
      ctx.font = `bold ${this.cellSize - 4}px monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = ent.color || "#FFFFFF";
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
