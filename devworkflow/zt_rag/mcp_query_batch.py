"""
Aja testikysymykset yhden MCP-istunnon kautta: yksi Podman-prosessi, stdio-MCP.

Sama periaate kuin Cursorissa: palvelin pysyy käynnissä → mallit lämpiminä kyselyjen välillä.

Käyttö (repojuuresta, requirements asennettuna):

  export ANTHROPIC_API_KEY=...
  PYTHONPATH=. python -m devworkflow.zt_rag.mcp_query_batch

Valinnaiset ympäristömuuttujat (samat kuin Cursorin MCP-konffissa):

  ZT_RAG_IMAGE   (oletus localhost/datapankki-mcp:latest)
  ZT_RAG_VOLUME  (oletus zt-rag-data-databank-ai)
  ZT_MCP_DATABANK_HOST — absoluuttinen polku tietopankkiin hostilla (esim. .../Databank/AI tai .../Databank/Software)

  Software-erä: --questions devworkflow/zt_rag/query_batch_questions_software.txt
    + ZT_RAG_VOLUME=zt-rag-data-databank-software ja ZT_MCP_DATABANK_HOST=.../Databank/Software

  Linux-erä: query_batch_questions_linux.txt + zt-rag-data-databank-linux + .../Databank/Linux
  Hacking-erä: query_batch_questions_hacking.txt + zt-rag-data-databank-hacking + .../Databank/Hacking

  Oletuksena mountataan repojuuren devworkflow/ → /app/devworkflow (sama kuin Cursor-ingest),
  jotta queries.jsonl saa cli_runner.py:n uudet kentät (esim. answer) ilman image-uudelleenbuildiä.
  Poista mount: ZT_MCP_SKIP_DEVWORKFLOW_MOUNT=1

  Eräajon metatiedot (asetetaan automaattisesti): ZT_QUERY_LOG_SOURCE=mcp_query_batch,
  ZT_QUERY_BATCH_FILE, ZT_QUERY_BATCH_RUN_ID → näkyvät queries.jsonl:ssä (batch + lähde).

  Kaikki pankit kerralla: devworkflow/zt_rag/run_query_batch_all.sh

  Vaikeat kysymykset + leveämpi haku: --hard (HyDE, suurempi top_k / multi-query pool).
  Tiedostot: query_batch_questions_*_hard.txt — ajo: run_query_batch_hard_all.sh
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from devworkflow.zt_rag.query_hard_profile import QUERY_HARD_PROFILE_ENV


def _podman_zt_env_flags(batch_env: dict[str, str], *, hard_retrieval: bool) -> list[str]:
    """Välitä ZT_* konttiin (podman run ei peri hostin ympäristöä automaattisesti)."""
    keys = [
        "ZT_QUERY_LOG_SOURCE",
        "ZT_QUERY_BATCH_FILE",
        "ZT_QUERY_BATCH_RUN_ID",
    ]
    if hard_retrieval:
        keys.extend(QUERY_HARD_PROFILE_ENV.keys())
    out: list[str] = []
    for k in keys:
        val = batch_env.get(k)
        if val is None or str(val).strip() == "":
            continue
        out.extend(["-e", f"{k}={val}"])
    return out


def _load_questions(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def _podman_args(
    *,
    image: str,
    volume: str,
    databank_host: str,
    devworkflow_host: str | None,
    batch_env: dict[str, str],
    hard_retrieval: bool,
) -> list[str]:
    args: list[str] = [
        "run",
        "--rm",
        "-i",
        "-e",
        "ANTHROPIC_API_KEY",
        "-e",
        "ZT_DATA_DIR=/data",
    ]
    args.extend(_podman_zt_env_flags(batch_env, hard_retrieval=hard_retrieval))
    if devworkflow_host:
        args.extend(
            [
                "-v",
                f"{devworkflow_host}:/app/devworkflow:ro,Z",
            ]
        )
    args.extend(
        [
            "-v",
            f"{databank_host}:/zt/bank:ro,Z",
            "-v",
            f"{volume}:/data",
            image,
        ]
    )
    return args


async def _run_batch(
    questions: list[str],
    *,
    questions_file: Path,
    hard_retrieval: bool,
) -> None:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print(
            "Puuttuva paketti: pip install 'mcp>=1.2.0' (tai: pip install -r requirements.txt)",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("Aseta ANTHROPIC_API_KEY.", file=sys.stderr)
        raise SystemExit(1)

    root = Path(__file__).resolve().parents[2]
    databank = os.environ.get(
        "ZT_MCP_DATABANK_HOST",
        str(root / "Databank" / "AI"),
    )
    vol = os.environ.get("ZT_RAG_VOLUME", "zt-rag-data-databank-ai")
    image = os.environ.get("ZT_RAG_IMAGE", "localhost/datapankki-mcp:latest")

    skip_dw = os.environ.get("ZT_MCP_SKIP_DEVWORKFLOW_MOUNT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    devworkflow_host: str | None = None
    if not skip_dw:
        dw = root / "devworkflow"
        if dw.is_dir():
            devworkflow_host = str(dw.resolve())

    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(4)
    )
    batch_env = {
        **os.environ,
        "ZT_QUERY_LOG_SOURCE": "mcp_query_batch",
        "ZT_QUERY_BATCH_FILE": str(questions_file.resolve()),
        "ZT_QUERY_BATCH_RUN_ID": run_id,
    }
    if hard_retrieval:
        batch_env = {**batch_env, **QUERY_HARD_PROFILE_ENV}
        print(
            "hard retrieval: HyDE + laajennettu hybrid/multi-query (ZT_QUERY_HARD_RETRIEVAL=1)",
            file=sys.stderr,
        )

    server_params = StdioServerParameters(
        command="podman",
        args=_podman_args(
            image=image,
            volume=vol,
            databank_host=databank,
            devworkflow_host=devworkflow_host,
            batch_env=batch_env,
            hard_retrieval=hard_retrieval,
        ),
        env=batch_env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            for n, q in enumerate(questions, start=1):
                print(f"========== #{n} ==========", file=sys.stderr)
                print(q, file=sys.stderr)
                result = await session.call_tool(
                    "zt_query",
                    arguments={"question": q},
                )
                text = ""
                for block in result.content:
                    if getattr(block, "type", None) == "text":
                        text = getattr(block, "text", "") or ""
                        break
                if not text:
                    print(json.dumps({"n": n, "error": "empty_tool_result"}, ensure_ascii=False))
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    print(
                        json.dumps(
                            {"n": n, "error": "invalid_json", "raw": text[:500]},
                            ensure_ascii=False,
                        )
                    )
                    continue

                ans = data.get("answer") or {}
                prev = ""
                if isinstance(ans, dict):
                    prev = str(ans.get("answer", ""))
                if len(prev) > 200:
                    prev = prev[:197] + "..."
                out = {
                    "n": n,
                    "verification_ok": data.get("verification_ok"),
                    "verification_reason": data.get("verification_reason"),
                    "answer_preview": prev,
                    "error": data.get("_error") or data.get("error"),
                }
                print(json.dumps(out, ensure_ascii=False))


def main() -> None:
    p = argparse.ArgumentParser(description="ZT-RAG: testikysymykset yhden MCP-istunnon kautta")
    p.add_argument(
        "--questions",
        type=Path,
        default=Path(__file__).resolve().parent / "query_batch_questions.txt",
        help="Tiedosto: yksi kysymys per rivi",
    )
    p.add_argument("--max", type=int, default=0, help="Enintään N ensimmäistä kysymystä (0 = kaikki)")
    p.add_argument(
        "--hard",
        action="store_true",
        help="Löydettävyysprofiili: HyDE + suurempi top_k / multi-query pool / konteksti (ks. query_hard_profile.py)",
    )
    args = p.parse_args()

    qs = _load_questions(args.questions)
    if args.max and args.max > 0:
        qs = qs[: args.max]
    if not qs:
        print("Ei kysymyksiä.", file=sys.stderr)
        raise SystemExit(1)

    asyncio.run(
        _run_batch(
            qs,
            questions_file=args.questions.resolve(),
            hard_retrieval=bool(args.hard),
        )
    )


if __name__ == "__main__":
    main()
