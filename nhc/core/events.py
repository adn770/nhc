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
    max_hp: int = 0  # snapshot before entity is destroyed


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
class DoorClosed(Event):
    entity: int = 0
    x: int = 0
    y: int = 0


@dataclass
class TerrainChanged(Event):
    """A terrain-mutating action touched tile ``(x, y)``.

    ``kind`` is a short tag describing the change (``"dug"`` for a
    wall dug through to floor). Used by the sub-hex mutation
    tracker to replay changes on re-entry.
    """
    x: int = 0
    y: int = 0
    kind: str = ""


@dataclass
class LeaveSiteRequested(Event):
    """Player stepped off the edge of a Site surface.

    Emitted by :class:`LeaveSiteAction`; the Game subscribes and
    runs the full off-map-exit path in response. Carrying the
    actor lets a future hook on this event (e.g. companion AI)
    react without pulling the game state in.
    """
    actor: int = 0


@dataclass
class LevelEntered(Event):
    entity: int = 0
    level_id: str = ""
    depth: int = 0
    fell: bool = False  # True when caused by trapdoor (random placement)
    fallen_items: list[str] = field(default_factory=list)


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
    item_id: str = ""  # real item ID (e.g. "potion_healing") for identification


@dataclass
class ItemSold(Event):
    entity: int = 0       # seller
    item_id: str = ""     # registry item ID


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


# --- Visual effects ---

@dataclass
class VisualEffect(Event):
    """Transient visual effect at a tile (rendered by web client)."""
    effect: str = ""
    x: int = 0
    y: int = 0


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


# --- Shop events ---

@dataclass
class ShopMenuEvent(Event):
    """Triggers the shop UI overlay."""
    merchant: int = 0


@dataclass
class HenchmanMenuEvent(Event):
    """Triggers the henchman encounter UI overlay."""
    henchman: int = 0


@dataclass
class TempleMenuEvent(Event):
    """Triggers the temple (priest) services + items menu."""
    priest: int = 0


# --- Overland (hex) events ---

@dataclass
class HexStepEvent(Event):
    """Emitted when an actor moves to an adjacent overland hex.

    ``target`` is a :class:`nhc.hexcrawl.coords.HexCoord`; typed as
    Any here to keep ``nhc.core`` independent of the hex module.
    """
    actor: int = 0
    target: Any = None


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
