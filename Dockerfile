# ============================================================
# Stage 1: builder — the full Rust + wasm toolchain. Compiles
# the nhc-render PyO3 wheel and the browser wasm bundle. None of
# this (rustup, cargo, wasm-pack, binaryen, build-essential,
# maturin) ships in the runtime image. The toolchain layers sit
# before `COPY . .`, so the legacy Docker builder caches them and
# app-only rebuilds stay fast — no separate base image / --base
# flag needed.
# ============================================================
FROM python:3.14-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl build-essential pkg-config ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain, pinned in lockstep with rust-toolchain.toml so
# the container, dev mac, and CI all agree.
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
ARG RUST_VERSION=1.95.0
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --default-toolchain $RUST_VERSION \
                       --profile minimal --no-modify-path

# wasm-pack 0.14.0 has no prebuilt GitHub binary (drager fork has
# no v0.14.0 asset), so build it from crates.io with the pinned
# toolchain. Version in lockstep with the dev mac.
ARG WASM_PACK_VERSION=0.14.0
RUN rustup target add wasm32-unknown-unknown \
    && cargo install wasm-pack --version "${WASM_PACK_VERSION}" --locked \
    && wasm-pack --version

# Pinned binaryen for wasm-opt. wasm-pack's *bundled* binaryen is
# too old for `--enable-bulk-memory-opt`, so Cargo.toml sets
# `wasm-opt = false` and `make wasm-build` invokes this pinned
# wasm-opt explicitly. Release binaries use rpath $ORIGIN/../lib
# so the extracted tree must stay intact.
ARG BINARYEN_VERSION=version_129
RUN curl --proto '=https' --tlsv1.2 -sSfL \
        "https://github.com/WebAssembly/binaryen/releases/download/${BINARYEN_VERSION}/binaryen-${BINARYEN_VERSION}-x86_64-linux.tar.gz" \
        | tar -xz -C /opt \
    && ln -s "/opt/binaryen-${BINARYEN_VERSION}/bin/wasm-opt" \
        /usr/local/bin/wasm-opt \
    && wasm-opt --version

RUN pip install --no-cache-dir maturin

WORKDIR /app
COPY . .

# nhc-render PyO3 wheel. We call `maturin build` directly rather
# than `pip install ./crates/nhc-render`: pip's PEP 517 build
# isolation installs a throwaway maturin that bootstraps its own
# Rust via `puccinialin` and fails ("no default linker (cc)")
# under the docker-build sandbox. Calling maturin against the
# system toolchain skips that detour.
RUN cd crates/nhc-render \
    && maturin build --release --interpreter python3.14 \
        --out /wheels

# Browser wasm bundle → crates/nhc-render-wasm/pkg/. `make
# wasm-build` runs wasm-pack then the pinned binaryen wasm-opt
# (flag set single-sourced in the Makefile).
RUN make wasm-build

# ============================================================
# Stage 2: runtime — lean. Python + the prebuilt wheel + wasm
# bundle. No compiler or Rust/wasm toolchain. `curl` stays for
# the HEALTHCHECK; ca-certificates for piper/onnx model fetches.
# ============================================================
FROM python:3.14-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash -u 1000 nhc

# Runtime Python deps — all wheels, no compiler needed. flatbuffers
# carries the IR migration's Python FB bindings. TTS deps are
# optional (fail gracefully if unavailable).
RUN pip install --no-cache-dir \
        flask flask-sock shapely gunicorn pyyaml flatbuffers \
    && pip install --no-cache-dir piper-tts onnxruntime requests \
        || true

WORKDIR /app
COPY . .

# Prebuilt artefacts from the builder stage.
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir --no-deps /tmp/*.whl \
    && rm -rf /tmp/*.whl
COPY --from=builder /app/crates/nhc-render-wasm/pkg/ \
    /app/crates/nhc-render-wasm/pkg/

USER nhc

ENV NHC_DATA_DIR=/var/nhc
ENV PYTHONPATH=/app

# Multi-core tuning. A single gunicorn gthread worker owns all
# session state; CPU-bound dungeon generation fans out to a
# ProcessPoolExecutor sized by NHC_GEN_WORKERS (default targets a
# quad-core x86_64 host).
ENV NHC_GEN_WORKERS=4

# Floor render mode the client fetches: "png" | "svg" | "wasm".
# Default wasm: the browser rasterises the ~38 KB NIR instead of
# the server building a multi-MB PNG/SVG. Override at run time:
#   docker run -e NHC_RENDER_MODE=png ...
ENV NHC_RENDER_MODE=wasm

# Build metadata for the welcome-page build-info badge. Set by
# deploy/update.sh via --build-arg; "dev" keeps local builds clean.
ARG NHC_GIT_SHA=dev
ARG NHC_BUILD_TIME=dev
ENV NHC_GIT_SHA=$NHC_GIT_SHA
ENV NHC_BUILD_TIME=$NHC_BUILD_TIME

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# --workers 1 + --worker-class gthread is intentional. Each
# request (including each WebSocket) runs on its own OS thread
# with its own asyncio thread-local state, so concurrent sessions
# don't collide on a shared event loop. Keeping state in one
# process avoids a shared session store; CPU parallelism for
# dungeon generation comes from NHC_GEN_WORKERS, not gunicorn
# workers. --threads 32 covers concurrent WS + short HTTP.
CMD ["gunicorn", \
     "--worker-class", "gthread", \
     "--workers", "1", \
     "--threads", "32", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "nhc.web.app:app_factory()"]
