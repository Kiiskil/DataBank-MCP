# Julkaisu (GHCR) ja ingest-profiilit

Tämä dokumentti täydentää suunnitelmaa `docs/superpowers/plans/2026-03-29-julkaisukunto-ja-ingest-profiilit.md`.

**Julkinen repo:** [github.com/Kiiskil/DataBank-MCP](https://github.com/Kiiskil/DataBank-MCP)  
**GHCR-image (workflowin tuottama nimi, pienet kirjaimet):** `ghcr.io/kiiskil/databank-mcp`

## GitHub Container Registry (GHCR)

Kun repoon työnnetään **git-tag** muodossa `vX.Y.Z` (esim. `v0.1.0`), workflow [`.github/workflows/publish-container.yml`](../.github/workflows/publish-container.yml) rakentaa ja työntää:

| Variantti | Dockerfile      | Esimerkkitagit (yksi release)                          |
|-----------|-----------------|--------------------------------------------------------|
| CPU       | `Dockerfile`    | `0.1.0`, `cpu`, `latest`                               |
| ROCm/AMD  | `Dockerfile.rocm` | `0.1.0-rocm`, `rocm`                                 |

Image-polku GitHub Actionsissa: **`ghcr.io/${GITHUB_REPOSITORY,,}`** eli tässä repossa **`ghcr.io/kiiskil/databank-mcp`**.  
Muissa repoissa: `ghcr.io/<omistaja pienillä>/<reponimi pienillä>`.

### Ensimmäinen käyttöönotto

1. Julkaise koodi GitHubiin (ks. alla [Ensimmäinen push ilman vanhaa historiaa](#ensimmäinen-push-ilman-vanhaa-historiaa) tarvittaessa).
2. Varmista että repon **Actions** ja **Packages** ovat sallittuja (oletus julkiselle repolle).
3. Luo tag ja työnnä se:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Odota workflowin valmistumista; tarkista **Packages** / **Actions**.
5. Vedä image (kirjaudu GHCR:ään tarvittaessa, jos paketti on yksityinen):
   ```bash
   podman pull ghcr.io/kiiskil/databank-mcp:cpu
   podman pull ghcr.io/kiiskil/databank-mcp:rocm
   ```

Yksityinen paketti: `podman login ghcr.io` (GitHub **PAT** + `read:packages` / `write:packages` tarvittaessa).

### Versiotiedosto

Juuren [`VERSION`](../VERSION) on inhimillinen semver-muistio; julkaisutunnisteena käytetään **git-tagia** (`v*`). Pidä `VERSION` ja tagi linjassa (esim. molemmat `0.1.0`).

---

## Ensimmäinen push ilman vanhaa historiaa

Jos haluat GitHubiin **yhden commitin** eikä koko paikallista historiaa näkyviin, tee tämä **ennen ensimmäistä pushia** uuteen remoteen (tai kun olet valmis korvaamaan remoten historian).

**Varoitus:** Jos remoteen on jo työnnetty historiaa tai muilla on clone, älä käytä `--force` ilman että kaikki ovat valmiita uuteen historiaan.

```bash
git status   # työpuu puhtaaksi

git checkout --orphan __initial_public__
git add -A
git commit -m "Initial public release"

# Jos olet haarassa main ja haluat säilyttää nimen main:
git branch -D main
git branch -m main

git remote add origin https://github.com/Kiiskil/DataBank-MCP.git   # jos remote puuttuu
git push -u origin main
```

Jos `origin` on jo olemassa mutta **tyhjä**, yleensä riittää `git push -u origin main`.  
Jos remote sisälsi jo vanhan historian ja haluat **korvata** sen tällä yhdellä commitilla:

```bash
git push --force-with-lease origin main
```

`--force-with-lease` on turvallisempi kuin pelkkä `--force`: se epäonnistuu, joku muu on työntänyt väliin.

---

## Ingest-profiilit (CPU / AMD / NVIDIA)

Usean ingest-MCP-merkinnän generointi, CUDA-image ja `create-mcp-agent --ingest-profiles` on kuvattu suunnitelmadokumentissa; tämä tiedosto päivitetään kun ne on toteutettu.

Nykytila:

- **CPU:** `Dockerfile` → tagit `cpu`, `latest`, semver.
- **AMD:** `Dockerfile.rocm` → tagit `rocm`, semver `-rocm` -suffixilla.
- **NVIDIA:** suunnitteilla (`Dockerfile.cuda` + Podman NVIDIA -profiili).

---

## Linkit

- [README](../README.md) — paikallinen build ja käyttö
- [PODMAN_AMD_GPU_SUUNNITELMA](PODMAN_AMD_GPU_SUUNNITELMA.md)
- [PODMAN_REBUILD](PODMAN_REBUILD.md)
