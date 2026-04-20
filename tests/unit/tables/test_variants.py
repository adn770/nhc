"""M16a — list-valued entry text subsystem tests."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from nhc.tables.loader import load_table_file
from nhc.tables.registry import TableRegistry
from nhc.tables.types import SchemaError


FIXTURES = (
    Path(__file__).resolve().parents[2] / "fixtures" / "tables" / "variants"
)

BAD_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "tables" / "bad_schema"
)


def _load_registry() -> TableRegistry:
    TableRegistry._cache.clear()
    return TableRegistry.get_or_load("en", root=FIXTURES)


# ── Roll / variant_index behaviour ────────────────────────────────────


def test_roll_entry_with_string_text_has_none_variant_index() -> None:
    reg = _load_registry()
    rng = random.Random(1)
    # Force picking the single_str entry by constraining the list
    # via render (roll picks weighted-random so any might come out).
    result = reg.render(
        "variants.simple", entry_id="single_str", context={},
    )
    assert result.variant_index is None
    assert result.text == "one"


def test_roll_list_text_populates_variant_index() -> None:
    reg = _load_registry()
    rng = random.Random(0xABC)
    # Keep rolling until we land on a list-valued entry, then verify
    # the variant is in range and the text matches one of the options.
    saw_list = False
    for _ in range(50):
        r = reg.roll("variants.simple", rng=rng, context={})
        if r.entry_id == "multi_text":
            saw_list = True
            assert r.variant_index is not None
            assert 0 <= r.variant_index < 3
            assert r.text in ("alpha", "beta", "gamma")
            assert r.text == ("alpha", "beta", "gamma")[r.variant_index]
    assert saw_list, "never rolled the multi_text entry in 50 tries"


def test_list_text_variant_stable_for_same_seed() -> None:
    reg = _load_registry()
    a = reg.roll(
        "variants.simple", rng=random.Random(42), context={},
    )
    b = reg.roll(
        "variants.simple", rng=random.Random(42), context={},
    )
    assert a.entry_id == b.entry_id
    assert a.variant_index == b.variant_index
    assert a.text == b.text


# ── Render behaviour ───────────────────────────────────────────────────


def test_render_variant_kwarg_returns_kth_variant() -> None:
    reg = _load_registry()
    for k, expected in enumerate(("alpha", "beta", "gamma")):
        r = reg.render(
            "variants.simple",
            entry_id="multi_text", context={}, variant=k,
        )
        assert r.text == expected
        assert r.variant_index == k


def test_render_list_text_defaults_to_variant_zero() -> None:
    """Backward-compat: render without variant on a list entry → index 0."""
    reg = _load_registry()
    r = reg.render(
        "variants.simple", entry_id="multi_text", context={},
    )
    assert r.text == "alpha"
    assert r.variant_index == 0


def test_render_variant_out_of_range_raises() -> None:
    reg = _load_registry()
    with pytest.raises(IndexError):
        reg.render(
            "variants.simple",
            entry_id="multi_text", context={}, variant=9,
        )


def test_render_variant_ignored_on_string_text() -> None:
    """Passing variant=k to a str-text entry is ignored silently."""
    reg = _load_registry()
    r = reg.render(
        "variants.simple",
        entry_id="single_str", context={}, variant=5,
    )
    assert r.text == "one"
    assert r.variant_index is None


# ── Validator / loader ─────────────────────────────────────────────────


def test_loader_accepts_list_text() -> None:
    tables = load_table_file(FIXTURES / "en" / "ex.yaml")
    by_id = {e.id: e for e in tables[0].entries}
    assert by_id["multi_text"].text == ["alpha", "beta", "gamma"]
    assert by_id["duo_text"].text == ["red", "blue"]


def test_loader_rejects_empty_list_text(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad.empty\n"
        "kind: flavor\n"
        "lifetime: gen_time\n"
        "entries:\n"
        "  - id: zero\n"
        "    text: []\n"
    )
    with pytest.raises(SchemaError, match="empty"):
        load_table_file(bad)


def test_loader_rejects_list_with_mixed_types(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad.mixed\n"
        "kind: flavor\n"
        "lifetime: gen_time\n"
        "entries:\n"
        "  - id: oops\n"
        "    text: [hello, 42]\n"
    )
    with pytest.raises(SchemaError, match="string"):
        load_table_file(bad)


# ── Save round-trip of variant ─────────────────────────────────────────


def test_rumor_source_round_trip_preserves_variant() -> None:
    """A RumorSource carrying a variant serializes and deserializes."""
    from nhc.hexcrawl.model import HexCoord, HexWorld, Rumor, RumorSource
    from nhc.core.save import (
        _deserialize_hex_world, _serialize_hex_world,
    )

    hw = HexWorld(
        pack_id="test", seed=1, width=1, height=1,
    )
    hw.active_rumors = [
        Rumor(
            id="r1", text="any",
            truth=True,
            reveals=HexCoord(q=0, r=0),
            source=RumorSource(
                table_id="variants.simple",
                entry_id="multi_text",
                context={},
                lang="en",
                variant=2,
            ),
        ),
    ]
    data = _serialize_hex_world(hw)
    loaded = _deserialize_hex_world(data)
    r = loaded.active_rumors[0]
    assert r.source is not None
    assert r.source.variant == 2


def test_rumor_source_round_trip_absent_variant_is_none() -> None:
    """Old saves without `variant` decode to None."""
    from nhc.hexcrawl.model import HexCoord, HexWorld, Rumor, RumorSource
    from nhc.core.save import (
        _deserialize_hex_world, _serialize_hex_world,
    )

    hw = HexWorld(pack_id="test", seed=1, width=1, height=1)
    hw.active_rumors = [
        Rumor(
            id="r1", text="any",
            truth=True,
            reveals=HexCoord(q=0, r=0),
            source=RumorSource(
                table_id="rumor.true_feature",
                entry_id="innkeeper_whisper",
                context={"q": 0, "r": 0},
                lang="en",
            ),
        ),
    ]
    data = _serialize_hex_world(hw)
    # Legacy save format: source lacks "variant" key
    for r in data["active_rumors"]:
        if "source" in r:
            r["source"].pop("variant", None)
    loaded = _deserialize_hex_world(data)
    assert loaded.active_rumors[0].source.variant is None
