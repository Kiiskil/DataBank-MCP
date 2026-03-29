"""
Cursor / Podman -MCP-merkintöjen generointi: yksi merkintä = yksi agentti + oma data-volyymi.

Lähteet mountataan kontissa oletuksena polkuun /zt/bank (--source-mount).
Indeksi ja manifesti: ZT_DATA_DIR=/data → erillinen volyymi per agentti.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from devworkflow.zt_rag.podman_gpu import PodmanGpuProfile, podman_gpu_run_args

DEFAULT_IMAGE = "localhost/datapankki-mcp:latest"
DEFAULT_SOURCE_MOUNT = "/zt/bank"
VOLUME_PREFIX = "zt-rag-data"


def slugify_agent_name(name: str, *, max_len: int = 48) -> str:
    """Turvallinen tunniste Podman-volyymille ja MCP-avaimelle."""
    s = name.strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s:
        s = "agent"
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "agent"


def data_volume_name(slug: str, *, prefix: str = VOLUME_PREFIX) -> str:
    return f"{prefix}-{slug}"


def build_mcp_server_entry(
    *,
    databank_host_path: Path,
    slug: str,
    image: str = DEFAULT_IMAGE,
    source_mount: str = DEFAULT_SOURCE_MOUNT,
    volume_prefix: str = VOLUME_PREFIX,
    include_hf_token: bool = False,
    bootstrap_sync: bool = False,
    podman_gpu: PodmanGpuProfile = "none",
) -> dict[str, Any]:
    """
    Yksi Cursorin mcpServers-objektin arvo (podman run ...).

    bootstrap_sync: True → ZT_BOOTSTRAP_SYNC_PATHS (ajaa manifesti-päivityksen joka MCP-käynnistyksellä).
    """
    host = str(databank_host_path.resolve())
    vol = data_volume_name(slug, prefix=volume_prefix)
    args: list[str] = [
        "run",
        "--rm",
        "-i",
        *podman_gpu_run_args(podman_gpu),
        "-e",
        "ANTHROPIC_API_KEY",
        "-e",
        "ZT_DATA_DIR=/data",
    ]
    if bootstrap_sync:
        args.extend(["-e", f"ZT_BOOTSTRAP_SYNC_PATHS={source_mount}"])
    args.extend(
        [
            "-v",
            f"{host}:{source_mount}:ro,Z",
            "-v",
            f"{vol}:/data",
        ]
    )
    if include_hf_token:
        args.extend(["-e", "HF_TOKEN"])
    args.append(image)

    entry: dict[str, Any] = {
        "command": "podman",
        "args": args,
        "env": {"ANTHROPIC_API_KEY": "${env:ANTHROPIC_API_KEY}"},
    }
    if include_hf_token:
        entry["env"]["HF_TOKEN"] = "${env:HF_TOKEN}"
    return entry


def mcp_server_key(slug: str, *, prefix: str = "zt-rag") -> str:
    """Vain fallback kun --name on tyhjä; oletusavain on käyttäjän nimi."""
    return f"{prefix}-{slug}"


def load_mcp_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"mcpServers": {}}
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        raise ValueError(f"Ei kelvollista JSON-objektia: {path}")
    servers = data.get("mcpServers")
    if servers is None:
        data["mcpServers"] = {}
    elif not isinstance(data["mcpServers"], dict):
        raise ValueError(f"mcpServers ei ole objekti: {path}")
    return data


def merge_mcp_server(
    mcp: dict[str, Any],
    key: str,
    entry: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    servers: dict[str, Any] = mcp.setdefault("mcpServers", {})
    if key in servers and not force:
        raise FileExistsError(f"MCP-palvelin '{key}' on jo olemassa. Käytä --force korvatakseksi.")
    servers[key] = entry
    return mcp


def write_mcp_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def provision_agent(
    *,
    name: str,
    databank: Path,
    mcp_json_path: Path | None,
    image: str = DEFAULT_IMAGE,
    source_mount: str = DEFAULT_SOURCE_MOUNT,
    volume_prefix: str = VOLUME_PREFIX,
    server_key: str | None = None,
    force: bool = False,
    include_hf_token: bool = False,
    bootstrap_sync: bool = False,
    dry_run: bool = False,
    podman_gpu: PodmanGpuProfile = "none",
) -> dict[str, Any]:
    """
    Palauttaa raportin: server_key, slug, volume, entry, optional merged path.
    """
    db = databank.expanduser()
    if not db.exists():
        raise FileNotFoundError(f"Tietopankkia ei löydy: {db}")
    if not db.is_dir():
        raise NotADirectoryError(f"Tietopankin on oltava hakemisto (EPUB/PDF -puu): {db}")

    slug = slugify_agent_name(name)
    # Cursorin mcpServers-avain = käyttäjän antama nimi (jotta @/viittaus toimii samalla nimellä).
    key = (server_key or name.strip())
    if not key:
        key = mcp_server_key(slug)
    entry = build_mcp_server_entry(
        databank_host_path=db,
        slug=slug,
        image=image,
        source_mount=source_mount,
        volume_prefix=volume_prefix,
        include_hf_token=include_hf_token,
        bootstrap_sync=bootstrap_sync,
        podman_gpu=podman_gpu,
    )
    report: dict[str, Any] = {
        "server_key": key,
        "slug": slug,
        "data_volume": data_volume_name(slug, prefix=volume_prefix),
        "databank_host": str(db.resolve()),
        "source_mount_container": source_mount,
        "bootstrap_sync": bootstrap_sync,
        "podman_gpu": podman_gpu,
        "mcp_entry": entry,
        "hint_sync_paths": [source_mount],
    }

    if mcp_json_path is not None and not dry_run:
        mcp = load_mcp_json(mcp_json_path)
        merge_mcp_server(mcp, key, entry, force=force)
        write_mcp_json(mcp_json_path, mcp)
        report["merged_into"] = str(mcp_json_path.resolve())

    return report
