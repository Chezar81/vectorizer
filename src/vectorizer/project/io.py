"""Versioned project container: ZIP with JSON manifest + image/vector assets.

Never uses pickle. Paths inside the archive are validated against traversal.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import ProjectError
from vectorizer.segmentation.map import SegmentationMap
from vectorizer.svg.parse import parse_svg_document

PROJECT_SCHEMA = 1
PROJECT_EXT = ".vproj"
MAX_ARCHIVE_UNCOMPRESSED = 200 * 1024 * 1024
ALLOWED_MEMBER_NAMES = frozenset(
    {
        "manifest.json",
        "source.png",
        "segmentation.png",
        "result.svg",
    }
)


@dataclass
class ProjectData:
    source: Image.Image
    settings: TraceSettings
    segmentation: SegmentationMap | None
    result_svg: str | None
    source_name: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def document(self) -> VectorDocument | None:
        if not self.result_svg:
            return None
        return parse_svg_document(self.result_svg, backend_name="project")


def save_project(path: str | Path, data: ProjectData) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != PROJECT_EXT:
        destination = destination.with_suffix(PROJECT_EXT)
    destination.parent.mkdir(parents=True, exist_ok=True)

    source = data.source.convert("RGBA")
    source_buf = io.BytesIO()
    source.save(source_buf, format="PNG")
    source_bytes = source_buf.getvalue()

    seg_bytes: bytes | None = None
    if data.segmentation is not None:
        seg_bytes = data.segmentation.to_png_bytes()

    svg_text = data.result_svg
    manifest = {
        "schema": PROJECT_SCHEMA,
        "format": "vectorizer-project",
        "source_name": data.source_name,
        "source": "source.png",
        "segmentation": "segmentation.png" if seg_bytes else None,
        "result": "result.svg" if svg_text else None,
        "settings": data.settings.validated().to_json(),
        "notes": list(data.notes),
        "dimensions": {"width": source.size[0], "height": source.size[1]},
    }

    tmp = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("source.png", source_bytes)
            if seg_bytes is not None:
                archive.writestr("segmentation.png", seg_bytes)
            if svg_text:
                archive.writestr("result.svg", svg_text.encode("utf-8"))
        tmp.replace(destination)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise ProjectError(f"Could not save project: {exc}") from exc
    return destination


def load_project(path: str | Path) -> ProjectData:
    file_path = Path(path)
    if not file_path.is_file():
        raise ProjectError(f"Project not found: {file_path}")
    try:
        with zipfile.ZipFile(file_path, "r") as archive:
            _validate_archive(archive)
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProjectError(f"Invalid project manifest: {exc}") from exc
            if not isinstance(manifest, dict):
                raise ProjectError("Project manifest must be a JSON object.")
            schema = manifest.get("schema")
            if schema != PROJECT_SCHEMA:
                raise ProjectError(f"Unsupported project schema: {schema}")
            if manifest.get("format") != "vectorizer-project":
                raise ProjectError("Not a Vectorizer project archive.")

            source_member = manifest.get("source", "source.png")
            _assert_safe_member(source_member)
            source = Image.open(io.BytesIO(archive.read(source_member)))
            source.load()
            source = source.convert("RGBA")

            settings_raw = manifest.get("settings")
            if not isinstance(settings_raw, dict):
                raise ProjectError("Project is missing settings.")
            try:
                settings = TraceSettings.from_mapping(settings_raw)
            except (ValueError, TypeError, KeyError) as exc:
                raise ProjectError(f"Invalid project settings: {exc}") from exc

            segmentation = None
            seg_member = manifest.get("segmentation")
            if seg_member:
                _assert_safe_member(seg_member)
                segmentation = SegmentationMap.from_png_bytes(archive.read(seg_member))
                if segmentation.size != source.size:
                    raise ProjectError(
                        "Segmentation dimensions do not match the source image."
                    )

            result_svg = None
            result_member = manifest.get("result")
            if result_member:
                _assert_safe_member(result_member)
                result_svg = archive.read(result_member).decode("utf-8")
                if "<svg" not in result_svg.lower():
                    raise ProjectError("Project result.svg is not valid SVG markup.")

            notes = tuple(str(n) for n in (manifest.get("notes") or []))
            return ProjectData(
                source=source,
                settings=settings,
                segmentation=segmentation,
                result_svg=result_svg,
                source_name=manifest.get("source_name"),
                notes=notes,
            )
    except ProjectError:
        raise
    except zipfile.BadZipFile as exc:
        raise ProjectError("Project file is not a valid ZIP archive.") from exc
    except Exception as exc:
        raise ProjectError(f"Could not load project: {exc}") from exc


def _validate_archive(archive: zipfile.ZipFile) -> None:
    total = 0
    for info in archive.infolist():
        name = info.filename
        if name.endswith("/"):
            continue
        _assert_safe_member(name)
        if name not in ALLOWED_MEMBER_NAMES:
            raise ProjectError(f"Unexpected archive member: {name}")
        total += info.file_size
        if total > MAX_ARCHIVE_UNCOMPRESSED:
            raise ProjectError("Project archive exceeds the size safety limit.")


def _assert_safe_member(name: str) -> None:
    if not name or name != Path(name).name:
        raise ProjectError(f"Unsafe archive path rejected: {name!r}")
    if ".." in name or name.startswith("/") or name.startswith("\\"):
        raise ProjectError(f"Unsafe archive path rejected: {name!r}")
