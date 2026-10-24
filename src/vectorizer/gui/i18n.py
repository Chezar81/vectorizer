"""UI language support (English / German) with QSettings persistence."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

LANG_EN = "en"
LANG_DE = "de"
SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    (LANG_EN, "English"),
    (LANG_DE, "Deutsch"),
)
_SETTINGS_KEY = "ui/language"

# English source string -> German. Missing keys fall back to English.
_DE: dict[str, str] = {
    # --- Menus / toolbar ---
    "&File": "&Datei",
    "&Open…": "Ö&ffnen…",
    "Paste &bitmap": "&Bitmap einfügen",
    "Open &recent": "&Zuletzt geöffnet",
    "Open &project…": "&Projekt öffnen…",
    "Save p&roject…": "P&rojekt speichern…",
    "Export &SVG…": "&SVG exportieren…",
    "Export &PDF…": "&PDF exportieren…",
    "Export P&NG preview…": "P&NG-Vorschau exportieren…",
    "Export D&XF…": "D&XF exportieren…",
    "Export EP&S…": "EP&S exportieren…",
    "&Batch process…": "&Stapelverarbeitung…",
    "&Quit": "&Beenden",
    "&Edit": "&Bearbeiten",
    "&Undo": "&Rückgängig",
    "&Redo": "&Wiederholen",
    "&Undo segmentation": "Segmentierung &rückgängig",
    "&Redo segmentation": "Segmentierung &wiederholen",
    "&View": "&Ansicht",
    "&Fit to window": "An &Fenster anpassen",
    "&Actual size": "&Originalgröße",
    "&Dark appearance": "&Dunkles Erscheinungsbild",
    "&Settings": "&Einstellungen",
    "&Language": "&Sprache",
    "&Preferences…": "&Präferenzen…",
    "&Reset all preferences…": "Alle &Einstellungen zurücksetzen…",
    "Preferences": "Präferenzen",
    "Defaults": "Vorgaben",
    "Default mode": "Standardmodus",
    "Default Automatic quality": "Standardqualität (Automatisch)",
    "Default export folder": "Standard-Exportordner",
    "Last preset": "Letzte Voreinstellung",
    "(none)": "(keine)",
    "Confirm before overwriting files": "Vor dem Überschreiben von Dateien nachfragen",
    "Default export formats": "Standard-Exportformate",
    "Batch defaults": "Stapel-Vorgaben",
    "External tools": "Externe Werkzeuge",
    "Inkscape path": "Inkscape-Pfad",
    "Leave empty to use PATH": "Leer lassen, um PATH zu verwenden",
    "Inkscape executable": "Inkscape-Programmdatei",
    "PNG preview defaults": "PNG-Vorschau-Vorgaben",
    "Width/height 0 = use the vector document size.": (
        "Breite/Höhe 0 = Größe des Vektordokuments verwenden."
    ),
    "Document": "Dokument",
    "History": "Verlauf",
    "Session undo steps": "Sitzungs-Rückgängig-Schritte",
    "Segmentation undo steps": "Segmentierungs-Rückgängig-Schritte",
    "Segmentation undo memory": "Segmentierungs-Rückgängig-Speicher",
    "Select at least one default export format.": (
        "Mindestens ein Standard-Exportformat wählen."
    ),
    "Reset all preferences?": "Alle Einstellungen zurücksetzen?",
    "Reset app preferences (defaults, export/batch options, history limits, "
    "Inkscape path) and UI chrome (theme, recent files)? "
    "Language is kept. This cannot be undone.": (
        "App-Einstellungen (Vorgaben, Export-/Stapeloptionen, Verlaufslimits, "
        "Inkscape-Pfad) und UI (Thema, zuletzt geöffnete Dateien) "
        "zurücksetzen? Die Sprache bleibt erhalten. Dies kann nicht rückgängig "
        "gemacht werden."
    ),
    "Preferences reset to defaults.": "Einstellungen auf Vorgaben zurückgesetzt.",
    "Requires Inkscape on PATH or a path set in Preferences.": (
        "Inkscape muss im PATH verfügbar sein oder unter Einstellungen hinterlegt werden."
    ),
    "EPS export requires Inkscape on PATH or a path set in Preferences.": (
        "EPS-Export erfordert Inkscape im PATH oder einen Pfad unter Einstellungen."
    ),
    "&Run": "&Ausführen",
    "&Vectorize": "&Vektorisieren",
    "&Retrace segmentation": "Segmentierung neu &nachzeichnen",
    "Rebuild &segmentation": "&Segmentierung neu aufbauen",
    "&Cancel": "&Abbrechen",
    "&Help": "&Hilfe",
    "&About Vectorizer": "&Über Vectorizer",
    "Main": "Haupt",
    "Open": "Öffnen",
    "Save": "Speichern",
    "Batch": "Stapel",
    "Undo": "Rückgängig",
    "Redo": "Wiederholen",
    "Vectorize": "Vektorisieren",
    "Retrace": "Nachzeichnen",
    "Fit": "Einpassen",
    "No recent files": "Keine kürzlich geöffneten Dateien",
    "Requires Inkscape on PATH.": "Inkscape muss im PATH verfügbar sein.",
    "Undo the last segmentation edit": "Letzte Segmentierungsänderung rückgängig",
    "Redo the last segmentation edit": "Letzte Segmentierungsänderung wiederholen",
    "Nothing to undo": "Nichts rückgängig zu machen",
    "Nothing to redo": "Nichts wiederherzustellen",
    # --- Tabs / compare ---
    "Original": "Original",
    "Vector": "Vektor",
    "Side by side": "Nebeneinander",
    "Split wipe": "Wischvergleich",
    "Segmentation": "Segmentierung",
    "Drag to wipe between original (left) and vector (right).": (
        "Ziehen, um zwischen Original (links) und Vektor (rechts) zu wischen."
    ),
    "Drop an image here\nto open it": "Bild hier ablegen,\num es zu öffnen",
    "Open an image to begin.": "Öffnen Sie ein Bild, um zu beginnen.",
    # --- Settings panel ---
    "Automatic": "Automatisch",
    "Basic": "Einfach",
    "Advanced": "Erweitert",
    "Fast": "Schnell",
    "Balanced": "Ausgewogen",
    "High detail": "Hohe Detailtiefe",
    "Color": "Farbe",
    "Black and white": "Schwarzweiß",
    "Stacked layers": "Gestapelte Ebenen",
    "Cutout mosaic": "Ausschnitt-Mosaik",
    "Spline curves": "Spline-Kurven",
    "Polygons": "Polygone",
    "Pixel-aligned": "Pixelgenau",
    "Keep existing transparency": "Vorhandene Transparenz behalten",
    "Remove background": "Hintergrund entfernen",
    "Choose color…": "Farbe wählen…",
    "Pick from image": "Aus Bild wählen",
    "Auto (off)": "Auto (aus)",
    "Recolor selected fill…": "Ausgewählte Füllung umfärben…",
    "Save": "Speichern",
    "Load": "Laden",
    "Delete": "Löschen",
    "Duplicate": "Duplizieren",
    "Cancel": "Abbrechen",
    "Background": "Hintergrund",
    "Background color": "Hintergrundfarbe",
    "Color tolerance": "Farbtoleranz",
    "Tip: enable Remove background, pick a color, then Vectorize.": (
        "Tipp: Hintergrund entfernen aktivieren, Farbe wählen, dann vektorisieren."
    ),
    "Colors": "Farben",
    "Image type": "Bildtyp",
    "Target color count": "Ziel-Farbanzahl",
    "Smooth noise before tracing": "Rauschen vor dem Nachzeichnen glätten",
    "Apply a light median filter to RGB before tracing. "
    "Helps JPEG artifacts and photographic noise; keep off for crisp logos.": (
        "Leichten Medianfilter auf RGB vor dem Nachzeichnen anwenden. "
        "Hilft bei JPEG-Artefakten und Fotorauschen; bei scharfen Logos auslassen."
    ),
    "Result palette (after vectorize):": "Ergebnispalette (nach dem Vektorisieren):",
    "Tracing (Basic)": "Nachzeichnen (Einfach)",
    "Path fitting": "Pfadanpassung",
    "Noise removal (px)": "Rauschentfernung (px)",
    "Layering": "Schichtung",
    "Advanced (VTracer)": "Erweitert (VTracer)",
    "Color precision (bits)": "Farbgenauigkeit (Bits)",
    "Layer difference": "Ebenendifferenz",
    "Corner threshold (°)": "Eckenschwelle (°)",
    "Length threshold (px)": "Längenschwelle (px)",
    "Max iterations": "Max. Iterationen",
    "Splice threshold (°)": "Spleißschwelle (°)",
    "Path precision": "Pfadgenauigkeit",
    "Presets": "Voreinstellungen",
    "Mode": "Modus",
    "Quality": "Qualität",
    "Automatic classifies the image (logo, line art, photo, …) and "
    "chooses tracing plus preprocess defaults. Background and color "
    "controls below always apply — switch to Basic for path-fitting options.": (
        "Automatisch klassifiziert das Bild (Logo, Strichzeichnung, Foto, …) und "
        "wählt Nachzeichnungs- sowie Vorverarbeitungsvorgaben. Hintergrund- und "
        "Farbsteuerungen darunter gelten immer — für Pfadoptionen zu Einfach wechseln."
    ),
    "Fast: quicker, fewer paths. Balanced: default. "
    "High detail: finer colors and more path detail.": (
        "Schnell: schneller, weniger Pfade. Ausgewogen: Standard. "
        "Hohe Detailtiefe: feinere Farben und mehr Pfaddetail."
    ),
    "Make pixels near the selected background color transparent before tracing "
    "(similar to a background knockout).": (
        "Pixel nahe der gewählten Hintergrundfarbe vor dem Nachzeichnen transparent machen "
        "(ähnlich einem Hintergrund-Knockout)."
    ),
    "How close a pixel may be to the background color (0 = exact).": (
        "Wie nah ein Pixel an der Hintergrundfarbe liegen darf (0 = exakt)."
    ),
    "Click a pixel on the Original tab to set the background color, then Vectorize.": (
        "Klicken Sie auf dem Original-Tab ein Pixel, um die Hintergrundfarbe zu setzen, "
        "dann vektorisieren."
    ),
    "Limit the number of colors before tracing (quantize). "
    "Use 8–32 for logos. 0 leaves colors to the tracer.": (
        "Farben vor dem Nachzeichnen begrenzen (quantisieren). "
        "Für Logos 8–32. 0 überlässt Farben dem Tracer."
    ),
    "Change a fill color in the current SVG without retracing geometry.": (
        "Eine Füllfarbe im aktuellen SVG ändern, ohne die Geometrie neu nachzuzeichnen."
    ),
    "Hints from Automatic analysis of the opened image.": (
        "Hinweise aus der Automatik-Analyse des geöffneten Bildes."
    ),
    "Fewer bits merge similar colors (faster, simpler). More bits keep more hues (more paths).": (
        "Weniger Bits vereinigen ähnliche Farben (schneller, einfacher). "
        "Mehr Bits behalten mehr Farbtöne (mehr Pfade)."
    ),
    "Drop regions smaller than this many pixels. Higher values clean noise and remove tiny paths.": (
        "Bereiche kleiner als diese Pixelanzahl verwerfen. Höhere Werte entfernen Rauschen "
        "und winzige Pfade."
    ),
    "Spline: smooth logos. Polygon: harder corners. Pixel-aligned: pixel art, more nodes.": (
        "Spline: glatte Logos. Polygon: schärfere Ecken. Pixelgenau: Pixelkunst, mehr Knoten."
    ),
    "Stacked: overlapping shapes, compact files. Cutout: non-overlapping mosaic, often more paths.": (
        "Gestapelt: überlappende Formen, kompakte Dateien. Ausschnitt: nicht überlappendes "
        "Mosaik, oft mehr Pfade."
    ),
    "Keep existing alpha. If unchecked, alpha is composited onto the background color.": (
        "Vorhandenes Alpha behalten. Wenn deaktiviert, wird Alpha auf die Hintergrundfarbe "
        "aufgerechnet."
    ),
    "Palette": "Palette",
    "Select a palette color first.": "Zuerst eine Palettenfarbe auswählen.",
    "New fill color": "Neue Füllfarbe",
    "Save preset": "Voreinstellung speichern",
    "Preset name:": "Name der Voreinstellung:",
    "Preset": "Voreinstellung",
    "Delete preset": "Voreinstellung löschen",
    'Delete preset “{name}”?': 'Voreinstellung „{name}“ löschen?',
    "Duplicate preset": "Voreinstellung duplizieren",
    "New name:": "Neuer Name:",
    "{source} copy": "{source} Kopie",
    # --- Segmentation editor ---
    "Color": "Farbe",
    "Remove small regions": "Kleine Bereiche entfernen",
    "Retrace from segmentation": "Aus Segmentierung nachzeichnen",
    "Rebuild from source…": "Aus Quelle neu aufbauen…",
    "Pick": "Pipette",
    "Brush": "Pinsel",
    "Fill": "Füllen",
    "Recolor": "Umfärben",
    "Connect": "Verbinden",
    "Separate": "Trennen",
    "Radius": "Radius",
    "Segmentation is a separate raster from the original. "
    "Edits affect the next Retrace. Middle-drag pans; wheel zooms.": (
        "Die Segmentierung ist ein separates Raster vom Original. "
        "Änderungen wirken beim nächsten Nachzeichnen. Mittelklick-Ziehen verschiebt; "
        "Mausrad zoomt."
    ),
    "Sample a region color.": "Eine Bereichsfarbe aufnehmen.",
    "Paint with the current color.": "Mit der aktuellen Farbe malen.",
    "Flood-fill a contiguous region.": "Einen zusammenhängenden Bereich füllen.",
    "Recolor the clicked region.": "Den angeklickten Bereich umfärben.",
    "Paint a bridge to connect separated regions of the current color.": (
        "Eine Brücke malen, um getrennte Bereiche der aktuellen Farbe zu verbinden."
    ),
    "Paint transparency to separate accidentally connected regions.": (
        "Transparenz malen, um versehentlich verbundene Bereiche zu trennen."
    ),
    "Brush color": "Pinselfarbe",
    "Transparent": "Transparent",
    "Removed small regions from the segmentation.": (
        "Kleine Bereiche aus der Segmentierung entfernt."
    ),
    "Picked {color}": "{color} aufgenommen",
    "No segmentation yet. Open an image and vectorize, or rebuild.": (
        "Noch keine Segmentierung. Bild öffnen und vektorisieren, oder neu aufbauen."
    ),
    "Undo ({depth} steps, {kib} KiB)": "Rückgängig ({depth} Schritte, {kib} KiB)",
    # --- Batch ---
    "Batch vectorize": "Stapel-Vektorisierung",
    "Input folder or leave empty and add files…": (
        "Eingabeordner oder leer lassen und Dateien hinzufügen…"
    ),
    "Browse folder…": "Ordner durchsuchen…",
    "Add files…": "Dateien hinzufügen…",
    "Clear": "Leeren",
    "Browse…": "Durchsuchen…",
    "PNG preview": "PNG-Vorschau",
    "DXF (outlines)": "DXF (Umrisse)",
    "EPS (Inkscape)": "EPS (Inkscape)",
    "Inkscape was not found on PATH. Install it to enable EPS export.": (
        "Inkscape wurde im PATH nicht gefunden. Installieren Sie es für EPS-Export."
    ),
    "Uses Inkscape with a timeout and argv-only invocation.": (
        "Verwendet Inkscape mit Timeout und nur argv-Aufruf."
    ),
    "Rename (file_1.svg)": "Umbenennen (datei_1.svg)",
    "Skip existing": "Vorhandene überspringen",
    "Overwrite": "Überschreiben",
    "(current sidebar settings)": "(aktuelle Seitenleisteneinstellungen)",
    "Continue on error": "Bei Fehler fortfahren",
    "Select inputs and an output folder.": "Eingaben und Ausgabeordner wählen.",
    "Start batch": "Stapel starten",
    "Export formats": "Exportformate",
    "Input": "Eingabe",
    "Files": "Dateien",
    "Output folder": "Ausgabeordner",
    "Collisions": "Namenskonflikte",
    "Settings preset": "Einstellungs-Voreinstellung",
    "Input folder": "Eingabeordner",
    "Add images": "Bilder hinzufügen",
    "{count} file(s) queued.": "{count} Datei(en) in der Warteschlange.",
    "Batch": "Stapel",
    "Add at least one input image.": "Mindestens ein Eingabebild hinzufügen.",
    "Choose an output folder.": "Einen Ausgabeordner wählen.",
    "Select at least one export format.": "Mindestens ein Exportformat wählen.",
    "Batch running…": "Stapel läuft…",
    "Cancelling after the current file…": "Abbruch nach der aktuellen Datei…",
    "{done}/{total}: skipped {name}": "{done}/{total}: übersprungen {name}",
    "{done}/{total}: ok {name} ({paths} paths)": (
        "{done}/{total}: ok {name} ({paths} Pfade)"
    ),
    "{done}/{total}: failed {name}: {error}": "{done}/{total}: fehlgeschlagen {name}: {error}",
    "Done. OK={ok} failed={failed} skipped={skipped}. Summary: {summary}": (
        "Fertig. OK={ok} fehlgeschlagen={failed} übersprungen={skipped}. Zusammenfassung: {summary}"
    ),
    "Batch complete": "Stapel abgeschlossen",
    "Processed with {ok} ok, {failed} failed, {skipped} skipped.\n"
    "Summary written next to the outputs.": (
        "Verarbeitet: {ok} ok, {failed} fehlgeschlagen, {skipped} übersprungen.\n"
        "Zusammenfassung neben den Ausgaben geschrieben."
    ),
    "Batch failed": "Stapel fehlgeschlagen",
    # --- Dialogs / file filters ---
    "Open image": "Bild öffnen",
    "Open project": "Projekt öffnen",
    "Save project": "Projekt speichern",
    "Export SVG": "SVG exportieren",
    "Export PDF": "PDF exportieren",
    "Export PNG preview": "PNG-Vorschau exportieren",
    "Export DXF": "DXF exportieren",
    "Export EPS": "EPS exportieren",
    "Images": "Bilder",
    "All files": "Alle Dateien",
    "Vectorizer project": "Vectorizer-Projekt",
    "SVG": "SVG",
    "PDF": "PDF",
    "PNG": "PNG",
    "DXF": "DXF",
    "EPS": "EPS",
    "Overwrite file?": "Datei überschreiben?",
    "{name} already exists. Replace it?": "{name} existiert bereits. Ersetzen?",
    "Width (px)": "Breite (px)",
    "Height (px)": "Höhe (px)",
    "Transparent": "Transparent",
    "White": "Weiß",
    "Black": "Schwarz",
    "Mint Aqua": "Mint Aqua",
    # --- Status / messages ---
    "About Vectorizer": "Über Vectorizer",
    "Vectorizer is an independent, offline raster-to-vector tool for Linux.\n\n"
    "Author: Christoph Rupprich.\n\n"
    "Appearance follows Linux Mint Mint-Y-Aqua colors. "
    "Tracing uses the open-source VTracer engine. Photograph vectorization "
    "produces stylized regions, not a lossless replacement of the photo.\n\n"
    "The Segmentation tab edits a working map that is distinct from the "
    "original raster. Retrace (F6) vectorizes that map.": (
        "Vectorizer ist ein unabhängiges Offline-Werkzeug zur Raster-zu-Vektor-Umwandlung "
        "für Linux.\n\n"
        "Autor: Christoph Rupprich.\n\n"
        "Das Erscheinungsbild folgt den Linux-Mint-Mint-Y-Aqua-Farben. "
        "Das Nachzeichnen nutzt die Open-Source-Engine VTracer. Die Vektorisierung von "
        "Fotografien erzeugt stilisierte Bereiche, keinen verlustfreien Ersatz des Fotos.\n\n"
        "Der Segmentierungs-Tab bearbeitet eine Arbeitskarte, die vom Originalraster "
        "getrennt ist. Nachzeichnen (F6) vektorisiert diese Karte."
    ),
    "The clipboard does not contain a bitmap.": "Die Zwischenablage enthält kein Bitmap.",
    "Loaded from Vectorizer project.": "Aus Vectorizer-Projekt geladen.",
    "Restored vector from project file.": "Vektor aus Projektdatei wiederhergestellt.",
    "Opened project {path}": "Projekt geöffnet: {path}",
    "Open an image before saving a project.": (
        "Öffnen Sie ein Bild, bevor Sie ein Projekt speichern."
    ),
    "Saved project {path}": "Projekt gespeichert: {path}",
    "Vectorizer — clipboard": "Vectorizer — Zwischenablage",
    "Automatic quality set to {quality}.": "Automatik-Qualität auf {quality} gesetzt.",
    "Open an image before vectorizing.": "Öffnen Sie ein Bild vor dem Vektorisieren.",
    "Open an image first.": "Öffnen Sie zuerst ein Bild.",
    "Rebuild segmentation?": "Segmentierung neu aufbauen?",
    "Rebuild the segmentation from the original image and current settings? "
    "Unsaved segmentation edits will be discarded.": (
        "Segmentierung aus dem Originalbild und den aktuellen Einstellungen neu aufbauen? "
        "Ungespeicherte Segmentierungsänderungen gehen verloren."
    ),
    "Segmentation rebuilt from source.": "Segmentierung aus der Quelle neu aufgebaut.",
    "No segmentation map is available.": "Keine Segmentierungskarte verfügbar.",
    "Saved {path}": "Gespeichert: {path}",
    "Saved vector PDF {path}": "Vektor-PDF gespeichert: {path}",
    "Vectorize an image before exporting.": (
        "Vektorisieren Sie ein Bild vor dem Exportieren."
    ),
    "Saved PNG preview {path}": "PNG-Vorschau gespeichert: {path}",
    "Saved DXF {path} (outlines only; curves linearized)": (
        "DXF gespeichert: {path} (nur Umrisse; Kurven linearisiert)"
    ),
    "EPS export requires Inkscape on PATH.": (
        "EPS-Export erfordert Inkscape im PATH."
    ),
    "Saved EPS {path}": "EPS gespeichert: {path}",
    "Open an image first, then pick a background color from it.": (
        "Öffnen Sie zuerst ein Bild und wählen Sie dann eine Hintergrundfarbe daraus."
    ),
    "Click a pixel on the Original image to set the background color…": (
        "Klicken Sie ein Pixel im Originalbild, um die Hintergrundfarbe zu setzen…"
    ),
    "Background set to {color} — press Vectorize to apply.": (
        "Hintergrund auf {color} gesetzt — Vektorisieren drücken zum Anwenden."
    ),
    "Retracing segmentation…": "Segmentierung wird nachgezeichnet…",
    "Tracing…": "Nachzeichnen…",
    "{label} (indeterminate; backend has no percent)": (
        "{label} (unbestimmt; Backend liefert keinen Prozentwert)"
    ),
    "Internal error: unexpected trace result.": (
        "Interner Fehler: unerwartetes Nachzeichnungsergebnis."
    ),
    "Retrace from segmentation complete.": "Nachzeichnen aus Segmentierung abgeschlossen.",
    "The SVG was generated but Qt could not render it.": (
        "Das SVG wurde erzeugt, aber Qt konnte es nicht darstellen."
    ),
    "Result cleared (undo).": "Ergebnis gelöscht (Rückgängig).",
    "action": "Aktion",
    "Undid {action}.": "{action} rückgängig gemacht.",
    "Redid {action}.": "{action} wiederhergestellt.",
    "Palette recolor applied to SVG fills.": (
        "Paletten-Umfärbung auf SVG-Füllungen angewendet."
    ),
    "Tracing failed.": "Nachzeichnen fehlgeschlagen.",
    "Tracing cancelled.": "Nachzeichnen abgebrochen.",
    # --- Analyzer notes (shown in sidebar) ---
    "This image looks photographic. Vectorization will produce stylized "
    "color regions, not a lossless stand-in for the photograph.": (
        "Dieses Bild wirkt fotografisch. Die Vektorisierung erzeugt stilisierte "
        "Farbbereiche, keinen verlustfreien Ersatz für das Foto."
    ),
    "Few unique colors detected; using binary tracing.": (
        "Wenige eindeutige Farben erkannt; binäres Nachzeichnen wird verwendet."
    ),
    "Small limited-color image; using pixel-aligned paths.": (
        "Kleines Bild mit begrenzten Farben; pixelgenaue Pfade werden verwendet."
    ),
    "Automatic quality: Fast — fewer paths, quicker result.": (
        "Automatik-Qualität: Schnell — weniger Pfade, schnelleres Ergebnis."
    ),
    "Automatic quality: High detail — finer colors and paths.": (
        "Automatik-Qualität: Hohe Detailtiefe — feinere Farben und Pfade."
    ),
    "Automatic quality: Balanced.": "Automatik-Qualität: Ausgewogen.",
}


class _LanguageBroker(QObject):
    changed = Signal(str)


_broker = _LanguageBroker()
_current = LANG_EN


def language_changed() -> Signal:
    """Signal emitted with the new language code when the UI language changes."""
    return _broker.changed


def current_language() -> str:
    return _current


def t(text: str) -> str:
    """Translate an English UI string to the active language."""
    if not text or _current == LANG_EN:
        return text
    return _DE.get(text, text)


def tf(template: str, **kwargs: object) -> str:
    """Translate a format template, then substitute placeholders."""
    return t(template).format(**kwargs)


def _ui_settings() -> QSettings:
    return QSettings("Vectorizer", "Vectorizer")


def load_language(*, default: str = LANG_EN) -> str:
    """Restore the last saved language from QSettings and activate it."""
    raw = _ui_settings().value(_SETTINGS_KEY, default)
    code = str(raw or default).strip().lower()
    if code not in {LANG_EN, LANG_DE}:
        code = default
    set_language(code, persist=False)
    return code


def set_language(code: str, *, persist: bool = True) -> str:
    """Activate a language; optionally write it to QSettings."""
    global _current
    normalized = code.strip().lower()
    if normalized not in {LANG_EN, LANG_DE}:
        normalized = LANG_EN
    if normalized == _current and not persist:
        return _current
    previous = _current
    _current = normalized
    if persist:
        store = _ui_settings()
        store.setValue(_SETTINGS_KEY, normalized)
        store.sync()
    if normalized != previous:
        _broker.changed.emit(normalized)
    return _current


def image_file_filter() -> str:
    return (
        f"{t('Images')} (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;"
        f"PNG (*.png);;JPEG (*.jpg *.jpeg);;{t('All files')} (*)"
    )


def project_file_filter() -> str:
    return f"{t('Vectorizer project')} (*.vproj)"
