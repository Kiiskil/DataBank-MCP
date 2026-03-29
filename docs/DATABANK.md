# Databank-hakemisto (paikallinen)

Kansio **`Databank/`** repojuuressa on tarkoitettu EPUB/PDF-lähteille (esim. `Databank/AI/*.epub`).

- Se on **`.gitignore`issa** — sisältöä ei viedä Gitiin.
- Luo kansio ja kopioi kirjat paikallisesti, tai pidä aiemmin siirretty rakenne.

[`zt_cursor_mcp.json`](../zt_cursor_mcp.json) mountaa koko repojuuren **`/workspace`**:iin — silloin `zt_sync_sources` käyttää tyypillisesti **`/workspace/Databank/AI`**. [`zt_mcp_multibank.example.json`](../zt_mcp_multibank.example.json) -setupissa tietopankki on suoraan **`/zt/bank`** (esim. `${workspaceFolder}/Databank/AI`).

**Useita pankkeja, indeksin päivitys ja `create-mcp-agent`:** ks. [MULTI_DATABANK_TOTEUTUS.md](MULTI_DATABANK_TOTEUTUS.md).
