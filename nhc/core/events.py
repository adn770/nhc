"""Event bus for decoupled system communication."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class Event:
    """Base event. All game events inherit from this."""
    turn: int = 0


# --- Combat events ---

@dataclass
class CreatureAttacked(Event):
    attacker: int = 0
    target: int = 0
    roll: int = 0
    damage: int = 0
    hit: bool = False


@dataclass
class CreatureDied(Event):
    entity: int = 0
    killer: int | None = None
    cause: str = ""


# --- Interaction events ---

@dataclass
class ItemPickedUp(Event):
    entity: int = 0
    item: int = 0


@dataclass
class DoorOpened(Event):
    entity: int = 0
    x: int = 0
    y: int = 0


@dataclass
class LevelEntered(Event):
    entity: int = 0
    level_id: str = ""
    depth: int = 0


@dataclass
class SpellCast(Event):
    caster: int = 0
    spell: str = ""
    targets: list[int] = field(default_factory=list)


# --- Item / feature events ---

@dataclass
class ItemUsed(Event):
    entity: int = 0
    item: int = 0
    effect: str = ""


@dataclass
class TrapTriggered(Event):
    entity: int = 0
    damage: int = 0
    trap_name: str = ""


# --- Game state events ---

@dataclass
class PlayerDied(Event):
    cause: str = ""


@dataclass
class GameWon(Event):
    message: str = ""


@dataclass
class MessageEvent(Event):
    text: str = ""
    style: str = "normal"
    actor: int | None = None  # entity that caused the message (for visibility filtering)


# --- Typed gameplay events ---

@dataclass
class CustomActionEvent(Event):
    """Result of a TTRPG-style freeform action."""
    description: str = ""
    ability: str = ""
    roll: int = 0
    bonus: int = 0
    dc: int = 12
    success: bool = False


# Handler type: sync or async callable
EventHandler = Callable[..., None] | Callable[..., Awaitable[None]]


class EventBus:
    """Pub/sub event dispatch.

    Supports both sync and async handlers. Async handlers are awaited
    inline; use emit_background() to fire-and-forget for slow handlers.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = {}

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: EventHandler) -> None:
        """Remove a handler."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event: Event) -> None:
        """Dispatch event to all subscribers (awaits async handlers)."""
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    def emit_fire_and_forget(self, event: Event) -> None:
        """Queue event as background task (for slow handlers like LLM)."""
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
