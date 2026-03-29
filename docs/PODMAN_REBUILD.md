# Podman-imaget ja volyymit — uudelleenbuild + Linux-testi

## Image-nimet (yhtenäinen repo)

| Käyttö | Image |
|--------|--------|
| Kysely-MCP (`zt_mcp_server`, CPU-torch) | `localhost/datapankki-mcp:latest` |
| Ingest-GPU-MCP (`zt_ingest_mcp_server`, ROCm) | `localhost/datapankki-mcp:rocm` |

Projektin [`.cursor/mcp.json`](../.cursor/mcp.json) käyttää näitä. Jos koneellasi on vanha tagi `localhost/zt-rag-mcp:latest`, voit säilyttää sen rinnalla:

```bash
podman tag localhost/datapankki-mcp:latest localhost/zt-rag-mcp:latest
```

## 1. Rakenna imaget (repojuuressa)

```bash
cd /polku/datapankki-mcp

podman build -t localhost/datapankki-mcp:latest .

podman build -f Dockerfile.rocm -t localhost/datapankki-mcp:rocm .
```

## 2. Tyhjennä yksi agentti (esim. Linux) — **poistaa indeksin**

MCP käyttää `podman run --rm`; pysyvä data on **volyymissa** `zt-rag-data-databank-<slug>`.

1. Sulje / disabloi Cursorissa kyseinen kysely- ja ingest-MCP (ettei volyymi ole käytössä).
2. Poista volyymi:

```bash
podman volume rm zt-rag-data-databank-linux
```

Volyymi syntyy uudelleen seuraavalla `podman run`:illa.

## 3. Uusi ingest

**Cursor:** käynnistä **Databank Linux ingest GPU** → `zt_sync_sources` (polku `/zt/bank`) → `zt_ingest`.

**CLI** (sama logiikka kuin ingest-MCP; säädä polut):

```bash
ROOT=/polku/datapankki-mcp
BANK="$ROOT/Databank/Linux"
VOL=zt-rag-data-databank-linux
IMG_ROCM=localhost/datapankki-mcp:rocm

podman run --rm -i \
  --device /dev/kfd --device /dev/dri --group-add 39 --group-add 105 \
  -e ZT_DATA_DIR=/data \
  -e ZT_TORCH_DEVICE=cuda \
  -e ZT_INGEST_REQUIRE_CUDA=1 \
  -v "$ROOT/devworkflow:/app/devworkflow:ro,Z" \
  -v "$BANK:/zt/bank:ro,Z" \
  -v "$VOL:/data" \
  "$IMG_ROCM" \
  -m devworkflow.zt_cli sync /zt/bank

podman run --rm -i \
  --device /dev/kfd --device /dev/dri --group-add 39 --group-add 105 \
  -e ZT_DATA_DIR=/data \
  -e ZT_TORCH_DEVICE=cuda \
  -e ZT_INGEST_REQUIRE_CUDA=1 \
  -v "$ROOT/devworkflow:/app/devworkflow:ro,Z" \
  -v "$BANK:/zt/bank:ro,Z" \
  -v "$VOL:/data" \
  "$IMG_ROCM" \
  -m devworkflow.zt_cli ingest
```

Valinnainen: `-e ZT_INGEST_PARSE_WORKERS=4` (tai `1`) rinnakkaisen parsinnan testiin.

## 4. IDE

Käynnistä **Databank Linux** (kysely-MCP) uudelleen tai **Reload** MCP-lista, jotta uusi `localhost/datapankki-mcp:latest` otetaan käyttöön.

Lisää: [MULTI_DATABANK_TOTEUTUS.md](MULTI_DATABANK_TOTEUTUS.md), [PODMAN_AMD_GPU_SUUNNITELMA.md](PODMAN_AMD_GPU_SUUNNITELMA.md), [PERF_ENV.md](PERF_ENV.md).
