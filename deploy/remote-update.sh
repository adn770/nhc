#!/usr/bin/env bash
#
# Host-side remote-deploy agent.
#
# Triggered by nhc-deploy.path when the admin panel's Update button
# drops ${NHC_DATA_DIR}/.deploy-request into the persistent volume.
# Consumes the marker, runs deploy/update.sh (git pull + rebuild +
# restart), and records progress in ${NHC_DATA_DIR}/.deploy-status so
# the in-container admin panel can poll it across the restart.
#
# Runs as the repo-owning user (NOT root) under nhc-deploy.service.
# The container itself is unprivileged and cannot deploy; this host
# agent is the only thing that touches docker/systemd.
#
# NOTE: no `set -e` — a failed build must still be recorded in the
# status file rather than aborting silently.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${NHC_DATA_DIR:-/var/nhc}"
REQUEST="${DATA_DIR}/.deploy-request"
STATUS="${DATA_DIR}/.deploy-status"
LOG="${DATA_DIR}/deploy.log"

# Write a JSON status atomically. $1 = state, $2 = message. The
# current short git SHA is captured so the panel can show the
# deployed commit. Python handles JSON escaping robustly.
write_status() {
    NHC_STATE="$1" NHC_MSG="${2:-}" NHC_REPO="${REPO_DIR}" \
    NHC_STATUS="${STATUS}" python3 - <<'PY'
import json, os, subprocess, time
try:
    sha = subprocess.check_output(
        ["git", "-C", os.environ["NHC_REPO"],
         "rev-parse", "--short", "HEAD"],
        text=True, stderr=subprocess.DEVNULL).strip()
except Exception:
    sha = "unknown"
data = {
    "state": os.environ["NHC_STATE"],
    "message": os.environ["NHC_MSG"],
    "git_sha": sha,
    "updated_at": int(time.time()),
}
path = os.environ["NHC_STATUS"]
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(data, fh)
os.replace(tmp, path)
PY
}

# Consume the marker up front so a request arriving during this run
# re-arms the path unit and re-triggers a fresh deploy afterwards.
rm -f "${REQUEST}"

write_status running "pulling latest code and rebuilding"

if bash "${SCRIPT_DIR}/update.sh" >"${LOG}" 2>&1; then
    write_status success "deploy completed"
else
    # Surface the last non-blank line of the build log to the panel.
    last_line="$(grep -v '^[[:space:]]*$' "${LOG}" | tail -n 1)"
    write_status failed "${last_line:-update.sh failed; see deploy.log}"
fi
