"""Core data types for the random tables subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["flavor", "parameterized", "composed", "structured"]
VALID_KINDS: set[str] = {"flavor", "parameterized", "composed", "structured"}

Lifetime = Literal["gen_time", "ephemeral"]
VALID_LIFETIMES: set[str] = {"gen_time", "ephemeral"}


@dataclass(frozen=True)
class TableEntry:
    id: str
    text: str
    weight: int = 1
    only_if: dict = field(default_factory=dict)
    effect: dict | None = None
    forms: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Table:
    id: str
    kind: Kind
    lifetime: Lifetime
    shared_structure: bool
    entries: list[TableEntry]
    only_if: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TableEffect:
    """An effect attached to a table entry."""
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TableResult:
    """Result of rolling or rendering a table entry."""
    text: str
    entry_id: str
    effect: TableEffect | None = None


class SchemaError(Exception):
    """Raised when a table YAML file has an invalid schema."""


@dataclass(frozen=True)
class ValidationError:
    """A single cross-language validation issue."""
    table_id: str
    kind: str
    detail: str
