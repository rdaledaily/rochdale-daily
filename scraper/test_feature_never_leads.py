#!/usr/bin/env python3
"""A reserve feature (evergreen folklore or explainer) is never a top story.

Regression for 24 Oct 2026: after a quiet afternoon "Does a boggart still haunt
Clegg Hall?" was the newest item and led the front page. Features are held
below the top-story positions, like sponsored pieces, in the Python ordering
and in functions/articles/frontpage.json.js.
Run: PYTHONPATH=scraper python scraper/test_feature_never_leads.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from ensure_manual_frontpage import demote_sponsored  # noqa: E402

feature = {"slug": "boggart", "source_kind": "evergreen", "publication_route": "evergreen_fallback"}
news = [{"slug": f"news-{n}"} for n in range(12)]

ordered = demote_sponsored([feature] + news)
assert [r["slug"] for r in ordered[:9]] == [f"news-{n}" for n in range(9)], ordered[:3]
assert ordered.index(feature) == 9

short = demote_sponsored([feature] + news[:3])          # a quiet day: still last, never first
assert short[-1] is feature and short[0]["slug"] == "news-0"

js = (ROOT / "functions" / "articles" / "frontpage.json.js").read_text(encoding="utf-8")
assert "isReserveFeature(article)" in js and "evergreen_fallback" in js
print("Reserve features never lead the front page.")
