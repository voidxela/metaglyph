"""Metaglyph desktop application CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="metaglyph",
        description="Modern cross-platform desktop font browser and installer.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version="%(prog)s 0.1.0",
    )
    parser.add_argument(
        "--sync",
        "-s",
        action="store_true",
        help="Run headless catalog synchronization and exit.",
    )
    return parser.parse_args()


async def run_sync() -> int:
    """Headless catalog synchronization CLI task."""
    from metaglyph.core.config import get_config
    from metaglyph.core.logging import setup_logging
    from metaglyph.db.database import DatabaseManager
    from metaglyph.db.repository import FontRepository
    from metaglyph.providers.manager import ProviderManager

    setup_logging()
    config = get_config()
    config.ensure_directories()

    db_manager = DatabaseManager(config.database_path)
    await db_manager.initialize()
    repository = FontRepository(db_manager)
    manager = ProviderManager()

    print("Starting headless catalog sync across providers...")
    try:
        results = await manager.sync_all(repository)
        for provider, count in results.items():
            print(f"  • {provider}: {count:,} fonts")
        stats = await repository.get_stats()
        print(f"\nCatalog sync complete! Total unique fonts: {stats['total_fonts']:,}")
        return 0
    finally:
        await manager.close()
        await db_manager.close()


def main() -> int:
    """Main application entry point."""
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            import ctypes.util

            libc_name = ctypes.util.find_library("c")
            if libc_name:
                ctypes.CDLL(libc_name).prctl(15, b"metaglyph", 0, 0, 0)
        except Exception:
            pass

    args = parse_args()

    if args.sync:
        return asyncio.run(run_sync())

    from metaglyph.ui.app import run_app

    return run_app()


if __name__ == "__main__":
    sys.exit(main())
