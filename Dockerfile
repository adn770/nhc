FROM nhc-base:latest

WORKDIR /app
COPY . .

USER nhc

ENV NHC_DATA_DIR=/var/nhc
ENV PYTHONPATH=/app

# Multi-core tuning. We run a single gunicorn gevent worker that owns
# all session state (sessions, player registry, WebSocket connections)
# and fan CPU-bound dungeon generation out to a ProcessPoolExecutor.
# NHC_GEN_WORKERS sizes that pool. Default 4 targets a quad-core SBC
# like the Orange Pi Zero 3. Override at `docker run` / compose time
# for larger or smaller hosts.
ENV NHC_GEN_WORKERS=4

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# --workers 1 is intentional: gevent handles per-worker concurrency
# via greenlets, and keeping state in one process avoids a shared
# session store. CPU parallelism comes from NHC_GEN_WORKERS, not from
# gunicorn workers.
CMD ["gunicorn", \
     "--worker-class", "gevent", \
     "--workers", "1", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "nhc.web.app:app_factory()"]
