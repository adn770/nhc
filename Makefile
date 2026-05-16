# NHC make targets.
#
# Daily test / lint loops are driven from CLAUDE.md and the
# ./play / ./server launchers — this file is reserved for build
# steps that orchestrate external compilers and would otherwise
# need a hand-written script.
#
# Convention: every target is .PHONY (no real file dependencies),
# every recipe runs from the repo root, and every recipe is
# idempotent (running twice produces the same tree as running
# once). Targets that produce committed artifacts also delete the
# previous artifacts before regenerating, so removed schema
# entries don't leave dangling files behind.

REPO_ROOT := $(shell pwd)

FBS_SRC      := nhc/rendering/ir/floor_ir.fbs
FBS_BUILD    := build/ir-bindings

PY_OUT       := nhc/rendering/ir/_fb
RUST_OUT     := crates/nhc-render/src/ir
TS_OUT       := nhc/web/static/js/ir

PYTHON       := .venv/bin/python
RUST_CRATE   := crates/nhc-render

.PHONY: ir-bindings
ir-bindings:
	@command -v flatc >/dev/null || \
		{ echo "flatc not found — see CONTRIBUTING.md"; exit 1; }
	@echo "==> Regenerating IR bindings from $(FBS_SRC)"
	rm -rf $(FBS_BUILD)
	mkdir -p $(FBS_BUILD)/py $(FBS_BUILD)/rs $(FBS_BUILD)/ts
	flatc --python --gen-object-api -o $(FBS_BUILD)/py $(FBS_SRC)
	flatc --rust                    -o $(FBS_BUILD)/rs $(FBS_SRC)
	flatc --ts   --gen-all          -o $(FBS_BUILD)/ts $(FBS_SRC)
	@echo "==> Installing Python bindings -> $(PY_OUT)"
	mkdir -p $(PY_OUT)
	rm -f $(PY_OUT)/*.py
	cp $(FBS_BUILD)/py/nhc/rendering/ir/_fb/*.py $(PY_OUT)/
	@echo "==> Installing Rust bindings -> $(RUST_OUT)"
	mkdir -p $(RUST_OUT)
	rm -f $(RUST_OUT)/*_generated.rs
	cp $(FBS_BUILD)/rs/floor_ir_generated.rs $(RUST_OUT)/
	@echo "==> Installing TS bindings -> $(TS_OUT)"
	rm -rf $(TS_OUT)/nhc
	mkdir -p $(TS_OUT)
	cp -r $(FBS_BUILD)/ts/nhc $(TS_OUT)/
	@echo "==> ir-bindings done. Generated files are tracked; commit them."

.PHONY: rust-build
rust-build:
	@command -v cargo >/dev/null || \
		{ echo "cargo not found — see CONTRIBUTING.md"; exit 1; }
	@echo "==> Building nhc-render PyO3 wheel + installing editable"
	$(PYTHON) -m pip install -e $(RUST_CRATE)

.PHONY: rust-test
rust-test:
	@command -v cargo >/dev/null || \
		{ echo "cargo not found — see CONTRIBUTING.md"; exit 1; }
	@echo "==> cargo test (no PyO3 extension-module to keep linker honest)"
	cargo test -p nhc-render

# WASM bundle for the browser-side rendering path. The Flask
# route ``/wasm/<path>`` (registered in nhc/web/app.py) serves
# the bundle straight from ``crates/nhc-render-wasm/pkg/`` so
# this target is the only step needed to refresh the
# browser-loaded module after a Rust source change. The
# generated ``pkg/`` directory is .gitignored and a missing
# build falls through to a 404 → the JS dispatcher then warns
# and falls back to PNG.
# Single source of truth for the wasm-opt invocation. The
# Dockerfile builds the bundle via `make wasm-build` so these
# flags never drift between local and prod. -O1 is the
# gzipped-size sweet spot; the --enable-* flags match the
# wasm-bindgen 0.2 + Rust 1.95 output. Cargo.toml sets
# `wasm-opt = false` because wasm-pack's bundled binaryen is too
# old for --enable-bulk-memory-opt — we run a pinned binaryen
# wasm-opt (dev: Homebrew; Docker: Dockerfile.base) explicitly.
WASM_PKG := crates/nhc-render-wasm/pkg/nhc_render_wasm_bg.wasm
WASM_OPT_FLAGS := -O1 --enable-bulk-memory --enable-bulk-memory-opt \
	--enable-mutable-globals --enable-sign-ext \
	--enable-nontrapping-float-to-int --enable-multivalue \
	--enable-reference-types

.PHONY: wasm-build
wasm-build:
	@command -v wasm-pack >/dev/null || \
		{ echo "wasm-pack not found — install with 'cargo install \
wasm-pack'"; exit 1; }
	@command -v wasm-opt >/dev/null || \
		{ echo "wasm-opt not found — install binaryen"; exit 1; }
	@echo "==> wasm-pack build crates/nhc-render-wasm --target web"
	wasm-pack build crates/nhc-render-wasm --target web
	@echo "==> wasm-opt $(WASM_OPT_FLAGS)"
	wasm-opt $(WASM_PKG) -o $(WASM_PKG).opt $(WASM_OPT_FLAGS)
	mv $(WASM_PKG).opt $(WASM_PKG)
