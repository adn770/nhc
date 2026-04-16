"""MCP debug tools for hex-mode worlds.

Each tool loads the :class:`HexWorld` from the autosave file,
applies a single transform from :mod:`nhc.hexcrawl.debug`, and
returns a JSON-friendly summary of the result. Mutations are
currently **dry-run** against an in-memory copy -- they tell the
operator what the next state WOULD look like but don't write
back to the live save. Writing back requires a cooperating game
process (hex worlds that belong to an active session must not be
rewritten under the session's feet); that integration lands with
the M-4.2 admin UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nhc.core.autosave import read_autosave_payload
from nhc.debug_tools.base import BaseTool
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
from nhc.hexcrawl.model import Biome, HexFeatureType, HexWorld


_DEFAULT_AUTOSAVE = "debug/autosave.nhc"


def _load_hex_world(path: Path) -> HexWorld | None:
    """Pull the HexWorld section out of the autosave at ``path``.

    Returns ``None`` for missing / unsigned / legacy-format
    saves, or for saves with no ``hex_world`` section (a
    pure dungeon-mode save).
    """
    payload = read_autosave_payload(path)
    if payload is None:
        return None
    return payload.get("hex_world")


def _coord_param() -> dict[str, Any]:
    """Re-usable JSON schema fragment for axial ``(q, r)`` input."""
    return {
        "type": "object",
        "properties": {
            "q": {"type": "integer"},
            "r": {"type": "integer"},
        },
        "required": ["q", "r"],
    }


class ShowWorldStateTool(BaseTool):
    name = "show_world_state"
    description = (
        "Return the HexWorld snapshot from the current autosave: "
        "cells (q, r, biome, feature, revealed/visited/cleared "
        "flags), day/time clock, and the active rumor list."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Autosave path (default: debug/autosave.nhc)"
                ),
            },
            "player": {
                **_coord_param(),
                "description": (
                    "Axial coord echoed in the response; defaults "
                    "to (0, 0) when absent."
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path = Path(kwargs.get("path") or _DEFAULT_AUTOSAVE)
        hw = _load_hex_world(path)
        if hw is None:
            return {"error": f"No hex-mode autosave at {path}"}
        player_raw = kwargs.get("player") or {"q": 0, "r": 0}
        player = HexCoord(q=player_raw["q"], r=player_raw["r"])
        return show_world_state(hw, player)


class RevealAllHexesTool(BaseTool):
    name = "reveal_all_hexes"
    description = (
        "Lift the fog of war: mark every in-shape hex as "
        "revealed. Reports newly-revealed count (dry run on an "
        "in-memory copy; does not rewrite the autosave)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path = Path(kwargs.get("path") or _DEFAULT_AUTOSAVE)
        hw = _load_hex_world(path)
        if hw is None:
            return {"error": f"No hex-mode autosave at {path}"}
        n = reveal_all_hexes(hw)
        return {
            "newly_revealed": n,
            "total_revealed": len(hw.revealed),
            "total_cells": len(hw.cells),
        }


class TeleportHexTool(BaseTool):
    name = "teleport_hex"
    description = (
        "Treat the given axial (q, r) coord as the new player "
        "position. Reveals the target and its neighbours so the "
        "teleport doubles as a scrying lens. Returns whether the "
        "target is in-shape."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "target": _coord_param(),
        },
        "required": ["target"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path = Path(kwargs.get("path") or _DEFAULT_AUTOSAVE)
        target_raw = kwargs["target"]
        target = HexCoord(q=target_raw["q"], r=target_raw["r"])
        hw = _load_hex_world(path)
        if hw is None:
            return {"error": f"No hex-mode autosave at {path}"}
        ok = teleport_hex(hw, target)
        return {
            "target": {"q": target.q, "r": target.r},
            "ok": ok,
            "revealed_count": len(hw.revealed),
        }


class ForceEncounterTool(BaseTool):
    name = "force_encounter"
    description = (
        "Build an Encounter descriptor for a given biome; "
        "optionally supply an explicit creature list."
    )
    parameters = {
        "type": "object",
        "properties": {
            "biome": {
                "type": "string",
                "description": (
                    "Biome enum value (greenlands, drylands, "
                    "sandlands, icelands, deadlands, forest, "
                    "mountain)"
                ),
            },
            "creatures": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional creature id list (omits the "
                    "biome-default pool draw)"
                ),
            },
        },
        "required": ["biome"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        biome_str = kwargs["biome"]
        try:
            biome = Biome(biome_str)
        except ValueError:
            return {"error": f"Unknown biome {biome_str!r}"}
        creatures = kwargs.get("creatures")
        enc = force_encounter(biome, creatures=creatures)
        return {
            "biome": enc.biome.value,
            "creatures": list(enc.creatures),
        }


class AdvanceDayClockTool(BaseTool):
    name = "advance_day_clock"
    description = (
        "Advance the overland clock by N half-day segments "
        "(4 segments = one full day)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "segments": {
                "type": "integer",
                "description": "Number of half-day segments",
            },
        },
        "required": ["segments"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path = Path(kwargs.get("path") or _DEFAULT_AUTOSAVE)
        segments = int(kwargs["segments"])
        hw = _load_hex_world(path)
        if hw is None:
            return {"error": f"No hex-mode autosave at {path}"}
        try:
            advance_day_clock(hw, segments)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"day": hw.day, "time": hw.time.name.lower()}


class SetRumorTruthTool(BaseTool):
    name = "set_rumor_truth"
    description = (
        "Flip the truth flag on a rumor in HexWorld.active_rumors."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "rumor_id": {"type": "string"},
            "truth": {"type": "boolean"},
        },
        "required": ["rumor_id", "truth"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path = Path(kwargs.get("path") or _DEFAULT_AUTOSAVE)
        rumor_id = kwargs["rumor_id"]
        truth = bool(kwargs["truth"])
        hw = _load_hex_world(path)
        if hw is None:
            return {"error": f"No hex-mode autosave at {path}"}
        ok = set_rumor_truth(hw, rumor_id, truth)
        return {
            "rumor_id": rumor_id,
            "truth": truth,
            "updated": ok,
        }


class ClearDungeonAtTool(BaseTool):
    name = "clear_dungeon_at"
    description = (
        "Mark the hex at (q, r) as a cleared dungeon."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "coord": _coord_param(),
        },
        "required": ["coord"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path = Path(kwargs.get("path") or _DEFAULT_AUTOSAVE)
        coord_raw = kwargs["coord"]
        coord = HexCoord(q=coord_raw["q"], r=coord_raw["r"])
        hw = _load_hex_world(path)
        if hw is None:
            return {"error": f"No hex-mode autosave at {path}"}
        ok = clear_dungeon_at(hw, coord)
        return {
            "coord": {"q": coord.q, "r": coord.r},
            "ok": ok,
            "cleared_count": len(hw.cleared),
        }


class SeedDungeonAtTool(BaseTool):
    name = "seed_dungeon_at"
    description = (
        "Write a feature + dungeon template at the given hex."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "coord": _coord_param(),
            "feature": {
                "type": "string",
                "description": "HexFeatureType value, e.g. 'cave'",
            },
            "template": {
                "type": "string",
                "description": (
                    "DungeonRef.template, e.g. 'procedural:cave'"
                ),
            },
            "depth": {"type": "integer"},
        },
        "required": ["coord", "feature", "template"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        path = Path(kwargs.get("path") or _DEFAULT_AUTOSAVE)
        coord_raw = kwargs["coord"]
        coord = HexCoord(q=coord_raw["q"], r=coord_raw["r"])
        try:
            feature = HexFeatureType(kwargs["feature"])
        except ValueError:
            return {
                "error": (
                    f"Unknown feature {kwargs['feature']!r}"
                ),
            }
        template = kwargs["template"]
        depth = int(kwargs.get("depth") or 1)
        hw = _load_hex_world(path)
        if hw is None:
            return {"error": f"No hex-mode autosave at {path}"}
        ok = seed_dungeon_at(
            hw, coord, feature=feature,
            template=template, depth=depth,
        )
        return {
            "coord": {"q": coord.q, "r": coord.r},
            "feature": feature.value,
            "template": template,
            "depth": depth,
            "ok": ok,
        }
