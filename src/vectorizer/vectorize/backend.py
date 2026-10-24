"""Tracing backend contract. Segmentation maps are not implied by SVG output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import TraceSettings


@dataclass(frozen=True)
class TraceResult:
    document: VectorDocument
    elapsed_seconds: float
    settings: TraceSettings
    backend_name: str
    warnings: tuple[str, ...] = ()


class VectorizeBackend(Protocol):
    name: str
    description: str

    def trace(self, image: Image.Image, settings: TraceSettings) -> TraceResult:
        """Trace a raster. Implementations must not mutate `image`."""
        ...
