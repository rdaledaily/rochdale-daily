#!/usr/bin/env python3
"""Ensure every published Rochdale Daily story has a usable local image.

Priority order:
1. Existing valid local/non-placeholder image.
2. Existing source_image_candidate_url.
3. RSS/media/enclosure image fields already stored in the article.
4. Original source page lead image:
   Open Graph, Twitter Card, JSON-LD, article figure/image.
5. Deterministic Rochdale Daily placeholder generated from the story metadata.

Publisher images are cached locally and credited to the original source.
Placeholders never fabricate landmarks; they use typography and simple shapes.

The script is idempotent and safe to run on every workflow.
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

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

DEFAULT_USER_AGENT = (
    "RochdaleDailyImageCoverage/2.0 "
    "(archive maintenance; contact: news@rochdaledaily.co.uk)"
)
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MIN_IMAGE_BYTES = 7 * 1024
WIDTH = 1200
HEIGHT = 675

PLACEHOLDER_MARKERS = (
    "stock_", "placeholder", "default-image", "default_image",
    "category-image", "category_image",
)
BAD_URL_HINTS = (
    "logo", "favicon", "sprite", "avatar", "tracking", "pixel",
    "spacer", "badge", "advert", "doubleclick",
)
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# Hosts that must never be treated as an article's picture source. These pages
# expose their own branding (the Google News newspaper logo, social sprites,
# etc.) via og:image, which previously got cached and credited as if it were the
# story's photograph.
DISALLOWED_SOURCE_HOSTS = {
    "news.google.com", "google.com", "google.co.uk",
    "facebook.com", "m.facebook.com", "x.com", "twitter.com",
    "tiktok.com", "instagram.com", "reddit.com", "old.reddit.com",
    "youtube.com", "youtu.be",
}
DISALLOWED_SOURCE_SUFFIXES = (
    "facebook.com", "instagram.com", "tiktok.com", "reddit.com",
    "google.com", "google.co.uk",
)
# Image *hosting* domains that only ever serve Google/consent chrome, never a
# publisher's editorial image.
DISALLOWED_IMAGE_HOST_SUFFIXES = (
    "google.com", "google.co.uk", "googleusercontent.com", "gstatic.com",
)
# Content hashes (sha256[:12]) of known non-editorial images that leaked in
# before this guard existed — currently the Google News logo. Any locally cached
# file matching one of these is treated as missing so it gets re-processed.
KNOWN_BAD_IMAGE_DIGESTS = {
    "872cdca296d0",  # Google News newspaper logo
}


def host_of(url: str) -> str:
    return urlparse(clean(url)).netloc.lower().split(":", 1)[0].removeprefix("www.")


def is_disallowed_source(url: str) -> bool:
    host = host_of(url)
    if not host:
        return False
    if host in DISALLOWED_SOURCE_HOSTS:
        return True
    return any(host.endswith("." + suffix) for suffix in DISALLOWED_SOURCE_SUFFIXES)


def is_disallowed_image(url: str) -> bool:
    host = host_of(url)
    if not host:
        return False
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in DISALLOWED_IMAGE_HOST_SUFFIXES
    )


def credit_is_disallowed(article: dict[str, Any]) -> bool:
    """True if the cached image was attributed to Google/social chrome."""
    credit = clean(article.get("image_credit")).lower()
    if credit in DISALLOWED_SOURCE_HOSTS:
        return True
    if any(credit == suffix or credit.endswith("." + suffix)
           for suffix in DISALLOWED_SOURCE_SUFFIXES):
        return True
    return is_disallowed_source(article.get("image_credit_url"))


def local_digest(repo_root: Path, image_url: str) -> str:
    if is_http_url(image_url):
        return ""
    path = repo_root / clean(image_url).lstrip("/")
    if not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


@dataclass(frozen=True)
class Candidate:
    url: str
    method: str
    credit_url: str


@dataclass
class Stats:
    total: int = 0
    already_covered: int = 0
    source_images_added: int = 0
    placeholders_added: int = 0
    source_attempts_failed: int = 0
    skipped_unpublished: int = 0


def clean(value: Any) -> str:
    return str(value or "").strip()


def is_http_url(value: Any) -> bool:
    value = clean(value)
    return value.startswith("https://") or value.startswith("http://")


def is_placeholder_path(value: Any) -> bool:
    value = clean(value).lower()
    return not value or any(marker in value for marker in PLACEHOLDER_MARKERS)


def has_real_image(article: dict[str, Any], repo_root: Path) -> bool:
    image_url = clean(article.get("image_url"))
    if not image_url or is_placeholder_path(image_url):
        return False

    # Self-heal legacy records: a picture credited to Google News / a social
    # network, or whose bytes match a known non-editorial image (the Google
    # logo), is not a real source image and must be re-processed.
    if credit_is_disallowed(article):
        return False
    if local_digest(repo_root, image_url) in KNOWN_BAD_IMAGE_DIGESTS:
        return False

    if is_http_url(image_url):
        return True

    path = repo_root / image_url.lstrip("/")
    return path.is_file() and path.stat().st_size >= MIN_IMAGE_BYTES


def source_urls(article: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for value in [article.get("source_url"), *(article.get("source_urls") or [])]:
        value = clean(value)
        if is_http_url(value) and value not in result:
            result.append(value)
    return result


def source_name(article: dict[str, Any], url: str) -> str:
    primary_url = clean(article.get("source_url"))
    primary_name = clean(article.get("source_name"))
    if url == primary_url and primary_name:
        return primary_name

    urls = [clean(v) for v in article.get("source_urls") or []]
    names = [clean(v) for v in article.get("source_names") or []]
    if url in urls:
        index = urls.index(url)
        if index < len(names) and names[index]:
            return names[index]

    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host or "Original source"


def request_bytes(
    url: str,
    *,
    timeout: int,
    max_bytes: int,
    accept: str,
) -> tuple[bytes, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    with build_opener().open(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type().lower()
        final_url = response.geturl()
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("response too large")

        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = response.read(min(65536, max_bytes - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("response too large")
        return b"".join(chunks), content_type, final_url


def meta_content(soup: BeautifulSoup, *, prop: str = "", name: str = "") -> str:
    attrs = {}
    if prop:
        attrs["property"] = re.compile(rf"^{re.escape(prop)}$", re.I)
    else:
        attrs["name"] = re.compile(rf"^{re.escape(name)}$", re.I)
    node = soup.find("meta", attrs=attrs)
    return clean(node.get("content")) if node else ""


def largest_srcset(srcset: str) -> str:
    best = ("", -1)
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        width = 0
        if len(bits) > 1 and bits[-1].endswith("w"):
            try:
                width = int(bits[-1][:-1])
            except ValueError:
                width = 0
        if width >= best[1]:
            best = (bits[0], width)
    return best[0]


def json_ld_images(soup: BeautifulSoup, page_url: str) -> list[Candidate]:
    result: list[Candidate] = []
    for node in soup.find_all(
        "script", attrs={"type": re.compile(r"application/ld\+json", re.I)}
    ):
        raw = node.string or node.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except Exception:
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
            values: list[str] = []
            if isinstance(image, str):
                values.append(image)
            elif isinstance(image, dict):
                values.append(clean(image.get("url") or image.get("contentUrl")))
            elif isinstance(image, list):
                for entry in image:
                    if isinstance(entry, str):
                        values.append(entry)
                    elif isinstance(entry, dict):
                        values.append(clean(entry.get("url") or entry.get("contentUrl")))

            for value in values:
                if value:
                    result.append(
                        Candidate(
                            url=urljoin(page_url, html.unescape(value)),
                            method="json-ld",
                            credit_url=page_url,
                        )
                    )
    return result


def page_candidates(page: bytes, page_url: str) -> list[Candidate]:
    soup = BeautifulSoup(page, "html.parser")
    result: list[Candidate] = []

    for kind, key in (
        ("prop", "og:image:secure_url"),
        ("prop", "og:image"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    ):
        value = meta_content(soup, **{kind: key})
        if value:
            result.append(
                Candidate(
                    url=urljoin(page_url, html.unescape(value)),
                    method=key,
                    credit_url=page_url,
                )
            )

    result.extend(json_ld_images(soup, page_url))

    for selector in (
        "article figure img",
        "article img",
        "main figure img",
        "main img",
        "[itemprop='articleBody'] img",
    ):
        for image in soup.select(selector)[:12]:
            value = (
                largest_srcset(clean(image.get("srcset")))
                or clean(image.get("data-src"))
                or clean(image.get("data-lazy-src"))
                or clean(image.get("src"))
            )
            if value:
                result.append(
                    Candidate(
                        url=urljoin(page_url, html.unescape(value)),
                        method=selector,
                        credit_url=page_url,
                    )
                )

    return deduplicate_candidates(result)


def article_candidates(article: dict[str, Any]) -> list[Candidate]:
    result: list[Candidate] = []
    primary_source = clean(article.get("source_url"))

    for field in (
        "source_image_candidate_url",
        "source_image_url",
        "rss_image_url",
        "media_content_url",
        "media_thumbnail_url",
        "enclosure_url",
        "thumbnail_url",
    ):
        value = clean(article.get(field))
        if is_http_url(value):
            result.append(
                Candidate(
                    url=value,
                    method=field,
                    credit_url=primary_source or value,
                )
            )

    for value in article.get("source_image_candidates") or []:
        if is_http_url(value):
            result.append(
                Candidate(
                    url=clean(value),
                    method="source_image_candidates",
                    credit_url=primary_source or clean(value),
                )
            )

    return deduplicate_candidates(result)


def deduplicate_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    result: list[Candidate] = []
    for candidate in candidates:
        url = clean(candidate.url)
        lower = url.lower()
        if not is_http_url(url) or url in seen:
            continue
        if any(hint in lower for hint in BAD_URL_HINTS):
            continue
        if is_disallowed_image(url):
            continue
        seen.add(url)
        result.append(candidate)
    return result


def extension_for(content_type: str, final_url: str, payload: bytes) -> str | None:
    content_type = content_type.split(";", 1)[0].lower()
    if content_type in IMAGE_EXTENSIONS:
        return IMAGE_EXTENSIONS[content_type]

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


def fetch_candidate(candidate: Candidate, timeout: int) -> tuple[bytes, str, str] | None:
    try:
        payload, content_type, final_url = request_bytes(
            candidate.url,
            timeout=timeout,
            max_bytes=MAX_IMAGE_BYTES,
            accept="image/avif,image/webp,image/png,image/jpeg,*/*;q=0.2",
        )
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None

    extension = extension_for(content_type, final_url, payload)
    if not extension or len(payload) < MIN_IMAGE_BYTES:
        return None
    return payload, extension, final_url


def fetch_source_image(
    article: dict[str, Any],
    *,
    timeout: int,
    sleep_seconds: float,
) -> tuple[bytes, str, Candidate, str] | None:
    candidates = article_candidates(article)

    for page_url in source_urls(article):
        if is_disallowed_source(page_url):
            # e.g. an unresolved news.google.com wrapper — its og:image is the
            # Google logo, not the story photo. Never scrape it.
            continue
        try:
            page, content_type, final_page_url = request_bytes(
                page_url,
                timeout=timeout,
                max_bytes=MAX_PAGE_BYTES,
                accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
            )
            if "html" in content_type or page.lstrip().startswith(b"<"):
                candidates.extend(page_candidates(page, final_page_url))
        except (HTTPError, URLError, TimeoutError, ValueError, OSError):
            pass
        if sleep_seconds:
            time.sleep(sleep_seconds)

    for candidate in deduplicate_candidates(candidates):
        fetched = fetch_candidate(candidate, timeout)
        if fetched is None:
            continue
        payload, extension, final_url = fetched
        if is_disallowed_image(final_url):
            continue
        return (
            payload,
            extension,
            Candidate(final_url, candidate.method, candidate.credit_url),
            source_name(article, candidate.credit_url),
        )
    return None


def slug_for(article: dict[str, Any]) -> str:
    raw = clean(article.get("slug") or article.get("id") or article.get("title"))
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:80] or "story"


def save_source_image(
    article: dict[str, Any],
    payload: bytes,
    extension: str,
    output_dir: Path,
) -> str:
    digest = hashlib.sha256(payload).hexdigest()[:12]
    filename = f"{slug_for(article)}-{digest}{extension}"
    path = output_dir / filename
    output_dir.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(payload)
    return path.as_posix()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:4]


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def placeholder_palette(article: dict[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    key = clean(article.get("category") or article.get("area") or "news").lower()
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    base = (10 + digest[0] // 8, 28 + digest[1] // 8, 55 + digest[2] // 8)
    accent = (30 + digest[3] // 3, 110 + digest[4] // 3, 170 + digest[5] // 3)
    return base, accent


def generate_placeholder(article: dict[str, Any], output_dir: Path) -> str:
    slug = slug_for(article)
    path = output_dir / f"{slug}-rochdale-daily-placeholder.jpg"
    if path.exists():
        return path.as_posix()

    base, accent = placeholder_palette(article)
    image = Image.new("RGB", (WIDTH, HEIGHT), base)
    draw = ImageDraw.Draw(image)

    # Clean editorial shapes only; no fabricated photography or landmarks.
    draw.rectangle((0, HEIGHT - 135, WIDTH, HEIGHT), fill=(5, 18, 38))
    draw.polygon(
        [(0, 0), (420, 0), (0, 420)],
        fill=accent,
    )
    draw.polygon(
        [(WIDTH, HEIGHT), (WIDTH - 330, HEIGHT), (WIDTH, HEIGHT - 330)],
        fill=accent,
    )

    category = clean(article.get("category") or "News").replace("-", " ").title()
    area = clean(article.get("area") or "Rochdale").replace("-", " ").title()
    title = clean(article.get("title") or "Rochdale Daily")

    small = load_font(30, bold=True)
    title_font = load_font(54, bold=True)
    brand_font = load_font(32, bold=True)
    credit_font = load_font(22)

    draw.text((72, 64), f"{category}  •  {area}", font=small, fill="white")

    lines = wrap_text(draw, title, title_font, WIDTH - 144)
    y = 165
    for line in lines:
        draw.text((72, y), line, font=title_font, fill="white")
        y += 66

    draw.text((72, HEIGHT - 96), "Rochdale Daily", font=brand_font, fill="white")
    draw.text(
        (WIDTH - 355, HEIGHT - 88),
        "Image unavailable from source",
        font=credit_font,
        fill=(220, 228, 238),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=90, optimize=True)
    return path.as_posix()


def ensure_article_image(
    article: dict[str, Any],
    *,
    repo_root: Path,
    output_dir: Path,
    timeout: int,
    sleep_seconds: float,
    retry_placeholders: bool,
) -> str:
    if has_real_image(article, repo_root):
        return "already-covered"

    existing_status = clean(article.get("image_status"))
    existing_placeholder = existing_status == "generated-placeholder"

    if not existing_placeholder or retry_placeholders:
        result = fetch_source_image(
            article,
            timeout=timeout,
            sleep_seconds=sleep_seconds,
        )
        if result is not None:
            payload, extension, candidate, credit = result
            local_path = save_source_image(article, payload, extension, output_dir)
            article["image_url"] = local_path
            article["image_credit"] = credit
            article["image_credit_url"] = candidate.credit_url
            article["source_image_candidate_url"] = candidate.url
            article["image_status"] = "source-image-cached"
            article["image_backfill_method"] = candidate.method
            article["source_image_reuse_status"] = article.get(
                "source_image_reuse_status"
            ) or "source-attributed-review-required"
            article.pop("image_placeholder_reason", None)
            return "source-image"

    local_path = generate_placeholder(article, output_dir)
    article["image_url"] = local_path
    article["image_credit"] = "Rochdale Daily"
    article["image_credit_url"] = "https://rochdaledaily.co.uk/"
    article["image_status"] = "generated-placeholder"
    article["image_placeholder_reason"] = "No usable source image could be retrieved"
    return "placeholder"


def atomic_write(path: Path, value: Any) -> None:
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
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument(
        "--retry-placeholders",
        action="store_true",
        help="Retry source extraction for stories currently using generated placeholders.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("image_coverage_report.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = Path.cwd()
    articles = json.loads(args.articles.read_text(encoding="utf-8"))
    if not isinstance(articles, list):
        raise SystemExit("articles.json must contain a JSON array")

    stats = Stats(total=len(articles))
    report: list[dict[str, str]] = []
    processed = 0

    for article in articles:
        if not isinstance(article, dict):
            continue
        if clean(article.get("status") or "published").lower() != "published":
            stats.skipped_unpublished += 1
            continue

        if args.limit and processed >= args.limit:
            break
        processed += 1

        result = ensure_article_image(
            article,
            repo_root=repo_root,
            output_dir=args.output_dir,
            timeout=args.timeout,
            sleep_seconds=args.sleep,
            retry_placeholders=args.retry_placeholders,
        )

        if result == "already-covered":
            stats.already_covered += 1
        elif result == "source-image":
            stats.source_images_added += 1
        elif result == "placeholder":
            stats.placeholders_added += 1
            stats.source_attempts_failed += 1

        report.append({
            "slug": slug_for(article),
            "title": clean(article.get("title")),
            "result": result,
            "image_url": clean(article.get("image_url")),
            "image_credit": clean(article.get("image_credit")),
        })
        print(f"{result:16} {slug_for(article)}")

    atomic_write(args.articles, articles)
    atomic_write(
        args.report,
        {
            "stats": stats.__dict__,
            "items": report,
        },
    )
    print(json.dumps(stats.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
