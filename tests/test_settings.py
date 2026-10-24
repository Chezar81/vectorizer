from __future__ import annotations

import pytest

from vectorizer.domain.settings import ColorMode, TraceSettings


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
