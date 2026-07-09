[README.md](https://github.com/user-attachments/files/29856667/README.md)
# Rochdale Daily autonomous news pipeline

Rochdale Daily runs from GitHub Actions and publishes current local stories into `articles.json`, then generates static article pages and the sitemap.

## Active flow

```text
.github/workflows/scrape.yml
    -> scraper/scraper.py
        -> scraper/search_queries.py
        -> scraper/locality_rules.py
        -> scraper/selection_policy.py
        -> scraper/story_identity.py
        -> scraper/rewrite_safety.py
    -> articles.json
    -> scraper/generate_pages.py
    -> articles/*.html and sitemap.xml
```

## Crime, police and court stories

Crime items do not use an approval queue. When a candidate passes the ordinary source, date, locality, duplicate and content checks, it is published automatically.

OpenAI remains the preferred rewriting route. If OpenAI is unavailable, errors, or returns `publishable: false`, the scraper creates an attributed fallback article instead of silently dropping a valid crime candidate.

Every published crime article is written with:

```json
{
  "category": "crime",
  "police_matter": true,
  "requires_approval": false,
  "status": "published"
}
```

The only retained identity protection is for protected children and sexual-offence complainants. This is not an approval queue and does not prevent ordinary crime stories from publishing.

## Source policy

Roch Valley Radio remains an allowed local source. Rochdale Times and Rochdale Online remain blocked.

The scraper respects `robots.txt`. Sources that cannot be fetched directly may still be discovered through permitted RSS feeds, indexed search results or authorised APIs.

## `review_queue.json`

`review_queue.json` is legacy output and is not read or written by the current pipeline. It can be deleted from the repository after any old material you need has been archived.

## Installation

Replace these two active files:

- `scraper/scraper.py`
- `.github/workflows/scrape.yml`

Replace `README.md` with this file so the repository documentation matches the live behaviour. Delete the old `review_queue.json` to remove the misleading legacy queue.

Commit the changes to `main`, then run:

**Actions -> Rochdale Daily 15-minute scraper -> Run workflow**

After the run, inspect `scraper_status.json`. It now records:

- `crime_auto_publish_enabled`
- `crime_review_queue_enabled`
- `selected_by_category`
- `published_by_category`

A successful run should show at least one published crime article whenever eligible crime candidates were selected.
