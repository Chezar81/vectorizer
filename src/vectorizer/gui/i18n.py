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
    "&System setting": "&Systemeinstellung",
    "&Light mode": "&Heller Modus",
    "&Dark mode": "&Dunkler Modus",
    "&Settings": "&Einstellungen",
    "&Language": "&Sprache",
    "&Preferences…": "&Präferenzen…",
    "Preferences": "Präferenzen",
    "General": "Allgemein",
    "Export": "Export",
    "Batch": "Stapel",
    "Advanced": "Erweitert",
    "Layout": "Anordnung",
    "Wipe": "Wischer",
    "Result colors": "Ergebnis-Farben",
    "SVG defaults": "SVG-Vorgaben",
    "DXF / EPS defaults": "DXF-/EPS-Vorgaben",
    "History and limits": "Verlauf und Limits",
    "After vectorize — recolor without retracing:": (
        "Nach dem Vektorisieren — umfärben ohne Nachzeichnen:"
    ),
    "Automatic classifies the image and chooses tracing defaults. "
    "Basic shows a short guide. Advanced unlocks expert knobs. "
    "Export options live in the export dialogs and Preferences.": (
        "Automatisch klassifiziert das Bild und wählt Trace-Vorgaben. "
        "Einfach zeigt eine kurze Anleitung. Erweitert schaltet Expertenregler frei. "
        "Exportoptionen liegen in den Export-Dialogen und den Präferenzen."
    ),
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
    "Reset these preferences to their defaults? Theme and recent files are "
    "cleared when you press OK. Language is kept.": (
        "Diese Präferenzen auf die Vorgaben zurücksetzen? Thema und zuletzt "
        "geöffnete Dateien werden mit OK gelöscht. Die Sprache bleibt erhalten."
    ),
    "&Reset Preferences": "Präferenzen &zurücksetzen",
    "Defaults shown. Press OK to apply them.": (
        "Vorgaben werden angezeigt. OK übernimmt sie."
    ),
    "Preferences reset to defaults.": "Einstellungen auf Vorgaben zurückgesetzt.",
    "Save preferences": "Präferenzen speichern",
    "Load preferences": "Präferenzen laden",
    "&Save to file": "In Datei &speichern",
    "&Load from file": "Aus Datei &laden",
    "Vectorizer preferences": "Vectorizer-Präferenzen",
    "Saved preferences {path}": "Präferenzen gespeichert: {path}",
    "Loaded {path}. Press OK to apply these values.": (
        "Geladen: {path}. OK übernimmt diese Werte."
    ),
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
    "Open an image (Ctrl+O)": "Bild öffnen (Strg+O)",
    "Save the project (Ctrl+S)": "Projekt speichern (Strg+S)",
    "Export SVG (Ctrl+E)": "SVG exportieren (Strg+E)",
    "Export PDF (Ctrl+Shift+E)": "PDF exportieren (Strg+Umschalt+E)",
    "Batch process (Ctrl+B)": "Stapelverarbeitung (Strg+B)",
    "Undo (Ctrl+Z)": "Rückgängig (Strg+Z)",
    "Redo (Ctrl+Shift+Z)": "Wiederholen (Strg+Umschalt+Z)",
    "Trace the open image (F5)": "Geöffnetes Bild nachzeichnen (F5)",
    "Retrace the segmentation (F6)": "Segmentierung neu nachzeichnen (F6)",
    "Fit the preview to the window (Ctrl+0)": "Vorschau an das Fenster anpassen (Strg+0)",
    "Show actual pixel size (Ctrl+1)": "Echte Pixelgröße zeigen (Strg+1)",
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
    "Compare": "Vergleich",
    "Segmentation": "Segmentierung",
    "Turn a bitmap into editable vector paths.": (
        "Eine Bitmap in bearbeitbare Vektorpfade verwandeln."
    ),
    "Open an image, or drop one on this window.": (
        "Ein Bild öffnen oder auf dieses Fenster ziehen."
    ),
    "Vectorize. Automatic mode picks the tracing settings.": (
        "Vektorisieren. Der Modus Automatisch wählt die Einstellungen."
    ),
    "Compare the result, then export SVG, PDF, or DXF.": (
        "Das Ergebnis vergleichen und als SVG, PDF oder DXF exportieren."
    ),
    "Open image…": "Bild öffnen…",
    "Paste bitmap": "Bitmap einfügen",
    "PNG, JPEG, WebP, GIF, BMP, TIFF, or a .vproj project.": (
        "PNG, JPEG, WebP, GIF, BMP, TIFF oder ein .vproj-Projekt."
    ),
    "Vectorize (F5) to see the paths here.": (
        "Vektorisieren (F5), um die Pfade hier zu sehen."
    ),
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
    "Edges": "Kanten",
    "Automatic edges": "Automatische Kanten",
    "Artwork with blending": "Grafik mit Übergängen",
    "Artwork without blending": "Grafik ohne Übergänge",
    "Photograph": "Fotografie",
    "Blending uses anti-aliased pixels to place the curve inside the pixel. "
    "Without blending, shapes snap to flat colors. Photographs are posterized.": (
        "Übergänge nutzen geglättete Pixel, um die Kurve im Pixel zu platzieren. "
        "Ohne Übergänge rasten Formen auf flache Farben ein. Fotos werden posterisiert."
    ),
    "Trace palette": "Nachzeichnungs-Palette",
    "Unlimited": "Unbegrenzt",
    "2 colors": "2 Farben",
    "4 colors": "4 Farben",
    "8 colors": "8 Farben",
    "12 colors": "12 Farben",
    "Best guess": "Beste Schätzung",
    "Custom": "Benutzerdefiniert",
    "Colors the trace must use:": "Farben, die das Nachzeichnen verwenden muss:",
    "Add from image": "Aus Bild hinzufügen",
    "Click a pixel on the Original image to add that color to the trace palette.": (
        "Klicken Sie ein Pixel im Originalbild an, um diese Farbe zur Palette hinzuzufügen."
    ),
    "Remove color": "Farbe entfernen",
    "SVG paint": "SVG-Farbe",
    "Fill only": "Nur Füllung",
    "Stroke and fill": "Strich und Füllung",
    "Gap filler": "Lückenfüller",
    "Stroke edges": "Kantenstriche",
    "Fill only is the simpler file. Stroke and fill paints a same-color hairline. "
    "Gap filler puts average-color strokes under shared edges. "
    "Stroke edges exports cutting paths only.": (
        "Nur Füllung ergibt die einfachere Datei. Strich und Füllung malt eine Haarlinie "
        "derselben Farbe. Der Lückenfüller legt gemittelte Striche unter gemeinsame Kanten. "
        "Kantenstriche exportieren nur Schnittpfade."
    ),
    "Gap / edge stroke width": "Lücken-/Kantenstrichbreite",
    "Non-scaling gap / edge strokes": "Nicht skalierende Lücken-/Kantenstriche",
    "Keep stroke width constant when zooming (SVG vector-effect).": (
        "Strichbreite beim Zoomen konstant halten (SVG vector-effect)."
    ),
    "Detect circles and rectangles": "Kreise und Rechtecke erkennen",
    "When a contour fits a circle or axis-aligned rectangle, emit native "
    "SVG shapes instead of generic path curves.": (
        "Wenn ein Konturverlauf zu einem Kreis oder achsparallelen Rechteck passt, "
        "native SVG-Formen statt generischer Pfadkurven ausgeben."
    ),
    "Palette snap tolerance": "Paletten-Fangtoleranz",
    "How close a color must be to snap onto the trace palette (0 = exact, "
    "255 = always snap). Remaps still apply afterward.": (
        "Wie nah eine Farbe an der Trace-Palette liegen muss (0 = exakt, "
        "255 = immer fangen). Remaps gelten danach weiterhin."
    ),
    "DXF curves": "DXF-Kurven",
    "DXF lines": "DXF-Linien",
    "DXF lines and arcs": "DXF-Linien und Bögen",
    "DXF splines": "DXF-Splines",
    "Lines samples curves into polylines. Lines and arcs keep circular arcs. "
    "Splines keep cubic curves. None of these modes write fills.": (
        "Linien tastet Kurven als Polylinien ab. Linien und Bögen behalten Kreisbögen. "
        "Splines behalten kubische Kurven. Keine dieser Arten schreibt Füllungen."
    ),
    "Few (~4)": "Wenige (~4)",
    "Normal (~8)": "Normal (~8)",
    "Many (~16)": "Viele (~16)",
    "DXF line density": "DXF-Liniendichte",
    "How many samples LINES mode uses per curve. Few is about 4, normal is 8, "
    "many is about 16. Lines-and-arcs and splines keep their own geometry.": (
        "Wie viele Abtastungen der Linienmodus je Kurve nutzt. Wenige ist etwa 4, "
        "normal 8, viele etwa 16. Linien und Bögen sowie Splines behalten ihre eigene Geometrie."
    ),
    "EPS compatibility": "EPS-Kompatibilität",
    "Maximize compatibility": "Kompatibilität maximieren",
    "Minimize file size": "Dateigröße minimieren",
    "Maximize compatibility writes PostScript Level 2. "
    "Minimize file size writes Level 3.": (
        "Kompatibilität maximieren schreibt PostScript Level 2. "
        "Dateigröße minimieren schreibt Level 3."
    ),
    "Cluster similar colors": "Ähnliche Farben zusammenfassen",
    "After an unlimited-palette trace, merge fills closer than a medium OKLab step. "
    "Off by default so automatic free-color keeps its own steps.": (
        "Nach einem Trace mit unbegrenzter Palette Füllungen zusammenfassen, die näher "
        "als ein mittlerer OKLab-Schritt liegen. Standardmäßig aus, damit automatische "
        "freie Farben ihre Abstufungen behalten."
    ),
    "Max working side": "Maximale Arbeitsseite",
    "Prompt": "Nachfragen",
    "0 asks before shrinking an image over the working limit. A positive value "
    "shrinks the working copy so the long side is at most this many pixels. "
    "The original file is not modified.": (
        "0 fragt nach, bevor ein Bild über dem Arbeitslimit verkleinert wird. Ein "
        "positiver Wert verkleinert die Arbeitskopie, sodass die lange Seite höchstens "
        "so viele Pixel hat. Die Originaldatei bleibt unverändert."
    ),
    "Compare &palette": "&Palette vergleichen",
    "Show the bitmap snapped to the trace palette beside the vector result.": (
        "Die auf die Trace-Palette gefangene Bitmap neben dem Vektorergebnis zeigen."
    ),
    "Palette": "Palette",
    "No palette to compare.": "Keine Palette zum Vergleichen.",
    "Palette compare is showing the snapped bitmap.": (
        "Der Palettenvergleich zeigt die gefangene Bitmap."
    ),
    "Trace as artwork": "Als Grafik nachzeichnen",
    "Cycle detail": "Detailstufe wechseln",
    "Make background": "Zum Hintergrund machen",
    "Re-trace flat or logo-like art with artwork edges instead of the photograph treatment.": (
        "Flache oder logoartige Grafik mit Grafikkanten statt der Fotobehandlung neu nachzeichnen."
    ),
    "Step Automatic quality (fast, balanced, high) and trace again.": (
        "Automatische Qualität (schnell, ausgewogen, hoch) weiterschalten und erneut nachzeichnen."
    ),
    "Remove finished shapes whose fill matches the background color.": (
        "Fertige Formen entfernen, deren Füllung der Hintergrundfarbe entspricht."
    ),
    "Transparency may be lost": "Transparenz kann verloren gehen",
    "This result has transparent fills. EPS, PDF, and DXF do not keep that alpha. "
    "A PNG preview preserves it.": (
        "Dieses Ergebnis hat transparente Füllungen. EPS, PDF und DXF behalten dieses "
        "Alpha nicht. Eine PNG-Vorschau erhält es."
    ),
    "Export PNG instead": "Stattdessen PNG exportieren",
    "Continue": "Fortfahren",
    "Image is very large": "Bild ist sehr groß",
    "This image is {width}×{height} ({megapixels:.1f} megapixels), above the "
    "{limit:.0f} megapixel working limit. Shrink the working copy so the long side "
    "is {side} px? The original file is not modified.": (
        "Dieses Bild ist {width}×{height} ({megapixels:.1f} Megapixel) und liegt über "
        "dem Arbeitslimit von {limit:.0f} Megapixeln. Arbeitskopie so verkleinern, dass "
        "die lange Seite {side} px hat? Die Originaldatei wird nicht verändert."
    ),
    "Averaged {count} pixels to {color}.": "{count} Pixel zu {color} gemittelt.",
    "Working copy is {width}×{height} (source was {original_width}×{original_height}).": (
        "Arbeitskopie ist {width}×{height} (Quelle war {original_width}×{original_height})."
    ),
    "outlines only; lines and circular arcs; fills omitted": (
        "nur Umrisse; Linien und Kreisbögen; Füllungen weggelassen"
    ),
    "Smooth noise before tracing": "Rauschen vor dem Nachzeichnen glätten",
    "Apply a light median filter to RGB before tracing. "
    "Helps JPEG artifacts and photographic noise; keep off for crisp logos.": (
        "Leichten Medianfilter auf RGB vor dem Nachzeichnen anwenden. "
        "Hilft bei JPEG-Artefakten und Fotorauschen; bei scharfen Logos auslassen."
    ),
    "Result palette (after vectorize):": "Ergebnispalette (nach dem Vektorisieren):",
    "Tracing (Basic)": "Nachzeichnen (Einfach)",
    "Basic guide": "Leitfaden (Einfach)",
    "Color mode": "Farbmodus",
    "Transparency": "Transparenz",
    "Recommended": "Empfohlen",
    "Recommended: {choice}": "Empfohlen: {choice}",
    "No transparency recommendation yet.": "Noch keine Transparenzempfehlung.",
    "Choose hard edges, blended artwork, or a photograph. This sets Edges.": (
        "Harte Kanten, Grafik mit Übergängen oder ein Foto wählen. Das setzt die Kanten."
    ),
    "Unlimited keeps the image colors. 2 colors uses a two-color palette, "
    "or black and white when no palette is suggested. Custom edits the trace palette.": (
        "Unbegrenzt behält die Bildfarben. 2 Farben nutzt eine Zweifarben-Palette "
        "oder Schwarzweiß, wenn keine Palette vorgeschlagen ist. Benutzerdefiniert "
        "bearbeitet die Trace-Palette."
    ),
    "Segments": "Segmente",
    "Curves": "Kurven",
    "Engine parameters": "Engine-Parameter",
    "Show parameters": "Parameter anzeigen",
    "Hide parameters": "Parameter ausblenden",
    "Low-level tracer knobs. Values still apply while this section is collapsed.": (
        "Feine Tracer-Regler. Die Werte gelten auch, solange dieser Abschnitt "
        "eingeklappt ist."
    ),
    "Merge near-duplicate fills after an unlimited-color trace.": (
        "Nahezu gleiche Füllungen nach einem Trace mit unbegrenzter Farbzahl zusammenfassen."
    ),
    "How regions drop anti-aliased fringe before curves are fit.": (
        "Wie Bereiche geglättete Ränder verwerfen, bevor Kurven angepasst werden."
    ),
    "How tightly fitted contours follow the segmentation.": (
        "Wie eng angepasste Konturen der Segmentierung folgen."
    ),
    "Path fitting": "Pfadanpassung",
    "Noise removal (px)": "Rauschentfernung (px)",
    "Layering": "Schichtung",
    "Color precision (bits)": "Farbgenauigkeit (Bits)",
    "Layer difference": "Ebenendifferenz",
    "Corner threshold (°)": "Eckenschwelle (°)",
    "Length threshold (px)": "Längenschwelle (px)",
    "Max iterations": "Max. Iterationen",
    "Splice threshold (°)": "Spleißschwelle (°)",
    "Path precision": "Pfadgenauigkeit",
    "Presets": "Voreinstellungen",
    "Output": "Ausgabe",
    "More preset actions": "Weitere Voreinstellungen",
    "Mode": "Modus",
    "Quality": "Qualität",
    "Automatic classifies the image (logo, line art, photo, …) and "
    "chooses tracing plus preprocess defaults. Background and color "
    "controls below always apply — switch to Basic for path-fitting options.": (
        "Automatisch klassifiziert das Bild (Logo, Strichzeichnung, Foto, …) und "
        "wählt Nachzeichnungs- sowie Vorverarbeitungsvorgaben. Hintergrund- und "
        "Farbsteuerungen darunter gelten immer — für Pfadoptionen zu Einfach wechseln."
    ),
    "For artwork, Fast absorbs a wider blend, Balanced is about 2 px, "
    "and High detail is about 1 px. For photographs, the same levels "
    "change how many shapes are kept.": (
        "Bei Grafik nimmt Schnell einen breiteren Übergang auf, Ausgewogen etwa 2 px "
        "und Hohe Detailtiefe etwa 1 px. Bei Fotos ändern dieselben Stufen, "
        "wie viele Formen erhalten bleiben."
    ),
    "Knock out pixels close to the background color and treat them as empty. "
    "This is separate from flattening existing alpha.": (
        "Pixel nahe der Hintergrundfarbe ausstanzen und als leer behandeln. "
        "Das ist etwas anderes als vorhandenes Alpha auf eine Farbe zu rechnen."
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
    "Keep the image alpha, including a real soft mask. Uncheck to flatten: "
    "composite the artwork onto the background color. This does not knock "
    "out a solid backdrop.": (
        "Das Alpha des Bildes behalten, auch eine echte weiche Maske. Deaktivieren "
        "ebnet ab: die Grafik wird auf die Hintergrundfarbe gerechnet. Das stanzt "
        "keinen deckenden Hintergrund aus."
    ),
    "Contour smoothness": "Konturglätte",
    "Node budget": "Knotenbudget",
    "AA artifact rejection": "AA-Artefakt-Unterdrückung",
    "None": "Keine",
    "Moderate": "Mittel",
    "Aggressive": "Aggressiv",
    "Drop anti-aliased fringe slivers that are not real features. "
    "Moderate is the default. Aggressive absorbs a wider fringe. "
    "This is not a minimum-pixel filter.": (
        "Geglättete Randstreifen verwerfen, die keine echten Details sind. "
        "Mittel ist die Vorgabe. Aggressiv nimmt einen breiteren Rand auf. "
        "Das ist kein Mindest-Pixel-Filter."
    ),
    "How closely curves follow the pixels. Lower keeps wiggles; higher "
    "flattens them. Scales blend fitting and the VTracer length threshold. "
    "Path precision stays the number of decimal places.": (
        "Wie eng Kurven den Pixeln folgen. Niedrig behält Zacken, hoch glättet sie. "
        "Skaliert die Blend-Anpassung und die VTracer-Längenschwelle. "
        "Die Pfadgenauigkeit bleibt die Anzahl der Nachkommastellen."
    ),
    "How many points to keep on fitted contours. Higher keeps more nodes; "
    "lower simplifies with a Douglas–Peucker pass. Separate from contour smoothness.": (
        "Wie viele Punkte an angepassten Konturen bleiben. Höher behält mehr Knoten, "
        "niedriger vereinfacht mit Douglas–Peucker. Getrennt von der Konturglätte."
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
    "Zap fringes": "Ränder auflösen",
    "Merge thin anti-aliased leftovers into the neighboring region "
    "instead of deleting them.": (
        "Dünne geglättete Reste in den Nachbarbereich übernehmen, statt sie zu löschen."
    ),
    "Find problems": "Probleme finden",
    "Mark one-pixel gaps and pinched strokes. Paint across a gap so regions "
    "connect; open a one-pixel gap on a pinch to separate them.": (
        "Ein-Pixel-Lücken und eingeschnürte Striche markieren. Über eine Lücke malen, "
        "damit Bereiche verbunden werden; an einer Einschnürung eine Ein-Pixel-Lücke "
        "öffnen, um sie zu trennen."
    ),
    "Zap": "Auflösen",
    "Dissolve the clicked segment into the neighboring colors.": (
        "Den angeklickten Bereich in die Nachbarfarben auflösen."
    ),
    "Clicked segment split into neighboring colors.": (
        "Angeklickter Bereich wurde in Nachbarfarben aufgeteilt."
    ),
    "Nothing to zap here.": "Hier gibt es nichts aufzulösen.",
    "Fringe regions merged into their neighbors.": (
        "Randbereiche in ihre Nachbarn übernommen."
    ),
    "No pinched gaps found.": "Keine eingeschnürten Lücken gefunden.",
    "Problem spots are marked. Paint across a one-pixel gap so regions "
    "connect. Open a one-pixel gap on a pinch to keep those regions separate.": (
        "Problemstellen sind markiert. Über eine Ein-Pixel-Lücke malen, damit Bereiche "
        "verbunden werden. An einer Einschnürung eine Ein-Pixel-Lücke öffnen, damit "
        "diese Bereiche getrennt bleiben."
    ),
    "Retrace from segmentation": "Aus Segmentierung nachzeichnen",
    "Rebuild from source…": "Aus Quelle neu aufbauen…",
    "Rebuild…": "Neu aufbauen…",
    "Rebuild the segmentation from the original image. Edits that are not retraced are discarded.": (
        "Segmentierung aus dem Originalbild neu aufbauen. Noch nicht nachgezeichnete "
        "Änderungen gehen verloren."
    ),
    "Clean up": "Bereinigen",
    "Smaller than": "Kleiner als",
    "Regions smaller than this many pixels are removed by Clean up → Remove small regions.": (
        "Bereiche mit weniger Pixeln entfernt „Bereinigen → Kleine Bereiche entfernen“."
    ),
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
    "Scale": "Skalierung",
    "Lock aspect ratio": "Seitenverhältnis sperren",
    "Keep the source aspect ratio when width, height, or scale changes.": (
        "Das Seitenverhältnis der Quelle beibehalten, wenn Breite, Höhe oder "
        "Skalierung sich ändern."
    ),
    "Source {width}×{height} px": "Quelle {width}×{height} px",
    "Export at {factor}× the source pixel size (Alt+{factor}).": (
        "Mit {factor}× der Quellpixelgröße exportieren (Alt+{factor})."
    ),
    "Transparent": "Transparent",
    "White": "Weiß",
    "Black": "Schwarz",
    "Mint Aqua": "Mint Aqua",
    # --- Status / messages ---
    "About Vectorizer": "Über Vectorizer",
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
    "<p>Author: Christoph Rupprich<br>License: MIT</p>": (
        "<b>Vectorizer {version}</b>"
        "<p>Eine eigenständige Linux-Anwendung, die Bitmap-Bilder in "
        "bearbeitbare Vektorpfade umwandelt. Sie läuft vollständig auf "
        "diesem Rechner: kein Konto, keine Telemetrie und kein Netzwerk.</p>"
        "<p>Öffnen Sie ein Bild oder ein .vproj-Projekt und vektorisieren "
        "Sie es (F5). Im Segmentierungs-Tab können Sie Bereiche korrigieren; "
        "Nachzeichnen (F6) erzeugt die Pfade aus dieser Karte. Export als "
        "SVG, PDF, PNG oder DXF. EPS ist verfügbar, wenn Inkscape installiert ist.</p>"
        "<p>Das Nachzeichnen nutzt die Open-Source-Engine VTracer. Fotografien "
        "werden zu stilisierten Farbflächen, nicht zu einer verlustfreien "
        "Kopie des Fotos.</p>"
        "<p>Autor: Christoph Rupprich<br>Lizenz: MIT</p>"
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
    "Saved DXF {path} ({note})": "DXF gespeichert: {path} ({note})",
    "outlines only; curves linearized": "nur Umrisse; Kurven linearisiert",
    "outlines only; cubics as splines; fills omitted": (
        "nur Umrisse; Kubiken als Splines; Füllungen ausgelassen"
    ),
    "Delete clicked shape": "Angeklickte Form löschen",
    "Click a filled shape on the vector preview to remove it.": (
        "Eine gefüllte Form in der Vektorvorschau anklicken, um sie zu entfernen."
    ),
    "Remove background shapes": "Hintergrundformen entfernen",
    "Drop finished paths whose fill matches the background color.": (
        "Fertige Pfade entfernen, deren Füllung der Hintergrundfarbe entspricht."
    ),
    "Open an image first, then pick a color from it.": (
        "Öffnen Sie zuerst ein Bild und wählen Sie dann eine Farbe daraus."
    ),
    "Click a pixel on the Original image to add that color to the palette…": (
        "Klicken Sie ein Pixel im Originalbild an, um diese Farbe zur Palette hinzuzufügen…"
    ),
    "Added {color} to the trace palette.": "{color} zur Nachzeichnungs-Palette hinzugefügt.",
    "Click a filled shape on the vector preview to delete it.": (
        "Klicken Sie eine gefüllte Form in der Vektorvorschau an, um sie zu löschen."
    ),
    "No filled shape at that point.": "Keine gefüllte Form an dieser Stelle.",
    "Shape removed from the vector result.": "Form aus dem Vektorergebnis entfernt.",
    "Delete shape": "Form löschen",
    "Vectorize an image before removing background shapes.": (
        "Vektorisieren Sie ein Bild, bevor Sie Hintergrundformen entfernen."
    ),
    "No background-colored shapes to remove.": "Keine hintergrundfarbenen Formen zum Entfernen.",
    "Background-colored shapes removed.": "Hintergrundfarbene Formen entfernt.",
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
    "Vectorizing…": "Vektorisierung läuft…",
    "Loading image…": "Bild wird geladen…",
    "Reading image…": "Bild wird gelesen…",
    "Opening project…": "Projekt wird geöffnet…",
    "Preparing preview…": "Vorschau wird vorbereitet…",
    "Building segmentation…": "Segmentierung wird aufgebaut…",
    "Please wait while the image is prepared.": (
        "Bitte warten, das Bild wird vorbereitet."
    ),
    "Image loaded. Adjust settings, then press Vectorize.": (
        "Bild geladen. Einstellungen anpassen, dann Vektorisieren drücken."
    ),
    "Preparing…": "Vorbereitung…",
    "Analyzing image…": "Bild wird analysiert…",
    "Preparing colors…": "Farben werden vorbereitet…",
    "Tracing contours…": "Konturen werden nachgezeichnet…",
    "Fitting curves…": "Kurven werden angepasst…",
    "Building SVG…": "SVG wird erzeugt…",
    "Finishing…": "Abschluss…",
    "Estimating time…": "Zeit wird geschätzt…",
    "Almost done…": "Gleich fertig…",
    "About {seconds}s remaining": "Noch ca. {seconds} s",
    "About {minutes} min remaining": "Noch ca. {minutes} Min.",
    "About {minutes} min {seconds}s remaining": (
        "Noch ca. {minutes} Min. {seconds} s"
    ),
    "Press Cancel in the sidebar to stop.": (
        "Zum Abbrechen in der Seitenleiste auf Abbrechen klicken."
    ),
    "Click a pixel on the original. Ctrl-drag averages a region. Press Esc to cancel.": (
        "Klicken Sie ein Pixel im Original. Strg-Ziehen mittelt einen Bereich. Esc bricht ab."
    ),
    "Click a pixel to add it to the trace palette. Ctrl-drag averages a region. Press Esc to cancel.": (
        "Klicken Sie ein Pixel, um es der Farbpalette hinzuzufügen. Strg-Ziehen mittelt einen Bereich. Esc bricht ab."
    ),
    "Click a filled shape to delete it. Press Esc to cancel.": (
        "Klicken Sie eine gefüllte Form, um sie zu löschen. Esc bricht ab."
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
    "Detected cel / cartoon art with ink outlines; preserving flat fills "
    "and dark line work.": (
        "Cel-/Cartoon-Grafik mit Tuschelinien erkannt; flächige Füllungen und "
        "dunkle Konturen werden erhalten."
    ),
    "Detected an illustration with a moderate palette.": (
        "Illustration mit begrenzter Palette erkannt."
    ),
    "Detected a flat-color logo or icon.": (
        "Flächiges Logo oder Icon erkannt."
    ),
    "Detected a binary mark / stencil.": (
        "Binäre Markierung / Schablone erkannt."
    ),
    "Detected small pixel-art / limited palette art.": (
        "Pixel-Art / Grafik mit begrenzter Palette erkannt."
    ),
    "Detected line art; preserving thin strokes.": (
        "Strichzeichnung erkannt; dünne Linien werden erhalten."
    ),
    "Smooth gradients detected. Colors will be posterized into editable regions.": (
        "Sanfte Verläufe erkannt. Farben werden in bearbeitbare Bereiche "
        "posterisiert."
    ),
    "Edges follow anti-aliased blending inside each boundary pixel.": (
        "Kanten folgen dem Anti-Aliasing innerhalb jedes Randpixels."
    ),
    "Hard edges: shapes snap to flat colors before fitting.": (
        "Harte Kanten: Formen rasten vor dem Anpassen auf flache Farben ein."
    ),
    "Photograph: posterized to the palette, then traced as regions.": (
        "Fotografie: auf die Palette posterisiert, dann als Regionen nachgezeichnet."
    ),
    "Cel outlines solidified before tracing so ink stays continuous.": (
        "Cel-Konturen vor dem Nachzeichnen verfestigt, damit die Tusche "
        "durchgängig bleibt."
    ),
    "Cel scene: palette-snapped regions with solidified ink outlines.": (
        "Cel-Szene: auf die Palette eingerastete Flächen mit verfestigten "
        "Tuschekonturen."
    ),
    "Light noise smoothing enabled before tracing.": (
        "Leichte Rauschglättung vor dem Nachzeichnen aktiv."
    ),
    "Source transparency will be preserved.": (
        "Vorhandene Transparenz wird beibehalten."
    ),
    "Using cutout hierarchy so holes stay clean.": (
        "Cutout-Hierarchie, damit Löcher sauber bleiben."
    ),
    "Few unique colors detected; using binary tracing.": (
        "Wenige eindeutige Farben erkannt; binäres Nachzeichnen wird verwendet."
    ),
    "Small limited-color image; using pixel-aligned paths.": (
        "Kleines Bild mit begrenzten Farben; pixelgenaue Pfade werden verwendet."
    ),
    "Automatic quality: Fast — fewer, larger shapes.": (
        "Automatik-Qualität: Schnell — weniger, größere Formen."
    ),
    "Automatic quality: High detail — more, smaller shapes.": (
        "Automatik-Qualität: Hohe Detailtiefe — mehr, kleinere Formen."
    ),
    "Automatic quality: Balanced — medium shape budget.": (
        "Automatik-Qualität: Ausgewogen — mittleres Formenbudget."
    ),
    "Automatic quality: Fast — wider noise and blend absorption.": (
        "Automatik-Qualität: Schnell — breitere Rausch- und Übergangsaufnahme."
    ),
    "Automatic quality: High detail — about 1 px of edge blend.": (
        "Automatik-Qualität: Hohe Detailtiefe — etwa 1 px Kantenübergang."
    ),
    "Automatic quality: Balanced — about 2 px of edge blend.": (
        "Automatik-Qualität: Ausgewogen — etwa 2 px Kantenübergang."
    ),
    "Hard 1-bit alpha (GIF-style mask). Edges blend toward white — "
    "flatten onto white instead of keeping the mask.": (
        "Hartes 1-Bit-Alpha (GIF-artige Maske). Kanten laufen ins Weiß — "
        "auf Weiß ebnen statt die Maske zu behalten."
    ),
    "Hard 1-bit alpha (GIF-style mask) with crisp edges. "
    "Leaving transparency is appropriate.": (
        "Hartes 1-Bit-Alpha (GIF-artige Maske) mit scharfen Kanten. "
        "Transparenz beizubehalten ist passend."
    ),
    "Soft edges blend toward white rather than transparency. Flatten onto white.": (
        "Weiche Kanten laufen ins Weiß statt in Transparenz. Auf Weiß ebnen."
    ),
    "Soft edges are true transparent anti-aliasing. Leave transparency on.": (
        "Weiche Kanten sind echtes transparentes Anti-Aliasing. Transparenz eingeschaltet lassen."
    ),
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


def preferences_file_filter() -> str:
    return f"{t('Vectorizer preferences')} (*.json);;{t('All files')} (*)"
