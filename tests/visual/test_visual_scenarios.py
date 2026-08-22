"""Automated test suite verifying the visual testing harness, UI driver, diff engine, and scenarios."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from PySide6.QtGui import QColor, QImage

from .diff import VisualDiff
from .driver import UIDriver
from .harness import VisualHarness
from .runner import ScenarioRunner
from .scenarios import PREDEFINED_SCENARIOS, VisualScenario


# ============================================================================
# 1. VisualDiff Engine Tests
# ============================================================================


def test_visual_diff_identical_images(tmp_path: Path) -> None:
    """Verify that comparing identical images produces a 100% match with 0% diff."""
    img1_path = tmp_path / "img1.png"
    img2_path = tmp_path / "img2.png"

    img = QImage(200, 100, QImage.Format.Format_ARGB32)
    img.fill(QColor(30, 41, 59))
    img.save(str(img1_path))
    img.save(str(img2_path))

    diff = VisualDiff()
    result = diff.compare_images(img1_path, img2_path)

    assert result.is_match is True
    assert result.mismatch_percentage == 0.0
    assert result.diff_pixels == 0
    assert result.total_pixels == 20000


def test_visual_diff_mismatch_and_composite(tmp_path: Path) -> None:
    """Verify that different images produce a mismatch and generate a composite diff image."""
    base_path = tmp_path / "base.png"
    actual_path = tmp_path / "actual.png"
    diff_out_path = tmp_path / "diff.png"

    base_img = QImage(100, 100, QImage.Format.Format_ARGB32)
    base_img.fill(QColor(15, 23, 42))
    base_img.save(str(base_path))

    act_img = QImage(100, 100, QImage.Format.Format_ARGB32)
    act_img.fill(QColor(15, 23, 42))
    # Draw a 20x20 distinct square (400 pixels = 4%)
    for y in range(10, 30):
        for x in range(10, 30):
            act_img.setPixelColor(x, y, QColor(255, 255, 255))
    act_img.save(str(actual_path))

    diff = VisualDiff(max_mismatch_percentage=0.05)
    result = diff.compare_images(base_path, actual_path, diff_output_path=diff_out_path)

    assert result.is_match is False
    assert result.diff_pixels == 400
    assert result.total_pixels == 10000
    assert result.mismatch_percentage == 4.0
    assert diff_out_path.exists()
    assert diff_out_path.stat().st_size > 0


def test_visual_diff_dimension_mismatch(tmp_path: Path) -> None:
    """Verify dimension mismatch handling."""
    img1_path = tmp_path / "small.png"
    img2_path = tmp_path / "large.png"

    img1 = QImage(50, 50, QImage.Format.Format_ARGB32)
    img1.save(str(img1_path))

    img2 = QImage(100, 100, QImage.Format.Format_ARGB32)
    img2.save(str(img2_path))

    diff = VisualDiff()
    result = diff.compare_images(img1_path, img2_path)

    assert result.is_match is False
    assert "Dimension mismatch" in (result.error_message or "")


# ============================================================================
# 2. Visual Scenarios & UI Driver Execution Tests
# ============================================================================


@pytest.mark.asyncio
async def test_all_predefined_visual_scenarios(visual_harness: VisualHarness) -> None:
    """Execute each predefined visual scenario and verify valid screenshot generation."""
    driver = visual_harness.driver
    assert driver is not None

    for scenario in PREDEFINED_SCENARIOS:
        visual_harness.resize_viewport(scenario.viewport_size[0], scenario.viewport_size[1])
        await scenario.execute(visual_harness, driver)

        snapshot = visual_harness.capture_snapshot(scenario.name, scenario.description)
        assert snapshot.image_path.exists(), f"Screenshot not created for scenario: {scenario.name}"
        assert snapshot.image_path.stat().st_size > 1000, f"Screenshot file is abnormally small for: {scenario.name}"

        # Verify image dimensions
        img = QImage(str(snapshot.image_path))
        assert not img.isNull()
        assert img.width() == scenario.viewport_size[0]
        assert img.height() == scenario.viewport_size[1]


@pytest.mark.asyncio
async def test_ui_driver_detail_pane_workflow(visual_harness: VisualHarness) -> None:
    """Verify UI driver fine-tuning operations on the Detail Pane."""
    driver = visual_harness.driver
    assert driver is not None

    await driver.navigate_to("search")
    assert driver.get_active_page_index() == 1

    # Select JetBrains Mono
    selected = await driver.select_font_card("JetBrains Mono")
    assert selected is True
    assert driver.is_detail_pane_visible() is True

    # Adjust controls
    await driver.set_detail_point_size(32)
    assert visual_harness.window.detail_pane._size_slider.value() == 32

    await driver.set_detail_weight("Bold (700)")
    assert visual_harness.window.detail_pane._weight_combo.currentText() == "Bold (700)"

    await driver.toggle_detail_italic(True)
    assert visual_harness.window.detail_pane._italic_check.isChecked() is True

    await driver.set_install_scope("System")
    assert visual_harness.window.detail_pane._radio_system.isChecked() is True

    # Close detail pane
    await driver.close_detail_pane()
    assert driver.is_detail_pane_visible() is False


@pytest.mark.asyncio
async def test_ui_driver_system_view_operations(visual_harness: VisualHarness) -> None:
    """Verify UI driver operations on System registry view."""
    driver = visual_harness.driver
    assert driver is not None

    await driver.navigate_to("system")
    assert driver.get_active_page_index() == 2

    # Toggle selection for Inter
    toggled = await driver.toggle_system_font_selection("Inter", selected=True)
    assert toggled is True

    # Expand details
    expanded = await driver.expand_system_font_details("Inter")
    assert expanded is True

    # Scope filter
    await driver.filter_system_scope("user")
    cards = driver.get_system_font_cards()
    assert len(cards) > 0


# ============================================================================
# 3. ScenarioRunner & Gallery Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_runner_reports_and_galleries(tmp_path: Path) -> None:
    """Verify that ScenarioRunner executes and writes Markdown, HTML, and JSON reports."""
    report_dir = tmp_path / "visual_reports"
    runner = ScenarioRunner(output_dir=report_dir)

    # Run a subset of scenarios for fast runner test
    test_scenarios = PREDEFINED_SCENARIOS[:3]
    reports = await runner.run_all(test_scenarios)

    assert len(reports) == 3
    assert all(r.status == "PASSED" for r in reports)

    # Check generated files
    md_file = report_dir / "gallery.md"
    html_file = report_dir / "gallery.html"
    json_file = report_dir / "results.json"

    assert md_file.exists()
    assert html_file.exists()
    assert json_file.exists()

    # Validate JSON content
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["total"] == 3
    assert data["passed"] == 3
    assert len(data["reports"]) == 3
