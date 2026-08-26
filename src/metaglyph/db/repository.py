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
    FEATURED_FONT_NAMES,
    FEATURED_FONT_SLUGS,
    curate_category,
    extract_nerd_font_counterpart,
    is_featured_font,
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

    async def upsert_fonts(self, fonts: list[Font]) -> int:
        """Batch upsert font families and variants with priority merging.

        Returns:
            Count of font families upserted.
        """
        if not fonts:
            return 0

        async with self._db.connection() as conn:
            # Batch fetch existing records
            font_ids = [f.id for f in fonts]
            existing_map: dict[str, Any] = {}
            chunk_size = 500
            for i in range(0, len(font_ids), chunk_size):
                chunk = font_ids[i : i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                cursor = await conn.execute(
                    f"SELECT id, primary_provider, is_variable, has_nerd_font, nerd_font_slug FROM fonts WHERE id IN ({placeholders})",
                    tuple(chunk),
                )
                rows = await cursor.fetchall()
                for row in rows:
                    existing_map[row["id"]] = dict(row)

            insert_font_params = []
            update_replace_params = []
            update_retain_params = []
            variant_params = []

            for font in fonts:
                curated = font.curated_category or curate_category(font.category, font.family_name)
                existing = existing_map.get(font.id)

                if existing is None:
                    insert_font_params.append((
                        font.id,
                        font.family_name,
                        font.category,
                        curated,
                        1 if font.is_variable else 0,
                        1 if font.has_nerd_font else 0,
                        font.nerd_font_slug,
                        font.primary_provider,
                        font.last_synced_at,
                    ))
                    existing_map[font.id] = {
                        "primary_provider": font.primary_provider,
                        "is_variable": 1 if font.is_variable else 0,
                        "has_nerd_font": 1 if font.has_nerd_font else 0,
                        "nerd_font_slug": font.nerd_font_slug,
                    }
                else:
                    existing_provider = existing["primary_provider"]
                    is_var = bool(existing["is_variable"] or font.is_variable)
                    has_nf = bool(existing["has_nerd_font"] or font.has_nerd_font)
                    nf_slug = font.nerd_font_slug or existing["nerd_font_slug"]

                    if should_replace_primary_provider(existing_provider, font.primary_provider):
                        update_replace_params.append((
                            font.family_name,
                            font.category,
                            curated,
                            1 if is_var else 0,
                            1 if has_nf else 0,
                            nf_slug,
                            font.primary_provider,
                            font.last_synced_at,
                            font.id,
                        ))
                        existing_map[font.id] = {
                            "primary_provider": font.primary_provider,
                            "is_variable": 1 if is_var else 0,
                            "has_nerd_font": 1 if has_nf else 0,
                            "nerd_font_slug": nf_slug,
                        }
                    else:
                        update_retain_params.append((
                            1 if is_var else 0,
                            1 if has_nf else 0,
                            nf_slug,
                            font.last_synced_at,
                            font.id,
                        ))
                        existing_map[font.id]["is_variable"] = 1 if is_var else 0
                        existing_map[font.id]["has_nerd_font"] = 1 if has_nf else 0
                        existing_map[font.id]["nerd_font_slug"] = nf_slug

                if font.variants:
                    for v in font.variants:
                        variant_params.append((
                            font.id,
                            v.provider,
                            v.style,
                            v.weight,
                            v.file_format,
                            v.download_url,
                            v.subset_url,
                            v.filesize,
                        ))

            if insert_font_params:
                await conn.executemany(
                    """
                    INSERT INTO fonts (
                        id, family_name, category, curated_category,
                        is_variable, has_nerd_font, nerd_font_slug,
                        primary_provider, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    insert_font_params,
                )

            if update_replace_params:
                await conn.executemany(
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
                    update_replace_params,
                )

            if update_retain_params:
                await conn.executemany(
                    """
                    UPDATE fonts SET
                        is_variable = ?,
                        has_nerd_font = ?,
                        nerd_font_slug = ?,
                        last_synced_at = ?
                    WHERE id = ?
                    """,
                    update_retain_params,
                )

            if variant_params:
                await conn.executemany(
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
                    variant_params,
                )

            await conn.commit()
            return len(fonts)

    async def prune_stale_provider_fonts(self, provider_name: str, valid_font_ids: list[str]) -> int:
        """Remove font records for a provider that no longer exist in its catalog.

        Args:
            provider_name: The provider identifier (e.g., 'fontsquirrel', 'fontsource').
            valid_font_ids: Complete list of font IDs currently in the provider catalog.

        Returns:
            Number of stale font families pruned.
        """
        if not valid_font_ids:
            return 0

        async with self._db.connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM fonts WHERE primary_provider = ?", (provider_name,)
            )
            rows = await cursor.fetchall()
            valid_set = set(valid_font_ids)
            stale_ids = [row["id"] for row in rows if row["id"] not in valid_set]

            if not stale_ids:
                return 0

            logger.info("Pruning %d stale fonts for provider '%s'", len(stale_ids), provider_name)
            for i in range(0, len(stale_ids), 500):
                chunk = stale_ids[i : i + 500]
                placeholders = ",".join("?" * len(chunk))
                await conn.execute(
                    f"DELETE FROM font_variants WHERE font_id IN ({placeholders})", tuple(chunk)
                )
                await conn.execute(
                    f"DELETE FROM fonts WHERE id IN ({placeholders})", tuple(chunk)
                )

            await conn.commit()
            return len(stale_ids)

    async def add_variants(self, variants: list[FontVariant]) -> None:
        """Batch insert or update font variants."""
        if not variants:
            return

        variant_params = [
            (
                v.font_id,
                v.provider,
                v.style,
                v.weight,
                v.file_format,
                v.download_url,
                v.subset_url,
                v.filesize,
            )
            for v in variants
        ]

        async with self._db.connection() as conn:
            await conn.executemany(
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
                variant_params,
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
        """Retrieve font by slug ID, family name, or nerd_font_slug counterpart."""
        slug = normalize_family_name(identifier)
        font = await self.get_font_by_id(slug)
        if font is not None:
            return font

        async with self._db.connection() as conn:
            # 1. Exact or case-insensitive family_name match
            cursor = await conn.execute(
                "SELECT id FROM fonts WHERE LOWER(family_name) = LOWER(?) LIMIT 1",
                (identifier,),
            )
            row = await cursor.fetchone()
            if row:
                return await self.get_font_by_id(row["id"])

            # 2. Check if a font links to this identifier/slug as its counterpart
            cursor = await conn.execute(
                "SELECT id FROM fonts WHERE nerd_font_slug = ? OR nerd_font_slug = ? LIMIT 1",
                (identifier, slug),
            )
            row = await cursor.fetchone()
            if row:
                return await self.get_font_by_id(row["id"])

            # 3. Normalized slug pattern match
            cursor = await conn.execute(
                "SELECT id FROM fonts WHERE id LIKE ? OR REPLACE(LOWER(family_name), ' ', '-') LIKE ? LIMIT 1",
                (f"{slug}%", f"{slug}%"),
            )
            row = await cursor.fetchone()
            if row:
                return await self.get_font_by_id(row["id"])

        return None

    def _build_featured_where_clause(self) -> tuple[str, list[Any]]:
        """Construct SQL WHERE clause and parameters for the Featured curated category."""
        slugs = sorted(FEATURED_FONT_SLUGS)
        names = sorted({n.lower() for n in FEATURED_FONT_NAMES})
        prefix_patterns = [
            "iosevka%",
            "iosevkaterm%",
            "fira-code%",
            "firacode%",
            "meslo%",
            "bitstream-vera%",
            "crimson-text%",
            "crimson-pro%",
            "crimson%",
            "gandhi-serif%",
            "plus-jakarta-sans%",
            "arimo%",
            "barlow-condensed%",
        ]
        name_prefix_patterns = [
            "iosevka%",
            "iosevkaterm%",
            "fira code%",
            "firacode%",
            "meslo%",
            "bitstream vera%",
            "crimson text%",
            "crimson pro%",
            "crimson%",
            "gandhi serif%",
            "plus jakarta sans%",
            "arimo%",
            "barlow condensed%",
        ]

        placeholders_slugs = ",".join("?" for _ in slugs)
        placeholders_names = ",".join("?" for _ in names)
        id_like_clauses = " OR ".join("LOWER(id) LIKE ?" for _ in prefix_patterns)
        name_like_clauses = " OR ".join("LOWER(family_name) LIKE ?" for _ in name_prefix_patterns)

        clause = (
            f"("
            f"LOWER(id) IN ({placeholders_slugs}) "
            f"OR LOWER(family_name) IN ({placeholders_names}) "
            f"OR REPLACE(LOWER(family_name), ' ', '-') IN ({placeholders_slugs}) "
            f"OR nerd_font_slug IN ({placeholders_slugs}) "
            f"OR {id_like_clauses} "
            f"OR {name_like_clauses} "
            f"OR LOWER(curated_category) = 'featured'"
            f")"
        )
        params = (
            list(slugs)
            + list(names)
            + list(slugs)
            + list(slugs)
            + list(prefix_patterns)
            + list(name_prefix_patterns)
        )
        return clause, params

    async def search_fonts(self, filter_params: FontFilter) -> tuple[list[Font], int]:
        """Search and filter fonts returning paginated results and total match count."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if filter_params.query:
            clean_q = f"%{filter_params.query.strip().lower()}%"
            where_clauses.append("(LOWER(id) LIKE ? OR LOWER(family_name) LIKE ?)")
            params.extend([clean_q, clean_q])

        if filter_params.categories:
            cat_clauses = []
            for cat in filter_params.categories:
                clean_c = cat.strip().lower()
                if clean_c == "featured":
                    f_clause, f_params = self._build_featured_where_clause()
                    cat_clauses.append(f_clause)
                    params.extend(f_params)
                else:
                    cat_clauses.append("(LOWER(category) = ? OR LOWER(curated_category) = ?)")
                    params.extend([clean_c, clean_c])
            if cat_clauses:
                where_clauses.append(f"({' OR '.join(cat_clauses)})")

        if filter_params.curated_categories:
            cat_clauses = []
            for cat in filter_params.curated_categories:
                clean_c = cat.strip().lower()
                if clean_c == "featured":
                    f_clause, f_params = self._build_featured_where_clause()
                    cat_clauses.append(f_clause)
                    params.extend(f_params)
                else:
                    cat_clauses.append("(LOWER(curated_category) = ? OR LOWER(category) = ?)")
                    params.extend([clean_c, clean_c])
            if cat_clauses:
                where_clauses.append(f"({' OR '.join(cat_clauses)})")

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
        """Return font count by category and curated category."""
        counts: dict[str, int] = {}
        async with self._db.connection() as conn:
            # Count featured fonts
            f_clause, f_params = self._build_featured_where_clause()
            feat_cursor = await conn.execute(
                f"SELECT COUNT(*) AS cnt FROM fonts WHERE {f_clause}",
                tuple(f_params),
            )
            feat_row = await feat_cursor.fetchone()
            counts["Featured"] = feat_row["cnt"] if feat_row else 0

            cursor = await conn.execute(
                "SELECT curated_category, COUNT(*) AS cnt FROM fonts WHERE curated_category IS NOT NULL GROUP BY curated_category"
            )
            rows = await cursor.fetchall()
            for row in rows:
                if row["curated_category"]:
                    counts[row["curated_category"]] = row["cnt"]

            cursor = await conn.execute(
                "SELECT category, COUNT(*) AS cnt FROM fonts WHERE category IS NOT NULL GROUP BY category"
            )
            rows = await cursor.fetchall()
            for row in rows:
                if row["category"]:
                    raw_c = row["category"]
                    counts[raw_c] = row["cnt"]
                    cat_map = {
                        "sans-serif": "Sans-Serif",
                        "serif": "Serif",
                        "monospace": "Monospace",
                        "display": "Display",
                        "handwriting": "Handwriting",
                    }
                    nice_name = cat_map.get(raw_c.lower())
                    if nice_name and nice_name not in counts:
                        counts[nice_name] = row["cnt"]
        return counts

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

    async def get_installed_font(self, font_id: str, scope: str | None = None) -> InstalledFont | None:
        """Retrieve a specific installed font record by font ID and optional scope."""
        async with self._db.connection() as conn:
            if scope:
                cursor = await conn.execute(
                    "SELECT * FROM installed_fonts WHERE font_id = ? AND install_scope = ? LIMIT 1",
                    (font_id, scope),
                )
            else:
                cursor = await conn.execute(
                    "SELECT * FROM installed_fonts WHERE font_id = ? LIMIT 1",
                    (font_id,),
                )
            row = await cursor.fetchone()
            if row is None:
                return None
            return InstalledFont.from_db_row(
                id=row["id"],
                font_id=row["font_id"],
                family_name=row["family_name"],
                provider=row["provider"],
                version=row["version"],
                install_scope=row["install_scope"],
                installed_at=row["installed_at"],
                file_paths_str=row["file_paths"],
            )

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
                    except Exception as exc:
                        logger.warning("Failed to parse installed file paths JSON '%s': %s", row["file_paths"], exc)


            params_list = []
            for entry in entries:
                is_managed = 1 if (entry.file_path in managed_paths or entry.is_metaglyph_managed) else 0
                style_name = getattr(entry, "style_name", "Regular") or "Regular"
                params_list.append((
                    entry.family_name,
                    style_name,
                    entry.postscript_name,
                    entry.file_path,
                    entry.scope,
                    is_managed,
                    entry.last_scanned_at,
                ))

            if params_list:
                await conn.executemany(
                    """
                    INSERT INTO system_font_cache (
                        family_name, style_name, postscript_name, file_path,
                        scope, is_metaglyph_managed, last_scanned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        family_name = excluded.family_name,
                        style_name = excluded.style_name,
                        postscript_name = excluded.postscript_name,
                        scope = excluded.scope,
                        is_metaglyph_managed = excluded.is_metaglyph_managed,
                        last_scanned_at = excluded.last_scanned_at
                    """,
                    params_list,
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
                f"SELECT * FROM system_font_cache {where_sql} ORDER BY family_name ASC, style_name ASC",
                tuple(params),
            )
            rows = await cursor.fetchall()
            return [
                SystemFontCacheEntry(
                    family_name=row["family_name"],
                    style_name=row["style_name"] if "style_name" in row.keys() and row["style_name"] else "Regular",
                    postscript_name=row["postscript_name"],
                    file_path=row["file_path"],
                    scope=row["scope"],
                    is_metaglyph_managed=bool(row["is_metaglyph_managed"]),
                    last_scanned_at=row["last_scanned_at"],
                )
                for row in rows
            ]

    async def delete_system_font_cache_by_paths(self, file_paths: list[str]) -> None:
        """Delete specific file paths from system font cache."""
        if not file_paths:
            return
        async with self._db.connection() as conn:
            placeholders = ",".join("?" for _ in file_paths)
            await conn.execute(
                f"DELETE FROM system_font_cache WHERE file_path IN ({placeholders})",
                file_paths,
            )
            await conn.commit()

    async def link_nerd_fonts(self) -> int:
        """Scan catalog and link standard fonts with counterpart Nerd Fonts."""
        linked_count = 0
        async with self._db.connection() as conn:
            # Find all fonts marked as nerd_fonts or with nerd font names
            cursor = await conn.execute(
                "SELECT id, family_name FROM fonts WHERE primary_provider = 'nerd_fonts' OR has_nerd_font = 1"
            )
            nf_rows = await cursor.fetchall()

            # Group candidate links by base_slug
            # Priority: Standard (0) > Mono (1) > Propo (2)
            variant_priority = {"Standard": 0, "Mono": 1, "Propo": 2}
            best_links: dict[str, tuple[str, int]] = {}

            for row in nf_rows:
                nf_slug = row["id"]
                base_slug, variant = extract_nerd_font_counterpart(row["family_name"])
                if base_slug != nf_slug:
                    prio = variant_priority.get(variant, 9)
                    if base_slug not in best_links or prio < best_links[base_slug][1]:
                        best_links[base_slug] = (nf_slug, prio)

            for base_slug, (nf_slug, _) in best_links.items():
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
