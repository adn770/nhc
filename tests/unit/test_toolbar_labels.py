"""Every toolbar button in the JS client must have a matching
localised tooltip emitted by ``WebClient._ui_labels()``.

The JS toolbar lists (``HEX_TOOLBAR``, ``FLOWER_TOOLBAR``,
``DUNGEON_TOOLBAR`` if any) reference label keys like
``toolbar_flower_enter``. The server's ``_ui_labels()`` dict is
what fills those keys at runtime via ``/labels.json``. When a
key is missing the client falls back to rendering the raw
labelKey string in the browser's title attribute -- the
symptom the user reported on the hexflower toolbar.

This test parses ``nhc/web/static/js/input.js`` for every
``labelKey: "..."`` literal and asserts the server-side
``_ui_labels()`` dict has a matching entry.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nhc.i18n import init as i18n_init
from nhc.rendering.web_client import WebClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_JS = PROJECT_ROOT / "nhc" / "web" / "static" / "js" / "input.js"


def _toolbar_labelkeys() -> set[str]:
    """Parse input.js and return every `labelKey: "..."` literal."""
    text = INPUT_JS.read_text()
    return set(re.findall(r'labelKey:\s*"([^"]+)"', text))


@pytest.fixture(scope="module", autouse=True)
def _i18n() -> None:
    i18n_init("en")


def test_every_toolbar_labelkey_is_served() -> None:
    client = WebClient(style="classic", lang="en")
    labels = client._ui_labels()
    keys = _toolbar_labelkeys()
    assert keys, (
        "no toolbar labelKey entries found in input.js -- parser "
        "regex needs updating"
    )
    missing = sorted(k for k in keys if k not in labels)
    assert not missing, (
        f"{len(missing)} toolbar label key(s) are declared in "
        f"input.js but not served by WebClient._ui_labels(): "
        f"{missing}. The browser falls back to showing the raw "
        "key in the tooltip, which is the hexflower toolbar bug."
    )


def test_served_labels_are_translated_not_raw_keys() -> None:
    """Each toolbar label value must be a non-empty translated
    string, not the raw i18n key. A missing locale entry would
    fall through to the key itself, which still looks like a
    labelId to the user."""
    client = WebClient(style="classic", lang="en")
    labels = client._ui_labels()
    for key in _toolbar_labelkeys():
        if key not in labels:
            continue
        value = labels[key]
        assert value and isinstance(value, str)
        assert not value.startswith("ui."), (
            f"label {key!r} resolved to the raw i18n key "
            f"{value!r}; missing locale entry"
        )
        assert not value.startswith("hex.ui."), (
            f"label {key!r} resolved to the raw i18n key "
            f"{value!r}; missing locale entry"
        )
