#!/usr/bin/env python3
"""Collect translatable strings and check locale files.

    python3 tools/i18n_check.py              # report missing/obsolete keys per language
    python3 tools/i18n_check.py --keys       # print all source strings as JSON
    python3 tools/i18n_check.py --update     # add missing keys (empty) and drop obsolete ones

A string is translatable when it is a literal argument of _() or N_().
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pangolin_gui"
LOCALES = PACKAGE / "locales"
PLACEHOLDER = re.compile(r"\{(\w*)\}")


def source_strings() -> list[str]:
    keys: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("_", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return sorted(keys, key=str.lower)


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text))


def check(update: bool = False) -> int:
    keys = source_strings()
    problems = 0
    for path in sorted(LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        strings: dict = data.setdefault("strings", {})
        missing = [k for k in keys if not strings.get(k)]
        obsolete = [k for k in strings if k not in keys]
        bad = [k for k in keys if strings.get(k) and placeholders(k) != placeholders(strings[k])]
        print(f"{path.name}: {len(keys) - len(missing)}/{len(keys)} translated, "
              f"{len(missing)} missing, {len(obsolete)} obsolete, {len(bad)} placeholder errors")
        for k in missing:
            print(f"  missing:     {k!r}")
        for k in bad:
            print(f"  placeholder: {k!r} -> {strings[k]!r}")
        problems += len(missing) + len(bad)
        if update:
            data["strings"] = {k: strings.get(k, "") for k in keys}
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    if args.keys:
        json.dump(source_strings(), sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    return check(update=args.update)


if __name__ == "__main__":
    sys.exit(main())
