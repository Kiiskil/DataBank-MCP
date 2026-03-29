#!/usr/bin/env python3
"""
ZT-RAG ingest-MCP (ei zt_query): sync, list ingestible, ingest, coverage, status.

Tarkoitettu ajettavaksi ROCm/GPU-kontissa (ks. Dockerfile.rocm) tai hostilla
GPU-torchilla. Sama ZT_DATA_DIR / volyymi kuin varsinaisessa zt-rag -MCP:ssä,
jotta indeksi on jaettu.

Ei vaadi ANTHROPIC_API_KEY:ia työkaluihin; voit jättää sen pois mcp.json:sta.
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

server = Server("zt-rag-ingest-gpu")


def _cli_runner():
    from devworkflow.zt_rag import cli_runner as cr

    return cr


def _paths() -> StoragePaths:
    p = StoragePaths.create()
    p.ensure()
    return p


def _log_torch_device_hint() -> None:
    """Yksi stderr-rivi käynnistyksessä (ei raskaita importteja ennen työkalua)."""
    dev = os.environ.get("ZT_TORCH_DEVICE", "auto").strip() or "auto"
    req = os.environ.get("ZT_INGEST_REQUIRE_CUDA", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    extra = " ZT_INGEST_REQUIRE_CUDA=1" if req else ""
    print(
        f"[zt-rag-ingest-gpu] ZT_TORCH_DEVICE={dev!r}{extra} "
        "(laite tarkistuu ensimmäisellä ingest/encode -kutsulla)",
        file=sys.stderr,
    )


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return zt_list_tools(include_query=False)


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    cr = _cli_runner()
    paths = _paths()
    return zt_call_tool(name, arguments, cr=cr, paths=paths, allow_query=False)


def _bootstrap_sync_from_env() -> None:
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
        f"[zt-rag-ingest-gpu] bootstrap sync: {out.get('count', 0)} lähdettä, polut: {parts}",
        file=sys.stderr,
    )


async def main() -> None:
    _log_torch_device_hint()
    _bootstrap_sync_from_env()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
