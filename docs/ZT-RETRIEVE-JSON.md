# zt-retrieve JSON-sopimus (schema_version 1)

Lähde totuudelle cli-botin `IndexAdapter`-parsinnalle. Toteutus: [`devworkflow/zt_rag/retrieve_runner.py`](../devworkflow/zt_rag/retrieve_runner.py), CLI: `python -m devworkflow.zt_cli retrieve -q "..." --json`.

## Käyttö

```bash
export ZT_DATA_DIR=~/.local/share/cli-bot/modules/linux
python -m devworkflow.zt_cli retrieve -q "dnf install package" --top-n 5 --json
```

- **stdout:** yksi JSON-objekti
- **stderr:** debug (ei parsittava)
- **Ei vaadi** `ANTHROPIC_API_KEY`
- Oletus: `ZT_QUERY_POLICY=fast` (yksi suora haku, ei dekomponointia eikä HyDE:tä)

## Onnistunut vastaus

```json
{
  "schema_version": 1,
  "ok": true,
  "question": "dnf install package",
  "chunks": [
    {
      "chunk_id": "uuid",
      "text": "...",
      "title": "Fedora Documentation",
      "section": "Package Management > dnf install",
      "heading_path": "Package Management > dnf install",
      "source_id": "abc12",
      "page": null,
      "lang": "en",
      "score": 0.82
    }
  ],
  "meta": {
    "index_version": 3,
    "embedding_model": "intfloat/multilingual-e5-base",
    "source_fingerprint": "abc123...",
    "chunk_count": 5
  },
  "telemetry": {
    "query_policy": "fast",
    "pre_rerank_pool_size": 42,
    "term_hints": ["dnf", "install"],
    "fingerprint_check_skipped": false,
    "timing_ms": { "retrieval": 850 }
  }
}
```

`score` on mukana kun rerank ajettiin; muuten kenttä voi puuttua.

## Virhevastaus

```json
{
  "schema_version": 1,
  "ok": false,
  "error": "index_not_published",
  "message": "No published index under ZT_DATA_DIR",
  "question": "optional if known"
}
```

| `error` | CLI exit |
|---------|----------|
| `empty_question` | 2 |
| `index_not_published` | 1 |
| `fingerprint_mismatch` | 1 |
| muu / poikkeus | 1 |

Tyhjä `chunks` onnistuneella haulla: `ok: true`, exit 0.

## Fingerprint export-paketissa

Jos `ZT_DATA_DIR` sisältää vain julkaistun indeksin (ei `manifests/sources.json` aktiivisilla lähteillä), fingerprint-tarkistus **ohitetaan** (`telemetry.fingerprint_check_skipped: true`).

## Indeksin export (cli-bot-paketti)

```bash
export ZT_DATA_DIR=/data/zt-rag-linux
python -m devworkflow.zt_cli export-linux \
  --output ./artifacts/linux-databank-dev.tar.zst \
  --version 0.1.0-dev
```

Pura cli-botissa: `~/.local/share/cli-bot/modules/linux/` (= `ZT_DATA_DIR`). Sisältö: `indexes/current/` + juuren `manifest.json`. Ei EPUB-lähteitä.

## Liittyvät dokumentit

- [INGEST_EPUB.md](INGEST_EPUB.md) — indeksin rakennus
- [MULTI_DATABANK_TOTEUTUS.md](MULTI_DATABANK_TOTEUTUS.md) — re-ingest + export-työnkulku
- [ZT_QUERY_BEST_PRACTICES.md](ZT_QUERY_BEST_PRACTICES.md) — täysi MCP-haku vs. retrieve
