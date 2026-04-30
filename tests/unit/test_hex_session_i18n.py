"""Hex-session messages must be translated in every locale.

Regression: user on a Catalan session saw ``"You enter the
city."`` and ``"You leave the area."`` in English because
``nhc/core/hex_session.py`` and ``nhc/core/game.py`` called
``renderer.add_message`` with hardcoded English strings.

These tests pin every user-facing string that gets emitted from
hex exploration dispatch so every new locale has to supply the
translation (fallback-to-English is still the runtime safety
net, but in CI we want to catch missing keys).
"""

from __future__ import annotations

import pytest

from nhc.i18n import init, t


_KEYS = [
    "hex.msg.leave_area",
    "hex.msg.return_overland",
    "hex.msg.cant_go_that_way",
    "hex.msg.nothing_to_enter",
    "hex.msg.panic_flee",
    "hex.msg.enter_feature",                   # template "You enter the {feature}."
    "hex.msg.start_journey",                   # opening flower-view tutorial
]


_FEATURE_KEYS = [
    # Major features routed through bespoke generators.
    "hex.feature.city",
    "hex.feature.village",
    "hex.feature.community",
    "hex.feature.tower",
    "hex.feature.keep",
    "hex.feature.mansion",
    "hex.feature.farm",
    "hex.feature.cottage",
    "hex.feature.temple",
    "hex.feature.cave",
    "hex.feature.ruin",
    "hex.feature.hole",
    "hex.feature.graveyard",
    "hex.feature.crystals",
    "hex.feature.stones",
    "hex.feature.wonder",
    "hex.feature.portal",
    "hex.feature.lake",
    "hex.feature.river",
]


_MINOR_KEYS = [
    "hex.minor.farm",
    "hex.minor.well",
    "hex.minor.shrine",
    "hex.minor.signpost",
    "hex.minor.campsite",
    "hex.minor.orchard",
    "hex.minor.cairn",
    "hex.minor.animal_den",
    "hex.minor.hollow_log",
    "hex.minor.mushroom_ring",
    "hex.minor.herb_patch",
    "hex.minor.bone_pile",
    "hex.minor.standing_stone",
    "hex.minor.lair",
    "hex.minor.nest",
    "hex.minor.burrow",
]


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
@pytest.mark.parametrize(
    "key", _KEYS + _FEATURE_KEYS + _MINOR_KEYS,
)
def test_key_resolves_and_is_not_the_key_itself(
    lang: str, key: str,
) -> None:
    """A missing translation leaves ``t`` returning the literal
    key as its own value — a clear regression signal."""
    init(lang)
    if key == "hex.msg.enter_feature":
        resolved = t(key, feature="Test")
    else:
        resolved = t(key)
    assert resolved != key, (
        f"{lang}: missing translation for {key!r}"
    )


def test_enter_feature_template_has_feature_placeholder() -> None:
    """The template must interpolate the feature name so each
    locale can word-order it correctly (e.g. gender-agreeing
    articles in Catalan/Spanish)."""
    for lang in ("en", "ca", "es"):
        init(lang)
        out = t("hex.msg.enter_feature", feature="__MARKER__")
        assert "__MARKER__" in out, (
            f"{lang}: enter_feature template lost the marker — "
            f"got {out!r}"
        )
