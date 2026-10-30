"""First-run canvas: what the app does, and how to get an image in."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QPixmap,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vectorizer.gui.canvas import first_drop_path
from vectorizer.gui.i18n import t
from vectorizer.resources import icon_path


class WelcomeView(QWidget):
    open_requested = Signal()
    paste_requested = Signal()
    path_dropped = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

        self._title = QLabel()
        self._title.setObjectName("welcomeTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lead = QLabel()
        self._lead.setObjectName("welcomeLead")
        self._lead.setWordWrap(True)
        self._lead.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lead.setMinimumWidth(0)
        self._lead.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self._step_labels: list[QLabel] = []
        steps = QVBoxLayout()
        steps.setSpacing(10)
        for number in ("1", "2", "3"):
            row = QWidget()
            row.setObjectName("welcomeRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)
            badge = QLabel(number)
            badge.setObjectName("stepIndex")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(22, 22)
            text = QLabel()
            text.setObjectName("welcomeStep")
            text.setWordWrap(True)
            text.setMinimumWidth(0)
            text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            line.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(text, 1)
            steps.addWidget(row)
            self._step_labels.append(text)

        self._formats = QLabel()
        self._formats.setObjectName("welcomeFormats")
        self._formats.setWordWrap(True)
        self._formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._formats.setMinimumWidth(0)
        self._formats.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.open_btn = QPushButton()
        self.open_btn.setObjectName("primaryButton")
        self.open_btn.clicked.connect(self.open_requested.emit)
        self.paste_btn = QPushButton()
        self.paste_btn.clicked.connect(self.paste_requested.emit)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.paste_btn)
        buttons.addStretch(1)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_file = icon_path("vectorizer.png")
        if icon_file.is_file():
            self._icon.setPixmap(
                QPixmap(str(icon_file)).scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        self._card = QFrame()
        self._card.setObjectName("welcomeCard")
        self._card.setMinimumWidth(260)
        self._card.setMaximumWidth(460)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(14)
        card_layout.addWidget(self._icon)
        card_layout.addWidget(self._title)
        card_layout.addWidget(self._lead)
        card_layout.addSpacing(4)
        card_layout.addLayout(steps)
        card_layout.addSpacing(4)
        card_layout.addLayout(buttons)
        card_layout.addWidget(self._formats)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.retranslate_ui()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        margin = 16 if event.size().width() < 420 else 28
        self.layout().setContentsMargins(margin, margin, margin, margin)
        width = max(220, min(460, event.size().width() - margin * 2))
        self._card.setFixedWidth(width)
        self._fit_copy()

    def _fit_copy(self) -> None:
        """Give wrapped labels a real width so long lines stay inside the card."""
        inner = max(160, self._card.width() - 56)
        step_width = max(120, inner - 32)
        self._size_wrapped(self._lead, inner)
        self._size_wrapped(self._formats, inner)
        for label in self._step_labels:
            self._size_wrapped(label, step_width)

    @staticmethod
    def _size_wrapped(label: QLabel, width: int) -> None:
        label.setFixedWidth(width)
        document = QTextDocument()
        document.setDefaultFont(label.font())
        document.setPlainText(label.text())
        document.setTextWidth(width)
        label.setFixedHeight(max(int(document.size().height()) + 2, label.fontMetrics().height()))

    def retranslate_ui(self) -> None:
        self._title.setText("Vectorizer")
        self._lead.setText(t("Turn a bitmap into editable vector paths."))
        steps = (
            t("Open an image, or drop one on this window."),
            t("Vectorize. Automatic mode picks the tracing settings."),
            t("Compare the result, then export SVG, PDF, or DXF."),
        )
        for label, text in zip(self._step_labels, steps, strict=True):
            label.setText(text)
        self.open_btn.setText(t("Open image…"))
        self.paste_btn.setText(t("Paste bitmap"))
        self._formats.setText(
            t("PNG, JPEG, WebP, GIF, BMP, TIFF, or a .vproj project.")
        )
        if self._card.width() > 0:
            self._fit_copy()

    def _set_drag_highlight(self, active: bool) -> None:
        self._card.setProperty("drag", "true" if active else "false")
        self._card.style().unpolish(self._card)
        self._card.style().polish(self._card)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if first_drop_path(event) is not None:
            event.acceptProposedAction()
            self._set_drag_highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if first_drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_drag_highlight(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_drag_highlight(False)
        path = first_drop_path(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.path_dropped.emit(path)
