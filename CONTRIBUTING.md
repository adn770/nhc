# Contributing to NHC

Most contribution mechanics (running the game, running tests, commit-message style, the
Python 3.14 floor) are documented in [`CLAUDE.md`](CLAUDE.md) and the
[`README.md`](README.md). This file covers the bits that are *not* obvious from the
codebase: the IR-migration toolchain, the git hooks, and the per-PR checklists used to
keep the parity gates honest.

## Day-to-day setup

Most work touches Python only and needs nothing beyond a virtualenv:

```sh
./play -G        # bootstraps .venv, installs requirements, starts the terminal game
./server         # same, but for the web server
.venv/bin/pytest -n auto --dist worksteal -m "not slow"   # the default dev loop
```

Once is enough — installing the git hooks. The pre-commit hook rejects commits that
reintroduce function-local imports shadowing a module-level name (the bug class behind
the teleporter-pad `UnboundLocalError` regression):

```sh
./scripts/install-hooks.sh
```

Skip the rest of this document if you are not touching `nhc/rendering/`, the
`crates/nhc-render/` Rust crate, or the FlatBuffers IR.

## First-time setup for IR-migration work

The map-rendering subsystem runs on a multi-runtime intermediate representation
(IR): a FlatBuffers schema is the wire format, a Rust crate (`crates/nhc-render/`)
holds the canonical procedural primitives, and the same crate cross-compiles to a PyO3
wheel for the server and a WebAssembly bundle for the browser. The plan is in
[`plans/nhc_ir_migration_plan.md`](plans/nhc_ir_migration_plan.md); the prerequisites
plan it depends on is [`plans/nhc_ir_prereqs_plan.md`](plans/nhc_ir_prereqs_plan.md),
including a longer recipe and version-policy notes in its Appendix A.

### Three switchable rasterisers

Every gameplay floor flows through one IR (`build_floor_ir(level)`); the floor
renders through one of three downstream rasterisers, picked at server start
via `--render-mode={svg,png,wasm}` (or the `NHC_RENDER_MODE` env var):

- **png** (default) — `nhc_render.ir_to_png` (Rust + tiny-skia). Smallest wire
  size; the gameplay client receives a `<img>` source. Deterministic pixels:
  the reference snapshots in `tests/fixtures/floor_ir/<descriptor>/reference.png`
  are tiny-skia output frozen via `--regen-reference`.
- **svg** — `ir_to_svg(buf)` (Python + Rust crate primitives). The gameplay
  client receives the SVG body and renders it inline. Cross-rasteriser parity
  is enforced by a PSNR > 35 dB gate against the same reference image, with
  `nhc_render.svg_to_png` (Rust resvg + usvg) as the SVG-mode pixel-comparison
  rasteriser.
- **wasm** — IR → Canvas via WASM. Phase 11 wires the third mode; the JS
  dispatch in `nhc/web/static/js/map.js` already reads the injected
  `<meta name="render-mode">` tag and falls back to PNG when the wasm
  loader is missing.

If you are working on the IR migration (or reviewing a PR that is), you need the Rust
toolchain plus three system binaries on PATH: `flatc`, `wasm-pack`, and `wasm-opt`.
Plus `maturin` in the project venv.

The Rust channel is pinned at the workspace root in `rust-toolchain.toml`, so once
`rustup` is installed, `cargo` auto-downloads the pinned channel the first time it
runs in the repo — no manual `rustup install` needed.

### macOS arm64 (primary dev target)

```sh
# rustup (do NOT use Homebrew's `rust` formula — version pinning matters for the
# wasm32-unknown-unknown target and PyO3 wheel reproducibility)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable
source "$HOME/.cargo/env"

# components + targets
rustup component add rustfmt clippy
rustup target add wasm32-unknown-unknown    # for IR migration Phase 6

# project tooling
brew install flatbuffers binaryen           # flatc + wasm-opt
cargo install wasm-pack                     # WASM packaging
.venv/bin/pip install maturin               # PyO3 wheel builder
```

### CachyOS / Arch (optional, server-side iteration)

The production server does not need Rust — wheels come from CI. Install on the server
only if your dev cycle includes "build wheel locally + rsync to server":

```sh
sudo pacman -S --needed base-devel pkgconf openssl flatbuffers binaryen

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable
# the server shell is fish — source the fish-flavoured env
source "$HOME/.cargo/env.fish"

rustup component add rustfmt clippy
.venv/bin/pip install maturin
```

To make the toolchain available in every fish session, add this to
`~/.config/fish/config.fish`:

```fish
source "$HOME/.cargo/env.fish"
```

### Verify

After install, every command below should print a version. If `rustc` reports a
channel different from the one in `rust-toolchain.toml`, run any `cargo` command
inside the repo to trigger the auto-download of the pinned channel.

```sh
rustc --version          # matches rust-toolchain.toml channel
cargo --version
flatc --version
wasm-pack --version
wasm-opt --version
.venv/bin/maturin --version
```

The Python-side sentinel `tests/unit/test_ir_prereqs.py` confirms `flatbuffers` and
`maturin` are importable in the venv. Run the fast suite to surface any breakage:

```sh
.venv/bin/pytest -n auto --dist worksteal -m "not slow"
```

## Working on the IR migration

The migration plan is split into eight phases (0 through 7), with byte-equal SVG
parity gates protecting every transition through Phase 7. The TDD cadence and
one-commit-per-milestone discipline are documented in the plan's *Working discipline*
section — read that before starting a phase.

The two specific contributor checklists worth surfacing here:

**Procedural-primitive PRs** (anything touching `nhc/rendering/_*.py` or
`crates/nhc-render/src/primitives/*`):

- Did the RNG or Perlin call sequence change?
- If yes, has the parity fixture set been regenerated (`make ir-fixtures`)?
- Has [`design/ir_primitives.md`](design/ir_primitives.md) been updated to match?

**FlatBuffers schema PRs** (anything touching `nhc/rendering/ir/floor_ir.fbs`):

- Is this additive (minor bump) or breaking (major bump)?
- For a major bump, are both transformers (Python emitter + Rust IR-to-SVG/PNG)
  updated in the same PR?
- The cache key includes `(major, minor)`, so version bumps auto-invalidate caches.
- After editing the schema, regenerate Python / Rust / TS bindings via
  `make ir-bindings`. The output is tracked in git — commit the regenerated
  files alongside the schema edit.

## Building the Rust crate locally

The procedural rendering primitives live in `crates/nhc-render/`. Two
build artefacts:

- **PyO3 wheel** (`make rust-build`) — installed editable into `.venv` via
  `maturin develop`. The Python side imports the resulting module as
  `nhc_render` (`import nhc_render`); see
  `nhc/rendering/ir_to_svg.py` for the call sites. Rebuild the wheel after
  any change under `crates/nhc-render/src/`.
- **Cargo unit tests** (`make rust-test` or
  `cargo test -p nhc-render --lib --release`) — pure-Rust tests for each
  primitive's RNG / Perlin contract.

The matching server build lane (Docker base image + app image) is
[deploy/setup.sh](deploy/setup.sh) and `bash deploy/update.sh --base`;
the cross-arch determinism contract (linux x86_64 reproduces the dev-mac
splitmix64 vector) is verified in `tests/unit/test_nhc_render_extension.py`.

## Adding a new procedural primitive

The canonical Rust core owns every per-tile RNG / geometry contract.
Adding a new primitive is a four-step recipe:

1. **Schema** — extend `nhc/rendering/ir/floor_ir.fbs` with a new op
   table (or a new variant on an existing op union). Bump
   `SCHEMA_MINOR` in `nhc/rendering/ir_emitter.py` for additive
   changes; major-bump only if you are removing fields. Run
   `make ir-bindings` and commit the regenerated Python / Rust / TS
   bindings.
2. **Rust port** — drop a new file under
   `crates/nhc-render/src/primitives/`, mirroring the structure of
   the existing primitives (e.g. `well.rs`, `tree.rs`). Re-export the
   PyO3 entry point from `crates/nhc-render/src/ffi/pyo3.rs`. Add
   inline `cargo test` cases that pin the deterministic call sequence
   independent of the Python harness. The methodology and pitfalls
   are normative in
   [`design/ir_primitives.md`](design/ir_primitives.md) §7.
3. **Python emitter** — populate the new op in the relevant
   `_emit_*_ir` helper in `nhc/rendering/_floor_layers.py`. Resolve
   any level-walk classification (corridor / surface_type / feature)
   in Python so the Rust handler stays purely geometric.
4. **Dispatcher** — register a handler in
   `nhc/rendering/ir_to_svg.py` (`_OP_HANDLERS[Op.Op.MyOp] =
   _draw_my_op_from_ir`) that calls the PyO3 entry point and wraps
   the output in any clip-path / dungeon-poly envelopes the layer
   needs. Update `_LAYER_OPS` so `layer_to_svg(buf, layer="...")`
   resolves to the new op type.

Tests: add a structural-invariants gate at
`tests/unit/test_emit_<primitive>_invariants.py` (synthetic-level
sanity checks — element counts, bbox bounds, NaN/Inf, byte-equal
re-render). Once a fixture covers the primitive, the snapshot lock
in `tests/fixtures/floor_ir/<descriptor>/` plus the floor-IR drift
gate (`tests/unit/test_floor_ir_fixture_drift.py`) provides full
regression coverage.

## Regenerating the WASM bundle (Phase 6)

The browser-side rendering path (Phase 6 of the IR plan) compiles
`crates/nhc-render/` to WebAssembly via `wasm-pack`. The bundle is
slated for `make wasm-build` once Phase 6 lands; today this target is
unimplemented (Phase 5 is server-side PNG rendering via `tiny-skia`).

When Phase 6 ships, the recipe will be:

```sh
make wasm-build       # wasm-pack build --target web --release
                      # then wasm-opt -Oz on the output .wasm
```

The resulting `.wasm` + JS glue gets vendored into
`nhc/web/static/js/nhc_render/` and loaded by the web client at
runtime.

## Toolchain version policy

- The Rust channel is pinned in `rust-toolchain.toml`. Bump it deliberately, in its
  own commit (`chore: bump rust-toolchain to <channel>`).
- `wasm-pack` and `wasm-opt` versions get pinned in `Cargo.toml` build-deps once
  Phase 6 of the IR migration ships, so contributors don't get surprised by
  upstream output drift.
- `flatc` rolling-stable is fine — the schema language is conservative; pin only
  if a breaking flatc release lands.
