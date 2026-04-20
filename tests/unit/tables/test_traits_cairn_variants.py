"""M16b — Cairn-informed CA/ES idiom replacements and variants.

Confirms the specific content decisions made during the M16b
collaborative shortlist: 7 straight replacements and 3 list-valued
variant additions. Also verifies the Cairn CC-BY attribution file
is in place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.tables.registry import TableRegistry


LOCALES_ROOT = (
    Path(__file__).resolve().parents[3] / "nhc" / "tables" / "locales"
)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _registry(lang: str) -> TableRegistry:
    TableRegistry._cache.clear()
    return TableRegistry.get_or_load(lang, root=LOCALES_ROOT)


# ── Straight replacements ──────────────────────────────────────────────


@pytest.mark.parametrize("lang,table,entry,expected", [
    ("ca", "trait.vice", "bitter", "amargat"),
    ("ca", "trait.vice", "deceitful", "mentider"),
    ("es", "trait.vice", "deceitful", "mentiroso"),
    ("es", "trait.vice", "rude", "rudo"),
    ("ca", "trait.background", "performer", "artista"),
    ("es", "trait.background", "performer", "artista"),
    ("es", "trait.background", "merchant", "mercader"),
])
def test_cairn_replacement_renders(
    lang: str, table: str, entry: str, expected: str,
) -> None:
    reg = _registry(lang)
    result = reg.render(table, entry_id=entry, context={})
    assert result.text == expected


# ── List-valued variants ───────────────────────────────────────────────


VARIANT_CASES = [
    # lang, table_id, entry_id, (variant_0, variant_1)
    ("ca", "trait.virtue", "gregarious", ("gregari", "sociable")),
    ("es", "trait.virtue", "gregarious", ("gregario", "sociable")),
    ("es", "trait.virtue", "cautious", ("prudente", "precavido")),
]


@pytest.mark.parametrize("lang,table,entry,variants", VARIANT_CASES)
def test_cairn_variant_both_options_reachable(
    lang: str, table: str, entry: str, variants: tuple[str, str],
) -> None:
    reg = _registry(lang)
    v0 = reg.render(table, entry_id=entry, context={}, variant=0)
    v1 = reg.render(table, entry_id=entry, context={}, variant=1)
    assert v0.text == variants[0]
    assert v1.text == variants[1]
    assert v0.variant_index == 0
    assert v1.variant_index == 1


@pytest.mark.parametrize("lang,table,entry,variants", VARIANT_CASES)
def test_cairn_variant_is_list_typed(
    lang: str, table: str, entry: str, variants: tuple[str, str],
) -> None:
    """The entry ships its text as a list, not a string."""
    from nhc.tables.loader import load_lang

    tables = load_lang(lang, root=LOCALES_ROOT)
    by_id = {e.id: e for e in tables[table].entries}
    assert isinstance(by_id[entry].text, list)
    assert list(by_id[entry].text) == list(variants)


# ── Cross-locale structural parity still holds ─────────────────────────


def test_trait_tables_still_validate() -> None:
    """Replacements and variants must not introduce entry-id drift."""
    from nhc.tables.validator import validate_all

    errors = [
        e for e in validate_all(root=LOCALES_ROOT)
        if e.table_id.startswith("trait.")
    ]
    assert errors == [], "\n".join(e.detail for e in errors)


# ── Attribution ────────────────────────────────────────────────────────


def test_license_content_file_exists_and_credits_cairn() -> None:
    path = REPO_ROOT / "LICENSE-CONTENT.md"
    assert path.is_file(), "LICENSE-CONTENT.md missing from repo root"
    text = path.read_text()
    assert "Cairn" in text
    assert "CC BY 4.0" in text
    assert "Yochai Gal" in text
