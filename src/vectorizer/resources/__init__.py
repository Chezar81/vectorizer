"""Bundled static assets (icons, etc.)."""

from __future__ import annotations

from pathlib import Path


def resource_dir() -> Path:
    return Path(__file__).resolve().parent


def icon_path(*parts: str) -> Path:
    return resource_dir().joinpath("icons", *parts)
