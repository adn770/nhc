#!/usr/bin/env bash
#
# Trigger a remote NHC deploy from a dev machine — no SSH required.
#
# Replaces `ssh host "cd ~/src/nhc && bash deploy/update.sh"` for the
# common case (app / code / dependency changes). It POSTs to the admin
# Update endpoint, which drops a marker that the host-side
# nhc-deploy.path unit picks up to run git pull + rebuild + restart,
# then polls the deploy status until the build reaches a terminal state.
#
# Infra changes (CSP, systemd units, anything in setup.sh) still need
# `sudo bash deploy/setup.sh --update` over SSH — the endpoint can only
# run update.sh, it cannot install host units.
#
# Prerequisite: push your commit to origin/main first; the host pulls
# from there.
#
# Config (env vars):
#   NHC_ADMIN_TOKEN       admin token (preferred), OR
#   NHC_ADMIN_TOKEN_FILE  path to a file holding it
#                         (default: ~/.config/nhc/admin-token)
#   NHC_DEPLOY_URL        base URL (default: https://nhc-game.duckdns.org)
#   NHC_DEPLOY_TIMEOUT    seconds to wait for the build (default: 600)
#
# Usage:
#   bash deploy/trigger-deploy.sh
#
set -euo pipefail

URL="${NHC_DEPLOY_URL:-https://nhc-game.duckdns.org}"
TOKEN_FILE="${NHC_ADMIN_TOKEN_FILE:-${HOME}/.config/nhc/admin-token}"
TIMEOUT="${NHC_DEPLOY_TIMEOUT:-600}"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${CYAN}[info]${NC}  $*"; }
ok()   { echo -e "${GREEN}[ok]${NC}    $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail() { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

# Resolve the admin token: env var wins, else the token file.
TOKEN="${NHC_ADMIN_TOKEN:-}"
if [[ -z "${TOKEN}" && -f "${TOKEN_FILE}" ]]; then
    TOKEN="$(tr -d '[:space:]' < "${TOKEN_FILE}")"
fi
[[ -z "${TOKEN}" ]] && fail \
    "No admin token. Set NHC_ADMIN_TOKEN or write it to ${TOKEN_FILE}."

# Send the token in a header, never in the URL, so it stays out of
# proxy/access logs.
AUTH=(-H "Authorization: Bearer ${TOKEN}")

RESP="$(mktemp)"
trap 'rm -f "${RESP}"' EXIT

state_of() { grep -o '"state":"[^"]*"' "${RESP}" | head -n1 | cut -d'"' -f4; }
field_of() { grep -o "\"$1\":\"[^\"]*\"" "${RESP}" | head -n1 | cut -d'"' -f4; }
num_field() { grep -o "\"$1\":[0-9]*" "${RESP}" | head -n1 | cut -d: -f2; }

# Capture the status timestamp BEFORE requesting so a terminal result
# left by a previous deploy isn't mistaken for this one's (the host
# briefly serves the old status between consuming the marker and
# flipping it to "running").
curl -sS -o "${RESP}" "${AUTH[@]}" "${URL}/api/admin/update" \
    >/dev/null 2>&1 || true
baseline="$(num_field updated_at)"; baseline="${baseline:-0}"

# ── Request the deploy ─────────────────────────────────────
info "Requesting deploy at ${URL} ..."
http="$(curl -sS -o "${RESP}" -w '%{http_code}' \
    "${AUTH[@]}" -X POST "${URL}/api/admin/update" || echo 000)"
case "${http}" in
    200) ok "Deploy requested." ;;
    409) warn "A deploy is already in progress — attaching to it." ;;
    401|403) fail "Auth rejected (HTTP ${http}) — check the admin token." ;;
    000) fail "Could not reach ${URL}." ;;
    *)   fail "Deploy request failed (HTTP ${http}): $(cat "${RESP}")" ;;
esac

# ── Poll until the build reaches a terminal state ──────────
info "Waiting for the build (timeout ${TIMEOUT}s)..."
deadline=$(( SECONDS + TIMEOUT ))
last=""
seen_active=0
while (( SECONDS < deadline )); do
    # The container restarts mid-deploy; treat unreachable as transient.
    if curl -sS -o "${RESP}" "${AUTH[@]}" "${URL}/api/admin/update" \
        >/dev/null 2>&1; then
        state="$(state_of)"
        if [[ -n "${state}" && "${state}" != "${last}" ]]; then
            info "deploy: ${state}"
            last="${state}"
        fi
        # Accept a terminal result only once this deploy has gone
        # active, or its timestamp is newer than the pre-request one.
        u="$(num_field updated_at)"; u="${u:-0}"
        fresh=0
        (( seen_active )) && fresh=1
        (( u > baseline )) && fresh=1
        case "${state}" in
            requested|running) seen_active=1 ;;
            success)
                (( fresh )) && {
                    ok "Deploy complete ($(field_of git_sha))."; exit 0
                } ;;
            failed)
                (( fresh )) && fail "Deploy failed: $(field_of message)" ;;
        esac
    fi
    sleep 3
done
fail "Timed out after ${TIMEOUT}s waiting for the deploy to finish."
