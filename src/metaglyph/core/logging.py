"""Structured logging configuration for Metaglyph."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import TextIO

from metaglyph.core.config import get_config

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_is_configured = False


def setup_logging(
    level: int = logging.INFO,
    log_to_file: bool = True,
    stream: TextIO | None = None,
    force: bool = False,
) -> None:
    """Configure application logging handlers."""
    global _is_configured
    if _is_configured and not force:
        return

    root_logger = logging.getLogger("metaglyph")
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console Handler
    console_handler = logging.StreamHandler(stream or sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    # File Handler with rotation (max 5MB, 3 backups)
    if log_to_file:
        try:
            config = get_config()
            root_logger.info("Ensuring log cache directory exists: %s", config.cache_dir)
            config.cache_dir.mkdir(parents=True, exist_ok=True)
            log_file = config.cache_dir / "metaglyph.log"
            root_logger.info("Configuring application file log: %s", log_file)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            root_logger.addHandler(file_handler)
        except Exception as exc:
            console_handler.setLevel(logging.DEBUG)
            root_logger.warning("Failed to initialize file logger: %s", exc)

    _is_configured = True


def get_logger(name: str) -> logging.Logger:
    """Retrieve a namespaced logger under the metaglyph root."""
    if not name.startswith("metaglyph"):
        name = f"metaglyph.{name}"
    return logging.getLogger(name)

