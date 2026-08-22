"""Font name normalization, Nerd Font association, and provider priority resolution."""

from __future__ import annotations

import re
from metaglyph.core.config import get_config

# Regex patterns for slug normalization
_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9]+")

# Known foundry prefixes to optionally strip or clean
_FOUNDRY_PREFIXES = [
    "adobe ",
    "google ",
]

# Nerd Font indicator tokens
_NERD_FONT_TOKENS = [
    "nerd font",
    "nerd-font",
    " nerd ",
    "-nerd-",
    " nf ",
    "-nf-",
    " nfm ",
    "-nfm-",
]


_COMPOUND_SUFFIXES = [
    ("NerdFontMono", " Nerd Font Mono"),
    ("NerdFontPropo", " Nerd Font Propo"),
    ("NerdFont", " Nerd Font"),
    ("NFPropo", " NF Propo"),
    ("NFM", " NFM"),
    ("NF", " NF"),
    ("Mono", " Mono"),
    ("Code", " Code"),
    ("Sans", " Sans"),
    ("Serif", " Serif"),
    ("Pro", " Pro"),
    ("Display", " Display"),
    ("Text", " Text"),
    ("LGS", " LGS"),
]


def normalize_family_name(name: str) -> str:
    """Normalize a font family name into a canonical slug identifier.

    Examples:
        "JetBrains Mono" -> "jetbrains-mono"
        "JetBrainsMono" -> "jetbrains-mono"
        "Fira Code" -> "fira-code"
        "FiraCode" -> "fira-code"
        "Source Sans 3" -> "source-sans-3"
    """
    clean_name = name.strip()

    # Split known joined camelCase suffixes if not already spaced
    for suffix, replacement in _COMPOUND_SUFFIXES:
        if clean_name.endswith(suffix) and not clean_name.endswith(replacement):
            prefix_part = clean_name[:-len(suffix)]
            if prefix_part:
                clean_name = f"{prefix_part}{replacement}"
                break

    lower_name = clean_name.lower()
    for prefix in _FOUNDRY_PREFIXES:
        if lower_name.startswith(prefix):
            lower_name = lower_name[len(prefix):].strip()
            break

    slug = _SLUG_CLEAN_RE.sub("-", lower_name).strip("-")
    return slug or "unnamed-font"


def is_nerd_font(name: str) -> bool:
    """Detect if a font name or slug indicates a patched Nerd Font."""
    lower = f" {name.lower().replace('-', ' ').replace('_', ' ')} "
    if "nerd font" in lower or " nf " in lower or " nfm " in lower or " nfpropo " in lower:
        return True
    return False


def extract_nerd_font_counterpart(name: str) -> tuple[str, str]:
    """Parse a Nerd Font family name and return its base standard font slug and variant.

    Returns:
        (base_family_slug, variant_name) where variant_name is 'Standard', 'Mono', or 'Propo'.

    Examples:
        "JetBrainsMono Nerd Font" -> ("jetbrains-mono", "Standard")
        "JetBrainsMono Nerd Font Mono" -> ("jetbrains-mono", "Mono")
        "JetBrainsMono Nerd Font Propo" -> ("jetbrains-mono", "Propo")
        "FiraCode NF" -> ("fira-code", "Standard")
        "Hack NFM" -> ("hack", "Mono")
    """
    variant = "Standard"
    lower = name.lower()

    if "propo" in lower or "nfpropo" in lower:
        variant = "Propo"
    elif " mono" in lower or "nfm" in lower:
        variant = "Mono"

    # Remove Nerd font suffix tokens
    cleaned = re.sub(
        r"(?i)(\s+|-|_)?(nerd\s*font(\s*mono|\s*propo)?|nfpropo|nfm|nf)\b",
        "",
        name,
    ).strip()

    base_slug = normalize_family_name(cleaned)
    return base_slug, variant


def curate_category(raw_category: str | None, family_name: str) -> str:
    """Map raw provider category and family name to Metaglyph's curated category.

    Categories:
    - Interface: Clean UI sans-serif fonts
    - Code: Monospace and programming fonts
    - Header: Display or strong serif/sans fonts for headings
    - Prose: High-legibility serif and body reading fonts
    - Display: Decorative, stylized, or headline fonts
    - Handwriting: Script, cursive, or handwritten fonts
    """
    raw_cat = (raw_category or "").strip().lower()
    fam_lower = family_name.lower()

    # Code / Monospace check
    if (
        raw_cat in ("monospace", "code")
        or "mono" in fam_lower
        or "code" in fam_lower
        or "nerd font" in fam_lower
        or is_nerd_font(family_name)
    ):
        return "Code"

    # Handwriting / Script check
    if raw_cat in ("handwriting", "script") or any(t in fam_lower for t in ("script", "hand", "calligraph")):
        return "Handwriting"

    # Specific raw category mappings
    if raw_cat == "display":
        return "Display"

    if raw_cat == "serif":
        # Known prose reading serifs
        if any(term in fam_lower for term in ("reader", "text", "book", "merriweather", "lora", "pt serif", "garamond", "charter")):
            return "Prose"
        return "Header"

    if raw_cat in ("sans-serif", "sans_serif", "sansserif"):
        if any(term in fam_lower for term in ("text", "book", "pt sans", "open sans", "roboto", "noto sans")):
            return "Prose"
        return "Interface"

    # Fallback when raw category is not provided
    if "display" in fam_lower or "poster" in fam_lower:
        return "Display"

    return "Interface"


def get_provider_priority(provider: str) -> int:
    """Return numeric priority for provider (lower number = higher precedence)."""
    config = get_config()
    return config.provider_priorities.get(provider.lower(), 99)


def should_replace_primary_provider(existing_provider: str, new_provider: str) -> bool:
    """Return True if new_provider has higher priority than existing_provider."""
    return get_provider_priority(new_provider) < get_provider_priority(existing_provider)
