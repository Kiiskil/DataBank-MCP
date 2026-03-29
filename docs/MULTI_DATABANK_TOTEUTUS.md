# Useita tietopankkeja + indeksin päivitys

Yksi palvelinbinääri (`devworkflow.zt_mcp_server`), **useita MCP-instansseja**: jokaisella oma **`Databank/<teema>/`** hostilla ja **oma Podman-volyymi** (`zt-rag-data-<slug>`).

---

## Hakemistorakenne

```
datapankki-mcp/
  Databank/
    AI/
    Software/
    Linux/
    Hacking/          # luo tarvittaessa
```

`Databank/` on `.gitignore`issa.

---

## Databank AI — päivitä indeksi (uudet EPUB/PDF)

1. Kopioi kirjat → `Databank/AI/`.
2. Jos agentti on luotu komennolla `create-mcp-agent --name "Databank AI"`, volyymi on **`zt-rag-data-databank-ai`** ja sync-polku kontissa **`/zt/bank`**.

```bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# tai: ROOT=/polku/datapankki-mcp
BANK="$ROOT/Databank/AI"
VOL=zt-rag-data-databank-ai
# Käytä samaa imagea kuin kysely-MCP:ssä (esim. zt_mcp_multibank.example.json → datapankki-mcp:latest).
# Vanha tagi koneella: podman tag localhost/datapankki-mcp:latest localhost/zt-rag-mcp:latest
IMG="${ZT_RAG_IMAGE:-localhost/datapankki-mcp:latest}"

podman run --rm -e ZT_DATA_DIR=/data \
  -v "$BANK:/zt/bank:ro,Z" -v "$VOL:/data" \
  --entrypoint python "$IMG" \
  -m devworkflow.zt_cli sync /zt/bank

podman run --rm -e ZT_DATA_DIR=/data \
  -v "$BANK:/zt/bank:ro,Z" -v "$VOL:/data" \
  --entrypoint python "$IMG" \
  -m devworkflow.zt_cli ingest

podman run --rm -e ZT_DATA_DIR=/data \
  -v "$BANK:/zt/bank:ro,Z" -v "$VOL:/data" \
  --entrypoint python "$IMG" \
  -m devworkflow.zt_cli coverage
```

- **Pakota täysi uudelleenparsinta:** `ingest`-vaiheessa `--force`.
3. Käynnistä **Databank AI** -MCP uudelleen IDE:ssä.

**Tarkista volyymi:** `podman volume ls | grep zt-rag`

**Legacy** ([`zt_cursor_mcp.json`](../zt_cursor_mcp.json)): workspace mount `/workspace`, volyymi `zt-rag-data` — käytä `sync /workspace/Databank/AI` samoilla mounteilla kuin MCP-merkinnässä.

---

## Monipankki-MCP (esimerkki: `zt_mcp_multibank.example.json`)

Neljä pankkia valmiina: **AI**, **Software**, **Linux**, **Hacking** — kullekin ingest-GPU + kysely-MCP; volyymit `zt-rag-data-databank-ai|software|linux|hacking`. Kysely-MCP käyttää **`localhost/datapankki-mcp:latest`**, ingest-GPU **`localhost/datapankki-mcp:rocm`**. Kopioi merkinnät **globaaliin** `~/.cursor/mcp.json`iin; repossa `.cursor/mcp.json` on tyhjä, jotta Cursor ei listaa palvelimia kahdesti. Polut `Databank/Linux/` ja `Databank/Hacking/`: Podman-mount vaatii että hakemisto on olemassa hostilla.

**Imagen uudelleenbuild ja yhden volyymin tyhjennys:** [PODMAN_REBUILD.md](PODMAN_REBUILD.md).

**Testikysymykset kaikille pankille (loki `queries.jsonl`):** reposta `./devworkflow/zt_rag/run_query_batch_all.sh` (`ANTHROPIC_API_KEY`). Vaikeat: `./devworkflow/zt_rag/run_query_batch_hard_all.sh` (`--hard`, tiedostot `query_batch_questions_*_hard.txt`).

**Cursor / agentit:** [MCP_AGENT_OHJE.md](MCP_AGENT_OHJE.md) — miten kysyä ilman kirjastoluetteloa; ylläpidon säätö (`query_hard_profile.py`, [PERF_ENV.md](PERF_ENV.md)).

---

## Uudet agentit: Software, Linux, Hacking

```bash
cd /polku/datapankki-mcp
export PYTHONPATH="$PWD"

python -m devworkflow.zt_cli create-mcp-agent \
  --name "Databank Software" \
  --databank "$PWD/Databank/Software" \
  --mcp-json ~/.cursor/mcp.json \
  --force

python -m devworkflow.zt_cli create-mcp-agent \
  --name "Databank Linux" \
  --databank "$PWD/Databank/Linux" \
  --mcp-json ~/.cursor/mcp.json \
  --force

python -m devworkflow.zt_cli create-mcp-agent \
  --name "Databank Hacking" \
  --databank "$PWD/Databank/Hacking" \
  --mcp-json ~/.cursor/mcp.json \
  --force
```

- **`--force`:** korvaa jo olemassa olevan saman avaimen.
- **`--mcp-json`:** vaihda polku jos käytät projektikohtaista konfiguraatiota.
- Tyhjä tai puuttuva `Databank/...` → luo kansio ja lisää kirjat ennen ajoa, tai `--mcp-only` + ingest myöhemmin.
- **Claude Desktop:** kopioi syntyneet `mcpServers`-objektit sovelluksen MCP-asetuksiin.

---

## Ympäristömuuttujat (muistutus)

- **`ANTHROPIC_API_KEY`**: pääasiassa **`zt_query`** -kutsuille; ingest/sync ovat usein paikallisia.
- **`ZT_QUERY_MODEL`**: oletusmalli kyselyille (ks. `zt_cli` / dokumentaatio).
- **`ZT_BOOTSTRAP_SYNC_PATHS`**: valinnainen; päivittää manifestin joka MCP-käynnistyksellä — **hidastaa** isoa korpusta.
- **`ZT_TORCH_DEVICE`**: `auto` (oletus), `cpu`, `cuda` — embeddingit ingestissä ja kyselyssä (ROCm = HIP → `cuda` kun saatavilla).
- **`ZT_EMBED_BATCH`**: embedding-batchin koko (oletus **32**).

### GPU Podmanissa (AMD)

Uutta agenttia luodessa: **`--podman-gpu amd`** — sama liputus tulee sekä **`mcp.json`**:n `podman run` -riveille että `create-mcp-agent`:n sync/ingest/coverage-ajoihin.  
Oletus-`Dockerfile` on **CPU-torch**; GPU-kontissa tarvitset **ROCm-PyTorch-imagen** (`--image …`). Yksityiskohdat: [PODMAN_AMD_GPU_SUUNNITELMA.md](PODMAN_AMD_GPU_SUUNNITELMA.md).

### Erillinen ingest-GPU -MCP (jaettu volyymi)

- **Image:** `podman build -f Dockerfile.rocm -t localhost/datapankki-mcp:rocm .`
- **Moduuli:** `devworkflow.zt_ingest_mcp_server` (ei `zt_query`; ei tarvitse `ANTHROPIC_API_KEY`:ia).
- **Valmiit merkinnät:** [`zt_mcp_multibank.example.json`](../zt_mcp_multibank.example.json) → liitä globaaliin MCP:hen; esim. Databank AI: mount `${workspaceFolder}/Databank/AI` → `/zt/bank`, volyymi **`zt-rag-data-databank-ai`**. Uusi pankki: kopioi yksi pari ja vaihda polut / volyymi / avaimet.
- **Käyttö:** aja raskaat ingestit GPU-kontissa MCP-työkalulla; kyselyt tavallisella **zt-rag** -instanssilla.

---

## Arch MCP (Coder-MCP-server)

Työkalurekisterissä jokaiselle pankille oma rivi; **`cursor_mcp_key`** = sama merkkijono kuin Cursorin / Clauden MCP-palvelimen **nimi** (esim. `Databank AI`).

---

## Tarkistuslista

1. Image ajan tasalla: `podman build -t localhost/datapankki-mcp:latest .`
2. `sync` → `ingest` → `coverage` ok
3. MCP uudelleenkäynnistys
4. Kokeile `zt_query` tai IDE:n työkalua
