# Agentit (Cursor / MCP)

**ZT-RAG / Databank MCP** — lue ennen `zt_query` -käyttöä:

- **[docs/ZT_QUERY_BEST_PRACTICES.md](docs/ZT_QUERY_BEST_PRACTICES.md)** — hakutarkkuus: kysymyksen muotoilu, putki, fallback, mittaus.
- **[docs/MCP_AGENT_OHJE.md](docs/MCP_AGENT_OHJE.md)** — korpustieto puuttuu oletuksena; `zt_status` + työkalumuistio; milloin ylläpito säätää `query_hard_profile` / `PERF_ENV`.
- **[docs/INGEST_EPUB.md](docs/INGEST_EPUB.md)** — EPUB-ingest (spine, nav, otsikkopolku); re-ingest `force_rebuild`.
- **[docs/ZT-RETRIEVE-JSON.md](docs/ZT-RETRIEVE-JSON.md)** — cli-bot retrieve-only (`zt_cli retrieve --json`), ei `zt_query`.
- **[docs/CLI_BOT_DATABANK.md](docs/CLI_BOT_DATABANK.md)** — export, verify, smoke, checksum.

**Lähteet samassa työtilassa:** jos avaat repojuurena `datapankki-mcp`, voit lukea raakatekstin polusta `Databank/<pankki>/` (esim. `Databank/AI/`) Cursorin Read/Grep-työkaluilla — sinne voi laittaa EPUBien lisäksi kloonatun repo-kansion. MCP:ssä `zt_list_ingestible` listaa ingestoitavat tiedostot (sama skannaus kuin `zt_sync_sources`, ei manifest-kirjoitusta). Tyhjät `source_paths` käyttävät `ZT_DEFAULT_SYNC_PATHS` (pilkuilla erotetut absoluuttiset polut, esim. mountattu pankki kontissa).

Muu repo:

- [README.md](README.md) — build, MCP, CLI  
- [docs/MULTI_DATABANK_TOTEUTUS.md](docs/MULTI_DATABANK_TOTEUTUS.md)  
