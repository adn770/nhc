"""Global test fixtures."""

import pytest

from nhc.i18n import init as i18n_init

# Initialize i18n with English for all tests.
i18n_init("en")


@pytest.fixture(autouse=True)
def _reset_i18n_to_english():
    """Reset i18n to English before every test.

    The i18n module is process-global; tests that flip to ``ca`` or
    ``es`` and forget to restore otherwise leak state across the
    xdist worker, which surfaces as flaky failures in tests that
    assume English (e.g. ``TestLookAction``). Tests that need a
    different locale call :func:`init` explicitly after this
    fixture runs and the change applies for the test body."""
    i18n_init("en")
    yield
