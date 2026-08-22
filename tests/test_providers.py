"""Tests for font providers and multi-provider manager."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from conftest import synthesize_test_font_bytes
from metaglyph.core.events import EventBus, get_event_bus
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontVariant
from metaglyph.db.repository import FontRepository
from metaglyph.providers.base import BaseFontProvider
from metaglyph.providers.fontsource import FontsourceProvider
from metaglyph.providers.google_fonts import GoogleFontsProvider
from metaglyph.providers.manager import ProviderManager
from metaglyph.providers.nerd_fonts import NerdFontsProvider
from metaglyph.subsetting.cache import SubsetCache


def create_mock_transport(handler) -> httpx.MockTransport:
    """Create httpx mock transport with request handler."""
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Google Fonts Provider Tests
# ---------------------------------------------------------------------------


def test_google_fonts_parse_variant_string() -> None:
    """Verify variant string parsing for Google Fonts tokens."""
    provider = GoogleFontsProvider()

    v_reg = provider.parse_variant_string("regular", "roboto", "Roboto")
    assert v_reg.weight == 400
    assert v_reg.style == "normal"

    v_italic = provider.parse_variant_string("italic", "roboto", "Roboto")
    assert v_italic.weight == 400
    assert v_italic.style == "italic"

    v_bold_italic = provider.parse_variant_string("700italic", "roboto", "Roboto")
    assert v_bold_italic.weight == 700
    assert v_bold_italic.style == "italic"

    v_black = provider.parse_variant_string("900", "roboto", "Roboto")
    assert v_black.weight == 900
    assert v_black.style == "normal"


@pytest.mark.asyncio
async def test_google_fonts_fetch_catalog() -> None:
    """Verify Google Fonts catalog fetching and JSON response parsing."""
    mock_metadata = {
        "familyMetadataList": [
            {
                "family": "Roboto",
                "category": "sans_serif",
                "variants": ["100", "regular", "700", "700italic"],
                "axes": [{"tag": "wght", "min": 100, "max": 900}],
            },
            {
                "family": "Fira Code",
                "category": "monospace",
                "variants": ["regular", "600"],
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "metadata/fonts" in str(request.url):
            return httpx.Response(200, json=mock_metadata)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = GoogleFontsProvider(client=client)

    fonts = await provider.fetch_catalog()
    assert len(fonts) == 2

    roboto = next(f for f in fonts if f.id == "roboto")
    assert roboto.family_name == "Roboto"
    assert roboto.category == "sans-serif"
    assert roboto.is_variable is True
    assert roboto.primary_provider == "google"
    assert len(roboto.variants) == 4

    fira = next(f for f in fonts if f.id == "fira-code")
    assert fira.category == "monospace"
    assert fira.curated_category == "Code"
    assert fira.is_variable is False
    assert len(fira.variants) == 2

    await provider.close()


@pytest.mark.asyncio
async def test_google_fonts_fetch_sample_subset_css2(temp_dir: Path) -> None:
    """Verify micro-subset fetching via Google Fonts CSS2 API."""
    cache = SubsetCache(cache_dir=temp_dir / "google_cache")
    ttf_data = synthesize_test_font_bytes("Roboto", "Regular")

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "css2" in url_str:
            css = (
                "@font-face {\n"
                "  font-family: 'Roboto';\n"
                "  src: url(https://fonts.gstatic.com/s/roboto.ttf) format('truetype');\n"
                "}"
            )
            return httpx.Response(200, text=css)
        elif "fonts.gstatic.com" in url_str:
            return httpx.Response(200, content=ttf_data)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = GoogleFontsProvider(client=client, cache=cache)

    font = Font(
        id="roboto",
        family_name="Roboto",
        category="sans-serif",
        primary_provider="google",
        last_synced_at=1000,
    )

    subset_path = await provider.fetch_sample_subset(font, "Quick Fox")
    assert subset_path.exists()
    assert cache.has_subset("roboto", "Quick Fox")
    assert subset_path.read_bytes() == ttf_data

    await provider.close()


@pytest.mark.asyncio
async def test_google_fonts_download_font_family(temp_dir: Path) -> None:
    """Verify Google Fonts family zip archive download and extraction."""
    ttf_regular = synthesize_test_font_bytes("Roboto", "Regular")
    ttf_bold = synthesize_test_font_bytes("Roboto", "Bold")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("Roboto-Regular.ttf", ttf_regular)
        z.writestr("Roboto-Bold.ttf", ttf_bold)
        z.writestr("OFL.txt", "Open Font License")

    zip_bytes = zip_buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        if "download" in str(request.url):
            return httpx.Response(200, content=zip_bytes)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = GoogleFontsProvider(client=client)

    font = Font(
        id="roboto",
        family_name="Roboto",
        category="sans-serif",
        primary_provider="google",
        last_synced_at=1000,
    )

    out_dir = temp_dir / "dl_google"
    downloaded = await provider.download_font_family(font, out_dir)

    assert len(downloaded) == 2
    assert any(p.name == "Roboto-Regular.ttf" for p in downloaded)
    assert any(p.name == "Roboto-Bold.ttf" for p in downloaded)
    assert not any(p.name == "OFL.txt" for p in downloaded)

    await provider.close()


# ---------------------------------------------------------------------------
# Fontsource Provider Tests
# ---------------------------------------------------------------------------


def test_fontsource_build_cdn_url() -> None:
    """Verify Fontsource CDN URL generation."""
    provider = FontsourceProvider()
    url = provider.build_cdn_variant_url("jetbrains-mono", weight=700, style="italic")
    assert url == "https://cdn.jsdelivr.net/fontsource/fonts/jetbrains-mono@latest/latin-700-italic.ttf"


@pytest.mark.asyncio
async def test_fontsource_fetch_catalog() -> None:
    """Verify Fontsource catalog index API parsing."""
    mock_index = [
        {
            "id": "jetbrains-mono",
            "family": "JetBrains Mono",
            "category": "monospace",
            "weights": [400, 700],
            "styles": ["normal", "italic"],
            "variable": True,
        },
        {
            "id": "inter",
            "family": "Inter",
            "category": "sans-serif",
            "weights": [400],
            "styles": ["normal"],
            "variable": False,
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if "v1/fonts" in str(request.url):
            return httpx.Response(200, json=mock_index)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = FontsourceProvider(client=client)

    fonts = await provider.fetch_catalog()
    assert len(fonts) == 2

    jb = next(f for f in fonts if f.id == "jetbrains-mono")
    assert jb.family_name == "JetBrains Mono"
    assert jb.is_variable is True
    assert jb.curated_category == "Code"
    assert len(jb.variants) == 4  # 2 weights * 2 styles
    assert jb.primary_provider == "fontsource"

    await provider.close()


@pytest.mark.asyncio
async def test_fontsource_fetch_sample_subset(temp_dir: Path) -> None:
    """Verify Fontsource CDN fetch and micro-subsetting."""
    cache = SubsetCache(cache_dir=temp_dir / "fontsource_cache")
    ttf_data = synthesize_test_font_bytes("JetBrains Mono", "Regular")

    def handler(request: httpx.Request) -> httpx.Response:
        if "cdn.jsdelivr.net" in str(request.url):
            return httpx.Response(200, content=ttf_data)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = FontsourceProvider(client=client, cache=cache)

    font = Font(
        id="jetbrains-mono",
        family_name="JetBrains Mono",
        category="monospace",
        primary_provider="fontsource",
        last_synced_at=1000,
        variants=[
            FontVariant(
                font_id="jetbrains-mono",
                provider="fontsource",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://cdn.jsdelivr.net/fontsource/fonts/jetbrains-mono@latest/latin-400-normal.ttf",
            )
        ],
    )

    subset_path = await provider.fetch_sample_subset(font, "Code Preview")
    assert subset_path.exists()
    assert cache.has_subset("jetbrains-mono", "Code Preview")

    await provider.close()


@pytest.mark.asyncio
async def test_fontsource_download_font_family(temp_dir: Path) -> None:
    """Verify Fontsource variant download and saving."""
    ttf_data = synthesize_test_font_bytes("Inter", "Regular")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ttf_data)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = FontsourceProvider(client=client)

    font = Font(
        id="inter",
        family_name="Inter",
        category="sans-serif",
        primary_provider="fontsource",
        last_synced_at=1000,
        variants=[
            FontVariant(
                font_id="inter",
                provider="fontsource",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-normal.ttf",
            ),
            FontVariant(
                font_id="inter",
                provider="fontsource",
                style="italic",
                weight=400,
                file_format="ttf",
                download_url="https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-italic.ttf",
            ),
        ],
    )

    out_dir = temp_dir / "dl_fontsource"
    downloaded = await provider.download_font_family(font, out_dir)

    assert len(downloaded) == 2
    for f in downloaded:
        assert f.exists()
        assert f.stat().st_size > 0

    await provider.close()


# ---------------------------------------------------------------------------
# Nerd Fonts Provider Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nerd_fonts_fetch_catalog_github_api() -> None:
    """Verify Nerd Fonts release asset parsing from GitHub API."""
    mock_release = {
        "assets": [
            {
                "name": "JetBrainsMono.zip",
                "browser_download_url": "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.1.1/JetBrainsMono.zip",
                "size": 34000000,
            },
            {
                "name": "FiraCode.zip",
                "browser_download_url": "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.1.1/FiraCode.zip",
                "size": 28000000,
            },
            {
                "name": "FontPatcher.zip",
                "browser_download_url": "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.1.1/FontPatcher.zip",
                "size": 5000000,
            },
            {
                "name": "cheat-sheet.json",
                "browser_download_url": "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.1.1/cheat-sheet.json",
                "size": 100000,
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "releases/latest" in str(request.url):
            return httpx.Response(200, json=mock_release)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = NerdFontsProvider(client=client)

    fonts = await provider.fetch_catalog()
    assert len(fonts) == 2

    jb = next(f for f in fonts if f.id == "jetbrainsmono-nerd-font")
    assert jb.family_name == "JetBrainsMono Nerd Font"
    assert jb.has_nerd_font is True
    assert jb.primary_provider == "nerd_fonts"
    assert len(jb.variants) == 3

    fira = next(f for f in fonts if f.id == "firacode-nerd-font")
    assert fira.family_name == "FiraCode Nerd Font"

    await provider.close()


@pytest.mark.asyncio
async def test_nerd_fonts_fetch_catalog_fallback() -> None:
    """Verify Nerd Fonts falls back to curated catalog if GitHub API is unavailable."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = NerdFontsProvider(client=client)

    fonts = await provider.fetch_catalog()
    assert len(fonts) >= 30
    assert any(f.id == "jetbrainsmono-nerd-font" for f in fonts)
    assert any(f.id == "firacode-nerd-font" for f in fonts)

    await provider.close()


@pytest.mark.asyncio
async def test_nerd_fonts_download_and_filter(temp_dir: Path) -> None:
    """Verify Nerd Font zip extraction with variant filter."""
    ttf_std = synthesize_test_font_bytes("JetBrainsMono NF", "Regular")
    ttf_mono = synthesize_test_font_bytes("JetBrainsMono NFM", "Regular")
    ttf_propo = synthesize_test_font_bytes("JetBrainsMono NFP", "Regular")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("JetBrainsMonoNerdFont-Regular.ttf", ttf_std)
        z.writestr("JetBrainsMonoNerdFontMono-Regular.ttf", ttf_mono)
        z.writestr("JetBrainsMonoNerdFontPropo-Regular.ttf", ttf_propo)

    zip_bytes = zip_buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=zip_bytes)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = NerdFontsProvider(client=client)

    font = Font(
        id="jetbrainsmono-nerd-font",
        family_name="JetBrainsMono Nerd Font",
        category="monospace",
        primary_provider="nerd_fonts",
        last_synced_at=1000,
        variants=[
            FontVariant(
                font_id="jetbrainsmono-nerd-font",
                provider="nerd_fonts",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://example.com/JetBrainsMono.zip",
            )
        ],
    )

    # 1. Test Mono filter
    out_dir_mono = temp_dir / "dl_nf_mono"
    files_mono = await provider.download_font_family(font, out_dir_mono, variant_filter="Mono")
    assert len(files_mono) == 1
    assert "Mono" in files_mono[0].name

    # 2. Test Propo filter
    out_dir_propo = temp_dir / "dl_nf_propo"
    files_propo = await provider.download_font_family(font, out_dir_propo, variant_filter="Propo")
    assert len(files_propo) == 1
    assert "Propo" in files_propo[0].name

    # 3. Test Standard filter
    out_dir_std = temp_dir / "dl_nf_std"
    files_std = await provider.download_font_family(font, out_dir_std, variant_filter="Standard")
    assert len(files_std) == 1
    assert files_std[0].name == "JetBrainsMonoNerdFont-Regular.ttf"

    await provider.close()


# ---------------------------------------------------------------------------
# Provider Manager Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_manager_sync_and_linking(
    repository: FontRepository,
    sample_font_jetbrains: Font,
) -> None:
    """Verify ProviderManager orchestrates catalog sync, DB upserts, and Nerd Font linking."""
    mock_fontsource = MagicMock(spec=BaseFontProvider)
    mock_fontsource.name = "fontsource"
    # Base font
    mock_fontsource.fetch_catalog = AsyncMock(
        return_value=[
            Font(
                id="jetbrains-mono",
                family_name="JetBrains Mono",
                category="monospace",
                curated_category="Code",
                primary_provider="fontsource",
                last_synced_at=1000,
            )
        ]
    )

    mock_nerd_fonts = MagicMock(spec=BaseFontProvider)
    mock_nerd_fonts.name = "nerd_fonts"
    # Counterpart Nerd Font
    mock_nerd_fonts.fetch_catalog = AsyncMock(
        return_value=[
            Font(
                id="jetbrainsmono-nerd-font",
                family_name="JetBrainsMono Nerd Font",
                category="monospace",
                curated_category="Code",
                has_nerd_font=True,
                nerd_font_slug="jetbrainsmono-nerd-font",
                primary_provider="nerd_fonts",
                last_synced_at=1000,
            )
        ]
    )

    manager = ProviderManager(providers=[mock_fontsource, mock_nerd_fonts])

    # Event tracking
    events_received: list[str] = []

    def on_event(**kwargs):
        events_received.append("catalog_synced")

    get_event_bus().subscribe("catalog_synced", on_event)

    results = await manager.sync_all(repository)

    assert results["fontsource"] == 1
    assert results["nerd_fonts"] == 1
    assert "catalog_synced" in events_received

    # Verify standard font in DB was linked to the Nerd Font
    stored_font = await repository.get_font("jetbrains-mono")
    assert stored_font is not None
    assert stored_font.has_nerd_font is True
    assert stored_font.nerd_font_slug == "jetbrainsmono-nerd-font"

    get_event_bus().unsubscribe("catalog_synced", on_event)
    await manager.close()


@pytest.mark.asyncio
async def test_google_fonts_fallback_subset(temp_dir: Path) -> None:
    """Verify GoogleFontsProvider falls back to downloading archive when CSS2 endpoint fails."""
    cache = SubsetCache(cache_dir=temp_dir / "google_fallback_cache")
    ttf_data = synthesize_test_font_bytes("Roboto", "Regular")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("Roboto-Regular.ttf", ttf_data)
    zip_bytes = zip_buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "css2" in url_str:
            # Simulate CSS2 500 error
            return httpx.Response(500)
        elif "download" in url_str:
            return httpx.Response(200, content=zip_bytes)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=create_mock_transport(handler))
    provider = GoogleFontsProvider(client=client, cache=cache)

    font = Font(
        id="roboto",
        family_name="Roboto",
        category="sans-serif",
        primary_provider="google",
        last_synced_at=1000,
    )

    subset_path = await provider.fetch_sample_subset(font, "Fallback Sample")
    assert subset_path.exists()
    assert cache.has_subset("roboto", "Fallback Sample")

    await provider.close()


@pytest.mark.asyncio
async def test_provider_manager_routing(temp_dir: Path) -> None:
    """Verify ProviderManager routes subset and download calls to the correct provider."""
    mock_google = MagicMock(spec=BaseFontProvider)
    mock_google.name = "google"
    mock_google.fetch_sample_subset = AsyncMock(return_value=temp_dir / "google.ttf")
    mock_google.download_font_family = AsyncMock(return_value=[temp_dir / "google.ttf"])

    mock_fontsource = MagicMock(spec=BaseFontProvider)
    mock_fontsource.name = "fontsource"
    mock_fontsource.fetch_sample_subset = AsyncMock(return_value=temp_dir / "fontsource.ttf")
    mock_fontsource.download_font_family = AsyncMock(return_value=[temp_dir / "fontsource.ttf"])

    manager = ProviderManager(providers=[mock_google, mock_fontsource])

    font_fs = Font(
        id="inter",
        family_name="Inter",
        category="sans-serif",
        primary_provider="fontsource",
        last_synced_at=1000,
    )

    # 1. Fetch subset with primary provider fontsource
    res_fs = await manager.fetch_sample_subset(font_fs, "Sample")
    assert res_fs == temp_dir / "fontsource.ttf"
    assert mock_fontsource.fetch_sample_subset.call_count == 1

    # 2. Download with preferred provider override
    res_override = await manager.download_font_family(font_fs, temp_dir, preferred_provider="google")
    assert res_override == [temp_dir / "google.ttf"]
    assert mock_google.download_font_family.call_count == 1

    # 3. Unknown provider lookup error
    with pytest.raises(KeyError):
        manager.get_provider("nonexistent")

    await manager.close()
