"""JSON action plan parser for LLM responses.

Extracts and validates the JSON action array returned by the interpret
phase, converting it to a list of Action objects.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)

# Direction name → (dx, dy)
DIRECTIONS: dict[str, tuple[int, int]] = {
    "north": (0, -1), "south": (0, 1),
    "east": (1, 0), "west": (-1, 0),
    "ne": (1, -1), "nw": (-1, -1),
    "se": (1, 1), "sw": (-1, 1),
}

# Valid action types
VALID_ACTIONS = {
    "move", "attack", "pickup", "use_item", "wait", "look", "search",
    "talk", "descend", "open_door", "custom", "impossible", "narrative",
}


def extract_json(text: str) -> str | None:
    """Extract a JSON array from LLM output, handling markdown fences."""
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    # Find first [ ... ] block
    start = text.find("[")
    if start == -1:
        # Try single object
        start = text.find("{")
        if start == -1:
            return None
        end = text.rfind("}") + 1
        if end <= start:
            return None
        return "[" + text[start:end] + "]"

    end = text.rfind("]") + 1
    if end <= start:
        return None
    return text[start:end]


def parse_action_plan(text: str) -> list[dict[str, Any]]:
    """Parse LLM response into a validated action plan.

    Returns a list of action dicts.  On any parse error, returns
    a single wait action.
    """
    json_str = extract_json(text)
    if not json_str:
        logger.warning("No JSON found in LLM response: %s", text[:200])
        return [{"action": "wait"}]

    try:
        plan = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse error: %s — %s", e, json_str[:200])
        return [{"action": "wait"}]

    if isinstance(plan, dict):
        plan = [plan]
    if not isinstance(plan, list):
        return [{"action": "wait"}]

    # Validate each action
    validated: list[dict[str, Any]] = []
    for item in plan[:3]:  # Max 3 actions per turn
        if not isinstance(item, dict):
            continue
        action = item.get("action", "")
        if action not in VALID_ACTIONS:
            continue
        validated.append(item)

    return validated or [{"action": "wait"}]


def action_plan_to_actions(
    plan: list[dict[str, Any]],
    actor: int,
    world: "World",
    level: "Level",
) -> list:
    """Convert parsed action dicts to Action objects."""
    from nhc.core.actions import (
        BumpAction,
        CustomAction,
        DescendStairsAction,
        ImpossibleAction,
        LookAction,
        MeleeAttackAction,
        PickupItemAction,
        UseItemAction,
        WaitAction,
    )

    actions = []
    pos = world.get_component(actor, "Position")

    for item in plan:
        action_type = item.get("action", "wait")

        if action_type == "move":
            direction = item.get("direction", "")
            dx, dy = DIRECTIONS.get(direction, (0, 0))
            if dx or dy:
                actions.append(BumpAction(actor, dx, dy))

        elif action_type == "attack":
            target = item.get("target")
            if target is not None:
                actions.append(MeleeAttackAction(actor, int(target)))

        elif action_type == "pickup":
            item_id = item.get("item")
            if item_id is not None:
                actions.append(PickupItemAction(actor, int(item_id)))

        elif action_type == "use_item":
            item_id = item.get("item")
            if item_id is not None:
                actions.append(UseItemAction(actor, int(item_id)))

        elif action_type == "descend":
            actions.append(DescendStairsAction(actor))

        elif action_type == "look":
            actions.append(LookAction(actor))

        elif action_type == "search":
            from nhc.core.actions import SearchAction
            actions.append(SearchAction(actor))

        elif action_type == "wait":
            actions.append(WaitAction(actor))

        elif action_type == "custom":
            desc = item.get("description", "")
            check = item.get("check", {})
            ability = check.get("ability", "wisdom")
            dc = check.get("dc", 12)
            actions.append(CustomAction(
                actor, description=desc, ability=ability, dc=dc,
            ))

        elif action_type == "narrative":
            # GM wants to emit a narrative message (no mechanical effect)
            text = item.get("text", "")
            if text:
                actions.append(ImpossibleAction(actor, reason=text))

        elif action_type == "impossible":
            reason = item.get("reason", "That's not possible right now.")
            actions.append(ImpossibleAction(actor, reason=reason))

    return actions or [WaitAction(actor)]
