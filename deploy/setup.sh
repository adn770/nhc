#!/usr/bin/env bash
#
# NHC deployment script — run with sudo on the target host.
#
# Usage:
#   sudo ./deploy/setup.sh          # interactive setup
#   sudo ./deploy/setup.sh --update # rebuild image + restart only
#
set -euo pipefail

# ── Colours ─────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

# ── Paths ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="nhc"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
OVERRIDE_DIR="/etc/systemd/system/${SERVICE_NAME}.service.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"
DATA_DIR="/var/nhc"
DOCKER_IMAGE="nhc-web"

# ── Pre-flight checks ──────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root (sudo)."
fi

if ! command -v docker &>/dev/null; then
    fail "Docker is not installed."
fi

if ! docker info &>/dev/null; then
    fail "Docker daemon is not running."
fi

info "Repository: ${REPO_DIR}"
info "Data dir:   ${DATA_DIR}"

# ── Parse flags ─────────────────────────────────────────────
UPDATE_ONLY=false
if [[ "${1:-}" == "--update" ]]; then
    UPDATE_ONLY=true
    info "Update mode — will rebuild image and restart service."
fi

# ── Build Docker image ──────────────────────────────────────
info "Building Docker image '${DOCKER_IMAGE}'..."
docker build -t "${DOCKER_IMAGE}" "${REPO_DIR}"
ok "Docker image built."

# In update mode, just restart and exit
if $UPDATE_ONLY; then
    info "Restarting ${SERVICE_NAME} service..."
    systemctl restart "${SERVICE_NAME}"
    sleep 3
    if curl -sf http://localhost:8080/health &>/dev/null; then
        ok "Service restarted and healthy."
    else
        warn "Service restarted but health check failed."
        echo "  Check logs with: journalctl -u ${SERVICE_NAME} -n 30"
    fi
    exit 0
fi

# ── Create data directory ───────────────────────────────────
if [[ ! -d "${DATA_DIR}" ]]; then
    info "Creating ${DATA_DIR}..."
    mkdir -p "${DATA_DIR}"
fi
chown 1000:1000 "${DATA_DIR}"
ok "Data directory ready: ${DATA_DIR}"

# ── Install systemd unit ────────────────────────────────────
info "Installing systemd unit file..."
cp "${SCRIPT_DIR}/nhc.service" "${SERVICE_FILE}"
ok "Installed ${SERVICE_FILE}"

# ── Gather secrets interactively ────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║        NHC Configuration Setup           ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# Load existing override values if present
EXISTING_AUTH_TOKEN=""
EXISTING_MAX_SESSIONS=""
EXISTING_DUCKDNS_SUB=""
EXISTING_DUCKDNS_TOKEN=""
if [[ -f "${OVERRIDE_FILE}" ]]; then
    info "Found existing override at ${OVERRIDE_FILE}"
    EXISTING_AUTH_TOKEN=$(grep -oP 'NHC_AUTH_TOKEN=\K.*' \
        "${OVERRIDE_FILE}" 2>/dev/null || true)
    EXISTING_MAX_SESSIONS=$(grep -oP 'NHC_MAX_SESSIONS=\K.*' \
        "${OVERRIDE_FILE}" 2>/dev/null || true)
    EXISTING_DUCKDNS_SUB=$(grep -oP 'DUCKDNS_SUBDOMAIN=\K.*' \
        "${OVERRIDE_FILE}" 2>/dev/null || true)
    EXISTING_DUCKDNS_TOKEN=$(grep -oP 'DUCKDNS_TOKEN=\K.*' \
        "${OVERRIDE_FILE}" 2>/dev/null || true)
fi

# Auth token
if [[ -n "${EXISTING_AUTH_TOKEN}" ]]; then
    echo -e "  Auth token: ${YELLOW}${EXISTING_AUTH_TOKEN:0:8}...${NC} (existing)"
    read -rp "  Keep existing auth token? [Y/n] " keep_token
    if [[ "${keep_token,,}" == "n" ]]; then
        EXISTING_AUTH_TOKEN=""
    fi
fi
if [[ -z "${EXISTING_AUTH_TOKEN}" ]]; then
    read -rp "  Generate a random auth token? [Y/n] " gen_token
    if [[ "${gen_token,,}" == "n" ]]; then
        read -rp "  Enter auth token: " NHC_AUTH_TOKEN
    else
        NHC_AUTH_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        echo -e "  Generated token: ${GREEN}${NHC_AUTH_TOKEN}${NC}"
    fi
else
    NHC_AUTH_TOKEN="${EXISTING_AUTH_TOKEN}"
fi

# Max sessions
DEFAULT_SESSIONS="${EXISTING_MAX_SESSIONS:-8}"
read -rp "  Max concurrent sessions [${DEFAULT_SESSIONS}]: " max_sessions
NHC_MAX_SESSIONS="${max_sessions:-${DEFAULT_SESSIONS}}"

# DuckDNS (optional, for internet exposure)
echo ""
read -rp "  Configure DuckDNS for internet access? [y/N] " setup_duckdns
DUCKDNS_SUBDOMAIN=""
DUCKDNS_TOKEN=""
if [[ "${setup_duckdns,,}" == "y" ]]; then
    if [[ -n "${EXISTING_DUCKDNS_SUB}" ]]; then
        echo -e "  Existing subdomain: ${YELLOW}${EXISTING_DUCKDNS_SUB}${NC}"
        read -rp "  Keep it? [Y/n] " keep_sub
        if [[ "${keep_sub,,}" != "n" ]]; then
            DUCKDNS_SUBDOMAIN="${EXISTING_DUCKDNS_SUB}"
        fi
    fi
    if [[ -z "${DUCKDNS_SUBDOMAIN}" ]]; then
        read -rp "  DuckDNS subdomain (without .duckdns.org): " DUCKDNS_SUBDOMAIN
    fi

    if [[ -n "${EXISTING_DUCKDNS_TOKEN}" ]]; then
        echo -e "  Existing DuckDNS token: ${YELLOW}${EXISTING_DUCKDNS_TOKEN:0:8}...${NC}"
        read -rp "  Keep it? [Y/n] " keep_dtoken
        if [[ "${keep_dtoken,,}" != "n" ]]; then
            DUCKDNS_TOKEN="${EXISTING_DUCKDNS_TOKEN}"
        fi
    fi
    if [[ -z "${DUCKDNS_TOKEN}" ]]; then
        read -rp "  DuckDNS token: " DUCKDNS_TOKEN
    fi
fi

# ── Write systemd override ──────────────────────────────────
info "Writing systemd override..."
mkdir -p "${OVERRIDE_DIR}"
cat > "${OVERRIDE_FILE}" <<CONF
[Service]
Environment=NHC_AUTH_TOKEN=${NHC_AUTH_TOKEN}
Environment=NHC_MAX_SESSIONS=${NHC_MAX_SESSIONS}
CONF

if [[ -n "${DUCKDNS_SUBDOMAIN}" && -n "${DUCKDNS_TOKEN}" ]]; then
    cat >> "${OVERRIDE_FILE}" <<CONF
Environment=DUCKDNS_SUBDOMAIN=${DUCKDNS_SUBDOMAIN}
Environment=DUCKDNS_TOKEN=${DUCKDNS_TOKEN}
CONF
fi

chmod 600 "${OVERRIDE_FILE}"
ok "Override written: ${OVERRIDE_FILE} (mode 600)"

# ── Enable and start ────────────────────────────────────────
info "Reloading systemd daemon..."
systemctl daemon-reload

info "Enabling ${SERVICE_NAME} service..."
systemctl enable "${SERVICE_NAME}"

info "Starting ${SERVICE_NAME} service..."
systemctl restart "${SERVICE_NAME}"

# ── Health check ────────────────────────────────────────────
echo ""
info "Waiting for service to become healthy..."
healthy=false
for i in $(seq 1 15); do
    if curl -sf http://localhost:8080/health &>/dev/null; then
        healthy=true
        break
    fi
    sleep 2
done

if $healthy; then
    HEALTH=$(curl -s http://localhost:8080/health)
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║          NHC deployed successfully!      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Health:   ${HEALTH}"
    echo -e "  Token:    ${GREEN}${NHC_AUTH_TOKEN}${NC}"
    echo -e "  LAN URL:  ${CYAN}http://$(hostname):8080/?token=${NHC_AUTH_TOKEN}${NC}"
    if [[ -n "${DUCKDNS_SUBDOMAIN}" ]]; then
        echo -e "  WAN URL:  ${CYAN}https://${DUCKDNS_SUBDOMAIN}.duckdns.org/?token=${NHC_AUTH_TOKEN}${NC}"
        echo ""
        warn "WAN access requires ports 80/443 forwarded to this host"
        warn "and Caddy reverse proxy running (not yet configured in systemd)."
    fi
    echo ""
    echo "  Useful commands:"
    echo "    journalctl -u nhc -f          # follow logs"
    echo "    systemctl status nhc          # service status"
    echo "    sudo $(realpath "$0") --update  # rebuild + restart"
else
    echo ""
    warn "Service did not become healthy in 30 seconds."
    echo "  Check logs with: journalctl -u ${SERVICE_NAME} -n 50"
    exit 1
fi
