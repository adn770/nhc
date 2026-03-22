"""Game Master — orchestrates the interpret → resolve → narrate pipeline.

The GameMaster translates natural-language player intents into ECS
actions and then narrates the mechanical outcomes as prose, all using
the active game language.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Generator

from nhc.narrative.context import ContextBuilder
from nhc.narrative.parser import action_plan_to_actions, parse_action_plan
from nhc.narrative.prompts import load_prompt

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.llm import LLMBackend

logger = logging.getLogger(__name__)


class GameMaster:
    """Orchestrates the LLM-driven typed gameplay pipeline."""

    def __init__(
        self,
        backend: "LLMBackend",
        context_builder: ContextBuilder,
    ) -> None:
        self.backend = backend
        self.ctx = context_builder
        self.story_summary: str = ""
        self._recent_narrative: list[str] = []
        self._turn_counter: int = 0

    async def interpret(
        self,
        intent: str,
        game_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Interpret a player's typed intent into a JSON action plan."""
        system = load_prompt("interpret")
        user_msg = json.dumps({
            "player_intent": intent,
            "game_state": game_state,
        }, ensure_ascii=False)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, self.backend.generate, messages,
        )

        logger.info("GM interpret response: %s", response[:500])
        return parse_action_plan(response)

    async def follow_up(
        self,
        intent: str,
        outcomes: list[dict[str, Any]],
        game_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Ask the GM what happens next after custom action results.

        Sends the ability check outcomes back to the LLM so it can
        decide follow-up mechanical actions (e.g. move past the trap
        on success, or trigger the trap on failure).
        """
        system = load_prompt("follow_up")
        user_msg = json.dumps({
            "original_intent": intent,
            "check_results": outcomes,
            "game_state": game_state,
        }, ensure_ascii=False)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, self.backend.generate, messages,
        )

        logger.info("GM follow_up response: %s", response[:500])
        return parse_action_plan(response)

    async def narrate(
        self,
        intent: str,
        outcomes: list[dict[str, Any]],
        char_name: str = "",
        char_background: str = "",
        char_virtue: str = "",
        char_vice: str = "",
        ambient: str = "",
    ) -> str:
        """Narrate the mechanical outcomes as prose."""
        system = load_prompt(
            "narrate",
            name=char_name,
            background=char_background,
            virtue=char_virtue,
            vice=char_vice,
        )
        user_msg = json.dumps({
            "intent": intent,
            "outcomes": outcomes,
            "story_so_far": self.story_summary,
            "ambient": ambient,
        }, ensure_ascii=False)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        loop = asyncio.get_event_loop()
        narrative = await loop.run_in_executor(
            None, self.backend.generate, messages,
        )

        # Track for story compression
        self._recent_narrative.append(narrative)
        self._turn_counter += 1
        if self._turn_counter >= 10:
            await self._compress_story()

        return narrative

    async def narrate_creatures(
        self,
        creature_actions: list[dict[str, Any]],
    ) -> str:
        """Briefly narrate creature actions."""
        if not creature_actions:
            return ""

        system = load_prompt(
            "creature_phase",
            creature_actions=json.dumps(
                creature_actions, ensure_ascii=False,
            ),
        )
        messages = [{"role": "user", "content": system}]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.backend.generate, messages,
        )

    async def intro(
        self,
        char_name: str,
        char_background: str,
        char_virtue: str,
        char_vice: str,
        char_alignment: str,
        level_name: str,
        ambient: str,
        hooks: str,
    ) -> str:
        """Generate the opening narration for a new game."""
        system = load_prompt(
            "intro",
            name=char_name,
            background=char_background,
            virtue=char_virtue,
            vice=char_vice,
            alignment=char_alignment,
            level_name=level_name,
            ambient=ambient,
            hooks=hooks,
        )
        messages = [{"role": "user", "content": system}]

        loop = asyncio.get_event_loop()
        narrative = await loop.run_in_executor(
            None, self.backend.generate, messages,
        )
        self._recent_narrative.append(narrative)
        return narrative

    async def _compress_story(self) -> None:
        """Compress recent narrative into a summary."""
        if not self._recent_narrative:
            return

        recent = "\n".join(self._recent_narrative)
        system = load_prompt("compress", recent_narrative=recent)
        messages = [{"role": "user", "content": system}]

        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(
            None, self.backend.generate, messages,
        )

        self.story_summary = summary.strip()
        self._recent_narrative.clear()
        self._turn_counter = 0
        logger.info("Story compressed: %s", self.story_summary[:200])
