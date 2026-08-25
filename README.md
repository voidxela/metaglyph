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

## 2. Architecture & Tech Stack

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
- **Runtime:** Python 3.11+

---

## 3. Installation & Developer Setup

### Prerequisites

- Python 3.11 or higher
- Optional: Rust toolchain (`cargo` / `rustc`) for building the privilege escalation helper

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

---

## 4. Running Metaglyph

### A. Launch the Desktop Application

Run the PySide6 desktop GUI directly:

```bash
# Using python module
python -m metaglyph

# Or using the console script
metaglyph
```

### B. Headless Catalog Synchronization (CLI)

Synchronize font catalogs across Fontsource, Font Squirrel, and Nerd Fonts without launching the GUI:

```bash
python -m metaglyph --sync
```

*(Note: Catalogs can also be synchronized directly in the GUI using the **Sync Catalog** button on the sidebar).*

### C. Building the Rust Helper Binary (Optional)

To enable system-wide font installations (e.g., in `/usr/local/share/fonts` on Linux or `C:\Windows\Fonts` on Windows), compile the standalone Rust helper binary:

```bash
cd helper
cargo build --release
cd ..
```

---

## 5. User Interface Overview

| View | Description |
| :--- | :--- |
| **✦ Discover** | Curated category dashboard for Interface, Code, Header, Prose, Display, and Handwriting typography with featured font spotlight cards. |
| **🔍 Search & Browse** | High-performance search with 200ms debounce, category/provider filter chips, variable & Nerd font toggles, and live micro-subset font previews. |
| **Inspector Drawer** | Real-time font tuner with live point size slider (10pt–72pt), weight selector (100–900), custom editable sample text, Nerd Font counterpart banner, and User/System scope installation. |
| **💻 System Registry** | OS font directory scanner tracking locally installed fonts and Metaglyph-managed installations with batch uninstallation. |

---

## 6. Directory Layout & Data Storage

Metaglyph follows standard OS directory conventions:

| Platform | Configuration Directory | Local Data & Database | Micro-Subset Cache |
| :--- | :--- | :--- | :--- |
| **Linux** | `~/.config/metaglyph/` | `~/.local/share/metaglyph/` | `~/.cache/metaglyph/subsets/` |
| **macOS** | `~/Library/Application Support/metaglyph/` | `~/Library/Application Support/metaglyph/` | `~/Library/Caches/metaglyph/subsets/` |
| **Windows** | `%APPDATA%\metaglyph\` | `%LOCALAPPDATA%\metaglyph\` | `%LOCALAPPDATA%\metaglyph\cache\subsets\` |

---

## 7. Running the Test Suite

Metaglyph includes a comprehensive test suite covering backend logic, database persistence, provider APIs, PySide6 UI components, and headless visual screenshot regression tests.

See **[`docs/TESTING.md`](docs/TESTING.md)** for the complete testing guide and API reference.

```bash
# Run all tests (including visual tests in headless offscreen mode)
pytest -v

# Run non-visual tests only (fastest)
pytest -m "not visual" -v

# Run visual testing scenarios and generate HTML/Markdown gallery reports
python -m tests.visual.runner --output ./visual_reports

# Run targeted test suites
pytest tests/test_e2e_integration.py -v
pytest tests/test_concurrency_stress.py -v
pytest tests/test_memory_leak.py -v
pytest tests/test_resilience_edge_cases.py -v
```

---

## 8. License

This is free and unencumbered software released into the public domain (Unlicense). See [LICENSE](LICENSE) for details.
