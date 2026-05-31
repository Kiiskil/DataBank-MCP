# cli-bot-databank (export, retrieve, tarkistus)

Ylläpidon työnkulku datapankki-mcp → cli-bot-release. Kysely-MCP:tä ei käytetä runtime-aikana.

## 1. Rakenna ja export

```bash
export ZT_DATA_DIR=/data/zt-rag-linux
python -m devworkflow.zt_cli sync /polku/Databank/Linux
python -m devworkflow.zt_cli ingest --force
python -m devworkflow.zt_cli export-linux \
  --output ./artifacts/linux-databank-0.1.0-dev.tar.zst \
  --version 0.1.0-dev
```

Tuottaa:

- `linux-databank-0.1.0-dev.tar.zst` — pura cli-bot-moduulihakemistoon
- `linux-databank-0.1.0-dev.tar.zst.package.json` — arkiston SHA256 + metadata (D5)

Sisäinen `manifest.json` (pakatun juuren alla) sisältää `sha256_indexes` hakemistolle `indexes/`.

## 2. Asennus cli-botissa

```text
~/.local/share/cli-bot/modules/linux/
  manifest.json
  indexes/current/ -> vN/
    meta.json
    chunks.jsonl
    bm25/
    embeddings.npy
    ...
```

`ZT_DATA_DIR` = tuo hakemisto.

## 3. Retrieve

```bash
export ZT_DATA_DIR=~/.local/share/cli-bot/modules/linux
python -m devworkflow.zt_retrieve -q "dnf install package" -n 5 --json
# tai
python -m devworkflow.zt_cli retrieve -q "..." -n 5 --json
```

JSON: [ZT-RETRIEVE-JSON.md](ZT-RETRIEVE-JSON.md). Ei `ANTHROPIC_API_KEY`. Ei dekomponointia eikä HyDE:tä.

## 4. Paketin eheys (doctor)

```bash
python -m devworkflow.zt_cli verify-databank-package --data-dir ~/.local/share/cli-bot/modules/linux
```

Valinnainen sidecar: `--package-manifest ./linux-databank-0.1.0-dev.tar.zst.package.json`

## 5. Smoke-kysymykset

```bash
export ZT_DATA_DIR=...
python -m devworkflow.zt_rag.run_smoke_retrieve
```

Lista: [`devworkflow/zt_rag/smoke_retrieve_questions.txt`](../devworkflow/zt_rag/smoke_retrieve_questions.txt). CI käyttää mock-testejä (`test_retrieve_smoke.py`); täysi integraatio vaatii mallit + indeksin.

`ZT_SMOKE_REQUIRE_CHUNKS=1` — epäonnistuu jos jokin kysymys palauttaa tyhjän `chunks`-listan.

## 6. zt-retrieve-binary (CI)

GitHub Actions: [`.github/workflows/build-zt-retrieve.yml`](../.github/workflows/build-zt-retrieve.yml) (tag `v*` tai `workflow_dispatch`).

Paikallinen build:

```bash
bash scripts/build_zt_retrieve.sh
# dist/zt-retrieve/zt-retrieve
# artifacts/zt-retrieve-<version>-linux-x86_64.tar.zst
```

Asenna cli-botissa esim. `~/.local/lib/cli-bot/zt-retrieve` (polku riippuu cli-bot-releasesta).

**R1 (mallit):** binary ei sisällä SentenceTransformer-/cross-encoder-malleja. Ensimmäinen ajo lataa HuggingFace-cacheen (`~/.cache/huggingface/`). Offline-asennus: esitä täytä cache ennen paketointia tai dokumentoi cli-bot-releasessa.

**R2:** CPU-only PyTorch retrieve-buildissä (`scripts/build_zt_retrieve.sh`).

## 7. Avoimet päätökset

| ID | Aihe |
|----|------|
| D1 | Dev-subset vs. koko Linux-korpus exportissa |
| R1 | Mallit mukana release-pakettiin vs. lazy HF-download |
