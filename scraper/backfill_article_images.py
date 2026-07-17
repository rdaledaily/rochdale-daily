#!/usr/bin/env python3
"""Backfill original-source images for archived Rochdale Daily stories.

The script is deliberately conservative:

* It never changes story identity, title, body, status or timestamps.
* It skips records that already have a non-placeholder image.
* It extracts only publisher-declared lead images (Open Graph, Twitter card,
  schema.org JSON-LD or a prominent article image).
* It caches accepted images under assets/article-images/.
* It records the original candidate URL, local cached path, source credit and
  credit link.
* It defaults to dry-run. Use --apply to write files and articles.json.
* Existing files are never overwritten with different bytes.

Attribution is not a substitute for permission. The generated
source_image_reuse_status value is "source-attributed-review-required" unless
the record already contains a stronger reuse status.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit(
        "BeautifulSoup is required. Add beautifulsoup4 to requirements.txt."
    ) from exc


DEFAULT_USER_AGENT = (
    "RochdaleDailyImageBackfill/1.0 "
    "(news archive maintenance; contact: news@rochdaledaily.co.uk)"
)
PLACEHOLDER_RE = re.compile(
    r"(?:^|/)(?:stock_|placeholder|default[-_]?image|category[-_]?image)",
    re.IGNORECASE,
)
DISALLOWED_IMAGE_HINTS = (
    "logo", "icon", "avatar", "sprite", "favicon", "tracking", "pixel",
    "badge", "advert", "banner-ad", "spacer",
)
SUPPORTED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MIN_IMAGE_BYTES = 8 * 1024


@dataclass(frozen=True)
class Candidate:
    url: str
    method: str


@dataclass
class Stats:
    total: int = 0
    eligible: int = 0
    updated: int = 0
    already_has_image: int = 0
    no_source: int = 0
    no_candidate: int = 0
    fetch_failed: int = 0
    skipped_social: int = 0


def clean(value: Any) -> str:
    return str(value or "").strip()


def is_http_url(value: Any) -> bool:
    text = clean(value)
    return text.startswith("https://") or text.startswith("http://")


def is_placeholder_image(article: dict[str, Any]) -> bool:
    image = clean(article.get("image_url"))
    credit = clean(article.get("image_credit")).lower()
    if not image:
        return True
    if PLACEHOLDER_RE.search(image):
        return True
    if "category image" in credit or "placeholder" in credit:
        return True
    return False


def source_urls(article: dict[str, Any]) -> list[str]:
    values: list[str] = []
    primary = clean(article.get("source_url"))
    if is_http_url(primary):
        values.append(primary)
    for value in article.get("source_urls") or []:
        value = clean(value)
        if is_http_url(value) and value not in values:
            values.append(value)
    return values


def source_name_for(article: dict[str, Any], source_url: str) -> str:
    primary_url = clean(article.get("source_url"))
    primary_name = clean(article.get("source_name"))
    if primary_name and source_url == primary_url:
        return primary_name

    urls = [clean(v) for v in article.get("source_urls") or []]
    names = [clean(v) for v in article.get("source_names") or []]
    try:
        index = urls.index(source_url)
    except ValueError:
        index = -1
    if 0 <= index < len(names) and names[index]:
        return names[index]

    host = urlparse(source_url).netloc.lower().removeprefix("www.")
    return host or "Original source"


def is_social_or_search_url(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return (
        host in {
            "news.google.com", "google.com", "facebook.com", "m.facebook.com",
            "x.com", "twitter.com", "tiktok.com", "instagram.com",
        }
        or host.endswith(".facebook.com")
        or host.endswith(".instagram.com")
        or host.endswith(".tiktok.com")
    )


def request_bytes(
    url: str,
    *,
    timeout: int,
    max_bytes: int,
    accept: str,
    user_agent: str,
) -> tuple[bytes, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": accept,
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    opener = build_opener()
    with opener.open(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type().lower()
        final_url = response.geturl()
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} bytes")

        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = response.read(min(64 * 1024, max_bytes - received + 1))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if received > max_bytes:
                raise ValueError(f"response exceeds {max_bytes} bytes")
        return b"".join(chunks), content_type, final_url


def meta_content(soup: BeautifulSoup, *, prop: str = "", name: str = "") -> str:
    if prop:
        node = soup.find(
            "meta",
            attrs={"property": re.compile(rf"^{re.escape(prop)}$", re.I)},
        )
    else:
        node = soup.find(
            "meta",
            attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)},
        )
    return clean(node.get("content")) if node else ""


def json_ld_image_candidates(soup: BeautifulSoup, base_url: str) -> list[Candidate]:
    found: list[Candidate] = []
    for node in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = node.string or node.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        stack = value if isinstance(value, list) else [value]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            image = item.get("image")
            urls: list[str] = []
            if isinstance(image, str):
                urls.append(image)
            elif isinstance(image, list):
                for entry in image:
                    if isinstance(entry, str):
                        urls.append(entry)
                    elif isinstance(entry, dict):
                        urls.append(clean(entry.get("url") or entry.get("contentUrl")))
            elif isinstance(image, dict):
                urls.append(clean(image.get("url") or image.get("contentUrl")))
            for url in urls:
                if url:
                    found.append(
                        Candidate(urljoin(base_url, html.unescape(url)), "json-ld")
                    )
    return found


def srcset_largest(srcset: str) -> str:
    best_url = ""
    best_width = -1
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        width = 0
        if len(parts) > 1 and parts[-1].endswith("w"):
            try:
                width = int(parts[-1][:-1])
            except ValueError:
                width = 0
        if width >= best_width:
            best_url = parts[0]
            best_width = width
    return best_url


def extract_candidates(page_html: bytes, page_url: str) -> list[Candidate]:
    soup = BeautifulSoup(page_html, "html.parser")
    candidates: list[Candidate] = []

    ordered_meta = (
        ("prop", "og:image:secure_url"),
        ("prop", "og:image"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    )
    for kind, key in ordered_meta:
        value = meta_content(soup, **{kind: key})
        if value:
            candidates.append(Candidate(urljoin(page_url, html.unescape(value)), key))

    candidates.extend(json_ld_image_candidates(soup, page_url))

    selectors = (
        "article figure img",
        "article img",
        "main figure img",
        "main img",
        "[itemprop='articleBody'] img",
    )
    for selector in selectors:
        for image in soup.select(selector)[:8]:
            value = (
                srcset_largest(clean(image.get("srcset")))
                or clean(image.get("data-src"))
                or clean(image.get("data-lazy-src"))
                or clean(image.get("src"))
            )
            if value:
                candidates.append(
                    Candidate(urljoin(page_url, html.unescape(value)), selector)
                )

    unique: list[Candidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = candidate.url.strip()
        lower = url.lower()
        if not is_http_url(url) or url in seen:
            continue
        if any(hint in lower for hint in DISALLOWED_IMAGE_HINTS):
            continue
        seen.add(url)
        unique.append(candidate)
    return unique


def extension_for(content_type: str, final_url: str, payload: bytes) -> str | None:
    content_type = content_type.split(";", 1)[0].lower()
    if content_type in SUPPORTED_CONTENT_TYPES:
        return SUPPORTED_CONTENT_TYPES[content_type]

    suffix = Path(urlparse(final_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return ".jpg"
    if suffix in {".png", ".webp"}:
        return suffix

    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return ".webp"
    return None


def plausible_dimensions(payload: bytes, extension: str) -> bool:
    if extension == ".png" and len(payload) >= 24:
        width = int.from_bytes(payload[16:20], "big")
        height = int.from_bytes(payload[20:24], "big")
        return width >= 300 and height >= 180
    return len(payload) >= MIN_IMAGE_BYTES


def safe_filename(article: dict[str, Any], payload: bytes, extension: str) -> str:
    slug = clean(article.get("slug") or article.get("id") or "article")
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:70] or "article"
    digest = hashlib.sha256(payload).hexdigest()[:12]
    return f"{slug}-{digest}{extension}"


def choose_and_fetch_image(
    page_url: str,
    *,
    timeout: int,
    user_agent: str,
) -> tuple[Candidate, bytes, str] | None:
    page, content_type, final_page_url = request_bytes(
        page_url,
        timeout=timeout,
        max_bytes=4 * 1024 * 1024,
        accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
        user_agent=user_agent,
    )
    if "html" not in content_type and not page.lstrip().startswith(b"<"):
        return None

    for candidate in extract_candidates(page, final_page_url):
        try:
            payload, image_type, final_image_url = request_bytes(
                candidate.url,
                timeout=timeout,
                max_bytes=MAX_IMAGE_BYTES,
                accept="image/avif,image/webp,image/png,image/jpeg,*/*;q=0.2",
                user_agent=user_agent,
            )
        except (HTTPError, URLError, TimeoutError, ValueError, OSError):
            continue

        extension = extension_for(image_type, final_image_url, payload)
        if not extension or not plausible_dimensions(payload, extension):
            continue
        return Candidate(final_image_url, candidate.method), payload, extension
    return None


def update_article(
    article: dict[str, Any],
    *,
    output_dir: Path,
    apply: bool,
    timeout: int,
    user_agent: str,
    allow_social: bool,
    sleep_seconds: float,
) -> tuple[bool, str]:
    urls = source_urls(article)
    if not urls:
        return False, "no-source"

    for source_url in urls:
        if is_social_or_search_url(source_url) and not allow_social:
            continue
        try:
            result = choose_and_fetch_image(
                source_url,
                timeout=timeout,
                user_agent=user_agent,
            )
        except (HTTPError, URLError, TimeoutError, ValueError, OSError):
            result = None

        if sleep_seconds:
            time.sleep(sleep_seconds)

        if result is None:
            continue

        candidate, payload, extension = result
        filename = safe_filename(article, payload, extension)
        local_path = output_dir / filename
        try:
            relative_path = local_path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            relative_path = local_path.as_posix()

        if apply:
            output_dir.mkdir(parents=True, exist_ok=True)
            if local_path.exists():
                existing = local_path.read_bytes()
                if existing != payload:
                    return False, "collision"
            else:
                local_path.write_bytes(payload)

        credit = source_name_for(article, source_url)
        article["image_url"] = relative_path
        article["image_credit"] = credit
        article["image_credit_url"] = source_url
        article["source_image_candidate_url"] = candidate.url
        if not clean(article.get("source_image_reuse_status")) or clean(
            article.get("source_image_reuse_status")
        ) in {"permission-required", "unknown"}:
            article["source_image_reuse_status"] = (
                "source-attributed-review-required"
            )
        article["image_backfill_method"] = candidate.method
        return True, "updated"

    if not allow_social and all(is_social_or_search_url(url) for url in urls):
        return False, "social-only"
    return False, "no-candidate"


def load_articles(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [item for item in value if isinstance(item, dict)]


def atomic_write_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assets/article-images"),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--allow-social", action="store_true")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("image_backfill_report.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    articles = load_articles(args.articles)
    original_text = args.articles.read_text(encoding="utf-8")
    stats = Stats(total=len(articles))
    report: list[dict[str, Any]] = []

    processed = 0
    for article in articles:
        if clean(article.get("status") or "published").lower() != "published":
            continue
        if not is_placeholder_image(article):
            stats.already_has_image += 1
            continue
        if args.limit and processed >= args.limit:
            break

        processed += 1
        stats.eligible += 1
        before = {
            key: article.get(key)
            for key in (
                "image_url", "image_credit", "image_credit_url",
                "source_image_candidate_url", "source_image_reuse_status",
            )
        }
        updated, reason = update_article(
            article,
            output_dir=args.output_dir,
            apply=args.apply,
            timeout=args.timeout,
            user_agent=args.user_agent,
            allow_social=args.allow_social,
            sleep_seconds=args.sleep,
        )

        if updated:
            stats.updated += 1
        elif reason == "no-source":
            stats.no_source += 1
        elif reason == "social-only":
            stats.skipped_social += 1
        elif reason == "no-candidate":
            stats.no_candidate += 1
        else:
            stats.fetch_failed += 1

        report.append({
            "slug": clean(article.get("slug")),
            "title": clean(article.get("title")),
            "result": reason,
            "before": before,
            "after": {
                key: article.get(key)
                for key in (
                    "image_url", "image_credit", "image_credit_url",
                    "source_image_candidate_url", "source_image_reuse_status",
                    "image_backfill_method",
                )
            },
        })
        print(f"{reason:14} {clean(article.get('slug') or article.get('title'))}")

    report_payload = {
        "mode": "apply" if args.apply else "dry-run",
        "stats": stats.__dict__,
        "items": report,
    }
    args.report.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.apply:
        atomic_write_json(args.articles, articles)
    elif args.articles.read_text(encoding="utf-8") != original_text:
        raise RuntimeError("dry-run modified articles.json unexpectedly")

    print(json.dumps(stats.__dict__, indent=2))
    print(f"Report: {args.report}")
    if not args.apply:
        print("Dry-run only. Re-run with --apply after reviewing the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
