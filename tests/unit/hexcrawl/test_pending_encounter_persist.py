"""Autosave round-trip for :attr:`Game.pending_encounter`.

Without persistence a server restart mid-prompt drops the
Fight/Flee/Talk state and the player silently loses an encounter
they were about to resolve. The autosave payload now carries
the staged :class:`Encounter` (or ``None``) verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.core.autosave import autosave, read_autosave_payload
from nhc.core.ecs import World
from nhc.core.events import EventBus
from nhc.hexcrawl.encounter_pipeline import Encounter
from nhc.hexcrawl.model import Biome


class _FakeRenderer:
    def __init__(self) -> None:
        self._messages: list[str] = []

    @property
    def messages(self) -> list[str]:
        return self._messages

    @messages.setter
    def messages(self, value: list[str]) -> None:
        self._messages = value


class _StubGame:
    """Minimal shape autosave.autosave() understands."""

    def __init__(self) -> None:
        self.world = World()
        self.event_bus = EventBus()
        self.seed = 42
        self.turn = 0
        self.player_id = -1
        self.level = None
        self.god_mode = False
        self.style = "classic"
        self.renderer = _FakeRenderer()
        self._floor_cache: dict = {}
        self._svg_cache: dict = {}
        self._knowledge = None
        self._character = None
        self._seen_creatures: set = set()
        self.running = False
        self.won = False
        self.game_over = False
        self.killed_by = ""
        self.hex_world = None
        self.hex_player_position = None
        self.pending_encounter = None


@pytest.fixture
def save_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "autosave.nhc"
    monkeypatch.setattr(
        "nhc.core.autosave._DEFAULT_PATH", path,
    )
    monkeypatch.setattr(
        "nhc.core.autosave._DEFAULT_DIR", tmp_path,
    )
    return path


def test_pending_encounter_roundtrips_through_autosave(save_path) -> None:
    g = _StubGame()
    g.pending_encounter = Encounter(
        biome=Biome.FOREST,
        creatures=["goblin", "kobold", "giant_rat"],
    )
    autosave(g)
    payload = read_autosave_payload(save_path)
    assert payload is not None
    assert "pending_encounter" in payload
    restored = payload["pending_encounter"]
    assert isinstance(restored, Encounter)
    assert restored.biome is Biome.FOREST
    assert restored.creatures == ["goblin", "kobold", "giant_rat"]


def test_none_pending_encounter_roundtrips(save_path) -> None:
    g = _StubGame()
    g.pending_encounter = None
    autosave(g)
    payload = read_autosave_payload(save_path)
    assert payload is not None
    assert payload.get("pending_encounter") is None


def test_legacy_payload_without_field_restores_as_none(
    save_path, monkeypatch,
) -> None:
    """Old pickles written before the field existed should
    restore cleanly (payload.get defaults to None)."""
    g = _StubGame()
    g.pending_encounter = Encounter(biome=Biome.MOUNTAIN, creatures=["orc"])
    autosave(g)
    # Strip the new field to emulate a pre-change payload.
    payload = read_autosave_payload(save_path)
    assert payload is not None
    payload.pop("pending_encounter", None)
    assert payload.get("pending_encounter") is None
