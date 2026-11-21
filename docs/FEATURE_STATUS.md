# Feature status

Statuses: **implemented** · **partial** · **planned** · **unsupported**

## Milestone 1–3

See earlier rows in git history for detail. Core open/trace/export, Mint-Y-Aqua UI,
comparison views, presets, PDF/PNG, segmentation editor, `.vproj` projects are
**implemented**.

## Automatic intelligence

| Feature | Status | Notes |
| --- | --- | --- |
| Content classification | implemented | Binary / logo / pixel / line / illustration / photo / gradient |
| Resolution-scaled speckle | implemented | Larger rasters get proportionally stronger cleanup |
| Auto background knock-out | implemented | Corner + border consensus; skipped for photos / real alpha |
| Cutout hierarchy for holes | implemented | Binary marks with nested ink/paper |
| Palette pre-quantize | implemented | Photos/illustrations; dithering disabled |
| Noise smooth preprocess | implemented | Optional median on RGB; Automatic for noisy photos |

## Milestone 4 (current)

| Feature | Status | Notes |
| --- | --- | --- |
| Batch: multiple files / folder | implemented | Non-recursive folder scan |
| Batch: shared settings / presets | implemented | Sidebar settings or named preset |
| Batch: per-file status | implemented | GUI list + summary JSON/MD |
| Batch: continue-on-error | implemented | Also `--stop-on-error` in CLI |
| Batch: cancellation | implemented | Stops after current file |
| Batch: filename collisions | implemented | skip / overwrite / rename |
| Batch: saved summary | implemented | `batch_summary.json` + `.md` |
| Sequential processing only | implemented | No uncontrolled parallelism |
| EPS export | implemented | Optional Inkscape; disabled if missing |
| DXF export | implemented | Lines: LWPOLYLINE. Splines: cubic SPLINE plus LINE. Fills and holes omitted in both |
| Constrained trace palette | implemented | Suggestions of 2, 4, 8, 12 and a best guess; eyedropper add and remove |
| Blended edges | implemented | Anti-aliased artwork places the curve inside the pixel. Hard edges and pixel art stay on VTracer. Photos are posterized |
| Zap and Finder | implemented | Global fringe zap plus click-zap (dissolve one segment into neighbors); Finder marks gaps/pinches |
| Delete result shape | implemented | Click a filled path, or drop paths that match the background color |
| SVG stroke and fill | implemented | Optional same-color hairline so viewers do not draw gaps between shapes |
| SVG gap filler | implemented | Average-color understrokes along shared edges; optional non-scaling width |
| SVG stroke edges | implemented | One stroke per shared edge (laser / vinyl); no fills |
| Parameterized shapes | implemented | Blend tracer emits native `<circle>` / `<rect>` when a contour fits |
| Palette snap tolerance + remaps | implemented | Soft snap gate (0–255) and optional `#from → #to` / transparent drop |
| DXF lines and arcs | implemented | Circular SVG arcs become DXF `ARC`; cubics still linearized |
| Vectorizer.AI oracle | implemented | Optional `scripts/oracle_vectorizer_ai.py` (test mode; not a runtime dependency) |
| User packaging (venv, wheel, `.desktop`) | implemented | `scripts/install-user.sh`, `build-wheel.sh` |
| macOS DMG | partial | Spec + `build-macos-dmg.sh` + GitHub Action; must build on macOS; unsigned |
| Linux .deb | partial | `build-linux-deb.sh` (PyInstaller → `/opt/vectorizer`); GitHub Release asset |
| Windows EXE | partial | Spec + CI zip with `Vectorizer.exe`; unsigned; GitHub Release asset |
| AppImage | planned | Not claimed ready until built+launched on Mint |
| Native Adobe `.ai` | unsupported | Will not rename SVG/PDF to `.ai` |
| EMF export | unsupported | Windows GDI metafile; SVG/PDF/EPS cover the same apps |
| GPU / cloud | unsupported | Offline CPU-only |

## Vector Magic parity (quality / UX)

Inspired by Vector Magic Desktop Edition’s wizard model (not a port of its fitter).

| Feature | Status | Notes |
| --- | --- | --- |
| Artwork vs photo quality split | implemented | Fast/Balanced/High: artwork = input blend width; photo = shape budget |
| Contour smoothness vs node budget | implemented | Separate Advanced sliders; DP simplify before cubic fit; `path_precision` stays decimals |
| AA artifact rejection | implemented | None / Moderate / Aggressive on the blend fringe path |
| Transparency advice | implemented | Detects hard 1-bit alpha and recommends leave / flatten-white / flatten-custom |
| Post-trace troubleshooting strip | implemented | Trace as artwork, cycle detail, make background when useful |
| Cutout SVG group-by-color | implemented | Same-fill paths wrapped in `<g>` at export |
| DXF line density | implemented | Few (~4) / Normal (~8) / Many (~16) for lines mode |
| EPS PostScript level | implemented | Compatible (PS2) vs compact (PS3) via Inkscape |
| Export alpha warning | implemented | EPS/PDF/DXF dialogs warn when fills use transparency |
| Palette compare | implemented | Snap preview on original/compare views |
| Cluster similar colors | implemented | Optional OKLab merge for unlimited-palette traces (default off) |
| Ctrl-average eyedropper | implemented | Ctrl-drag or Ctrl-click averages a region |
| Oversized image shrink | implemented | Recommend max side; GUI prompt; CLI/batch `--max-side` / `max_side` |
| PNG linked scale presets | implemented | Width/height/scale linked; 1× / 2× / 4× / 8× |
| Advanced panel groups | implemented | Palette / Segments / Curves; engine knobs behind disclosure |
| Basic guide | implemented | Image type, transparency, quality, color mode with Recommended badges |

## Honest export gaps

- **EPS:** requires Inkscape on `PATH`. Detected at runtime; argv-only; timeout applied.
  Compatibility mode sets `--export-ps-level=2` or `3`.
- **DXF:** 1 unit = 1 SVG pixel; Y flipped to CAD-ish coordinates. Lines mode
  samples curves to `LWPOLYLINE` (density few/normal/many). Lines-and-arcs keeps
  circular `ARC` entities and linearizes the rest. Spline mode writes cubic
  Béziers as `SPLINE` and straight spans as `LINE`. Fills and holes are not
  represented. Complex transforms beyond `translate()` are ignored.
- **Batch memory:** one image at a time; oversized inputs can shrink via `max_side`
  instead of only failing the 25 MP safety cap.
