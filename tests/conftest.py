"""Global test fixtures."""

import pytest

from nhc.i18n import init as i18n_init

# Initialize i18n with English for all tests.
i18n_init("en")


def pytest_collection_modifyitems(config, items):
    """Auto-skip ``perf``-marked tests unless ``-m perf`` is given.

    The project has no ``addopts`` deselect, so a bare ``pytest`` /
    full ``--dist worksteal`` run would otherwise collect the
    opt-in WASM perf benches (Phase M). They need a browser + a
    fresh wasm bundle and are reporting-only, so they must never
    ride along in routine correctness runs. Passing ``-m perf``
    (or any marker expression naming ``perf``) opts back in.
    """
    markexpr = config.getoption("-m", default="")
    if "perf" in markexpr:
        return
    skip_perf = pytest.mark.skip(reason="perf bench — run with `-m perf`")
    for item in items:
        if "perf" in item.keywords:
            item.add_marker(skip_perf)


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
