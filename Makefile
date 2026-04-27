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
