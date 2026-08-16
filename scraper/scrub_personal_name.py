#!/usr/bin/env python3
"""Remove the editor's private name from byline/author metadata only.

This deliberately does NOT scan or rewrite article prose, HTML, Python, CSS or
other repository text. A person with the same name could legitimately appear in
a news story; privacy protection must never silently alter journalism.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NAME_PARTS = ("Sarah", "Pickles")
TARGET = " ".join(NAME_PARTS)
LONG_TARGET = " ".join((NAME_PARTS[0], "Jane", NAME_PARTS[1]))
REPLACEMENT = "Rochdale Daily"
TARGETS = (LONG_TARGET, TARGET)
PRIVATE_METADATA_KEYS = {
    "byline",
    "byline_name",
    "author",
    "author_name",
    "editor",
    "editor_name",
}
SOURCE_FILES = (
    ROOT / "articles.json",
    ROOT / "manual_articles.json",
)


def _clean_metadata(value: Any, *, key: str = "") -> tuple[Any, int]:
    changed = 0
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            if child_key in PRIVATE_METADATA_KEYS and isinstance(child_value, str):
                cleaned = child_value
                for target in TARGETS:
                    cleaned = cleaned.replace(target, REPLACEMENT)
                changed += int(cleaned != child_value)
                result[child_key] = cleaned
            else:
                result[child_key], child_changed = _clean_metadata(child_value, key=child_key)
                changed += child_changed
        return result, changed
    if isinstance(value, list):
        result = []
        for item in value:
            cleaned, child_changed = _clean_metadata(item, key=key)
            result.append(cleaned)
            changed += child_changed
        return result, changed
    return value, 0


def _contains_private_metadata(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in PRIVATE_METADATA_KEYS and isinstance(child, str):
                if any(target in child for target in TARGETS):
                    return True
            if _contains_private_metadata(child):
                return True
    elif isinstance(value, list):
        return any(_contains_private_metadata(item) for item in value)
    return False


def _paths() -> list[Path]:
    paths = [path for path in SOURCE_FILES if path.is_file()]
    manual_dir = ROOT / "manual_articles.d"
    if manual_dir.is_dir():
        paths.extend(sorted(manual_dir.glob("*.json")))
    return paths


def main() -> int:
    changed_files: list[str] = []
    remaining: list[str] = []

    for path in _paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Could not parse {path.relative_to(ROOT)}: {exc}")
        cleaned, changes = _clean_metadata(payload)
        if changes:
            path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed_files.append(path.relative_to(ROOT).as_posix())
        if _contains_private_metadata(cleaned):
            remaining.append(path.relative_to(ROOT).as_posix())

    print(f"Scoped privacy scrub changed {len(changed_files)} source file(s).")
    for item in changed_files:
        print(f"  - {item}")
    if remaining:
        raise SystemExit(f"Private byline metadata still present in: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
