#!/usr/bin/env bash
#
# Quick update: pull, rebuild Docker image, restart service.
# Runs as regular user (needs passwordless sudo for systemctl).
#
# Setup (once, as root):
#   echo 'jtorra ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nhc' \
#     > /etc/sudoers.d/nhc-deploy
#
# Usage:
#   ./deploy/update.sh          # code-only rebuild (fast)
#   ./deploy/update.sh --base   # rebuild base image (deps changed)
#   ssh host "cd ~/src/nhc && bash deploy/update.sh"
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
BASE_IMAGE="nhc-base"
APP_IMAGE="nhc-web"

# ── Pull latest code ───────────────────────────────────────
info "Pulling latest changes..."
cd "$REPO_DIR"
git pull --ff-only || fail "git pull failed (maybe local changes?)"
ok "Code updated."

# ── Build base image (only when --base is passed) ──────────
if [[ "${1:-}" == "--base" ]]; then
    info "Building base image (dependencies)..."
    docker build -t "$BASE_IMAGE" -f Dockerfile.base "$REPO_DIR"
    ok "Base image built."
elif ! docker image inspect "$BASE_IMAGE" &>/dev/null; then
    info "Base image not found, building it..."
    docker build -t "$BASE_IMAGE" -f Dockerfile.base "$REPO_DIR"
    ok "Base image built."
fi

# ── Validate multilingual tables (if subsystem exists) ────
if [[ -d nhc/tables ]]; then
    info "Validating multilingual tables..."
    docker run --rm -v "$REPO_DIR:/app" -w /app "$BASE_IMAGE" \
        python -m nhc.tables.validator \
        || fail "Table validation failed — deploy aborted."
    ok "Tables validated."
fi

# ── Rebuild app image ─────────────────────────────────────
info "Building app image..."
docker build -t "$APP_IMAGE" "$REPO_DIR"
ok "App image built."

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
