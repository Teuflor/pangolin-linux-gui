import importlib.util
import json
from pathlib import Path

import pytest

from pangolin_gui import i18n
from pangolin_gui.i18n import _

ROOT = Path(__file__).resolve().parent.parent


def load_checker():
    spec = importlib.util.spec_from_file_location("i18n_check", ROOT / "tools" / "i18n_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def reset_language():
    yield
    i18n.set_language("en")


def test_available_languages():
    langs = i18n.available_languages()
    assert langs["en"] == "English"
    assert langs["de"] == "Deutsch"


@pytest.mark.parametrize("path", sorted((ROOT / "pangolin_gui" / "locales").glob("*.json")), ids=lambda p: p.stem)
def test_locale_complete_and_placeholders_match(path):
    checker = load_checker()
    keys = checker.source_strings()
    assert len(keys) > 100
    strings = json.loads(path.read_text(encoding="utf-8"))["strings"]
    missing = [k for k in keys if not strings.get(k)]
    assert missing == [], f"untranslated in {path.name}: {missing}"
    for key in keys:
        assert checker.placeholders(key) == checker.placeholders(strings[key]), key


def test_switch_language_and_fallback():
    assert i18n.set_language("de") == "de"
    assert _("Connect") == "Verbinden"
    assert _("{seconds} s ago").format(seconds=5) == "vor 5 s"
    assert _("A string nobody translated") == "A string nobody translated"
    assert i18n.set_language("en") == "en"
    assert _("Connect") == "Connect"
    assert i18n.set_language("xx") == "en"  # unknown -> English


@pytest.mark.parametrize("env,expected", [
    ({"LANG": "de_DE.UTF-8"}, "de"),
    ({"LANGUAGE": "fr:de", "LANG": "fr_FR.UTF-8"}, "de"),
    ({"LANG": "fr_FR.UTF-8"}, "en"),
    ({"LANG": "C"}, "en"),
])
def test_system_language(monkeypatch, env, expected):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *_a: (None, None))
    assert i18n.set_language("system") == expected


def test_translated_widgets_use_runtime_language():
    # format_relative lives in a GTK-free helper; translation must apply at call time
    from pangolin_gui.tray import get_status_label
    from pangolin_gui.models import AppState, ConnState
    i18n.set_language("de")
    assert get_status_label(AppState(conn=ConnState.CONNECTED)) == "Verbunden"
    i18n.set_language("en")
    assert get_status_label(AppState(conn=ConnState.CONNECTED)) == "Connected"
