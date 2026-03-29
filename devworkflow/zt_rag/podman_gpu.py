"""
Podman-ajojen GPU-passthrough (AMD ROCm / HIP).

Oletus-Dockerfile asentaa CPU-torchin; laitepolkuja tarvitaan kun image on
rakennettu ROCm-PyTorchilla tai vastaavalla. Katso docs/PODMAN_AMD_GPU_SUUNNITELMA.md.
"""
from __future__ import annotations

from typing import Literal

PodmanGpuProfile = Literal["none", "amd"]


def podman_gpu_run_args(profile: PodmanGpuProfile) -> list[str]:
    """
    Lisäargumentit heti `podman run`-lipun jälkeen (ennen -e / -v).

    AMD: /dev/kfd + /dev/dri + tyypilliset render-ryhmät (Fedora/Nobara).
    """
    if profile == "none":
        return []
    if profile == "amd":
        return [
            "--device",
            "/dev/kfd",
            "--device",
            "/dev/dri",
            "--group-add",
            "video",
            "--group-add",
            "render",
        ]
    raise ValueError(f"tuntematon podman-gpu-profiili: {profile!r}")
