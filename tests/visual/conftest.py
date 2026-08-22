"""Pytest fixtures for visual testing harness."""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator
import pytest
from PySide6.QtWidgets import QApplication

from metaglyph.ui.app import create_application
from .harness import VisualHarness


@pytest.fixture(scope="session", autouse=True)
def qapp_session() -> QApplication:
    """Ensure QApplication is created in offscreen mode for all visual tests."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = create_application()
    return app


@pytest.fixture
async def visual_harness(tmp_path: Path) -> AsyncGenerator[VisualHarness, None]:
    """Provide an initialized, isolated VisualHarness instance."""
    output_dir = tmp_path / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    async with VisualHarness(output_dir=output_dir) as harness:
        yield harness
