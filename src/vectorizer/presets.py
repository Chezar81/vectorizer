"""Named presets stored as JSON under the user config directory. No pickle."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import VectorizerError

PRESET_SCHEMA = 1
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")

# Overridable for tests.
_PRESETS_DIR_OVERRIDE: Path | None = None


class PresetError(VectorizerError):
    """Preset load/save failure."""


def set_presets_dir_override(path: Path | None) -> None:
    global _PRESETS_DIR_OVERRIDE
    _PRESETS_DIR_OVERRIDE = path


def presets_dir() -> Path:
    if _PRESETS_DIR_OVERRIDE is not None:
        path = _PRESETS_DIR_OVERRIDE
        path.mkdir(parents=True, exist_ok=True)
        return path
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        path = Path(xdg) / "Vectorizer" / "presets"
    else:
        path = Path.home() / ".config" / "Vectorizer" / "presets"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Sandbox / read-only home: fall back to a temp-like location under /tmp.
        fallback = Path(os.environ.get("TMPDIR", "/tmp")) / "vectorizer-presets"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    return path


def list_presets() -> list[str]:
    directory = presets_dir()
    try:
        return [file.stem for file in sorted(directory.glob("*.json"))]
    except OSError:
        return []



def preset_path(name: str) -> Path:
    if not SAFE_NAME.match(name):
        raise PresetError(
            "Preset names may use letters, digits, spaces, underscore, dot, and hyphen (max 64)."
        )
    return presets_dir() / f"{name}.json"


def save_preset(name: str, settings: TraceSettings) -> Path:
    path = preset_path(name)
    payload = {
        "schema": PRESET_SCHEMA,
        "name": name,
        "settings": settings.validated().to_json(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_preset(name: str) -> TraceSettings:
    path = preset_path(name)
    if not path.is_file():
        raise PresetError(f"Preset not found: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PresetError(f"Preset file is corrupt: {exc}") from exc
    if not isinstance(data, dict):
        raise PresetError("Preset root must be a JSON object.")
    schema = data.get("schema", 1)
    if schema != PRESET_SCHEMA:
        raise PresetError(f"Unsupported preset schema {schema}.")
    settings = data.get("settings")
    if not isinstance(settings, dict):
        raise PresetError("Preset is missing a settings object.")
    try:
        return TraceSettings.from_mapping(settings)
    except (ValueError, TypeError, KeyError) as exc:
        raise PresetError(f"Invalid preset settings: {exc}") from exc


def delete_preset(name: str) -> None:
    path = preset_path(name)
    if path.is_file():
        path.unlink()


def duplicate_preset(source: str, dest: str) -> Path:
    settings = load_preset(source)
    return save_preset(dest, settings)
