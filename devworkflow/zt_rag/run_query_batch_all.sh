#!/usr/bin/env bash
# Aja kaikki neljä Databank-MCP-testierää peräkkäin (loki: volyymin /data/logs/queries.jsonl).
# Vaatii: ANTHROPIC_API_KEY, Podman, imagen localhost/datapankki-mcp:latest, indeksit volyymeissa.
#
# Käyttö (repojuuresta):
#   export ANTHROPIC_API_KEY=...
#   ./devworkflow/zt_rag/run_query_batch_all.sh
#
# Valinnainen: ZT_RAG_IMAGE, ZT_MCP_SKIP_DEVWORKFLOW_MOUNT=1
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
  echo "==================== ${name} ====================" >&2
  ZT_RAG_VOLUME="$vol" \
  ZT_MCP_DATABANK_HOST="${ROOT}/${bank_sub}" \
  python -m devworkflow.zt_rag.mcp_query_batch --questions "$ROOT/${qfile}"
  echo "" >&2
}

run_one "Databank AI" "zt-rag-data-databank-ai" "Databank/AI" "devworkflow/zt_rag/query_batch_questions.txt"
run_one "Databank Software" "zt-rag-data-databank-software" "Databank/Software" "devworkflow/zt_rag/query_batch_questions_software.txt"
run_one "Databank Linux" "zt-rag-data-databank-linux" "Databank/Linux" "devworkflow/zt_rag/query_batch_questions_linux.txt"
run_one "Databank Hacking" "zt-rag-data-databank-hacking" "Databank/Hacking" "devworkflow/zt_rag/query_batch_questions_hacking.txt"

echo "Valmis. Tarkista lokit: podman run --rm -v <VOL>:/data:ro,Z --entrypoint cat localhost/datapankki-mcp:latest /data/logs/queries.jsonl" >&2
