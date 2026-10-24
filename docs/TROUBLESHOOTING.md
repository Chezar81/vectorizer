# Troubleshooting

## The application does not start

- Confirm the venv is active and `python -c "import PySide6, vtracer, PIL"` works.
- On a headless SSH session, the GUI needs `DISPLAY`. Use `python -m vectorizer image.png -o out.svg` instead.
- Wayland vs X11: Mint Cinnamon is typically X11 (`DISPLAY=:0`). If Qt fails to create a window, try `QT_QPA_PLATFORM=xcb`.
- If Qt prints `xcb-cursor0 or libxcb-cursor0 is needed`, the PySide wheel found the xcb plugin but the cursor helper library is missing. That is an **optional system package** (`libxcb-cursor0` on Ubuntu/Mint). This project will not install it without your approval. Headless tracing and `QT_QPA_PLATFORM=offscreen` still work.

## `vtracer` fails to import

The 0.6.15 wheel used here is `manylinux` for CPython 3.12 x86_64. Other
architectures need a matching wheel or a local build (not documented in M1).

## Tracing looks noisy or too simple

- Automatic mode is a heuristic. Switch to Basic and raise **Noise removal** or change **Path fitting**.
- Photographs become posterized regions on purpose.

## Transparent images look wrong

Use Basic/Advanced → **Preserve source transparency** and optionally
**Remove background by color** with a tolerance. These preprocess a copy before
tracing; the original file is never modified. VTracer 0.6.x still has no native
alpha-as-holes switch.

## Cancel does not stop instantly

The worker is a subprocess. Cancel sends terminate, then kill. In-flight Rust
work cannot checkpoint; the GUI should become idle within about a second.

## Export is empty

Vectorize successfully first. Export writes the backend SVG, not a screenshot.

## EPS is disabled or fails

EPS needs Inkscape on `PATH`. Vectorizer detects it at runtime and disables the
menu item when missing. Failures surface Inkscape’s stderr; conversions use a
timeout and never `shell=True`.

## DXF looks wrong in CAD

DXF export is outlines only with linearized curves. See `docs/DXF_NOTES.md`.

## Batch summary location

Batch writes `batch_summary.json` and `batch_summary.md` into the chosen output
folder.

## Permission errors

The app does not need administrator rights. Write exports to your home directory.
