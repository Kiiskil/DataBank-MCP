# Julkaisukunto ja ingest-profiilit (kontti) — toteutussuunnitelma

> **Agenteille:** Toteutusta voi ajaa tehtävä kerrallaan; käytä tarvittaessa skilliä `superpowers:subagent-driven-development` tai `superpowers:executing-plans`. Ennen “valmis”-väitettä: `superpowers:verification-before-completion` (CI, smoke, manuaalinen pull).

**Tavoite:** Reposta julkaistaan **versionoidut container-imaget** (CPU / ROCm / CUDA), automaattinen build-push, lisenssi ja metadata; käyttäjä ottaa ZT-RAG:n käyttöön **ainoastaan kontissa**; **useita ingest-MCP-merkintöjä** (CPU vs AMD vs NVIDIA) voidaan generoida samaan data-volyymiin ilman manuaalista JSON-kopiointia.

**Arkkitehtuurin ydin:** Jakelu = imaget rekisterissä. GPU ↔ CPU -vaihto ei ole yksi env-toggle yhdessä imagessa: **eri image-tagit** (torch-binääri) + **Podman-laitteet** (GPU-profiili). Runtime-valinta Cursorissa = **minkä MCP-palvelimen** käyttäjä pitää käytössä (tai viittaa työkaluun); sama `zt-rag-data-<slug>` ja sama tietopankkimount kaikille ingest-varianteille.

**Tekninen pinu:** Python 3.12, Podman (ensisijainen), Docker-yhteensopivat Dockerfilet, GitHub Actions → GHCR (tai vastaava), Cursor `mcp.json`, `devworkflow.zt_cli create-mcp-agent`, `devworkflow.zt_rag.mcp_provision`, `devworkflow.zt_rag.podman_gpu`.

**Liittyvät skillit:** `superpowers:writing-plans` (rakenne), `superpowers:brainstorming` (laajennukset ennen speksiä), `superpowers:verification-before-completion` (todisteet ennen mergeä).

**Nykytila (lähtökohta):** `Dockerfile` + `Dockerfile.rocm`; ei `LICENSE`-tiedostoa; ei `.github/workflows`; `DEFAULT_IMAGE` = `localhost/datapankki-mcp:latest` (`devworkflow/zt_rag/mcp_provision.py`); `PodmanGpuProfile` = `none` | `amd` (`devworkflow/zt_rag/podman_gpu.py`); NVIDIA-podman-argsit ja CUDA-Dockerfile puuttuvat.

---

## Tiedostokartta (luodaan / muokataan)

| Polku | Vastuu |
|-------|--------|
| `LICENSE` | Oikeudellinen minimi (valitse lisenssi projektin omistajan kanssa). |
| `VERSION` tai `git describe` injektio | Semver / build-tunniste labeleihin. |
| `Dockerfile` | CPU-image (nykyinen, mahdollinen tag-strategia-dokumentointi). |
| `Dockerfile.rocm` | AMD ROCm-image (nykyinen). |
| `Dockerfile.cuda` | **Uusi** — PyTorch CUDA-wheel, linjassa `requirements.txt`:n kanssa. |
| `.github/workflows/container-release.yml` (tai jaettu CI + release) | Build + push tagista; cache. |
| `.github/workflows/ci.yml` (valinnainen erillinen) | PR-buildit, kevyet testit. |
| `devworkflow/zt_rag/podman_gpu.py` | Profiili `nvidia` + argsit (CDI ensisijainen dokissa). |
| `devworkflow/zt_rag/mcp_provision.py` | Julkiset oletuskuvat (env tai vakiot); API usealle ingest-merkinnälle. |
| `devworkflow/zt_cli.py` | `--ingest-profiles`, `--image-cpu` / `--image-rocm` / `--image-cuda`. |
| `devworkflow/zt_rag/podman_zt_cli.py` | Preview + pipeline synkassa GPU-profiilien kanssa. |
| `tests/...` | `podman_gpu_run_args` -matriisi; tarvittaessa provision dry-run -JSON. |
| `docs/JULKAISU_JA_INGEST_PROFIILIT.md` (tämän suunnitelman käyttöohje) | Käyttäjän happy path, tagit, NVIDIA vs AMD. |
| `README.md` | Linkki julkaisuohjeeseen; oletusimaget → GHCR kun valmis. |
| `docs/PODMAN_AMD_GPU_SUUNNITELMA.md` | Päivitys: rinnalle NVIDIA-viittaus uuteen doksiin. |
| Esimerkki-JSONit (valinnainen) | `zt_ingest_*_mcp.json` -tyyliin CPU+GPU -mallit. |

---

## Vaihe A: Julkaisurunko (MVP)

### Task A1: Lisenssi ja versiotunniste

**Files:**
- Create: `LICENSE`
- Create: `VERSION` (sisältö esim. `0.1.0`) tai päätös käyttää vain `git describe` CI:ssä

- [x] Valitse lisenssi (esim. MIT tai Apache-2.0) ja lisää täysi `LICENSE`-teksti. *(Tehty: MIT.)*
- [x] Päätä version lähde: staattinen `VERSION` + CI injektoi `IMAGE_VERSION` build-argina **tai** pelkkä tag `vX.Y.Z` → label `org.opencontainers.image.version`. *(Tehty: `VERSION` + `github.ref_name` workflowissa.)*
- [x] Dokumentoi README:hen yksi rivi: “Lisenssi: katso `LICENSE`.” *(Tehty: README-lisenssikappale.)*

### Task A2: OCI-labelit CPU-Dockerfilessa

**Files:**
- Modify: `Dockerfile`

- [x] Lisää `ARG` / `LABEL`: `org.opencontainers.image.source`, `revision` (build-arg `GIT_REVISION`), `version`.
- [x] Varmista että `ENTRYPOINT` pysyy ennallaan (`devworkflow.zt_mcp_server`). *(Sama myös `Dockerfile.rocm`.)*

### Task A3: GitHub Actions — build + push CPU (GHCR)

**Files:**
- Create: `.github/workflows/container-release.yml` (tai `publish-container.yml`)

- [x] Workflow: trigger `push` tags `v*`. *(Tiedosto: `.github/workflows/publish-container.yml` — CPU + ROCm.)*
- [x] Kirjaudu GHCR:ään `GITHUB_TOKEN`illa (oikeudet paketille).
- [x] Build `Dockerfile` → push `ghcr.io/<org>/datapankki-mcp:<semver>` ja `:cpu` tai `:latest` (dokumentoi strategia).
- [x] Dokumentoi `docs/JULKAISU_JA_INGEST_PROFIILIT.md`: `podman pull` + esimerkkikomento.

### Task A4: Julkaisuprosessi (inhimillinen checklist)

**Files:**
- Modify: `docs/JULKAISU_JA_INGEST_PROFIILIT.md`

- [x] Kirjoita: miten luodaan git tag, miten Release-muistiinpano kirjoitetaan, miten varmistetaan imagen digest. *(Tag + GHCR + ensimmäinen push / historian litistys dokumentoitu.)*

---

## Vaihe B: Imagematriisi (ROCm + CUDA)

### Task B1: ROCm-image CI:ssä

**Files:**
- Modify: `.github/workflows/container-release.yml`
- Modify: `Dockerfile.rocm` (labelit kuten CPU)

- [ ] Lisää job tai matrix-solu: build `Dockerfile.rocm` → push `…:X.Y.Z-rocm` (tai sovittu tagi).
- [ ] Dokumentoi `TORCH_INDEX_URL` / host-ajuriyhteensopivuus (viittaus `docs/PODMAN_AMD_GPU_SUUNNITELMA.md`).

### Task B2: CUDA-Dockerfile

**Files:**
- Create: `Dockerfile.cuda`

- [ ] Perusta: `python:3.12-slim` + CUDA-PyTorch pip-indeksistä (esim. cu121 — **päätä yksi oletuslinja** ja dokumentoi minimi-NVIDIA-ajuri).
- [ ] Sama `COPY devworkflow` ja riippuvuudet kuin `Dockerfile`:ssa.
- [ ] Lisää OCI-labelit.

### Task B3: CUDA-image CI:ssä

**Files:**
- Modify: `.github/workflows/container-release.yml`

- [ ] Push `…:X.Y.Z-cuda12` (tai valittu tagi).
- [ ] Jos build-aika liian pitkä: erillinen workflow “nightly full matrix” tai cache-from.

---

## Vaihe C: Ingest-profiilit ja MCP-generointi

### Task C1: `podman_gpu` — NVIDIA

**Files:**
- Modify: `devworkflow/zt_rag/podman_gpu.py`
- Create tai modify: `tests/...` (esim. `tests/test_podman_gpu.py`)

- [ ] Laajenna `PodmanGpuProfile`: `"none" | "amd" | "nvidia"`.
- [ ] Toteuta `podman_gpu_run_args("nvidia")`: **ensisijainen** Podman CDI `--device nvidia.com/gpu=all`; dokumentoi Docker `--gpus all` vaihtoehtona.
- [ ] **TDD:** kirjoita testit jotka assertoivat palautuvat arg-listat (ei tarvitse oikeaa GPU:ta).

### Task C2: `mcp_provision` — useita ingest-merkintöjä

**Files:**
- Modify: `devworkflow/zt_rag/mcp_provision.py`

- [ ] Pidä `build_mcp_server_entry` yhtenä totuuden lähteenä `(image, podman_gpu, extra_env)`.
- [ ] Lisää funktio tyyliin `provision_ingest_variants(...)` joka palauttaa listan `(server_key, entry)`:
  - Sama `slug`, sama `data_volume_name`, sama mount; eri `image`, eri `podman_gpu`, tarvittaessa `-e ZT_TORCH_DEVICE=…` ingest-entryssä.
- [ ] MCP-avainten nimet deterministisesti, esim. `"<name> ingest (CPU)"`, `"<name> ingest (GPU AMD)"`, `"<name> ingest (GPU NVIDIA)"`.

### Task C3: `create-mcp-agent` CLI

**Files:**
- Modify: `devworkflow/zt_cli.py`
- Modify: `devworkflow/zt_rag/podman_zt_cli.py` (preview + pipeline GPU-profiileille)

- [ ] Lisää `--ingest-profiles` (csv: `cpu`, `amd`, `nvidia`) — vähintään yksi profiili.
- [ ] Lisää `--image-cpu`, `--image-rocm`, `--image-cuda` (oletukset: GHCR-tagit dokumentaation mukaan).
- [ ] **Taaksepäin yhteensopivuus:** nykyinen `--podman-gpu amd` + yksi merkintä mapataan uuteen malliin tai säilytetään rinnalla yhden ajaksi (dokumentoi deprekoitu polku).
- [ ] `--dry-run` tulostaa kaikkien varianttien `args` + imaget JSONissa.

### Task C4: Virheviestit ja status

**Files:**
- Modify: `devworkflow/zt_rag/cli_runner.py` (tai ingest-polku jossa `ZT_INGEST_REQUIRE_CUDA`)

- [ ] Kun GPU puuttuu, viesti ei saa viitata vain ROCm:iin; mainitse image + Podman-laitteet.

- [ ] (Valinnainen) Näytä build-version `zt_status`-vastauksessa — lue label tai `VERSION` tiedostosta buildissa.

---

## Vaihe D: CI laatu, dokumentaatio, turva

### Task D1: PR-CI (kevyt)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] `pytest` osajoukko ilman raskaita integraatioita (tarkista `tests/conftest.py` ja stub-envit).
- [ ] `docker build` CPU vain PR:ssä (valinnainen jos runner kestää).

### Task D2: Käyttödokumentti

**Files:**
- Create: `docs/JULKAISU_JA_INGEST_PROFIILIT.md`
- Modify: `README.md`
- Modify: `docs/PODMAN_AMD_GPU_SUUNNITELMA.md` (linkki NVIDIA-ohjeeseen)

- [ ] Happy path: pull kolme tagia, ensimmäinen ingest, kysely-MCP.
- [ ] Taulukko: profiili → image → Podman-liput → tyypillinen virhe.
- [ ] Cursor: kaksi tai kolme ingest-palvelinta — käytä vain yhtä kerrallaan tai tarkoituksella oikeaa @-viittausta.

### Task D3: Dependabot / SECURITY

**Files:**
- Create: `.github/dependabot.yml` (pip + actions)
- Create: `SECURITY.md` (yhteystapa)

---

## Hyväksymiskriteerit (Definition of Done)

- [ ] Tag `vX.Y.Z` tuottaa rekisteriin **vähintään** CPU- ja ROCm-imaget; CUDA mukana tai eksplisiittisesti merkitty “seuraavaan iteraatioon”.
- [ ] Uusi käyttäjä pystyy `podman pull` + `podman run` + volyymi -ketjulla käyttämään CLI:tä ilman paikallista `pip install` -pinoa.
- [ ] `create-mcp-agent --ingest-profiles cpu,amd` (ja tarvittaessa `nvidia`) kirjoittaa `mcp.json`:iin eri avaimet, **sama volyymi**.
- [ ] Repossa on `LICENSE`; julkaisudokumentti ja README linkitetty.
- [ ] CI vihreä mainissa (tai dokumentoitu poikkeus).

---

## Riskit ja päätökset ennen koodausta

1. **NVIDIA + Podman**: ympäristö vaihtelee; valitse **yksi referenssiasennus** (esim. Fedora + CDI) ja mainitse Docker-vaihtoehto.
2. **CUDA vs host-ajuri**: dokumentoi minimi-ajuri; yksi oletus-CUDA-tag (esim. 12.1) vähentää tukeutumista.
3. **CI-aika**: kolme täyttä imagea — käytä cachea tai erota ROCm/CUDA release-workflowiin.
4. **`--force` create-mcp-agentissa**: määrittele korvaavatko uudet ajot kaikki kolme avainta vai vain samat avaimet.

---

## Toteutuksen jälkeen (skillit)

Suunnitelman tallennuspaikka: `docs/superpowers/plans/2026-03-29-julkaisukunto-ja-ingest-profiilit.md`.

**Toteutusvaihtoehdot:**

1. **Subagent-driven** — `superpowers:subagent-driven-development`: yksi agentti per Task, tarkistus välissä.
2. **Inline** — `superpowers:executing-plans`: erät ja ihmisen checkpointit samassa sessiossa.

Ennen mergeä ja julkaisua: **todisteet** testeistä ja/tai manuaalisesta `podman pull` -smokesta (`superpowers:verification-before-completion`).
