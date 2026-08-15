#!/usr/bin/env python3
"""Remove the editor's private personal name from the published repository tree.

The target is assembled from fragments deliberately. The original implementation
stored the target as one literal string, then scanned and rewrote this script too;
a successful run therefore changed its own TARGET to the replacement byline and
made every later run try to replace ``Rochdale Daily`` with itself. That caused
thousands of no-op rewrites and permanent workflow failure.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Keep the private name out of this source file as a contiguous string so the
# scrubber can safely scan its own public repository without corrupting itself.
NAME_PARTS = ("Sarah", "Pickles")
TARGET = " ".join(NAME_PARTS)
LONG_TARGET = " ".join((NAME_PARTS[0], "Jane", NAME_PARTS[1]))
REPLACEMENT = "Rochdale Daily"
TARGETS = (LONG_TARGET, TARGET)  # longest first avoids leaving a middle name
TEXT_SUFFIXES = {
    ".html", ".json", ".md", ".txt", ".yml", ".yaml", ".py", ".js", ".css", ".xml"
}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def main() -> int:
    changed: list[str] = []
    remaining: list[str] = []

    for path in iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        cleaned = text
        for target in TARGETS:
            cleaned = cleaned.replace(target, REPLACEMENT)
        if cleaned == text:
            continue
        path.write_text(cleaned, encoding="utf-8")
        changed.append(path.relative_to(ROOT).as_posix())

    for path in iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(target in text for target in TARGETS):
            remaining.append(path.relative_to(ROOT).as_posix())

    print(f"Scrubbed {len(changed)} files")
    for item in changed:
        print(f"  - {item}")
    if remaining:
        raise SystemExit(f"Personal name still present in: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
