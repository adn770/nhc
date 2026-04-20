"""YAML loader for random tables."""

from __future__ import annotations

from pathlib import Path

import yaml

from nhc.tables.types import (
    VALID_KINDS,
    VALID_LIFETIMES,
    SchemaError,
    Table,
    TableEntry,
)

_REQUIRED_TABLE_FIELDS = ("id", "kind", "lifetime")
_REQUIRED_ENTRY_FIELDS = ("id", "text")


def _validate_text(raw, entry_id: str, path: Path) -> str | list[str]:
    """Normalize and validate an entry's text field.

    Accepts a single string or a non-empty list of strings. Rejects
    empty lists and lists containing non-string values.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        if not raw:
            raise SchemaError(
                f"{path}: entry '{entry_id}' has empty list text"
            )
        for v in raw:
            if not isinstance(v, str):
                raise SchemaError(
                    f"{path}: entry '{entry_id}' list text must "
                    f"contain only strings; got {type(v).__name__}"
                )
        return list(raw)
    raise SchemaError(
        f"{path}: entry '{entry_id}' text must be a string or list "
        f"of strings; got {type(raw).__name__}"
    )


def load_table_file(path: Path) -> list[Table]:
    """Load all YAML documents from *path* and return Table objects."""
    with open(path) as f:
        docs = list(yaml.safe_load_all(f))

    tables: list[Table] = []
    for doc in docs:
        if doc is None:
            continue
        tables.append(_parse_table(doc, path))
    return tables


def _parse_table(doc: dict, path: Path) -> Table:
    for field in _REQUIRED_TABLE_FIELDS:
        if field not in doc:
            raise SchemaError(
                f"{path}: missing required field '{field}'"
            )

    kind = doc["kind"]
    if kind not in VALID_KINDS:
        raise SchemaError(
            f"{path}: invalid kind '{kind}'; "
            f"expected one of {sorted(VALID_KINDS)}"
        )

    lifetime = doc["lifetime"]
    if lifetime not in VALID_LIFETIMES:
        raise SchemaError(
            f"{path}: invalid lifetime '{lifetime}'; "
            f"expected one of {sorted(VALID_LIFETIMES)}"
        )

    raw_entries = doc.get("entries", [])
    entries: list[TableEntry] = []
    for raw in raw_entries:
        for ef in _REQUIRED_ENTRY_FIELDS:
            if ef not in raw:
                raise SchemaError(
                    f"{path}: entry missing required field '{ef}'"
                )
        entries.append(TableEntry(
            id=raw["id"],
            text=_validate_text(raw["text"], raw["id"], path),
            weight=raw.get("weight", 1),
            only_if=raw.get("only_if", {}),
            effect=raw.get("effect"),
            forms=raw.get("forms", {}),
            tags=raw.get("tags", []),
        ))

    return Table(
        id=doc["id"],
        kind=kind,
        lifetime=lifetime,
        shared_structure=doc.get("shared_structure", True),
        entries=entries,
        only_if=doc.get("only_if", {}),
    )


def load_lang(lang: str, root: Path | None = None) -> dict[str, Table]:
    """Load all tables for a language, returning {table_id: Table}."""
    if root is None:
        root = Path(__file__).parent / "locales"

    lang_dir = root / lang
    if not lang_dir.is_dir():
        return {}

    tables: dict[str, Table] = {}
    for yaml_file in sorted(lang_dir.glob("*.yaml")):
        for table in load_table_file(yaml_file):
            tables[table.id] = table
    return tables
