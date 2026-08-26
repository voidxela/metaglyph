# Metaglyph

> Modern cross-platform desktop font browser and installer built with Python, PySide6, and Rust.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![GUI: PySide6](https://img.shields.io/badge/GUI-PySide6%20%28Qt%206%29-green.svg)](https://wiki.qt.io/Qt_for_Python)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

---

## 1. Overview

**Metaglyph** unifies multiple online font providers (Fontsource, Font Squirrel, Nerd Fonts) into a single, unified, high-performance desktop application. Key capabilities include:

- **Unified Font Catalog:** Multi-source deduplication across providers with deterministic priority resolution and automatic metadata merging.
- **Native Async Micro-Subsetting:** Zero-lag live font previews rendered with native Qt widgets (`QLabel`) via dynamic TrueType micro-subset extraction and runtime `QFontDatabase` loading.
- **Strict Privilege Isolation:** User-space fonts are installed directly without privileges; system-wide font installations are safely executed via a dedicated standalone Rust helper binary (`metaglyph-helper`) communicating via IPC JSON manifests.
- **Nerd Font Intelligence:** Proactive counterpart suggestions with one-click transitions and variant selection (`Standard`, `Mono`, `Propo`).
- **System Font Management:** Real-time OS font directory scanning, tracking of Metaglyph-managed fonts, and single-pass multi-scope batch uninstallation.

---

## 2. Installation & Quick Start

### Download Latest Release

For end users on Linux, download the standalone, self-contained **AppImage** from the [Latest Releases](https://github.com/voidxela/metaglyph/releases):

```bash
# 1. Download the latest Metaglyph-x86_64.AppImage from GitHub Releases
# 2. Make it executable and launch:
chmod +x Metaglyph-*.AppImage
./Metaglyph-*.AppImage
```

### Recommended AppImage Manager: Gear Lever

For the best desktop experience on Linux, we recommend using **[Gear Lever](https://flathub.org/apps/it.mijorus.gearlever)** to manage Metaglyph:

- **Automatic Desktop Integration:** Generates application menu entries, system tray integration, and MIME type handlers.
- **One-Click Updates:** Automatically tracks and updates to new tagged release versions.
- **Sandbox Management:** Manage permissions and sandbox settings with ease.

Install Gear Lever via Flatpak:
```bash
flatpak install flathub it.mijorus.gearlever
```
Or view the project on [GitHub](https://github.com/mijorus/gearlever).

---

## 3. Architecture & Tech Stack

```
+----------------------------------------------------------------------------+
|                             Metaglyph (PySide6)                            |
|  +----------------------------------------------------------------------+  |
|  | Discover Page  |  Search & Browse Page  |  System Registry View      |  |
|  +----------------------------------------------------------------------+  |
|  | Live Font Preview & Tuning Drawer (Size, Weight, Preset Pangrams)    |  |
|  +----------------------------------------------------------------------+  |
|                                     |                                      |
|    +--------------------------------+-------------------------------+      |
|    |                                |                               |      |
|    v                                v                               v      |
| [Subset Pipeline]           [SQLite Repository]           [Installer Core] |
| (fonttools + QFontDatabase) (Deduplicated Catalog)       (User / System)  |
+-------------------------------------------------------------------|--------+
                                                                    |
                                        [IPC JSON Manifest]         v
                                   +-----------------------------------------+
                                   |  metaglyph-helper (Standalone Rust)     |
                                   |  (Elevated: pkexec / Windows RunAs)     |
                                   +-----------------------------------------+
```

- **GUI Framework:** PySide6 (Qt for Python) with native async QSS dark theme
- **Async Concurrency:** Python `asyncio` integrated with Qt's event loop via `qasync`
- **Local Database:** SQLite via `aiosqlite` with WAL mode and foreign key constraints
- **Font Subsetting & Loader:** `fonttools` + `QFontDatabase` dynamic application font loading
- **System Helper:** Rust binary communicating via IPC JSON manifests (`pkexec` / `runas`)
- **Task Runner:** `just` (command runner)
- **Runtime:** Python 3.11+

---

## 4. Developer Setup & Justfile Workflow

We use **[just](https://github.com/casey/just)** as the standard command runner for testing, building, running, and packaging.

### Prerequisites

- Python 3.11 or higher
- Rust toolchain (`cargo` / `rustc`) for compiling the helper binary
- `just` task runner (`cargo install just` or your system package manager)

### Environment Setup

```bash
# 1. Clone repository
git clone https://github.com/voidxela/metaglyph.git
cd metaglyph

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies and Metaglyph in editable mode
pip install -e ".[dev]"
```

### Supported `just` Actions

| Command | Description |
| :--- | :--- |
| `just run` | Start the Metaglyph desktop app from source (warns if helper binary is missing). |
| `just test` | Run the complete test suite across app (Python) and helper (Rust). |
| `just test-app` | Run Python application tests and linting (`pytest`). |
| `just test-helper` | Run Cargo tests, check, and Clippy linting on the Rust helper. |
| `just build-helper` | Compile the standalone Rust privilege escalation helper in release mode. |
| `just package-linux` | Build the Rust helper and bundle a standalone Linux AppImage into `dist/linux`. |

---

## 5. Packaging & Distribution

### Building Linux AppImage

To package Metaglyph as a standalone Linux AppImage:

```bash
just package-linux
```

The build script will:
1. Compile the standalone Rust helper binary (`metaglyph-helper`).
2. Construct a relocatable `AppDir` containing all PySide6 libraries, Qt plugins, Python dependencies, icons, and desktop metadata.
3. Bundle the AppImage using `appimagetool` into:
   - `dist/linux/Metaglyph-<version>-<arch>.AppImage`
   - `dist/linux/Metaglyph-<arch>.AppImage` (symlink to latest)

---

## 6. Running Metaglyph

### A. Launch the Desktop Application

```bash
# Using Just task runner
just run

# Or using Python module directly
python -m metaglyph
```

### B. Headless Catalog Synchronization (CLI)

Synchronize font catalogs across Fontsource, Font Squirrel, and Nerd Fonts without launching the GUI:

```bash
python -m metaglyph --sync
```

*(Note: Catalogs can also be synchronized directly in the GUI using the **Sync Catalog** button on the sidebar).*

---

## 7. User Interface Overview

| View | Description |
| :--- | :--- |
| **✦ Discover** | Curated category dashboard for Featured, Interface, Code, Header, Prose, Display, and Handwriting typography with featured font spotlight cards. |
| **🔍 Search & Browse** | High-performance search with 200ms debounce, category/provider filter chips, variable & Nerd font toggles, and live micro-subset font previews. |
| **Inspector Drawer** | Real-time font tuner with live point size slider (10pt–72pt), weight selector (100–900), custom editable sample text, Nerd Font counterpart banner, and User/System scope installation. |
| **💻 System Registry** | OS font directory scanner tracking locally installed fonts and Metaglyph-managed installations with batch uninstallation. |

---

## 8. Directory Layout & Data Storage

Metaglyph follows standard OS directory conventions:

| Platform | Configuration Directory | Local Data & Database | Micro-Subset Cache |
| :--- | :--- | :--- | :--- |
| **Linux** | `~/.config/metaglyph/` | `~/.local/share/metaglyph/` | `~/.cache/metaglyph/subsets/` |
| **macOS** | `~/Library/Application Support/metaglyph/` | `~/Library/Application Support/metaglyph/` | `~/Library/Caches/metaglyph/subsets/` |
| **Windows** | `%APPDATA%\metaglyph\` | `%LOCALAPPDATA%\metaglyph\` | `%LOCALAPPDATA%\metaglyph\cache\subsets\` |

---

## 9. Running the Test Suite

Metaglyph includes a comprehensive test suite covering backend logic, database persistence, provider APIs, PySide6 UI components, and headless visual screenshot regression tests.

See **[`docs/TESTING.md`](docs/TESTING.md)** for the complete testing guide and API reference.

```bash
# Run all tests using just
just test

# Run non-visual app tests only
just test-app

# Run visual testing scenarios and generate HTML/Markdown gallery reports
python -m tests.visual.runner --output ./visual_reports

# Run targeted test suites
pytest tests/test_e2e_integration.py -v
pytest tests/test_concurrency_stress.py -v
pytest tests/test_memory_leak.py -v
pytest tests/test_resilience_edge_cases.py -v
```

---

## 10. License

This is free and unencumbered software released into the public domain (Unlicense). See [LICENSE](LICENSE) for details.
