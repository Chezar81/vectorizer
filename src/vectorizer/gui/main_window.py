"""Main window: menus, canvas, settings, and job orchestration. No tracing math."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSettings, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QShowEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QComboBox,
    QVBoxLayout,
    QWidget,
)

from vectorizer import __version__
from vectorizer.domain.settings import (
    AutomaticQuality,
    DxfCurveMode,
    TraceSettings,
    WorkflowMode,
)
from vectorizer.errors import ExportError, ImageLoadError, ProjectError, TraceError, VectorizerError
from vectorizer.export.dxf import export_dxf
from vectorizer.export.eps import export_eps, inkscape_available
from vectorizer.export.pdf import export_pdf
from vectorizer.export.png import export_png_preview
from vectorizer.export.svg import export_svg
from vectorizer.gui.batch_dialog import BatchDialog
from vectorizer.gui.canvas import ImageCanvas, first_drop_path
from vectorizer.gui.compare_view import SplitCompare, SyncSideBySide
from vectorizer.gui.i18n import (
    SUPPORTED_LANGUAGES,
    current_language,
    image_file_filter,
    load_language,
    project_file_filter,
    set_language,
    t,
    tf,
)
from vectorizer.gui.preferences import (
    clear_ui_chrome,
    current_preferences,
    load_preferences,
    preferences_changed,
    update_preferences,
)
from vectorizer.gui.preferences_dialog import PreferencesDialog
from vectorizer.gui.qtutil import pil_to_qpixmap, qimage_to_png_bytes
from vectorizer.gui.seg_editor import SegmentationEditor
from vectorizer.gui.session_history import SessionHistory, SessionSnapshot
from vectorizer.gui.settings_panel import SettingsPanel
from vectorizer.gui.welcome import WelcomeView
from vectorizer.jobs.runner import TraceJobRunner
from vectorizer.project.io import ProjectData, load_project, save_project
from vectorizer.raster.analyzer import analyze_image
from vectorizer.raster.loader import LoadedImage, load_image, load_image_from_bytes
from vectorizer.raster.palette import suggest_palettes
from vectorizer.raster.preprocess import preprocess_image
from vectorizer.resources import icon_path
from vectorizer.segmentation.build import build_segmentation
from vectorizer.svg.edit import delete_shape_at, remove_background_shapes
from vectorizer.svg.parse import parse_svg_document
from vectorizer.svg.recolor import recolor_document
from vectorizer.vectorize.backend import TraceResult

MAX_RECENT = 10
# Fixed sidebar width: fits labels + "Pick from image" / preset buttons without clipping.
SIDEBAR_WIDTH = 420
GOLDEN_RATIO = (1.0 + 5.0**0.5) / 2.0
SCREEN_MARGIN = 24
MIN_CANVAS_WIDTH = 480


def _load_app_icon() -> QIcon:
    icon = QIcon()
    for name in ("vectorizer-256.png", "vectorizer.png", "vectorizer.svg"):
        path = icon_path(name)
        if path.is_file():
            icon.addFile(str(path))
    return icon


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vectorizer")
        self.setAcceptDrops(True)
        app_icon = _load_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self._settings_store = QSettings("Vectorizer", "Vectorizer")
        load_language()
        prefs = load_preferences()
        # Always apply golden-ratio + sidebar-fit size on first show (ignore any
        # previously saved window geometry so the designed default stays stable).
        self._pending_default_geometry = True
        self.resize(int(round(720 * GOLDEN_RATIO)), 720)
        self._loaded: LoadedImage | None = None
        self._result: TraceResult | None = None
        self._current_token: int | None = None
        self._retrace_from_segmentation = False
        self._project_path: Path | None = None
        self._original_pixmap: QPixmap | None = None
        self._picking_background = False
        self._picking_palette = False
        self._delete_shapes = False
        self._idle_status = True
        self._history = SessionHistory(max_steps=prefs.session_history_steps)
        self._export_dir = prefs.resolved_export_dir()
        self._persist_sidebar = False

        self.panel = SettingsPanel()
        self.original_canvas = ImageCanvas()
        self.vector_canvas = ImageCanvas()
        self.side_by_side = SyncSideBySide()
        self.split_compare = SplitCompare()
        self.seg_editor = SegmentationEditor()
        self._restore_sidebar_defaults(prefs)

        tabs = QTabWidget()
        tabs.addTab(self.original_canvas, "")
        tabs.addTab(self.vector_canvas, "")
        tabs.addTab(self.side_by_side, "")
        tabs.addTab(self.split_compare, "")
        tabs.addTab(self.seg_editor, "")
        self.preview_tabs = tabs
        # Allow the window to shrink to golden-ratio defaults on smaller screens.
        tabs.setMinimumWidth(MIN_CANVAS_WIDTH)
        self.seg_editor.setMinimumWidth(MIN_CANVAS_WIDTH)
        self.side_by_side.setMinimumWidth(MIN_CANVAS_WIDTH)
        self.split_compare.setMinimumWidth(MIN_CANVAS_WIDTH)

        self.welcome = WelcomeView()
        self.welcome.open_requested.connect(self.open_file_dialog)
        self.welcome.paste_requested.connect(self.paste_clipboard)
        self.welcome.path_dropped.connect(self._open_dropped_path)
        self._preview_stack = QStackedWidget()
        self._preview_stack.addWidget(self.welcome)
        self._preview_stack.addWidget(tabs)
        self._preview_stack.setMinimumWidth(MIN_CANVAS_WIDTH)
        self._mode_banner = QLabel()
        self._mode_banner.setObjectName("modeBanner")
        self._mode_banner.setWordWrap(True)
        self._mode_banner.hide()

        self.panel.setFixedWidth(SIDEBAR_WIDTH)
        central = QWidget()
        central.setMinimumWidth(SIDEBAR_WIDTH + MIN_CANVAS_WIDTH)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.panel)
        stage = QWidget()
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)
        stage_layout.addWidget(self._mode_banner)
        stage_layout.addWidget(self._preview_stack, 1)
        central_layout.addWidget(stage, 1)
        self.setCentralWidget(central)
        self.setMinimumSize(640, 360)

        self._progress = QProgressBar()
        self._progress.setMaximumWidth(180)
        self._progress.setRange(0, 0)
        self._progress.hide()
        self._status_info = QLabel()
        self.statusBar().addWidget(self._status_info, 1)
        self.statusBar().addPermanentWidget(self._progress)

        self.runner = TraceJobRunner(self)
        self.runner.started.connect(self._on_job_started)
        self.runner.succeeded.connect(self._on_job_succeeded)
        self.runner.failed.connect(self._on_job_failed)
        self.runner.cancelled.connect(self._on_job_cancelled)

        self.panel.vectorize_requested.connect(self.vectorize)
        self.panel.cancel_requested.connect(self.runner.cancel)
        self.panel.palette_recolor_requested.connect(self._apply_recolor)
        self.panel.pick_background_requested.connect(self._start_background_pick)
        self.panel.pick_trace_color_requested.connect(self._start_palette_pick)
        self.panel.automatic_quality_changed.connect(self._apply_automatic_quality)
        self.panel.settings_changed.connect(self._on_sidebar_settings_changed)
        self.original_canvas.pixel_clicked.connect(self._on_original_pixel_clicked)
        self.vector_canvas.pixel_clicked.connect(self._on_vector_pixel_clicked)
        self.side_by_side.right.pixel_clicked.connect(self._on_vector_pixel_clicked)
        self.seg_editor.retrace_requested.connect(self.retrace_segmentation)
        self.seg_editor.rebuild_btn.clicked.connect(self.rebuild_segmentation)
        self.seg_editor.status_message.connect(self.statusBar().showMessage)
        self.seg_editor.map_changed.connect(self._on_seg_changed)
        self.preview_tabs.currentChanged.connect(lambda _i: self._update_undo_actions())
        for canvas in self._drop_canvases():
            canvas.path_dropped.connect(self._open_dropped_path)
        preferences_changed().connect(self._on_preferences_changed)

        self._build_menus()
        self.retranslate_ui()
        self._apply_recent_menu()
        self._update_undo_actions()
        self._update_file_drop_enabled()
        self._update_eps_availability()
        self._persist_sidebar = True

    def _build_menus(self) -> None:
        self._file_menu = self.menuBar().addMenu("")
        self.open_act = QAction(self)
        self.open_act.setShortcut(QKeySequence.StandardKey.Open)
        self.open_act.triggered.connect(self.open_file_dialog)
        self._file_menu.addAction(self.open_act)

        self.paste_act = QAction(self)
        self.paste_act.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_act.triggered.connect(self.paste_clipboard)
        self._file_menu.addAction(self.paste_act)

        self.recent_menu = self._file_menu.addMenu("")
        self._file_menu.addSeparator()

        self.open_proj_act = QAction(self)
        self.open_proj_act.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.open_proj_act.triggered.connect(self.open_project_dialog)
        self._file_menu.addAction(self.open_proj_act)
        self.save_proj_act = QAction(self)
        self.save_proj_act.setShortcut(QKeySequence("Ctrl+S"))
        self.save_proj_act.triggered.connect(self.save_project_dialog)
        self._file_menu.addAction(self.save_proj_act)
        self._file_menu.addSeparator()

        self.export_svg_act = QAction(self)
        self.export_svg_act.setShortcut(QKeySequence("Ctrl+E"))
        self.export_svg_act.triggered.connect(self.export_svg_dialog)
        self._file_menu.addAction(self.export_svg_act)

        self.export_pdf_act = QAction(self)
        self.export_pdf_act.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.export_pdf_act.triggered.connect(self.export_pdf_dialog)
        self._file_menu.addAction(self.export_pdf_act)

        self.export_png_act = QAction(self)
        self.export_png_act.triggered.connect(self.export_png_dialog)
        self._file_menu.addAction(self.export_png_act)

        self.export_dxf_act = QAction(self)
        self.export_dxf_act.triggered.connect(self.export_dxf_dialog)
        self._file_menu.addAction(self.export_dxf_act)

        self.export_eps_act = QAction(self)
        self.export_eps_act.triggered.connect(self.export_eps_dialog)
        if not inkscape_available():
            self.export_eps_act.setEnabled(False)
        self._file_menu.addAction(self.export_eps_act)
        self._file_menu.addSeparator()

        self.batch_act = QAction(self)
        self.batch_act.setShortcut(QKeySequence("Ctrl+B"))
        self.batch_act.triggered.connect(self.open_batch_dialog)
        self._file_menu.addAction(self.batch_act)
        self._file_menu.addSeparator()

        self.quit_act = QAction(self)
        self.quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_act.triggered.connect(self.close)
        self._file_menu.addAction(self.quit_act)

        self._edit_menu = self.menuBar().addMenu("")
        self.undo_act = QAction(self)
        self.undo_act.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_act.triggered.connect(self.undo)
        self._edit_menu.addAction(self.undo_act)
        self.redo_act = QAction(self)
        self.redo_act.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_act.triggered.connect(self.redo)
        self._edit_menu.addAction(self.redo_act)
        self._edit_menu.addSeparator()
        self.delete_shape_act = QAction(self)
        self.delete_shape_act.setCheckable(True)
        self.delete_shape_act.toggled.connect(self._toggle_delete_shapes)
        self._edit_menu.addAction(self.delete_shape_act)
        self.remove_bg_shape_act = QAction(self)
        self.remove_bg_shape_act.triggered.connect(self._remove_result_background)
        self._edit_menu.addAction(self.remove_bg_shape_act)

        self._view_menu = self.menuBar().addMenu("")
        self.fit_act = QAction(self)
        self.fit_act.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_act.triggered.connect(self.fit_views)
        self._view_menu.addAction(self.fit_act)
        self.actual_act = QAction(self)
        self.actual_act.setShortcut(QKeySequence("Ctrl+1"))
        self.actual_act.triggered.connect(self.actual_size)
        self._view_menu.addAction(self.actual_act)
        self._view_menu.addSeparator()
        from vectorizer.gui.theme import (
            APPEARANCE_DARK,
            APPEARANCE_LIGHT,
            APPEARANCE_SYSTEM,
            appearance_mode,
        )

        self._appearance_actions: dict[str, QAction] = {}
        self._appearance_group = QActionGroup(self)
        self._appearance_group.setExclusive(True)
        current_appearance = appearance_mode()
        for mode in (APPEARANCE_SYSTEM, APPEARANCE_LIGHT, APPEARANCE_DARK):
            act = QAction(self)
            act.setCheckable(True)
            act.setData(mode)
            act.setChecked(mode == current_appearance)
            act.triggered.connect(lambda checked=False, m=mode: self._set_appearance(m))
            self._appearance_group.addAction(act)
            self._view_menu.addAction(act)
            self._appearance_actions[mode] = act

        self._run_menu = self.menuBar().addMenu("")
        self.vec_act = QAction(self)
        self.vec_act.setShortcut(QKeySequence("F5"))
        self.vec_act.triggered.connect(self.vectorize)
        self._run_menu.addAction(self.vec_act)
        self.retrace_act = QAction(self)
        self.retrace_act.setShortcut(QKeySequence("F6"))
        self.retrace_act.triggered.connect(self.retrace_segmentation)
        self._run_menu.addAction(self.retrace_act)
        self.rebuild_act = QAction(self)
        self.rebuild_act.triggered.connect(self.rebuild_segmentation)
        self._run_menu.addAction(self.rebuild_act)
        self.cancel_act = QAction(self)
        self.cancel_act.setShortcut(QKeySequence("Esc"))
        self.cancel_act.triggered.connect(self._cancel_current)
        self._run_menu.addAction(self.cancel_act)

        self._settings_menu = self.menuBar().addMenu("")
        self.language_menu = self._settings_menu.addMenu("")
        self._lang_actions: dict[str, QAction] = {}
        for code, _label in SUPPORTED_LANGUAGES:
            act = QAction(self)
            act.setCheckable(True)
            act.setData(code)
            act.triggered.connect(lambda checked=False, c=code: self._set_ui_language(c))
            self.language_menu.addAction(act)
            self._lang_actions[code] = act
        self._settings_menu.addSeparator()
        self.prefs_act = QAction(self)
        self.prefs_act.triggered.connect(self.open_preferences_dialog)
        self._settings_menu.addAction(self.prefs_act)

        self._help_menu = self.menuBar().addMenu("")
        self.about_act = QAction(self)
        self.about_act.triggered.connect(self._about)
        self._help_menu.addAction(self.about_act)

        self.toolbar = QToolBar()
        self.toolbar.setObjectName("mainToolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.actual_act.setIconText("1:1")
        self.addToolBar(self.toolbar)
        self.toolbar.addAction(self.open_act)
        self.toolbar.addAction(self.save_proj_act)
        self.toolbar.addAction(self.export_svg_act)
        self.toolbar.addAction(self.export_pdf_act)
        self.toolbar.addAction(self.batch_act)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.undo_act)
        self.toolbar.addAction(self.redo_act)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.vec_act)
        self.toolbar.addAction(self.retrace_act)
        self.toolbar.addAction(self.fit_act)
        self.toolbar.addAction(self.actual_act)
        vectorize_button = self.toolbar.widgetForAction(self.vec_act)
        if vectorize_button is not None:
            vectorize_button.setObjectName("primaryTool")

    def retranslate_ui(self) -> None:
        """Refresh all chrome text for the active language."""
        self._file_menu.setTitle(t("&File"))
        self.open_act.setText(t("&Open…"))
        self.paste_act.setText(t("Paste &bitmap"))
        self.recent_menu.setTitle(t("Open &recent"))
        self.open_proj_act.setText(t("Open &project…"))
        self.save_proj_act.setText(t("Save p&roject…"))
        self.export_svg_act.setText(t("Export &SVG…"))
        self.export_pdf_act.setText(t("Export &PDF…"))
        self.export_png_act.setText(t("Export P&NG preview…"))
        self.export_dxf_act.setText(t("Export D&XF…"))
        self.export_eps_act.setText(t("Export EP&S…"))
        self._update_eps_availability()
        self.batch_act.setText(t("&Batch process…"))
        self.quit_act.setText(t("&Quit"))

        self._edit_menu.setTitle(t("&Edit"))
        self.delete_shape_act.setText(t("Delete clicked shape"))
        self.delete_shape_act.setToolTip(
            t("Click a filled shape on the vector preview to remove it.")
        )
        self.remove_bg_shape_act.setText(t("Remove background shapes"))
        self.remove_bg_shape_act.setToolTip(
            t("Drop finished paths whose fill matches the background color.")
        )
        self._view_menu.setTitle(t("&View"))
        self.fit_act.setText(t("&Fit to window"))
        self.actual_act.setText(t("&Actual size"))
        from vectorizer.gui.theme import APPEARANCE_DARK, APPEARANCE_LIGHT, APPEARANCE_SYSTEM

        self._appearance_actions[APPEARANCE_SYSTEM].setText(t("&System setting"))
        self._appearance_actions[APPEARANCE_LIGHT].setText(t("&Light mode"))
        self._appearance_actions[APPEARANCE_DARK].setText(t("&Dark mode"))

        self._run_menu.setTitle(t("&Run"))
        self.vec_act.setText(t("&Vectorize"))
        self.retrace_act.setText(t("&Retrace segmentation"))
        self.rebuild_act.setText(t("Rebuild &segmentation"))
        self.cancel_act.setText(t("&Cancel"))

        self._settings_menu.setTitle(t("&Settings"))
        self.language_menu.setTitle(t("&Language"))
        for code, label in SUPPORTED_LANGUAGES:
            act = self._lang_actions[code]
            act.setText(label)
            act.setChecked(code == current_language())
        self.prefs_act.setText(t("&Preferences…"))

        self._help_menu.setTitle(t("&Help"))
        self.about_act.setText(t("&About Vectorizer"))

        self.toolbar.setWindowTitle(t("Main"))
        self.open_act.setIconText(t("Open"))
        self.save_proj_act.setIconText(t("Save"))
        self.export_svg_act.setIconText(t("SVG"))
        self.export_pdf_act.setIconText(t("PDF"))
        self.batch_act.setIconText(t("Batch"))
        self.undo_act.setIconText(t("Undo"))
        self.redo_act.setIconText(t("Redo"))
        self.vec_act.setIconText(t("Vectorize"))
        self.retrace_act.setIconText(t("Retrace"))
        self.fit_act.setIconText(t("Fit"))
        self.open_act.setToolTip(t("Open an image (Ctrl+O)"))
        self.save_proj_act.setToolTip(t("Save the project (Ctrl+S)"))
        self.export_svg_act.setToolTip(t("Export SVG (Ctrl+E)"))
        self.export_pdf_act.setToolTip(t("Export PDF (Ctrl+Shift+E)"))
        self.batch_act.setToolTip(t("Batch process (Ctrl+B)"))
        self.vec_act.setToolTip(t("Trace the open image (F5)"))
        self.retrace_act.setToolTip(t("Retrace the segmentation (F6)"))
        self.fit_act.setToolTip(t("Fit the preview to the window (Ctrl+0)"))
        self.actual_act.setToolTip(t("Show actual pixel size (Ctrl+1)"))

        tabs = self.preview_tabs
        tabs.setTabText(0, t("Original"))
        tabs.setTabText(1, t("Vector"))
        tabs.setTabText(2, t("Side by side"))
        tabs.setTabText(3, t("Compare"))
        tabs.setTabText(4, t("Segmentation"))
        self._refresh_placeholders()
        self.welcome.retranslate_ui()

        if self._idle_status and self._loaded is None:
            self._status_info.setText(t("Open an image to begin."))

        self.panel.retranslate_ui()
        self.seg_editor.retranslate_ui()
        self.side_by_side.retranslate_ui()
        self.split_compare.retranslate_ui()
        self._apply_recent_menu()
        self._update_undo_actions()
        self.original_canvas.viewport().update()

    def _set_ui_language(self, code: str) -> None:
        if code == current_language():
            for lang, act in self._lang_actions.items():
                act.setChecked(lang == code)
            return
        set_language(code, persist=True)
        self.retranslate_ui()

    def _restore_sidebar_defaults(self, prefs) -> None:
        """Apply remembered preset, or fall back to default workflow/quality."""
        if self.panel.apply_last_preset():
            return
        current = self.panel.settings()
        self.panel.set_settings(
            replace(
                current,
                workflow=prefs.workflow,
                automatic_quality=prefs.automatic_quality,
            )
        )

    def _on_sidebar_settings_changed(self) -> None:
        if not self._persist_sidebar:
            return
        try:
            settings = self.panel.settings()
        except ValueError:
            return
        update_preferences(
            workflow=settings.workflow,
            automatic_quality=settings.automatic_quality,
        )

    def open_preferences_dialog(self) -> None:
        dialog = PreferencesDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.chrome_reset_requested:
            self._apply_ui_chrome_reset()
        self._on_preferences_changed()

    def _apply_ui_chrome_reset(self) -> None:
        """Drop theme, recent files, and window geometry after a confirmed reset."""
        clear_ui_chrome()
        from vectorizer.gui.theme import APPEARANCE_SYSTEM, apply_appearance

        self._select_appearance(APPEARANCE_SYSTEM)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_appearance(app)
        self._persist_sidebar = False
        self._restore_sidebar_defaults(current_preferences())
        self._persist_sidebar = True
        self._apply_recent_menu()
        self._apply_default_geometry()
        self.statusBar().showMessage(t("Preferences reset to defaults."), 4000)

    def _on_preferences_changed(self) -> None:
        prefs = current_preferences()
        self._history.set_max_steps(prefs.session_history_steps)
        self._export_dir = prefs.resolved_export_dir()
        self._update_eps_availability()

    def _update_eps_availability(self) -> None:
        if inkscape_available():
            self.export_eps_act.setToolTip("")
        else:
            self.export_eps_act.setToolTip(
                t("Requires Inkscape on PATH or a path set in Preferences.")
            )
        self._sync_document_actions()

    def _remember_export_dir(self, dest: Path) -> None:
        self._export_dir = dest.parent
        update_preferences(export_dir=str(dest.parent))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            t("About Vectorizer"),
            tf(
                "<b>Vectorizer {version}</b>"
                "<p>An independent Linux application that turns bitmap images "
                "into editable vector paths. It runs entirely on this computer: "
                "no account, no telemetry, and no network.</p>"
                "<p>Open an image or a .vproj project and vectorize it (F5). "
                "On the Segmentation tab you can correct regions; Retrace (F6) "
                "builds the paths from that map. Export SVG, PDF, PNG, or DXF. "
                "EPS is available when Inkscape is installed.</p>"
                "<p>Tracing uses the open-source VTracer engine. Photographs "
                "become stylized color regions, not a lossless copy of the photo.</p>"
                "<p>Author: Christoph Rupprich<br>License: MIT</p>",
                version=__version__,
            ),
        )

    def _set_appearance(self, mode: str) -> None:
        from vectorizer.gui.theme import apply_appearance, set_appearance_mode

        set_appearance_mode(mode)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_appearance(app)

    def _select_appearance(self, mode: str) -> None:
        for key, action in self._appearance_actions.items():
            action.blockSignals(True)
            action.setChecked(key == mode)
            action.blockSignals(False)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowActivate:
            from vectorizer.gui.theme import refresh_system_theme

            app = QApplication.instance()
            if isinstance(app, QApplication):
                refresh_system_theme(app)
        super().changeEvent(event)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # Keep the wide text toolbar from forcing a huge minimum window width.
        return QSize(640, 360)

    def _chrome_height(self) -> int:
        height = 0
        menu = self.menuBar()
        if menu is not None and not menu.isNativeMenuBar():
            height += max(menu.sizeHint().height(), menu.height())
        for toolbar in self.findChildren(QToolBar):
            if toolbar.isVisible() and not toolbar.isFloating():
                height += max(toolbar.sizeHint().height(), toolbar.height())
        status = self.statusBar()
        if status is not None:
            height += max(status.sizeHint().height(), status.height())
        return height + 12

    def _apply_default_geometry(self) -> None:
        """Size to fit the sidebar, keep golden-ratio aspect, clamp to the screen."""
        screen = self.screen() or QApplication.primaryScreen()
        sidebar_h = self.panel.preferred_content_height()
        # Offscreen / incomplete layout can report tiny hints; use a sane floor.
        if sidebar_h < 240:
            sidebar_h = 560
        height = sidebar_h + self._chrome_height()
        width = int(round(height * GOLDEN_RATIO))

        avail = None
        max_w = 10_000
        max_h = 10_000
        if screen is not None:
            avail = screen.availableGeometry()
            max_w = max(640, avail.width() - 2 * SCREEN_MARGIN)
            max_h = max(480, avail.height() - 2 * SCREEN_MARGIN)

        scale = min(1.0, max_w / float(width), max_h / float(height))
        width = max(1, int(round(width * scale)))
        height = max(1, int(round(height * scale)))

        # Force the computed size; layout minimums (toolbar / seg bar) would
        # otherwise refuse a shorter golden-ratio window on constrained screens.
        self.setFixedSize(width, height)
        self.setMinimumSize(min(640, width), min(360, height))
        self.setMaximumSize(16777215, 16777215)
        canvas_min = min(MIN_CANVAS_WIDTH, max(200, width - SIDEBAR_WIDTH))
        self.preview_tabs.setMinimumWidth(canvas_min)
        self._preview_stack.setMinimumWidth(canvas_min)
        self.seg_editor.setMinimumWidth(canvas_min)
        self.side_by_side.setMinimumWidth(canvas_min)
        self.split_compare.setMinimumWidth(canvas_min)

        if avail is not None:
            frame = self.frameGeometry()
            frame.moveCenter(avail.center())
            self.move(frame.topLeft())

        # Drop any previously saved size so it cannot override next launch.
        self._settings_store.remove("ui/geometry")

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self._pending_default_geometry:
            self._pending_default_geometry = False
            self._apply_default_geometry()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.runner.busy:
            self.runner.cancel()
        # Do not persist window geometry — startup always uses the designed default.
        self._settings_store.remove("ui/geometry")
        super().closeEvent(event)

    def _drop_canvases(self) -> tuple[ImageCanvas, ...]:
        return (
            self.original_canvas,
            self.vector_canvas,
            self.side_by_side.left,
            self.side_by_side.right,
        )

    def _update_file_drop_enabled(self) -> None:
        # The welcome screen accepts drops until an image is open.
        enabled = self._loaded is None
        for canvas in self._drop_canvases():
            canvas.set_file_drop_enabled(enabled)
        self._preview_stack.setCurrentWidget(self.welcome if enabled else self.preview_tabs)
        self._sync_document_actions()

    def _refresh_placeholders(self) -> None:
        hint = t("Vectorize (F5) to see the paths here.")
        self.vector_canvas.set_placeholder(hint)
        self.side_by_side.right.set_placeholder(hint)

    def _show_mode_banner(self, text: str | None) -> None:
        if not text:
            self._mode_banner.hide()
            self._mode_banner.clear()
            return
        self._mode_banner.setText(text)
        self._mode_banner.show()

    def _clear_pointer_modes(self) -> None:
        self._picking_background = False
        self._picking_palette = False
        self.original_canvas.set_sample_mode(False)
        if self._delete_shapes:
            self.delete_shape_act.blockSignals(True)
            self.delete_shape_act.setChecked(False)
            self.delete_shape_act.blockSignals(False)
            self._delete_shapes = False
            self.vector_canvas.set_sample_mode(False)
            self.side_by_side.right.set_sample_mode(False)
        self._show_mode_banner(None)

    def _cancel_current(self) -> None:
        self.runner.cancel()
        self._clear_pointer_modes()

    def _sync_document_actions(self) -> None:
        if not hasattr(self, "vec_act"):
            return
        has_image = self._loaded is not None
        has_result = self._result is not None
        busy = self.runner.busy
        self.save_proj_act.setEnabled(has_image and not busy)
        self.vec_act.setEnabled(has_image and not busy)
        self.retrace_act.setEnabled(has_image and self.seg_editor.has_map() and not busy)
        self.rebuild_act.setEnabled(has_image and not busy)
        self.panel.set_ready(has_image)
        for action in (
            self.export_svg_act,
            self.export_pdf_act,
            self.export_png_act,
            self.export_dxf_act,
        ):
            action.setEnabled(has_result)
        self.export_eps_act.setEnabled(has_result and inkscape_available())
        self.delete_shape_act.setEnabled(has_result)
        self.remove_bg_shape_act.setEnabled(has_result)

    def _open_dropped_path(self, path: object) -> None:
        if self._loaded is not None:
            return
        if not isinstance(path, Path):
            return
        if path.suffix.lower() == ".vproj":
            self.open_project(path)
        else:
            self.open_path(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._loaded is None and first_drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if self._loaded is not None:
            event.ignore()
            return
        path = first_drop_path(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self._open_dropped_path(path)

    def open_file_dialog(self) -> None:
        start = self._settings_store.value("ui/last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(
            self, t("Open image"), str(start), image_file_filter()
        )
        if path:
            self.open_path(Path(path))

    def paste_clipboard(self) -> None:
        image = QApplication.clipboard().image()
        if image.isNull():
            self._error(t("The clipboard does not contain a bitmap."))
            return
        try:
            loaded = load_image_from_bytes(qimage_to_png_bytes(image), source_path=None)
        except ImageLoadError as exc:
            self._error(str(exc))
            return
        self._adopt_loaded(loaded)

    def open_path(self, path: Path) -> None:
        try:
            loaded = load_image(path)
        except ImageLoadError as exc:
            self._error(str(exc))
            return
        self._settings_store.setValue("ui/last_dir", str(path.parent))
        self._remember_recent(path)
        self._project_path = None
        self._adopt_loaded(loaded)

    def open_project_dialog(self) -> None:
        start = self._settings_store.value("ui/last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(
            self, t("Open project"), str(start), project_file_filter()
        )
        if path:
            self.open_project(Path(path))

    def open_project(self, path: Path) -> None:
        try:
            data = load_project(path)
        except ProjectError as exc:
            self._error(str(exc))
            return
        self._settings_store.setValue("ui/last_dir", str(path.parent))
        self._project_path = path
        loaded = LoadedImage(
            image=data.source,
            source_path=path,
            source_format="PROJECT",
            notes=data.notes + ("Loaded from Vectorizer project.",),
            file_size=path.stat().st_size,
            original_mode=data.source.mode,
            frame_index=0,
        )
        self.panel.set_settings(data.settings)
        self._adopt_loaded(loaded, auto_vectorize=False)
        if data.segmentation is not None:
            self.seg_editor.set_map(data.segmentation)
        if data.result_svg:
            document = parse_svg_document(data.result_svg, backend_name="project")
            self._apply_result(
                TraceResult(
                    document=document,
                    elapsed_seconds=0.0,
                    settings=data.settings,
                    backend_name="project",
                    warnings=("Restored vector from project file.",),
                ),
                rebuild_segmentation=False,
            )
        self.setWindowTitle(f"Vectorizer — {path.name}")
        self.statusBar().showMessage(tf("Opened project {path}", path=path), 4000)

    def save_project_dialog(self) -> None:
        if self._loaded is None:
            self._error(t("Open an image before saving a project."))
            return
        suggested = self._project_path
        if suggested is None:
            name = "project.vproj"
            if self._loaded.source_path:
                name = self._loaded.source_path.with_suffix(".vproj").name
            suggested = self._export_dir / name
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("Save project"),
            str(suggested),
            project_file_filter(),
        )
        if not path:
            return
        dest = Path(path)
        if dest.suffix.lower() != ".vproj":
            dest = dest.with_suffix(".vproj")
        if dest.exists() and current_preferences().confirm_overwrite:
            answer = QMessageBox.question(
                self,
                t("Overwrite file?"),
                tf("{name} already exists. Replace it?", name=dest.name),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        data = ProjectData(
            source=self._loaded.image,
            settings=self.panel.settings(),
            segmentation=self.seg_editor.current_map(),
            result_svg=self._result.document.raw_svg if self._result else None,
            source_name=self._loaded.source_path.name if self._loaded.source_path else None,
            notes=self._loaded.notes,
        )
        try:
            save_project(dest, data)
        except ProjectError as exc:
            self._error(str(exc))
            return
        self._project_path = dest
        self._remember_export_dir(dest)
        self.setWindowTitle(f"Vectorizer — {dest.name}")
        self.statusBar().showMessage(tf("Saved project {path}", path=dest), 4000)

    def _adopt_loaded(self, loaded: LoadedImage, *, auto_vectorize: bool = True) -> None:
        self._clear_pointer_modes()
        self._loaded = loaded
        self._result = None
        self._history.clear()
        self._retrace_from_segmentation = False
        self._update_undo_actions()
        self._update_file_drop_enabled()
        pixmap = pil_to_qpixmap(loaded.image)
        self._original_pixmap = pixmap
        self.original_canvas.show_pixmap(pixmap)
        self.side_by_side.left.show_pixmap(pixmap)
        self.vector_canvas.clear_content()
        self.side_by_side.right.clear_content()
        self.split_compare.set_images(pixmap, None)
        self.panel.set_palette([])
        quality = self.panel.settings().automatic_quality
        self._refresh_palette_suggestions()
        analysis = analyze_image(loaded.image, quality=quality)
        notes = list(loaded.notes) + list(analysis.notes)
        if loaded.source_path and loaded.source_format != "PROJECT":
            self.setWindowTitle(f"Vectorizer — {loaded.source_path.name}")
        elif loaded.source_format != "PROJECT":
            self.setWindowTitle(t("Vectorizer — clipboard"))
        current = self.panel.settings()
        will_auto = auto_vectorize and current.workflow == WorkflowMode.AUTOMATIC
        if will_auto:
            self._apply_suggested_automatic(analysis.suggested, preserve_preprocess=False)
        # Skip an immediate segmentation build when auto-vectorize will rebuild
        # it after the job finishes (avoids double quantize on every open).
        if not will_auto:
            self.seg_editor.set_map(
                build_segmentation(loaded.image, self.panel.settings()),
                reset_history=True,
            )
        else:
            self.seg_editor.clear_map()
        self.panel.set_notes("\n".join(notes) if notes else "")
        self._idle_status = False
        self._status_info.setText(
            f"{analysis.width}×{analysis.height}  ·  mode {loaded.original_mode}  ·  "
            f"{loaded.source_format}"
        )
        self.preview_tabs.setCurrentIndex(0)
        if will_auto:
            self.vectorize()

    def _apply_suggested_automatic(
        self,
        suggested: TraceSettings,
        *,
        preserve_preprocess: bool,
    ) -> None:
        current = self.panel.settings()
        quality = current.automatic_quality or AutomaticQuality.BALANCED
        if preserve_preprocess:
            merged = replace(
                suggested,
                automatic_quality=quality,
                preserve_transparency=current.preserve_transparency,
                remove_background=current.remove_background,
                background_r=current.background_r,
                background_g=current.background_g,
                background_b=current.background_b,
                background_tolerance=current.background_tolerance,
                # Keep manual target_colors unless Automatic Fast/High set one.
                target_colors=(
                    suggested.target_colors
                    if suggested.target_colors
                    else current.target_colors
                ),
                smooth_noise=current.smooth_noise,
            )
        else:
            # Honor Automatic suggestions including background knock-out,
            # palette reduction, and noise smoothing from the analyzer.
            merged = replace(
                suggested,
                automatic_quality=quality,
                preserve_transparency=suggested.preserve_transparency,
                remove_background=suggested.remove_background,
                background_r=suggested.background_r,
                background_g=suggested.background_g,
                background_b=suggested.background_b,
                background_tolerance=suggested.background_tolerance,
                target_colors=suggested.target_colors,
                smooth_noise=suggested.smooth_noise,
            )
        self.panel.set_settings(merged)

    def _apply_automatic_quality(self) -> None:
        if self._loaded is None:
            return
        if self.panel.settings().workflow != WorkflowMode.AUTOMATIC:
            return
        quality = self.panel.settings().automatic_quality
        self._refresh_palette_suggestions()
        analysis = analyze_image(self._loaded.image, quality=quality)
        notes = list(self._loaded.notes) + list(analysis.notes)
        self.panel.set_notes("\n".join(notes) if notes else "")
        self._apply_suggested_automatic(analysis.suggested, preserve_preprocess=True)
        labels = {
            AutomaticQuality.FAST: t("Fast"),
            AutomaticQuality.BALANCED: t("Balanced"),
            AutomaticQuality.HIGH: t("High detail"),
        }
        self.statusBar().showMessage(
            tf(
                "Automatic quality set to {quality}.",
                quality=labels.get(quality, quality.value),
            ),
            3000,
        )

    def vectorize(self) -> None:
        if self._loaded is None:
            self._error(t("Open an image before vectorizing."))
            return
        if self.runner.busy:
            return
        try:
            settings = replace(self.panel.settings(), apply_preprocess=True)
        except ValueError as exc:
            self._error(str(exc))
            return
        # Optional preprocess preview — only for modest images so the UI thread
        # does not freeze on megapixel knock-out/quantize (worker still does it).
        width, height = self._loaded.image.size
        if (settings.remove_background or settings.target_colors) and width * height <= 1_500_000:
            try:
                working = preprocess_image(self._loaded.image, settings)
                self.side_by_side.left.show_pixmap(pil_to_qpixmap(working))
            except Exception:
                pass
        self._retrace_from_segmentation = False
        try:
            handle = self.runner.start(self._loaded.image, settings)
        except TraceError as exc:
            self._error(str(exc))
            return
        self._current_token = handle.token

    def rebuild_segmentation(self) -> None:
        if self._loaded is None:
            self._error(t("Open an image first."))
            return
        answer = QMessageBox.question(
            self,
            t("Rebuild segmentation?"),
            t(
                "Rebuild the segmentation from the original image and current settings? "
                "Unsaved segmentation edits will be discarded."
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            settings = self.panel.settings()
            seg = build_segmentation(self._loaded.image, settings)
        except Exception as exc:
            self._error(str(exc))
            return
        self.seg_editor.set_map(seg, reset_history=True)
        self.preview_tabs.setCurrentWidget(self.seg_editor)
        self.statusBar().showMessage(t("Segmentation rebuilt from source."), 4000)

    def retrace_segmentation(self) -> None:
        if self._loaded is None:
            self._error(t("Open an image first."))
            return
        seg = self.seg_editor.current_map()
        if seg is None:
            self._error(t("No segmentation map is available."))
            return
        if self.runner.busy:
            return
        try:
            settings = replace(self.panel.settings(), apply_preprocess=False)
        except ValueError as exc:
            self._error(str(exc))
            return
        self._retrace_from_segmentation = True
        try:
            handle = self.runner.start(seg.image, settings)
        except TraceError as exc:
            self._error(str(exc))
            return
        self._current_token = handle.token

    def export_svg_dialog(self) -> None:
        dest = self._ask_export_path(t("Export SVG"), f"{t('SVG')} (*.svg)", ".svg")
        if dest is None or self._result is None:
            return
        try:
            export_svg(
                self._result.document,
                dest,
                paint_style=self.panel.settings().svg_paint_style,
            )
        except ExportError as exc:
            self._error(str(exc))
            return
        self._remember_export_dir(dest)
        self.statusBar().showMessage(tf("Saved {path}", path=dest), 4000)

    def export_pdf_dialog(self) -> None:
        dest = self._ask_export_path(t("Export PDF"), f"{t('PDF')} (*.pdf)", ".pdf")
        if dest is None or self._result is None:
            return
        try:
            export_pdf(self._result.document, dest)
        except ExportError as exc:
            self._error(str(exc))
            return
        self._remember_export_dir(dest)
        self.statusBar().showMessage(tf("Saved vector PDF {path}", path=dest), 4000)

    def export_png_dialog(self) -> None:
        if self._result is None:
            self._error(t("Vectorize an image before exporting."))
            return
        prefs = current_preferences()
        default_w = prefs.png_width or int(self._result.document.width)
        default_h = prefs.png_height or int(self._result.document.height)
        dialog = PngExportDialog(
            self,
            default_w=default_w,
            default_h=default_h,
            default_background=prefs.png_background_value(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height, background = dialog.values()
        update_preferences(
            png_width=0 if width == int(self._result.document.width) else width,
            png_height=0 if height == int(self._result.document.height) else height,
            png_background="" if background is None else background,
        )
        dest = self._ask_export_path(
            t("Export PNG preview"), f"{t('PNG')} (*.png)", ".png"
        )
        if dest is None:
            return
        try:
            export_png_preview(
                self._result.document,
                dest,
                width=width,
                height=height,
                background=background,
            )
        except ExportError as exc:
            self._error(str(exc))
            return
        self._remember_export_dir(dest)
        self.statusBar().showMessage(tf("Saved PNG preview {path}", path=dest), 4000)

    def export_dxf_dialog(self) -> None:
        dest = self._ask_export_path(t("Export DXF"), f"{t('DXF')} (*.dxf)", ".dxf")
        if dest is None or self._result is None:
            return
        try:
            curve_mode = self.panel.settings().dxf_curve_mode
            export_dxf(self._result.document, dest, curve_mode=curve_mode)
        except ExportError as exc:
            self._error(str(exc))
            return
        self._remember_export_dir(dest)
        if curve_mode == DxfCurveMode.SPLINES:
            note = t("outlines only; cubics as splines; fills omitted")
        else:
            note = t("outlines only; curves linearized")
        self.statusBar().showMessage(tf("Saved DXF {path} ({note})", path=dest, note=note), 5000)

    def export_eps_dialog(self) -> None:
        if not inkscape_available():
            self._error(
                t("EPS export requires Inkscape on PATH or a path set in Preferences.")
            )
            return
        dest = self._ask_export_path(t("Export EPS"), f"{t('EPS')} (*.eps)", ".eps")
        if dest is None or self._result is None:
            return
        try:
            export_eps(self._result.document, dest)
        except ExportError as exc:
            self._error(str(exc))
            return
        self._remember_export_dir(dest)
        self.statusBar().showMessage(tf("Saved EPS {path}", path=dest), 4000)

    def open_batch_dialog(self) -> None:
        try:
            settings = self.panel.settings()
        except ValueError as exc:
            self._error(str(exc))
            return
        dialog = BatchDialog(self, settings)
        dialog.exec()

    def _start_background_pick(self) -> None:
        if self._loaded is None:
            self._error(t("Open an image first, then pick a background color from it."))
            return
        if self._delete_shapes:
            self.delete_shape_act.setChecked(False)
        self._picking_palette = False
        self._picking_background = True
        self.preview_tabs.setCurrentWidget(self.original_canvas)
        self.original_canvas.set_sample_mode(True)
        self._show_mode_banner(t("Click a pixel on the original. Press Esc to cancel."))

    def _start_palette_pick(self) -> None:
        if self._loaded is None:
            self._error(t("Open an image first, then pick a color from it."))
            return
        if self._delete_shapes:
            self.delete_shape_act.setChecked(False)
        self._picking_background = False
        self._picking_palette = True
        self.preview_tabs.setCurrentWidget(self.original_canvas)
        self.original_canvas.set_sample_mode(True)
        self._show_mode_banner(
            t("Click a pixel to add it to the trace palette. Press Esc to cancel.")
        )

    def _on_original_pixel_clicked(self, x: int, y: int) -> None:
        if self._loaded is None or not (self._picking_background or self._picking_palette):
            return
        width, height = self._loaded.image.size
        if not (0 <= x < width and 0 <= y < height):
            return
        pixel = self._loaded.image.getpixel((x, y))
        if len(pixel) < 3:
            return
        color = QColor(int(pixel[0]), int(pixel[1]), int(pixel[2]))
        if self._picking_palette:
            self.panel.add_trace_color(color.name())
            self._picking_palette = False
            self.original_canvas.set_sample_mode(False)
            self._show_mode_banner(None)
            self.statusBar().showMessage(
                tf("Added {color} to the trace palette.", color=color.name()),
                6000,
            )
            return
        self.panel.set_background_color(color, enable_removal=True)
        self._picking_background = False
        self.original_canvas.set_sample_mode(False)
        self._show_mode_banner(None)
        self.statusBar().showMessage(
            tf("Background set to {color} — press Vectorize to apply.", color=color.name()),
            6000,
        )

    def _toggle_delete_shapes(self, enabled: bool) -> None:
        self._delete_shapes = enabled
        self.vector_canvas.set_sample_mode(enabled)
        self.side_by_side.right.set_sample_mode(enabled)
        if enabled:
            self._picking_background = False
            self._picking_palette = False
            self.original_canvas.set_sample_mode(False)
            self.preview_tabs.setCurrentWidget(self.vector_canvas)
            self._show_mode_banner(t("Click a filled shape to delete it. Press Esc to cancel."))
        else:
            self._show_mode_banner(None)

    def _on_vector_pixel_clicked(self, x: int, y: int) -> None:
        if not self._delete_shapes or self._result is None:
            return
        document = delete_shape_at(self._result.document, float(x), float(y))
        if document is None:
            self.statusBar().showMessage(t("No filled shape at that point."), 3000)
            return
        updated = TraceResult(
            document=document,
            elapsed_seconds=self._result.elapsed_seconds,
            settings=self._result.settings,
            backend_name=self._result.backend_name,
            warnings=self._result.warnings,
        )
        self._apply_result(updated, rebuild_segmentation=False, history_label="Delete shape")
        self.statusBar().showMessage(t("Shape removed from the vector result."), 3000)

    def _remove_result_background(self) -> None:
        if self._result is None:
            self._error(t("Vectorize an image before removing background shapes."))
            return
        settings = self.panel.settings()
        document = remove_background_shapes(
            self._result.document,
            (settings.background_r, settings.background_g, settings.background_b),
            tolerance=settings.background_tolerance,
        )
        if document is self._result.document or document.path_count == self._result.document.path_count:
            self.statusBar().showMessage(t("No background-colored shapes to remove."), 4000)
            return
        updated = TraceResult(
            document=document,
            elapsed_seconds=self._result.elapsed_seconds,
            settings=self._result.settings,
            backend_name=self._result.backend_name,
            warnings=self._result.warnings,
        )
        self._apply_result(
            updated, rebuild_segmentation=False, history_label="Remove background"
        )
        self.statusBar().showMessage(t("Background-colored shapes removed."), 3000)

    def _refresh_palette_suggestions(self) -> None:
        if self._loaded is None:
            return
        settings = self.panel.settings()
        ignore = None
        if settings.remove_background:
            ignore = (settings.background_r, settings.background_g, settings.background_b)
        suggestions = suggest_palettes(self._loaded.image, ignore_rgb=ignore)
        mapping = dict(suggestions.palettes)
        best = suggestions.palettes.get(suggestions.best)
        if best:
            mapping[-1] = best
        self.panel.set_palette_suggestions(mapping)

    def _ask_export_path(
        self,
        title: str,
        file_filter: str,
        suffix: str,
        *,
        confirm_overwrite: bool | None = None,
    ) -> Path | None:
        if self._result is None:
            self._error(t("Vectorize an image before exporting."))
            return None
        if confirm_overwrite is None:
            confirm_overwrite = current_preferences().confirm_overwrite
        suggested = f"vectorizer-output{suffix}"
        if self._loaded and self._loaded.source_path:
            suggested = self._loaded.source_path.with_suffix(suffix).name
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(self._export_dir / suggested),
            file_filter,
        )
        if not path:
            return None
        dest = Path(path)
        if dest.suffix.lower() != suffix:
            dest = dest.with_suffix(suffix)
        if confirm_overwrite and dest.exists():
            answer = QMessageBox.question(
                self,
                t("Overwrite file?"),
                tf("{name} already exists. Replace it?", name=dest.name),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        return dest

    def fit_views(self) -> None:
        for canvas in (
            self.original_canvas,
            self.vector_canvas,
            self.side_by_side.left,
            self.side_by_side.right,
        ):
            canvas.fit_in_view()
        self.seg_editor.fit_view()

    def actual_size(self) -> None:
        for canvas in (
            self.original_canvas,
            self.vector_canvas,
            self.side_by_side.left,
            self.side_by_side.right,
        ):
            canvas.zoom_actual()

    def _on_job_started(self, token: int) -> None:
        if token != self._current_token:
            return
        self.panel.set_busy(True)
        self._progress.show()
        self._idle_status = False
        label = (
            t("Retracing segmentation…")
            if self._retrace_from_segmentation
            else t("Tracing…")
        )
        self._status_info.setText(label)
        self._sync_document_actions()

    def _on_job_succeeded(self, token: int, result: object) -> None:
        if token != self._current_token:
            return
        self.panel.set_busy(False)
        self._progress.hide()
        self._sync_document_actions()
        if not isinstance(result, TraceResult):
            self._error(t("Internal error: unexpected trace result."))
            return
        rebuild = not self._retrace_from_segmentation
        label = "Retrace" if self._retrace_from_segmentation else "Vectorize"
        self._apply_result(result, rebuild_segmentation=rebuild, history_label=label)
        self.preview_tabs.setCurrentWidget(self.side_by_side)
        if self._retrace_from_segmentation:
            self.statusBar().showMessage(t("Retrace from segmentation complete."), 4000)

    def _current_snapshot(self, label: str) -> SessionSnapshot:
        return SessionSnapshot(
            label=label,
            result=self._result,
            settings=self.panel.settings(),
        )

    def _push_history(self, label: str) -> None:
        self._history.push(self._current_snapshot(label))
        self._update_undo_actions()

    def _apply_result(
        self,
        result: TraceResult,
        *,
        rebuild_segmentation: bool,
        history_label: str | None = None,
    ) -> None:
        if history_label is not None:
            self._push_history(history_label)
        self._result = result
        svg = result.document.raw_svg
        ok = self.vector_canvas.show_svg(svg) and self.side_by_side.right.show_svg(svg)
        if not ok:
            self._error(t("The SVG was generated but Qt could not render it."))
            return
        vector_pix = _svg_to_pixmap(svg, int(result.document.width), int(result.document.height))
        self.split_compare.set_images(self._original_pixmap, vector_pix)
        palette = [
            group.palette_key
            for group in result.document.groups
            if group.palette_key and group.palette_key.startswith("#")
        ]
        self.panel.set_palette(palette)
        if rebuild_segmentation and self._loaded is not None:
            try:
                seg = build_segmentation(self._loaded.image, result.settings)
                self.seg_editor.set_map(seg, reset_history=True)
            except Exception:
                pass
        seconds = result.elapsed_seconds
        paths = result.document.path_count
        size = result.document.byte_size
        self._idle_status = False
        self._status_info.setText(
            f"{int(self._loaded.image.width) if self._loaded else 0}×"
            f"{int(self._loaded.image.height) if self._loaded else 0}  ·  "
            f"{seconds:.2f}s  ·  {paths} paths  ·  {size} bytes SVG"
        )
        if result.warnings:
            # Keep English source notes; append English warnings then retranslate.
            existing = [
                line for line in self.panel.notes_english.splitlines() if line.strip()
            ]
            merged = existing + [w for w in result.warnings if w not in existing]
            self.panel.set_notes("\n".join(merged))
        self._update_undo_actions()
        self._sync_document_actions()

    def _clear_vector_views(self) -> None:
        self._result = None
        self.vector_canvas.clear_content()
        self.side_by_side.right.clear_content()
        self.split_compare.set_images(self._original_pixmap, None)
        self.panel.set_palette([])
        self._idle_status = False
        self._status_info.setText(t("Result cleared (undo)."))
        self._update_undo_actions()
        self._sync_document_actions()

    def _restore_snapshot(self, snapshot: SessionSnapshot) -> None:
        self.panel.set_settings(snapshot.settings)
        if snapshot.result is None:
            self._clear_vector_views()
            return
        self._apply_result(snapshot.result, rebuild_segmentation=False, history_label=None)

    def _prefer_segmentation_history(self) -> bool:
        return self.preview_tabs.currentWidget() is self.seg_editor

    def undo(self) -> None:
        if self._prefer_segmentation_history() and self.seg_editor.can_undo:
            self.seg_editor.undo()
            self._update_undo_actions()
            return
        if self._history.can_undo:
            action = self._history.undo_label or "action"
            restored = self._history.undo(self._current_snapshot(action))
            if restored is None:
                return
            self._restore_snapshot(restored)
            self.statusBar().showMessage(tf("Undid {action}.", action=t(action)), 3000)
            self._update_undo_actions()
            return
        if self.seg_editor.can_undo:
            self.seg_editor.undo()
            self._update_undo_actions()

    def redo(self) -> None:
        if self._prefer_segmentation_history() and self.seg_editor.can_redo:
            self.seg_editor.redo()
            self._update_undo_actions()
            return
        if self._history.can_redo:
            action = self._history.redo_label or "action"
            restored = self._history.redo(self._current_snapshot(action))
            if restored is None:
                return
            self._restore_snapshot(restored)
            self.statusBar().showMessage(tf("Redid {action}.", action=t(action)), 3000)
            self._update_undo_actions()
            return
        if self.seg_editor.can_redo:
            self.seg_editor.redo()
            self._update_undo_actions()

    def _update_undo_actions(self) -> None:
        if not hasattr(self, "undo_act"):
            return
        if self._prefer_segmentation_history():
            can_undo = self.seg_editor.can_undo or self._history.can_undo
            can_redo = self.seg_editor.can_redo or self._history.can_redo
            if self.seg_editor.can_undo:
                self.undo_act.setText(t("&Undo segmentation"))
                self.undo_act.setToolTip(t("Undo the last segmentation edit"))
            elif self._history.undo_label:
                label = t(self._history.undo_label)
                self.undo_act.setText(f"{t('&Undo')} {label}")
                self.undo_act.setToolTip(f"{t('Undo')} {label}")
            else:
                self.undo_act.setText(t("&Undo"))
                self.undo_act.setToolTip(t("Nothing to undo"))
            if self.seg_editor.can_redo:
                self.redo_act.setText(t("&Redo segmentation"))
                self.redo_act.setToolTip(t("Redo the last segmentation edit"))
            elif self._history.redo_label:
                label = t(self._history.redo_label)
                self.redo_act.setText(f"{t('&Redo')} {label}")
                self.redo_act.setToolTip(f"{t('Redo')} {label}")
            else:
                self.redo_act.setText(t("&Redo"))
                self.redo_act.setToolTip(t("Nothing to redo"))
        else:
            can_undo = self._history.can_undo or self.seg_editor.can_undo
            can_redo = self._history.can_redo or self.seg_editor.can_redo
            if self._history.undo_label:
                label = t(self._history.undo_label)
                self.undo_act.setText(f"{t('&Undo')} {label}")
                self.undo_act.setToolTip(f"{t('Undo')} {label}")
            elif self.seg_editor.can_undo:
                self.undo_act.setText(t("&Undo segmentation"))
                self.undo_act.setToolTip(t("Undo the last segmentation edit"))
            else:
                self.undo_act.setText(t("&Undo"))
                self.undo_act.setToolTip(t("Nothing to undo"))
            if self._history.redo_label:
                label = t(self._history.redo_label)
                self.redo_act.setText(f"{t('&Redo')} {label}")
                self.redo_act.setToolTip(f"{t('Redo')} {label}")
            elif self.seg_editor.can_redo:
                self.redo_act.setText(t("&Redo segmentation"))
                self.redo_act.setToolTip(t("Redo the last segmentation edit"))
            else:
                self.redo_act.setText(t("&Redo"))
                self.redo_act.setToolTip(t("Nothing to redo"))
        self.undo_act.setEnabled(can_undo)
        self.redo_act.setEnabled(can_redo)

    def _on_seg_changed(self) -> None:
        seg = self.seg_editor.current_map()
        if seg is not None:
            self.panel.set_palette(seg.opaque_palette())
        self._update_undo_actions()

    def _apply_recolor(self, mapping: dict) -> None:
        if self._result is None:
            return
        try:
            document = recolor_document(self._result.document, mapping)
        except Exception as exc:
            self._error(str(exc))
            return
        updated = TraceResult(
            document=document,
            elapsed_seconds=self._result.elapsed_seconds,
            settings=self._result.settings,
            backend_name=self._result.backend_name,
            warnings=self._result.warnings,
        )
        self._apply_result(updated, rebuild_segmentation=False, history_label="Recolor")
        self.statusBar().showMessage(t("Palette recolor applied to SVG fills."), 3000)

    def _on_job_failed(self, token: int, message: str) -> None:
        if token != self._current_token:
            return
        self.panel.set_busy(False)
        self._progress.hide()
        self._idle_status = False
        self._status_info.setText(t("Tracing failed."))
        # Auto-open skips the initial seg build; restore one so the tab stays usable.
        if self._loaded is not None and not self.seg_editor.has_map():
            try:
                self.seg_editor.set_map(
                    build_segmentation(self._loaded.image, self.panel.settings()),
                    reset_history=True,
                )
            except Exception:
                pass
        self._sync_document_actions()
        self._error(message)

    def _on_job_cancelled(self, token: int) -> None:
        if token != self._current_token:
            return
        self.panel.set_busy(False)
        self._progress.hide()
        self._idle_status = False
        self._status_info.setText(t("Tracing cancelled."))
        if self._loaded is not None and not self.seg_editor.has_map():
            try:
                self.seg_editor.set_map(
                    build_segmentation(self._loaded.image, self.panel.settings()),
                    reset_history=True,
                )
            except Exception:
                pass
        self._sync_document_actions()

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "Vectorizer", message)

    def _recent_paths(self) -> list[Path]:
        values = self._settings_store.value("recent/files", [], type=list)
        paths: list[Path] = []
        for item in values or []:
            path = Path(str(item))
            if path.is_file():
                paths.append(path)
        return paths[:MAX_RECENT]

    def _remember_recent(self, path: Path) -> None:
        paths = [p for p in self._recent_paths() if p != path]
        paths.insert(0, path)
        self._settings_store.setValue("recent/files", [str(p) for p in paths[:MAX_RECENT]])
        self._apply_recent_menu()

    def _apply_recent_menu(self) -> None:
        self.recent_menu.clear()
        paths = self._recent_paths()
        if not paths:
            empty = QAction(t("No recent files"), self)
            empty.setEnabled(False)
            self.recent_menu.addAction(empty)
            return
        for path in paths:
            action = QAction(str(path), self)
            action.triggered.connect(lambda _checked=False, p=path: self.open_path(p))
            self.recent_menu.addAction(action)

    def current_result(self) -> TraceResult | None:
        return self._result


class PngExportDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        default_w: int,
        default_h: int,
        default_background: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Export PNG preview"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 16000)
        self.width_spin.setValue(max(1, default_w))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 16000)
        self.height_spin.setValue(max(1, default_h))
        self.bg = QComboBox()
        self.bg.addItem(t("Transparent"), None)
        self.bg.addItem(t("White"), "#ffffff")
        self.bg.addItem(t("Black"), "#000000")
        self.bg.addItem(t("Mint Aqua"), "#1f9ede")
        if default_background:
            idx = self.bg.findData(default_background)
            if idx >= 0:
                self.bg.setCurrentIndex(idx)
        form = QFormLayout(self)
        form.addRow(t("Width (px)"), self.width_spin)
        form.addRow(t("Height (px)"), self.height_spin)
        form.addRow(t("Background"), self.bg)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[int, int, str | None]:
        return self.width_spin.value(), self.height_spin.value(), self.bg.currentData()


def _svg_to_pixmap(svg_text: str, width: int, height: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    w = max(width, 1)
    h = max(height, 1)
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return QPixmap.fromImage(image)


def show_load_error(window: QWidget, exc: VectorizerError) -> None:
    QMessageBox.warning(window, "Vectorizer", str(exc))
