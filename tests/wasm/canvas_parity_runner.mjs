// Node runner for the Phase 5.6 canvas parity gate.
//
// Loads the wasm-pack output (`crates/nhc-render-wasm/pkg/`),
// renders a FloorIR fixture onto a Cairo-backed Canvas2D ctx
// from `@napi-rs/canvas`, and writes the resulting bitmap to a
// PNG. The pytest gate spawns this script and PSNR-compares the
// output against the canonical PNG fixture in
// `tests/fixtures/floor_ir/<descriptor>/reference.png`.
//
// Usage:
//   node tests/wasm/canvas_parity_runner.mjs <fixture_dir> <out_png>
//
//   - <fixture_dir>: directory containing `floor.nir` (e.g.
//     `tests/fixtures/floor_ir/seed7_town_surface`).
//   - <out_png>: path the runner writes the rendered PNG to.
//
// Why polyfill the DOM globals — `--target web` wasm-bindgen
// output guards every browser-typed argument with `instanceof`
// against globals like `CanvasRenderingContext2D` and
// `HTMLCanvasElement`, and the WebCanvasCtx (Phase 5.3) uses
// `document.createElement('canvas')` for the begin_group
// offscreen allocation. None of those exist in Node by default.
// The runner installs minimal shims BEFORE the wasm module
// imports — the canvases come from `@napi-rs/canvas`, and a
// stub `globalThis.document` routes the createElement calls
// back through `createCanvas`. The instanceof checks pass
// because we pin the `@napi-rs/canvas` constructors as the
// matching globals.

import { readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createCanvas } from "@napi-rs/canvas";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..");
const WASM_PKG = resolve(
  REPO_ROOT, "crates", "nhc-render-wasm", "pkg",
);

async function main() {
  const [, , fixtureDirArg, outPathArg] = process.argv;
  if (!fixtureDirArg || !outPathArg) {
    console.error(
      "usage: canvas_parity_runner.mjs <fixture_dir> <out_png>",
    );
    process.exit(2);
  }
  const fixtureDir = resolve(fixtureDirArg);
  const outPath = resolve(outPathArg);

  // The wasm bundle's WebCanvasCtx (Phase 5.3) reaches into
  // ``web_sys::window().document().create_element("canvas")`` for
  // each begin_group offscreen, and wasm-bindgen guards every
  // browser-typed argument with an ``instanceof`` check against
  // a global constructor (``Window`` / ``HTMLCanvasElement`` /
  // ``CanvasRenderingContext2D``). Node has none of those, so we
  // shim each one with a class whose ``Symbol.hasInstance`` slot
  // returns ``true`` unconditionally — every check passes
  // regardless of the actual prototype chain. This is safe for
  // the test runner because it never round-trips Rust code that
  // distinguishes between sub-types of the canvas hierarchy;
  // the only consumers are wasm-bindgen's own guard rails.
  function makePolyfillClass() {
    class Stub {}
    Object.defineProperty(Stub, Symbol.hasInstance, {
      value: () => true,
    });
    return Stub;
  }
  globalThis.Window = makePolyfillClass();
  globalThis.HTMLCanvasElement = makePolyfillClass();
  globalThis.CanvasRenderingContext2D = makePolyfillClass();
  // ``js_sys::global()`` returns globalThis; web_sys's
  // ``window()`` calls ``global.dyn_into::<Window>()`` which
  // succeeds now that ``globalThis instanceof Window`` is true.
  // The patched ``window.document`` then routes the
  // create_element path through @napi-rs/canvas; the wasm
  // ``dyn_into::<HtmlCanvasElement>()`` accepts the result
  // because the HTMLCanvasElement stub also accepts everything.
  globalThis.window = globalThis;
  globalThis.document = {
    createElement(tag) {
      if (tag !== "canvas") {
        throw new Error(`stub document.createElement(${tag}) unsupported`);
      }
      // Allocate at 0×0 — the wasm side immediately calls
      // canvas.set_width / set_height, which @napi-rs/canvas
      // honours through its width/height property setters.
      return createCanvas(0, 0);
    },
  };

  // wasm-bindgen's --target web init expects either a URL/path
  // or a BufferSource. Hand it the raw .wasm bytes so we don't
  // need fetch() in the Node runtime.
  const wasmBytes = await readFile(
    join(WASM_PKG, "nhc_render_wasm_bg.wasm"),
  );
  const mod = await import(join(WASM_PKG, "nhc_render_wasm.js"));
  // wasm-bindgen 0.2.95+ takes a single options object; the
  // legacy positional-arg form prints a deprecation warning.
  await mod.default({ module_or_path: wasmBytes });
  // Route Rust panics to console.error with their actual
  // message instead of the bare V8 ``RuntimeError: unreachable``.
  mod.install_panic_hook();

  const nirBytes = await readFile(join(fixtureDir, "floor.nir"));
  // Unwrap the Buffer view so wasm-bindgen sees a plain
  // Uint8Array — Node's Buffer is a Uint8Array subclass and
  // works directly, but the explicit copy keeps the boundary
  // clean.
  const nirU8 = new Uint8Array(
    nirBytes.buffer,
    nirBytes.byteOffset,
    nirBytes.byteLength,
  );

  const dims = mod.ir_canvas_dims(nirU8, 1.0);
  const [w, h] = [dims[0], dims[1]];

  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext("2d");
  const renderDims = mod.render_ir_to_canvas(
    nirU8, ctx, 1.0, undefined, false,
  );
  if (renderDims[0] !== w || renderDims[1] !== h) {
    console.error(
      `dims mismatch: pre-flight=${w}x${h} render=${renderDims[0]}x${renderDims[1]}`,
    );
    process.exit(3);
  }

  const png = await canvas.encode("png");
  await writeFile(outPath, png);
  console.log(JSON.stringify({ width: w, height: h, bytes: png.length }));
}

main().catch((err) => {
  console.error(err?.stack || String(err));
  process.exit(1);
});
