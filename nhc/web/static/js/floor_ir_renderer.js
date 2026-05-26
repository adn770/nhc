// Browser-side dispatcher for the WASM rendering path.
//
// NIR-only: the game always renders the floor browser-side from
// the NIR. map.js's setFloorURL() imports this module lazily on
// the first floor change and falls back to the PNG endpoint only
// if the WASM bundle fails to load.
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

// Whole-floor render cache. The renderer runs ONCE per floor
// change, not per frame. When the player re-enters a previously
// rendered floor in the same session (stairs down, then back up),
// the `.nir` URL is stable (server-side `floor_svg_id` is a uuid
// hex held for the session, body is byte-identical between visits)
// — so the rendered pixels are identical too. Cache the rendered
// canvas keyed on the URL so revisits return in <10 ms.
//
// MAX = 3: at 3456x2880x4 bytes per canvas (~39.6 MB) this caps
// memory at ~120 MB. Tune lower if a player tab runs hot.
//
// Cache entries hold DETACHED canvases — we clone-on-read AND
// clone-on-write so the DOM-attached copy (installed via
// container.replaceChildren) can't be silently moved out from
// under us by a future floor change.
const RENDER_CACHE = new Map();
const RENDER_CACHE_MAX = 3;

function cloneCanvas(src) {
  const dst = document.createElement("canvas");
  dst.id = "floor-canvas";
  dst.width = src.width;
  dst.height = src.height;
  dst.getContext("2d").drawImage(src, 0, 0);
  return dst;
}

async function loadModule() {
  if (modulePromise === null) {
    modulePromise = (async () => {
      // Cache-bust against the same `?v=` token templates use
      // for static JS/CSS so a fresh wasm-pack build invalidates
      // the browser's cached bundle. The token is injected as a
      // `<meta name="static-version">` tag in index.html — no
      // fallback to a hard-coded value because a missing tag
      // means a templating bug, not something to silently work
      // around.
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
 * @param {boolean} [options.profile=false] Route through the
 *   profiled WASM entry. Logs one `[nhc-render]` line per render
 *   with per-layer ms (shadow, hatch, paint, stroke, stamp, roof,
 *   path, fixture) + total — used to investigate settlement
 *   render cost in DevTools. Ignored when `layer` is set (the
 *   single-layer debug path bypasses per-kind dispatch).
 * @param {string|null} [options.profileLabel=null] Opaque tag
 *   echoed into the profiling log line so DevTools filter by
 *   site / floor descriptor. Falls back to `url` when omitted.
 * @returns {Promise<{canvas: HTMLCanvasElement, width: number, height: number}>}
 */
export async function fetchAndRender(url, options = {}) {
  const {
    scale = 1.0,
    layer = null,
    bare = false,
    profile = false,
    profileLabel = null,
  } = options;
  // Cache key is the full URL (the per-floor uuid lives in the
  // path). Skip the cache for debug knobs (`layer`, `bare`,
  // non-default `scale`) so a one-off single-layer render can't
  // poison the production cache the production map.js path uses.
  if (layer === null && !bare && scale === 1.0 && RENDER_CACHE.has(url)) {
    const hit = RENDER_CACHE.get(url);
    RENDER_CACHE.delete(url);
    RENDER_CACHE.set(url, hit);
    if (profile) {
      const label = profileLabel ?? url;
      console.log(
        `[nhc-render] ${label} cached=true canvas=${hit.width}x${hit.height}`,
      );
    }
    return {
      canvas: cloneCanvas(hit.canvas),
      width: hit.width,
      height: hit.height,
    };
  }
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
  let renderDims;
  if (profile && layer === null) {
    const label = profileLabel ?? url;
    renderDims = mod.render_ir_to_canvas_profiled(
      buf, ctx, scale, bare, label,
    );
  } else {
    renderDims = mod.render_ir_to_canvas(buf, ctx, scale, layer, bare);
  }
  if (renderDims[0] !== w || renderDims[1] !== h) {
    console.warn(
      "[floor_ir_renderer] dims mismatch:",
      "pre-flight=", w, h, "render=", renderDims[0], renderDims[1],
    );
  }
  // Cache only the canonical render shape (no debug knobs). Match
  // the read-side gate above so the two paths stay symmetric.
  if (layer === null && !bare && scale === 1.0) {
    if (RENDER_CACHE.size >= RENDER_CACHE_MAX) {
      RENDER_CACHE.delete(RENDER_CACHE.keys().next().value);
    }
    RENDER_CACHE.set(url, {
      canvas: cloneCanvas(canvas),
      width: w,
      height: h,
    });
  }
  return { canvas, width: w, height: h };
}
