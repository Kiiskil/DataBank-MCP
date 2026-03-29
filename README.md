# Datapankki-MCP (ZT-RAG)

GitHub-repo: **[Kiiskil/DataBank-MCP](https://github.com/Kiiskil/DataBank-MCP)** (sama projekti; repossa englanninkertainen nimi).

Erillinen repo: **EPUB/PDF-tietopankki**, hybridihaku (BM25 + embeddings), MCP-stdio (`zt_*`-työkalut) ja `zt_cli` Podmanille.

Sisarrepo: **Coder-MCP-server** (`../Coder-MCP-server`) — DevWorkflow + Arch MCP; ei sisällä tätä RAG-pinoa. Ks. [docs/CODER_MCP_SERVER.md](docs/CODER_MCP_SERVER.md).

**Kirjasto:** paikallinen **`Databank/`** (esim. `Databank/AI/`) — **ei Gitissä** (`.gitignore`). Ks. [docs/DATABANK.md](docs/DATABANK.md).

**Useita MCP-agentteja + AI-indeksin päivitys:** [docs/MULTI_DATABANK_TOTEUTUS.md](docs/MULTI_DATABANK_TOTEUTUS.md).

**MCP + AI-agentit (ei korpustietoa oletuksena):** [AGENTS.md](AGENTS.md) → [docs/MCP_AGENT_OHJE.md](docs/MCP_AGENT_OHJE.md) (`zt_status`, kysymyksen muotoilu, milloin ylläpito säätää hakuprofiilia / `query_hard_profile.py`).

**AMD GPU:** [docs/PODMAN_AMD_GPU_SUUNNITELMA.md](docs/PODMAN_AMD_GPU_SUUNNITELMA.md) — hybridi (ingest hostilla) tai **Podman GPU-liput** (`create-mcp-agent --podman-gpu amd`) + valinnainen ROCm-image.

## Vaatimukset

- **`ANTHROPIC_API_KEY`** ympäristömuuttujana (kyselyt / `zt_query`; ingest ei välttämättä tarvitse sitä). Älä committaa avainta — käytä `${env:ANTHROPIC_API_KEY}` MCP-konffissa.
- **Podman** tai **Docker** (julkaistu image tai paikallinen build).
- **Python 3.12+** vain jos ajat koodia **paikallisesti** (ks. [Kehitys (ilman konttia)](#kehitys-ilman-konttia)); pelkkä kontti + `podman run` ei vaadi asennettua Pythonia hostilla.
- Raskaat riippuvuudet kontissa / venvissä: `requirements.txt` + `requirements-nli.txt`. Täysi lista: [docs/PERF_ENV.md](docs/PERF_ENV.md).

## Käyttöönotto (pika)

1. **Kloonaa** (tai lataa release) ja luo tietopankkihakemisto, esim. `Databank/AI/` ja sinne EPUB/PDF-tiedostoja. Ks. [docs/DATABANK.md](docs/DATABANK.md).
2. **API-avain** (kyselyihin): aseta `ANTHROPIC_API_KEY` shellissä tai käyttöjärjestelmän ympäristömuuttujissa ennen Cursorin / `podman run` -komentoja.
3. **Image** — joko julkaistu (kun repossa on tag `v*`, ks. [docs/JULKAISU_JA_INGEST_PROFIILIT.md](docs/JULKAISU_JA_INGEST_PROFIILIT.md)) tai [paikallinen build](#image).

**Esimerkki: GHCR-image + CLI** (korvaa `0.1.0` sopivalla tagilla, jos eri):

```bash
podman pull ghcr.io/kiiskil/databank-mcp:cpu
export ANTHROPIC_API_KEY=...   # älä tallenna repoon

podman run --rm -e ZT_DATA_DIR=/data \
  -v "$PWD:/workspace:ro,Z" -v zt-rag-data-demo:/data \
  --entrypoint python ghcr.io/kiiskil/databank-mcp:cpu \
  -m devworkflow.zt_cli sync /workspace/Databank/AI

podman run --rm -e ZT_DATA_DIR=/data \
  -v "$PWD:/workspace:ro,Z" -v zt-rag-data-demo:/data \
  --entrypoint python ghcr.io/kiiskil/databank-mcp:cpu \
  -m devworkflow.zt_cli ingest

podman run --rm -e ANTHROPIC_API_KEY -e ZT_DATA_DIR=/data \
  -v "$PWD:/workspace:ro,Z" -v zt-rag-data-demo:/data \
  --entrypoint python ghcr.io/kiiskil/databank-mcp:cpu \
  -m devworkflow.zt_cli status

podman run --rm -e ANTHROPIC_API_KEY -e ZT_DATA_DIR=/data \
  -v "$PWD:/workspace:ro,Z" -v zt-rag-data-demo:/data \
  --entrypoint python ghcr.io/kiiskil/databank-mcp:cpu \
  -m devworkflow.zt_cli query "Esimerkkikysymys korpuksesta"
```

Sama ketju **paikallisella imagella**: vaihda `ghcr.io/kiiskil/databank-mcp:cpu` → `localhost/datapankki-mcp:latest`.

**Cursor:** kopioi [`zt_cursor_mcp.json`](zt_cursor_mcp.json) tai käytä repossa olevaa [`.cursor/mcp.json`](.cursor/mcp.json) pohjana — säädä polut, volyymin nimi ja image (`localhost/...` tai `ghcr.io/...`). MCP-työkalut: [Työkalut (MCP)](#työkalut-mcp).

## Image

Paikallinen build:

```bash
cd /polku/datapankki-mcp
podman build -t localhost/datapankki-mcp:latest .
# tai: docker build -t localhost/datapankki-mcp:latest .
```

**Julkaistu image (GitHub Actions → GHCR):** kun [Kiiskil/DataBank-MCP](https://github.com/Kiiskil/DataBank-MCP) -repoon työnnetään tag `vX.Y.Z`, syntyy paketti `ghcr.io/kiiskil/databank-mcp`, tagit mm. `cpu`, `latest`, `rocm`, semver. Katso [docs/JULKAISU_JA_INGEST_PROFIILIT.md](docs/JULKAISU_JA_INGEST_PROFIILIT.md) (ensimmäinen push, historian litistäminen, `podman pull`).

Imagen päivitys, volyymin tyhjennys (esim. Linux-testi): [docs/PODMAN_REBUILD.md](docs/PODMAN_REBUILD.md).

### GPU-ingest (ROCm) + erillinen ingest-MCP

1. **Rakenna ROCm-image** (AMD; ROCm-indeksi vastaa host-ajureita, ks. [PyTorch ROCm](https://pytorch.org/get-started/locally/)):

```bash
podman build -f Dockerfile.rocm -t localhost/datapankki-mcp:rocm .
# Oletus-wheel: test/rocm7.1 (Nobaran / FC:n ROCm ~7.1 -ajurit). Vanhempi stack:
# --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/rocm6.3
# tai: https://download.pytorch.org/whl/rocm6.2
# Yöllinen 7.1: https://download.pytorch.org/whl/nightly/rocm7.1
```

2. **MCP-palvelin:** `python -m devworkflow.zt_ingest_mcp_server` — työkalut: `zt_sync_sources`, `zt_ingest`, `zt_verify_coverage`, `zt_status` (**ei** `zt_query`). Käyttää samaa `ZT_DATA_DIR` / Podman-volyymia kuin varsainen kysely-MCP, jotta indeksi on jaettu.

3. **Cursor:** kopioi `mcpServers`-lohko tiedostosta `mcp.json`iin. **Databank AI** (sama volyymi kuin `create-mcp-agent --name "Databank AI"`): [`zt_ingest_gpu_databank_ai_mcp.json`](zt_ingest_gpu_databank_ai_mcp.json) — workspace juuri (`${workspaceFolder}/Databank/AI`). **Databank Software / Linux / Hacking:** [`zt_ingest_gpu_databank_software_mcp.json`](zt_ingest_gpu_databank_software_mcp.json), [`zt_ingest_gpu_databank_linux_mcp.json`](zt_ingest_gpu_databank_linux_mcp.json), [`zt_ingest_gpu_databank_hacking_mcp.json`](zt_ingest_gpu_databank_hacking_mcp.json) (volyymit `zt-rag-data-databank-software`, `zt-rag-data-databank-linux`, `zt-rag-data-databank-hacking`). Muille pankkeille: [`zt_ingest_gpu_cursor_mcp.json`](zt_ingest_gpu_cursor_mcp.json) (säädä mount + `zt-rag-data-<slug>`). **GPU-laitteet** ovat pakollisia (`--device /dev/kfd`, `/dev/dri`, `video`/`render`).

4. **Työnkulku:** ingest-GPU-MCP:llä `zt_ingest` → käynnistä / käytä tavallista **zt-rag** -MCP:tä (`zt_mcp_server`) kyselyihin (CPU tai GPU, sama data).

## Cursor

- Esimerkki: [`zt_cursor_mcp.json`](zt_cursor_mcp.json) → kopioi `.cursor/mcp.json`iin tai globaaliin.
- **Projektissa:** repossa on [`.cursor/mcp.json`](.cursor/mcp.json) — useita palvelimia (esim. **Databank AI ingest GPU**, **Databank AI**). Polut ja `localhost/datapankki-mcp:*` -imaget ovat kehitysympäristökohtaisia; julkaistu image: [Image](#image) / [docs/JULKAISU_JA_INGEST_PROFIILIT.md](docs/JULKAISU_JA_INGEST_PROFIILIT.md).
- Paikallisen buildin image-nimet: **`localhost/datapankki-mcp:latest`** (CPU) ja **`localhost/datapankki-mcp:rocm`** (GPU-ingest).

## Työkalut (MCP)

| Työkalu | Kuvaus |
|--------|--------|
| `zt_sync_sources` | Lisää lähteet manifestiin |
| `zt_ingest` | Parsinta + indeksi |
| `zt_verify_coverage` | Manifest vs julkaistu indeksi |
| `zt_query` | Hybridihaku + vastaus |
| `zt_status` | Tila |

## CLI (Podman)

```bash
podman run --rm -e ANTHROPIC_API_KEY -e ZT_DATA_DIR=/data \
  -v "$PWD:/workspace:ro,Z" -v zt-rag-data:/data \
  --entrypoint python localhost/datapankki-mcp:latest \
  -m devworkflow.zt_cli sync /workspace/Databank/AI
```

Lisää komennot: `ingest`, `coverage`, `status`, `query`.

## Uusi MCP-agentti (useita tietopankkeja)

```bash
export PYTHONPATH=/polku/datapankki-mcp
python -m devworkflow.zt_cli create-mcp-agent --name "Työ AI" --databank /polku/kirjastoihin
# AMD GPU Podmanissa (MCP + ingest-putki): lisää ROCm-torch -image --image … ja:
# python -m devworkflow.zt_cli create-mcp-agent ... --podman-gpu amd
```

**Torch-laite / batch (ingest & kysely):** `ZT_TORCH_DEVICE` (`auto`|`cpu`|`cuda`), `ZT_EMBED_BATCH` (yliajo). Ilman yliajoa GPU/ROCm (`cuda`): embedding-batch oletus vähintään **64**, CPU: **32**.

**Ingest CPU:** EPUB käyttää `lxml`-parseria (fallback `html.parser`). Rinnakkainen parsinta: `ZT_INGEST_PARSE_WORKERS` (oletus `min(4, lähteitä)`; `1` = sekventiaalinen).

**Hybridin fuusio:** `ZT_TOP_K_FUSION` yliajaa haun `top_k`-fusionin (ks. [docs/PERF_ENV.md](docs/PERF_ENV.md)).

**Inkrementaalinen embedding (ingest):** uusi julkaisu yrittää kopioida vektorit edellisestä julkaistusta indeksistä `chunk_hash`-avaimella (sama `ZT_EMBEDDING_MODEL`). e5-malleilla edellisen indeksin `meta.json`:ssa pitää olla `st_encode_e5_mode: "prompt"` (vanhat indeksit → yksi täysi ingest ilman välimuistia). Täysi uudelleenencode: `ZT_DISABLE_EMBED_CACHE=1`. Julkaisuvastauksessa: `embedding_incremental` → `hits` / `misses` / `unique_encoded`.

**HyDE:** usean alakyselyn Anthropic-laajennukset rinnakkain (`ThreadPoolExecutor`, enintään 4 työntekijää).

**Kysely-latenssi:** `ZT_QUERY_POLICY=fast` (tai `single` / `quick`) tai `ZT_SKIP_QUERY_DECOMPOSE=1` → ei alakysely-dekomponointi-Anthropic-kutsua; yksi hakukysely (huonompi recall monimutkaisissa kysymyksissä).

**Skaala / vektorihaku:** ingest rakentaa FAISS HNSW -indeksin (`vectors.faiss`, inner product, normalisoidut embeddingit). Pois päältä: `ZT_DISABLE_ANN=1` → brute-force `E @ q`. Säätö: `ZT_ANN_MIN_CHUNKS`, `ZT_ANN_HNSW_M`, `ZT_ANN_EF_CONSTRUCTION`, `ZT_ANN_EF_SEARCH`. Chunk-id:t uusissa julkaisuissa: `chunk_ids.txt` (pienempi `meta.json`).

**Adaptiivinen rerank:** `ZT_RERANK_POLICY=adaptive` (tai `always`/`off`). Kynnykset: `ZT_RERANK_MIN_GAP`, `ZT_RERANK_MIN_CANDIDATES`.

**Kontekstibudjetti:** `ZT_CONTEXT_MAX_CHARS`, `ZT_CONTEXT_MAX_CHUNK_CHARS`, `ZT_CONTEXT_MAX_ROWS`. Kyselyvastauksen ja `queries.jsonl`-lokin mukana tulee `telemetry`, jossa vaiheajat (`decompose`, `hyde`, `retrieval`, `context_build`, `llm_answer`, `verify`, `total`), context-statistiikka sekä **`telemetry.rerank.events`**: lista rerank-päätöksistä (`stage`, `policy`, `requested`, `candidate_count`, `top_n`, `executed`, `skip_reason`, adaptiivisessa tilassa `min_candidates_threshold`).

## Git-remote

Katso [docs/REMOTE_SETUP.md](docs/REMOTE_SETUP.md).

## Kehitys (ilman konttia)

```bash
pip install "torch>=2.2.0" --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install -r requirements-nli.txt
export PYTHONPATH=.
python -m devworkflow.zt_mcp_server
```

Eval: `python -m devworkflow.zt_rag.eval_runner --query-log /polku/queries.jsonl` (keskiarvovaiheajat) tai `--golden golden.jsonl --query-log queries.jsonl --k 10` (recall@k + timing).

Testikysymykset (10 / pankki): AI — `devworkflow/zt_rag/query_batch_questions.txt` / `run_query_batch.sh`; Software / Linux / Hacking — `query_batch_questions_{software,linux,hacking}.txt` ja vastaavat `run_query_batch_*.sh`. **Kaikki neljä peräkkäin** (loki kuhunkin volyymiin): `./devworkflow/zt_rag/run_query_batch_all.sh` (`ANTHROPIC_API_KEY` + Podman). **Vaikeat kysymykset + leveämpi haku (HyDE):** `query_batch_questions_*_hard.txt` + `./devworkflow/zt_rag/run_query_batch_hard_all.sh` tai `mcp_query_batch --hard --questions …`. Vaihtoehto: `python -m devworkflow.zt_rag.mcp_query_batch --questions …` + `ZT_RAG_VOLUME` / `ZT_MCP_DATABANK_HOST`.

Kyselyloki volyymissa: `/data/logs/queries.jsonl`. Image käyttää oletuksena `zt_mcp_server`-entrypointia — tiedoston lukeminen: `podman run --rm -v <zt-rag-data-databank-*>:/data:ro,Z --entrypoint cat localhost/datapankki-mcp:latest /data/logs/queries.jsonl` (ilman `--entrypoint cat` komento `cat` ei suoritu).

---

Ympäristömuuttujat ja Podman-yksityiskohdat: ks. alkuperäinen pitkä ohje sisarrepossa `Coder-MCP-server/cursor_setup.md` (ZT-RAG -osuudet) tai laajenna tätä README:tä tarpeen mukaan.

## Lisenssi

[MIT](LICENSE).
