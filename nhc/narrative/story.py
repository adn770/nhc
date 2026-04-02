"""Story state tracking and narrative compression.

Maintains a rolling summary of the adventure that fits within the LLM
context window, compressing older narrative every N turns.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nhc.narrative.prompts import load_prompt

if TYPE_CHECKING:
    from nhc.utils.llm import LLMBackend

logger = logging.getLogger(__name__)


class StoryState:
    """Tracks adventure narrative and compresses it periodically."""

    def __init__(self, compress_interval: int = 10) -> None:
        self.summary: str = ""
        self.recent_narrative: list[str] = []
        self.turn_counter: int = 0
        self._compress_interval = compress_interval

    def add_turn(self, narrative: str) -> None:
        """Record a turn's narrative text."""
        if narrative.strip():
            self.recent_narrative.append(narrative)
            self.turn_counter += 1

    @property
    def needs_compression(self) -> bool:
        return self.turn_counter >= self._compress_interval

    async def compress(self, backend: "LLMBackend") -> None:
        """Compress recent narrative into a summary via LLM."""
        if not self.recent_narrative:
            return

        recent = "\n".join(self.recent_narrative)
        prompt = load_prompt("compress", recent_narrative=recent)
        messages = [{"role": "user", "content": prompt}]

        loop = asyncio.get_event_loop()
        new_summary = await loop.run_in_executor(
            None, backend.generate, messages,
        )

        # Append to existing summary
        if self.summary:
            self.summary = f"{self.summary} {new_summary.strip()}"
        else:
            self.summary = new_summary.strip()

        self.recent_narrative.clear()
        self.turn_counter = 0
        logger.info("Story compressed: %s", self.summary[:200])
