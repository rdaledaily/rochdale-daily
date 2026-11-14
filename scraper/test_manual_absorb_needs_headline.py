"""An editor's story must not absorb an unrelated scrape (14 Nov 2026).

A long analysis of Buckley Hall prison mentioned "assault", "men" and
"Rochdale"; the incident-fact route matched it to a sexual-assault witness
appeal and the loader folded the appeal in (crime, ONGOING, police photo).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manual_articles as m  # noqa: E402

NOW = datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc)

analysis = m._normalise({
    "slug": "buckley-hall-prison-drugs-self-harm-requires-improvement",
    "title": "Buckley Hall Prison: drugs, self-harm and ‘requires improvement’",
    "body": ("Buckley Hall prison in Rochdale is not doing enough to rehabilitate the men it holds.\\n\\n"
             "Inspectors found violence lower than at most category C prisons, with fewer serious assaults. "
             "Intelligence suggested a man had been assaulted over a drug debt."),
    "area": "rochdale", "category": "news", "published_at": "2026-11-14T23:05:00Z",
    "source_url": "https://hmiprisons.justiceinspectorates.gov.uk/hmipris_reports/hmp-buckley-hall",
}, NOW)

appeal = {
    "id": "9bb5f0387558e6d6ba",
    "slug": "police-search-for-man-who-helped-woman-after-alleged-sexual-assault-in-rochdale",
    "title": "Police search for man who helped woman after alleged sexual assault in Rochdale",
    "excerpt": "Police want to trace a man who helped a woman after she was sexually assaulted in Rochdale.",
    "content_html": "<p>A woman was sexually assaulted in Rochdale. Police want to speak to a man who helped her.</p>",
    "area": "rochdale", "category": "crime", "published_at": "2026-11-14T18:00:00Z",
    "source_url": "https://www.rochdaletimes.co.uk/police-seek-key-witness-who-helped-sexual-assault-victim/",
    "source_name": "Rochdale Times",
}

twin = dict(appeal, id="abc123", slug="buckley-hall-prison-requires-improvement-inspectors-say",
            title="Buckley Hall prison requires improvement, inspectors say", category="news",
            source_url="https://example.org/buckley-hall")

assert not m._headline_corroborates(analysis, appeal), "unrelated appeal must not be absorbed"
assert m._headline_corroborates(analysis, twin), "a scrape of the same story still merges"
same_url = dict(appeal, title="Completely different words", source_url=analysis["source_url"])
assert m._headline_corroborates(analysis, same_url), "same source URL always corroborates"
print("manual absorb headline guard: 3 checks passed")
