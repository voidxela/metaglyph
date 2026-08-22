"""Predefined visual test scenarios covering Metaglyph views, states, and layouts across multiple viewports."""

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
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("discover")
    await driver.wait_for_idle(250)


async def _scenario_discover_compact(harness: VisualHarness, driver: UIDriver) -> None:
    """Discover view at minimum supported viewport (960x600)."""
    harness.resize_viewport(960, 600)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("discover")
    await driver.wait_for_idle(250)


async def _scenario_discover_fhd(harness: VisualHarness, driver: UIDriver) -> None:
    """Discover view at Full HD desktop viewport (1920x1080)."""
    harness.resize_viewport(1920, 1080)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("discover")
    await driver.wait_for_idle(250)


async def _scenario_search_default(harness: VisualHarness, driver: UIDriver) -> None:
    """Search & browse view default catalog list."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.reset_search_filters()
    await driver.clear_search()
    await driver.wait_for_idle(300)


async def _scenario_search_query_filtered(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view filtered by query 'JetBrains'."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.search("JetBrains")
    await driver.wait_for_idle(250)


async def _scenario_search_category_code(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view filtered by Monospace category chip."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.toggle_category_filter("monospace", active=True)
    await driver.wait_for_idle(250)


async def _scenario_search_provider_fontsource(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view filtered by Fontsource provider chip."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.toggle_category_filter("monospace", active=False)
    await driver.toggle_provider_filter("fontsource", active=True)
    await driver.wait_for_idle(250)


async def _scenario_search_features_filtered(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view with variable and nerd font feature filters active."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.reset_search_filters()
    await driver.toggle_variable_filter(active=True)
    await driver.toggle_nerd_filter(active=True)
    await driver.wait_for_idle(250)


async def _scenario_search_empty_state(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view empty state ('No Fonts Found')."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.reset_search_filters()
    await driver.search("NonExistentFontXYZ999")
    await driver.wait_for_idle(250)


async def _scenario_search_compact(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view at compact 960x600 resolution with unclipped 2-row filter bar."""
    harness.resize_viewport(960, 600)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.reset_search_filters()
    await driver.clear_search()
    await driver.wait_for_idle(300)


async def _scenario_search_fhd(harness: VisualHarness, driver: UIDriver) -> None:
    """Search view at 1920x1080 resolution."""
    harness.resize_viewport(1920, 1080)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("search")
    await driver.reset_search_filters()
    await driver.clear_search()
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_standard(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane open for 'Inter' font with live preview and scope selector."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("Inter")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_nerd_suggestion(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane for 'JetBrains Mono' showing Nerd Font suggestion banner & variant picker."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("JetBrains Mono")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_nerd_patched_font(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane viewing a Nerd Font patched font showing 'View Original Font' option."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("FiraCode Nerd Font")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_weight_tuning(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane with 'Black (900)' weight and programming ligatures sample preset."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("Fira Code")
    await driver.set_detail_point_size(28)
    await driver.set_detail_weight("Black (900)")
    await driver.set_detail_preset_sample("Programming Ligatures")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_installed_state(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail pane for an already-installed font displaying uninstall action."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("Inter")
    await driver.wait_for_idle(300)


async def _scenario_detail_pane_compact_960x600(harness: VisualHarness, driver: UIDriver) -> None:
    """Detail inspector open on compact window (960x600) with clean vertical scrolling."""
    harness.resize_viewport(960, 600)
    await driver.navigate_to("search")
    await driver.clear_search()
    await driver.select_font_card("Inter")
    await driver.wait_for_idle(300)


async def _scenario_system_view_default(harness: VisualHarness, driver: UIDriver) -> None:
    """System registry view listing user and system installed fonts with badges."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("system")
    await driver.wait_for_idle(300)


async def _scenario_system_view_scope_filter(harness: VisualHarness, driver: UIDriver) -> None:
    """System view filtered to User Scope installed fonts."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("system")
    await driver.filter_system_scope("User")
    await driver.wait_for_idle(250)


async def _scenario_system_view_batch_selection(harness: VisualHarness, driver: UIDriver) -> None:
    """System view with multiple fonts checked, activating batch actions."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("system")
    await driver.filter_system_scope("All")
    await driver.toggle_system_font_selection("Inter", selected=True)
    await driver.toggle_system_font_selection("DejaVu Sans", selected=True)
    await driver.wait_for_idle(200)


async def _scenario_system_view_expanded_details(harness: VisualHarness, driver: UIDriver) -> None:
    """System view font card with expanded metadata inspector drawer."""
    harness.resize_viewport(1280, 820)
    await driver.navigate_to("system")
    await driver.expand_system_font_details("Inter")
    await driver.wait_for_idle(200)


async def _scenario_system_view_compact(harness: VisualHarness, driver: UIDriver) -> None:
    """System view at compact 960x600 resolution."""
    harness.resize_viewport(960, 600)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("system")
    await driver.wait_for_idle(300)


async def _scenario_system_view_fhd(harness: VisualHarness, driver: UIDriver) -> None:
    """System view at 1920x1080 resolution."""
    harness.resize_viewport(1920, 1080)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("system")
    await driver.wait_for_idle(300)


async def _scenario_workflow_discover_to_search(harness: VisualHarness, driver: UIDriver) -> None:
    """Workflow: clicking Code curated category on Discover navigates to pre-filtered Search view."""
    harness.resize_viewport(1280, 820)
    if driver.is_detail_pane_visible():
        await driver.close_detail_pane()
    await driver.navigate_to("discover")
    await driver.wait_for_idle(200)
    await driver.click_discover_category("Code")
    await driver.wait_for_idle(300)


# ============================================================================
# Predefined Scenarios Catalog
# ============================================================================

PREDEFINED_SCENARIOS: list[VisualScenario] = [
    VisualScenario(
        name="01_discover_view_default",
        description="Discover view with curated category cards and sidebar catalog metrics (1280x820).",
        viewport_size=(1280, 820),
        execute=_scenario_discover_default,
    ),
    VisualScenario(
        name="02_discover_view_compact_960x600",
        description="Discover view rendered at minimum supported resolution (960x600).",
        viewport_size=(960, 600),
        execute=_scenario_discover_compact,
    ),
    VisualScenario(
        name="03_discover_view_fhd_1920x1080",
        description="Discover view rendered at Full HD desktop resolution (1920x1080).",
        viewport_size=(1920, 1080),
        execute=_scenario_discover_fhd,
    ),
    VisualScenario(
        name="04_search_view_default",
        description="Search & Browse view with 2-row filter bar and live typography preview cards.",
        viewport_size=(1280, 820),
        execute=_scenario_search_default,
    ),
    VisualScenario(
        name="05_search_query_filtered",
        description="Search catalog filtered by family query 'JetBrains'.",
        viewport_size=(1280, 820),
        execute=_scenario_search_query_filtered,
    ),
    VisualScenario(
        name="06_search_category_code",
        description="Search catalog filtered by Monospace / Code category chip.",
        viewport_size=(1280, 820),
        execute=_scenario_search_category_code,
    ),
    VisualScenario(
        name="07_search_provider_fontsource",
        description="Search catalog filtered by Fontsource provider chip.",
        viewport_size=(1280, 820),
        execute=_scenario_search_provider_fontsource,
    ),
    VisualScenario(
        name="08_search_features_filtered",
        description="Search catalog with Variable and Nerd Font checkboxes enabled.",
        viewport_size=(1280, 820),
        execute=_scenario_search_features_filtered,
    ),
    VisualScenario(
        name="09_search_empty_state",
        description="Search view empty state when no matching fonts are found.",
        viewport_size=(1280, 820),
        execute=_scenario_search_empty_state,
    ),
    VisualScenario(
        name="10_search_view_compact_960x600",
        description="Search view rendered at minimum supported window size (960x600) with unclipped filter chips.",
        viewport_size=(960, 600),
        execute=_scenario_search_compact,
    ),
    VisualScenario(
        name="11_search_view_fhd_1920x1080",
        description="Search view rendered at Full HD desktop resolution (1920x1080).",
        viewport_size=(1920, 1080),
        execute=_scenario_search_fhd,
    ),
    VisualScenario(
        name="12_detail_pane_standard",
        description="Detail inspector open for standard font (Inter) with controls and scope selector.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_standard,
    ),
    VisualScenario(
        name="13_detail_pane_nerd_suggestion",
        description="Detail inspector displaying Nerd Font counterpart suggestion banner & variant picker.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_nerd_suggestion,
    ),
    VisualScenario(
        name="14_detail_pane_nerd_patched_font",
        description="Detail inspector for a Nerd Font patched font showing 'View Original Font' banner.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_nerd_patched_font,
    ),
    VisualScenario(
        name="15_detail_pane_weight_tuning",
        description="Detail inspector with heavy weight (Black 900) and programming ligature sample preset.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_weight_tuning,
    ),
    VisualScenario(
        name="16_detail_pane_installed_state",
        description="Detail inspector displaying already-installed font with Uninstall action button.",
        viewport_size=(1280, 820),
        execute=_scenario_detail_pane_installed_state,
    ),
    VisualScenario(
        name="17_detail_pane_compact_960x600",
        description="Detail inspector drawer open in compact window (960x600) without horizontal clipping.",
        viewport_size=(960, 600),
        execute=_scenario_detail_pane_compact_960x600,
    ),
    VisualScenario(
        name="18_system_view_default",
        description="Installed fonts view with family groups, variants, and scope badges.",
        viewport_size=(1280, 820),
        execute=_scenario_system_view_default,
    ),
    VisualScenario(
        name="19_system_view_scope_filter",
        description="Installed fonts view filtered by User Scope.",
        viewport_size=(1280, 820),
        execute=_scenario_system_view_scope_filter,
    ),
    VisualScenario(
        name="20_system_view_batch_selection",
        description="Installed fonts view in multi-selection mode with batch uninstall action bar enabled.",
        viewport_size=(1280, 820),
        execute=_scenario_system_view_batch_selection,
    ),
    VisualScenario(
        name="21_system_view_expanded_details",
        description="Installed fonts view with expanded metadata inspector drawer on font row selection.",
        viewport_size=(1280, 820),
        execute=_scenario_system_view_expanded_details,
    ),
    VisualScenario(
        name="22_system_view_compact_960x600",
        description="Installed fonts view at compact resolution (960x600).",
        viewport_size=(960, 600),
        execute=_scenario_system_view_compact,
    ),
    VisualScenario(
        name="23_system_view_fhd_1920x1080",
        description="Installed fonts view at Full HD desktop resolution (1920x1080).",
        viewport_size=(1920, 1080),
        execute=_scenario_system_view_fhd,
    ),
    VisualScenario(
        name="24_workflow_discover_to_search",
        description="End-to-end workflow: Discover category card click navigating to filtered Search view.",
        viewport_size=(1280, 820),
        execute=_scenario_workflow_discover_to_search,
    ),
]
