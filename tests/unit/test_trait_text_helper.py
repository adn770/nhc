"""M14 — trait_text helper replaces the legacy traits.{id} i18n lookup."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


LOCALE_DIR = Path(__file__).resolve().parents[1].parent / "nhc" / "i18n" / "locales"


def test_trait_text_renders_known_axis() -> None:
    from nhc.i18n import init as i18n_init
    from nhc.rules.chargen import trait_text

    i18n_init("en")
    assert trait_text("virtue", "brave") == "brave"
    assert trait_text("background", "alchemist") == "alchemist"
    assert trait_text("alignment", "lawful") == "Lawful"


def test_trait_text_follows_current_locale() -> None:
    from nhc.i18n import init as i18n_init
    from nhc.rules.chargen import trait_text

    i18n_init("ca")
    assert trait_text("virtue", "brave") == "valent"
    assert trait_text("vice", "aggressive") == "agressiu"
    assert trait_text("alignment", "chaotic") == "Caòtic"

    i18n_init("es")
    assert trait_text("virtue", "brave") == "valiente"
    assert trait_text("alignment", "chaotic") == "Caótico"

    i18n_init("en")


def test_trait_text_unknown_axis_raises() -> None:
    from nhc.rules.chargen import trait_text

    with pytest.raises(KeyError):
        trait_text("nonsense", "foo")


def test_trait_text_unknown_entry_id_raises() -> None:
    from nhc.i18n import init as i18n_init
    from nhc.rules.chargen import trait_text

    i18n_init("en")
    with pytest.raises(KeyError):
        trait_text("virtue", "not_a_trait")


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
def test_legacy_traits_block_removed_from_i18n(lang: str) -> None:
    """M14 cleanup: nhc/i18n/locales/*.yaml no longer ships `traits:`."""
    path = LOCALE_DIR / f"{lang}.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert "traits" not in data, (
        f"{lang}.yaml still has a top-level 'traits' block"
    )


def test_legacy_chargen_constants_are_gone() -> None:
    import nhc.rules.chargen as chargen

    for name in (
        "PHYSIQUE", "FACE", "SKIN", "HAIR", "CLOTHING",
        "VIRTUE", "VICE", "SPEECH", "BACKGROUND",
        "MISFORTUNE", "ALIGNMENT", "_ALIGNMENT_THRESHOLDS",
        "_pick", "_roll_alignment",
    ):
        assert not hasattr(chargen, name), (
            f"chargen.py still exposes legacy symbol '{name}'"
        )
