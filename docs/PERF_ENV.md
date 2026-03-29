# ZT-RAG: suorituskyvyn säätö (ympäristömuuttujat)

## Kyselypolku

| Muuttuja | Kuvaus |
|----------|--------|
| `ZT_QUERY_POLICY` | `standard` (oletus), `fast` / `single` / `quick` → ei dekomponointi-LLM-kutsua |
| `ZT_SKIP_QUERY_DECOMPOSE` | `1` → sama kuin fast |
| `ZT_ENABLE_HYDE` | `1` / `true` / `yes` / `on` → HyDE (rinnakkain) |
| `ZT_CONTEXT_CHUNKS` | Haettavien chunkkien määrä (oletus 10) |
| `ZT_CONTEXT_MAX_CHARS` | Prompt-kontekstin merkkikatto (oletus 45000) |
| `ZT_CONTEXT_MAX_CHUNK_CHARS` | Per-chunk katto (oletus 6000) |
| `ZT_CONTEXT_MAX_ROWS` | Enintään näin monta chunkkia kontekstiin |
| `ZT_TOP_K_FUSION` | Pakota hybridin fuusion `top_k` (yliajaa kutsun parametrin) |
| `ZT_MULTI_QUERY_K_PER` | Multi-query: kandidaatteja per alakysely (oletus 30) |
| `ZT_MULTI_QUERY_POOL` | Multi-query: yhdistetty pooli ennen rerankia (oletus 60) |
| `ZT_MULTI_QUERY_RRF_K` | RRF-k (oletus 60) |
| `ZT_RERANK_POLICY` | `always`, `adaptive`, `off` |
| `ZT_RERANK_MIN_GAP`, `ZT_RERANK_MIN_CANDIDATES` | Adaptiivinen rerank |
| `ZT_DISABLE_ANN` | `1` → brute-force vektori (`E @ qv`) |
| `ZT_ANN_MIN_CHUNKS`, `ZT_ANN_HNSW_M`, `ZT_ANN_EF_CONSTRUCTION`, `ZT_ANN_EF_SEARCH` | FAISS HNSW |
| `ZT_RERANKER_MODEL` | Cross-encoder-malli |
| `ZT_EMBED_BATCH` | Yliajaa embedding-batchin (ingest + kysely) |
| `ZT_TORCH_DEVICE` | `auto` / `cpu` / `cuda` |

### Vaikeat kysymykset (löydettävyys)

| Muuttuja / komento | Kuvaus |
|--------------------|--------|
| `python -m devworkflow.zt_rag.mcp_query_batch --hard` | Asettaa kontissa profiilin: `ZT_QUERY_HARD_RETRIEVAL=1`, `ZT_ENABLE_HYDE=1`, suuremmat `ZT_TOP_K_FUSION` / `ZT_MULTI_QUERY_*`, `ZT_CONTEXT_CHUNKS=14`, `ZT_ANN_EF_SEARCH=128` (tarkat arvot: `query_hard_profile.py`) |
| `ZT_QUERY_HARD_RETRIEVAL` | `1` → telemetriaan `retrieval_profile: hard` |
| `./devworkflow/zt_rag/run_query_batch_hard_all.sh` | Ajaa `query_batch_questions_*_hard.txt` kaikille pankille `--hard`-tilassa |

### Query-fallback ja termihakemisto (sanasto-ongelmat)

| Muuttuja | Kuvaus |
|----------|--------|
| `ZT_ENABLE_QUERY_FALLBACK` | `1` → toinen hakuyritys, jos ensimmäinen haku on heikko (tyhjä / liian vähän chunkkeja / kapea kandidaattipooli); toinen ajo käyttää tilapäisesti `query_hard_profile.py`‑profiilia (sis. **pakotettu HyDE** tuon profiilin ajaksi, vaikka hostilla `ZT_ENABLE_HYDE=0`) |
| `ZT_ENABLE_CORPUS_AWARE_REWRITE` | `1` → fallback-kyselyt ohjataan ottaen huomioon julkaistu `term_catalog.jsonl` (ota käyttöön yhdessä fallbackin kanssa) |
| `ZT_DISABLE_TERM_CATALOG` | `1` → ingest ei rakenna eikä julkaise termihakemistoa |
| `ZT_TERM_CATALOG_MAX_LINES` | `load_term_catalog` lukee enintään näin monta JSONL-riviä (oletus `100000`) — rajaa pahimman muistikuorman |
| `ZT_TERM_HINTS_MAX` | Enintään näin monta termivihjettä fallback-prompttiin (oletus `24`); tyhjällä osumalla + `ZT_ENABLE_CORPUS_AWARE_REWRITE` käytetään enintään 8 painotuinta termiä vihjeeksi |
| `ZT_FALLBACK_MIN_CTX_ROWS` | Fallback, jos palautuneita chunkkeja alle tämän (oletus `2`) |
| `ZT_FALLBACK_MIN_PRE_RERANK_POOL` | Fallback, jos rerankia edeltävä pooli (telemetria) on tätä kapeampi (oletus `12`) |

Telemetria: `retrieval_attempt_count`, `retrieval_chosen_attempt` (`primary` / `fallback`), `fallback_trigger_reason`, `fallback_queries`, `term_hints`. Eval: `eval_runner` raportoi `no_retrieval_rate` ja `fallback_chosen_rate`.

Golden-setit ja A/B: [devworkflow/zt_rag/golden_sets/README.md](../devworkflow/zt_rag/golden_sets/README.md), `./devworkflow/zt_rag/run_vocab_ab_compare.sh`.

Agentit eivät yleensä näe mitä kirjoja pankissa on; kysymyksen muotoilu vs. hakuprofiili: [MCP_AGENT_OHJE.md](MCP_AGENT_OHJE.md).

## Ingest

| Muuttuja | Kuvaus |
|----------|--------|
| `ZT_INGEST_PARSE_WORKERS` | Rinnakkaisten parse-prosessien määrä (oletus `min(4, lähteitä)`); `1` = sekventiaalinen |
| `ZT_DISABLE_EMBED_CACHE` | `1` → ei inkrementaalista embedding-välimuistia |
| `ZT_INGEST_REQUIRE_CUDA` | `1` → ingest vaatii GPU:n |

## Eval

```bash
PYTHONPATH=. python -m devworkflow.zt_rag.eval_runner \
  --golden golden.jsonl \
  --query-log /polku/queries.jsonl \
  --k 10
```

Golden-rivi: `{"question": "...", "gold_chunk_ids": ["..."]}`.

## Docker / NLI

`sentence-transformers` asentaa tyypillisesti `transformers`-riippuvuuden. Erillinen “NLI-image” ei välttämättä pienennä kokoa merkittävästi ilman kevyempää embedding-pinon vaihtoehtoa. NLI päälle: `ZT_ENABLE_NLI=1` (+ mallin lataus ensimmäisellä ajolla).
