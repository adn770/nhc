"""M17 — CA/ES translations for the 7 previously-untranslated axes.

M13 shipped physique/face/skin/hair/clothing/speech/misfortune with
English placeholder text in the CA and ES tables (no i18n existed
for those axes). M17 fills the 140 entries × 2 languages with
translations drawn from the Knave CA/ES reference docs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.tables.loader import load_lang
from nhc.tables.registry import TableRegistry


LOCALES_ROOT = (
    Path(__file__).resolve().parents[3] / "nhc" / "tables" / "locales"
)

UNTRANSLATED_AXES = (
    "trait.physique",
    "trait.face",
    "trait.skin",
    "trait.hair",
    "trait.clothing",
    "trait.speech",
    "trait.misfortune",
)

# ── Representative spot-checks (not exhaustive — full coverage
# below via no-placeholders check) ─────────────────────────────────────


CA_SPOT_CHECKS = {
    ("trait.physique", "athletic"): "atlètic",
    ("trait.physique", "brawny"): "forçut",
    ("trait.physique", "gaunt"): "demacrat",
    ("trait.face", "bloated"): "inflada",
    ("trait.face", "wicked"): "malèvola",
    ("trait.skin", "battle_scar"): "cicatriu de guerra",
    ("trait.skin", "pockmarked"): "granelluda",
    ("trait.hair", "bald"): "calb",
    ("trait.hair", "dreadlocks"): "rastes",
    ("trait.clothing", "antique"): "antiga",
    ("trait.clothing", "tattered"): "estripada",
    ("trait.speech", "whispering"): "xiuxiuejant",
    ("trait.speech", "stuttering"): "tartamuda",
    ("trait.misfortune", "abandoned"): "abandonat",
    ("trait.misfortune", "kidnapped"): "segrestat",
}

ES_SPOT_CHECKS = {
    ("trait.physique", "athletic"): "atlético",
    ("trait.physique", "gaunt"): "demacrado",
    ("trait.physique", "scrawny"): "flaco",
    ("trait.face", "bloated"): "hinchada",
    ("trait.face", "elongated"): "alargada",
    ("trait.skin", "battle_scar"): "cicatriz de guerra",
    ("trait.skin", "pockmarked"): "marcas de viruela",
    ("trait.hair", "bald"): "calvo",
    ("trait.hair", "braided"): "trenzado",
    ("trait.clothing", "bloody"): "ensangrentados",
    ("trait.speech", "whispering"): "susurrante",
    ("trait.misfortune", "kidnapped"): "secuestrado",
    ("trait.misfortune", "exiled"): "exiliado",
}


@pytest.mark.parametrize("key,expected", list(CA_SPOT_CHECKS.items()))
def test_ca_spot_checks(key: tuple[str, str], expected: str) -> None:
    table_id, entry_id = key
    TableRegistry._cache.clear()
    try:
        reg = TableRegistry.get_or_load("ca", root=LOCALES_ROOT)
        result = reg.render(table_id, entry_id=entry_id, context={})
        assert result.text == expected
    finally:
        TableRegistry._cache.clear()


@pytest.mark.parametrize("key,expected", list(ES_SPOT_CHECKS.items()))
def test_es_spot_checks(key: tuple[str, str], expected: str) -> None:
    table_id, entry_id = key
    TableRegistry._cache.clear()
    try:
        reg = TableRegistry.get_or_load("es", root=LOCALES_ROOT)
        result = reg.render(table_id, entry_id=entry_id, context={})
        assert result.text == expected
    finally:
        TableRegistry._cache.clear()


# ── Coverage: no more English placeholders in CA/ES for the 7 axes ────


# Known true cognates — identical across EN/<lang> by language history,
# not an untranslated placeholder.
COGNATES: dict[str, set[tuple[str, str]]] = {
    "ca": {
        ("trait.physique", "corpulent"),
        ("trait.physique", "robust"),
        ("trait.skin", "radiant"),
        ("trait.clothing", "elegant"),
        ("trait.speech", "formal"),
        ("trait.speech", "dialectal"),
        ("trait.speech", "incoherent"),
    },
    "es": {
        ("trait.speech", "formal"),
        ("trait.speech", "grave"),
        ("trait.speech", "dialectal"),
    },
}


@pytest.mark.parametrize("lang", ["ca", "es"])
def test_no_english_placeholders_remain(lang: str) -> None:
    """Every non-cognate entry in the 7 axes differs from its EN twin."""
    en = load_lang("en", root=LOCALES_ROOT)
    other = load_lang(lang, root=LOCALES_ROOT)
    allowed = COGNATES[lang]

    overlaps: list[str] = []
    for table_id in UNTRANSLATED_AXES:
        en_text = {e.id: e.text for e in en[table_id].entries}
        other_text = {e.id: e.text for e in other[table_id].entries}
        for eid, otxt in other_text.items():
            etxt = en_text[eid]
            # Only compare str-typed text (lists untouched by M17)
            if isinstance(otxt, str) and isinstance(etxt, str):
                if otxt == etxt and (table_id, eid) not in allowed:
                    overlaps.append(f"{table_id}/{eid}={otxt!r}")

    assert not overlaps, (
        f"{lang}: {len(overlaps)} entries still carry the EN "
        f"placeholder:\n  " + "\n  ".join(overlaps)
    )


# ── Structural parity still holds ─────────────────────────────────────


def test_trait_tables_still_validate() -> None:
    from nhc.tables.validator import validate_all

    errors = [
        e for e in validate_all(root=LOCALES_ROOT)
        if e.table_id.startswith("trait.")
    ]
    assert errors == [], "\n".join(e.detail for e in errors)
