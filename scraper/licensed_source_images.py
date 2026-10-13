#!/usr/bin/env python3
"""Find original-story images with demonstrable permission for news republication.

A photo's presence in Open Graph or a publisher's article is NOT a licence.
Use images with an explicit compatible image-level licence (ImageObject JSON-LD)
or a separately verified permission entry in image_permissions.json.

CC BY and CC BY-SA require attribution. CC0/public domain is permitted, with a
source credit where available. NC and ND works are excluded from automated use.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from backfill_article_images import (
    DEFAULT_USER_AGENT, MAX_IMAGE_BYTES, Candidate, extension_for,
    extract_candidates, is_http_url, plausible_dimensions, request_bytes,
)


PERMISSIONS_PATH = Path("image_permissions.json")
LICENSES = (
    ("creativecommons.org/publicdomain/zero/", "CC0"),
    ("creativecommons.org/publicdomain/mark/", "Public domain"),
    ("creativecommons.org/licenses/by-sa/", "CC BY-SA"),
    ("creativecommons.org/licenses/by/", "CC BY"),
)


def canonical(value: Any, base: str = "") -> str:
    value = html.unescape(str(value or "").strip())
    if not value:
        return ""
    url = urljoin(base, value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def license_name(url: Any) -> str:
    value = str(url or "").lower()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in {
        "creativecommons.org", "www.creativecommons.org",
    }:
        return ""
    for path, name in LICENSES:
        if path in parsed.netloc + parsed.path.lower():
            return name
    return ""


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("legalName") or value.get("@id"))
    if isinstance(value, list):
        return ", ".join(filter(None, (_text(item) for item in value)))
    return html.unescape(str(value or "").strip())


def _images(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _images(item)
    if isinstance(node, dict):
        typ = node.get("@type")
        types = [str(x).lower() for x in (typ if isinstance(typ, list) else [typ])]
        if any(t in {"imageobject", "photograph"} for t in types):
            yield node
        for value in node.values():
            if isinstance(value, (list, dict)):
                yield from _images(value)


def image_object_rights(page: bytes, page_url: str) -> dict[str, dict[str, str]]:
    """Match an explicit image-level licence to the image URL, never the page's generic copyright."""
    soup = BeautifulSoup(page, "html.parser")
    result: dict[str, dict[str, str]] = {}
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        for node in _images(data):
            license_url = _text(node.get("license")).strip()
            license_label = license_name(license_url)
            if not license_label:
                continue
            author = _text(node.get("creditText") or node.get("creator") or node.get("author") or node.get("copyrightHolder"))
            for key in ("contentUrl", "url", "thumbnailUrl"):
                raw = node.get(key)
                if isinstance(raw, dict):
                    raw = raw.get("@id") or raw.get("url")
                url = canonical(raw, page_url)
                if url:
                    result[url] = {
                        "license_url": license_url,
                        "license_name": license_label,
                        "creator": author,
                        "evidence_url": page_url,
                    }
    return result


def permission_entries(path: Path = PERMISSIONS_PATH) -> dict[str, dict[str, str]]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(entries, list):
        return {}
    rights: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("permission_verified"):
            continue
        url = canonical(entry.get("image_url"))
        evidence = str(entry.get("evidence_url") or "")
        creator = str(entry.get("credit") or "").strip()
        license_url = str(entry.get("license_url") or "")
        kind = str(entry.get("permission_type") or "").lower().strip()
        if not url or not evidence.startswith("https://") or not creator:
            continue
        license_label = license_name(license_url)
        if not license_label and kind != "explicit-publication-permission":
            continue
        rights[url] = {
            "license_url": license_url,
            "license_name": license_label or "Used with permission",
            "creator": creator,
            "evidence_url": evidence,
        }
    return rights


def permitted_candidate(
    url: str,
    page_url: str,
    image_rights: dict[str, dict[str, str]],
    permissions: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    key = canonical(url, page_url)
    if not key:
        return None
    return permissions.get(key) or image_rights.get(key)


def fetch_licensed_source_image(
    source_url: str,
    *,
    permissions: dict[str, dict[str, str]] | None = None,
    timeout: int = 8,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[Candidate, bytes, str, dict[str, str]] | None:
    """Fetch a source's real lead image only where an image-specific licence is recorded."""
    page, content_type, final_url = request_bytes(
        source_url, timeout=timeout, max_bytes=4 * 1024 * 1024,
        accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
        user_agent=user_agent,
    )
    if "html" not in content_type and not page.lstrip().startswith(b"<"):
        return None
    verified = permission_entries() if permissions is None else permissions
    rights_map = image_object_rights(page, final_url)
    for candidate in extract_candidates(page, final_url):
        rights = permitted_candidate(candidate.url, final_url, rights_map, verified)
        if rights is None:
            continue
        try:
            payload, image_type, image_url = request_bytes(
                candidate.url, timeout=timeout, max_bytes=MAX_IMAGE_BYTES,
                accept="image/webp,image/png,image/jpeg,*/*;q=0.1",
                user_agent=user_agent,
            )
        except (OSError, ValueError):
            continue
        ext = extension_for(image_type, image_url, payload)
        if ext and plausible_dimensions(payload, ext):
            return Candidate(image_url, candidate.method), payload, ext, rights
    return None
