#!/usr/bin/env bash
# A/B: eval_runner samasta query-lokista; vertaa baseline vs. fallback + termihakemisto.
# Käyttö: QUERY_LOG=/data/logs/queries.jsonl ./devworkflow/zt_rag/run_vocab_ab_compare.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="${ROOT}"
LOG="${QUERY_LOG:-}"
if [[ -z "${LOG}" ]]; then
  echo "Aseta QUERY_LOG=polku/queries.jsonl" >&2
  exit 1
fi
GOLDEN="${GOLDEN_JSONL:-${ROOT}/devworkflow/zt_rag/golden_sets/ai_vocab_mismatch.jsonl}"

echo "=== A: ilman fallback (ZT_ENABLE_QUERY_FALLBACK=0) ==="
env -u ZT_ENABLE_QUERY_FALLBACK -u ZT_ENABLE_CORPUS_AWARE_REWRITE \
  python -m devworkflow.zt_rag.eval_runner --query-log "${LOG}" "${GOLDEN:+--golden ${GOLDEN}}" || true

echo "=== B: fallback + korpus-vihjeet (loki ajettava näillä asetuksilla) ==="
echo "Vinkki: aja kyselyerät ZT_ENABLE_QUERY_FALLBACK=1 ZT_ENABLE_CORPUS_AWARE_REWRITE=1 ja vertaa lokia."
env ZT_ENABLE_QUERY_FALLBACK=1 ZT_ENABLE_CORPUS_AWARE_REWRITE=1 \
  python -m devworkflow.zt_rag.eval_runner --query-log "${LOG}" "${GOLDEN:+--golden ${GOLDEN}}" || true
