"""M8 cleanup verification tests."""

import importlib

import pytest
import yaml
from pathlib import Path


LOCALE_DIR = Path(__file__).resolve().parents[3] / "nhc" / "i18n" / "locales"


def test_rumors_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("nhc.hexcrawl.rumors")


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
def test_no_rumor_table_text_keys_in_locale(lang: str) -> None:
    """Table text (true_feature, false_lead) moved to YAML tables."""
    path = LOCALE_DIR / f"{lang}.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    rumor_block = data.get("rumor", {})
    assert "true_feature" not in rumor_block, (
        f"{lang}.yaml still has rumor.true_feature"
    )
    assert "false_lead" not in rumor_block, (
        f"{lang}.yaml still has rumor.false_lead"
    )
