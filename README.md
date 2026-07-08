# Rochdale Daily pipeline repair

This package replaces the broken live-feed pipeline.

## Replace these repository files

- `index.html`
- `scraper/scraper.py`
- `.github/workflows/scrape.yml`
- `requirements.txt`
- `articles.json`
- `review_queue.json`

Upload the complete `assets/img/` directory as well.

The original September 2025 feed is preserved as
`articles-archive-2025.json` for reference only. Do not use that archive as the
live `articles.json`.

## What happens after upload

1. Commit all files to `main`.
2. Confirm the repository secret `OPENAI_API_KEY` exists.
3. Open Actions > Rochdale Daily hourly scraper > Run workflow.
4. The scraper reads current RSS and discovery pages.
5. It rejects undated, stale, non-local and promotional material.
6. OpenAI returns strict JSON, not Markdown.
7. Low-risk stories go into `articles.json`.
8. Crime, court, allegation, death, child-safeguarding and similar stories go
   into `review_queue.json` and are not shown automatically.
9. The website checks `articles.json` every five minutes.

## Images

The scraper looks for:

- RSS `media:content`
- RSS thumbnails or image enclosures
- Open Graph images
- Twitter card images
- JSON-LD `NewsArticle.image`

Commercial publisher images are not automatically republished. The workflow
sets an explicit allow-list for official-source domains. Confirm the reuse
terms for every allowed domain. Remove a domain from
`IMAGE_REUSE_SOURCE_DOMAINS` if permission is uncertain.

Unapproved or missing images use original Rochdale Daily category SVGs from
`assets/img/`.

## Important editorial controls

Automated rewriting is not a substitute for a media lawyer or editor. The
pipeline deliberately queues sensitive stories. Review facts, reporting
restrictions, anonymity, copyright, attribution and right-to-reply before
moving any queued story into the public feed.

Facebook groups are not scraped by the replacement. Group posts should be
treated as tips and independently verified before publication.

