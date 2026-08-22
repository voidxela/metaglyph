"""Catalog query, filtering, deduplication, and installation state repository."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from metaglyph.core.logging import get_logger
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import (
    Font,
    FontFilter,
    FontVariant,
    InstalledFont,
    SystemFontCacheEntry,
)
from metaglyph.db.normalizer import (
    curate_category,
    extract_nerd_font_counterpart,
    is_nerd_font,
    normalize_family_name,
    should_replace_primary_provider,
)

logger = get_logger("db.repository")


class FontRepository:
    """Async repository for catalog queries, deduplication, and installation records."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    async def upsert_font(self, font: Font) -> None:
        """Upsert a single font family and its variants with priority merging."""
        await self.upsert_fonts([font])

    async def upsert_fonts(self, fonts: list[Font]) -> None:
        """Batch upsert font families and variants with priority merging."""
        if not fonts:
            return

        async with self._db.connection() as conn:
            for font in fonts:
                # Ensure curated category is set
                curated = font.curated_category or curate_category(font.category, font.family_name)

                # Check for existing record
                cursor = await conn.execute(
                    "SELECT primary_provider, is_variable, has_nerd_font, nerd_font_slug FROM fonts WHERE id = ?",
                    (font.id,),
                )
                existing = await cursor.fetchone()

                if existing is None:
                    # New font insertion
                    await conn.execute(
                        """
                        INSERT INTO fonts (
                            id, family_name, category, curated_category,
                            is_variable, has_nerd_font, nerd_font_slug,
                            primary_provider, last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            font.id,
                            font.family_name,
                            font.category,
                            curated,
                            1 if font.is_variable else 0,
                            1 if font.has_nerd_font else 0,
                            font.nerd_font_slug,
                            font.primary_provider,
                            font.last_synced_at,
                        ),
                    )
                else:
                    existing_provider = existing["primary_provider"]
                    is_var = bool(existing["is_variable"] or font.is_variable)
                    has_nf = bool(existing["has_nerd_font"] or font.has_nerd_font)
                    nf_slug = font.nerd_font_slug or existing["nerd_font_slug"]

                    if should_replace_primary_provider(existing_provider, font.primary_provider):
                        # New provider has higher priority
                        await conn.execute(
                            """
                            UPDATE fonts SET
                                family_name = ?,
                                category = ?,
                                curated_category = ?,
                                is_variable = ?,
                                has_nerd_font = ?,
                                nerd_font_slug = ?,
                                primary_provider = ?,
                                last_synced_at = ?
                            WHERE id = ?
                            """,
                            (
                                font.family_name,
                                font.category,
                                curated,
                                1 if is_var else 0,
                                1 if has_nf else 0,
                                nf_slug,
                                font.primary_provider,
                                font.last_synced_at,
                                font.id,
                            ),
                        )
                    else:
                        # Existing provider retained
                        await conn.execute(
                            """
                            UPDATE fonts SET
                                is_variable = ?,
                                has_nerd_font = ?,
                                nerd_font_slug = ?,
                                last_synced_at = ?
                            WHERE id = ?
                            """,
                            (
                                1 if is_var else 0,
                                1 if has_nf else 0,
                                nf_slug,
                                font.last_synced_at,
                                font.id,
                            ),
                        )

                # Upsert variants
                if font.variants:
                    for v in font.variants:
                        await conn.execute(
                            """
                            INSERT INTO font_variants (
                                font_id, provider, style, weight,
                                file_format, download_url, subset_url, filesize
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(font_id, provider, style, weight) DO UPDATE SET
                                file_format = excluded.file_format,
                                download_url = excluded.download_url,
                                subset_url = excluded.subset_url,
                                filesize = excluded.filesize
                            """,
                            (
                                font.id,
                                v.provider,
                                v.style,
                                v.weight,
                                v.file_format,
                                v.download_url,
                                v.subset_url,
                                v.filesize,
                            ),
                        )

            await conn.commit()

    async def add_variants(self, variants: list[FontVariant]) -> None:
        """Batch insert or update font variants."""
        if not variants:
            return

        async with self._db.connection() as conn:
            for v in variants:
                await conn.execute(
                    """
                    INSERT INTO font_variants (
                        font_id, provider, style, weight,
                        file_format, download_url, subset_url, filesize
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(font_id, provider, style, weight) DO UPDATE SET
                        file_format = excluded.file_format,
                        download_url = excluded.download_url,
                        subset_url = excluded.subset_url,
                        filesize = excluded.filesize
                    """,
                    (
                        v.font_id,
                        v.provider,
                        v.style,
                        v.weight,
                        v.file_format,
                        v.download_url,
                        v.subset_url,
                        v.filesize,
                    ),
                )
            await conn.commit()

    async def get_font(self, font_id: str) -> Font | None:
        """Retrieve font family and all associated variants by ID (alias for get_font_by_id)."""
        return await self.get_font_by_id(font_id)

    async def get_font_by_id(self, font_id: str) -> Font | None:
        """Retrieve font family and all associated variants by ID."""
        async with self._db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM fonts WHERE id = ?",
                (font_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None

            variants_cursor = await conn.execute(
                """
                SELECT * FROM font_variants
                WHERE font_id = ?
                ORDER BY weight ASC, style ASC
                """,
                (font_id,),
            )
            variant_rows = await variants_cursor.fetchall()
            variants = [
                FontVariant(
                    id=v["id"],
                    font_id=v["font_id"],
                    provider=v["provider"],
                    style=v["style"],
                    weight=v["weight"],
                    file_format=v["file_format"],
                    download_url=v["download_url"],
                    subset_url=v["subset_url"],
                    filesize=v["filesize"] or 0,
                )
                for v in variant_rows
            ]

            return Font(
                id=row["id"],
                family_name=row["family_name"],
                category=row["category"],
                curated_category=row["curated_category"],
                is_variable=bool(row["is_variable"]),
                has_nerd_font=bool(row["has_nerd_font"]),
                nerd_font_slug=row["nerd_font_slug"],
                primary_provider=row["primary_provider"],
                last_synced_at=row["last_synced_at"],
                variants=variants,
            )

    async def get_font_by_slug_or_family(self, identifier: str) -> Font | None:
        """Retrieve font by slug ID or family name (case-insensitive)."""
        slug = normalize_family_name(identifier)
        font = await self.get_font_by_id(slug)
        if font is not None:
            return font

        async with self._db.connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM fonts WHERE LOWER(family_name) = LOWER(?) LIMIT 1",
                (identifier,),
            )
            row = await cursor.fetchone()
            if row:
                return await self.get_font_by_id(row["id"])
        return None

    async def search_fonts(self, filter_params: FontFilter) -> tuple[list[Font], int]:
        """Search and filter fonts returning paginated results and total match count."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if filter_params.query:
            clean_q = f"%{filter_params.query.strip().lower()}%"
            where_clauses.append("(LOWER(id) LIKE ? OR LOWER(family_name) LIKE ?)")
            params.extend([clean_q, clean_q])

        if filter_params.categories:
            placeholders = ",".join("?" for _ in filter_params.categories)
            where_clauses.append(f"category IN ({placeholders})")
            params.extend(filter_params.categories)

        if filter_params.curated_categories:
            placeholders = ",".join("?" for _ in filter_params.curated_categories)
            where_clauses.append(f"curated_category IN ({placeholders})")
            params.extend(filter_params.curated_categories)

        if filter_params.providers:
            placeholders = ",".join("?" for _ in filter_params.providers)
            where_clauses.append(f"primary_provider IN ({placeholders})")
            params.extend(filter_params.providers)

        if filter_params.is_variable is not None:
            where_clauses.append("is_variable = ?")
            params.append(1 if filter_params.is_variable else 0)

        if filter_params.has_nerd_font is not None:
            where_clauses.append("has_nerd_font = ?")
            params.append(1 if filter_params.has_nerd_font else 0)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        async with self._db.connection() as conn:
            # Get total count
            count_cursor = await conn.execute(
                f"SELECT COUNT(*) AS count FROM fonts {where_sql}",
                tuple(params),
            )
            count_row = await count_cursor.fetchone()
            total_count = count_row["count"] if count_row else 0

            # Get paginated fonts
            query_sql = f"""
                SELECT * FROM fonts
                {where_sql}
                ORDER BY family_name ASC
                LIMIT ? OFFSET ?
            """
            paginated_params = list(params) + [filter_params.limit, filter_params.offset]

            cursor = await conn.execute(query_sql, tuple(paginated_params))
            font_rows = await cursor.fetchall()

            if not font_rows:
                return [], total_count

            # Fetch variants for all returned fonts in one query
            font_ids = [row["id"] for row in font_rows]
            placeholders = ",".join("?" for _ in font_ids)
            variants_cursor = await conn.execute(
                f"""
                SELECT * FROM font_variants
                WHERE font_id IN ({placeholders})
                ORDER BY font_id, weight ASC, style ASC
                """,
                tuple(font_ids),
            )
            variant_rows = await variants_cursor.fetchall()

            variants_by_font: dict[str, list[FontVariant]] = {fid: [] for fid in font_ids}
            for v in variant_rows:
                variants_by_font[v["font_id"]].append(
                    FontVariant(
                        id=v["id"],
                        font_id=v["font_id"],
                        provider=v["provider"],
                        style=v["style"],
                        weight=v["weight"],
                        file_format=v["file_format"],
                        download_url=v["download_url"],
                        subset_url=v["subset_url"],
                        filesize=v["filesize"] or 0,
                    )
                )

            fonts = [
                Font(
                    id=row["id"],
                    family_name=row["family_name"],
                    category=row["category"],
                    curated_category=row["curated_category"],
                    is_variable=bool(row["is_variable"]),
                    has_nerd_font=bool(row["has_nerd_font"]),
                    nerd_font_slug=row["nerd_font_slug"],
                    primary_provider=row["primary_provider"],
                    last_synced_at=row["last_synced_at"],
                    variants=variants_by_font.get(row["id"], []),
                )
                for row in font_rows
            ]

            return fonts, total_count

    async def get_curated_category_counts(self) -> dict[str, int]:
        """Return font count by curated category."""
        async with self._db.connection() as conn:
            cursor = await conn.execute(
                "SELECT curated_category, COUNT(*) AS cnt FROM fonts GROUP BY curated_category"
            )
            rows = await cursor.fetchall()
            return {row["curated_category"]: row["cnt"] for row in rows if row["curated_category"]}

    async def record_installation(self, installed: InstalledFont) -> int:
        """Insert or replace an installed font record."""
        async with self._db.connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO installed_fonts (
                    font_id, family_name, provider, version,
                    install_scope, installed_at, file_paths
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    installed.font_id,
                    installed.family_name,
                    installed.provider,
                    installed.version,
                    installed.install_scope,
                    installed.installed_at,
                    installed.file_paths_json(),
                ),
            )
            await conn.commit()
            return cursor.lastrowid or 0

    async def remove_installation(self, font_id: str, scope: str | None = None) -> bool:
        """Remove font installation record."""
        async with self._db.connection() as conn:
            if scope:
                cursor = await conn.execute(
                    "DELETE FROM installed_fonts WHERE font_id = ? AND install_scope = ?",
                    (font_id, scope),
                )
            else:
                cursor = await conn.execute(
                    "DELETE FROM installed_fonts WHERE font_id = ?",
                    (font_id,),
                )
            await conn.commit()
            return cursor.rowcount > 0

    async def get_installed_fonts(self, scope: str | None = None) -> list[InstalledFont]:
        """Retrieve all installed font records."""
        async with self._db.connection() as conn:
            if scope:
                cursor = await conn.execute(
                    "SELECT * FROM installed_fonts WHERE install_scope = ? ORDER BY installed_at DESC",
                    (scope,),
                )
            else:
                cursor = await conn.execute(
                    "SELECT * FROM installed_fonts ORDER BY installed_at DESC"
                )
            rows = await cursor.fetchall()
            return [
                InstalledFont.from_db_row(
                    id=row["id"],
                    font_id=row["font_id"],
                    family_name=row["family_name"],
                    provider=row["provider"],
                    version=row["version"],
                    install_scope=row["install_scope"],
                    installed_at=row["installed_at"],
                    file_paths_str=row["file_paths"],
                )
                for row in rows
            ]

    async def is_font_installed(self, font_id: str) -> bool:
        """Check if a font is currently recorded as installed."""
        async with self._db.connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM installed_fonts WHERE font_id = ? LIMIT 1",
                (font_id,),
            )
            return (await cursor.fetchone()) is not None

    async def sync_system_font_cache(self, entries: list[SystemFontCacheEntry]) -> None:
        """Refresh system font cache entries."""
        async with self._db.connection() as conn:
            # Fetch all installed font paths to identify Metaglyph-managed fonts
            inst_cursor = await conn.execute("SELECT file_paths FROM installed_fonts")
            inst_rows = await inst_cursor.fetchall()
            managed_paths: set[str] = set()
            for row in inst_rows:
                if row["file_paths"]:
                    try:
                        paths = json.loads(row["file_paths"])
                        managed_paths.update(paths)
                    except Exception:
                        pass

            for entry in entries:
                is_managed = 1 if (entry.file_path in managed_paths or entry.is_metaglyph_managed) else 0
                await conn.execute(
                    """
                    INSERT INTO system_font_cache (
                        family_name, postscript_name, file_path,
                        scope, is_metaglyph_managed, last_scanned_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        family_name = excluded.family_name,
                        postscript_name = excluded.postscript_name,
                        scope = excluded.scope,
                        is_metaglyph_managed = excluded.is_metaglyph_managed,
                        last_scanned_at = excluded.last_scanned_at
                    """,
                    (
                        entry.family_name,
                        entry.postscript_name,
                        entry.file_path,
                        entry.scope,
                        is_managed,
                        entry.last_scanned_at,
                    ),
                )
            await conn.commit()

    async def get_system_fonts(
        self, scope: str | None = None, metaglyph_only: bool = False
    ) -> list[SystemFontCacheEntry]:
        """Retrieve system font cache records."""
        async with self._db.connection() as conn:
            clauses: list[str] = []
            params: list[Any] = []

            if scope:
                clauses.append("scope = ?")
                params.append(scope)
            if metaglyph_only:
                clauses.append("is_metaglyph_managed = 1")

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            cursor = await conn.execute(
                f"SELECT * FROM system_font_cache {where_sql} ORDER BY family_name ASC",
                tuple(params),
            )
            rows = await cursor.fetchall()
            return [
                SystemFontCacheEntry(
                    family_name=row["family_name"],
                    postscript_name=row["postscript_name"],
                    file_path=row["file_path"],
                    scope=row["scope"],
                    is_metaglyph_managed=bool(row["is_metaglyph_managed"]),
                    last_scanned_at=row["last_scanned_at"],
                )
                for row in rows
            ]

    async def link_nerd_fonts(self) -> int:
        """Scan catalog and link standard fonts with counterpart Nerd Fonts."""
        linked_count = 0
        async with self._db.connection() as conn:
            # Find all fonts marked as nerd_fonts or with nerd font names
            cursor = await conn.execute(
                "SELECT id, family_name FROM fonts WHERE primary_provider = 'nerd_fonts' OR has_nerd_font = 1"
            )
            nf_rows = await cursor.fetchall()

            for row in nf_rows:
                nf_slug = row["id"]
                base_slug, _ = extract_nerd_font_counterpart(row["family_name"])

                if base_slug != nf_slug:
                    # Update base font to point to this nerd font slug
                    update_cursor = await conn.execute(
                        """
                        UPDATE fonts SET
                            has_nerd_font = 1,
                            nerd_font_slug = ?
                        WHERE id = ? AND id != ?
                        """,
                        (nf_slug, base_slug, nf_slug),
                    )
                    if update_cursor.rowcount > 0:
                        linked_count += update_cursor.rowcount

            await conn.commit()
        return linked_count

    async def get_stats(self) -> dict[str, int]:
        """Return catalog and installation metrics."""
        async with self._db.connection() as conn:
            f_cur = await conn.execute("SELECT COUNT(*) AS c FROM fonts")
            f_cnt = (await f_cur.fetchone())["c"]

            v_cur = await conn.execute("SELECT COUNT(*) AS c FROM font_variants")
            v_cnt = (await v_cur.fetchone())["c"]

            i_cur = await conn.execute("SELECT COUNT(*) AS c FROM installed_fonts")
            i_cnt = (await i_cur.fetchone())["c"]

            return {
                "total_fonts": f_cnt,
                "total_variants": v_cnt,
                "total_installed": i_cnt,
            }
