#!/usr/bin/env bash
#
# Quick update: pull, rebuild the multi-stage Docker image,
# restart the service. Runs as a regular user (needs passwordless
# sudo for `systemctl restart nhc`).
#
# Setup (once, as root):
#   echo 'jtorra ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nhc' \
#     > /etc/sudoers.d/nhc-deploy
#
# Usage:
#   ./deploy/update.sh
#   ssh host "cd ~/src/nhc && bash deploy/update.sh"
#
# The image is a single multi-stage build (see Dockerfile): the
# fat builder stage's toolchain layers sit before `COPY . .`, so
# Docker caches them and app-only rebuilds stay fast. There is no
# separate base image or base-rebuild flag.
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_IMAGE="nhc-web"

# ── Pull latest code ───────────────────────────────────────
info "Pulling latest changes..."
cd "$REPO_DIR"
git pull --ff-only || fail "git pull failed (maybe local changes?)"
ok "Code updated."

# ── Build the multi-stage image ────────────────────────────
# Build args feed the welcome-page build-info badge so the
# running container advertises its commit + build time.
GIT_SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
info "Building app image (sha=${GIT_SHA}, time=${BUILD_TIME})..."
docker build \
    --build-arg "NHC_GIT_SHA=${GIT_SHA}" \
    --build-arg "NHC_BUILD_TIME=${BUILD_TIME}" \
    -t "$APP_IMAGE" "$REPO_DIR"
ok "App image built."

# ── Validate multilingual tables in the fresh image ───────
# Runs against the just-built runtime image (no toolchain base
# image exists anymore). Gates the restart: a bad table set
# leaves the old container running.
if [[ -d nhc/tables ]]; then
    info "Validating multilingual tables..."
    docker run --rm "$APP_IMAGE" \
        python -m nhc.tables.validator \
        || fail "Table validation failed — deploy aborted."
    ok "Tables validated."
fi

# ── Restart service ────────────────────────────────────────
info "Restarting nhc service..."
sudo /usr/bin/systemctl restart nhc

# ── Health check ───────────────────────────────────────────
info "Waiting for health check..."
for i in $(seq 1 10); do
    if curl -sf http://localhost:8080/health &>/dev/null; then
        ok "Service healthy."
        exit 0
    fi
    sleep 1
done
fail "Service did not become healthy in 10 seconds."
