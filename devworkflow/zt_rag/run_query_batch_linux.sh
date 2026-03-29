#!/usr/bin/env bash
# ZT-RAG-testikysymykset — Databank Linux (10 kpl).
# Kysymykset: devworkflow/zt_rag/query_batch_questions_linux.txt
# Lämmin MCP: python -m devworkflow.zt_rag.mcp_query_batch + env alla
# Käyttö: ./devworkflow/zt_rag/run_query_batch_linux.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMG="${ZT_RAG_IMAGE:-localhost/datapankki-mcp:latest}"
VOL="${ZT_RAG_VOLUME:-zt-rag-data-databank-linux}"
BANK="${ZT_DATABANK:-$ROOT/Databank/Linux}"
QFILE="${ZT_QUERY_BATCH_FILE:-$ROOT/devworkflow/zt_rag/query_batch_questions_linux.txt}"

mapfile -t QUESTIONS < <(grep -v '^[[:space:]]*#' "$QFILE" | grep -v '^[[:space:]]*$' || true)
if [[ ${#QUESTIONS[@]} -eq 0 ]]; then
  echo "Ei kysymyksiä: $QFILE" >&2
  exit 1
fi

extract_json() {
  python3 -c '
import json, sys
raw = sys.stdin.read()
dec = json.JSONDecoder()
candidates = []
for i, c in enumerate(raw):
    if c != "{":
        continue
    try:
        obj, _ = dec.raw_decode(raw[i:])
        if isinstance(obj, dict) and "verification_ok" in obj:
            candidates.append(obj)
    except json.JSONDecodeError:
        pass
if not candidates:
    print("{}", file=sys.stderr)
    sys.exit(1)
best = max(candidates, key=lambda d: len(json.dumps(d, ensure_ascii=False)))
print(json.dumps(best, ensure_ascii=False))
'
}

n=1
for q in "${QUESTIONS[@]}"; do
  echo "========== #$n ==========" >&2
  echo "$q" >&2
  out=$(podman run --rm \
    -e ANTHROPIC_API_KEY \
    -e ZT_DATA_DIR=/data \
    -v "$BANK:/zt/bank:ro,Z" \
    -v "$VOL:/data" \
    --entrypoint python "$IMG" \
    -m devworkflow.zt_cli query "$q" 2>&1) || true
  echo "$out" | extract_json | python3 -c '
import json,sys
d=json.load(sys.stdin)
vo=d.get("verification_ok")
vr=d.get("verification_reason","")
ans=d.get("answer") or {}
if isinstance(ans, dict):
    prev=ans.get("answer","")
else:
    prev=str(ans)
if len(prev)>160:
    prev=prev[:157]+"..."
err=d.get("_error") or d.get("error")
print(json.dumps({"n":'"$n"',"verification_ok":vo,"verification_reason":vr,"answer_preview":prev,"error":err}, ensure_ascii=False))
'
  n=$((n+1))
done
