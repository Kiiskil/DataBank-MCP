"""
Aja zt_cli (sync / ingest) Podmanissa samoilla mounteilla kuin MCP-merkinnässä.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from devworkflow.zt_rag.podman_gpu import PodmanGpuProfile, podman_gpu_run_args


def build_podman_zt_cli_argv(
    *,
    image: str,
    databank_host_resolved: str,
    data_volume: str,
    source_mount: str,
    zt_cli_extra_args: list[str],
    pass_hf_token: bool,
    podman_gpu: PodmanGpuProfile = "none",
) -> list[str]:
    argv: list[str] = [
        "podman",
        "run",
        "--rm",
        *podman_gpu_run_args(podman_gpu),
        "-e",
        "ZT_DATA_DIR=/data",
    ]
    if pass_hf_token:
        argv.extend(["-e", "HF_TOKEN"])
    argv.extend(
        [
            "-v",
            f"{databank_host_resolved}:{source_mount}:ro,Z",
            "-v",
            f"{data_volume}:/data",
            "--entrypoint",
            "python",
            image,
            "-m",
            "devworkflow.zt_cli",
            *zt_cli_extra_args,
        ]
    )
    return argv


def _run_podman_json(argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    parsed: dict[str, Any] | None = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = None
    if proc.returncode != 0:
        msg = err or out or f"exit {proc.returncode}"
        raise RuntimeError(f"Podman epäonnistui ({proc.returncode}): {msg}")
    if parsed is None:
        raise RuntimeError(f"Ei kelvollista JSONia stdoutissa: {out[:500]!r}")
    return parsed


def run_agent_data_pipeline_via_podman(
    *,
    image: str,
    databank_host_resolved: str,
    data_volume: str,
    source_mount: str,
    ingest_force: bool = False,
    pass_hf_token: bool = True,
    run_coverage: bool = True,
    podman_gpu: PodmanGpuProfile = "none",
) -> dict[str, Any]:
    """
    sync (lähdepolku kontissa) + ingest; valinnainen coverage. Vaatii podman PATHilla ja image:n.
    """
    if not shutil.which("podman"):
        raise FileNotFoundError("podman ei löydy PATHista")

    sync_argv = build_podman_zt_cli_argv(
        image=image,
        databank_host_resolved=databank_host_resolved,
        data_volume=data_volume,
        source_mount=source_mount,
        zt_cli_extra_args=["sync", source_mount],
        pass_hf_token=pass_hf_token,
        podman_gpu=podman_gpu,
    )
    ingest_args = ["ingest"]
    if ingest_force:
        ingest_args.append("--force")
    ingest_argv = build_podman_zt_cli_argv(
        image=image,
        databank_host_resolved=databank_host_resolved,
        data_volume=data_volume,
        source_mount=source_mount,
        zt_cli_extra_args=ingest_args,
        pass_hf_token=pass_hf_token,
        podman_gpu=podman_gpu,
    )

    sync_result = _run_podman_json(sync_argv)
    ingest_result = _run_podman_json(ingest_argv)
    out: dict[str, Any] = {"sync": sync_result, "ingest": ingest_result}
    if run_coverage:
        coverage_argv = build_podman_zt_cli_argv(
            image=image,
            databank_host_resolved=databank_host_resolved,
            data_volume=data_volume,
            source_mount=source_mount,
            zt_cli_extra_args=["coverage"],
            pass_hf_token=pass_hf_token,
            podman_gpu=podman_gpu,
        )
        out["coverage"] = _run_podman_json(coverage_argv)
    return out


def preview_podman_commands(
    *,
    image: str,
    databank_host_resolved: str,
    data_volume: str,
    source_mount: str,
    ingest_force: bool,
    pass_hf_token: bool,
    podman_gpu: PodmanGpuProfile = "none",
) -> dict[str, list[str]]:
    """Dry-run: näytettävät podman-komennot (listana argv)."""
    sync_a = build_podman_zt_cli_argv(
        image=image,
        databank_host_resolved=databank_host_resolved,
        data_volume=data_volume,
        source_mount=source_mount,
        zt_cli_extra_args=["sync", source_mount],
        pass_hf_token=pass_hf_token,
        podman_gpu=podman_gpu,
    )
    ingest_args = ["ingest"]
    if ingest_force:
        ingest_args.append("--force")
    ingest_a = build_podman_zt_cli_argv(
        image=image,
        databank_host_resolved=databank_host_resolved,
        data_volume=data_volume,
        source_mount=source_mount,
        zt_cli_extra_args=ingest_args,
        pass_hf_token=pass_hf_token,
        podman_gpu=podman_gpu,
    )
    cov_a = build_podman_zt_cli_argv(
        image=image,
        databank_host_resolved=databank_host_resolved,
        data_volume=data_volume,
        source_mount=source_mount,
        zt_cli_extra_args=["coverage"],
        pass_hf_token=pass_hf_token,
        podman_gpu=podman_gpu,
    )
    return {"sync_argv": sync_a, "ingest_argv": ingest_a, "coverage_argv": cov_a}
