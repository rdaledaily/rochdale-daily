#!/usr/bin/env python3
"""Find original-story images with demonstrable permission for news republication.

A photo's presence in Open Graph or a publisher's article is NOT a licence.
Use images with an explicit compatible image-level licence (ImageObject JSON-LD),
a separately verified per-image permission entry in image_permissions.json, or a
verified SOURCE-LEVEL grant in the same file: written permission from an
organisation to republish the photographs it issues with its own stories.

A source grant covers only images served by that organisation on its own
domain, on pages from that domain, and never a photo the page credits to a
picture agency (the organisation cannot grant rights it does not hold).

CC BY and CC BY-SA require attribution. CC0/public domain is permitted, with a
source credit where available. NC and ND works are excluded from automated use.
"""
from __future__ import annotations

import html
import json
import re
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


SOURCE_GRANT_TYPE = "source-publication-permission"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Words in a caption/alt/credit that mean the photo belongs to a picture agency
# or freelance, not to the organisation that granted permission.
AGENCY_RE = re.compile(
    r"\b(getty|alamy|shutterstock|reuters|pa images|pa wire|pa media|press association|"
    r"ap photo|associated press|pinnacle|news images|mercury press|cavendish press|"
    r"istock|adobe stock|dreamstime)\b",
    re.I,
)
# Site furniture that pages expose as og:image when a story has no photo.
CHROME_IMAGE_RE = re.compile(
    r"(logo|favicon|icon|crest|badge|placeholder|default[-_]?(share|og|social|image)|"
    r"social[-_]?(share|card)|og[-_]?default|share[-_]?image|apple-touch)",
    re.I,
)


def bare_host(value: Any) -> str:
    return (urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")


def _host_covered(host: str, allowed: list[str]) -> bool:
    return any(host == item or host.endswith("." + item) for item in allowed)


def source_grants(path: Path = PERMISSIONS_PATH) -> list[dict[str, Any]]:
    """Verified organisation-level grants. An incomplete record grants nothing."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    grants: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("permission_type") != SOURCE_GRANT_TYPE:
            continue
        hosts = [bare_host("https://" + str(h).strip().removeprefix("https://").removeprefix("http://"))
                 for h in entry.get("source_hosts") or [] if str(h).strip()]
        image_hosts = [bare_host("https://" + str(h).strip().removeprefix("https://").removeprefix("http://"))
                       for h in entry.get("image_hosts") or [] if str(h).strip()]
        credit = str(entry.get("credit") or "").strip()
        granted_by = str(entry.get("granted_by") or "").strip()
        granted_on = str(entry.get("granted_on") or "").strip()
        if not (entry.get("permission_verified") is True and hosts and credit
                and granted_by and _DATE_RE.match(granted_on)):
            continue
        grants.append({
            "organisation": str(entry.get("organisation") or credit),
            "source_hosts": hosts,
            "image_hosts": hosts + image_hosts,
            "credit": credit,
            "granted_by": granted_by,
            "granted_on": granted_on,
            "exclude_categories": {str(c).casefold() for c in entry.get("exclude_categories") or []},
        })
    return grants


def inactive_grants(path: Path = PERMISSIONS_PATH) -> list[str]:
    """Names of source-grant records present but not complete enough to use."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    active = {g["organisation"] for g in source_grants(path)}
    return [str(e.get("organisation") or e.get("credit") or "?") for e in entries
            if isinstance(e, dict) and e.get("permission_type") == SOURCE_GRANT_TYPE
            and str(e.get("organisation") or e.get("credit") or "?") not in active]


def grant_for(image_url: Any, page_url: Any, grants: list[dict[str, Any]],
              category: Any = "") -> dict[str, str] | None:
    """Rights for an image under a source grant, or None.

    Both the page AND the image must sit on the granting organisation's own
    hosts, and the image must not be site furniture (logo, default share card).
    """
    page_host, image_host = bare_host(page_url), bare_host(image_url)
    if not page_host or not image_host:
        return None
    if CHROME_IMAGE_RE.search(urlparse(str(image_url)).path):
        return None
    for grant in grants:
        if not _host_covered(page_host, grant["source_hosts"]):
            continue
        if not _host_covered(image_host, grant["image_hosts"]):
            continue
        if str(category or "").casefold() in grant["exclude_categories"]:
            continue
        return {
            "license_url": "",
            "license_name": "Used with permission",
            "creator": grant["credit"],
            "evidence_url": "",
            "evidence_ref": f"Written permission from {grant['granted_by']}, {grant['granted_on']}",
            "grant": grant["organisation"],
        }
    return None


def agency_credited(page: bytes, image_url: str, page_url: str) -> bool:
    """True when the page credits this image (or its only lead image) to an agency."""
    soup = BeautifulSoup(page, "html.parser")
    target = canonical(image_url, page_url)
    texts: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if canonical(src, page_url) == target:
            texts += [img.get("alt") or "", img.get("title") or ""]
            figure = img.find_parent("figure")
            if figure:
                texts.append(figure.get_text(" "))
    for key in ("og:image:alt", "twitter:image:alt"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag:
            texts.append(tag.get("content") or "")
    for node in soup.select("figcaption, .credit, .image-credit, .photo-credit, [class*=caption]")[:6]:
        texts.append(node.get_text(" "))
    return bool(AGENCY_RE.search(" ".join(texts)))


def permitted_candidate(
    url: str,
    page_url: str,
    image_rights: dict[str, dict[str, str]],
    permissions: dict[str, dict[str, str]],
    grants: list[dict[str, Any]] | None = None,
    category: Any = "",
) -> dict[str, str] | None:
    key = canonical(url, page_url)
    if not key:
        return None
    return (permissions.get(key) or image_rights.get(key)
            or (grant_for(key, page_url, grants, category) if grants else None))


def fetch_licensed_source_image(
    source_url: str,
    *,
    permissions: dict[str, dict[str, str]] | None = None,
    grants: list[dict[str, Any]] | None = None,
    category: Any = "",
    skip_urls: set[str] | frozenset[str] = frozenset(),
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
    active_grants = source_grants() if grants is None else grants
    rights_map = image_object_rights(page, final_url)
    for candidate in extract_candidates(page, final_url):
        rights = permitted_candidate(candidate.url, final_url, rights_map, verified,
                                     active_grants, category)
        if rights is None:
            continue
        if rights.get("grant") and canonical(candidate.url, final_url) in skip_urls:
            continue  # the same picture on another story = the site's default image
        if rights.get("grant") and agency_credited(page, candidate.url, final_url):
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
