"""Rochdale Daily newsroom entrypoint.

Extends the existing Rochdale-first pipeline with indexed fallbacks for important
sources whose APIs/RSS feeds can be unavailable. The direct source remains
preferred whenever it works; these searches stop one broken integration from
making the local news desk blind.
"""
from __future__ import annotations

import scraper as core
import run_fast_local_pipeline as base
from search_queries import SearchQuery


EXTRA_FRESH_SEARCHES = [
    SearchQuery(
        "fallback:men-rochdale-today",
        'site:manchestereveningnews.co.uk (Rochdale OR Heywood OR Middleton OR Littleborough) when:1d',
        "news",
    ),
    SearchQuery(
        "fallback:gmp-rochdale-today",
        'site:gmp.police.uk (Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow) when:1d',
        "crime",
    ),
    SearchQuery(
        "fallback:rochdale-council-today",
        'site:rochdale.gov.uk/news (Rochdale OR Heywood OR Middleton OR Littleborough) when:1d',
        "news",
    ),
    SearchQuery(
        "fallback:tfgm-rochdale-today",
        '(site:news.tfgm.com OR site:tfgm.com) (Rochdale OR Heywood OR Middleton) when:1d',
        "transport",
    ),
    SearchQuery(
        "fallback:fire-rochdale-today",
        'site:manchesterfire.gov.uk (Rochdale OR Heywood OR Middleton OR Littleborough) when:2d',
        "news",
    ),
    SearchQuery(
        "fallback:nca-rochdale-today",
        'site:northerncarealliance.nhs.uk Rochdale when:2d',
        "health",
    ),
    SearchQuery(
        "fallback:local-public-posts-today",
        '("GMPRochdale" OR "Rochdale Borough Council" OR "Bee Network") '
        '(Rochdale OR Heywood OR Middleton OR Littleborough) when:1d',
        "news",
    ),
]


def main() -> int:
    # scraper.py historically forces at least 168 hours even when production
    # asks for a shorter age window. A news desk should search recent material
    # first, so this entrypoint explicitly enforces the configured 72-hour cap.
    core.MAX_NEWS_AGE_HOURS = 72

    existing = {item.query.casefold().strip() for item in base.PRIORITY_SEARCHES}
    for item in EXTRA_FRESH_SEARCHES:
        if item.query.casefold().strip() not in existing:
            base.PRIORITY_SEARCHES.append(item)
            existing.add(item.query.casefold().strip())

    base.configure()
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
