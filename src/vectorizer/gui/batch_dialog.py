"""Batch processing dialog. Runs work on a QThread to keep the UI responsive."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vectorizer.batch.engine import (
    BatchJob,
    BatchResult,
    BatchSummary,
    CollisionPolicy,
    ExportFormat,
    collect_inputs,
    run_batch,
)
from vectorizer.domain.settings import TraceSettings
from vectorizer.export.eps import inkscape_available
from vectorizer.gui.i18n import image_file_filter, t, tf
from vectorizer.gui.preferences import current_preferences, update_preferences
from vectorizer.presets import list_presets, load_preset


class _BatchWorker(QThread):
    progress = Signal(int, int, object)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, job: BatchJob, summary_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._job = job
        self._summary_path = summary_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: N802
        try:
            summary = run_batch(
                self._job,
                on_progress=lambda done, total, result: self.progress.emit(done, total, result),
                should_cancel=lambda: self._cancel,
                summary_path=self._summary_path,
            )
            self.finished_ok.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))


class BatchDialog(QDialog):
    def __init__(self, parent: QWidget | None, settings: TraceSettings) -> None:
        super().__init__(parent)
        self.resize(720, 560)
        self._settings = settings
        self._worker: _BatchWorker | None = None
        self._files: list[Path] = []

        self.input_edit = QLineEdit()
        self.browse_in = QPushButton()
        self.browse_in.clicked.connect(self._browse_input)
        self.add_files_btn = QPushButton()
        self.add_files_btn.clicked.connect(self._add_files)
        self.clear_files_btn = QPushButton()
        self.clear_files_btn.clicked.connect(self._clear_files)

        self.output_edit = QLineEdit()
        self.browse_out = QPushButton()
        self.browse_out.clicked.connect(self._browse_output)

        self.file_list = QListWidget()

        prefs = current_preferences()

        self.fmt_svg = QCheckBox()
        self.fmt_pdf = QCheckBox()
        self.fmt_png = QCheckBox()
        self.fmt_dxf = QCheckBox()
        self.fmt_eps = QCheckBox()
        self.fmt_svg.setChecked(prefs.export_svg)
        self.fmt_pdf.setChecked(prefs.export_pdf)
        self.fmt_png.setChecked(prefs.export_png)
        self.fmt_dxf.setChecked(prefs.export_dxf)
        self.fmt_eps.setChecked(prefs.export_eps)
        if not any(
            (
                prefs.export_svg,
                prefs.export_pdf,
                prefs.export_png,
                prefs.export_dxf,
                prefs.export_eps,
            )
        ):
            self.fmt_svg.setChecked(True)
        if not inkscape_available():
            self.fmt_eps.setEnabled(False)
            if self.fmt_eps.isChecked() and not any(
                b.isChecked()
                for b in (self.fmt_svg, self.fmt_pdf, self.fmt_png, self.fmt_dxf)
            ):
                self.fmt_svg.setChecked(True)
                self.fmt_eps.setChecked(False)

        self.collision = QComboBox()
        self.preset = QComboBox()
        self.preset.addItem("", None)
        for name in list_presets():
            self.preset.addItem(name, name)

        self.continue_on_error = QCheckBox()
        self.continue_on_error.setChecked(prefs.batch_continue_on_error)
        if prefs.batch_input_dir:
            self.input_edit.setText(prefs.batch_input_dir)
        if prefs.batch_output_dir:
            self.output_edit.setText(prefs.batch_output_dir)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status = QLabel()
        self.status.setWordWrap(True)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("primaryButton")
        self.cancel_btn = QPushButton()
        self.cancel_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)

        in_row = QHBoxLayout()
        in_row.addWidget(self.input_edit, 1)
        in_row.addWidget(self.browse_in)
        in_row.addWidget(self.add_files_btn)
        in_row.addWidget(self.clear_files_btn)

        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(self.browse_out)

        self.fmt_box = QGroupBox()
        fmt_row = QHBoxLayout(self.fmt_box)
        for w in (self.fmt_svg, self.fmt_pdf, self.fmt_png, self.fmt_dxf, self.fmt_eps):
            fmt_row.addWidget(w)
        fmt_row.addStretch(1)

        form = QFormLayout()
        self._input_label = QLabel()
        self._files_label = QLabel()
        self._output_label = QLabel()
        self._collisions_label = QLabel()
        self._preset_label = QLabel()
        form.addRow(self._input_label, in_row)
        form.addRow(self._files_label, self.file_list)
        form.addRow(self._output_label, out_row)
        form.addRow(self.fmt_box)
        form.addRow(self._collisions_label, self.collision)
        form.addRow(self._preset_label, self.preset)
        form.addRow(self.continue_on_error)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self.retranslate_ui()
        # Apply collision after labels are filled so findData works.
        for i in range(self.collision.count()):
            if self.collision.itemData(i) == prefs.batch_collision:
                self.collision.setCurrentIndex(i)
                break
        if prefs.batch_input_dir:
            self._refresh_from_folder()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("Batch vectorize"))
        self.input_edit.setPlaceholderText(
            t("Input folder or leave empty and add files…")
        )
        self.browse_in.setText(t("Browse folder…"))
        self.add_files_btn.setText(t("Add files…"))
        self.clear_files_btn.setText(t("Clear"))
        self.browse_out.setText(t("Browse…"))
        self.fmt_svg.setText(t("SVG"))
        self.fmt_pdf.setText(t("PDF"))
        self.fmt_png.setText(t("PNG preview"))
        self.fmt_dxf.setText(t("DXF (outlines)"))
        self.fmt_eps.setText(t("EPS (Inkscape)"))
        if not inkscape_available():
            self.fmt_eps.setToolTip(
                t("Inkscape was not found on PATH. Install it to enable EPS export.")
            )
        else:
            self.fmt_eps.setToolTip(
                t("Uses Inkscape with a timeout and argv-only invocation.")
            )
        current_collision = self.collision.currentData()
        self.collision.blockSignals(True)
        self.collision.clear()
        self.collision.addItem(t("Rename (file_1.svg)"), CollisionPolicy.RENAME)
        self.collision.addItem(t("Skip existing"), CollisionPolicy.SKIP)
        self.collision.addItem(t("Overwrite"), CollisionPolicy.OVERWRITE)
        if current_collision is not None:
            idx = self.collision.findData(current_collision)
            if idx >= 0:
                self.collision.setCurrentIndex(idx)
        self.collision.blockSignals(False)
        # First preset item is the sidebar-settings sentinel.
        if self.preset.count() > 0 and self.preset.itemData(0) is None:
            self.preset.setItemText(0, t("(current sidebar settings)"))
        self.continue_on_error.setText(t("Continue on error"))
        self.status.setText(t("Select inputs and an output folder."))
        self.start_btn.setText(t("Start batch"))
        self.cancel_btn.setText(t("Cancel"))
        self.fmt_box.setTitle(t("Export formats"))
        self._input_label.setText(t("Input"))
        self._files_label.setText(t("Files"))
        self._output_label.setText(t("Output folder"))
        self._collisions_label.setText(t("Collisions"))
        self._preset_label.setText(t("Settings preset"))

    def _browse_input(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("Input folder"))
        if path:
            self.input_edit.setText(path)
            self._refresh_from_folder()

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("Output folder"))
        if path:
            self.output_edit.setText(path)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("Add images"),
            "",
            image_file_filter(),
        )
        for path in paths:
            p = Path(path)
            if p not in self._files:
                self._files.append(p)
        self._sync_list()

    def _clear_files(self) -> None:
        self._files.clear()
        self._sync_list()

    def _refresh_from_folder(self) -> None:
        folder = self.input_edit.text().strip()
        if not folder:
            return
        collected = collect_inputs(Path(folder))
        for path in collected:
            if path not in self._files:
                self._files.append(path)
        self._sync_list()

    def _sync_list(self) -> None:
        self.file_list.clear()
        for path in self._files:
            self.file_list.addItem(str(path))
        self.status.setText(tf("{count} file(s) queued.", count=len(self._files)))

    def _selected_formats(self) -> list[ExportFormat]:
        formats: list[ExportFormat] = []
        if self.fmt_svg.isChecked():
            formats.append(ExportFormat.SVG)
        if self.fmt_pdf.isChecked():
            formats.append(ExportFormat.PDF)
        if self.fmt_png.isChecked():
            formats.append(ExportFormat.PNG)
        if self.fmt_dxf.isChecked():
            formats.append(ExportFormat.DXF)
        if self.fmt_eps.isChecked():
            formats.append(ExportFormat.EPS)
        return formats

    def _resolve_settings(self) -> TraceSettings:
        name = self.preset.currentData()
        if name:
            return load_preset(str(name))
        return self._settings

    def _start(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._refresh_from_folder()
        if not self._files:
            QMessageBox.warning(self, t("Batch"), t("Add at least one input image."))
            return
        out = self.output_edit.text().strip()
        if not out:
            QMessageBox.warning(self, t("Batch"), t("Choose an output folder."))
            return
        formats = self._selected_formats()
        if not formats:
            QMessageBox.warning(self, t("Batch"), t("Select at least one export format."))
            return
        try:
            settings = self._resolve_settings()
        except Exception as exc:
            QMessageBox.warning(self, t("Batch"), str(exc))
            return
        collision = self.collision.currentData()
        continue_on_error = self.continue_on_error.isChecked()
        job = BatchJob(
            inputs=tuple(self._files),
            output_dir=Path(out),
            settings=settings,
            formats=tuple(formats),
            collision=collision,
            continue_on_error=continue_on_error,
        )
        update_preferences(
            export_svg=self.fmt_svg.isChecked(),
            export_pdf=self.fmt_pdf.isChecked(),
            export_png=self.fmt_png.isChecked(),
            export_dxf=self.fmt_dxf.isChecked(),
            export_eps=self.fmt_eps.isChecked(),
            batch_collision=collision,
            batch_continue_on_error=continue_on_error,
            batch_input_dir=self.input_edit.text().strip(),
            batch_output_dir=out,
        )
        summary_path = Path(out) / "batch_summary.json"
        self.progress.setRange(0, len(self._files))
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status.setText(t("Batch running…"))
        self._worker = _BatchWorker(job, summary_path, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.status.setText(t("Cancelling after the current file…"))

    def _on_progress(self, done: int, total: int, result: object) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        if isinstance(result, BatchResult):
            name = Path(result.source).name
            if result.skipped:
                msg = tf("{done}/{total}: skipped {name}", done=done, total=total, name=name)
            elif result.ok:
                msg = tf(
                    "{done}/{total}: ok {name} ({paths} paths)",
                    done=done,
                    total=total,
                    name=name,
                    paths=result.path_count,
                )
            else:
                msg = tf(
                    "{done}/{total}: failed {name}: {error}",
                    done=done,
                    total=total,
                    name=name,
                    error=result.error,
                )
            self.status.setText(msg)

    def _on_finished(self, summary: object) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if not isinstance(summary, BatchSummary):
            return
        summary_path = f"{summary.job.get('output_dir')}/batch_summary.json"
        self.status.setText(
            tf(
                "Done. OK={ok} failed={failed} skipped={skipped}. Summary: {summary}",
                ok=summary.ok_count,
                failed=summary.fail_count,
                skipped=summary.skip_count,
                summary=summary_path,
            )
        )
        QMessageBox.information(
            self,
            t("Batch complete"),
            tf(
                "Processed with {ok} ok, {failed} failed, {skipped} skipped.\n"
                "Summary written next to the outputs.",
                ok=summary.ok_count,
                failed=summary.fail_count,
                skipped=summary.skip_count,
            ),
        )

    def _on_failed(self, message: str) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status.setText(message)
        QMessageBox.warning(self, t("Batch failed"), message)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)
