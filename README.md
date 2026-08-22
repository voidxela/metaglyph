# Metaglyph

> Modern cross-platform desktop font browser and installer built with Python, PySide6, and Rust.

## Overview

Metaglyph unifies multiple font providers (Google Fonts, Fontsource, Nerd Fonts) into a single interface. Key capabilities include:

- **Unified Font Catalog:** Seamless deduplication across providers with deterministic priority resolution.
- **Native Async Micro-Subsetting:** Zero-lag live font previews rendered with native Qt widgets via dynamic subset font loading (`QFontDatabase`).
- **Privilege-Isolated Installation:** User-space fonts are installed directly without privileges; system-wide font installations are safely performed via a dedicated standalone Rust helper binary (`metaglyph-helper`).
- **Nerd Font Intelligence:** Proactive counter-part suggestions with variant switching (Standard, Mono, Propo).
- **System Font Management:** Local font registry scanning, tracking of Metaglyph-managed fonts, and batch uninstallation.

## Architecture

- **GUI Framework:** PySide6 (Qt for Python)
- **Local Database:** SQLite via `aiosqlite`
- **System Helper:** Rust binary communicating via IPC JSON manifests
- **Runtime:** Python 3.11+

## Development Setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and package in editable mode
pip install -e ".[dev]"

# Run tests
pytest
```

## License

This is free and unencumbered software released into the public domain (Unlicense).
