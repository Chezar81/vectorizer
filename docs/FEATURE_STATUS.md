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
| DXF export | implemented | Native outlines; curves linearized; fills omitted |
| User packaging (venv, wheel, `.desktop`) | implemented | `scripts/install-user.sh`, `build-wheel.sh` |
| AppImage | planned | Not claimed ready until built+launched on Mint |
| Native Adobe `.ai` | unsupported | Will not rename SVG/PDF to `.ai` |
| GPU / cloud | unsupported | Offline CPU-only |

## Honest export gaps

- **EPS:** requires Inkscape on `PATH`. Detected at runtime; argv-only; timeout applied.
- **DXF:** 1 unit = 1 SVG pixel; Y flipped to CAD-ish coordinates; Beziers sampled;
  fills/holes not represented; complex transforms beyond `translate()` ignored.
- **Batch memory:** one image at a time; still avoid huge inputs (loader caps apply).
