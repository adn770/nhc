// Browser-side dispatcher for the WASM rendering path.
//
// Phase 5.4 of plans/nhc_pure_ir_v5_migration_plan.md. Loaded
// only when the server runs with --render-mode wasm; the meta
// tag injected by templates/index.html flips map.js's
// _renderMode() and setFloorURL() routes here instead of the
// PNG / SVG branches.
//
// The dispatcher:
//
//   1. Lazy-loads the wasm bundle on first use (cached for the
//      lifetime of the page).
//   2. Fetches the .nir buffer from the per-floor endpoint that
//      the server already exposes (`/api/game/<sid>/floor/<id>.nir`).
//   3. Pre-computes canvas dims via `ir_canvas_dims` so the
//      destination canvas can be sized BEFORE rendering (Canvas2D
//      rendering clips to the existing canvas size, so without
//      this step content lands cropped or stretched).
//   4. Calls `render_ir_to_canvas(buffer, ctx, scale, layer, bare)`.
//
// Initialisation failures (no /wasm/ route, wasm-pack output
// missing, init throws) bubble up as rejected Promises; the
// caller (map.js setFloorURL) catches and falls back to PNG so
// the player isn't stuck with a blank screen during a broken
// build.

let modulePromise = null;

async function loadModule() {
  if (modulePromise === null) {
    modulePromise = (async () => {
      // Cache-bust against the same `?v=` token templates use
      // for static JS/CSS so a fresh wasm-pack build invalidates
      // the browser's cached bundle. The token is injected as a
      // `<meta name="static-version">` tag in index.html alongside
      // the existing `render-mode` meta — no fallback to a
      // hard-coded value because a missing tag means a
      // templating bug, not something to silently work around.
      const meta = document.querySelector('meta[name="static-version"]');
      const v = meta ? meta.getAttribute("content") : "0";
      const mod = await import(`/wasm/nhc_render_wasm.js?v=${v}`);
      // wasm-bindgen's `--target web` glue exports `default` as
      // the init function; the first arg is the .wasm URL.
      await mod.default(`/wasm/nhc_render_wasm_bg.wasm?v=${v}`);
      return mod;
    })();
  }
  return modulePromise;
}

/**
 * Fetch a FloorIR buffer + render it onto a freshly-allocated
 * `<canvas>` element. Returns the canvas + its dimensions so the
 * caller can install it into the DOM and size companion overlay
 * canvases.
 *
 * @param {string} url Full URL to the .nir endpoint (no
 *   ".nir" suffix is appended — the caller passes the complete
 *   URL the floor was registered under).
 * @param {object} [options]
 * @param {number} [options.scale=1.0] Multiplier for the natural
 *   canvas dimensions. Matches the PNG entry point's scale.
 * @param {string|null} [options.layer=null] Single-layer filter
 *   (e.g. "shadows") for the debug visualiser. `null` renders
 *   the full stack.
 * @param {boolean} [options.bare=false] Drop the four
 *   decoration layers (mirror of the SVG `bare` flag).
 * @returns {Promise<{canvas: HTMLCanvasElement, width: number, height: number}>}
 */
export async function fetchAndRender(url, options = {}) {
  const { scale = 1.0, layer = null, bare = false } = options;
  const mod = await loadModule();
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Floor IR fetch failed: ${resp.status} ${url}`);
  }
  const buf = new Uint8Array(await resp.arrayBuffer());
  const dims = mod.ir_canvas_dims(buf, scale);
  const w = dims[0];
  const h = dims[1];
  const canvas = document.createElement("canvas");
  canvas.id = "floor-canvas";
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("canvas.getContext('2d') returned null");
  }
  // The render call returns dims too — they should match what
  // ir_canvas_dims produced; assert in dev mode so a regression
  // in either path surfaces loudly.
  const renderDims = mod.render_ir_to_canvas(buf, ctx, scale, layer, bare);
  if (renderDims[0] !== w || renderDims[1] !== h) {
    console.warn(
      "[floor_ir_renderer] dims mismatch:",
      "pre-flight=", w, h, "render=", renderDims[0], renderDims[1],
    );
  }
  return { canvas, width: w, height: h };
}
