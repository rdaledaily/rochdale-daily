from __future__ import annotations

# This module is also the permanent publishing guard against visible model artefacts.
import argparse
import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Every string field here can be rendered as reader-facing article copy or
# metadata. Detection and cleaning deliberately share this exact field set so a
# --fix run cannot leave a visible emoji behind and then fail verification on it.
PUBLIC_TEXT_FIELDS = {
    "title", "body", "content", "content_html", "excerpt", "summary",
    "description", "social_context_note", "legal_disclaimer", "right_to_reply",
    "byline", "author", "kicker", "strapline",
    "image_credit", "image_alt", "image_caption", "image_label",
    "source_name", "source_label", "source_note",
}
URL_FIELDS = {
    "source_url", "image_credit_url", "image_url", "url",
}

CITATION_PATTERNS = [
    re.compile(r"\s*\[oai_citation:[^\]]+\]\([^)]*\)", re.I),
    re.compile(r"\s*\[oaicite[^\]]*\]\([^)]*\)", re.I),
    re.compile(r"\s*::contentReference\[[^\]]*\]", re.I),
    re.compile(r"\s*(?:cite|filecite|oaicite)[^]*", re.I),
    re.compile(r"\s*【[^】]*(?:turn\d+|source|citation)[^】]*】", re.I),
    re.compile(r"\s*\[(?:turn\d+\w*\d*|source\s*\d+|citation\s*\d+)\]", re.I),
]

EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "]",
    re.UNICODE,
)
EMOJI_COMPONENT_RE = re.compile(r"[\U0001F3FB-\U0001F3FF\uFE0F\u200D\u20E3]", re.UNICODE)

MODEL_LINK = re.compile(
    r"\s*\[[^\]]*\]\((https?://[^)]*(?:utm_source=chatgpt\.com|chatgpt\.com|openai\.com)[^)]*)\)",
    re.I,
)
MODEL_ANCHOR = re.compile(
    r"\s*<a\b[^>]*href=[\"'][^\"']*(?:utm_source=chatgpt\.com|chatgpt\.com|openai\.com)[^\"']*[\"'][^>]*>.*?</a>",
    re.I | re.S,
)

BAD_SENTENCES = re.compile(
    r"(?:^|(?<=[.!?]))\s*(?:"
    r"as an ai(?: language model)?[^.!?]*[.!?]|"
    r"here (?:is|are) (?:the|your) (?:article|rewrite|json)[^.!?]*[.!?]|"
    r"the source item is titled[^.!?]*[.!?]|"
    r"the update was published by[^.!?]*[.!?]|"
    r"this automated brief[^.!?]*[.!?]|"
    r"readers can use the source link[^.!?]*[.!?]|"
    r"further confirmed information will be added[^.!?]*[.!?]|"
    r"the article remains open to correction[^.!?]*[.!?]|"
    r"this article was generated[^.!?]*[.!?]|"
    r"i (?:cannot|can't) (?:verify|confirm|access|browse)[^.!?]*[.!?]"
    r")",
    re.I,
)

DETECTORS = [
    re.compile(r"oai_citation|oaicite|contentReference|(?:cite|filecite)|utm_source=chatgpt\.com", re.I),
    re.compile(r"as an ai(?: language model)?|this automated brief|the source item is titled|readers can use the source link", re.I),
    EMOJI_RE,
    EMOJI_COMPONENT_RE,
]


def clean_url(value: str) -> str:
    if not value.startswith(("http://", "https://")):
        return value
    try:
        parts = urlsplit(value)
        query = [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except ValueError:
        return value


def clean_text(value: str) -> str:
    text = html.unescape(value)
    text = MODEL_ANCHOR.sub("", text)
    text = MODEL_LINK.sub("", text)
    for pattern in CITATION_PATTERNS:
        text = pattern.sub("", text)
    text = BAD_SENTENCES.sub(" ", text)
    text = EMOJI_RE.sub("", text)
    text = EMOJI_COMPONENT_RE.sub("", text)
    text = re.sub(r"([?&])utm_(?:source|medium|campaign|term|content)=[^&#\s\"')<]+", "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"(?:<p>\s*</p>)+", "", text, flags=re.I)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() if value.strip() else text


def clean_json(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {item_key: clean_json(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item, key) for item in value]
    if isinstance(value, str):
        if key in URL_FIELDS:
            return clean_url(value)
        if key in PUBLIC_TEXT_FIELDS or key == "":
            return clean_text(value)
    return value


def public_text_findings(value: Any, key: str = "") -> list[str]:
    findings: set[str] = set()
    if isinstance(value, dict):
        for item_key, item in value.items():
            findings.update(public_text_findings(item, item_key))
    elif isinstance(value, list):
        for item in value:
            findings.update(public_text_findings(item, key))
    elif isinstance(value, str) and (key in PUBLIC_TEXT_FIELDS or key in URL_FIELDS or key == ""):
        for pattern in DETECTORS:
            if pattern.search(value):
                findings.add(pattern.pattern)
    return sorted(findings)


def has_public_text_violation(value: Any) -> bool:
    return bool(public_text_findings(value))


def public_paths(root: Path) -> list[Path]:
    paths: set[Path] = set()
    for name in ("manual_articles.json", "articles.json"):
        path = root / name
        if path.exists():
            paths.add(path)
    manual_dir = root / "manual_articles.d"
    if manual_dir.exists():
        paths.update(manual_dir.rglob("*.json"))
    article_dir = root / "articles"
    if article_dir.exists():
        paths.update(article_dir.rglob("*.json"))
        paths.update(article_dir.glob("*.html"))
    return sorted(paths)


def process(path: Path, fix: bool) -> tuple[bool, list[str]]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return False, ["invalid JSON"]
        findings = public_text_findings(payload)
        cleaned = json.dumps(clean_json(payload), ensure_ascii=False, indent=2) + "\n"
    else:
        findings = [pattern.pattern for pattern in DETECTORS if pattern.search(raw)]
        cleaned = clean_text(raw)
        if raw.endswith("\n"):
            cleaned += "\n"
    changed = cleaned != raw
    if changed and fix:
        path.write_text(cleaned, encoding="utf-8")
    return changed, findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root)
    changed: list[str] = []
    flagged: list[str] = []
    for path in public_paths(root):
        was_changed, findings = process(path, args.fix)
        relative = str(path.relative_to(root))
        if was_changed:
            changed.append(relative)
        if findings:
            flagged.append(relative)
    print(json.dumps({"changed": changed, "flagged": flagged}, indent=2))
    if not args.fix and (changed or flagged):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
