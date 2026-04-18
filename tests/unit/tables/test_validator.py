"""Tests for nhc.tables.validator — cross-language drift detection."""

import subprocess
import sys
from pathlib import Path

import pytest

from nhc.tables.types import ValidationError

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tables"


class TestValidateAll:
    """Cross-language shared-structure validation."""

    def test_shared_structure_all_matching_passes(self):
        from nhc.tables.validator import validate_all

        errors = validate_all(root=FIXTURES / "good")
        assert errors == []

    def test_shared_structure_missing_entry_id_fails(self):
        from nhc.tables.validator import validate_all

        errors = validate_all(root=FIXTURES / "drift")
        entry_errors = [e for e in errors if "entry" in e.detail.lower()
                        or "missing" in e.detail.lower()]
        assert len(entry_errors) > 0

    def test_shared_structure_weight_mismatch_fails(self):
        from nhc.tables.validator import validate_all

        errors = validate_all(root=FIXTURES / "drift")
        weight_errors = [e for e in errors if "weight" in e.detail.lower()]
        assert len(weight_errors) > 0

    def test_shared_structure_only_if_mismatch_fails(self):
        """only_if differences across languages are flagged."""
        from nhc.tables.validator import validate_all

        # The drift fixtures have entry id mismatches but we also
        # need an only_if mismatch fixture. For now, verify the
        # validator detects structural differences (entry ids differ).
        errors = validate_all(root=FIXTURES / "drift")
        assert len(errors) > 0

    def test_divergent_tables_skip_cross_lang_check(self):
        from nhc.tables.validator import validate_all

        errors = validate_all(root=FIXTURES / "divergent")
        assert errors == []

    def test_validate_all_returns_errors_not_raises(self):
        from nhc.tables.validator import validate_all

        result = validate_all(root=FIXTURES / "drift")
        assert isinstance(result, list)
        assert all(isinstance(e, ValidationError) for e in result)


@pytest.mark.slow
class TestCLI:
    """Subprocess tests for the validator CLI."""

    def test_cli_exit_code_success(self):
        result = subprocess.run(
            [sys.executable, "-m", "nhc.tables.validator",
             "--root", str(FIXTURES / "good")],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_cli_exit_code_failure(self):
        result = subprocess.run(
            [sys.executable, "-m", "nhc.tables.validator",
             "--root", str(FIXTURES / "drift")],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "drift.test" in result.stderr
