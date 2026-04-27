FROM nhc-base:latest

WORKDIR /app
COPY . .

# Build + install the nhc-render PyO3 wheel from the bundled
# crate source. Runs on every app-image rebuild so the wheel
# always matches the committed Rust + .fbs files.
#
# We invoke `maturin build` directly instead of `pip install
# ./crates/nhc-render` because pip's PEP 517 build isolation
# installs a fresh maturin into a throwaway venv, which then
# bootstraps its own Rust via the `puccinialin` helper instead
# of using the system toolchain at /usr/local/cargo. The bundled
# Rust install fails reproducibly with "no default linker (cc)
# was found in your PATH" under the docker-build sandbox.
# Calling maturin from the base image directly skips that whole
# detour and uses our pinned 1.95.0 toolchain.
RUN cd crates/nhc-render \
    && maturin build --release --interpreter python3.14 \
        --out /tmp/wheels \
    && pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels target

USER nhc

ENV NHC_DATA_DIR=/var/nhc
ENV PYTHONPATH=/app

# Multi-core tuning. We run a single gunicorn gthread worker that
# owns all session state (sessions, player registry, WebSocket
# connections) and fan CPU-bound dungeon generation out to a
# ProcessPoolExecutor. NHC_GEN_WORKERS sizes that pool. Default 4
# targets a quad-core x86_64 server. Override at `docker run` /
# compose time for larger or smaller hosts.
ENV NHC_GEN_WORKERS=4

# Build metadata surfaced on the welcome-page footer for
# at-a-glance deploy verification. Set by deploy/update.sh via
# --build-arg; the "dev" sentinel keeps local builds clean.
ARG NHC_GIT_SHA=dev
ARG NHC_BUILD_TIME=dev
ENV NHC_GIT_SHA=$NHC_GIT_SHA
ENV NHC_BUILD_TIME=$NHC_BUILD_TIME

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# --workers 1 + --worker-class gthread is intentional. Each request
# (including each WebSocket connection) runs on its own real OS
# thread with its own asyncio thread-local state, so concurrent
# sessions no longer collide on a shared event loop (the gevent
# worker monkey-patched threading, collapsing every "thread" into a
# greenlet on one OS thread and breaking per-session asyncio loops).
# Keeping state in one process avoids a shared session store. CPU
# parallelism for dungeon generation comes from NHC_GEN_WORKERS, not
# from gunicorn workers. --threads 32 comfortably covers concurrent
# WS sessions plus short-lived HTTP requests.
CMD ["gunicorn", \
     "--worker-class", "gthread", \
     "--workers", "1", \
     "--threads", "32", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "nhc.web.app:app_factory()"]
