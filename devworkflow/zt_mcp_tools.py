"""
Jaettu ZT-RAG MCP -työkalumäärittely ja suoritus (kysely + ingest).
Raskaat importit vain työkalukutsussa (cli_runner).
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

from mcp import types

from devworkflow.zt_rag.storage_layout import StoragePaths


@contextmanager
def _cursor_mcp_query_source() -> Iterator[None]:
    key = "ZT_QUERY_LOG_SOURCE"
    prev = os.environ.get(key)
    os.environ[key] = "cursor_mcp"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev


def list_tools(*, include_query: bool) -> list[types.Tool]:
    tools: list[types.Tool] = [
        types.Tool(
            name="zt_sync_sources",
            description=(
                "Lisää/päivittää lähdetiedostot manifestiin (EPUB/PDF/Markdown). "
                "Hakemisto skannataan *.epub, *.pdf, *.md ja *.markdown (.git ym. ohitetaan). "
                "Tyhjä source_paths: käytä ZT_DEFAULT_SYNC_PATHS (pilkuilla erotetut juurihakemistot), "
                "esim. yksi polku johon EPUB-kirjat ja kloonatut repo-kansiot on kopioitu."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": (
                            "Tiedostot tai hakemistot. Tyhjä taulukko + ZT_DEFAULT_SYNC_PATHS → oletusskannaus."
                        ),
                    },
                },
            },
        ),
        types.Tool(
            name="zt_list_ingestible",
            description=(
                "Listaa levyllä olevat ingestoitavat tiedostot (sama logiikka kuin sync), "
                "ei kirjoita manifestiin. Käytä kun haluat nähdä mitä hakemistossa on ennen sync/ingest. "
                "Tyhjä source_paths + ZT_DEFAULT_SYNC_PATHS kuten zt_sync_sources."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "Skannattavat juuret; tyhjä + ZT_DEFAULT_SYNC_PATHS.",
                    },
                },
            },
        ),
        types.Tool(
            name="zt_ingest",
            description="Parsii lähteet, chunkkaa, rakentaa BM25+vektori-indeksin ja julkaisee atomisesti.",
            inputSchema={
                "type": "object",
                "properties": {
                    "force_rebuild": {
                        "type": "boolean",
                        "default": False,
                        "description": "Pakota uudelleenparsinta",
                    },
                },
            },
        ),
        types.Tool(
            name="zt_verify_coverage",
            description="Tarkista että kaikki aktiiviset lähteet on indeksoitu ja hashit täsmäävät julkaistuun indeksiin.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="zt_status",
            description=(
                "Näyttää manifestin ja julkaistun indeksin tilan. "
                "Julkaistut polut: published_meta.sources. "
                "Levy-skannaus ilman manifestia: zt_list_ingestible. "
                "Jos työtila on sama datapankki-repo, raakateksti luettavissa polusta Databank/… (Read-työkalu)."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
    if include_query:
        tools.append(
            types.Tool(
                name="zt_query",
                description=(
                    "Hybridihaku + JSON-vastaus + sitaattiverifiointi (+ valinnainen NLI). "
                    "Jos vastaus heikko tai 'ei löydy lähteistä', muotoile kysymys uudelleen konkreettisemmiksi "
                    "(työkalu- ja protokollanimet kuten kirjassa). Korpuksen nimistä: zt_status / zt_list_ingestible; "
                    "tiedoston sisältöön workspace-datapankissa Databank/… Read-työkalulla. "
                    "Ylläpito: HyDE, top_k — docs/MCP_AGENT_OHJE.md ja PERF_ENV.md."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "model": {
                            "type": "string",
                            "description": "Anthropic-malli (oletus Sonnet)",
                        },
                    },
                    "required": ["question"],
                },
            ),
        )
    return tools


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    cr: Any,
    paths: StoragePaths,
    allow_query: bool,
) -> list[types.TextContent]:
    if name == "zt_sync_sources":
        raw_paths = arguments.get("source_paths") or []
        out = cr.run_sync_sources(paths, [str(x) for x in raw_paths])
        return [types.TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]

    if name == "zt_list_ingestible":
        raw_paths = arguments.get("source_paths") or []
        out = cr.run_list_ingestible(paths, [str(x) for x in raw_paths])
        return [types.TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]

    if name == "zt_ingest":
        force = bool(arguments.get("force_rebuild", False))
        out = cr.run_ingest(paths, force_rebuild=force)
        return [types.TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]

    if name == "zt_verify_coverage":
        out = cr.run_verify_coverage(paths)
        return [types.TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]

    if name == "zt_status":
        out = cr.run_status(paths)
        return [types.TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]

    if name == "zt_query":
        if not allow_query:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "ok": False,
                            "error": "zt_query ei ole käytössä ingest-GPU -MCP:ssä; käytä varsinaista zt-rag -MCP:tä.",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            ]
        question = str(arguments.get("question", ""))
        if not question.strip():
            return [types.TextContent(type="text", text="Virhe: tyhjä kysymys")]
        model = arguments.get("model")
        with _cursor_mcp_query_source():
            out = cr.run_query(paths, question, model=model)
        return [types.TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=2))]

    return [types.TextContent(type="text", text=f"Tuntematon työkalu: {name}")]
