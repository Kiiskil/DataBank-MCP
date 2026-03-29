#!/usr/bin/env python3
"""
ZT-RAG MCP-palvelin: yksi instanssi = yksi tietopankki.
Työkalut: zt_sync_sources, zt_list_ingestible, zt_ingest, zt_verify_coverage, zt_query, zt_status

Raskas cli_runner ladataan vasta työkalukutsussa (ei import-vaiheessa), jotta
tools/list ja Cursorin käyttöliittymä saavat vastauksen nopeasti. Cursorin
lokissa esiintyvä "listOfferingsForUI" ei ole MCP-palvelimen toteutettava
metodi — se on IDE:n sisäinen kutsu, joka käyttää tools/list -vastetta.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))
if Path("/app").exists() and "/app" not in sys.path:
    sys.path.insert(0, "/app")

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print("pip install mcp", file=sys.stderr)
    sys.exit(1)

from devworkflow.zt_rag.storage_layout import StoragePaths
from devworkflow.zt_mcp_tools import call_tool as zt_call_tool
from devworkflow.zt_mcp_tools import list_tools as zt_list_tools

server = Server("zt-rag")


def _cli_runner():
    from devworkflow.zt_rag import cli_runner as cr

    return cr


def _paths() -> StoragePaths:
    p = StoragePaths.create()
    p.ensure()
    return p


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return zt_list_tools(include_query=True)


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    cr = _cli_runner()
    paths = _paths()
    return zt_call_tool(name, arguments, cr=cr, paths=paths, allow_query=True)


def _bootstrap_sync_from_env() -> None:
    """Valinnainen: ZT_BOOTSTRAP_SYNC_PATHS=/polku tai /a,/b (pilkulla)."""
    raw = os.environ.get("ZT_BOOTSTRAP_SYNC_PATHS", "").strip()
    if not raw:
        return
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return
    paths = _paths()
    cr = _cli_runner()
    out = cr.run_sync_sources(paths, parts)
    if not out.get("ok"):
        print(json.dumps(out, ensure_ascii=False), file=sys.stderr)
        return
    print(
        f"[zt-rag] bootstrap sync: {out.get('count', 0)} lähdettä, polut: {parts}",
        file=sys.stderr,
    )


async def main() -> None:
    _bootstrap_sync_from_env()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
