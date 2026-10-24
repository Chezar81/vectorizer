# Architecture

## Process and layers

```
GUI (PySide6)  -->  Job runner (QProcess)  -->  trace_worker
       |                                            |
       v                                            v
  canvas / settings                     raster load + VTracer backend
                                              |
                                              v
                                    SVG XML parse --> VectorDocument
                                              |
                                              v
                                    SVG / PDF / PNG export
```

The GUI must not import tracing internals except through job/session objects.
Image processing lives under `raster/`, `vectorize/`, `svg/`, and `export/`.

Preprocessing (background knock-out, optional noise smooth, quantization)
runs on a **copy** of the source before VTracer. The original `LoadedImage`
remains immutable.

Automatic mode classifies content (binary mark, flat logo, pixel art, line art,
illustration, photo, gradient) from lightweight raster metrics, then suggests
VTracer parameters plus preprocess flags (including corner-consensus background
removal and cutout hierarchy for nested holes).

## Packages

| Package | Responsibility |
| --- | --- |
| `domain` | `TraceSettings`, `VectorDocument` (paths, fills, groups, ordering) |
| `raster` | Load, EXIF, GIF first frame, size limits, analysis, preprocess |
| `vectorize` | Backend protocol + VTracer adapter |
| `svg` | XML parse + fill recolor; no regex rewriting of geometry |
| `export` | Atomic SVG, vector PDF, PNG preview |
| `presets` | Named JSON presets (no pickle) |
| `segmentation` | Working map, ops, history (memory-bounded undo) |
| `project` | `.vproj` ZIP container (manifest + PNG/SVG assets) |
| `batch` | Sequential multi-file jobs, collisions, summary |
| `jobs` | Subprocess worker, cancellation, stale-token ignore |
| `gui` | Qt window, Mint-Y-Aqua theme, synced compare, seg editor, batch dialog |

## Canonical document

`VectorDocument` stores:

- width/height and optional viewBox
- groups keyed by fill color (palette association)
- path data, fill, opacity, fill-rule, transform, source order
- `raw_svg` from the backend (export uses this in Milestone 1 so geometry is not degraded)

## Segmentation vs tracing

VTracer 0.6.x returns SVG only. It does **not** return an editable segmentation
map. Vectorizer keeps three distinct buffers:

1. Original raster (immutable)
2. Working segmentation raster (built by preprocess+quantize; edited in the GUI)
3. Generated vector geometry

**Vectorize (F5)** traces the original through preprocess. After success it
rebuilds the segmentation for editing.

**Retrace segmentation (F6)** traces the working map with `apply_preprocess=False`
so brush/fill edits are not re-quantized away.

## Backend choice

| Candidate | Decision |
| --- | --- |
| VTracer 0.6.15 | **Selected.** MIT, CPU; adapter uses `convert_raw_image_to_svg` (PNG bytes) to avoid W×H Python pixel tuples. |
| VTracer 1.0.0a4 | Not used. Alpha API; not installed from this environment’s PyPI index. |
| Potrace | Monochrome only; wrap later if needed. |
| OpenCV | Not required for M1 tracing. |
| Custom tracer | Deferred; quality would lag a maintained engine. |

## Jobs

Tracing runs in `python -m vectorizer.jobs.trace_worker` so:

- the Qt event loop stays responsive
- Cancel can terminate the process
- a generation token drops stale results

The backend does not report percent complete. The UI uses an indeterminate bar.

## Coordinates

Imported SVG uses the backend’s pixel-space coordinates (origin top-left as
emitted by VTracer). The canvas renders that SVG through `QSvgRenderer`.
