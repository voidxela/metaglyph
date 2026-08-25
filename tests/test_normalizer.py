"""Unit tests for font name normalization, category curation, and provider priority."""

from __future__ import annotations

import pytest

from metaglyph.db.normalizer import (
    curate_category,
    extract_nerd_font_counterpart,
    get_provider_priority,
    is_nerd_font,
    normalize_family_name,
    should_replace_primary_provider,
)


@pytest.mark.parametrize(
    "input_name, expected_slug",
    [
        ("JetBrains Mono", "jetbrains-mono"),
        ("JetBrainsMono", "jetbrains-mono"),
        ("Fira Code", "fira-code"),
        ("FiraCode", "fira-code"),
        ("Source Sans 3", "source-sans-3"),
        ("Noto Sans JP", "noto-sans-jp"),
        ("Adobe Garamond Pro", "garamond-pro"),
        ("Google Sans", "sans"),
        ("  Space Mono  ", "space-mono"),
        ("Cascadia_Code", "cascadia-code"),
        ("PT-Serif", "pt-serif"),
    ],
)
def test_normalize_family_name(input_name: str, expected_slug: str) -> None:
    """Test family name normalization to canonical slugs."""
    assert normalize_family_name(input_name) == expected_slug


@pytest.mark.parametrize(
    "name, expected",
    [
        ("JetBrainsMono Nerd Font", True),
        ("FiraCode NF", True),
        ("Hack NFM", True),
        ("CascadiaCode NFPropo", True),
        ("MesloLGS Nerd Font Mono", True),
        ("Roboto", False),
        ("JetBrains Mono", False),
        ("Open Sans", False),
        ("Fira Code", False),
    ],
)
def test_is_nerd_font(name: str, expected: bool) -> None:
    """Test Nerd Font detection."""
    assert is_nerd_font(name) == expected


@pytest.mark.parametrize(
    "nf_name, expected_slug, expected_variant",
    [
        ("JetBrainsMono Nerd Font", "jetbrains-mono", "Standard"),
        ("JetBrainsMono Nerd Font Mono", "jetbrains-mono", "Mono"),
        ("JetBrainsMono Nerd Font Propo", "jetbrains-mono", "Propo"),
        ("FiraCode NF", "fira-code", "Standard"),
        ("Hack NFM", "hack", "Mono"),
        ("MesloLGS NFPropo", "meslo-lgs", "Propo"),
    ],
)
def test_extract_nerd_font_counterpart(
    nf_name: str, expected_slug: str, expected_variant: str
) -> None:
    """Test extraction of base font slug and variant from Nerd Font names."""
    base_slug, variant = extract_nerd_font_counterpart(nf_name)
    assert base_slug == expected_slug
    assert variant == expected_variant


@pytest.mark.parametrize(
    "raw_category, family_name, expected_curated",
    [
        ("monospace", "JetBrains Mono", "Code"),
        ("sans-serif", "Fira Code", "Code"),
        ("sans-serif", "Inter", "Interface"),
        ("sans-serif", "Roboto", "Prose"),
        ("serif", "Merriweather", "Prose"),
        ("serif", "Playfair Display", "Header"),
        ("display", "Bebas Neue", "Display"),
        ("handwriting", "Dancing Script", "Handwriting"),
    ],
)
def test_curate_category(
    raw_category: str, family_name: str, expected_curated: str
) -> None:
    """Test category mapping to curated UI categories."""
    assert curate_category(raw_category, family_name) == expected_curated


def test_provider_priorities() -> None:
    """Test provider priority ranking and replacement decisions."""
    # fontsource (1) > fontsquirrel (2) > nerd_fonts (3)
    assert get_provider_priority("fontsource") < get_provider_priority("fontsquirrel")
    assert get_provider_priority("fontsquirrel") < get_provider_priority("nerd_fonts")

    # Fontsource replaces Font Squirrel
    assert should_replace_primary_provider("fontsquirrel", "fontsource") is True
    # Font Squirrel does not replace Fontsource
    assert should_replace_primary_provider("fontsource", "fontsquirrel") is False
    # Fontsource replaces Nerd Fonts
    assert should_replace_primary_provider("nerd_fonts", "fontsource") is True
    # Font Squirrel replaces Nerd Fonts
    assert should_replace_primary_provider("nerd_fonts", "fontsquirrel") is True
    # Nerd Fonts does not replace Font Squirrel
    assert should_replace_primary_provider("fontsquirrel", "nerd_fonts") is False
