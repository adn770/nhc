#!/usr/bin/env bash
# Setup OpenEuroLLM-Catalan model for ollama with GPU fix.
#
# The upstream model (jobautomation/OpenEuroLLM-Catalan) ships with
# num_gpu=1 which forces CPU-only inference. This script pulls the
# model and recreates it with num_gpu=999 so all layers load on GPU.
#
# Usage: ./scripts/setup-ollama-catalan.sh [--benchmark]

set -euo pipefail

MODEL_SRC="jobautomation/OpenEuroLLM-Catalan"
MODEL_FIX="OpenEuroLLM-Catalan-FIX"
BENCHMARK_PROMPT="Descriu en 3 frases una sala fosca de masmorra amb un altar antic i ossos escampats pel terra."

# Check ollama is available
if ! command -v ollama &>/dev/null; then
    echo "Error: ollama not found in PATH" >&2
    exit 1
fi

# Pull the upstream model if not already present
echo "==> Pulling ${MODEL_SRC}..."
ollama pull "${MODEL_SRC}"

# Create fixed model with GPU offloading
TMPFILE=$(mktemp /tmp/Modelfile.XXXXXX)
trap 'rm -f "${TMPFILE}"' EXIT

cat > "${TMPFILE}" <<EOF
FROM ${MODEL_SRC}
PARAMETER num_gpu 999
EOF

echo "==> Creating ${MODEL_FIX} (GPU fix: num_gpu 999)..."
ollama create "${MODEL_FIX}" -f "${TMPFILE}"

echo "==> Done. Model '${MODEL_FIX}' is ready."
echo "    Use with nhc: ./play --mode typed --model ${MODEL_FIX}"

# Optional benchmark
if [[ "${1:-}" == "--benchmark" ]]; then
    echo ""
    echo "==> Benchmarking ${MODEL_FIX}..."
    echo "    Prompt: ${BENCHMARK_PROMPT}"
    echo ""
    ollama run "${MODEL_FIX}" "${BENCHMARK_PROMPT}" --verbose 2>&1
fi
