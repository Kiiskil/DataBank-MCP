# Golden-setit (sanasto / recall)

Tiedostot `ai_vocab_mismatch.jsonl` ja `software_vocab_mismatch.jsonl` sisältävät kysymyksiä, joissa **intento** vastaa tietopankin aihetta, mutta **sanasto** on tarkoituksella väärä tai epätarkka (synonyymit, puhekieli, väärät kirjainlyhennelmät).

## Muoto

```json
{"question": "...", "gold_chunk_ids": ["chunk-uuid-1", "..."]}
```

- **`gold_chunk_ids`**: täytä indeksin `chunks.jsonl`:stä tai tunnetusta testidokumentista **ingestin jälkeen**. Tyhjä lista ei anna merkityksellistä `recall@k`‑mittaa — se on tarkoitettu pohjaksi.
- Voit ajaa `zt_query` / `mcp_query_batch`, kerätä `queries.jsonl`→`retrieval_chunk_ids` ja päivittää golden‑rivit, kun tiedät oikeat chunkit.

## Baseline / A/B

```bash
# Vain lokitilastot (ei recall ilman täytettyjä gold_chunk_idsejä):
PYTHONPATH=. python -m devworkflow.zt_rag.eval_runner \
  --query-log /data/logs/queries.jsonl

# Recall (täytetyt goldit):
PYTHONPATH=. python -m devworkflow.zt_rag.eval_runner \
  --golden devworkflow/zt_rag/golden_sets/ai_vocab_mismatch.jsonl \
  --query-log /data/logs/queries.jsonl \
  --k 10
```

Automaattinen vertailu kahdella profiililla: `devworkflow/zt_rag/run_vocab_ab_compare.sh`.
