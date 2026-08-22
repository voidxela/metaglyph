"""Predefined visual test scenarios covering Metaglyph views, states, and layouts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable
from .driver import UIDriver
from .harness import VisualHarness


@dataclass
class VisualScenario:
    """Definition of a reproducible visual test scenario."""

    name: str
    description: str
    viewport_size: tuple[int, int]
    execute: Callable[[VisualHarness, UIDriver], Awaitable[None]]


# ============================================================================
# Scenario Execution Functions
# ============================================================================


async def _scenario_discover_default(harness: VisualHarness, driver: UIDriver) -> None:
    """Discover view default state with category cards and sidebar metrics."""
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("discover")
    await driver.wait_for_idle(200)


async def _scenario_search_default(harness: VisualHarness, driver: UIDriver) -> None:
    """Search & browse view default catalog list."""
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.wait_for_idle(300)


async def _scenario_search_query_filtered(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view filtered by query 'JetBrains'."""
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.search("JetBrains")
    await driver.wait_for_idle(250)


async def _scenario_search_category_code(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view filtered by Monospace category chip."""
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.toggle_category_filter("monospace", active=True)
    await driver.wait_for_idle(250)


async def _scenario_search_provider_fontsource(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view filtered by Fontsource provider chip."""
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.toggle_category_filter("monospace", active=False)
    await driver.toggle_provider_filter("fontsource", active=True)
    await driver.wait_for_idle(250)


async def _scenario_search_empty_state(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view empty state ('No Fonts Found')."""
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.reset_search_filters()
    await driver.search("NonExistentFontXYZ999")
    await driver.wait_for_idle(250)


async def _scenario_detail_pane_standard(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane open for 'Inter' font with live preview and scope selector."""
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("Inter")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_nerd_suggestion(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane for 'JetBrains Mono' showing Nerd Font suggestion banner & variant picker."""
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("JetBrains Mono")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_weight_tuning(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane with 'Black (900)' weight and programming ligatures sample preset."""
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("Fira Code")
    await driver.set_detail_point_size(28)
    await driver.set_detail_weight("Black (900)")
    await driver.set_detail_preset_sample("Programming Ligatures")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_installed_state(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane for an already-installed font displaying uninstall action."""
    await driver.navigate_to("search")
    await driver.clear_search()
    # Inter was seeded as installed in VisualHarness
    await driver.select_font_card("Inter")
    await driver.wait_for_idle(300)


async def _scenario_system_view_default(harness: VisualHarness, driver: UIDriver) -> None:
    """System registry view listing user and system installed fonts with badges."""
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("system")
    await driver.wait_for_idle(300)


async def _scenario_system_view_batch_selection(harness: VisualHarness, driver: UIDriver) -> None:
    """System view with multiple fonts checked, activating batch actions."""
    await driver.navigate_to("system")
    await driver.toggle_system_font_selection("Inter", selected=True)
    await driver.toggle_system_font_selection("DejaVu Sans", selected=True)
    await driver.wait_for_idle(200)


async def _scenario_system_view_expanded_details(harness: VisualHarness, driver: UIDriver) -> None:
    """System view font card with expanded metadata inspector drawer."""
    await driver.navigate_to("system")
    await driver.expand_system_font_details("Inter")
    await driver.wait_for_idle(200)


async def _scenario_responsive_compact_960x600(harness: VisualHarness, driver: UIDriver) -> None:
    """Full application layout rendered at minimum supported resolution (960x600)."""
    harness.resize_viewport(960, 600)
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("Inter")
    await driver.wait_for_idle(300)


async def _scenario_responsive_standard_1280x820(harness: VisualHarness, driver: UIDriver) -> None:
    """Full application layout rendered at standard resolution (1280x820)."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("discover")
    await driver.wait_for_idle(300)


# ============================================================================
# Predefined Scenarios Catalog
# ============================================================================

PREDEFINED_SCENARIOS: list[VisualScenario] = [
    VisualScenario(
        name="01_discover_view_default",
        description="Discover view with curated category cards and sidebar catalog metrics.",
        viewport_size=(1280, 820),
        execute=_scenario_discover_default,
    ),
    VisualScenario(
        name="02_search_view_default",
        description="Search & Browse view populated with font cards and live micro-subset previews.",
        viewport_size=(1280, 820),
        execute=_scenario_search_default,
    ),
    VisualScenario(
        name="03_search_query_filtered",
        description="Search catalog filtered by family query 'JetBrains'.",
        viewport_size=(1280, 820),
        execute=_scenario_search_query_filtered,
    ),
    VisualScenario(
        name="04_search_category_code",
        description="Search catalog filtered by Monospace / Code structural category chip.",
        viewport_size=(1280, 820),
        execute=_scenario_search_category_code,
    ),
    VisualScenario(
        name="05_search_provider_fontsource",
        description="Search catalog filtered by Fontsource provider chip.",
        viewport_size=(1280, 820),
        execute=_scenario_search_provider_fontsource,
    ),
    VisualScenario(
        name="06_search_empty_state",
        description="Search view empty state when no matching fonts are found.",
        viewport_size=(1280, 820),
        execute=_scenario_search_empty_state,
    ),
    VisualScenario(
        name="07_detail_pane_standard",
        description="Detail inspector open for standard font (Inter) with controls and scope selector.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_standard,
    ),
    VisualScenario(
        name="08_detail_pane_nerd_suggestion",
        description="Detail inspector displaying Nerd Font counterpart suggestion banner & variant picker.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_nerd_suggestion,
    ),
    VisualScenario(
        name="09_detail_pane_weight_tuning",
        description="Detail inspector with heavy weight (Black 900) and programming ligature sample preset.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_weight_tuning,
    ),
    VisualScenario(
        name="10_detail_pane_installed_state",
        description="Detail inspector displaying already-installed font with Uninstall action button.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_installed_state,
    ),
    VisualScenario(
        name="11_system_view_default",
        description="System font registry view listing detected and managed fonts with scope badges.",
        viewport_size=(1280, 820),
        execute=_scenario_system_view_default,
    ),
    VisualScenario(
        name="12_system_view_batch_selection",
        description="System view in multi-selection mode with batch uninstall action bar enabled.",
        viewport_size=(1280, 820),
        execute=_scenario_system_view_batch_selection,
    ),
    VisualScenario(
        name="13_system_view_expanded_details",
        description="System font card with expanded metadata inspector drawer.",
        viewport_size=(1280, 820),
        execute=_scenario_system_view_expanded_details,
    ),
    VisualScenario(
        name="14_responsive_compact_960x600",
        description="Compact layout geometry rendered at minimum supported window size (960x600).",
        viewport_size=(960, 600),
        execute=_scenario_responsive_compact_960x600,
    ),
    VisualScenario(
        name="15_responsive_standard_1280x820",
        description="Standard desktop layout geometry rendered at 1280x820.",
        viewport_size=(1280, 820),
        execute=_scenario_responsive_standard_1280x820,
    ),
]
