"""Tiny translation layer.

Source strings are English. Each other language is one JSON file in
pangolin_gui/locales/<code>.json:

    {"name": "Deutsch", "strings": {"Connect": "Verbinden", ...}}

Adding a language = adding a file. Missing entries fall back to English.

Usage:
    from pangolin_gui.i18n import _, N_
    label = _("Connect")
    text = _("Version {version}").format(version=v)   # never translate f-strings
    LABELS = [N_("Site")]  # mark module-level constants, translate with _() at use time
"""
from __future__ import annotations

import json
import locale
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

LOCALE_DIR = Path(__file__).resolve().parent / "locales"
SOURCE_LANGUAGE = "en"
SYSTEM = "system"

_catalog: dict[str, str] = {}
_current = SOURCE_LANGUAGE


def available_languages() -> dict[str, str]:
    """Language code -> native name, English first."""
    langs = {SOURCE_LANGUAGE: "English"}
    for path in sorted(LOCALE_DIR.glob("*.json")):
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name") or path.stem
        except (OSError, ValueError):
            log.warning("ignoring broken locale file %s", path)
            continue
        langs[path.stem] = name
    return langs


def system_language() -> str:
    """Best match for the desktop locale among the available languages."""
    candidates = []
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            candidates.extend(value.split(":"))  # LANGUAGE may list several
    try:
        loc = locale.getlocale(locale.LC_MESSAGES)[0]
        if loc:
            candidates.append(loc)
    except (AttributeError, ValueError):
        pass
    available = available_languages()
    for cand in candidates:
        code = cand.split(".")[0].split("@")[0]       # de_DE.UTF-8 -> de_DE
        for key in (code, code.split("_")[0]):        # de_DE, then de
            if key in available:
                return key
    return SOURCE_LANGUAGE


def resolve(code: str | None) -> str:
    if not code or code == SYSTEM:
        return system_language()
    return code if code in available_languages() else SOURCE_LANGUAGE


def set_language(code: str | None) -> str:
    """Activate a language ("system", "en", "de", ...). Returns the resolved code."""
    global _catalog, _current
    resolved = resolve(code)
    catalog: dict[str, str] = {}
    if resolved != SOURCE_LANGUAGE:
        try:
            data = json.loads((LOCALE_DIR / f"{resolved}.json").read_text(encoding="utf-8"))
            catalog = {k: v for k, v in (data.get("strings") or {}).items() if isinstance(v, str) and v}
        except (OSError, ValueError) as exc:
            log.warning("cannot load language %s: %s", resolved, exc)
            resolved = SOURCE_LANGUAGE
    _catalog, _current = catalog, resolved
    return resolved


def current_language() -> str:
    return _current


def _(text: str) -> str:
    return _catalog.get(text, text)


def N_(text: str) -> str:
    """Mark a string for translation without translating it now."""
    return text
