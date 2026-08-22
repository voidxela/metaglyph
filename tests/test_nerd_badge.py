"""Unit tests for NerdFontBadge UI component."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from metaglyph.db.models import Font, FontVariant
from metaglyph.ui.components.nerd_badge import NerdFontBadge


def test_nerd_badge_initial_and_none() -> None:
    badge = NerdFontBadge()
    assert badge.get_selected_variant() == "Standard"

    badge.set_font(None)
    assert badge.isHidden()


def test_nerd_badge_with_standard_counterpart(sample_font_jetbrains: Font) -> None:
    badge = NerdFontBadge()
    badge.set_font(sample_font_jetbrains)

    assert not badge.isHidden()
    assert "Counterpart Available" in badge._title_label.text()
    assert badge._switch_btn.text() == "Switch to Nerd Font"

    # Variant selection
    emitted_variants: list[str] = []
    badge.variant_changed.connect(emitted_variants.append)

    badge.set_selected_variant("Mono")
    assert badge.get_selected_variant() == "Mono"
    assert "Mono" in emitted_variants

    badge.set_selected_variant("Propo")
    assert badge.get_selected_variant() == "Propo"
    assert "Propo" in emitted_variants

    # Switch click signal
    switches: list[tuple[str, str]] = []
    badge.switch_requested.connect(lambda s, v: switches.append((s, v)))

    badge._switch_btn.click()
    assert len(switches) == 1
    assert switches[0][0] == "jetbrainsmono-nerd-font"
    assert switches[0][1] == "Propo"


def test_nerd_badge_with_already_nerd_font() -> None:
    nf_font = Font(
        id="fira-code-nerd-font",
        family_name="FiraCode Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        nerd_font_slug="fira-code-nerd-font",
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
        variants=[
            FontVariant(
                font_id="fira-code-nerd-font",
                provider="nerd_fonts",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://example.com/firacode.zip",
            )
        ],
    )

    badge = NerdFontBadge()
    badge.set_font(nf_font)

    assert not badge.isHidden()
    assert "Patched Version" in badge._title_label.text()
    assert "Original Standard Font" in badge._switch_btn.text()

    switches: list[tuple[str, str]] = []
    badge.switch_requested.connect(lambda s, v: switches.append((s, v)))

    badge._switch_btn.click()
    assert len(switches) == 1
    assert switches[0][0] == "fira-code"


def test_nerd_badge_hidden_for_non_nerd_font(sample_font_inter: Font) -> None:
    badge = NerdFontBadge()
    badge.set_font(sample_font_inter)

    assert badge.isHidden()
