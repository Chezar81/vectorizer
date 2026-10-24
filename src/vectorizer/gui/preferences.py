"""App-level preferences persisted via QSettings (not per-image tracing params)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QStandardPaths, Signal

from vectorizer.batch.engine import CollisionPolicy, ExportFormat
from vectorizer.domain.settings import AutomaticQuality, WorkflowMode
from vectorizer.gui.session_history import DEFAULT_MAX_STEPS as SESSION_DEFAULT_STEPS
from vectorizer.segmentation.history import (
    DEFAULT_MAX_BYTES as SEG_DEFAULT_BYTES,
    DEFAULT_MAX_STEPS as SEG_DEFAULT_STEPS,
)

ORG = "Vectorizer"
APP = "Vectorizer"

# Keys intentionally wiped by "Reset all preferences".
# Geometry / dark / language / recent stay unless reset_all clears them too.
PREF_PREFIX = "prefs/"


@dataclass
class AppPreferences:
    """User preferences restored at startup and edited in Settings → Preferences."""

    # 1 — default workflow / quality (also auto-updated when the sidebar changes)
    workflow: WorkflowMode = WorkflowMode.AUTOMATIC
    automatic_quality: AutomaticQuality = AutomaticQuality.BALANCED

    # 2 — default export folder
    export_dir: str = ""

    # 3 — default export formats (batch + multi-export)
    export_svg: bool = True
    export_pdf: bool = False
    export_png: bool = False
    export_dxf: bool = False
    export_eps: bool = False

    # 4 — batch defaults
    batch_collision: CollisionPolicy = CollisionPolicy.RENAME
    batch_continue_on_error: bool = True
    batch_input_dir: str = ""
    batch_output_dir: str = ""

    # 5 — confirm before overwrite
    confirm_overwrite: bool = True

    # 7 — last loaded preset name (empty = none)
    last_preset: str = ""

    # 12 — Inkscape executable override (empty = PATH)
    inkscape_path: str = ""

    # 13 — PNG preview defaults (width/height 0 = use document size)
    png_width: int = 0
    png_height: int = 0
    png_background: str = ""  # "", "transparent", "#ffffff", "#000000", "#1f9ede"

    # 14 — history depth
    session_history_steps: int = SESSION_DEFAULT_STEPS
    segmentation_history_steps: int = SEG_DEFAULT_STEPS
    segmentation_history_mib: int = SEG_DEFAULT_BYTES // (1024 * 1024)

    def export_formats(self) -> tuple[ExportFormat, ...]:
        out: list[ExportFormat] = []
        if self.export_svg:
            out.append(ExportFormat.SVG)
        if self.export_pdf:
            out.append(ExportFormat.PDF)
        if self.export_png:
            out.append(ExportFormat.PNG)
        if self.export_dxf:
            out.append(ExportFormat.DXF)
        if self.export_eps:
            out.append(ExportFormat.EPS)
        return tuple(out) or (ExportFormat.SVG,)

    def resolved_export_dir(self) -> Path:
        if self.export_dir.strip():
            path = Path(self.export_dir).expanduser()
            if path.is_dir() or not path.exists():
                return path
        documents = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        return Path(documents or ".")

    def png_background_value(self) -> str | None:
        raw = (self.png_background or "").strip().lower()
        if not raw or raw == "transparent":
            return None
        return self.png_background.strip()

    def validated(self) -> AppPreferences:
        workflow = self.workflow
        if not isinstance(workflow, WorkflowMode):
            try:
                workflow = WorkflowMode(str(workflow))
            except ValueError:
                workflow = WorkflowMode.AUTOMATIC
        quality = self.automatic_quality
        if not isinstance(quality, AutomaticQuality):
            try:
                quality = AutomaticQuality(str(quality))
            except ValueError:
                quality = AutomaticQuality.BALANCED
        collision = self.batch_collision
        if not isinstance(collision, CollisionPolicy):
            try:
                collision = CollisionPolicy(str(collision))
            except ValueError:
                collision = CollisionPolicy.RENAME
        png_w = max(0, min(16000, int(self.png_width)))
        png_h = max(0, min(16000, int(self.png_height)))
        session_steps = max(2, min(500, int(self.session_history_steps)))
        seg_steps = max(2, min(500, int(self.segmentation_history_steps)))
        seg_mib = max(8, min(512, int(self.segmentation_history_mib)))
        return replace(
            self,
            workflow=workflow,
            automatic_quality=quality,
            batch_collision=collision,
            png_width=png_w,
            png_height=png_h,
            session_history_steps=session_steps,
            segmentation_history_steps=seg_steps,
            segmentation_history_mib=seg_mib,
            confirm_overwrite=bool(self.confirm_overwrite),
            batch_continue_on_error=bool(self.batch_continue_on_error),
            export_svg=bool(self.export_svg),
            export_pdf=bool(self.export_pdf),
            export_png=bool(self.export_png),
            export_dxf=bool(self.export_dxf),
            export_eps=bool(self.export_eps),
            export_dir=str(self.export_dir or "").strip(),
            batch_input_dir=str(self.batch_input_dir or "").strip(),
            batch_output_dir=str(self.batch_output_dir or "").strip(),
            last_preset=str(self.last_preset or "").strip(),
            inkscape_path=str(self.inkscape_path or "").strip(),
            png_background=str(self.png_background or "").strip(),
        )


class _PreferencesBroker(QObject):
    changed = Signal()


_broker = _PreferencesBroker()
_current = AppPreferences().validated()


def preferences_changed() -> Signal:
    return _broker.changed


def current_preferences() -> AppPreferences:
    return _current


def _store() -> QSettings:
    return QSettings(ORG, APP)


def _read_bool(store: QSettings, key: str, default: bool) -> bool:
    return bool(store.value(key, default, type=bool))


def _read_int(store: QSettings, key: str, default: int) -> int:
    raw = store.value(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _read_str(store: QSettings, key: str, default: str = "") -> str:
    raw = store.value(key, default)
    return str(raw) if raw is not None else default


def load_preferences() -> AppPreferences:
    """Load preferences from QSettings and activate them."""
    global _current
    store = _store()
    prefs = AppPreferences(
        workflow=_read_str(store, f"{PREF_PREFIX}workflow", WorkflowMode.AUTOMATIC.value),
        automatic_quality=_read_str(
            store, f"{PREF_PREFIX}automatic_quality", AutomaticQuality.BALANCED.value
        ),
        export_dir=_read_str(store, f"{PREF_PREFIX}export_dir"),
        export_svg=_read_bool(store, f"{PREF_PREFIX}export_svg", True),
        export_pdf=_read_bool(store, f"{PREF_PREFIX}export_pdf", False),
        export_png=_read_bool(store, f"{PREF_PREFIX}export_png", False),
        export_dxf=_read_bool(store, f"{PREF_PREFIX}export_dxf", False),
        export_eps=_read_bool(store, f"{PREF_PREFIX}export_eps", False),
        batch_collision=_read_str(
            store, f"{PREF_PREFIX}batch_collision", CollisionPolicy.RENAME.value
        ),
        batch_continue_on_error=_read_bool(
            store, f"{PREF_PREFIX}batch_continue_on_error", True
        ),
        batch_input_dir=_read_str(store, f"{PREF_PREFIX}batch_input_dir"),
        batch_output_dir=_read_str(store, f"{PREF_PREFIX}batch_output_dir"),
        confirm_overwrite=_read_bool(store, f"{PREF_PREFIX}confirm_overwrite", True),
        last_preset=_read_str(store, f"{PREF_PREFIX}last_preset"),
        inkscape_path=_read_str(store, f"{PREF_PREFIX}inkscape_path"),
        png_width=_read_int(store, f"{PREF_PREFIX}png_width", 0),
        png_height=_read_int(store, f"{PREF_PREFIX}png_height", 0),
        png_background=_read_str(store, f"{PREF_PREFIX}png_background"),
        session_history_steps=_read_int(
            store, f"{PREF_PREFIX}session_history_steps", SESSION_DEFAULT_STEPS
        ),
        segmentation_history_steps=_read_int(
            store, f"{PREF_PREFIX}segmentation_history_steps", SEG_DEFAULT_STEPS
        ),
        segmentation_history_mib=_read_int(
            store,
            f"{PREF_PREFIX}segmentation_history_mib",
            SEG_DEFAULT_BYTES // (1024 * 1024),
        ),
    ).validated()
    _current = prefs
    _apply_runtime_side_effects(prefs)
    return prefs


def save_preferences(prefs: AppPreferences, *, emit: bool = True) -> AppPreferences:
    """Persist preferences and activate them."""
    global _current
    prefs = prefs.validated()
    store = _store()
    store.setValue(f"{PREF_PREFIX}workflow", prefs.workflow.value)
    store.setValue(f"{PREF_PREFIX}automatic_quality", prefs.automatic_quality.value)
    store.setValue(f"{PREF_PREFIX}export_dir", prefs.export_dir)
    store.setValue(f"{PREF_PREFIX}export_svg", prefs.export_svg)
    store.setValue(f"{PREF_PREFIX}export_pdf", prefs.export_pdf)
    store.setValue(f"{PREF_PREFIX}export_png", prefs.export_png)
    store.setValue(f"{PREF_PREFIX}export_dxf", prefs.export_dxf)
    store.setValue(f"{PREF_PREFIX}export_eps", prefs.export_eps)
    store.setValue(f"{PREF_PREFIX}batch_collision", prefs.batch_collision.value)
    store.setValue(f"{PREF_PREFIX}batch_continue_on_error", prefs.batch_continue_on_error)
    store.setValue(f"{PREF_PREFIX}batch_input_dir", prefs.batch_input_dir)
    store.setValue(f"{PREF_PREFIX}batch_output_dir", prefs.batch_output_dir)
    store.setValue(f"{PREF_PREFIX}confirm_overwrite", prefs.confirm_overwrite)
    store.setValue(f"{PREF_PREFIX}last_preset", prefs.last_preset)
    store.setValue(f"{PREF_PREFIX}inkscape_path", prefs.inkscape_path)
    store.setValue(f"{PREF_PREFIX}png_width", prefs.png_width)
    store.setValue(f"{PREF_PREFIX}png_height", prefs.png_height)
    store.setValue(f"{PREF_PREFIX}png_background", prefs.png_background)
    store.setValue(f"{PREF_PREFIX}session_history_steps", prefs.session_history_steps)
    store.setValue(
        f"{PREF_PREFIX}segmentation_history_steps", prefs.segmentation_history_steps
    )
    store.setValue(
        f"{PREF_PREFIX}segmentation_history_mib", prefs.segmentation_history_mib
    )
    store.sync()
    _current = prefs
    _apply_runtime_side_effects(prefs)
    if emit:
        _broker.changed.emit()
    return prefs


def update_preferences(**kwargs: object) -> AppPreferences:
    """Patch individual preference fields and persist."""
    return save_preferences(replace(current_preferences(), **kwargs))


def reset_all_preferences(*, include_ui: bool = True) -> AppPreferences:
    """Clear preference keys (and optionally UI chrome keys) then restore defaults."""
    store = _store()
    for key in list(store.allKeys()):
        if key.startswith(PREF_PREFIX):
            store.remove(key)
        elif include_ui and (
            key.startswith("ui/")
            or key.startswith("recent/")
        ):
            # Keep language so the reset confirmation stays readable; wipe the rest.
            if key == "ui/language":
                continue
            store.remove(key)
    store.sync()
    return load_preferences()


def _apply_runtime_side_effects(prefs: AppPreferences) -> None:
    from vectorizer.export.tools import set_inkscape_override

    set_inkscape_override(prefs.inkscape_path or None)


def preferences_as_dict(prefs: AppPreferences | None = None) -> dict[str, object]:
    prefs = (prefs or current_preferences()).validated()
    data = asdict(prefs)
    data["workflow"] = prefs.workflow.value
    data["automatic_quality"] = prefs.automatic_quality.value
    data["batch_collision"] = prefs.batch_collision.value
    return data
