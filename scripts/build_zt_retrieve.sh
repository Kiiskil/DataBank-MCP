#!/usr/bin/env bash
# Rakenna zt-retrieve onedir-dist (linux x86_64). Mallit ladataan ensimmäisellä ajolla (HF).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${ZT_RETRIEVE_VERSION:-0.0.0-dev}"
DIST_NAME="zt-retrieve"
OUT_DIR="$ROOT/dist/$DIST_NAME"
ARTIFACTS="$ROOT/artifacts"
TARBALL="$ARTIFACTS/${DIST_NAME}-${VERSION}-linux-x86_64.tar.zst"

echo "[build] repo: $ROOT"
PY="${PYTHON:-python3.12}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python3
fi
"$PY" -m venv .build-venv
# shellcheck disable=SC1091
source .build-venv/bin/activate

pip install -q --upgrade pip
pip install -q "torch>=2.2.0" --index-url https://download.pytorch.org/whl/cpu
pip install -q -r requirements-retrieve.txt
pip install -q -r requirements-build.txt

rm -rf build dist "$DIST_NAME.spec"

pyinstaller --noconfirm --clean --onedir \
  --name "$DIST_NAME" \
  --paths "$ROOT" \
  --hidden-import sklearn.utils._cython_blas \
  --collect-submodules bm25s \
  --exclude-module bm25s.mcp \
  --collect-all faiss \
  --collect-all sentence_transformers \
  "$ROOT/devworkflow/zt_retrieve.py"

test -x "$OUT_DIR/$DIST_NAME"
# Ilman julkaistua indeksiä CLI exit 1; stdout on silti validi JSON.
SMOKE_JSON=$("$OUT_DIR/$DIST_NAME" -q "ci smoke" --json 2>/dev/null || true)
printf '%s\n' "$SMOKE_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('error') == 'index_not_published', d
print('[build] smoke: index_not_published ok')
"

mkdir -p "$ARTIFACTS"
rm -f "$TARBALL"
if command -v zstd >/dev/null 2>&1; then
  tar -C "$ROOT/dist" -cf - "$DIST_NAME" | zstd -q -o "$TARBALL"
  echo "[build] artifact: $TARBALL"
else
  TARBALL_GZ="$ARTIFACTS/${DIST_NAME}-${VERSION}-linux-x86_64.tar.gz"
  tar -C "$ROOT/dist" -czf "$TARBALL_GZ" "$DIST_NAME"
  echo "[build] artifact (no zstd): $TARBALL_GZ"
fi

echo "[build] dist: $OUT_DIR"
deactivate 2>/dev/null || true
