FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash -u 1000 nhc

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir \
    flask flask-sock shapely noise gunicorn gevent pyyaml

COPY . .

RUN apt-get purge -y --auto-remove gcc libc6-dev

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
