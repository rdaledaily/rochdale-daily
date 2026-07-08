from story_identity import (
    build_story_key,
    dedupe_article_records,
    same_story,
    story_similarity,
)

SIGNING = {
    "title": "Rochdale AFC signs midfielder Will Jenkins",
    "excerpt": (
        "Rochdale AFC has confirmed the signing of midfielder Will Jenkins "
        "from South Shields on a two-year deal."
    ),
    "content_html": (
        "<p>Rochdale AFC has confirmed the signing of Will Jenkins.</p>"
    ),
    "source_name": "Rochdale AFC",
    "source_url": "https://rochdaleafc.co.uk/dale-sign-will-jenkins/",
    "category": "sport",
    "area": "rochdale",
    "published_at": "2026-07-08T08:45:00Z",
}

INTERVIEW = {
    "title": "New Rochdale AFC arrival discusses move to the Crown Oil Arena",
    "excerpt": "The club has published an interview with new arrival Will Jenkins.",
    "content_html": (
        "<p>Will Jenkins discusses his move after signing for Rochdale AFC.</p>"
    ),
    "source_name": "Rochdale AFC",
    "source_url": "https://rochdaleafc.co.uk/hear-from-will-jenkins/",
    "category": "sport",
    "area": "rochdale",
    "published_at": "2026-07-08T09:00:00Z",
}

TICKETS = {
    "title": "Tickets go on sale for Rochdale AFC pre-season opener",
    "excerpt": "Supporters can now buy tickets for the first pre-season fixture.",
    "source_name": "Rochdale AFC",
    "source_url": "https://rochdaleafc.co.uk/pre-season-tickets/",
    "category": "sport",
    "area": "rochdale",
    "published_at": "2026-07-08T09:15:00Z",
}

assert same_story(SIGNING, INTERVIEW)
assert story_similarity(SIGNING, INTERVIEW) >= 0.72
assert not same_story(SIGNING, TICKETS)

deduped = dedupe_article_records([INTERVIEW, SIGNING, TICKETS])
assert len(deduped) == 2
jenkins = next(item for item in deduped if "Will Jenkins" in item["title"])
assert "sign" in jenkins["title"].lower()
assert jenkins["source_count"] == 2
assert build_story_key(SIGNING) == build_story_key(INTERVIEW)

print("Story identity regression tests passed.")
