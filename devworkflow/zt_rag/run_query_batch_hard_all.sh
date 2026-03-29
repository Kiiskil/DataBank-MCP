#!/usr/bin/env bash
# Vaikeat testikysymykset kaikille pankille + löydettävyysprofiili (--hard: HyDE, leveämpi haku).
# Vaatii: ANTHROPIC_API_KEY, Podman, imagen localhost/datapankki-mcp:latest.
#
# Kysymystiedostot: query_batch_questions_*_hard.txt
#
# Käyttö (repojuuresta):
#   export ANTHROPIC_API_KEY=...
#   ./devworkflow/zt_rag/run_query_batch_hard_all.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "Aseta ANTHROPIC_API_KEY." >&2
  exit 1
fi

run_one() {
  local name="$1" vol="$2" bank_sub="$3" qfile="$4"
  echo "==================== ${name} (hard) ====================" >&2
  ZT_RAG_VOLUME="$vol" \
  ZT_MCP_DATABANK_HOST="${ROOT}/${bank_sub}" \
  python -m devworkflow.zt_rag.mcp_query_batch --hard --questions "$ROOT/${qfile}"
  echo "" >&2
}

run_one "Databank AI" "zt-rag-data-databank-ai" "Databank/AI" "devworkflow/zt_rag/query_batch_questions_ai_hard.txt"
run_one "Databank Software" "zt-rag-data-databank-software" "Databank/Software" "devworkflow/zt_rag/query_batch_questions_software_hard.txt"
run_one "Databank Linux" "zt-rag-data-databank-linux" "Databank/Linux" "devworkflow/zt_rag/query_batch_questions_linux_hard.txt"
run_one "Databank Hacking" "zt-rag-data-databank-hacking" "Databank/Hacking" "devworkflow/zt_rag/query_batch_questions_hacking_hard.txt"

echo "Valmis (hard). Lokissa telemetry.retrieval_profile == hard kun devworkflow mountattu." >&2
