#!/usr/bin/env bash
#
# scripts/harden-tests.sh — run the pytest suite repeatedly to
# surface flaky hangs, RNG-dependent long tails, and intermittent
# failures. Designed to run unattended for hours; each iteration
# drops a full log so you can come back later and grep.
#
# Usage:
#   scripts/harden-tests.sh [options]
#
# Options:
#   -n, --iterations N       Stop after N iterations (default: infinite)
#   -d, --duration H         Stop after H hours of wall time (default: infinite)
#   -m, --markers EXPR       pytest -m expression (default: "not slow")
#   -t, --test-timeout S     Per-test faulthandler timeout (default: 90)
#   -r, --run-timeout S      Per-iteration shell timeout (default: 900 = 15m)
#   -j, --jobs N             xdist worker count (default: "auto")
#   -o, --output-dir DIR     Log output root (default: debug/harden-<ts>)
#       --stop-on-fail       Exit on first failing iteration
#       --serial             Force single-process run (-p no:xdist). Useful
#                            when a hang has already been spotted and you
#                            want test-name granularity in the live log.
#   -h, --help               Show this help
#
# The suite hangs in the foreground → the live log goes silent at
# the hung test. On per-iteration timeout, the script sends SIGABRT
# first (Python's faulthandler prints every thread's stack into the
# log) then SIGKILL after a grace period. Any orphaned xdist
# workers are reaped between iterations so runs stay independent.
#
# Logs produced per run:
#   <output-dir>/
#     summary.csv             iter, start, duration_s, rc, status, passed, failed, hangs
#     summary.log             rolling human-readable summary
#     iter-0001.log           full pytest output for iteration 1
#     iter-0002.log           ...
#
# Status values in summary.csv:
#   pass   — all tests green
#   fail   — at least one test failed
#   hang   — exceeded --run-timeout, killed via SIGABRT/SIGKILL
#   error  — pytest exited with an unexpected code (collection error etc.)
#
set -u

RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${CYAN}[info]${NC}  %s\n" "$*" >&2; }
ok()    { printf "${GREEN}[ok]${NC}    %s\n" "$*" >&2; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$*" >&2; }
fail()  { printf "${RED}[fail]${NC}  %s\n" "$*" >&2; }

# ── defaults ──────────────────────────────────────────────────
ITER_LIMIT=0          # 0 = infinite
DURATION_HOURS=0      # 0 = infinite
MARKERS="not slow"
TEST_TIMEOUT=90
RUN_TIMEOUT=900
JOBS="auto"
OUTPUT_DIR=""
STOP_ON_FAIL=0
SERIAL=0

usage() {
    sed -n '2,40p' "$0"
    exit 0
}

# ── parse args ────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        -n|--iterations)   ITER_LIMIT="$2"; shift 2 ;;
        -d|--duration)     DURATION_HOURS="$2"; shift 2 ;;
        -m|--markers)      MARKERS="$2"; shift 2 ;;
        -t|--test-timeout) TEST_TIMEOUT="$2"; shift 2 ;;
        -r|--run-timeout)  RUN_TIMEOUT="$2"; shift 2 ;;
        -j|--jobs)         JOBS="$2"; shift 2 ;;
        -o|--output-dir)   OUTPUT_DIR="$2"; shift 2 ;;
        --stop-on-fail)    STOP_ON_FAIL=1; shift ;;
        --serial)          SERIAL=1; shift ;;
        -h|--help)         usage ;;
        *) fail "unknown arg: $1"; usage ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PYTEST="$SCRIPT_DIR/.venv/bin/pytest"
if [ ! -x "$PYTEST" ]; then
    fail ".venv/bin/pytest not found — create the venv first"
    exit 2
fi

# pick timeout binary (gtimeout on macOS, timeout elsewhere)
if command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN="gtimeout"
elif command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN="timeout"
else
    fail "need 'timeout' (GNU coreutils). Install with 'brew install coreutils'."
    exit 2
fi

# ── prepare output dir ────────────────────────────────────────
if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR="debug/harden-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$OUTPUT_DIR"
SUMMARY_CSV="$OUTPUT_DIR/summary.csv"
SUMMARY_LOG="$OUTPUT_DIR/summary.log"

if [ ! -f "$SUMMARY_CSV" ]; then
    printf "iter,start_utc,duration_s,rc,status,passed,failed,hangs\n" \
        > "$SUMMARY_CSV"
fi

# ── shutdown trap: flush final summary, reap xdist stragglers ─
START_EPOCH=$(date +%s)
finalize() {
    {
        printf "\n== harden-tests.sh shutting down at %s ==\n" \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        elapsed=$(( $(date +%s) - START_EPOCH ))
        printf "total elapsed: %dm %ds\n" $((elapsed / 60)) $((elapsed % 60))
        printf "iterations run: %d\n" "$ITER_DONE"
        if [ -s "$SUMMARY_CSV" ]; then
            # skip header
            rows=$(tail -n +2 "$SUMMARY_CSV")
            if [ -n "$rows" ]; then
                printf "status tally:\n"
                echo "$rows" | awk -F, '{print $5}' | sort | uniq -c \
                    | awk '{printf "  %-6s %s\n", $2, $1}'
            fi
        fi
    } | tee -a "$SUMMARY_LOG" >&2
    pkill -9 -f "sys.stdin.readline" 2>/dev/null || true
    exit 0
}
ITER_DONE=0
trap finalize INT TERM

# ── header in summary.log ─────────────────────────────────────
{
    printf "\n== harden-tests.sh started at %s ==\n" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf "output dir: %s\n" "$OUTPUT_DIR"
    printf "markers: %s\n" "$MARKERS"
    printf "test-timeout: %ds  run-timeout: %ds\n" \
        "$TEST_TIMEOUT" "$RUN_TIMEOUT"
    printf "jobs: %s  serial: %s\n" "$JOBS" "$SERIAL"
    if [ "$ITER_LIMIT" -gt 0 ]; then
        printf "iterations: %d\n" "$ITER_LIMIT"
    fi
    if [ "$DURATION_HOURS" != 0 ]; then
        printf "duration cap: %s hours\n" "$DURATION_HOURS"
    fi
    printf "\n"
} | tee -a "$SUMMARY_LOG"

DURATION_SECONDS=0
if [ "$DURATION_HOURS" != 0 ]; then
    DURATION_SECONDS=$(awk "BEGIN { print $DURATION_HOURS * 3600 }")
fi

# ── pytest args ───────────────────────────────────────────────
# faulthandler_timeout dumps every thread's stack when a single
# test exceeds it. We pair it with a per-run gtimeout that sends
# SIGABRT (triggering faulthandler dump + pytest abort) for any
# hang that doesn't trip the per-test limit.
PYTEST_ARGS=(
    -m "$MARKERS"
    -v
    --durations=10
    -o "faulthandler_timeout=${TEST_TIMEOUT}"
)
if [ "$SERIAL" = 0 ]; then
    PYTEST_ARGS+=( -n "$JOBS" --dist worksteal )
else
    PYTEST_ARGS+=( -p no:xdist )
fi

# ── main loop ─────────────────────────────────────────────────
run_iter() {
    local n=$1
    local logfile
    logfile="$OUTPUT_DIR/$(printf "iter-%04d.log" "$n")"

    local start_utc start_epoch
    start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    start_epoch=$(date +%s)

    info "iter ${n}: starting (log=${logfile})"
    {
        printf "== iter %d started %s ==\n" "$n" "$start_utc"
        printf "cmd: pytest %s\n" "${PYTEST_ARGS[*]}"
        printf "\n"
    } > "$logfile"

    # SIGABRT on timeout → Python faulthandler dumps stacks; -k
    # followed by SIGKILL 30s later if it ignores the abort.
    "$TIMEOUT_BIN" -s ABRT -k 30s "${RUN_TIMEOUT}s" \
        "$PYTEST" "${PYTEST_ARGS[@]}" \
        >> "$logfile" 2>&1
    local rc=$?
    local end_epoch
    end_epoch=$(date +%s)
    local duration=$(( end_epoch - start_epoch ))

    # classify outcome
    # timeout's conventional exit: 124 = SIGTERM timeout, 134/137 =
    # SIGABRT/SIGKILL follow-up. pytest's: 0 pass, 1 fail, 2 usage,
    # 3 internal, 4 no tests, 5 collect err.
    local status passed failed hangs
    passed=0; failed=0; hangs=0
    if [ "$rc" -eq 124 ] || [ "$rc" -eq 134 ] || [ "$rc" -eq 137 ]; then
        status=hang
        hangs=1
        warn "iter ${n}: HANG after ${duration}s (rc=$rc)"
    elif [ "$rc" -eq 0 ]; then
        status=pass
        passed=$(grep -oE '^[0-9]+ passed' "$logfile" | tail -1 \
            | awk '{print $1}')
        [ -z "$passed" ] && passed=0
        ok "iter ${n}: PASS (${passed} tests, ${duration}s)"
    elif [ "$rc" -eq 1 ]; then
        status=fail
        passed=$(grep -oE '[0-9]+ passed' "$logfile" | tail -1 \
            | awk '{print $1}')
        failed=$(grep -oE '[0-9]+ failed' "$logfile" | tail -1 \
            | awk '{print $1}')
        [ -z "$passed" ] && passed=0
        [ -z "$failed" ] && failed=0
        fail "iter ${n}: FAIL (${failed} failed, ${passed} passed, ${duration}s)"
    else
        status=error
        fail "iter ${n}: ERROR rc=$rc (${duration}s)"
    fi

    printf "%d,%s,%d,%d,%s,%d,%d,%d\n" \
        "$n" "$start_utc" "$duration" "$rc" "$status" \
        "$passed" "$failed" "$hangs" \
        >> "$SUMMARY_CSV"

    # reap any xdist workers the timeout killed without cleanup
    pkill -9 -f "sys.stdin.readline" 2>/dev/null || true

    case "$status" in
        hang|fail|error)
            if [ "$STOP_ON_FAIL" -eq 1 ]; then
                warn "--stop-on-fail set; exiting after iter ${n}"
                finalize
            fi
            ;;
    esac
}

ITER=0
while :; do
    ITER=$(( ITER + 1 ))
    run_iter "$ITER"
    ITER_DONE="$ITER"

    # iteration cap
    if [ "$ITER_LIMIT" -gt 0 ] && [ "$ITER" -ge "$ITER_LIMIT" ]; then
        info "reached --iterations $ITER_LIMIT; done"
        break
    fi

    # duration cap
    if [ "$DURATION_SECONDS" != 0 ]; then
        now=$(date +%s)
        elapsed=$(( now - START_EPOCH ))
        if [ "$elapsed" -ge "$DURATION_SECONDS" ]; then
            info "reached --duration cap (${DURATION_HOURS}h); done"
            break
        fi
    fi
done

finalize
