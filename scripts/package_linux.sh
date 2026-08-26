#!/usr/bin/env bash
set -euo pipefail

# Project root resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Configuration
ARCH="${ARCH:-$(uname -m)}"
VERSION="${VERSION:-$(python3 -c 'import tomllib; f=open("pyproject.toml", "rb"); print(tomllib.load(f)["project"]["version"])' 2>/dev/null || echo "0.1.0")}"
DIST_DIR="${REPO_ROOT}/dist/linux"
BUILD_DIR="${REPO_ROOT}/build/appimage"
APP_DIR="${BUILD_DIR}/AppDir"
TOOLS_DIR="${REPO_ROOT}/build/tools"

echo "========================================"
echo " Packaging Metaglyph v${VERSION} (${ARCH}) for Linux"
echo "========================================"

mkdir -p "${DIST_DIR}"
mkdir -p "${APP_DIR}/usr/bin"
mkdir -p "${APP_DIR}/usr/share/applications"
mkdir -p "${APP_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${APP_DIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${APP_DIR}/usr/share/icons/hicolor/512x512/apps"
mkdir -p "${TOOLS_DIR}"

# 1. Ensure Rust helper is present
HELPER_BIN="${REPO_ROOT}/helper/target/release/metaglyph-helper"
if [ ! -f "${HELPER_BIN}" ]; then
    echo "metaglyph-helper binary not found in release target. Checking for cargo..."
    if command -v cargo >/dev/null 2>&1; then
        echo "Building metaglyph-helper in release mode..."
        cargo build --release --manifest-path "${REPO_ROOT}/helper/Cargo.toml"
    elif [ -f "${REPO_ROOT}/bin/metaglyph-helper" ]; then
        HELPER_BIN="${REPO_ROOT}/bin/metaglyph-helper"
    else
        echo "WARNING: Cargo not found and metaglyph-helper binary not present. Packaging will proceed without embedded helper binary." >&2
    fi
fi

if [ -f "${HELPER_BIN}" ]; then
    echo "Embedding helper binary: ${HELPER_BIN}"
    cp "${HELPER_BIN}" "${APP_DIR}/usr/bin/metaglyph-helper"
    chmod +x "${APP_DIR}/usr/bin/metaglyph-helper"
fi

# 2. Build or update isolated Python venv in AppDir
echo "Setting up application environment in AppDir..."
if [ ! -d "${APP_DIR}/usr/venv" ]; then
    python3 -m venv --copies "${APP_DIR}/usr/venv"
fi

echo "Installing Metaglyph dependencies into AppDir..."
"${APP_DIR}/usr/venv/bin/pip" install --upgrade pip
"${APP_DIR}/usr/venv/bin/pip" install "${REPO_ROOT}"

# 3. Ensure assets (icons and desktop entry)
if [ ! -f "${REPO_ROOT}/assets/icons/metaglyph.svg" ] || [ ! -f "${REPO_ROOT}/assets/icons/metaglyph.png" ]; then
    echo "Generating application icons..."
    QT_QPA_PLATFORM=offscreen python3 "${REPO_ROOT}/scripts/generate_icons.py" || true
fi

if [ -f "${REPO_ROOT}/assets/metaglyph.desktop" ]; then
    cp "${REPO_ROOT}/assets/metaglyph.desktop" "${APP_DIR}/metaglyph.desktop"
    cp "${REPO_ROOT}/assets/metaglyph.desktop" "${APP_DIR}/usr/share/applications/metaglyph.desktop"
fi

if [ -f "${REPO_ROOT}/assets/icons/metaglyph.svg" ]; then
    cp "${REPO_ROOT}/assets/icons/metaglyph.svg" "${APP_DIR}/metaglyph.svg"
    cp "${REPO_ROOT}/assets/icons/metaglyph.svg" "${APP_DIR}/.DirIcon"
    cp "${REPO_ROOT}/assets/icons/metaglyph.svg" "${APP_DIR}/usr/share/icons/hicolor/scalable/apps/metaglyph.svg"
fi

if [ -f "${REPO_ROOT}/assets/icons/metaglyph.png" ]; then
    cp "${REPO_ROOT}/assets/icons/metaglyph.png" "${APP_DIR}/metaglyph.png"
    cp "${REPO_ROOT}/assets/icons/metaglyph.png" "${APP_DIR}/usr/share/icons/hicolor/256x256/apps/metaglyph.png"
fi

if [ -f "${REPO_ROOT}/assets/icons/metaglyph-512.png" ]; then
    cp "${REPO_ROOT}/assets/icons/metaglyph-512.png" "${APP_DIR}/usr/share/icons/hicolor/512x512/apps/metaglyph.png"
fi

# 4. Create AppRun launcher
cat << 'EOF' > "${APP_DIR}/AppRun"
#!/usr/bin/env bash
set -e

# Discover AppDir location
HERE="$(dirname "$(readlink -f "${0}")")"
export APPDIR="${HERE}"

# Discover Python site-packages
for p in "${APPDIR}/usr/venv/lib"/python3.*/site-packages "${APPDIR}/usr/venv/lib64"/python3.*/site-packages "${APPDIR}/usr/lib"/python3.*/site-packages; do
    if [ -d "${p}" ]; then
        export PYTHONPATH="${p}:${PYTHONPATH:-}"
    fi
done

# Configure Qt dynamic library and plugin paths
for p in "${APPDIR}/usr/venv/lib"/python3.*/site-packages/PySide6 "${APPDIR}/usr/venv/lib64"/python3.*/site-packages/PySide6; do
    if [ -d "${p}/Qt/lib" ]; then
        export LD_LIBRARY_PATH="${p}/Qt/lib:${APPDIR}/usr/lib:${LD_LIBRARY_PATH:-}"
        export QT_PLUGIN_PATH="${p}/Qt/plugins:${QT_PLUGIN_PATH:-}"
        break
    fi
done

export PATH="${APPDIR}/usr/venv/bin:${APPDIR}/usr/bin:${PATH}"
export METAGLYPH_HELPER_PATH="${APPDIR}/usr/bin/metaglyph-helper"

if [ -x "${APPDIR}/usr/venv/bin/python3" ]; then
    exec "${APPDIR}/usr/venv/bin/python3" -m metaglyph "$@"
elif [ -x "${APPDIR}/usr/bin/python3" ]; then
    exec "${APPDIR}/usr/bin/python3" -m metaglyph "$@"
else
    exec python3 -m metaglyph "$@"
fi
EOF
chmod +x "${APP_DIR}/AppRun"

# 5. Acquire appimagetool
APPIMAGETOOL_EXEC=""
if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL_EXEC="appimagetool"
elif [ -x "${TOOLS_DIR}/squashfs-root/AppRun" ]; then
    APPIMAGETOOL_EXEC="${TOOLS_DIR}/squashfs-root/AppRun"
else
    echo "Downloading appimagetool..."
    TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    curl -Lo "${TOOLS_DIR}/appimagetool" "${TOOL_URL}"
    chmod +x "${TOOLS_DIR}/appimagetool"
    (
        cd "${TOOLS_DIR}"
        ./appimagetool --appimage-extract >/dev/null 2>&1 || true
    )
    if [ -x "${TOOLS_DIR}/squashfs-root/AppRun" ]; then
        APPIMAGETOOL_EXEC="${TOOLS_DIR}/squashfs-root/AppRun"
    else
        APPIMAGETOOL_EXEC="${TOOLS_DIR}/appimagetool"
    fi
fi

# 6. Generate AppImage
TARGET_APPIMAGE="${DIST_DIR}/Metaglyph-${VERSION}-${ARCH}.AppImage"
LATEST_APPIMAGE="${DIST_DIR}/Metaglyph-${ARCH}.AppImage"

echo "Building AppImage package: ${TARGET_APPIMAGE}"
ARCH="${ARCH}" "${APPIMAGETOOL_EXEC}" "${APP_DIR}" "${TARGET_APPIMAGE}"

ln -sf "$(basename "${TARGET_APPIMAGE}")" "${LATEST_APPIMAGE}"

echo ""
echo "========================================"
echo " Build successful!"
echo " Output files:"
echo "   - ${TARGET_APPIMAGE}"
echo "   - ${LATEST_APPIMAGE}"
echo " Size: $(du -h "${TARGET_APPIMAGE}" | cut -f1)"
echo "========================================"
