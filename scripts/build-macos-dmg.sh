#!/usr/bin/env bash
# Build Vectorizer.app and a distributable .dmg (must run on macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS DMG builds require macOS (PyInstaller cannot cross-compile)." >&2
  echo "On Linux, push to GitHub and run the 'Build macOS DMG' workflow, or" >&2
  echo "copy this repo to a Mac and re-run: ./scripts/build-macos-dmg.sh" >&2
  exit 1
fi

PYTHON_BIN="${ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi
VERSION="$("${PYTHON_BIN}" - <<'PY'
from pathlib import Path
text = Path("src/vectorizer/__init__.py").read_text(encoding="utf-8")
for line in text.splitlines():
    if line.startswith("__version__"):
        print(line.split("=", 1)[1].strip().strip("\"'"))
        break
else:
    raise SystemExit("version not found")
PY
)"
APP_NAME="Vectorizer"
DMG_NAME="${APP_NAME}-${VERSION}-macos.dmg"
SPEC="${ROOT}/packaging/macos/vectorizer.spec"
DIST="${ROOT}/dist"
BUILD="${ROOT}/build"
STAGE="${DIST}/dmg-stage"
APP_BUNDLE="${DIST}/${APP_NAME}.app"

echo "==> Preparing venv"
if [[ ! -x "${ROOT}/.venv/bin/python" ]]; then
  python3 -m venv "${ROOT}/.venv"
fi
# shellcheck disable=SC1091
source "${ROOT}/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e ".[dev,packaging]"
python "${ROOT}/scripts/make-icns.py"

echo "==> Cleaning previous build"
rm -rf "${BUILD}/vectorizer" "${DIST}/${APP_NAME}" "${APP_BUNDLE}" "${STAGE}" "${DIST}/${DMG_NAME}"

echo "==> PyInstaller"
pyinstaller --noconfirm --clean --distpath "${DIST}" --workpath "${BUILD}" "${SPEC}"

if [[ ! -d "${APP_BUNDLE}" ]]; then
  echo "Expected app bundle missing: ${APP_BUNDLE}" >&2
  exit 1
fi

echo "==> Staging DMG contents"
mkdir -p "${STAGE}"
cp -R "${APP_BUNDLE}" "${STAGE}/"
ln -s /Applications "${STAGE}/Applications"

echo "==> Creating ${DMG_NAME}"
if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
    --volname "${APP_NAME}" \
    --volicon "${ROOT}/packaging/macos/Vectorizer.icns" \
    --window-pos 200 120 \
    --window-size 640 400 \
    --icon-size 100 \
    --icon "${APP_NAME}.app" 160 180 \
    --hide-extension "${APP_NAME}.app" \
    --app-drop-link 460 180 \
    --no-internet-enable \
    "${DIST}/${DMG_NAME}" \
    "${STAGE}"
else
  echo "create-dmg not found; using hdiutil (plain DMG)."
  hdiutil create \
    -volname "${APP_NAME}" \
    -srcfolder "${STAGE}" \
    -ov \
    -format UDZO \
    "${DIST}/${DMG_NAME}"
fi

rm -rf "${STAGE}"
echo
echo "Built:"
ls -lh "${DIST}/${DMG_NAME}" "${APP_BUNDLE}"
echo
echo "Install: open the DMG and drag Vectorizer into Applications."
echo "Unsigned builds: right-click the app → Open the first time (Gatekeeper)."
