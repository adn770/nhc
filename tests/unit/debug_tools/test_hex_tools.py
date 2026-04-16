"""MCP hex-debug tools (M-4.1).

Covers the pure-function layer that the MCP tool wrappers call
into. Each entry in the plan's tool table gets at least one
test: reveal_all_hexes, teleport_hex, force_encounter,
show_world_state, advance_day_clock, set_rumor_truth,
clear_dungeon_at, seed_dungeon_at.
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.debug import (
    advance_day_clock,
    clear_dungeon_at,
    force_encounter,
    reveal_all_hexes,
    seed_dungeon_at,
    set_rumor_truth,
    show_world_state,
    teleport_hex,
)
from nhc.hexcrawl.encounter_pipeline import Encounter
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    HexCell,
    HexFeatureType,
    HexWorld,
    Rumor,
    TimeOfDay,
)


def _tiny_world() -> HexWorld:
    w = HexWorld(pack_id="test", seed=0, width=4, height=4)
    for q in range(3):
        for r in range(3):
            c = HexCoord(q=q, r=r)
            w.cells[c] = HexCell(
                coord=c, biome=Biome.GREENLANDS,
                feature=HexFeatureType.NONE,
            )
    # Seed one feature hex for the teleport / seed tests.
    cave = HexCoord(q=2, r=2)
    w.cells[cave].feature = HexFeatureType.CAVE
    w.cells[cave].dungeon = DungeonRef(template="procedural:cave")
    w.reveal(HexCoord(q=0, r=0))
    return w


# ---------------------------------------------------------------------------
# reveal_all_hexes
# ---------------------------------------------------------------------------


def test_reveal_all_hexes_reveals_every_cell() -> None:
    w = _tiny_world()
    revealed_before = len(w.revealed)
    n = reveal_all_hexes(w)
    assert len(w.revealed) == len(w.cells)
    assert n == len(w.cells) - revealed_before
    for coord in w.cells:
        assert coord in w.revealed


def test_reveal_all_hexes_is_idempotent() -> None:
    w = _tiny_world()
    reveal_all_hexes(w)
    n = reveal_all_hexes(w)
    assert n == 0


# ---------------------------------------------------------------------------
# teleport_hex
# ---------------------------------------------------------------------------


def test_teleport_hex_accepts_in_shape_target() -> None:
    w = _tiny_world()
    target = HexCoord(q=2, r=1)
    ok = teleport_hex(w, target)
    assert ok is True
    # Side effect: target is revealed (debug tools act like a
    # "scrying" / god-mode teleport and lift the fog).
    assert target in w.revealed


def test_teleport_hex_marks_target_as_visited() -> None:
    """A teleport means the player IS at that hex; it should
    join the visited set, not just the revealed set. Otherwise
    repeat teleports to the same hex keep re-counting as a
    first visit in downstream logic."""
    w = _tiny_world()
    target = HexCoord(q=2, r=1)
    teleport_hex(w, target)
    assert target in w.visited


def test_teleport_hex_rejects_out_of_shape() -> None:
    w = _tiny_world()
    ok = teleport_hex(w, HexCoord(q=99, r=99))
    assert ok is False


# ---------------------------------------------------------------------------
# force_encounter
# ---------------------------------------------------------------------------


def test_force_encounter_builds_encounter_with_biome_pool() -> None:
    enc = force_encounter(Biome.FOREST)
    assert isinstance(enc, Encounter)
    assert enc.biome is Biome.FOREST
    assert enc.creatures, "force_encounter should draw a non-empty pack"


def test_force_encounter_honours_explicit_creature_list() -> None:
    enc = force_encounter(
        Biome.MOUNTAIN, creatures=["goblin", "kobold"],
    )
    assert enc.creatures == ["goblin", "kobold"]


# ---------------------------------------------------------------------------
# show_world_state
# ---------------------------------------------------------------------------


def test_show_world_state_returns_serializable_snapshot() -> None:
    w = _tiny_world()
    state = show_world_state(w, player=HexCoord(q=0, r=0))
    assert state["day"] == w.day
    assert state["time"] == w.time.name.lower()
    assert state["width"] == w.width
    assert state["height"] == w.height
    # Cell summary uses axial coords + biome + feature strings.
    assert state["cells"], "snapshot must include cells"
    sample = state["cells"][0]
    assert {"q", "r", "biome", "feature", "revealed"} <= set(sample.keys())
    # Player section echoes the requested coord.
    assert state["player"] == {"q": 0, "r": 0}


# ---------------------------------------------------------------------------
# advance_day_clock
# ---------------------------------------------------------------------------


def test_advance_day_clock_moves_forward() -> None:
    w = _tiny_world()
    w.day = 1
    w.time = TimeOfDay.MORNING
    advance_day_clock(w, segments=4)  # full day
    assert w.day == 2
    assert w.time is TimeOfDay.MORNING


def test_advance_day_clock_rejects_negative_segments() -> None:
    w = _tiny_world()
    try:
        advance_day_clock(w, segments=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError on negative segments")


# ---------------------------------------------------------------------------
# set_rumor_truth
# ---------------------------------------------------------------------------


def test_set_rumor_truth_flips_matching_rumor() -> None:
    w = _tiny_world()
    w.active_rumors = [
        Rumor(id="r1", text_key="rumor.foo", truth=True),
        Rumor(id="r2", text_key="rumor.bar", truth=True),
    ]
    ok = set_rumor_truth(w, "r2", False)
    assert ok is True
    assert w.active_rumors[0].truth is True
    assert w.active_rumors[1].truth is False


def test_set_rumor_truth_returns_false_on_missing_id() -> None:
    w = _tiny_world()
    w.active_rumors = [Rumor(id="r1", text_key="x", truth=True)]
    assert set_rumor_truth(w, "nope", False) is False


# ---------------------------------------------------------------------------
# clear_dungeon_at
# ---------------------------------------------------------------------------


def test_clear_dungeon_at_marks_cleared_set() -> None:
    w = _tiny_world()
    coord = HexCoord(q=2, r=2)
    assert coord not in w.cleared
    ok = clear_dungeon_at(w, coord)
    assert ok is True
    assert coord in w.cleared


def test_clear_dungeon_at_rejects_out_of_shape() -> None:
    w = _tiny_world()
    assert clear_dungeon_at(w, HexCoord(q=99, r=99)) is False


# ---------------------------------------------------------------------------
# seed_dungeon_at
# ---------------------------------------------------------------------------


def test_seed_dungeon_at_writes_feature_and_template() -> None:
    w = _tiny_world()
    coord = HexCoord(q=1, r=1)
    ok = seed_dungeon_at(
        w, coord,
        feature=HexFeatureType.RUIN,
        template="procedural:ruin",
    )
    assert ok is True
    cell = w.cells[coord]
    assert cell.feature is HexFeatureType.RUIN
    assert cell.dungeon is not None
    assert cell.dungeon.template == "procedural:ruin"


def test_seed_dungeon_at_rejects_out_of_shape() -> None:
    w = _tiny_world()
    ok = seed_dungeon_at(
        w, HexCoord(q=99, r=99),
        feature=HexFeatureType.CAVE,
        template="procedural:cave",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# MCP wrapper integration: load from an autosave, apply tool
# ---------------------------------------------------------------------------


import pytest  # noqa: E402

from nhc.core.autosave import autosave  # noqa: E402
from nhc.core.ecs import World  # noqa: E402
from nhc.core.events import EventBus  # noqa: E402
from nhc.debug_tools.tools.hex_tools import (  # noqa: E402
    ForceEncounterTool,
    RevealAllHexesTool,
    ShowWorldStateTool,
    TeleportHexTool,
)


class _FakeRenderer:
    def __init__(self) -> None:
        self._messages: list[str] = []

    @property
    def messages(self) -> list[str]:
        return self._messages

    @messages.setter
    def messages(self, value: list[str]) -> None:
        self._messages = value


class _FakeHexGame:
    """Minimal game shape that autosave.autosave() understands."""

    def __init__(self, hex_world: HexWorld) -> None:
        self.world = World()
        self.event_bus = EventBus()
        self.seed = 42
        self.turn = 0
        self.player_id = -1
        self.level = None
        self.god_mode = False
        self.mode = "classic"
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
        self.hex_world = hex_world

    def _update_fov(self) -> None:
        pass


@pytest.fixture
def autosave_with_hex(tmp_path, monkeypatch):
    """Write a signed autosave containing a real HexWorld."""
    save_path = tmp_path / "autosave.nhc"
    monkeypatch.setattr(
        "nhc.core.autosave._DEFAULT_PATH", save_path,
    )
    monkeypatch.setattr(
        "nhc.core.autosave._DEFAULT_DIR", tmp_path,
    )
    hw = _tiny_world()
    autosave(_FakeHexGame(hw))
    return save_path, hw


@pytest.mark.asyncio
async def test_show_world_state_tool_reads_autosave(
    autosave_with_hex,
) -> None:
    save_path, _ = autosave_with_hex
    result = await ShowWorldStateTool().execute(path=str(save_path))
    assert "error" not in result
    assert result["player"] == {"q": 0, "r": 0}
    assert result["cells"], "cells must be present"
    assert result["width"] == 4 and result["height"] == 4


@pytest.mark.asyncio
async def test_reveal_all_hexes_tool_reports_count(
    autosave_with_hex,
) -> None:
    save_path, _ = autosave_with_hex
    result = await RevealAllHexesTool().execute(path=str(save_path))
    assert "error" not in result
    assert result["total_revealed"] == result["total_cells"] == 9
    # Only (0,0) was pre-revealed; rest are new.
    assert result["newly_revealed"] == 8


@pytest.mark.asyncio
async def test_teleport_hex_tool_accepts_in_shape(
    autosave_with_hex,
) -> None:
    save_path, _ = autosave_with_hex
    result = await TeleportHexTool().execute(
        path=str(save_path),
        target={"q": 2, "r": 2},
    )
    assert result["ok"] is True
    assert result["target"] == {"q": 2, "r": 2}


@pytest.mark.asyncio
async def test_force_encounter_tool_parses_biome_string() -> None:
    result = await ForceEncounterTool().execute(
        biome="forest",
        creatures=["goblin"],
    )
    assert result["biome"] == "forest"
    assert result["creatures"] == ["goblin"]


@pytest.mark.asyncio
async def test_tool_errors_on_missing_autosave(tmp_path) -> None:
    result = await ShowWorldStateTool().execute(
        path=str(tmp_path / "does-not-exist.nhc"),
    )
    assert "error" in result
