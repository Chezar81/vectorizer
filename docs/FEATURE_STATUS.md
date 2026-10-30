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
| Zap and Finder | implemented | Segmentation editor merges thin leftovers and marks one-pixel gaps and pinches |
| Delete result shape | implemented | Click a filled path, or drop paths that match the background color |
| SVG stroke and fill | implemented | Optional same-color hairline so viewers do not draw gaps between shapes |
| User packaging (venv, wheel, `.desktop`) | implemented | `scripts/install-user.sh`, `build-wheel.sh` |
| macOS DMG | partial | Spec + `build-macos-dmg.sh` + GitHub Action; must build on macOS; unsigned |
| AppImage | planned | Not claimed ready until built+launched on Mint |
| Native Adobe `.ai` | unsupported | Will not rename SVG/PDF to `.ai` |
| GPU / cloud | unsupported | Offline CPU-only |

## Honest export gaps

- **EPS:** requires Inkscape on `PATH`. Detected at runtime; argv-only; timeout applied.
- **DXF:** 1 unit = 1 SVG pixel; Y flipped to CAD-ish coordinates. Lines mode
  samples curves to `LWPOLYLINE`. Spline mode writes cubic Béziers as `SPLINE`
  and straight spans as `LINE`; arcs are still sampled. Fills and holes are not
  represented. Complex transforms beyond `translate()` are ignored.
- **Batch memory:** one image at a time; still avoid huge inputs (loader caps apply).
