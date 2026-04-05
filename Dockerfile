FROM nhc-base:latest

WORKDIR /app
COPY . .

USER nhc

ENV NHC_DATA_DIR=/var/nhc
ENV PYTHONPATH=/app

# Multi-core tuning. We run a single gunicorn gthread worker that
# owns all session state (sessions, player registry, WebSocket
# connections) and fan CPU-bound dungeon generation out to a
# ProcessPoolExecutor. NHC_GEN_WORKERS sizes that pool. Default 4
# targets a quad-core SBC like the Orange Pi Zero 3. Override at
# `docker run` / compose time for larger or smaller hosts.
ENV NHC_GEN_WORKERS=4

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
