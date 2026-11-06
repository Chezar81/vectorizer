from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PIL import Image

from vectorizer.domain.settings import ColorMode, EdgeTreatment, TraceSettings
from vectorizer.jobs.progress import parse_progress_line
from vectorizer.jobs.runner import worker_process_arguments
from vectorizer.raster.analyzer import ContentKind
from vectorizer.vectorize.dispatch import trace_prepared


def test_parse_progress_line_ok() -> None:
    parsed = parse_progress_line(
        '{"type":"progress","stage":"Tracing contours…","fraction":0.42}\n'
    )
    assert parsed == ("Tracing contours…", 0.42)


def test_parse_progress_line_rejects_noise() -> None:
    assert parse_progress_line("hello") is None
    assert parse_progress_line('{"type":"other"}') is None
    assert parse_progress_line("{not-json") is None


def test_worker_argv_includes_meta() -> None:
    args = worker_process_arguments(
        input_path=Path("in.png"),
        output_svg=Path("out.svg"),
        settings_path=Path("settings.json"),
        result_path=Path("result.json"),
        meta_path=Path("meta.json"),
    )
    assert "--meta" in args
    assert "meta.json" in args


def test_content_kind_hint_skips_gradient_reanalysis() -> None:
    image = Image.new("RGBA", (8, 8), (120, 140, 200, 255))
    settings = TraceSettings(
        edge_treatment=EdgeTreatment.PHOTO,
        target_colors=6,
    ).validated()
    with patch(
        "vectorizer.raster.analyzer.analyze_image",
        side_effect=AssertionError("analyze_image should not run"),
    ):
        with patch(
            "vectorizer.vectorize.dispatch.GradientTracer.trace",
            return_value=_dummy_result(settings, "gradient"),
        ) as gradient_trace:
            with patch(
                "vectorizer.vectorize.dispatch.VTracerBackend.trace",
                return_value=_dummy_result(settings, "vtracer"),
            ):
                result = trace_prepared(
                    image, settings, content_kind=ContentKind.GRADIENT.value
                )
    assert result.backend_name == "gradient"
    gradient_trace.assert_called_once()


def test_started_signal_is_deferred_until_after_start_returns() -> None:
    """started must not fire synchronously inside start() before the token is stored."""
    import os
    from unittest.mock import MagicMock

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication

    from vectorizer.jobs.runner import TraceJobRunner

    app = QApplication.instance() or QApplication(["vectorizer-progress-race"])
    runner = TraceJobRunner()
    order: list[str] = []

    def on_started(token: int) -> None:
        order.append(f"started:{token}")

    runner.started.connect(on_started)

    process = MagicMock()
    process.state.return_value = QProcess.ProcessState.Running
    process.waitForStarted.return_value = True
    process.readAllStandardOutput.return_value = b""

    from PIL import Image
    from vectorizer.domain.settings import TraceSettings

    real_qprocess = TraceJobRunner.start.__globals__["QProcess"]

    class FakeProcess(real_qprocess):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._running = False

        def start(self, *args, **kwargs):
            self._running = True

        def waitForStarted(self, _ms=30000):
            return True

        def state(self):
            return (
                QProcess.ProcessState.Running
                if self._running
                else QProcess.ProcessState.NotRunning
            )

        def terminate(self):
            self._running = False

        def kill(self):
            self._running = False

        def waitForFinished(self, _ms=30000):
            self._running = False
            return True

    import vectorizer.jobs.runner as runner_mod

    monkey_process = FakeProcess
    original = runner_mod.QProcess
    runner_mod.QProcess = monkey_process  # type: ignore[misc]
    try:
        image = Image.new("RGBA", (4, 4), (0, 0, 0, 255))
        handle = runner.start(image, TraceSettings().validated())
        order.append(f"returned:{handle.token}")
        app.processEvents()
    finally:
        runner_mod.QProcess = original  # type: ignore[misc]
        if runner.busy:
            runner.cancel()
        app.processEvents()

    assert order[0].startswith("returned:")
    assert order[1].startswith("started:")
    assert order[0].split(":")[1] == order[1].split(":")[1]


def test_progress_callback_receives_stages() -> None:
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
    settings = TraceSettings(
        edge_treatment=EdgeTreatment.HARD,
        colormode=ColorMode.BINARY,
    ).validated()
    events: list[tuple[str, float]] = []

    def on_progress(stage: str, fraction: float) -> None:
        events.append((stage, fraction))

    result = trace_prepared(image, settings, on_progress=on_progress)
    assert result.document.path_count >= 0
    assert events
    assert events[0][1] <= events[-1][1]
    assert events[-1][1] == 1.0


def _dummy_result(settings: TraceSettings, backend: str):
    from vectorizer.domain.document import VectorDocument
    from vectorizer.vectorize.backend import TraceResult

    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>'
    document = VectorDocument(
        width=8,
        height=8,
        view_box=(0, 0, 8, 8),
        groups=(),
        raw_svg=svg,
        backend_name=backend,
        path_count=0,
        source_notes=(),
    )
    return TraceResult(
        document=document,
        elapsed_seconds=0.01,
        settings=settings,
        backend_name=backend,
    )
