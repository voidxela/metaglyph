# AI Agent Instructions for Metaglyph

Welcome. If you are an AI coding assistant, autonomous agent, or copilot contributing to this repository, you must strictly adhere to the guidelines and constraints outlined in this document.

## 1. Project Specification (Source of Truth)
Before writing code, generating components, or altering schemas, you **must** review the project specification located at:
**`docs/SPEC.md`**

This document outlines the core architecture, data flow, and user experience requirements. All implementation decisions must align with this specification.

## 2. Architectural Constraints
* **GUI Framework:** Use PySide6 exclusively. Do not generate code for PyQt5, PyQt6, or Tkinter.
* **No WebViews:** Do not use `QWebEngineView` for font rendering. Metaglyph uses a native async subsetting approach for live previews as defined in the spec.
* **Privilege Escalation:** Do not attempt to escalate the main Python UI process using `sudo`, `pkexec`, or Windows UAC natively in Python. All system-level file operations must be delegated to the separate Rust helper binary via IPC (JSON manifests).
* **Concurrency:** The main Qt UI thread must never block. Use `asyncio` integrations (e.g., `qasync`) or `QThread`/`QRunnable` for network requests, SQLite database queries, and filesystem operations.
* **Python Version:** Target Python 3.11+. Use modern type hinting (`str | None` instead of `Optional[str]`).

## 3. Testing Requirements & UI Validation
* **Testing Guide:** Detailed testing instructions are documented in **`docs/TESTING.md`**.
* **Mandatory UI Validation:** When modifying, creating, or refactoring UI components, views, layouts, or stylesheets, you **must run the visual tests** (`pytest tests/visual -v` or `python -m tests.visual.runner`) and validate the visual rendering of all affected UI states before considering a task complete.
* **Non-Visual Tests:** For non-UI tasks (backend, database, providers), you may run standard tests quickly with `pytest -m "not visual"`.

## 4. Commit Guidelines
You are expected to commit your work incrementally as you complete logical blocks or resolve specific tasks. 

You **must** format all your commits using **subject-only Conventional Commits**. Do not generate multiline commit messages, bodies, or footers.

**Format:** `<type>(<optional scope>): <description>`

**Valid Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

**Examples of valid commits:**
* `feat: add async fontsource api client`
* `fix: prevent ui thread block during sqlite deduplication`
* `chore: initialize rust helper binary cargo project`
* `refactor(ui): extract discover page grid into reusable widget`

**Invalid commit (Do not do this):**
```text
feat: add google fonts provider

Implemented the base class and added the google fonts API parser.
Fixes issue with the search bar.
```