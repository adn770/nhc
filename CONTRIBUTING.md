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

The map-rendering subsystem is migrating to a multi-runtime intermediate representation
(IR): a FlatBuffers schema is the wire format, a Rust crate (`crates/nhc-render/`)
holds the canonical procedural primitives, and the same crate cross-compiles to a PyO3
wheel for the server and a WebAssembly bundle for the browser. The plan is in
[`plans/nhc_ir_migration_plan.md`](plans/nhc_ir_migration_plan.md); the prerequisites
plan it depends on is [`plans/nhc_ir_prereqs_plan.md`](plans/nhc_ir_prereqs_plan.md),
including a longer recipe and version-policy notes in its Appendix A.

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

## Toolchain version policy

- The Rust channel is pinned in `rust-toolchain.toml`. Bump it deliberately, in its
  own commit (`chore: bump rust-toolchain to <channel>`).
- `wasm-pack` and `wasm-opt` versions get pinned in `Cargo.toml` build-deps once
  Phase 6 of the IR migration ships, so contributors don't get surprised by
  upstream output drift.
- `flatc` rolling-stable is fine — the schema language is conservative; pin only
  if a breaking flatc release lands.
