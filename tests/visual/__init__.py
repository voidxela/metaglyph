"""Metaglyph visual testing harness, UI driver, diff engine, and scenario runner."""

from .diff import DiffResult, VisualDiff
from .driver import UIDriver
from .harness import VisualHarness, VisualSnapshot
from .runner import ScenarioReport, ScenarioRunner
from .scenarios import PREDEFINED_SCENARIOS, VisualScenario

__all__ = [
    "DiffResult",
    "PREDEFINED_SCENARIOS",
    "ScenarioReport",
    "ScenarioRunner",
    "UIDriver",
    "VisualDiff",
    "VisualHarness",
    "VisualScenario",
    "VisualSnapshot",
]
