#!/usr/bin/env bash
# Generate a sample catalog from a base git ref into an output dir,
# for visual comparison against the working branch.
#
# Usage: gen_reference.sh [REF] [OUTDIR]
#   REF     git ref to render from   (default: main)
#   OUTDIR  catalog destination      (default: debug/reference)
#
# Rebuilds the native nhc_render extension for REF's IR schema,
# generates the catalog, then always restores the original branch
# and rebuilds its extension on exit (even on failure).
set -euo pipefail

REF="${1:-main}"
OUTDIR="${2:-debug/reference}"

cd "$(git rev-parse --show-toplevel)"
ORIG_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

restore() {
  echo "=== RESTORE: back to ${ORIG_BRANCH} ==="
  git checkout "${ORIG_BRANCH}"
  make ir-bindings
  make rust-build
  echo "=== RESTORE done ==="
}
trap restore EXIT

# Pick whichever sample generator module this ref ships. The tool
# was renamed generate_svg -> generate_samples across the pure-IR
# rewrite, so resolve it after checkout rather than hardcoding.
gen_module() {
  if [ -f tests/samples/generate_samples.py ]; then
    echo tests.samples.generate_samples
  elif [ -f tests/samples/generate_svg.py ]; then
    echo tests.samples.generate_svg
  else
    echo "no sample generator on ${REF}" >&2
    exit 1
  fi
}

echo "=== CHECKOUT ${REF} ==="
git checkout "${REF}"
git rev-parse --short HEAD

# The Cargo workspace globs crates/*; older refs lack
# nhc-render-wasm. Its gitignored pkg/ output survives checkout and
# leaves a Cargo.toml-less dir the glob chokes on. Drop it
# (regenerable; git checkout restores tracked crate files on
# restore).
echo "=== DROP stray crates/nhc-render-wasm ==="
rm -rf crates/nhc-render-wasm

echo "=== BUILD nhc_render for ${REF} ==="
make ir-bindings
make rust-build

MODULE="$(gen_module)"
echo "=== GENERATE (${MODULE}) -> ${OUTDIR}/ ==="
rm -rf "${OUTDIR}"
.venv/bin/python -m "${MODULE}" --outdir "${OUTDIR}"
echo "PNG count: $(find "${OUTDIR}" -name '*.png' | wc -l | tr -d ' ')"
echo "SVG count: $(find "${OUTDIR}" -name '*.svg' | wc -l | tr -d ' ')"
echo "=== GENERATE done ==="
