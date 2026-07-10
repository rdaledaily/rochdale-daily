from story_identity import (
    build_story_key,
    canonicalise_url,
    dedupe_article_records,
    incident_fact_match,
    incident_locations,
    perpetrator_ethnicities,
    perpetrator_genders,
    precise_locations,
    same_story,
    story_similarity,
    victim_genders,
)

SIGNING = {
    "title": "Rochdale AFC signs midfielder Will Jenkins",
    "excerpt": (
        "Rochdale AFC has confirmed the signing of midfielder Will Jenkins "
        "from South Shields on a two-year deal."
    ),
    "content_html": "<p>Rochdale AFC has confirmed the signing of Will Jenkins.</p>",
    "source_name": "Rochdale AFC",
    "source_url": "https://rochdaleafc.co.uk/dale-sign-will-jenkins/",
    "category": "sport",
    "area": "rochdale",
    "published_at": "2026-07-08T08:45:00Z",
}

INTERVIEW = {
    "title": "New Rochdale AFC arrival discusses move to the Crown Oil Arena",
    "excerpt": "The club has published an interview with new arrival Will Jenkins.",
    "content_html": "<p>Will Jenkins discusses his move after signing for Rochdale AFC.</p>",
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
assert build_story_key(SIGNING) == build_story_key(INTERVIEW)

# Regression: the currently duplicated deportation headlines must become one
# ongoing record even though the old matcher scored them around 0.41-0.48.
GROOMING_UPDATES = [
    {
        "id": "old-canonical-id",
        "slug": "pakistan-wont-take-back-released-rochdale-grooming-gang-leader",
        "story_key": "crime-old-legacy-key-1",
        "title": "Pakistan ‘won’t take back’ released Rochdale grooming gang leader",
        "excerpt": "Pakistan will not accept the return of a released Rochdale grooming gang leader.",
        "source_name": "Publisher A",
        "source_url": "https://a.example/story",
        "category": "crime",
        "area": "rochdale",
        "published_at": "2026-07-09T09:45:00Z",
        "scraped_at": "2026-07-09T10:00:00Z",
        "police_matter": True,
    },
    {
        "story_key": "crime-old-legacy-key-2",
        "title": "Pakistan Declines to Repatriate Rochdale Grooming Gang Leader",
        "excerpt": "Pakistan has reportedly refused to accept the return of the gang leader.",
        "source_name": "Publisher B",
        "source_url": "https://b.example/story",
        "category": "crime",
        "area": "rochdale",
        "published_at": "2026-07-09T10:12:00Z",
        "scraped_at": "2026-07-09T10:20:00Z",
        "police_matter": True,
    },
    {
        "story_key": "crime-old-legacy-key-3",
        "title": "Pakistan Likely to Reject Deportation of Rochdale Grooming Gang Leader",
        "excerpt": "Legal changes may be needed because Pakistan is expected to refuse the deportation.",
        "source_name": "Publisher C",
        "source_url": "https://c.example/story",
        "category": "news",
        "area": "rochdale",
        "published_at": "2026-07-09T10:33:00Z",
        "scraped_at": "2026-07-09T10:40:00Z",
    },
    {
        "story_key": "crime-old-legacy-key-4",
        "title": "Law to be changed to allow deportation of Rochdale grooming gang leader - STV News",
        "excerpt": "The government plans to change the law to enable the deportation.",
        "source_name": "STV News",
        "source_url": "https://d.example/story",
        "category": "politics",
        "area": "rochdale",
        "published_at": "2026-07-09T10:45:00Z",
        "scraped_at": "2026-07-09T10:50:00Z",
    },
    {
        "story_key": "crime-old-legacy-key-5",
        "title": "Changes to Law Could Enable Deportation of Grooming Gang Leader from Rochdale",
        "excerpt": "Proposed amendments would enable the grooming gang leader to be deported.",
        "source_name": "Publisher E",
        "source_url": "https://e.example/story",
        "category": "crime",
        "area": "rochdale",
        "published_at": "2026-07-08T18:37:10Z",
        "scraped_at": "2026-07-09T10:55:00Z",
        "police_matter": True,
    },
    {
        "story_key": "crime-old-legacy-key-6",
        "title": "Burnham backs law change to allow deportation of Rochdale grooming gang leader - Messenger Newspapers",
        "excerpt": "Andy Burnham has backed the legal change concerning the gang leader's deportation.",
        "source_name": "Messenger Newspapers",
        "source_url": "https://f.example/story",
        "category": "crime",
        "area": "rochdale",
        "published_at": "2026-07-08T18:37:10Z",
        "scraped_at": "2026-07-09T11:00:00Z",
        "police_matter": True,
    },
]

for left in GROOMING_UPDATES:
    assert build_story_key(left) != left["story_key"]  # legacy keys are healed

clustered = dedupe_article_records(GROOMING_UPDATES)
assert len(clustered) == 1, [item["title"] for item in clustered]
ongoing = clustered[0]
assert ongoing["source_count"] == 6
assert ongoing["is_ongoing"] is True
assert ongoing["ongoing_label"] == "ONGOING"
assert ongoing["update_count"] == 6
assert ongoing["category"] == "crime"
assert ongoing["police_matter"] is True
assert ongoing["id"] == "old-canonical-id"
assert ongoing["slug"] == "pakistan-wont-take-back-released-rochdale-grooming-gang-leader"
assert " - STV News" not in ongoing["title"]

# Do not merge a different grooming-gang subject merely because it shares the
# broad phrase.  It lacks the same leader/deportation identity.
SURVIVOR_INQUIRY = {
    "title": "Rochdale grooming gang survivor calls for a new public inquiry",
    "excerpt": "A survivor has called for a fresh inquiry into institutional failures.",
    "source_name": "Publisher G",
    "source_url": "https://g.example/story",
    "category": "crime",
    "area": "rochdale",
    "published_at": "2026-07-09T11:10:00Z",
}
assert not same_story(GROOMING_UPDATES[0], SURVIVOR_INQUIRY)

# Empty URLs must never be treated as the same canonical URL.
EMPTY_URL_A = {
    "title": "Council approves new town-centre market plan",
    "category": "politics",
    "area": "rochdale",
    "published_at": "2026-07-09T08:00:00Z",
}
EMPTY_URL_B = {
    "title": "Police appeal after burglary in Heywood",
    "category": "crime",
    "area": "heywood",
    "published_at": "2026-07-09T08:00:00Z",
}
assert canonicalise_url("") == ""
assert not same_story(EMPTY_URL_A, EMPTY_URL_B)

# The ongoing window is deliberately bounded.
OLD_UPDATE = dict(GROOMING_UPDATES[0])
OLD_UPDATE["source_url"] = "https://old.example/story"
OLD_UPDATE["published_at"] = "2026-06-01T09:45:00Z"
assert not same_story(OLD_UPDATE, GROOMING_UPDATES[1])

# Original regression remains intact.
deduped = dedupe_article_records([INTERVIEW, SIGNING, TICKETS])
assert len(deduped) == 2
jenkins = next(item for item in deduped if "Will Jenkins" in item["title"])
assert "sign" in jenkins["title"].lower()
assert jenkins["source_count"] == 2
assert jenkins["is_ongoing"] is True


# Regression: the two Littleborough fire reports shown on the homepage are the
# same ongoing incident.  "blaze" == "fire" and "mum" == "mother".
LITTLEBOROUGH_FIRE_A = {
    "id": "littleborough-fire-canonical",
    "slug": "escaping-blaze-neighbours-rally-around-littleborough-family",
    "title": (
        "Escaping blaze with their lives, neighbours now rallying around "
        "Littleborough family left with nothing"
    ),
    "excerpt": (
        "A mother and her baby escaped the house fire in Littleborough with "
        "only the clothes they were wearing."
    ),
    "source_name": "Publisher Fire A",
    "source_url": "https://fire-a.example/littleborough-family",
    "category": "news",
    "area": "littleborough",
    "published_at": "2026-07-09T07:00:00Z",
}

LITTLEBOROUGH_FIRE_B = {
    "title": (
        "Mum and baby with just clothes on their backs after escaping house fire"
    ),
    "excerpt": (
        "The mother and child escaped a fire at their Littleborough home before "
        "neighbours began collecting essentials."
    ),
    "source_name": "Publisher Fire B",
    "source_url": "https://fire-b.example/mum-baby-house-fire",
    "category": "news",
    # Deliberately broad/misaligned metadata: the explicit title/body locality
    # still proves that both reports concern Littleborough.
    "area": "rochdale",
    "published_at": "2026-07-09T08:15:00Z",
}

assert victim_genders(LITTLEBOROUGH_FIRE_A) == {"female"}
assert victim_genders(LITTLEBOROUGH_FIRE_B) == {"female"}
assert "littleborough" in incident_locations(LITTLEBOROUGH_FIRE_A)
assert "littleborough" in incident_locations(LITTLEBOROUGH_FIRE_B)
assert incident_fact_match(LITTLEBOROUGH_FIRE_A, LITTLEBOROUGH_FIRE_B)
assert same_story(LITTLEBOROUGH_FIRE_A, LITTLEBOROUGH_FIRE_B)
fire_cluster = dedupe_article_records([LITTLEBOROUGH_FIRE_A, LITTLEBOROUGH_FIRE_B])
assert len(fire_cluster) == 1
assert fire_cluster[0]["source_count"] == 2
assert fire_cluster[0]["id"] == "littleborough-fire-canonical"

# Regression: same perpetrator gender + same explicitly stated ethnicity +
# same location + same crime also forces an ongoing-story merge.
ROBBERY_A = {
    "title": "Police seek Asian man after robbery on Yorkshire Street",
    "excerpt": "An Asian male suspect is wanted after a robbery on Yorkshire Street.",
    "source_name": "Publisher Robbery A",
    "source_url": "https://robbery-a.example/yorkshire-street",
    "category": "crime",
    "area": "rochdale",
    "published_at": "2026-07-09T09:00:00Z",
}
ROBBERY_B = {
    "title": "Asian male suspect wanted over Yorkshire Street robbery",
    "excerpt": "Police are appealing for information about the Asian man wanted for robbery.",
    "source_name": "Publisher Robbery B",
    "source_url": "https://robbery-b.example/yorkshire-street",
    "category": "crime",
    "area": "rochdale",
    "published_at": "2026-07-09T11:00:00Z",
}
assert perpetrator_genders(ROBBERY_A) == {"male"}
assert perpetrator_genders(ROBBERY_B) == {"male"}
assert "asian" in perpetrator_ethnicities(ROBBERY_A)
assert "asian" in perpetrator_ethnicities(ROBBERY_B)
assert incident_fact_match(ROBBERY_A, ROBBERY_B)
assert same_story(ROBBERY_A, ROBBERY_B)

DIFFERENT_ROBBERY = dict(ROBBERY_B)
DIFFERENT_ROBBERY["source_url"] = "https://robbery-c.example/drake-street"
DIFFERENT_ROBBERY["title"] = "Asian male suspect wanted over Drake Street robbery"
DIFFERENT_ROBBERY["excerpt"] = "Police want an Asian man after a robbery on Drake Street."
assert not incident_fact_match(ROBBERY_A, DIFFERENT_ROBBERY)


# Regression: the Milnrow farm fire and the grooming-gang deportation case are
# unrelated stories and must never merge, even though both are crime items in
# the borough on the same day.
FARM_FIRE = {
    "title": "Murder investigation launched following fatal fire at Rochdale farm",
    "excerpt": (
        "Emergency services were called to Tunshill Farm in Milnrow on "
        "9 July 2026. A woman was pronounced dead at the scene."
    ),
    "content_html": (
        "<p>A woman died following a fire at Tunshill Farm in Milnrow "
        "on 9 July 2026. A person was arrested.</p>"
    ),
    "category": "crime",
    "area": "milnrow",
    "event_location": "Tunshill Farm, Milnrow",
    "published_at": "2026-07-09T10:00:00Z",
    "source_url": "https://example.com/farm-fire",
}

assert not same_story(FARM_FIRE, GROOMING_UPDATES[0])
assert not same_story(FARM_FIRE, GROOMING_UPDATES[3])
separated = dedupe_article_records([FARM_FIRE, GROOMING_UPDATES[0], GROOMING_UPDATES[3]])
assert len(separated) == 2, [item["title"] for item in separated]

# Regression: a contaminated legacy record whose text mixes two stories must
# not act as a bridge that chains the two unrelated clusters together.  With
# complete-linkage clustering it can join at most one cluster, and only if it
# fully matches every member of that cluster.
CONTAMINATED_BRIDGE = {
    "title": "Murder investigation launched following fatal fire at Rochdale farm",
    "excerpt": (
        "A woman died in a fire at Tunshill Farm in Milnrow. Pakistan has "
        "refused to accept the return of the released Rochdale grooming "
        "gang leader."
    ),
    "content_html": (
        "<p>A woman died following a blaze at Tunshill Farm. Ministers "
        "consider law changes to deport the grooming gang leader to "
        "Pakistan.</p>"
    ),
    "category": "crime",
    "area": "rochdale",
    "published_at": "2026-07-09T11:00:00Z",
    "source_url": "https://old.example/contaminated",
}

bridged = dedupe_article_records(
    [GROOMING_UPDATES[0], CONTAMINATED_BRIDGE, GROOMING_UPDATES[3], FARM_FIRE]
)
assert len(bridged) >= 2, [item["title"] for item in bridged]
deportation_records = [
    item for item in bridged
    if "grooming" in str(item.get("title") or "").lower()
]
for item in deportation_records:
    surface = " ".join([
        str(item.get("title") or ""),
        str(item.get("excerpt") or ""),
    ]).lower()
    assert not ("farm" in surface and "fire" in surface), item.get("title")

print("Story identity regression tests passed.")

# ---------------------------------------------------------------------------
# Venue divergence: two DIFFERENT programmes at the same venue must never
# merge. Live failure: a football-sessions headline published over a
# back-care-yoga body because both were "announced at Whitworth Swimming
# Baths" and the venue's own words satisfied every overlap check.
# ---------------------------------------------------------------------------
FOOTBALL_SESSIONS = {
    "title": "Indoor 5 A Side Football Sessions Announced at Whitworth Swimming Baths",
    "summary": (
        "Indoor five-a-side football sessions for adults will run weekly at "
        "Whitworth Swimming Baths sports hall."
    ),
    "category": "events",
    "area": "whitworth",
    "published_at": "2026-07-09T10:00:00Z",
    "source_name": "Your Trust",
    "source_url": "https://example.org/football-sessions",
}
YOGA_SESSIONS = {
    "title": "Back Care Yoga Sessions Announced at Whitworth Swimming Baths",
    "summary": (
        "New Back Care Yoga sessions are set to begin at Whitworth Swimming "
        "Baths, aimed at improving posture and alleviating back pain."
    ),
    "category": "events",
    "area": "whitworth",
    "published_at": "2026-07-09T14:00:00Z",
    "source_name": "Your Trust",
    "source_url": "https://example.org/yoga-sessions",
}
YOGA_SECOND_OUTLET = {
    "title": "New back care yoga classes to start at Whitworth Swimming Baths",
    "summary": (
        "Weekly back care yoga sessions aimed at posture and back pain begin "
        "at Whitworth Swimming Baths this month."
    ),
    "category": "events",
    "area": "whitworth",
    "published_at": "2026-07-09T18:00:00Z",
    "source_name": "Rochdale Observer",
    "source_url": "https://example.org/yoga-observer",
}

assert not same_story(FOOTBALL_SESSIONS, YOGA_SESSIONS), (
    "different programmes at the same venue must not merge"
)
# The same programme reported by two outlets is a genuine duplicate.
assert same_story(YOGA_SESSIONS, YOGA_SECOND_OUTLET)
venue_clusters = dedupe_article_records(
    [FOOTBALL_SESSIONS, YOGA_SESSIONS, YOGA_SECOND_OUTLET]
)
assert len(venue_clusters) == 2, [item["title"] for item in venue_clusters]

# ---------------------------------------------------------------------------
# Title-case robustness: the same incident published in Title Case and in
# sentence case must merge despite the fake capitalised "entities" Title
# Case creates.
# ---------------------------------------------------------------------------
TITLE_CASE_REPORT = {
    "title": "Man Charged After Serious Assault On Yorkshire Street In Rochdale",
    "summary": "A Man Has Been Charged Following A Serious Assault On Yorkshire Street.",
    "category": "crime",
    "area": "rochdale",
    "published_at": "2026-07-09T10:00:00Z",
    "source_name": "GMP",
    "source_url": "https://example.org/title-case",
}
SENTENCE_CASE_REPORT = {
    "title": "Man charged after serious assault on Yorkshire Street",
    "summary": (
        "Police have charged a man after a serious assault on Yorkshire "
        "Street in Rochdale town centre."
    ),
    "category": "crime",
    "area": "rochdale",
    "published_at": "2026-07-09T12:00:00Z",
    "source_name": "MEN",
    "source_url": "https://example.org/sentence-case",
}
assert same_story(TITLE_CASE_REPORT, SENTENCE_CASE_REPORT)

print("Venue-divergence and title-case regression tests passed.")
