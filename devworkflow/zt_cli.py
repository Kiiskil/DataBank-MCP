#!/usr/bin/env python3
"""
ZT-RAG CLI – aja suoraan Podmanissa / paikallisesti (ei tarvitse Cursor-MCP:tä).

Esimerkki Podman (workspace + data-volume):

  podman run --rm \\
    -e ANTHROPIC_API_KEY \\
    -e ZT_DATA_DIR=/data \\
    -v "$PWD:/workspace:ro,Z" \\
    -v zt-rag-data:/data \\
    --entrypoint python localhost/datapankki-mcp:latest \\
    -m devworkflow.zt_cli sync /workspace/Databank/AI

  podman run ... -m devworkflow.zt_cli ingest
  podman run ... -m devworkflow.zt_cli coverage
  podman run ... -m devworkflow.zt_cli status
  podman run ... -m devworkflow.zt_cli query "Mitä sanotaan RAG:sta?"

  # Uusi MCP-agentti: mcp.json + Podmanissa sync + ingest + coverage (oletus):
  python -m devworkflow.zt_cli create-mcp-agent --name "Työ AI" --databank /polku/kirjastoihin
  # Vain MCP-merkintä ilman indeksointia:
  python -m devworkflow.zt_cli create-mcp-agent --name "X" --databank /polku --mcp-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))
if Path("/app").exists() and "/app" not in sys.path:
    sys.path.insert(0, "/app")

from devworkflow.zt_rag.mcp_provision import provision_agent
from devworkflow.zt_rag.podman_gpu import PodmanGpuProfile
from devworkflow.zt_rag.podman_zt_cli import (
    preview_podman_commands,
    run_agent_data_pipeline_via_podman,
)


def _paths():
    from devworkflow.zt_rag.storage_layout import StoragePaths

    p = StoragePaths.create()
    p.ensure()
    return p


def main() -> None:
    p = argparse.ArgumentParser(description="ZT-RAG komentorivi (sync, ingest, coverage, status, query)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sync", help="Lisää lähteet manifestiin")
    sp.add_argument("paths", nargs="+", help="Tiedostot tai hakemistot (EPUB/PDF)")

    ip = sub.add_parser("ingest", help="Parsinta + indeksin julkaisu")
    ip.add_argument("--force", action="store_true", help="Pakota uudelleenparsinta")

    sub.add_parser("coverage", help="Tarkista manifest vs julkaistu indeksi")
    sub.add_parser("status", help="Manifest + meta.json -yhteenveto")

    qp = sub.add_parser("query", help="Kysely (Anthropic API)")
    qp.add_argument("question", help="Kysymys")
    qp.add_argument("--model", default=None, help="Malli (oletus ZT_QUERY_MODEL tai claude-sonnet-4-6)")

    cap = sub.add_parser(
        "create-mcp-agent",
        help=(
            "Luo zt-rag -MCP-agentin: kirjoittaa mcp.json:in ja oletuksena ajaa Podmanissa "
            "sync + ingest + coverage"
        ),
    )
    cap.add_argument("--name", required=True, help="Agentin näyttönimi (slugi volyymille/MCP-avaimelle)")
    cap.add_argument(
        "--databank",
        required=True,
        type=Path,
        help="Absoluuttinen polku hakemistoon (EPUB/PDF -puu)",
    )
    cap.add_argument(
        "--mcp-json",
        type=Path,
        default=None,
        help="Kohde-mcp.json (oletus: ~/.cursor/mcp.json). --dry-run ohittaa kirjoituksen.",
    )
    cap.add_argument(
        "--server-key",
        default=None,
        help="Cursorin mcpServers-avain (oletus: sama kuin --name)",
    )
    cap.add_argument(
        "--image",
        default="localhost/datapankki-mcp:latest",
        help="Podman-image",
    )
    cap.add_argument(
        "--source-mount",
        default="/zt/bank",
        help="Polku kontissa johon tietopankki mountataan (zt_sync_sources: tämä polku)",
    )
    cap.add_argument(
        "--volume-prefix",
        default="zt-rag-data",
        help="Podman-volyymin etuliite (kokonaisnimi: <prefix>-<slug>)",
    )
    cap.add_argument(
        "--bootstrap-sync",
        action="store_true",
        help="Lisää ZT_BOOTSTRAP_SYNC_PATHS (manifesti päivittyy joka MCP-käynnistyksellä; iso korpus hidas)",
    )
    cap.add_argument(
        "--hf-token",
        action="store_true",
        help="Lisää HF_TOKEN Podman-argsiin ja env-viittaukseen",
    )
    cap.add_argument(
        "--force",
        action="store_true",
        help="Korvaa olemassa oleva sama mcpServers-avain",
    )
    cap.add_argument(
        "--dry-run",
        action="store_true",
        help="Älä kirjoita tiedostoa äläkä aja Podmania; tulosta JSON + esikatselukomennot",
    )
    cap.add_argument(
        "--mcp-only",
        action="store_true",
        help="Kirjoita vain MCP-merkintä; älä aja sync/ingest/coverage Podmanissa",
    )
    cap.add_argument(
        "--ingest-force",
        action="store_true",
        help="Podman-ingest --force (uudelleenparsinta)",
    )
    cap.add_argument(
        "--skip-coverage",
        action="store_true",
        help="Älä aja zt_cli coverage Podmanissa ingestin jälkeen",
    )
    cap.add_argument(
        "--podman-gpu",
        choices=["none", "amd"],
        default="none",
        metavar="PROFIILI",
        help=(
            "AMD ROCm: lisää Podman-laitteet MCP-merkintään ja sync/ingest/coverage-ajoihin. "
            "Oletusimage on CPU-torch; GPU vaatii ROCm-PyTorch-imagen (ks. PODMAN_AMD_GPU_SUUNNITELMA.md)."
        ),
    )

    args = p.parse_args()

    if args.cmd == "create-mcp-agent":
        default_mcp = Path.home() / ".cursor" / "mcp.json"
        target = None if args.dry_run else (args.mcp_json if args.mcp_json is not None else default_mcp)
        podman_gpu: PodmanGpuProfile = args.podman_gpu
        try:
            out = provision_agent(
                name=args.name,
                databank=args.databank,
                mcp_json_path=target,
                image=args.image,
                source_mount=args.source_mount,
                volume_prefix=args.volume_prefix,
                server_key=args.server_key,
                force=args.force,
                include_hf_token=args.hf_token,
                bootstrap_sync=args.bootstrap_sync,
                dry_run=args.dry_run,
                podman_gpu=podman_gpu,
            )
        except FileExistsError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr)
            sys.exit(2)
        except (OSError, ValueError, NotADirectoryError) as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)

        host_bank = out["databank_host"]
        vol = out["data_volume"]
        preview = preview_podman_commands(
            image=args.image,
            databank_host_resolved=host_bank,
            data_volume=vol,
            source_mount=args.source_mount,
            ingest_force=args.ingest_force,
            pass_hf_token=bool(args.hf_token or os.environ.get("HF_TOKEN", "").strip()),
            podman_gpu=podman_gpu,
        )
        out["would_run_podman"] = {k: v for k, v in preview.items()}

        run_pipeline = (
            not args.dry_run
            and not args.mcp_only
        )
        if run_pipeline:
            try:
                pipeline = run_agent_data_pipeline_via_podman(
                    image=args.image,
                    databank_host_resolved=host_bank,
                    data_volume=vol,
                    source_mount=args.source_mount,
                    ingest_force=args.ingest_force,
                    pass_hf_token=bool(args.hf_token or os.environ.get("HF_TOKEN", "").strip()),
                    run_coverage=not args.skip_coverage,
                    podman_gpu=podman_gpu,
                )
                out["data_pipeline"] = pipeline
                cov = pipeline.get("coverage")
                if cov is not None and not cov.get("ok", False):
                    out["ok"] = False
                    out["error"] = "coverage ei ok (katso data_pipeline.coverage)"
                    print(json.dumps(out, ensure_ascii=False, indent=2))
                    sys.exit(4)
            except FileNotFoundError as e:
                out["ok"] = False
                out["data_pipeline_error"] = str(e)
                print(json.dumps(out, ensure_ascii=False, indent=2))
                sys.exit(3)
            except RuntimeError as e:
                out["ok"] = False
                out["data_pipeline_error"] = str(e)
                print(json.dumps(out, ensure_ascii=False, indent=2))
                sys.exit(3)

        notes = [
            "Käynnistä Cursor uudelleen tai lataa MCP-palvelimet.",
        ]
        if args.mcp_only or args.dry_run:
            notes.append(
                f"Manuaalisesti: zt_sync_sources {json.dumps(out.get('hint_sync_paths', []), ensure_ascii=False)} → zt_ingest → zt_verify_coverage."
            )
        elif run_pipeline:
            notes.append("Indeksi rakennettu Podmanissa; voit käyttää zt_queryä Cursorissa.")
        out = {"ok": True, **out, "next_steps": notes}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    from devworkflow.zt_rag.cli_runner import (
        run_ingest,
        run_query,
        run_status,
        run_sync_sources,
        run_verify_coverage,
    )

    paths = _paths()

    if args.cmd == "sync":
        out = run_sync_sources(paths, list(args.paths))
    elif args.cmd == "ingest":
        out = run_ingest(paths, force_rebuild=args.force)
    elif args.cmd == "coverage":
        out = run_verify_coverage(paths)
    elif args.cmd == "status":
        out = run_status(paths)
    elif args.cmd == "query":
        if not os.environ.get("ZT_QUERY_LOG_SOURCE", "").strip():
            os.environ["ZT_QUERY_LOG_SOURCE"] = "zt_cli"
        out = run_query(paths, args.question, model=args.model)
    else:
        p.error("tuntematon komento")

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
