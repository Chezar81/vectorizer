"""Canonical vector document independent of any one backend."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FillStyle:
    color: str
    opacity: float = 1.0


@dataclass(frozen=True)
class VectorPath:
    d: str
    fill: FillStyle | None = None
    fill_rule: str | None = None
    transform: str | None = None
    source_order: int = 0


@dataclass(frozen=True)
class VectorGroup:
    name: str
    palette_key: str | None
    paths: tuple[VectorPath, ...] = ()


@dataclass(frozen=True)
class VectorDocument:
    width: float
    height: float
    view_box: tuple[float, float, float, float] | None
    groups: tuple[VectorGroup, ...]
    raw_svg: str
    backend_name: str
    path_count: int
    source_notes: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def byte_size(self) -> int:
        return len(self.raw_svg.encode("utf-8"))
