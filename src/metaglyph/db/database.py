"""SQLite connection management, initialization, and schema migrations using aiosqlite."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from metaglyph.core.config import get_config
from metaglyph.core.logging import get_logger

logger = get_logger("db.database")

SCHEMA_DDL = """
-- Unified Fonts Table
CREATE TABLE IF NOT EXISTS fonts (
    id TEXT PRIMARY KEY,
    family_name TEXT NOT NULL,
    category TEXT NOT NULL,
    curated_category TEXT,
    is_variable INTEGER NOT NULL DEFAULT 0,
    has_nerd_font INTEGER NOT NULL DEFAULT 0,
    nerd_font_slug TEXT,
    primary_provider TEXT NOT NULL,
    last_synced_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fonts_category ON fonts(category);
CREATE INDEX IF NOT EXISTS idx_fonts_curated_category ON fonts(curated_category);
CREATE INDEX IF NOT EXISTS idx_fonts_primary_provider ON fonts(primary_provider);
CREATE INDEX IF NOT EXISTS idx_fonts_has_nerd_font ON fonts(has_nerd_font);
CREATE INDEX IF NOT EXISTS idx_fonts_family_name ON fonts(family_name);

-- Provider Offerings & Variants
CREATE TABLE IF NOT EXISTS font_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    font_id TEXT NOT NULL REFERENCES fonts(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    style TEXT NOT NULL,
    weight INTEGER NOT NULL,
    file_format TEXT NOT NULL,
    download_url TEXT NOT NULL,
    subset_url TEXT,
    filesize INTEGER DEFAULT 0,
    UNIQUE(font_id, provider, style, weight)
);

CREATE INDEX IF NOT EXISTS idx_font_variants_font_id ON font_variants(font_id);
CREATE INDEX IF NOT EXISTS idx_font_variants_provider ON font_variants(provider);

-- Metaglyph Installation State Tracking
CREATE TABLE IF NOT EXISTS installed_fonts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    font_id TEXT NOT NULL REFERENCES fonts(id),
    family_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    version TEXT,
    install_scope TEXT NOT NULL,
    installed_at INTEGER NOT NULL,
    file_paths TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_installed_fonts_font_id ON installed_fonts(font_id);
CREATE INDEX IF NOT EXISTS idx_installed_fonts_scope ON installed_fonts(install_scope);

-- System Font Index Cache (for System View)
CREATE TABLE IF NOT EXISTS system_font_cache (
    family_name TEXT NOT NULL,
    style_name TEXT DEFAULT 'Regular',
    postscript_name TEXT,
    file_path TEXT NOT NULL PRIMARY KEY,
    scope TEXT NOT NULL,
    is_metaglyph_managed INTEGER NOT NULL DEFAULT 0,
    last_scanned_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_font_cache_scope ON system_font_cache(scope);
CREATE INDEX IF NOT EXISTS idx_system_font_cache_family ON system_font_cache(family_name);
CREATE INDEX IF NOT EXISTS idx_system_font_cache_managed ON system_font_cache(is_metaglyph_managed);
"""


class DatabaseManager:
    """Manages asynchronous SQLite database connections, schema setup, and transactions."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            config = get_config()
            self._db_path = config.database_path
            self._is_memory = False
            self._conn_str = str(self._db_path)
            self._uri = False
        elif db_path == ":memory:":
            self._db_path = ":memory:"
            self._is_memory = True
            # Shared in-memory database so multiple connections see the same tables
            self._conn_str = "file:metaglyph_mem?mode=memory&cache=shared"
            self._uri = True
        else:
            self._db_path = Path(db_path) if isinstance(db_path, str) else db_path
            self._is_memory = False
            self._conn_str = str(self._db_path)
            self._uri = False

        self._is_initialized = False
        self._memory_hold_conn: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> Path | str:
        """Configured database file path or :memory: string."""
        return self._db_path

    async def initialize(self) -> None:
        """Ensure parent directories exist, open database, and apply schema."""
        if isinstance(self._db_path, Path):
            logger.info("Ensuring database parent directory exists: %s", self._db_path.parent)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        if self._is_memory and self._memory_hold_conn is None:
            # Hold a persistent connection to keep shared in-memory database alive
            logger.info("Opening persistent shared in-memory database: %s", self._conn_str)
            self._memory_hold_conn = await aiosqlite.connect(self._conn_str, uri=self._uri)
            await self._memory_hold_conn.execute("PRAGMA foreign_keys = ON;")

        logger.info("Initializing database schema at %s", self._db_path)
        async with self.connection() as conn:
            # Enable Foreign Keys
            await conn.execute("PRAGMA foreign_keys = ON;")
            # Enable WAL mode for high concurrency if file-based
            if not self._is_memory:
                await conn.execute("PRAGMA journal_mode = WAL;")

            await conn.executescript(SCHEMA_DDL)

            # Migration: ensure style_name exists in system_font_cache
            try:
                await conn.execute("ALTER TABLE system_font_cache ADD COLUMN style_name TEXT DEFAULT 'Regular';")
            except Exception as exc:
                if "duplicate column" not in str(exc).lower():
                    logger.warning("Database migration notice for system_font_cache: %s", exc)

            await conn.commit()

        self._is_initialized = True
        logger.info("Database initialized successfully at %s", self._db_path)

    async def close(self) -> None:
        """Close any held in-memory database connection."""
        if self._memory_hold_conn is not None:
            logger.info("Closing held database connection: %s", self._conn_str)
            await self._memory_hold_conn.close()
            self._memory_hold_conn = None

    @contextlib.asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Async context manager yielding an aiosqlite database connection."""
        logger.info("Opening database connection: %s", self._conn_str)
        conn = await aiosqlite.connect(self._conn_str, uri=self._uri)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            await conn.close()

