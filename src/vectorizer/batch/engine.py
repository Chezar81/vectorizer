"""Sequential batch vectorization. No uncontrolled parallelism."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import ExportError, ImageLoadError, TraceError, VectorizerError
from vectorizer.export.dxf import export_dxf
from vectorizer.export.eps import export_eps, inkscape_available
from vectorizer.export.pdf import export_pdf
from vectorizer.export.png import export_png_preview
from vectorizer.export.svg import export_svg
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.raster.loader import OPEN_EXTENSIONS, load_image

ProgressCallback = Callable[[int, int, "BatchResult | None"], None]
CancelCallback = Callable[[], bool]


class CollisionPolicy(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"


class ExportFormat(str, Enum):
    SVG = "svg"
    PDF = "pdf"
    PNG = "png"
    EPS = "eps"
    DXF = "dxf"


@dataclass(frozen=True)
class BatchJob:
    inputs: tuple[Path, ...]
    output_dir: Path
    settings: TraceSettings
    formats: tuple[ExportFormat, ...] = (ExportFormat.SVG,)
    collision: CollisionPolicy = CollisionPolicy.RENAME
    continue_on_error: bool = True


@dataclass
class BatchResult:
    source: str
    ok: bool
    outputs: list[str] = field(default_factory=list)
    error: str | None = None
    path_count: int = 0
    seconds: float = 0.0
    skipped: bool = False


@dataclass
class BatchSummary:
    started: float
    finished: float
    job: dict
    results: list[BatchResult]

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok and not r.skipped)

    @property
    def skip_count(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    def to_json(self) -> dict:
        return {
            "started": self.started,
            "finished": self.finished,
            "duration_seconds": round(self.finished - self.started, 3),
            "ok": self.ok_count,
            "failed": self.fail_count,
            "skipped": self.skip_count,
            "job": self.job,
            "results": [asdict(r) for r in self.results],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")
        md = path.with_suffix(".md")
        lines = [
            "# Batch summary",
            "",
            f"- Duration: {self.finished - self.started:.2f}s",
            f"- OK: {self.ok_count}",
            f"- Failed: {self.fail_count}",
            f"- Skipped: {self.skip_count}",
            "",
            "| Source | Status | Paths | Seconds | Outputs / Error |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in self.results:
            status = "skipped" if r.skipped else ("ok" if r.ok else "failed")
            detail = ", ".join(r.outputs) if r.ok else (r.error or "")
            lines.append(
                f"| `{Path(r.source).name}` | {status} | {r.path_count} | "
                f"{r.seconds:.2f} | {detail} |"
            )
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def collect_inputs(paths: list[Path] | Path) -> list[Path]:
    """Collect raster files from explicit paths and/or directories (non-recursive)."""
    items = [paths] if isinstance(paths, Path) else list(paths)
    found: list[Path] = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in OPEN_EXTENSIONS:
                    found.append(child)
        elif path.is_file() and path.suffix.lower() in OPEN_EXTENSIONS:
            found.append(path)
    # Preserve order, drop duplicates.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def resolve_output_path(
    output_dir: Path,
    source: Path,
    suffix: str,
    collision: CollisionPolicy,
) -> Path | None:
    base = output_dir / f"{source.stem}{suffix}"
    if not base.exists():
        return base
    if collision == CollisionPolicy.SKIP:
        return None
    if collision == CollisionPolicy.OVERWRITE:
        return base
    # rename
    index = 1
    while True:
        candidate = output_dir / f"{source.stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
        if index > 10_000:
            raise ExportError(f"Could not find a free filename for {source.name}")


def run_batch(
    job: BatchJob,
    *,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    summary_path: Path | None = None,
) -> BatchSummary:
    if not job.formats:
        raise ValueError("At least one export format is required.")
    if ExportFormat.EPS in job.formats and not inkscape_available():
        raise ExportError(
            "EPS was requested but Inkscape is not available. "
            "Install Inkscape or remove EPS from the batch formats."
        )

    job.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    results: list[BatchResult] = []
    total = len(job.inputs)

    for index, source in enumerate(job.inputs):
        if should_cancel and should_cancel():
            results.append(
                BatchResult(source=str(source), ok=False, error="Cancelled", skipped=True)
            )
            if on_progress:
                on_progress(index + 1, total, results[-1])
            break
        result = _process_one(source, job)
        results.append(result)
        if on_progress:
            on_progress(index + 1, total, result)
        if not result.ok and not result.skipped and not job.continue_on_error:
            break

    summary = BatchSummary(
        started=started,
        finished=time.time(),
        job={
            "output_dir": str(job.output_dir),
            "formats": [f.value for f in job.formats],
            "collision": job.collision.value,
            "continue_on_error": job.continue_on_error,
            "settings": job.settings.to_json(),
            "input_count": total,
        },
        results=results,
    )
    if summary_path is None:
        summary_path = job.output_dir / "batch_summary.json"
    summary.write(summary_path)
    return summary


def _process_one(source: Path, job: BatchJob) -> BatchResult:
    t0 = time.time()
    try:
        loaded = load_image(source)
        traced = run_trace_sync(loaded.image, job.settings)
        outputs: list[str] = []
        skipped_all = True
        for fmt in job.formats:
            suffix = f".{fmt.value}"
            dest = resolve_output_path(job.output_dir, source, suffix, job.collision)
            if dest is None:
                continue
            skipped_all = False
            if fmt == ExportFormat.SVG:
                export_svg(traced.document, dest)
            elif fmt == ExportFormat.PDF:
                export_pdf(traced.document, dest)
            elif fmt == ExportFormat.PNG:
                export_png_preview(traced.document, dest, background=None)
            elif fmt == ExportFormat.EPS:
                export_eps(traced.document, dest)
            elif fmt == ExportFormat.DXF:
                export_dxf(traced.document, dest)
            else:
                raise ExportError(f"Unsupported format: {fmt}")
            outputs.append(str(dest))
        if skipped_all and not outputs:
            return BatchResult(
                source=str(source),
                ok=True,
                skipped=True,
                seconds=time.time() - t0,
                path_count=traced.document.path_count,
                error="All outputs already existed (collision=skip).",
            )
        return BatchResult(
            source=str(source),
            ok=True,
            outputs=outputs,
            path_count=traced.document.path_count,
            seconds=time.time() - t0,
        )
    except (ImageLoadError, TraceError, ExportError, VectorizerError, ValueError, OSError) as exc:
        return BatchResult(
            source=str(source),
            ok=False,
            error=str(exc),
            seconds=time.time() - t0,
        )
