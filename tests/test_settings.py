from __future__ import annotations

import pytest

from vectorizer.domain.settings import (
    AaArtifactRejection,
    ColorMode,
    DxfLineDensity,
    EpsCompatibility,
    HierarchyMode,
    TraceSettings,
    scaled_length_threshold,
)
from vectorizer.vectorize.curves import node_budget_epsilon, simplify_closed_ring


def test_defaults_validate() -> None:
    settings = TraceSettings().validated()
    kwargs = settings.to_backend_kwargs()
    assert kwargs["colormode"] == "color"
    assert kwargs["mode"] == "spline"
    assert 3.5 <= kwargs["length_threshold"] <= 10


def test_invalid_length_rejected() -> None:
    with pytest.raises(ValueError):
        TraceSettings(length_threshold=1.0).validated()


def test_round_trip_mapping() -> None:
    original = TraceSettings(colormode=ColorMode.BINARY, filter_speckle=7).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored == original


def test_contour_smoothness_node_budget_and_aa_rejection_validate() -> None:
    settings = TraceSettings().validated()
    assert settings.contour_smoothness == 50
    assert settings.node_budget == 50
    assert settings.aa_artifact_rejection == AaArtifactRejection.MODERATE
    with pytest.raises(ValueError):
        TraceSettings(contour_smoothness=101).validated()
    with pytest.raises(ValueError):
        TraceSettings(contour_smoothness=-1).validated()
    with pytest.raises(ValueError):
        TraceSettings(node_budget=101).validated()
    with pytest.raises(ValueError):
        TraceSettings(aa_artifact_rejection="nope").validated()


def test_smoothness_scales_length_threshold_and_round_trips() -> None:
    base = TraceSettings(length_threshold=4.2, contour_smoothness=50).validated()
    assert base.to_backend_kwargs()["length_threshold"] == pytest.approx(4.2)
    assert base.to_backend_kwargs()["path_precision"] == base.path_precision
    tight = TraceSettings(length_threshold=4.2, contour_smoothness=0).validated()
    loose = TraceSettings(length_threshold=4.2, contour_smoothness=100).validated()
    assert tight.to_backend_kwargs()["length_threshold"] == pytest.approx(3.5)
    assert loose.to_backend_kwargs()["length_threshold"] == pytest.approx(10.0)
    assert scaled_length_threshold(4.2, 50) == pytest.approx(4.2)
    original = TraceSettings(
        contour_smoothness=80,
        node_budget=20,
        aa_artifact_rejection=AaArtifactRejection.AGGRESSIVE,
    ).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored.contour_smoothness == 80
    assert restored.node_budget == 20
    assert restored.aa_artifact_rejection == AaArtifactRejection.AGGRESSIVE
    assert restored.to_backend_kwargs()["length_threshold"] > restored.length_threshold


def test_dxf_density_eps_cluster_and_max_side_round_trip() -> None:
    defaults = TraceSettings().validated()
    assert defaults.dxf_line_density == DxfLineDensity.NORMAL
    assert defaults.eps_compatibility == EpsCompatibility.COMPACT
    assert defaults.cluster_similar_colors is False
    assert defaults.max_side == 0
    original = TraceSettings(
        hierarchical=HierarchyMode.CUTOUT,
        dxf_line_density=DxfLineDensity.MANY,
        eps_compatibility=EpsCompatibility.COMPATIBLE,
        cluster_similar_colors=True,
        max_side=2400,
    ).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored == original
    with pytest.raises(ValueError):
        TraceSettings(max_side=-1).validated()
    with pytest.raises(ValueError):
        TraceSettings(dxf_line_density="dense").validated()


def test_node_budget_keeps_more_points_when_higher() -> None:
    assert node_budget_epsilon(100, tolerance=1.0) < node_budget_epsilon(50, tolerance=1.0)
    assert node_budget_epsilon(50, tolerance=1.0) < node_budget_epsilon(0, tolerance=1.0)
    stair = [(float(i), float((i // 2) % 2)) for i in range(40)]
    stair.append(stair[0])
    loose = simplify_closed_ring(stair, epsilon=node_budget_epsilon(0, tolerance=1.2))
    tight = simplify_closed_ring(stair, epsilon=node_budget_epsilon(100, tolerance=1.2))
    assert len(loose) < len(tight)
