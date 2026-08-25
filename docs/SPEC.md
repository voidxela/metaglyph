# Metaglyph: Application Specification

## 1. Executive Summary

**Metaglyph** is a desktop font browser and installer built with Python and PySide6. It unifies multiple font providers (Fontsource, Font Squirrel, Nerd Fonts) into a single interface, featuring native async font subsetting for lightweight live previews, local metadata deduplication, and a secure Rust-based helper binary for handling OS-level system font installations.

## 2. Core Technologies

* **Primary Application:** Python 3.11+
* **GUI Framework:** PySide6 (Qt for Python)
* **System Integrations:** Rust (for the privilege escalation helper binary)
* **Local Data Store:** SQLite (for caching metadata and tracking installed fonts)
* **Concurrency:** Python `asyncio` integrated with Qt's `QThread` event loop via `qasync` or native QRunnable wrappers.

## 3. Architecture & Data Flow

### The Provider Interface & Deduplication

The `BaseFontProvider` class defines the contract for external sources (`fetch_catalog()`, `search()`, `download_font()`).

* **Deduplication:** A local SQLite database merges metadata across providers. Fonts are uniquely keyed by `normalize(font_family_name)`. A priority matrix dictates which provider serves the download if a font exists across multiple sources.
* **State Tracking:** SQLite tracks `family_name`, `provider`, `install_scope` (`User` | `System`), and `file_paths` for accurate uninstallation and system state mirroring.

### Native Async Live Previews

To achieve performant live previews without embedding Chromium (`QWebEngineView`), Metaglyph utilizes dynamic font subsetting.

1. **Request:** As the user scrolls the search list, an async worker requests small, subsetted `.ttf` files from the provider APIs containing only the glyphs required for a static sample string (e.g., "The quick brown fox...").
2. **Load:** These micro-files are saved to a temporary directory and loaded into Qt via `QFontDatabase.addApplicationFont(path)`.
3. **Render:** Standard native Qt widgets (`QLabel`) display the subsetted fonts.
*(Note: Editing the sample text dynamically is deferred for a future iteration to manage API request volume.)*

### Privilege Escalation: The Rust Helper

System-level font installations (e.g., `/usr/local/share/fonts` on Linux, `C:\Windows\Fonts`) require elevated privileges. This is handled by a separate, statically compiled Rust binary.

1. **Payload Generation:** The Python app downloads the fonts to a temporary directory and writes an `install_manifest.json` file detailing source paths and target OS font directories.
2. **Execution:** The Python app spawns the Rust binary as a subprocess, requesting privilege escalation natively via the OS (e.g., `pkexec` on Linux, `runas` on Windows). The path to the JSON manifest is passed as a CLI argument.
3. **Operation:** The elevated Rust binary reads the JSON, performs the file copies, executes the OS-specific font cache rebuild commands (e.g., `fc-cache`, `AddFontResource`), and exits with a status code.
4. **UI Feedback:** The Python app awaits the exit code and updates the UI and SQLite database accordingly. User-level installations bypass the Rust helper entirely.

## 4. User Interface & Experience

The application is structured around three primary views accessed via a sidebar navigation, styled using Qt Style Sheets (QSS) for a modern aesthetic.

### A. Discover Page

A visual dashboard using `QScrollArea` and grid layouts to present curated font groupings.

* **Categories:** Featured, Interface, Code, Header, Prose, Display, Handwriting. Clicking a category acts as a quick-filter for the Search page.

### B. Search & Browse Page

* **Filters:** Toggles for Providers (Fontsource, Font Squirrel, Nerd Fonts) and structural Categories (Serif, Sans-Serif, Monospace, Variable).
* **Results List:** Displays the natively rendered subsetted fonts based on the static sample text.
* **Detail Pane:** Clicking a font loads the full `.ttf`/`.otf` file into the temporary cache, allowing manipulation of `QFont.setPointSizeF()` and `QFont.setWeight()`.

### C. System Page

* **Registry View:** Lists all OS-level system fonts alongside user-installed fonts, cross-referencing the SQLite database to identify fonts installed specifically via Metaglyph.
* **Management:** Users can select fonts to batch uninstall. Metaglyph utilizes the stored `file_paths` to delete the local files and rebuild the OS font cache.

## 5. Nerd Font Integration

Metaglyph proactively suggests patched, developer-friendly versions of standard fonts.

1. **Mapping:** The system utilizes the `unpatchedName` field from the Nerd Font repository metadata. Suffixes are stripped and strings normalized for reliable matching against standard fonts (e.g., matching "Fira Code" to "FiraCode Nerd Font").
2. **Suggestion UI:** When a user selects a mappable font (e.g., JetBrains Mono), a prominent `QFrame` appears in the detail pane indicating a Nerd Font version is available.
3. **Variant Selection:** Clicking the suggestion presents the user with a choice of the available Nerd Font variants (e.g., Standard, Mono, Propo) before proceeding with the installation.