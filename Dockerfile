FROM nhc-base:latest

WORKDIR /app
COPY . .

USER nhc

ENV NHC_DATA_DIR=/var/nhc
ENV PYTHONPATH=/app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["gunicorn", \
     "--worker-class", "gevent", \
     "--workers", "1", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "nhc.web.app:app_factory()"]
