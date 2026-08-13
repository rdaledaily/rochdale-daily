from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# Rochdale Daily house style: emoji/pictographic characters are never allowed
# in article titles or title metadata.
EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "]",
    re.UNICODE,
)
EMOJI_COMPONENT_RE = re.compile(r"[\U0001F3FB-\U0001F3FF\uFE0F\u200D\u20E3]", re.UNICODE)
TITLE_KEYS = {"title", "headline", "seo_title", "og_title", "twitter_title"}


def clean_title(value: str) -> str:
    text = EMOJI_RE.sub("", value)
    text = EMOJI_COMPONENT_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def clean_json(value: Any, key: str = "") -> tuple[Any, int]:
    changed = 0
    if isinstance(value, dict):
        out = {}
        for item_key, item in value.items():
            cleaned, count = clean_json(item, item_key)
            out[item_key] = cleaned
            changed += count
        return out, changed
    if isinstance(value, list):
        out = []
        for item in value:
            cleaned, count = clean_json(item, key)
            out.append(cleaned)
            changed += count
        return out, changed
    if isinstance(value, str) and key in TITLE_KEYS:
        cleaned = clean_title(value)
        return cleaned, int(cleaned != value)
    return value, 0


def clean_json_file(path: Path, check: bool) -> int:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    cleaned, count = clean_json(payload)
    if count and not check:
        path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return count


def replace_html_titles(raw: str) -> tuple[str, int]:
    count = 0

    def repl_text(match: re.Match[str]) -> str:
        nonlocal count
        old = match.group(2)
        new = clean_title(old)
        if new != old:
            count += 1
        return match.group(1) + new + match.group(3)

    # Browser title and visible article h1.
    raw = re.sub(r"(<title>)(.*?)(</title>)", repl_text, raw, flags=re.I | re.S)
    raw = re.sub(r"(<h1\b[^>]*>)(.*?)(</h1>)", repl_text, raw, flags=re.I | re.S)

    def repl_meta(match: re.Match[str]) -> str:
        nonlocal count
        prefix, value, suffix = match.group(1), match.group(2), match.group(3)
        new = clean_title(value)
        if new != value:
            count += 1
        return prefix + new + suffix

    # OpenGraph/Twitter title metadata, regardless of attribute order used by
    # the current generator.
    patterns = [
        r'(<meta\b[^>]*(?:property|name)=["\'](?:og:title|twitter:title)["\'][^>]*content=["\'])(.*?)(["\'][^>]*>)',
        r'(<meta\b[^>]*content=["\'])(.*?)(["\'][^>]*(?:property|name)=["\'](?:og:title|twitter:title)["\'][^>]*>)',
    ]
    for pattern in patterns:
        raw = re.sub(pattern, repl_meta, raw, flags=re.I | re.S)
    return raw, count


def clean_html_file(path: Path, check: bool) -> int:
    raw = path.read_text(encoding="utf-8")
    cleaned, count = replace_html_titles(raw)
    if count and not check:
        path.write_text(cleaned, encoding="utf-8")
    return count


def targets(root: Path) -> list[Path]:
    paths: set[Path] = set()
    for name in ("articles.json", "manual_articles.json"):
        path = root / name
        if path.exists():
            paths.add(path)
    manual = root / "manual_articles.d"
    if manual.exists():
        paths.update(manual.rglob("*.json"))
    articles = root / "articles"
    if articles.exists():
        paths.update(articles.rglob("*.json"))
        paths.update(articles.glob("*.html"))
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)

    changed_files: list[str] = []
    changes = 0
    for path in targets(root):
        count = clean_json_file(path, args.check) if path.suffix == ".json" else clean_html_file(path, args.check)
        if count:
            changed_files.append(str(path.relative_to(root)))
            changes += count

    print(json.dumps({"title_emoji_changes": changes, "files": changed_files}, indent=2))
    return 1 if args.check and changes else 0


if __name__ == "__main__":
    raise SystemExit(main())
