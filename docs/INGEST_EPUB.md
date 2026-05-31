# EPUB-ingest (ZT-RAG)

Tämä kuvaa [`devworkflow/zt_rag/parsers.py`](../devworkflow/zt_rag/parsers.py) EPUB-käsittelyn ingest-vaiheessa. Sama koodi MCP:ssä (`zt_ingest`, ingest-GPU-MCP) ja CLI:ssa.

## Mitä parseri tekee

| Vaihe | Kuvaus |
|--------|--------|
| **Spine-järjestys** | Lukujärjestys `book.spine` -listasta, ei satunnaista `get_items()`-järjestystä. Tyhjä spine → fallback manifestiin. |
| **Nav / TOC / cover** | Ohitetaan: manifest `nav`, tiedostonimi (`nav`, `toc`, `cover`, `ncx`), tai lyhyt linkki-painotteinen body. Raportti: `quality.skipped_items`. |
| **linear="no"** | Ohitetaan oletuksena (cover jne.). Sisällytä: `ZT_EPUB_INCLUDE_NONLINEAR=1`. |
| **Otsikkopolku** | h1–h6-pino spine-yli; chunk-tekstiin: `Kirjan otsikko > Osio > Alaosio` + `## lehtiotsikko`. |
| **Kieli** | DC `language` → `ParsedDocument.lang`; `<html lang>` tai item-kieli osiossa. |
| **HTML → Markdown** | `markdownify` (ATX-otsikot); virhe/tyhjä → `get_text`-fallback. |

Chunk-metat: `ChunkRecord.section` (polku), `heading_path`, `lang`. Indeksointi käyttää **chunk-tekstiä** (polku mukana) BM25:ssä ja embeddingeissä.

## Ylläpito: uudelleenindeksointi

Parserimuutokset muuttavat `chunk_hash`-arvoja. **Vanha indeksi ei ole semanttisesti yhteensopiva.**

1. `zt_sync_sources` (tai CLI `sync`) — päivitä manifesti.
2. `zt_ingest` **`force_rebuild: true`** — pakota parsinta + uusi julkaisu.
3. Toista **jokaiselle pankille** (AI, Software, Linux, Hacking), jos käytät useaa volyymiä.

GPU-ingest-MCP ajaa saman ingest-koodin; kyselyt vain varsinaisesta query-MCP:stä.

### Ympäristö

| Muuttuja | Kuvaus |
|----------|--------|
| `ZT_INGEST_PARSE_WORKERS` | Rinnakkaiset parse-prosessit (oletus `min(4, lähteitä)`). |
| `ZT_DISABLE_EMBED_CACHE` | `1` → ei inkrementaalista embedding-välimuistia. |
| `ZT_EPUB_INCLUDE_NONLINEAR` | `1` → spine `linear="no"` -sivut mukaan. |

## Rajoitteet

- EPUB3-landmarkit ja epätyypilliset nav-rakenteet voivat vaatia lisäheuristiikkoja.
- `ebooklib` voi kirjoituksen yhteydessä normalisoida `<html lang>` -arvoja; DC-kieli on luotettavin doc-tasolla.
- PDF ja Markdown käyttävät omaa polkuaan; vain `.epub` hyötyy spine/nav/MD-parannuksista.

## Testit

```bash
python -m unittest discover -s devworkflow/zt_rag/tests -p 'test_epub*.py'
```

## Liittyvät dokumentit

- [ZT_QUERY_BEST_PRACTICES.md](ZT_QUERY_BEST_PRACTICES.md) — hakutarkkuus ingestin jälkeen
- [MULTI_DATABANK_TOTEUTUS.md](MULTI_DATABANK_TOTEUTUS.md) — useita pankkeja
- [PERF_ENV.md](PERF_ENV.md) — ingest- ja kyselymuuttujat
