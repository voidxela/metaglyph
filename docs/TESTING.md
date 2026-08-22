# Metaglyph Testing Guide

This guide provides comprehensive instructions for running and writing tests in **Metaglyph**, covering unit tests, integration tests, end-to-end user workflows, and the headless visual testing harness.

---

## 1. Quick Start

### Prerequisites
Ensure you have set up your Python 3.11+ virtual environment and installed all dependencies, including development extras:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Metaglyph in editable mode with development dependencies
pip install -e ".[dev]"
```

### Running All Tests
To run the entire test suite (unit, integration, and visual tests):

```bash
pytest -v
```

> **Note:** Tests run in headless offscreen mode (`QT_QPA_PLATFORM=offscreen`) by default, so no display server (X11/Wayland) is required.

---

## 2. Standard Testing Suite

The standard test suite is located in the `tests/` directory and covers all backend, data persistence, network provider, and UI components.

### Test Categories

| Test File | Focus Area |
|---|---|
| [`tests/test_normalizer.py`](file:///home/alex/Develop/metaglyph/tests/test_normalizer.py) | Slug generation, Nerd Font counterpart extraction, curated category heuristics, provider priority matrix. |
| [`tests/test_db_repository.py`](file:///home/alex/Develop/metaglyph/tests/test_db_repository.py) | SQLite schema migrations, asynchronous repository queries, deduplication, full-text search, installation tracking. |
| [`tests/test_providers.py`](file:///home/alex/Develop/metaglyph/tests/test_providers.py) | Google Fonts, Fontsource, and Nerd Fonts API parsers, download mechanisms, and provider manager routing. |
| [`tests/test_subsetting.py`](file:///home/alex/Develop/metaglyph/tests/test_subsetting.py) | Dynamic `fontTools` glyph subsetting, font cache management, LRU eviction, and `QFontDatabase` application loading. |
| [`tests/test_ui_components.py`](file:///home/alex/Develop/metaglyph/tests/test_ui_components.py) | PySide6 widget units (`SearchBar`, `FilterBar`, `FontCard`, `FontPreviewWidget`, `SidebarWidget`, `ThemeManager`). |
| [`tests/test_detail_pane.py`](file:///home/alex/Develop/metaglyph/tests/test_detail_pane.py) | Font inspector drawer, weight/size sliders, Nerd Font variant picker, install/uninstall actions. |
| [`tests/test_system_view.py`](file:///home/alex/Develop/metaglyph/tests/test_system_view.py) | OS font registry view, scope filtering, multi-select checkboxes, and batch uninstaller. |
| [`tests/test_e2e_integration.py`](file:///home/alex/Develop/metaglyph/tests/test_e2e_integration.py) | Complete user journeys (Browse → Inspect → Install → System Registry → Batch Uninstall). |
| [`tests/test_concurrency_stress.py`](file:///home/alex/Develop/metaglyph/tests/test_concurrency_stress.py) | UI thread non-blocking validation during heavy network/DB loads. |
| [`tests/test_memory_leak.py`](file:///home/alex/Develop/metaglyph/tests/test_memory_leak.py) | Font loader memory eviction, resource cleanup, and widget disposal. |
| [`tests/test_resilience_edge_cases.py`](file:///home/alex/Develop/metaglyph/tests/test_resilience_edge_cases.py) | Fault tolerance against corrupted font binaries, missing files, database edge cases, and network errors. |

### Targeted Test Execution

Run a specific test file:
```bash
pytest tests/test_db_repository.py -v
```

Run tests matching a keyword or function name:
```bash
pytest -k "nerd_font" -v
```

---

## 3. Visual Testing Harness & UI Driver

The visual testing harness is located in [`tests/visual/`](file:///home/alex/Develop/metaglyph/tests/visual), completely isolated from the runtime application package. It provides programmatic UI driving, headless screenshot generation, pixel diff comparison, and visual test galleries.

### Key Components

* **`UIDriver` ([`tests/visual/driver.py`](file:///home/alex/Develop/metaglyph/tests/visual/driver.py))**: High-level semantic actions for controlling the UI (navigating pages, typing queries, toggling filter chips, adjusting sliders, selecting Nerd Font variants, interacting with the system registry, and waiting for async UI states).
* **`VisualHarness` ([`tests/visual/harness.py`](file:///home/alex/Develop/metaglyph/tests/visual/harness.py))**: Context manager orchestrating an isolated testing sandbox (mock providers, valid synthesized TrueType font binaries with renderable glyph outlines, pre-seeded SQLite database, and configurable viewports).
* **`VisualDiff` ([`tests/visual/diff.py`](file:///home/alex/Develop/metaglyph/tests/visual/diff.py))**: Fast, native PySide6 pixel comparator that calculates mismatch percentages and generates 3-panel composite diff images highlighting differences in magenta.
* **`ScenarioRunner` ([`tests/visual/runner.py`](file:///home/alex/Develop/metaglyph/tests/visual/runner.py))**: Programmatic and CLI runner for executing scenarios and compiling HTML/Markdown galleries.

### Running Visual Tests via Pytest
```bash
pytest tests/visual -v
```

### Running the Standalone Visual Scenario Runner CLI
To execute all 15 predefined visual scenarios and generate a visual gallery report:

```bash
python -m tests.visual.runner --output ./visual_reports
```

This generates:
* `./visual_reports/gallery.html` — Interactive visual gallery with embedded screenshots and metrics.
* `./visual_reports/gallery.md` — GitHub-flavored Markdown gallery.
* `./visual_reports/results.json` — Structured test results and timing metrics.
* `./visual_reports/*.png` — High-fidelity full-window screenshots for each scenario.

#### Running a Specific Scenario
```bash
python -m tests.visual.runner --scenario "detail_pane_nerd" --output ./visual_reports
```

#### Comparing Against Baseline Screenshots
To perform automated visual regression testing against a directory of baseline images:

```bash
python -m tests.visual.runner --baseline ./baseline_screenshots --output ./visual_reports --tolerance 0.05
```

If a visual mismatch exceeds the tolerance threshold, the runner generates a composite diff image (`<scenario>_diff.png`) displaying:
`[ Baseline (Expected) | Actual (Current) | Diff Overlay (Highlighted Changes) ]`

---

## 4. Writing New Visual Scenarios & Tests

### Example: Writing a Scenario

To define a new visual scenario, add a `VisualScenario` definition to [`tests/visual/scenarios.py`](file:///home/alex/Develop/metaglyph/tests/visual/scenarios.py):

```python
from tests.visual.driver import UIDriver
from tests.visual.harness import VisualHarness
from tests.visual.scenarios import VisualScenario

async def _scenario_custom_search_filter(harness: VisualHarness, driver: UIDriver) -> None:
    # 1. Ensure clean view state
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
        
    # 2. Navigate and drive actions
    await driver.navigate_to("search")
    await driver.toggle_category_filter("monospace", active=True)
    await driver.search("Fira Code")
    await driver.select_font_card("Fira Code")
    
    # 3. Fine-tune detail inspector
    await driver.set_detail_point_size(32)
    await driver.set_detail_weight("Bold (700)")
    await driver.wait_for_idle(300)

custom_scenario = VisualScenario(
    name="custom_search_filter",
    description="Search view filtered by monospace and Fira Code selected.",
    viewport_size=(1280, 820),
    execute=_scenario_custom_search_filter,
)
```

### Interactive UI Scripting for Prototyping & AI Agents

You can write quick Python scripts during development to iterate on UI components, layouts, or QSS styles and immediately capture/review the visual result:

```python
import asyncio
from tests.visual import VisualHarness

async def inspect_ui():
    async with VisualHarness(viewport_size=(1280, 820)) as harness:
        driver = harness.driver
        
        # Navigate to Discover page
        await driver.navigate_to("discover")
        await driver.click_discover_category("Code")
        
        # Capture screenshot for visual inspection
        img_path = harness.capture_window("discover_to_code.png")
        print("Captured screenshot at:", img_path)

if __name__ == "__main__":
    asyncio.run(inspect_ui())
```

---

## 5. UI Driver API Reference

The `UIDriver` instance (`harness.driver`) provides the following methods:

### Navigation & View Switching
* `await driver.navigate_to("discover" | "search" | "system")`: Switch views via the sidebar.
* `driver.get_active_page_index()`: Returns the integer index of the active view.

### Search & Browse View
* `await driver.search(query, debounce_wait=True)`: Enter a search query.
* `await driver.clear_search()`: Clear the active search text.
* `await driver.reset_search_filters()`: Reset all category and provider chips to "All".
* `await driver.toggle_provider_filter("google" | "fontsource" | "nerd_fonts", active=True)`: Toggle provider.
* `await driver.toggle_category_filter("sans-serif" | "serif" | "monospace" | "display" | "handwriting", active=True)`: Toggle structural category.
* `await driver.toggle_variable_filter(active=True)`: Toggle variable fonts only checkbox.
* `await driver.toggle_nerd_filter(active=True)`: Toggle Nerd Fonts only checkbox.
* `await driver.select_font_card(font_name_or_id)`: Select a font card to open the detail inspector.

### Detail Inspector Pane
* `driver.is_detail_pane_visible()`: Check if the inspector drawer is open.
* `await driver.close_detail_pane()`: Close the inspector drawer.
* `await driver.set_detail_point_size(pt)`: Set point size slider (10–72 pt).
* `await driver.set_detail_weight("Regular (400)" | "Bold (700)" | "Black (900)")`: Select weight from dropdown.
* `await driver.toggle_detail_italic(True | False)`: Toggle italic preview.
* `await driver.set_detail_preset_sample("Programming Ligatures" | "Quick Brown Fox")`: Select sample text preset.
* `await driver.set_detail_sample_text("Custom Text")`: Set custom sample string.
* `await driver.set_install_scope("User" | "System")`: Choose installation target.
* `await driver.switch_nerd_font_variant("Standard" | "Mono" | "Propo")`: Switch to Nerd Font counterpart.
* `await driver.click_detail_install()`: Trigger installation.
* `await driver.click_detail_uninstall()`: Trigger uninstallation.

### System View
* `await driver.search_system_fonts(query)`: Filter system fonts.
* `await driver.filter_system_scope("All" | "User" | "System")`: Filter system font scope.
* `await driver.toggle_system_font_selection(family_name, selected=True)`: Check/uncheck font checkbox.
* `await driver.select_all_system_fonts(selected=True)`: Select/deselect all fonts.
* `await driver.expand_system_font_details(family_name)`: Expand font metadata drawer.
* `await driver.click_batch_uninstall()`: Trigger batch uninstallation.

### Event Loop & Synchronization
* `await driver.wait_for_idle(ms=250)`: Pump Qt events and wait for async tasks.
* `await driver.wait_until(condition_callable, timeout_ms=3000)`: Wait for state condition.
* `driver.pump_events(iterations=5)`: Synchronously process pending Qt events.

---

## 6. Guidelines for Contributors

1. **Keep UI Thread Non-Blocking:** All disk I/O, network requests, SQLite queries, and font subsetting operations must run asynchronously or in background workers. Use `test_concurrency_stress.py` to verify responsiveness.
2. **Visual Consistency:** When modifying themes or layout geometry, run `python -m tests.visual.runner` and inspect the generated screenshots in `./visual_reports/gallery.html` to ensure no visual regressions across compact (`960x600`) and standard (`1280x820`) viewports.
3. **Commit Messages:** All commits must follow subject-only Conventional Commits (`feat: ...`, `fix: ...`, `docs: ...`, `test: ...`, `refactor: ...`). Do not use multiline commit bodies.
