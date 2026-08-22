"""Unit tests for configuration, logging, and event bus."""

from __future__ import annotations

import logging
from pathlib import Path
import pytest

from metaglyph.core.config import Config, get_config, set_config
from metaglyph.core.events import EventBus, get_event_bus
from metaglyph.core.logging import get_logger, setup_logging


def test_config_paths_and_defaults(tmp_path: Path) -> None:
    """Test default paths and directory overrides."""
    data_dir = tmp_path / "custom_data"
    cache_dir = tmp_path / "custom_cache"
    config_dir = tmp_path / "custom_config"

    cfg = Config(
        data_dir_override=data_dir,
        cache_dir_override=cache_dir,
        config_dir_override=config_dir,
    )

    assert cfg.data_dir == data_dir
    assert cfg.cache_dir == cache_dir
    assert cfg.config_dir == config_dir
    assert cfg.subsets_cache_dir == cache_dir / "subsets"
    assert cfg.downloads_cache_dir == cache_dir / "downloads"
    assert cfg.database_path == data_dir / "metaglyph.db"

    cfg.ensure_directories()
    assert data_dir.exists()
    assert cache_dir.exists()
    assert config_dir.exists()
    assert (cache_dir / "subsets").exists()
    assert (cache_dir / "downloads").exists()


def test_config_provider_priorities() -> None:
    """Verify default provider priority order."""
    cfg = Config()
    # fontsource (1) > google (2) > nerd_fonts (3)
    assert cfg.provider_priorities["fontsource"] < cfg.provider_priorities["google"]
    assert cfg.provider_priorities["google"] < cfg.provider_priorities["nerd_fonts"]


def test_logging_setup(tmp_path: Path) -> None:
    """Test logger initialization and retrieval."""
    cfg = Config(cache_dir_override=tmp_path / "cache")
    set_config(cfg)

    setup_logging(level=logging.DEBUG, log_to_file=True)
    logger = get_logger("test_module")
    assert logger.name == "metaglyph.test_module"
    logger.info("Test log message")


@pytest.mark.asyncio
async def test_event_bus_sync_and_async() -> None:
    """Test event subscription and emission."""
    bus = EventBus()
    events_received: list[str] = []

    def sync_handler(msg: str) -> None:
        events_received.append(f"sync:{msg}")

    async def async_handler(msg: str) -> None:
        events_received.append(f"async:{msg}")

    bus.subscribe("test_event", sync_handler)
    bus.subscribe("test_event", async_handler)

    await bus.emit_async("test_event", msg="hello")
    assert "sync:hello" in events_received
    assert "async:hello" in events_received

    # Unsubscribe
    bus.unsubscribe("test_event", sync_handler)
    events_received.clear()
    await bus.emit_async("test_event", msg="world")
    assert "sync:world" not in events_received
    assert "async:world" in events_received
