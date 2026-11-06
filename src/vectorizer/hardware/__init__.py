"""Hardware probing and compute-device policy for tracing."""

from vectorizer.hardware.policy import (
    ComputeMode,
    ComputePlan,
    active_plan,
    apply_compute_preference,
    describe_plan,
    ensure_compute_plan,
    recommend_plan,
    resolve_plan,
)
from vectorizer.hardware.probe import GpuInfo, HardwareProfile, probe_hardware

__all__ = [
    "ComputeMode",
    "ComputePlan",
    "GpuInfo",
    "HardwareProfile",
    "active_plan",
    "apply_compute_preference",
    "describe_plan",
    "ensure_compute_plan",
    "probe_hardware",
    "recommend_plan",
    "resolve_plan",
]
