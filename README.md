# Metaglyph

> Modern cross-platform desktop font browser and installer built with Python, PySide6, and Rust.

## Overview

Metaglyph unifies multiple font providers (Google Fonts, Fontsource, Nerd Fonts) into a single interface. Key capabilities include:

- **Unified Font Catalog:** Seamless deduplication across providers with deterministic priority resolution.
- **Native Async Micro-Subsetting:** Zero-lag live font previews rendered with native Qt widgets via dynamic subset font loading (`QFontDatabase`).
- **Privilege-Isolated Installation:** User-space fonts are installed directly without privileges; system-wide font installations are safely performed via a dedicated standalone Rust helper binary (`metaglyph-helper`).
- **Nerd Font Intelligence:** Proactive counterpart suggestions with variant switching (Standard, Mono, Propo).
- **System Font Management:** Local font registry scanning, tracking of Metaglyph-managed fonts, and batch uninstallation.

---

## Architecture

- **GUI Framework:** PySide6 (Qt for Python) with native async QSS dark theme
- **Async Concurrency:** Python `asyncio` integrated with Qt's event loop via `qasync`
- **Local Database:** SQLite via `aiosqlite`
- **Font Subsetting & Loader:** `fonttools` + `QFontDatabase` dynamic application font loading
- **System Helper:** Rust binary communicating via IPC JSON manifests (`pkexec` / `runas`)
- **Runtime:** Python 3.11+

---

## Installation & Running from Source

### 1. Prerequisites

- Python 3.11 or higher
- Rust toolchain (`cargo` / `rustc`) for building the optional privilege helper

### 2. Environment Setup

```bash
# Clone repository
git clone https://github.com/voidxela/metaglyph.git
cd metaglyph

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and Metaglyph in editable mode
pip install -e ".[dev]"
```

### 3. Launching the Application

Run the desktop application directly using Python or the installed CLI entry point:

```bash
# Launch the PySide6 Desktop GUI
python -m metaglyph

# Or using the console script
metaglyph
```

### 4. Headless Catalog Synchronization (Optional CLI)

You can synchronize font metadata catalogs from Google Fonts, Fontsource, and Nerd Fonts without launching the UI:

```bash
python -m metaglyph --sync
```

*(Note: You can also sync catalogs directly inside the GUI using the **Sync Catalog** button on the sidebar or discover dashboard).*

### 5. Building the Rust Helper Binary (Optional)

To enable system-wide font installations (in `/usr/local/share/fonts` or `C:\Windows\Fonts`), build the standalone Rust helper binary:

```bash
cd helper
cargo build --release
cd ..
```

---

## UI Overview

| View | Description |
| :--- | :--- |
| **✦ Discover** | Curated category dashboard for Interface, Code, Header, Prose, Display, and Handwriting typography with featured font spotlight cards. |
| **🔍 Search & Browse** | High-performance search with 200ms debounce, category/provider filter chips, variable & Nerd font toggles, and live micro-subset font previews. |
| **Inspector Drawer** | Real-time font tuner with live point size slider (10pt–72pt), weight selector (100–900), custom editable sample text, Nerd Font counterpart banner, and User/System scope installation. |
| **💻 System Registry** | OS font directory scanner tracking locally installed fonts and Metaglyph-managed installations. |

---

## Running Tests

Run the complete test suite across normalization, database repository, providers, micro-subsetting, installer, and UI components:

```bash
pytest
```

---

## License

This is free and unencumbered software released into the public domain (Unlicense).
