"""Unit and integration tests for SQLite DatabaseManager and FontRepository."""

from __future__ import annotations

import time
import pytest

from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import (
    Font,
    FontFilter,
    FontVariant,
    InstalledFont,
    SystemFontCacheEntry,
)
from metaglyph.db.repository import FontRepository


@pytest.mark.asyncio
async def test_schema_initialization(db_manager: DatabaseManager) -> None:
    """Verify database tables and indexes are created properly."""
    async with db_manager.connection() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] for row in await cursor.fetchall()]
        assert "fonts" in tables
        assert "font_variants" in tables
        assert "installed_fonts" in tables
        assert "system_font_cache" in tables


@pytest.mark.asyncio
async def test_upsert_and_get_font(
    repository: FontRepository, sample_font_jetbrains: Font
) -> None:
    """Test inserting and retrieving a font with its variants."""
    await repository.upsert_font(sample_font_jetbrains)

    fetched = await repository.get_font_by_id("jetbrains-mono")
    assert fetched is not None
    assert fetched.id == "jetbrains-mono"
    assert fetched.family_name == "JetBrains Mono"
    assert fetched.curated_category == "Code"
    assert fetched.is_variable is True
    assert fetched.has_nerd_font is True
    assert fetched.primary_provider == "fontsource"
    assert len(fetched.variants) == 2
    assert fetched.variants[0].weight == 400
    assert fetched.variants[1].weight == 700

    # Retrieve by family name
    by_name = await repository.get_font_by_slug_or_family("JetBrains Mono")
    assert by_name is not None
    assert by_name.id == "jetbrains-mono"


@pytest.mark.asyncio
async def test_provider_priority_deduplication(repository: FontRepository) -> None:
    """Verify provider priority resolution during deduplication."""
    now = int(time.time())

    # 1. Insert from Font Squirrel (Priority 2)
    fontsquirrel_font = Font(
        id="fira-code",
        family_name="Fira Code",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=False,
        primary_provider="fontsquirrel",
        last_synced_at=now,
        variants=[
            FontVariant(
                font_id="fira-code",
                provider="fontsquirrel",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://fontsquirrel.com/fira-400.ttf",
            )
        ],
    )
    await repository.upsert_font(fontsquirrel_font)

    font_after_fsquirrel = await repository.get_font_by_id("fira-code")
    assert font_after_fsquirrel is not None
    assert font_after_fsquirrel.primary_provider == "fontsquirrel"
    assert len(font_after_fsquirrel.variants) == 1

    # 2. Upsert same font from Fontsource (Priority 1 - Higher)
    fontsource_font = Font(
        id="fira-code",
        family_name="Fira Code",
        category="monospace",
        curated_category="Code",
        is_variable=True,
        has_nerd_font=False,
        primary_provider="fontsource",
        last_synced_at=now + 10,
        variants=[
            FontVariant(
                font_id="fira-code",
                provider="fontsource",
                style="normal",
                weight=500,
                file_format="woff2",
                download_url="https://fontsource.org/fira-500.woff2",
            )
        ],
    )
    await repository.upsert_font(fontsource_font)

    font_after_fs = await repository.get_font_by_id("fira-code")
    assert font_after_fs is not None
    # Primary provider upgraded to Fontsource
    assert font_after_fs.primary_provider == "fontsource"
    assert font_after_fs.is_variable is True
    # Variants from both providers are merged
    assert len(font_after_fs.variants) == 2

    # 3. Upsert from Nerd Fonts (Priority 3 - Lower)
    nerd_font = Font(
        id="fira-code",
        family_name="Fira Code",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        nerd_font_slug="firacode-nerd-font",
        primary_provider="nerd_fonts",
        last_synced_at=now + 20,
        variants=[],
    )
    await repository.upsert_font(nerd_font)

    font_after_nf = await repository.get_font_by_id("fira-code")
    assert font_after_nf is not None
    # Primary provider remains Fontsource
    assert font_after_nf.primary_provider == "fontsource"
    # Nerd font flag and slug were updated
    assert font_after_nf.has_nerd_font is True
    assert font_after_nf.nerd_font_slug == "firacode-nerd-font"


@pytest.mark.asyncio
async def test_search_and_filtering(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
) -> None:
    """Test search queries and multi-attribute filters."""
    await repository.upsert_fonts([sample_font_jetbrains, sample_font_inter])

    # Search by text query
    results, total = await repository.search_fonts(FontFilter(query="jetbrains"))
    assert total == 1
    assert results[0].id == "jetbrains-mono"

    # Search by curated category
    results, total = await repository.search_fonts(
        FontFilter(curated_categories=["Interface"])
    )
    assert total == 1
    assert results[0].id == "inter"

    # Search by Featured curated category (including IosevkaTerm and Meslo Nerd Fonts)
    sample_font_fira = Font(
        id="fira-code",
        family_name="Fira Code",
        category="monospace",
        curated_category="Code",
        is_variable=True,
        has_nerd_font=True,
        primary_provider="fontsource",
        last_synced_at=1700000000,
    )
    sample_font_iosevka_term = Font(
        id="iosevka-term-nerd-font",
        family_name="IosevkaTerm Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        nerd_font_slug="iosevka-term-nerd-font",
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    sample_font_meslo = Font(
        id="meslo-lg-nerd-font",
        family_name="MesloLG Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        nerd_font_slug="meslo-lg-nerd-font",
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    await repository.upsert_fonts([sample_font_fira, sample_font_iosevka_term, sample_font_meslo])

    featured_results, featured_total = await repository.search_fonts(
        FontFilter(curated_categories=["Featured"])
    )
    assert featured_total == 3
    featured_ids = {r.id for r in featured_results}
    assert "fira-code" in featured_ids
    assert "iosevka-term-nerd-font" in featured_ids
    assert "meslo-lg-nerd-font" in featured_ids
    assert "jetbrains-mono" not in featured_ids
    assert "inter" not in featured_ids

    # Search by provider
    results, total = await repository.search_fonts(
        FontFilter(providers=["fontsource"])
    )
    assert total == 2
    assert {r.id for r in results} == {"jetbrains-mono", "fira-code"}

    # Search by Nerd Font availability
    results, total = await repository.search_fonts(
        FontFilter(has_nerd_font=True)
    )
    assert total == 4

    # Pagination test
    results, total = await repository.search_fonts(
        FontFilter(limit=1, offset=1)
    )
    assert total == 5
    assert len(results) == 1


@pytest.mark.asyncio
async def test_category_counts(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
) -> None:
    """Test curated category counting."""
    sample_font_fira = Font(
        id="fira-code",
        family_name="Fira Code",
        category="monospace",
        curated_category="Code",
        is_variable=True,
        has_nerd_font=True,
        primary_provider="fontsource",
        last_synced_at=1700000000,
    )
    sample_font_iosevka_term = Font(
        id="iosevka-term-nerd-font",
        family_name="IosevkaTerm Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    sample_font_meslo = Font(
        id="meslo-lg-nerd-font",
        family_name="MesloLG Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    await repository.upsert_fonts([
        sample_font_jetbrains,
        sample_font_inter,
        sample_font_fira,
        sample_font_iosevka_term,
        sample_font_meslo,
    ])
    counts = await repository.get_curated_category_counts()

    assert counts.get("Code") == 4
    assert counts.get("Interface") == 1
    assert counts.get("Featured") == 3


@pytest.mark.asyncio
async def test_installation_tracking(
    repository: FontRepository, sample_font_jetbrains: Font
) -> None:
    """Test recording, checking, and deleting font installations."""
    await repository.upsert_font(sample_font_jetbrains)

    assert await repository.is_font_installed("jetbrains-mono") is False

    installed = InstalledFont(
        font_id="jetbrains-mono",
        family_name="JetBrains Mono",
        provider="fontsource",
        version="2.304",
        install_scope="User",
        installed_at=int(time.time()),
        file_paths=["/home/user/.local/share/fonts/JetBrainsMono-Regular.ttf"],
    )
    await repository.record_installation(installed)

    assert await repository.is_font_installed("jetbrains-mono") is True

    installed_list = await repository.get_installed_fonts()
    assert len(installed_list) == 1
    assert installed_list[0].font_id == "jetbrains-mono"
    assert installed_list[0].file_paths == [
        "/home/user/.local/share/fonts/JetBrainsMono-Regular.ttf"
    ]

    # Delete installation
    removed = await repository.remove_installation("jetbrains-mono", scope="User")
    assert removed is True
    assert await repository.is_font_installed("jetbrains-mono") is False


@pytest.mark.asyncio
async def test_system_font_cache_sync(
    repository: FontRepository, sample_font_jetbrains: Font
) -> None:
    """Test system font cache scanning and correlation with managed fonts."""
    await repository.upsert_font(sample_font_jetbrains)

    installed_path = "/home/user/.local/share/fonts/JetBrainsMono-Regular.ttf"
    await repository.record_installation(
        InstalledFont(
            font_id="jetbrains-mono",
            family_name="JetBrains Mono",
            provider="fontsource",
            install_scope="User",
            installed_at=int(time.time()),
            file_paths=[installed_path],
        )
    )

    now = int(time.time())
    entries = [
        SystemFontCacheEntry(
            family_name="JetBrains Mono",
            file_path=installed_path,
            scope="User",
            is_metaglyph_managed=False,  # Repository will correlate and set True
            last_scanned_at=now,
        ),
        SystemFontCacheEntry(
            family_name="DejaVu Sans",
            file_path="/usr/share/fonts/DejaVuSans.ttf",
            scope="System",
            is_metaglyph_managed=False,
            last_scanned_at=now,
        ),
    ]

    await repository.sync_system_font_cache(entries)

    cached_all = await repository.get_system_fonts()
    assert len(cached_all) == 2

    # Metaglyph managed only
    managed = await repository.get_system_fonts(metaglyph_only=True)
    assert len(managed) == 1
    assert managed[0].family_name == "JetBrains Mono"
    assert managed[0].is_metaglyph_managed is True


@pytest.mark.asyncio
async def test_link_nerd_fonts(repository: FontRepository) -> None:
    """Test linking standard fonts with nerd font counterparts."""
    now = int(time.time())

    # Standard font
    std_font = Font(
        id="fira-code",
        family_name="Fira Code",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=False,
        primary_provider="fontsquirrel",
        last_synced_at=now,
    )
    # Nerd font
    nf_font = Font(
        id="firacode-nerd-font",
        family_name="FiraCode Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=now,
    )

    await repository.upsert_fonts([std_font, nf_font])

    linked = await repository.link_nerd_fonts()
    assert linked >= 1

    updated_std = await repository.get_font_by_id("fira-code")
    assert updated_std is not None
    assert updated_std.has_nerd_font is True
    assert updated_std.nerd_font_slug == "firacode-nerd-font"


@pytest.mark.asyncio
async def test_link_nerd_fonts_variant_priority(repository: FontRepository) -> None:
    """Test that link_nerd_fonts deterministically prioritizes Standard over Mono and Propo."""
    now = int(time.time())

    base_font = Font(
        id="jetbrains-mono",
        family_name="JetBrains Mono",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=False,
        primary_provider="fontsquirrel",
        last_synced_at=now,
    )
    # Insert in reverse priority order (Propo, then Mono, then Standard)
    nf_propo = Font(
        id="jetbrainsmono-nfp",
        family_name="JetBrainsMono Nerd Font Propo",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=now,
    )
    nf_mono = Font(
        id="jetbrainsmono-nfm",
        family_name="JetBrainsMono Nerd Font Mono",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=now,
    )
    nf_std = Font(
        id="jetbrainsmono-nerd-font",
        family_name="JetBrainsMono Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=now,
    )

    await repository.upsert_fonts([base_font, nf_propo, nf_mono, nf_std])
    await repository.link_nerd_fonts()

    updated = await repository.get_font_by_id("jetbrains-mono")
    assert updated is not None
    assert updated.has_nerd_font is True
    # Standard variant must be prioritized
    assert updated.nerd_font_slug == "jetbrainsmono-nerd-font"


@pytest.mark.asyncio
async def test_file_db_persistence(
    file_db_manager: DatabaseManager, sample_font_jetbrains: Font
) -> None:
    """Verify data persistence in file-backed SQLite database."""
    repo = FontRepository(file_db_manager)
    await repo.upsert_font(sample_font_jetbrains)

    # Re-open database with a new connection manager pointing to the same file
    new_manager = DatabaseManager(db_path=file_db_manager.db_path)
    await new_manager.initialize()
    new_repo = FontRepository(new_manager)

    font = await new_repo.get_font_by_id("jetbrains-mono")
    assert font is not None
    assert font.family_name == "JetBrains Mono"
    assert len(font.variants) == 2


@pytest.mark.asyncio
async def test_get_nonexistent_font(repository: FontRepository) -> None:
    """Verify None is returned when looking up non-existent font."""
    assert await repository.get_font_by_id("non-existent") is None
    assert await repository.get_font_by_slug_or_family("Non Existent Family") is None


@pytest.mark.asyncio
async def test_stats_and_empty_repository(repository: FontRepository) -> None:
    """Test get_stats on empty and populated repository."""
    stats = await repository.get_stats()
    assert stats == {"total_fonts": 0, "total_variants": 0, "total_installed": 0}

    results, total = await repository.search_fonts(FontFilter())
    assert total == 0
    assert len(results) == 0


@pytest.mark.asyncio
async def test_add_variants_standalone(
    repository: FontRepository, sample_font_inter: Font
) -> None:
    """Test adding variants independently to an existing font."""
    await repository.upsert_font(sample_font_inter)

    new_variant = FontVariant(
        font_id="inter",
        provider="fontsquirrel",
        style="italic",
        weight=700,
        file_format="ttf",
        download_url="https://example.com/inter-700italic.ttf",
        filesize=98000,
    )
    await repository.add_variants([new_variant])

    fetched = await repository.get_font_by_id("inter")
    assert fetched is not None
    assert len(fetched.variants) == 2
    assert any(v.style == "italic" and v.weight == 700 for v in fetched.variants)


@pytest.mark.asyncio
async def test_upsert_fonts_return_count(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
) -> None:
    """Verify that upsert_fonts returns exact integer count of processed fonts."""
    empty_count = await repository.upsert_fonts([])
    assert empty_count == 0

    count = await repository.upsert_fonts([sample_font_jetbrains, sample_font_inter])
    assert count == 2


@pytest.mark.asyncio
async def test_prune_stale_provider_fonts(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
) -> None:
    """Verify that prune_stale_provider_fonts removes stale records not in active catalog."""
    await repository.upsert_fonts([sample_font_jetbrains, sample_font_inter])

    # Inter is primary_provider = fontsquirrel
    # Pruning fontsquirrel keeping only chunkfive should delete inter
    pruned = await repository.prune_stale_provider_fonts("fontsquirrel", ["chunkfive"])
    assert pruned == 1

    inter = await repository.get_font_by_id("inter")
    assert inter is None

    jb = await repository.get_font_by_id("jetbrains-mono")
    assert jb is not None
