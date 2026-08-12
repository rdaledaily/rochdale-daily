#!/usr/bin/env python3
"""Replace generated Rochdale Daily article cards with real source photographs.

The normal cards matcher remains the first choice. This pass only touches published
articles that are still using a generated/placeholder card after that matcher has
run. It then checks the article's original publisher page for a declared lead image
(Open Graph, Twitter card, JSON-LD or a prominent article image), caches an accepted
image locally under ``assets/img/cards`` and keeps the source credit.

For safety this automated repair is limited to source domains that the newsroom has
explicitly allowed for image reuse. If no suitable image can be obtained, the
existing generated card is left untouched. The pass is retrospective, so an older
placeholder can be repaired on any later scraper run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backfill_article_images import (
    DEFAULT_USER_AGENT,
    atomic_write_json,
    clean,
    load_articles,
    source_urls,
    update_article,
)

DEFAULT_ALLOWED_DOMAINS = (
    "rochdale.gov.uk,gmp.police.uk,manchesterfire.gov.uk,rochdaleafc.co.uk,"
    "hornetsrugbyleague.co.uk,tfgm.com,gmca.gov.uk,nationalhighways.co.uk,"
    "hopwood.ac.uk,northerncarealliance.nhs.uk,penninecare.nhs.uk,"
    "rochvalleyradio.com,actiontogether.org.uk,yourtrustrochdale.co.uk,"
    "rochdaletownhall.co.uk,visitrochdale.com,investinrochdale.co.uk,"
    "media.northernrailway.co.uk"
)


def host(value: str) -> str:
    return urlparse(value).netloc.lower().removeprefix("www.")


def allowed_domains() -> set[str]:
    raw = os.getenv("IMAGE_REUSE_SOURCE_DOMAINS", DEFAULT_ALLOWED_DOMAINS)
    return {item.strip().lower().removeprefix("www.") for item in raw.split(",") if item.strip()}


def domain_allowed(value: str, allowed: set[str]) -> bool:
    name = host(value)
    return any(name == domain or name.endswith("." + domain) for domain in allowed)


def is_generated_or_placeholder(article: dict[str, Any]) -> bool:
    image = clean(article.get("image_url") or article.get("img")).lower()
    status = clean(article.get("image_status")).lower()
    return bool(
        not image
        or "generated-card" in image
        or "area-category-card" in image
        or "placeholder" in image
        or status == "cards-generated"
        or clean(article.get("image_placeholder_reason"))
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=Path, default=Path("articles.json"))
    parser.add_argument("--report", type=Path, default=Path("image_repair_report.json"))
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    articles = load_articles(args.articles)
    allowed = allowed_domains()
    repaired = 0
    eligible = 0
    no_allowed_source = 0
    no_image = 0
    rows: list[dict[str, Any]] = []

    for article in articles:
        if clean(article.get("status") or "published").lower() != "published":
            continue
        if not is_generated_or_placeholder(article):
            continue
        if args.limit and eligible >= args.limit:
            break

        eligible += 1
        original_sources = list(article.get("source_urls") or [])
        primary = clean(article.get("source_url"))
        candidates = source_urls(article)
        permitted = [url for url in candidates if domain_allowed(url, allowed)]
        if not permitted:
            no_allowed_source += 1
            rows.append({
                "slug": clean(article.get("slug")),
                "result": "no-allowed-source",
                "sources": candidates,
            })
            continue

        before = {
            "image_url": article.get("image_url"),
            "img": article.get("img"),
            "image_credit": article.get("image_credit"),
            "image_credit_url": article.get("image_credit_url"),
            "image_status": article.get("image_status"),
            "image_placeholder_reason": article.get("image_placeholder_reason"),
        }

        # Temporarily expose only permitted sources to the existing conservative
        # publisher-image extractor. Restore the source list immediately after.
        article["source_url"] = permitted[0]
        article["source_urls"] = permitted
        updated, reason = update_article(
            article,
            output_dir=Path("assets/img/cards"),
            apply=True,
            timeout=args.timeout,
            user_agent=DEFAULT_USER_AGENT,
            allow_social=False,
            sleep_seconds=0,
        )
        article["source_url"] = primary
        if original_sources:
            article["source_urls"] = original_sources
        else:
            article.pop("source_urls", None)

        if updated:
            article["img"] = article.get("image_url")
            article["image_status"] = "source-photo-cached"
            article["image_backfill_method"] = "publisher-lead-image"
            article.pop("image_placeholder_reason", None)
            repaired += 1
            result = "repaired"
        else:
            # update_article mutates only on success, but restore explicitly so
            # this script remains safe if its implementation changes later.
            for key, value in before.items():
                if value is None:
                    article.pop(key, None)
                else:
                    article[key] = value
            no_image += 1
            result = reason or "no-image"

        rows.append({
            "slug": clean(article.get("slug")),
            "title": clean(article.get("title")),
            "result": result,
            "source": permitted[0],
            "before": before.get("image_url"),
            "after": article.get("image_url"),
        })
        print(f"{result:18} {clean(article.get('slug') or article.get('title'))}")

    if repaired:
        atomic_write_json(args.articles, articles)

    report = {
        "eligible_placeholders": eligible,
        "repaired_with_source_photo": repaired,
        "no_allowed_source": no_allowed_source,
        "no_usable_source_image": no_image,
        "allowed_domains": sorted(allowed),
        "items": rows,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "eligible_placeholders", "repaired_with_source_photo", "no_allowed_source", "no_usable_source_image"
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
