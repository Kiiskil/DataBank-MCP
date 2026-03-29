# ZT-RAG MCP — ohje **agenteille ja kielimalleille** (Cursor, Claude, …)

Tämä koskee työkaluja **`zt_query`**, **`zt_status`**, **`zt_sync_sources`**, **`zt_ingest`**, **`zt_verify_coverage`**.

## 1. Sinulla ei ole oletuksena “mitä kirjoja pankissa on”

- Tietopankki (`Databank/…`) ei ole tässä Git-repossa; sisältö riippuu **käyttäjän** koneesta ja ingestistä.
- **Älä oleta** tiettyjä teoksia, ellei käyttäjä tai workspace kerro niitä.

**Mitä voit tehdä:**

- **`zt_status`**: julkaistu indeksi → **`published_meta.sources`** ja polut (kun indeksi on rakennettu).
- **`zt_list_ingestible`**: mitä **levyllä** on ingestoitavissa (EPUB/PDF/MD), **ei** manifest-kirjoitusta; sama hakemistoskannaus kuin `zt_sync_sources`. Tyhjä `source_paths` + ympäristö **`ZT_DEFAULT_SYNC_PATHS`** = oletusjuuret (esim. yksi hakemisto jossa sekä kirjat että repo-kansiot).
- **Työtila = `datapankki-mcp`:** voit **lukea** lähdetiedostoja suoraan polusta **`Databank/…`** (Read/Grep) — kansio on `.gitignore`-listalla mutta polku on silti käytettävissä, jos käyttäjän koneella on sisältöä.

## 2. Hyvä kysymys ilman korpustietoa

- Käytä **selkeitä, teknisiä** termejä ja **oikeita nimiä** (komennot, protokollat, työkalut), jotka todennäköisesti esiintyvät dokumentaatiossa.
- Jos kysymys on abstrakti, pilko se **useampaan konkreettiseen** kysymykseen tai toista sama idea **eri sanoin** (synonyymit, englanti/suomi).
- Jos vastaus on “Ei löydy lähteistäni” tai **sitaattivahvistus epäonnistuu**, kysymys voi olla **väärällä sanastolla** suhteessa indeksoituun tekstiin — **muotoile uudelleen** lähemmäs tiedostopoluista pääteltävää aihetta (esim. vim → `:wq`, `:q!`, Ansible → *playbook*, *module*).

## 3. Löydettävyys vs. ylläpito (tärkeä erottelu)

**Agentin keinot** (ei vaadi koneen konfiguraatiota):

- Uudelleenmuotoiltu kysymys, useampi kysymys, tarkistus `zt_status`-poluista.

**Käyttäjän / ylläpidon keinot** (kun korpus on sama mutta osumat jäävät heikoiksi):

- **`ZT_ENABLE_QUERY_FALLBACK=1`** (ja valinnainen **`ZT_ENABLE_CORPUS_AWARE_REWRITE=1`**): automaattinen toinen hakuyritys leveämmällä profiililla ja korpus-pohjaisilla termivinkeillä, jos ensimmäinen haku on heikko — ks. [PERF_ENV.md](PERF_ENV.md).
- MCP-kontin tai hostin **muut ympäristömuuttujat**: laajempi haku, HyDE, isompi kandidaattipooli — ks. [PERF_ENV.md](PERF_ENV.md) ja `devworkflow/zt_rag/query_hard_profile.py`.
- Testierät: `mcp_query_batch --hard` ja `run_query_batch_hard_all.sh` (kehitys / regressio).
- **Kysymyslistojen rikastaminen** vastaamaan **oikeiden kirjojen** termistöä (esim. O’Reilly-vim → eksplisiittiset komennot), koska agentti **ei tiedä** sisäistä termistöä ilman `zt_status`-polkuja tai käyttäjän kuvausta.

→ Agentille: jos useat uudelleenmuotoilut eivät auta, **kerro käyttäjälle** että indeksi/kyselyprofiili tai kysymyksen sanasto saattaa vaatia **ylläpidon säätöä** (viittaa tähän tiedostoon ja `PERF_ENV.md`:hen).

## 4. Lyhyt työkalumuistio

| Työkalu | Käyttö |
|---------|--------|
| `zt_status` | Indeksin tila + `published_meta` → lähteiden polut |
| `zt_list_ingestible` | Levy-skannaus: ingestoitavat tiedostot (ei manifest-muutosta) |
| `zt_query` | Kysymys → haku + vastaus + sitaatit |
| `zt_verify_coverage` | Manifest vs. julkaistu indeksi |
| `zt_sync_sources` / `zt_ingest` | Manifest + indeksi (ylläpito; ei pakollinen pelkkään lukukyselyyn) |

Ingest-GPU -MCP:ssä **`zt_query` ei ole käytössä**; kyselyt varsinaisen kysely-MCP:n kautta.

## 5. Liittyvät dokumentit

- [MULTI_DATABANK_TOTEUTUS.md](MULTI_DATABANK_TOTEUTUS.md) — useita pankkeja / volyymeja  
- [PERF_ENV.md](PERF_ENV.md) — kysely- ja hakusäätö  
- [PODMAN_REBUILD.md](PODMAN_REBUILD.md) — imaget ja volyymit  

---

*Päivitä tätä ohjetta, jos työkalujen vastausmuoto tai status-kentät muuttuvat.*
