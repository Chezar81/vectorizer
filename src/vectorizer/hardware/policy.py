"""Choose CPU, GPU, or hybrid compute for vectorization."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from enum import Enum

from vectorizer.hardware.probe import HardwareProfile, probe_hardware

# Env keys mirrored into the tracing subprocess.
ENV_PREFERENCE = "VECTORIZER_COMPUTE_PREFERENCE"
ENV_EFFECTIVE = "VECTORIZER_COMPUTE_EFFECTIVE"
ENV_THREADS = "VECTORIZER_CPU_THREADS"
ENV_GPU_RASTER = "VECTORIZER_GPU_RASTER"

# Transfer + kernel launch only pays off past this pixel count for nearest-color.
_GPU_PIXEL_FLOOR = 400_000


class ComputeMode(str, Enum):
    """User preference for where heavy raster work may run."""

    AUTO = "auto"
    CPU = "cpu"
    GPU = "gpu"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class ComputePlan:
    """Resolved runtime plan used by tracing and preferences UI."""

    preference: ComputeMode
    effective: ComputeMode  # cpu | gpu | hybrid (never auto)
    cpu_threads: int
    use_gpu_raster: bool
    reason: str
    hardware: HardwareProfile
    fallback_notes: tuple[str, ...] = ()

    def summary(self) -> str:
        device = self.effective.value
        gpu = "on" if self.use_gpu_raster else "off"
        return (
            f"{device} · {self.cpu_threads} CPU thread(s) · GPU raster {gpu} — {self.reason}"
        )


_active: ComputePlan | None = None


def active_plan() -> ComputePlan | None:
    return _active


def ensure_compute_plan(
    preference: ComputeMode | str | None = None,
    *,
    hardware: HardwareProfile | None = None,
    force: bool = False,
) -> ComputePlan:
    """Resolve and activate a plan. Reuses the cache unless force=True."""
    global _active
    if _active is not None and not force and preference is None and hardware is None:
        return _active
    pref = _coerce_mode(preference if preference is not None else _preference_from_env())
    profile = hardware or probe_hardware(force=force)
    plan = resolve_plan(pref, profile)
    apply_plan(plan)
    return plan


def apply_compute_preference(
    preference: ComputeMode | str,
    *,
    hardware: HardwareProfile | None = None,
) -> ComputePlan:
    """Re-resolve from a user preference and activate it."""
    return ensure_compute_plan(preference, hardware=hardware, force=True)


def resolve_plan(preference: ComputeMode | str, hardware: HardwareProfile) -> ComputePlan:
    pref = _coerce_mode(preference)
    if pref == ComputeMode.AUTO:
        return recommend_plan(hardware)
    if pref == ComputeMode.CPU:
        return _cpu_plan(hardware, pref, "User selected CPU-only.")
    if pref == ComputeMode.GPU:
        return _gpu_or_fallback(hardware, pref)
    # HYBRID
    return _hybrid_or_fallback(hardware, pref)


def recommend_plan(hardware: HardwareProfile) -> ComputePlan:
    """Pick the best default for speed without hurting path quality.

    Topology, marching squares, and VTracer stay on the CPU (branchy / Rust).
    A usable CUDA stack plus CuPy may accelerate dense OKLab nearest-color work
    on large rasters (hybrid). Otherwise stay on a tuned multi-thread CPU plan.
    """
    if hardware.usable_cuda:
        gpu = hardware.best_gpu
        name = gpu.name if gpu else "CUDA GPU"
        return ComputePlan(
            preference=ComputeMode.AUTO,
            effective=ComputeMode.HYBRID,
            cpu_threads=_thread_budget(hardware),
            use_gpu_raster=True,
            reason=(
                f"Usable {name} with CuPy — GPU for large raster colour maths, "
                "CPU for contours and VTracer (best speed without changing path logic)."
            ),
            hardware=hardware,
            fallback_notes=hardware.warnings,
        )
    notes = list(hardware.warnings)
    if any(g.backend == "cuda" for g in hardware.gpus) and not hardware.cupy_available:
        notes.append(hardware.cupy_notes or "CUDA GPU seen but CuPy is not ready.")
    if any(g.backend == "metal" for g in hardware.gpus):
        notes.append("Apple GPU present; Metal kernels are not implemented yet.")
    return _cpu_plan(
        hardware,
        ComputeMode.AUTO,
        "CPU is the best default: path quality stays on numpy/VTracer; "
        "no usable GPU accelerator was found.",
        extra_notes=tuple(notes),
    )


def describe_plan(plan: ComputePlan | None = None) -> str:
    plan = plan or active_plan() or ensure_compute_plan()
    lines = [
        plan.summary(),
        plan.hardware.summary(),
    ]
    if plan.fallback_notes:
        lines.extend(plan.fallback_notes)
    return "\n".join(lines)


def apply_plan(plan: ComputePlan) -> None:
    """Publish the plan to process env / BLAS thread caps and the module cache."""
    global _active
    _active = plan
    os.environ[ENV_PREFERENCE] = plan.preference.value
    os.environ[ENV_EFFECTIVE] = plan.effective.value
    os.environ[ENV_THREADS] = str(plan.cpu_threads)
    os.environ[ENV_GPU_RASTER] = "1" if plan.use_gpu_raster else "0"
    # Cap BLAS/OpenMP so tracing does not oversubscribe the machine (GUI + worker).
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[key] = str(plan.cpu_threads)


def gpu_raster_worthwhile(pixel_count: int, plan: ComputePlan | None = None) -> bool:
    """True when the active plan should run dense colour kernels on the GPU."""
    plan = plan or active_plan()
    if plan is None or not plan.use_gpu_raster:
        return False
    return int(pixel_count) >= _GPU_PIXEL_FLOOR


def _gpu_or_fallback(hardware: HardwareProfile, pref: ComputeMode) -> ComputePlan:
    if hardware.usable_cuda:
        gpu = hardware.best_gpu
        name = gpu.name if gpu else "CUDA GPU"
        return ComputePlan(
            preference=pref,
            effective=ComputeMode.GPU,
            cpu_threads=max(1, min(2, _thread_budget(hardware))),
            use_gpu_raster=True,
            reason=f"User selected GPU — dense raster maths on {name}; light CPU assist.",
            hardware=hardware,
            fallback_notes=hardware.warnings,
        )
    notes = list(hardware.warnings)
    notes.append(
        "GPU preferred but no usable CUDA+CuPy stack — falling back to CPU."
    )
    if hardware.cupy_notes:
        notes.append(hardware.cupy_notes)
    return replace(
        _cpu_plan(hardware, pref, "GPU unavailable; using tuned CPU."),
        fallback_notes=tuple(notes),
    )


def _hybrid_or_fallback(hardware: HardwareProfile, pref: ComputeMode) -> ComputePlan:
    if hardware.usable_cuda:
        return ComputePlan(
            preference=pref,
            effective=ComputeMode.HYBRID,
            cpu_threads=_thread_budget(hardware),
            use_gpu_raster=True,
            reason=(
                "User selected hybrid — GPU raster colour maths + CPU contours/VTracer."
            ),
            hardware=hardware,
            fallback_notes=hardware.warnings,
        )
    notes = list(hardware.warnings)
    notes.append("Hybrid preferred but GPU accelerator unavailable — using CPU.")
    return replace(
        _cpu_plan(hardware, pref, "Hybrid unavailable; using tuned CPU."),
        fallback_notes=tuple(notes),
    )


def _cpu_plan(
    hardware: HardwareProfile,
    preference: ComputeMode,
    reason: str,
    *,
    extra_notes: tuple[str, ...] = (),
) -> ComputePlan:
    return ComputePlan(
        preference=preference,
        effective=ComputeMode.CPU,
        cpu_threads=_thread_budget(hardware),
        use_gpu_raster=False,
        reason=reason,
        hardware=hardware,
        fallback_notes=extra_notes,
    )


def _thread_budget(hardware: HardwareProfile) -> int:
    # Leave one logical CPU for the GUI / OS when the worker runs as a subprocess.
    logical = max(1, hardware.cpu_logical)
    if logical <= 2:
        return 1
    return max(1, min(logical - 1, hardware.cpu_physical or logical - 1))


def _preference_from_env() -> ComputeMode:
    raw = os.environ.get(ENV_PREFERENCE, ComputeMode.AUTO.value)
    return _coerce_mode(raw)


def _coerce_mode(value: ComputeMode | str | None) -> ComputeMode:
    if isinstance(value, ComputeMode):
        return value
    if value is None or str(value).strip() == "":
        return ComputeMode.AUTO
    try:
        return ComputeMode(str(value).strip().lower())
    except ValueError:
        return ComputeMode.AUTO
