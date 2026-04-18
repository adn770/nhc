"""Integration tests for rumor generation via TableRegistry."""

from __future__ import annotations

import random
from pathlib import Path
from unittest.mock import patch

from nhc.hexcrawl.model import Rumor, RumorSource
from nhc.i18n import init as i18n_init


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _world(seed: int = 7):
    from nhc.hexcrawl._generator import generate_continental_world
    from nhc.hexcrawl.pack import load_pack

    pack = Path(__file__).resolve().parents[3] / "content" / "testland" / "pack.yaml"
    return generate_continental_world(seed=seed, pack=load_pack(pack))


def setup_module():
    i18n_init("en")


# ---------------------------------------------------------------------------
# M6 integration tests
# ---------------------------------------------------------------------------


def test_rumor_generation_populates_source() -> None:
    from nhc.hexcrawl.rumor_pool import generate_rumors

    world = _world()
    rumors = generate_rumors(world, seed=1, count=3, lang="en")
    for r in rumors:
        assert r.source is not None, f"rumor {r.id} has no source"
        assert isinstance(r.source, RumorSource)
        assert r.source.table_id in (
            "rumor.true_feature", "rumor.false_lead",
        )
        assert r.source.entry_id
        assert r.source.lang == "en"
        assert "q" in r.source.context
        assert "r" in r.source.context


def test_rumor_text_is_rendered_not_a_key() -> None:
    from nhc.hexcrawl.rumor_pool import generate_rumors

    world = _world()
    rumors = generate_rumors(world, seed=1, count=3, lang="en")
    for r in rumors:
        assert r.reveals is not None
        # Text should contain the actual coordinates, not a key
        assert str(r.reveals.q) in r.text, (
            f"expected q={r.reveals.q} in text: {r.text!r}"
        )
        assert str(r.reveals.r) in r.text, (
            f"expected r={r.reveals.r} in text: {r.text!r}"
        )
        # Should NOT be a bare i18n key
        assert not r.text.startswith("rumor.")


def test_rumor_save_roundtrip_preserves_source() -> None:
    from nhc.core.save import _deserialize_hex_world, _serialize_hex_world
    from nhc.hexcrawl.rumor_pool import generate_rumors

    world = _world()
    world.active_rumors = generate_rumors(
        world, seed=1, count=2, lang="en",
    )
    data = _serialize_hex_world(world)
    loaded = _deserialize_hex_world(data)
    for r in loaded.active_rumors:
        assert r.source is not None
        assert r.source.table_id
        assert r.source.entry_id
        assert r.source.lang == "en"


def test_rumor_save_load_old_format_tolerates_missing_source() -> None:
    from nhc.core.save import _deserialize_hex_world

    world = _world()
    # Simulate old save format: "text_key" field, no "source"
    old_data = _minimal_hex_data(world)
    old_data["active_rumors"] = [
        {
            "id": "old_rumor",
            "text_key": "rumor.true_feature",
            "truth": True,
            "reveals": [3, 4],
        },
    ]
    loaded = _deserialize_hex_world(old_data)
    assert len(loaded.active_rumors) == 1
    r = loaded.active_rumors[0]
    assert r.text == "rumor.true_feature"
    assert r.source is None


def _minimal_hex_data(world):
    """Build a minimal serialized hex world dict for testing."""
    from nhc.core.save import _serialize_hex_world

    data = _serialize_hex_world(world)
    data["active_rumors"] = []
    return data


def test_generate_rumors_uses_table_registry() -> None:
    from nhc.hexcrawl.rumor_pool import generate_rumors
    from nhc.tables.registry import TableRegistry

    world = _world()
    with patch.object(
        TableRegistry, "get_or_load", wraps=TableRegistry.get_or_load,
    ) as spy:
        generate_rumors(world, seed=1, count=3, lang="ca")
        spy.assert_called_with("ca")


def test_refresh_rumor_language_swaps_text_preserves_id_and_reveals() -> None:
    from nhc.hexcrawl.rumor_pool import generate_rumors, refresh_rumor_language

    world = _world()
    rumors = generate_rumors(world, seed=1, count=1, lang="en")
    original = rumors[0]
    refreshed = refresh_rumor_language(original, "ca")
    assert refreshed.id == original.id
    assert refreshed.reveals == original.reveals
    assert refreshed.truth == original.truth
    assert refreshed.text != original.text
    assert refreshed.source.lang == "ca"
