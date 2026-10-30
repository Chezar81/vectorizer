#!/usr/bin/env bash
# Build a self-contained amd64 .deb (must run on Linux).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Linux .deb builds require Linux." >&2
  exit 1
fi

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "dpkg-deb is required (Debian/Ubuntu/Mint)." >&2
  exit 1
fi

ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
PYTHON_BIN="${ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  python3 -m venv "${ROOT}/.venv"
  PYTHON_BIN="${ROOT}/.venv/bin/python"
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

PKG_NAME="vectorizer"
DEB_NAME="${PKG_NAME}_${VERSION}_${ARCH}.deb"
SPEC="${ROOT}/packaging/linux/vectorizer.spec"
DIST="${ROOT}/dist"
BUILD="${ROOT}/build"
STAGE="${DIST}/deb-stage"
OPT_DIR="${STAGE}/opt/${PKG_NAME}"
APP_DIR="${DIST}/${PKG_NAME}"

echo "==> Preparing venv"
# shellcheck disable=SC1091
source "${ROOT}/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e ".[dev,packaging]"

echo "==> Cleaning previous build"
rm -rf "${BUILD}/vectorizer" "${APP_DIR}" "${STAGE}" "${DIST}/${DEB_NAME}"

echo "==> PyInstaller"
pyinstaller --noconfirm --clean --distpath "${DIST}" --workpath "${BUILD}" "${SPEC}"

if [[ ! -x "${APP_DIR}/vectorizer" ]]; then
  echo "Expected binary missing: ${APP_DIR}/vectorizer" >&2
  exit 1
fi

echo "==> Staging Debian package tree"
mkdir -p \
  "${OPT_DIR}" \
  "${STAGE}/usr/bin" \
  "${STAGE}/usr/share/applications" \
  "${STAGE}/usr/share/doc/${PKG_NAME}" \
  "${STAGE}/DEBIAN"

cp -a "${APP_DIR}/." "${OPT_DIR}/"

cat > "${STAGE}/usr/bin/vectorizer" <<'EOF'
#!/usr/bin/env bash
exec /opt/vectorizer/vectorizer "$@"
EOF
chmod 755 "${STAGE}/usr/bin/vectorizer"

sed \
  -e 's|^Exec=vectorizer|Exec=/usr/bin/vectorizer|' \
  -e 's|^TryExec=vectorizer|TryExec=/usr/bin/vectorizer|' \
  "${ROOT}/packaging/vectorizer.desktop" \
  > "${STAGE}/usr/share/applications/vectorizer.desktop"
chmod 644 "${STAGE}/usr/share/applications/vectorizer.desktop"

if [[ -d "${ROOT}/packaging/icons/hicolor" ]]; then
  mkdir -p "${STAGE}/usr/share/icons"
  cp -a "${ROOT}/packaging/icons/hicolor" "${STAGE}/usr/share/icons/"
fi

{
  echo "Vectorizer ${VERSION}"
  echo
  echo "Offline raster-to-vector desktop application."
  echo "Homepage: https://github.com/Chezar81/vectorizer"
  echo
  echo "Installed under /opt/vectorizer with launcher /usr/bin/vectorizer."
} > "${STAGE}/usr/share/doc/${PKG_NAME}/README"
cp "${ROOT}/LICENSE" "${STAGE}/usr/share/doc/${PKG_NAME}/copyright"
chmod 644 "${STAGE}/usr/share/doc/${PKG_NAME}/"*

INSTALLED_SIZE="$(du -sk "${STAGE}" | awk '{print $1}')"

cat > "${STAGE}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE}
Maintainer: Christoph Rupprich <Chezar81@users.noreply.github.com>
Homepage: https://github.com/Chezar81/vectorizer
Depends: libc6, libxcb-cursor0 | libxcb-cursor0t64
Description: Offline raster-to-vector conversion
 Vectorizer turns bitmap images into editable SVG paths with a Qt desktop UI.
 Bundles Python, PySide6, Pillow, and VTracer under /opt/vectorizer.
EOF

cat > "${STAGE}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
fi
exit 0
EOF
chmod 755 "${STAGE}/DEBIAN/postinst"

# Drop world-writable bits; keep owner execute on binaries.
find "${STAGE}" -type d -exec chmod 755 {} +
find "${STAGE}" -type f -exec chmod go-w {} +
chmod 755 "${OPT_DIR}/vectorizer" "${STAGE}/usr/bin/vectorizer"

echo "==> Building ${DEB_NAME}"
dpkg-deb --root-owner-group --build "${STAGE}" "${DIST}/${DEB_NAME}"
rm -rf "${STAGE}"

echo
ls -lh "${DIST}/${DEB_NAME}"
echo "Install with: sudo apt install ./${DEB_NAME}"
echo "Remove with:  sudo apt remove ${PKG_NAME}"
