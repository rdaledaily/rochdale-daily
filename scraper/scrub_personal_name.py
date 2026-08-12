#!/usr/bin/env python3
"""Remove a private personal byline/name from the published repository tree.

This deliberately targets the exact full name only. It replaces public-facing
occurrences with the house byline so generated pages, feeds and static fallbacks
cannot re-publish the personal name.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "Sarah Pickles"
REPLACEMENT = "Rochdale Daily"
TEXT_SUFFIXES = {
    ".html", ".json", ".md", ".txt", ".yml", ".yaml", ".py", ".js", ".css", ".xml"
}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}


def main() -> int:
    changed: list[str] = []
    remaining: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if TARGET not in text:
            continue
        path.write_text(text.replace(TARGET, REPLACEMENT), encoding="utf-8")
        changed.append(path.relative_to(ROOT).as_posix())

    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            if TARGET in path.read_text(encoding="utf-8"):
                remaining.append(path.relative_to(ROOT).as_posix())
        except (UnicodeDecodeError, OSError):
            continue

    print(f"Scrubbed {len(changed)} files")
    for item in changed:
        print(f"  - {item}")
    if remaining:
        raise SystemExit(f"Personal name still present in: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
