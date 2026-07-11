"""Editorial takedown: permanently remove stories from Rochdale Daily.

Run by the "Remove story" workflow (workflow_dispatch). Steps, in order:

  1. Add the given slugs / title patterns / source URLs to
     story_blocklist.json FIRST, so any run already in flight cannot
     resurrect the story through the push-race merge.
  2. Scrub every matching record from articles.json.
  3. Delete the matching article pages from articles/.
  4. Rebuild the article pages, frontpage.json and sitemap.xml via
     generate_pages so the published site no longer references the story.

Usage:
  python scraper/remove_story.py \
      --slugs "slug-one,slug-two" \
      --title-patterns "henry nowak" \
      --source-urls "https://example.com/story"

At least one selector is required. Matching is identical to the pipeline's
blocklist semantics: slugs exact, title patterns lowercase substring,
source URLs canonicalised exact (checked against every merged source URL).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_blocklist import (  # noqa: E402
    canonical_url,
    is_blocked_article,
    load_blocklist,
    save_blocklist,
)

ARTICLES_JSON = Path("articles.json")
ARTICLE_PAGES_DIR = Path("articles")


def split_arg(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slugs", default="", help="Comma-separated page slugs")
    parser.add_argument(
        "--title-patterns", default="",
        help="Comma-separated lowercase title substrings",
    )
    parser.add_argument("--source-urls", default="", help="Comma-separated source URLs")
    parser.add_argument(
        "--skip-regenerate", action="store_true",
        help="Skip rebuilding pages/frontpage (for tests only)",
    )
    args = parser.parse_args()

    slugs = [slug.lower() for slug in split_arg(args.slugs)]
    patterns = [pattern.lower() for pattern in split_arg(args.title_patterns)]
    urls = [canonical_url(url) for url in split_arg(args.source_urls)]

    if not (slugs or patterns or urls):
        print("ERROR: provide at least one of --slugs / --title-patterns / --source-urls")
        return 2

    # 1. Blocklist first: from this moment no merge or re-scrape can
    #    reintroduce the story, even if steps below race another run.
    blocklist = load_blocklist()
    blocklist["slugs"] = list(blocklist["slugs"]) + slugs
    blocklist["title_patterns"] = list(blocklist["title_patterns"]) + patterns
    blocklist["source_urls"] = list(blocklist["source_urls"]) + urls
    save_blocklist(blocklist)
    blocklist = load_blocklist()
    print(
        f"Blocklist updated: {len(blocklist['slugs'])} slugs, "
        f"{len(blocklist['title_patterns'])} title patterns, "
        f"{len(blocklist['source_urls'])} source URLs."
    )

    # 2. Scrub the feed.
    try:
        feed = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not read articles.json ({exc})")
        return 1
    if not isinstance(feed, list):
        print("ERROR: articles.json is not a JSON list")
        return 1

    removed_records = [
        article for article in feed
        if isinstance(article, dict) and is_blocked_article(article, blocklist)
    ]
    kept = [article for article in feed if article not in removed_records]
    ARTICLES_JSON.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for article in removed_records:
        print(f"Removed from feed: {article.get('slug')} — {article.get('title')}")
    print(f"articles.json: {len(feed)} -> {len(kept)} records.")

    # 3. Ensure every removed record's slug is blocklisted too, so
    #    cleanup_stale_article_pages keeps the page dead on future runs,
    #    then delete the pages now.
    removed_slugs = {
        str(article.get("slug") or "").lower()
        for article in removed_records
        if article.get("slug")
    }
    extra_slugs = removed_slugs - set(blocklist["slugs"])
    if extra_slugs:
        blocklist["slugs"] = list(blocklist["slugs"]) + sorted(extra_slugs)
        save_blocklist(blocklist)
        blocklist = load_blocklist()

    deleted_pages = 0
    for slug in set(blocklist["slugs"]):
        page = ARTICLE_PAGES_DIR / f"{slug}.html"
        if page.exists():
            page.unlink()
            deleted_pages += 1
            print(f"Deleted page: {page}")
    print(f"Article pages deleted: {deleted_pages}.")

    # 4. Rebuild pages, frontpage.json and sitemap.xml from the scrubbed feed.
    if not args.skip_regenerate:
        from generate_pages import main as regenerate
        regenerate()
        print("Regenerated article pages, frontpage.json and sitemap.xml.")

    if not removed_records and not deleted_pages:
        print(
            "NOTE: no live records or pages matched. The blocklist entries were "
            "still saved, so the story cannot be (re)published in future."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
