# AMD GPU + ZT-RAG: hybridimalli (valittu lähestymistapa)

## Onko tämä järkevä?

**Kyllä.** Tämä on usein **kustannustehokkain** kompromissi:

| Osio | Missä | Peruste |
|------|--------|---------|
| **Ingest, coverage, isot batchit** | **Host** + **ROCm PyTorch** | Suurin GPU-hyöty; vähiten Podman+GPU -säätöä |
| **MCP (`zt_mcp_server`, `zt_query`)** | **Podman CPU-image** (nykyinen) | Kevyt, toimii ilman `/dev/kfd` -passthroughia; query ei ole sama pullonkaula kuin ingest |

MCP ja ingest jakavat **saman indeksin**, kun **`ZT_DATA_DIR`** osoittaa **samaan dataan** kuin MCP-kontin volyymi (ks. §2).

---

## 1. Nykytila (lähtökohta)

| Komponentti | Tila |
|-------------|------|
| `Dockerfile` | PyTorch **CPU-wheel** — **säilyy** MCP:lle |
| `index_publish.py` | `encode` ilman eksplisiittistä `device` / `batch_size` |
| `retrieval.py` | Encoderit oletuslaitteella |
| Ingest tyypillisesti | `podman run … zt_cli ingest` — voidaan jatkaa CPU:lla tai siirtää hostille GPU:lle |

---

## 2. Kriittinen: sama data hostin ja MCP:n välillä

MCP käyttää Podman-volyymia, esim. `zt-rag-data-databank-ai:/data`.

Host-ingestin pitää kirjoittaa **samaan hakemistoon**:

```bash
# Etsi volyymin mountpoint (rootless-polku vaihtelee)
podman volume inspect zt-rag-data-databank-ai --format '{{.Mountpoint}}'
```

Aja hostilla (esimerkki):

```bash
export ZT_DATA_DIR=/polku/jonka/sait/yllä
export PYTHONPATH=/polku/datapankki-mcp
cd /polku/datapankki-mcp
python -m devworkflow.zt_cli sync /polku/Databank/AI   # tai vain ingest jos manifest ajan tasalla
python -m devworkflow.zt_cli ingest
python -m devworkflow.zt_cli coverage
```

**Huom:** `sync` tarvitsee **samat lähteet** kuin MCP:llä (esim. sama `Databank/AI` -polku hostilla). **Älä** aja ingestiä MCP:hen ja hostille **samanaikaisesti** samaan volyymiin (kaksi kirjoittajaa). Jos ingest-MCP:ää ei käynnistä tai et kutsu siltä `zt_ingest` samanaikaisesti, pelkkä host-ingest on ok.

**ROCm ↔ PyTorch-kontti:** Tarkista hostilla `rpm -q rocm-core` / `rocminfo`. Rakenna `Dockerfile.rocm` niin, että `TORCH_INDEX_URL` vastaa ajuripinoa (ks. Dockerfile.rocm -kommentit; Nobara 43 + ROCm 7.1.x → oletuksena `test/rocm7.1`). Vanha `rocm6.2` -wheel ROCm 7.x -ajurilla + RDNA3 voi antaa `HIP error: invalid device function`.

**Vaihtoehto tulevaisuuteen:** sidottu bind-mount host-polkuun `:/data` kehityksessä — helpottaa polkua ilman `volume inspect`.

---

## 3. Tavoitearkkitehtuuri (hybridi)

```
  Host (Nobara/Fedora)
  ├── ROCm + PyTorch + venv
  ├── zt_cli sync / ingest / coverage  ──►  ZT_DATA_DIR = volyymin mountpoint
  └── (GPU vain täällä)

  Podman (CPU image, ennallaan)
  └── zt_mcp_server  ──►  sama volyymi :/data  →  zt_query lukee julkaistun indeksin
```

---

## 4. Toteutusvaiheet (suositusjärjestys)

### A — Host-ympäristö

1. Asenna **ROCm** + ajurit (AMD + distro-ohje).
2. Luo **venv** datapankki-mcp -repoon; asenna **PyTorch ROCm** (ei CPU-wheelia Dockerfilesta — erillinen `requirements-host-rocm.txt` tai dokumentoitu `pip install`).
3. `pip install -r requirements.txt` ja `pip install -r requirements-nli.txt` (torch jätetään pois host-asennuksessa *tai* yliajetaan ROCm-wheelilla).
4. Varmista: `python -c "import torch; print(torch.cuda.is_available())"` → `True`.

### B — Koodi (repo) — toteutettu

1. **`ZT_TORCH_DEVICE`**: `auto` | `cpu` | `cuda` (ROCm:lla usein `cuda` = HIP) — `devworkflow/zt_rag/torch_device.py`.
2. **`ZT_EMBED_BATCH`**: positiivinen kokonaisluku (embedding-encode batch) — oletus **32**.
3. **`index_publish.py`**: `SentenceTransformer(..., device=…)` + `encode(..., batch_size=…)`.
4. **`retrieval.py`**: sama laite logiikka kysely- ja rerank-malleille.

**MCP-kontissa** oletus-CPU-imagella `auto` → **CPU** (kuten ennen). ROCm-imagella + GPU-passthrough → `cuda` kun `torch.cuda.is_available()`.

### C — Dokumentaatio

- README + [MULTI_DATABANK_TOTEUTUS.md](MULTI_DATABANK_TOTEUTUS.md): **“Raskas ingest: host + GPU”** -osio, `volume inspect`, esimerkkikomennot.
- Valinnainen: `scripts/ingest_host_gpu.sh` joka lukee volyymin ja asettaa `ZT_DATA_DIR`.

### D — MCP / Podman (GPU-liput)

- **Oletus:** ei muutosta — sama CPU-image ja `mcp.json` kuin nyt.
- **Valinnainen:** `create-mcp-agent … --podman-gpu amd` lisää MCP-merkintään ja sync/ingest/coverage-Podman-ajoihin liput  
  `--device /dev/kfd`, `--device /dev/dri`, `--group-add video`, `--group-add render`  
  (`devworkflow/zt_rag/podman_gpu.py`, `mcp_provision`, `podman_zt_cli`).
- **Huom:** oletus-`Dockerfile` asentaa **CPU-torchin**; GPU-käyttö kontissa vaatii **ROCm-PyTorch-imagen** (tai vastaavan) — liput yksin eivät riitä.

---

## 5. Työmäärä (hybridi)

| Osio | Arvio |
|------|--------|
| ROCm + venv hostilla (kerran) | 0.5–2 pv |
| Koodi (`ZT_TORCH_DEVICE`, batch) | ~0.5 pv |
| Dokumentaatio + volyymi-polku | ~0.25 pv |
| **Yhteensä** | **n. 1–3 pv** (vähemmän kuin täysi Podman-ROCm -ketju) |

---

## 6. Riskit ja käytäntö

- **Oikeudet:** host-käyttäjän täytyy voida **kirjoittaa** volyymin `Mountpoint`-hakemistoon (rootless Podman: usein omistajuus ok).
- **Rinnakkaisuus:** älä sekoita kahta ingest-prosessia samaan `ZT_DATA_DIR`:iin.
- **Versiot:** hostin `torch` / `sentence-transformers` / `numpy` — pyri **lähelle** kontissa olevia versioita, jotta indeksin binäärit pysyvät yhteensopivina.

---

## 7. Tarkistuslista (hybridi go-live)

- [ ] `rocm-smi` / `torch.cuda.is_available()` hostilla  
- [ ] `podman volume inspect …` → `ZT_DATA_DIR` asetettu  
- [ ] `zt_cli ingest` hostilla päättyy ok  
- [ ] `zt_cli coverage` ok  
- [ ] MCP (CPU) käynnissä; **reload**; `zt_query` löytää uuden sisällön  

---

## Liite A — Täysi Podman + ROCm (valinnainen, ei valittu oletukseksi)

Jos myöhemmin haluat **ingestinkin kontissa GPU:lla** (CI, identtinen ympäristö):

- Erottele image: `localhost/datapankki-mcp:rocm`
- Podman: `--device /dev/kfd`, `--device /dev/dri`, ryhmät `video` / `render`
- **Toteutettu:** `mcp_provision` / `podman_zt_cli` + `create-mcp-agent --podman-gpu amd`.

Tämä on **enemmän ylläpitoa** kuin pelkkä hybridi; käytä kun haluat ingestin tai MCP:n **samassa ROCm-kontissa** kuin GPU.

---

---

## 8. Ingest-GPU -MCP (kontissa)

Erillinen MCP (`devworkflow.zt_ingest_mcp_server`, palvelinnimi `zt-rag-ingest-gpu`) tarjoaa vain **sync / ingest / coverage / status**. Rakenna **`Dockerfile.rocm`** → `localhost/datapankki-mcp:rocm`, aja Podmanissa **GPU-laitteilla**; käytä **samaa data-volyymia** kuin kysely-MCP:ssä. Esimerkkimerkinnät: **`zt_ingest_gpu_databank_ai_mcp.json`** (Databank AI + `zt-rag-data-databank-ai`), `zt_ingest_gpu_cursor_mcp.json` (muut pankit).

*Tämä dokumentti kuvaa **valitun** strategian: raskaat operaatiot hostilla GPU, MCP Podmanissa CPU; ingest-GPU -MCP on **vaihtoehto** kontissa-ajoon.*
