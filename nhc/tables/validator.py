"""Cross-language shared-structure drift validator.

Checks that shared_structure tables have identical entry IDs,
weights, and only_if conditions across all language directories.

CLI entry point::

    python -m nhc.tables.validator [--root PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nhc.tables.loader import load_lang
from nhc.tables.types import ValidationError

_LANGS = ("en", "ca", "es")


def validate_all(
    root: Path | None = None,
) -> list[ValidationError]:
    """Load all languages and diff shared-structure tables."""
    if root is None:
        root = Path(__file__).parent / "locales"

    per_lang: dict[str, dict] = {}
    for lang in _LANGS:
        lang_dir = root / lang
        if lang_dir.is_dir():
            per_lang[lang] = load_lang(lang, root=root)

    if len(per_lang) < 2:
        return []

    errors: list[ValidationError] = []
    ref_lang = "en" if "en" in per_lang else next(iter(per_lang))
    ref_tables = per_lang[ref_lang]

    for table_id, ref_table in ref_tables.items():
        if not ref_table.shared_structure:
            continue

        for lang, tables in per_lang.items():
            if lang == ref_lang:
                continue
            if table_id not in tables:
                errors.append(ValidationError(
                    table_id=table_id,
                    kind="missing_table",
                    detail=f"Table '{table_id}' missing in '{lang}'",
                ))
                continue
            errors.extend(_diff_tables(
                ref_table, tables[table_id], ref_lang, lang,
            ))

    return errors


def _diff_tables(
    ref: object, other: object, ref_lang: str, other_lang: str,
) -> list[ValidationError]:
    """Compare two Table objects for structural drift."""
    errors: list[ValidationError] = []
    table_id = ref.id  # type: ignore[union-attr]

    ref_ids = {e.id for e in ref.entries}  # type: ignore[union-attr]
    other_ids = {e.id for e in other.entries}  # type: ignore[union-attr]

    missing_in_other = ref_ids - other_ids
    extra_in_other = other_ids - ref_ids

    for eid in sorted(missing_in_other):
        errors.append(ValidationError(
            table_id=table_id,
            kind="missing_entry",
            detail=(
                f"Entry '{eid}' present in {ref_lang} "
                f"but missing in {other_lang}"
            ),
        ))
    for eid in sorted(extra_in_other):
        errors.append(ValidationError(
            table_id=table_id,
            kind="extra_entry",
            detail=(
                f"Entry '{eid}' present in {other_lang} "
                f"but missing in {ref_lang}"
            ),
        ))

    ref_by_id = {e.id: e for e in ref.entries}  # type: ignore[union-attr]
    other_by_id = {e.id: e for e in other.entries}  # type: ignore[union-attr]

    for eid in sorted(ref_ids & other_ids):
        re = ref_by_id[eid]
        oe = other_by_id[eid]
        if re.weight != oe.weight:
            errors.append(ValidationError(
                table_id=table_id,
                kind="weight_mismatch",
                detail=(
                    f"Entry '{eid}' weight differs: "
                    f"{ref_lang}={re.weight}, {other_lang}={oe.weight}"
                ),
            ))
        if re.only_if != oe.only_if:
            errors.append(ValidationError(
                table_id=table_id,
                kind="only_if_mismatch",
                detail=(
                    f"Entry '{eid}' only_if differs: "
                    f"{ref_lang}={re.only_if}, {other_lang}={oe.only_if}"
                ),
            ))

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate multilingual random tables",
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Root directory containing per-language subdirectories",
    )
    args = parser.parse_args()

    errors = validate_all(root=args.root)
    if not errors:
        print("All tables valid.", file=sys.stderr)
        sys.exit(0)

    for err in errors:
        print(
            f"[{err.kind}] {err.table_id}: {err.detail}",
            file=sys.stderr,
        )
    sys.exit(1)


if __name__ == "__main__":
    main()
