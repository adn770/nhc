"""Tests for buried marker description localization."""

import pytest

from nhc.core.actions._interaction import _place_buried_marker
from nhc.core.ecs import World
from nhc.i18n import init as i18n_init


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
def test_buried_marker_description_is_localized(lang):
    """BuriedMarker Description uses locale strings, not hardcoded English."""
    i18n_init(lang)
    world = World()
    world.turn = 1
    eid = _place_buried_marker(world, 3, 4, "test", 1)
    desc = world.get_component(eid, "Description")
    assert desc is not None
    # Must not be the raw locale key (t() returns the key on miss)
    assert not desc.name.startswith("feature."), (
        f"locale key returned as-is for lang={lang}: {desc.name}"
    )
    assert not desc.short.startswith("feature."), (
        f"locale key returned as-is for lang={lang}: {desc.short}"
    )
    # English values should match the en.yaml entries
    if lang == "en":
        assert desc.name == "buried treasure"
        assert desc.short == "something hidden underfoot"
    # Non-English must differ from English
    else:
        assert desc.name != "buried treasure", (
            f"lang={lang} should not return English name"
        )
