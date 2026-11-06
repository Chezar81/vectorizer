"""Full-preview progress overlay shown while loading or tracing."""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from vectorizer.gui.i18n import t, tf


class TraceProgressOverlay(QWidget):
    """Dimmed card over the preview area with stage text, bar, and ETA."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("traceProgressOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self._apply_dim_palette()
        # Sit above layout-managed siblings when shown.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()

        self._title = QLabel()
        self._title.setObjectName("traceProgressTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)

        self._stage = QLabel()
        self._stage.setObjectName("traceProgressStage")
        self._stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stage.setWordWrap(True)

        self._bar = QProgressBar()
        self._bar.setObjectName("traceProgressBar")
        self._bar.setRange(0, 1000)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFormat("%p%")
        self._bar.setMinimumWidth(260)

        self._eta = QLabel()
        self._eta.setObjectName("traceProgressEta")
        self._eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._eta.setWordWrap(True)

        self._hint = QLabel()
        self._hint.setObjectName("traceProgressHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)

        card = QFrame()
        card.setObjectName("traceProgressCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setAutoFillBackground(True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(12)
        card_layout.addWidget(self._title)
        card_layout.addWidget(self._stage)
        card_layout.addWidget(self._bar)
        card_layout.addWidget(self._eta)
        card_layout.addWidget(self._hint)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.addStretch(1)
        root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)

        self._started_at = 0.0
        self._fraction = 0.0
        self._title_key = "Vectorizing…"
        self._stage_key = "Tracing…"
        self._hint_key = "Press Cancel in the sidebar to stop."
        self._seed_seconds: float | None = None
        self._indeterminate = False
        self._show_eta = True
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._refresh_eta)

        if parent is not None:
            parent.installEventFilter(self)
            self._sync_geometry()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.parentWidget() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        }:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        if self.isVisible():
            self.raise_()

    def _apply_dim_palette(self) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(20, 22, 28, 160))
        self.setPalette(palette)

    def retranslate_ui(self) -> None:
        if not self.isVisible():
            return
        self._apply_texts()

    def begin(
        self,
        *,
        retrace: bool = False,
        seed_seconds: float | None = None,
    ) -> None:
        self.begin_busy(
            title=("Retracing segmentation…" if retrace else "Vectorizing…"),
            stage=("Retracing segmentation…" if retrace else "Tracing…"),
            hint="Press Cancel in the sidebar to stop.",
            indeterminate=False,
            show_eta=True,
            seed_seconds=seed_seconds,
        )

    def begin_busy(
        self,
        *,
        title: str,
        stage: str,
        hint: str = "",
        indeterminate: bool = False,
        show_eta: bool = True,
        seed_seconds: float | None = None,
    ) -> None:
        self._title_key = title
        self._stage_key = stage
        self._hint_key = hint
        self._indeterminate = indeterminate
        self._show_eta = show_eta and not indeterminate
        self._seed_seconds = seed_seconds if seed_seconds and seed_seconds > 0 else None
        self._started_at = time.perf_counter()
        self._fraction = 0.0
        if indeterminate:
            self._bar.setRange(0, 0)
            self._bar.setTextVisible(False)
        else:
            self._bar.setRange(0, 1000)
            self._bar.setValue(0)
            self._bar.setTextVisible(True)
            self._bar.setFormat("%p%")
        self._apply_dim_palette()
        self._apply_texts()
        self._sync_geometry()
        self.show()
        self.raise_()
        if self._show_eta:
            self._tick.start()
        else:
            self._tick.stop()

    def set_stage(self, stage: str, *, fraction: float | None = None) -> None:
        self._stage_key = stage
        if fraction is not None:
            if self._indeterminate:
                self._indeterminate = False
                self._bar.setRange(0, 1000)
                self._bar.setTextVisible(True)
                self._bar.setFormat("%p%")
            self._fraction = max(self._fraction, max(0.0, min(1.0, float(fraction))))
            self._bar.setValue(int(round(self._fraction * 1000)))
        if not self.isVisible():
            self._sync_geometry()
            self.show()
            self.raise_()
        self._apply_texts()

    def update_progress(self, fraction: float, stage: str) -> None:
        if self._indeterminate:
            self._indeterminate = False
            self._show_eta = True
            self._bar.setRange(0, 1000)
            self._bar.setTextVisible(True)
            self._bar.setFormat("%p%")
            if not self._tick.isActive():
                self._tick.start()
        self._fraction = max(self._fraction, max(0.0, min(1.0, float(fraction))))
        if stage:
            self._stage_key = stage
        self._bar.setValue(int(round(self._fraction * 1000)))
        if not self.isVisible():
            self._sync_geometry()
            self.show()
            self.raise_()
        self._apply_texts()

    def finish(self) -> None:
        self._tick.stop()
        self.hide()
        self._fraction = 0.0
        self._seed_seconds = None
        self._indeterminate = False
        self._show_eta = True

    def _apply_texts(self) -> None:
        self._title.setText(t(self._title_key))
        self._stage.setText(t(self._stage_key))
        self._hint.setText(t(self._hint_key) if self._hint_key else "")
        self._hint.setVisible(bool(self._hint_key))
        if self._show_eta:
            self._eta.setText(self._eta_text())
            self._eta.show()
        else:
            self._eta.setText("")
            self._eta.hide()

    def _refresh_eta(self) -> None:
        if not self.isVisible() or not self._show_eta:
            return
        # Soft advance while opaque backends sit still, so the bar never looks stuck.
        if self._fraction > 0.05 and self._fraction < 0.92:
            elapsed = max(0.001, time.perf_counter() - self._started_at)
            if self._seed_seconds and self._seed_seconds > 0.4:
                soft = min(0.90, elapsed / self._seed_seconds)
                if soft > self._fraction:
                    self._fraction = (self._fraction * 0.85) + (soft * 0.15)
                    self._bar.setValue(int(round(self._fraction * 1000)))
        self._eta.setText(self._eta_text())

    def _eta_text(self) -> str:
        elapsed = max(0.0, time.perf_counter() - self._started_at)
        remaining: float | None = None
        if self._fraction >= 0.04:
            total = elapsed / max(self._fraction, 0.04)
            remaining = max(0.0, total - elapsed)
        elif self._seed_seconds is not None:
            remaining = max(0.0, self._seed_seconds - elapsed)
        if remaining is None:
            return t("Estimating time…")
        if remaining < 1.0:
            return t("Almost done…")
        seconds = int(round(remaining))
        if seconds < 60:
            return tf("About {seconds}s remaining", seconds=seconds)
        minutes = seconds // 60
        secs = seconds % 60
        if secs == 0:
            return tf("About {minutes} min remaining", minutes=minutes)
        return tf(
            "About {minutes} min {seconds}s remaining",
            minutes=minutes,
            seconds=secs,
        )
