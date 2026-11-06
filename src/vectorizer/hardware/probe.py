"""Detect CPU and GPU capabilities available to this process."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class GpuInfo:
    """One display/compute GPU the host reports."""

    name: str
    backend: str  # cuda | metal | opencl | unknown
    memory_mib: int | None = None
    usable: bool = False
    notes: str = ""


@dataclass(frozen=True)
class HardwareProfile:
    """Snapshot of host compute resources relevant to vectorization."""

    cpu_logical: int
    cpu_physical: int
    ram_mib: int | None
    platform: str
    gpus: tuple[GpuInfo, ...] = ()
    cupy_available: bool = False
    cupy_notes: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def usable_cuda(self) -> bool:
        return any(g.usable and g.backend == "cuda" for g in self.gpus) and self.cupy_available

    @property
    def best_gpu(self) -> GpuInfo | None:
        usable = [g for g in self.gpus if g.usable]
        if not usable:
            return None
        usable.sort(key=lambda g: (g.memory_mib or 0), reverse=True)
        return usable[0]

    def summary(self) -> str:
        ram = f"{self.ram_mib} MiB RAM" if self.ram_mib else "RAM unknown"
        parts = [
            f"{self.cpu_physical}C/{self.cpu_logical}T CPU",
            ram,
        ]
        if self.gpus:
            gpu_bits = []
            for gpu in self.gpus:
                state = "ready" if gpu.usable else "present"
                mem = f", {gpu.memory_mib} MiB" if gpu.memory_mib else ""
                gpu_bits.append(f"{gpu.name} ({gpu.backend}, {state}{mem})")
            parts.append("; ".join(gpu_bits))
        else:
            parts.append("no discrete GPU reported")
        if self.cupy_available:
            parts.append("CuPy available")
        return " · ".join(parts)


def probe_hardware(*, force: bool = False) -> HardwareProfile:
    """Return a cached hardware snapshot. Pass force=True to re-probe."""
    if force:
        _probe_hardware_cached.cache_clear()
    return _probe_hardware_cached()


@lru_cache(maxsize=1)
def _probe_hardware_cached() -> HardwareProfile:
    warnings: list[str] = []
    logical = os.cpu_count() or 1
    physical = _physical_cpu_count(logical)
    ram_mib = _ram_mib()
    gpus: list[GpuInfo] = []
    gpus.extend(_probe_nvidia(warnings))
    gpus.extend(_probe_metal())
    cupy_ok, cupy_notes = _probe_cupy()
    unique: dict[tuple[str, str], GpuInfo] = {}
    for gpu in gpus:
        unique[(gpu.backend, gpu.name)] = gpu
    return HardwareProfile(
        cpu_logical=logical,
        cpu_physical=physical,
        ram_mib=ram_mib,
        platform=platform.platform(),
        gpus=tuple(unique.values()),
        cupy_available=cupy_ok,
        cupy_notes=cupy_notes,
        warnings=tuple(warnings),
    )


def _physical_cpu_count(logical: int) -> int:
    cpuinfo = Path("/proc/cpuinfo")
    try:
        text = cpuinfo.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return max(1, logical // 2) if logical > 1 else 1
    cores: set[tuple[str, str]] = set()
    phys = "0"
    core = "0"
    for line in text.splitlines():
        if line.startswith("physical id"):
            phys = line.split(":", 1)[1].strip()
        elif line.startswith("core id"):
            core = line.split(":", 1)[1].strip()
            cores.add((phys, core))
    if cores:
        return max(1, len(cores))
    return max(1, logical // 2) if logical > 1 else 1


def _ram_mib() -> int | None:
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        if page > 0 and pages > 0:
            return int((page * pages) / (1024 * 1024))
    except (AttributeError, ValueError, OSError):
        pass
    if platform.system() == "Darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=2
            )
            return int(int(out.strip()) / (1024 * 1024))
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    return None


def _probe_nvidia(warnings: list[str]) -> list[GpuInfo]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    try:
        out = subprocess.check_output(
            [
                smi,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=3,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        warnings.append(f"NVIDIA GPU present but driver unusable ({exc}).")
        return [
            GpuInfo(
                name="NVIDIA (driver unavailable)",
                backend="cuda",
                usable=False,
                notes="nvidia-smi failed; install/load the proprietary driver to use CUDA.",
            )
        ]
    gpus: list[GpuInfo] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0] or "NVIDIA GPU"
        try:
            mem = int(float(parts[1]))
        except ValueError:
            mem = None
        gpus.append(
            GpuInfo(
                name=name,
                backend="cuda",
                memory_mib=mem,
                usable=True,
                notes=f"driver {parts[2]}" if len(parts) > 2 and parts[2] else "",
            )
        )
    return gpus


def _probe_metal() -> list[GpuInfo]:
    if platform.system() != "Darwin":
        return []
    # Vectorizer has no Metal kernels yet; report presence for honesty.
    return [
        GpuInfo(
            name="Apple GPU",
            backend="metal",
            usable=False,
            notes="Metal is present but Vectorizer has no Metal raster kernels yet.",
        )
    ]


def _probe_cupy() -> tuple[bool, str]:
    try:
        import cupy  # type: ignore
    except Exception as exc:  # noqa: BLE001 — optional accelerator
        return False, f"CuPy not available ({type(exc).__name__})."
    try:
        device_count = int(cupy.cuda.runtime.getDeviceCount())
        if device_count < 1:
            return False, "CuPy imported but no CUDA device is visible."
        _ = cupy.zeros((4,), dtype=cupy.float32)
        cupy.cuda.Stream.null.synchronize()
        return True, f"CuPy {getattr(cupy, '__version__', '?')} · {device_count} device(s)"
    except Exception as exc:  # noqa: BLE001
        return False, f"CuPy import ok but CUDA runtime failed ({exc})."
