"""Real-content validator — scans nhc/tables/locales/."""

from pathlib import Path

import pytest

LOCALES = Path(__file__).resolve().parents[3] / "nhc" / "tables" / "locales"


@pytest.mark.validator
def test_real_tables_pass_validation():
    from nhc.tables.validator import validate_all

    errors = validate_all(root=LOCALES)
    assert errors == [], "\n".join(e.detail for e in errors)
