"""Background tracing via a subprocess so the GUI can cancel and stay alive."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import JobCancelled, TraceError
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.backend import TraceResult

# Re-entered by frozen .app / .exe builds instead of ``python -m …``.
TRACE_WORKER_FLAG = "--trace-worker"


def worker_process_arguments(
    *,
    input_path: Path,
    output_svg: Path,
    settings_path: Path,
    result_path: Path,
) -> list[str]:
    """Build argv for the tracing subprocess (after ``sys.executable``)."""
    job_args = [
        "--input",
        str(input_path),
        "--output-svg",
        str(output_svg),
        "--settings",
        str(settings_path),
        "--result",
        str(result_path),
    ]
    if getattr(sys, "frozen", False):
        return [TRACE_WORKER_FLAG, *job_args]
    return ["-m", "vectorizer.jobs.trace_worker", *job_args]


@dataclass
class JobHandle:
    token: int
    workdir: Path


class TraceJobRunner(QObject):
    started = Signal(int)
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._token = 0
        self._process: QProcess | None = None
        self._workdir: Path | None = None
        self._active_token: int | None = None
        self._cancel_requested = False

    @property
    def busy(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def start(self, image: Image.Image, settings: TraceSettings) -> JobHandle:
        if self.busy:
            raise TraceError("A tracing job is already running.")
        self._token += 1
        token = self._token
        self._cancel_requested = False
        workdir = Path(tempfile.mkdtemp(prefix="vectorizer-job-"))
        input_path = workdir / "input.png"
        output_svg = workdir / "output.svg"
        settings_path = workdir / "settings.json"
        result_path = workdir / "result.json"
        rgba = image.convert("RGBA")
        # Fast temp encode: worker reloads immediately; size vs CPU favors level 1.
        rgba.save(input_path, format="PNG", compress_level=1, optimize=False)
        settings_path.write_text(json.dumps(settings.to_json()), encoding="utf-8")

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            worker_process_arguments(
                input_path=input_path,
                output_svg=output_svg,
                settings_path=settings_path,
                result_path=result_path,
            )
        )
        env = QProcessEnvironment.systemEnvironment()
        if not getattr(sys, "frozen", False):
            pythonpath_parts = [p for p in sys.path if p]
            existing = env.value("PYTHONPATH")
            if existing:
                pythonpath_parts.append(existing)
            env.insert("PYTHONPATH", os.pathsep.join(pythonpath_parts))
        process.setProcessEnvironment(env)

        process.finished.connect(lambda code, status: self._on_finished(token, code, status, workdir, settings))
        process.errorOccurred.connect(lambda err: self._on_error(token, err, workdir))
        self._process = process
        self._workdir = workdir
        self._active_token = token
        process.start()
        if not process.waitForStarted(5000):
            self._cleanup(workdir)
            self._process = None
            raise TraceError("Could not start the tracing worker process.")
        self.started.emit(token)
        return JobHandle(token=token, workdir=workdir)

    def cancel(self) -> None:
        if not self.busy or self._process is None:
            return
        self._cancel_requested = True
        self._process.terminate()
        if not self._process.waitForFinished(800):
            self._process.kill()
            self._process.waitForFinished(800)

    def _on_error(self, token: int, error: QProcess.ProcessError, workdir: Path) -> None:
        if token != self._active_token:
            return
        if self._cancel_requested:
            return
        message = f"Tracing process error: {error}"
        self._finish_cleanup()
        self.failed.emit(token, message)

    def _on_finished(
        self,
        token: int,
        code: int,
        _status: QProcess.ExitStatus,
        workdir: Path,
        settings: TraceSettings,
    ) -> None:
        if token != self._active_token:
            self._cleanup(workdir)
            return
        cancel = self._cancel_requested
        result_path = workdir / "result.json"
        svg_path = workdir / "output.svg"
        payload = None
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = None
        svg_text = svg_path.read_text(encoding="utf-8") if svg_path.is_file() else ""
        self._finish_cleanup()
        if cancel:
            self.cancelled.emit(token)
            return
        if payload and payload.get("ok") and svg_text:
            try:
                document = parse_svg_document(svg_text, backend_name=str(payload.get("backend", "vtracer")))
                result = TraceResult(
                    document=document,
                    elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
                    settings=settings,
                    backend_name=document.backend_name,
                    warnings=tuple(payload.get("warnings") or ()),
                )
            except Exception as exc:
                self.failed.emit(token, str(exc))
                return
            self.succeeded.emit(token, result)
            return
        error = None
        if payload:
            error = payload.get("error")
        if not error:
            error = f"Tracing worker exited with code {code}."
        if code == 0 and not svg_text:
            error = "Tracing worker produced no SVG."
        self.failed.emit(token, error)

    def _finish_cleanup(self) -> None:
        if self._workdir is not None:
            self._cleanup(self._workdir)
        self._workdir = None
        self._process = None
        self._active_token = None
        self._cancel_requested = False

    @staticmethod
    def _cleanup(workdir: Path) -> None:
        shutil.rmtree(workdir, ignore_errors=True)


def run_trace_sync(image: Image.Image, settings: TraceSettings) -> TraceResult:
    """In-process tracing for CLI and tests. Does not touch Qt."""
    from vectorizer.vectorize.dispatch import trace_prepared

    return trace_prepared(image, settings)


def raise_if_cancelled(cancelled: bool) -> None:
    if cancelled:
        raise JobCancelled("Tracing was cancelled.")
