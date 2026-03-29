"""
Vaikeiden / abstraktien kysymysten hakuprofiili: leveämpi pooli, HyDE, isompi ANN-ef.

Käyttö: ``mcp_query_batch --hard`` asettaa nämä kontissa (yliajaa tyhjät host-arvot).
Voit yliajaa yksittäisiä arvoja exportilla ennen ajoa.

Query-fallback käyttää ``hard_retrieval_profile_env()``-kontekstia: silloin
``QUERY_HARD_PROFILE_ENV`` yliajaa ``os.environ``-arvot (mukaan lukien ``ZT_ENABLE_HYDE=1``)
fallback-hakukierroksen ajaksi. Hostilla voi siis olla ``ZT_ENABLE_HYDE=0`` ensimmäisellä
kierroksella, mutta fallback pakottaa HyDE + leveän haun profiilin mukaan.
"""
from __future__ import annotations

# Merkitään lokiin / telemetriaan (cli_runner.run_query)
MARKER_KEY = "ZT_QUERY_HARD_RETRIEVAL"
MARKER_VAL = "1"

QUERY_HARD_PROFILE_ENV: dict[str, str] = {
    MARKER_KEY: MARKER_VAL,
    "ZT_ENABLE_HYDE": "1",
    "ZT_TOP_K_FUSION": "120",
    "ZT_MULTI_QUERY_K_PER": "48",
    "ZT_MULTI_QUERY_POOL": "96",
    "ZT_MULTI_QUERY_RRF_K": "80",
    "ZT_CONTEXT_CHUNKS": "14",
    "ZT_ANN_EF_SEARCH": "128",
}
