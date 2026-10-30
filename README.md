# Vectorizer

Independent, offline raster-to-vector desktop application (primary target:
Linux Mint; macOS via DMG). It imports a bitmap, traces it into editable SVG
paths, lets you inspect and correct segmentation, and exports SVG / PDF / PNG /
DXF (plus optional EPS).

**Author:** Christoph Rupprich.

Current milestone: **4** — batch processing, optional EPS, native DXF, user packaging.

## Download

Pre-built installers are on the
[**GitHub Releases**](https://github.com/Chezar81/vectorizer/releases/latest)
page (currently [v0.4.0](https://github.com/Chezar81/vectorizer/releases/tag/v0.4.0)):

| Platform | File | How to install |
| --- | --- | --- |
| **macOS** (Apple Silicon) | `Vectorizer-*-macos-arm64.dmg` | Open the DMG and drag **Vectorizer** into Applications. First launch of an unsigned build: right-click → **Open**. |
| **Windows** (x64) | `Vectorizer-*-windows-x64.zip` | Unzip and run **`Vectorizer.exe`**. Windows may warn about an unrecognized app (unsigned build). |
| **Linux** (amd64) | `vectorizer_*_amd64.deb` | `sudo apt install ./vectorizer_*_amd64.deb` — remove later with `sudo apt remove vectorizer`. |

The same release also offers a source archive and a pip wheel if you prefer to
run from a virtualenv (see **Setup** below).

## Environment

Developed and tested on:

- Linux Mint 22.3 (Zena), Cinnamon, Ubuntu noble base
- Desktop theme: **Mint-Y-Aqua** (accent `#1f9ede`)
- Python 3.12.3 from the system interpreter
- CPU-only (no GPU required)
- No cloud APIs, accounts, telemetry, or runtime downloads

## Setup (project-local virtualenv)

Do not install into system Python.

```bash
cd "/path/to/Vectorizer"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Or install a user launcher, app icon, and menu/desktop starter (no sudo):

```bash
./scripts/install-user.sh
```

Afterwards open **Vectorizer** from the application menu (or the Desktop shortcut).
The shell command `vectorizer` works when `~/.local/bin` is on your `PATH`.

## Run

```bash
source .venv/bin/activate
vectorizer
```

Or without activating the venv (after `install-user.sh`):

```bash
vectorizer
```

Headless single file:

```bash
python -m vectorizer path/to/logo.png -o path/to/logo.svg
```

Batch (sequential):

```bash
python -m vectorizer --batch path/to/images --outdir path/to/out --formats svg,pdf,dxf
```

### GUI workflow

1. Open an image (or a `.vproj` project). **Automatic** mode classifies content
   (logo, line art, photo, …) and tunes tracing + preprocess for you.
2. Vectorize (F5); edit **Segmentation** and retrace (F6) if needed.
3. Export SVG / PDF / PNG / DXF; EPS if Inkscape is installed.
4. **File → Batch process…** for folders (shared settings, collision policy, summary).

## Optional system tools

| Tool | Purpose |
| --- | --- |
| Inkscape | EPS export only (detected at runtime; UI disables if missing) |

DXF does not need Inkscape. See `docs/DXF_NOTES.md`.

## Tests

```bash
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m pytest
```

## Packaging (developers)

See `docs/PACKAGING.md` for building packages yourself.

- **End users:** prefer the [Release downloads](#download) above.
- **Linux:** `.deb` via `./scripts/build-linux-deb.sh`; user launcher via
  `./scripts/install-user.sh`. AppImage is **not** claimed ready.
- **macOS:** `./scripts/build-macos-dmg.sh` on a Mac, or the **Build macOS DMG**
  GitHub Action.
- **Windows:** `.\scripts\build-windows-exe.ps1` on Windows, or the
  **Build Windows EXE** GitHub Action.

## License

Application code: MIT (see `LICENSE`).
Third-party notices: `docs/THIRD_PARTY_LICENSES.md`.
