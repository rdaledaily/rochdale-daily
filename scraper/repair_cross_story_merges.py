from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "articles.json"
ARTICLE_DIR = ROOT / "articles"


def is_known_cross_story_contamination(article: dict) -> bool:
    title = str(article.get("title") or "").lower()
    excerpt = str(article.get("excerpt") or article.get("summary") or "").lower()
    body = str(article.get("content_html") or "").lower()
    combined = " ".join([title, excerpt, body])

    has_shabir_case = (
        "shabir ahmed" in combined
        or (
            "grooming" in combined
            and ("deport" in combined or "pakistan" in combined)
        )
    )
    has_farm_fire = (
        "farm" in combined
        and ("fire" in combined or "blaze" in combined)
        and ("murder" in combined or "died" in combined or "dead" in combined)
    )

    title_is_farm_fire = (
        "farm" in title
        and ("fire" in title or "blaze" in title)
        and ("murder" in title or "fatal" in title or "death" in title)
    )
    body_is_shabir = (
        "shabir ahmed" in excerpt
        or "shabir ahmed" in body
        or (
            "grooming" in excerpt
            and ("deport" in excerpt or "pakistan" in excerpt)
        )
    )

    return (
        has_shabir_case and has_farm_fire
        or title_is_farm_fire and body_is_shabir
    )


def main() -> int:
    articles = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    kept: list[dict] = []
    removed: list[dict] = []

    for article in articles:
        if isinstance(article, dict) and is_known_cross_story_contamination(article):
            removed.append(article)
            slug = str(article.get("slug") or "").strip()
            if slug:
                page = ARTICLE_DIR / f"{slug}.html"
                if page.exists():
                    page.unlink()
                    print(f"Deleted contaminated page: {page}")
            continue
        kept.append(article)

    ARTICLES_PATH.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Removed {len(removed)} cross-story contaminated article(s).")
    for article in removed:
        print(" -", article.get("title") or article.get("slug") or "Untitled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
