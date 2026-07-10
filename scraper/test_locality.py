from locality_rules import AREA_KEYWORDS, detect_area, is_local, locality_evidence

CASES = [
    # ------------------------------------------------------------------
    # Original regression cases (all previous behaviour preserved).
    # ------------------------------------------------------------------
    (
        False,
        "Queen Elizabeth II favoured Kate Middleton's wedding over Princess Diana's",
        "BBC News",
        "",
        "Kate Middleton is a person, not the town of Middleton",
    ),
    (
        False,
        "Ella Langley achieves Billboard milestone",
        "Music News",
        "",
        "Ella Langley is a person and Langley is not an accepted locality",
    ),
    (
        False,
        "Actor David Wardle wins television award",
        "Entertainment News",
        "",
        "Wardle used as a surname must not count",
    ),
    (
        False,
        "Historian Bill Heywood receives national award",
        "National News",
        "",
        "Heywood used as a surname must not count",
    ),
    (
        True,
        "Police have closed a road in Middleton after a collision",
        "Regional News",
        "",
        "Explicit geographical wording",
    ),
    (
        True,
        "Middleton residents are invited to a council meeting",
        "Regional News",
        "",
        "Place followed by residents",
    ),
    (
        True,
        "Flood warning issued for Wardle village",
        "Environment Agency",
        "",
        "Place followed by village",
    ),
    (
        True,
        "Heywood pub announces reopening date",
        "Regional News",
        "",
        "Place followed by pub",
    ),
    (
        True,
        "Ella Langley will perform at Rochdale Town Hall",
        "Events Listing",
        "",
        "The event has an explicit Rochdale location",
    ),
    (
        True,
        "Service update",
        "Rochdale Borough Council",
        "https://www.rochdale.gov.uk/news/example",
        "Trusted local first-party source",
    ),
    (
        False,
        "Local council update",
        "Rochdale Times",
        "https://www.rochdaletimes.co.uk/example",
        "Explicitly denied source",
    ),
    (
        False,
        "Royal experts have recently reflected on Kate Middleton's strong "
        "message directed at Prince Harry during his visit to the UK. This "
        "commentary comes amidst ongoing discussions about the royal "
        "family's dynamics and public perceptions. The message from "
        "Middleton is seen as significant given the current climate "
        "surrounding the royal family.",
        "Royal News",
        "",
        "Second mention drops to bare surname ('from Middleton'); must "
        "still be recognised as the same person, not a place",
    ),
    (
        False,
        "David Wardle said he was proud of the award. Wardle added that it "
        "meant a great deal to his family.",
        "National News",
        "",
        "Surname repeated with no place context anywhere in the article",
    ),
    (
        True,
        "Flooding from Middleton has affected several roads this morning, "
        "police have confirmed.",
        "Regional News",
        "",
        "Genuine place usage via 'from' with no full personal name present "
        "must still count",
    ),
    (
        True,
        "Councillor John Wardle spoke at a meeting in Wardle village last "
        "night about flooding concerns.",
        "Rochdale News",
        "",
        "A person with an ambiguous surname is fine when the article also "
        "gives real geographic context (Wardle village)",
    ),
    # ------------------------------------------------------------------
    # New cases: impostor places and rival geography.
    # ------------------------------------------------------------------
    (
        False,
        "A man has been arrested following a two-vehicle collision that "
        "occurred near Norden on 9 July. Police responded promptly to the "
        "scene and enquiries are ongoing.",
        "Swanage News",
        "",
        "LIVE FALSE POSITIVE 1: Norden in Dorset. The body never names "
        "Dorset, but the source name 'Swanage News' identifies the wrong "
        "Norden",
    ),
    (
        False,
        "Lightnin' Willie and the Poorboys are set to perform at Norden "
        "Farm Centre for the Arts in Maidenhead. The venue regularly hosts "
        "live music and cultural events.",
        "Ents24",
        "",
        "LIVE FALSE POSITIVE 2: Norden Farm is in Maidenhead, Berkshire",
    ),
    (
        False,
        "Visitors flocked to the Blue John Cavern in Castleton in the "
        "Peak District over the weekend.",
        "Derbyshire Times",
        "",
        "Castleton in Derbyshire's Hope Valley is not Castleton, Rochdale",
    ),
    (
        False,
        "Walkers were rescued near Bamford in the Hope Valley after "
        "getting into difficulty on Bamford Edge.",
        "Mountain Rescue News",
        "",
        "Bamford in Derbyshire is not Bamford, Rochdale",
    ),
    (
        False,
        "A new independent café has opened in Meanwood, Leeds, drawing "
        "long queues on its first weekend.",
        "Leeds Live",
        "",
        "Meanwood in Leeds is not Meanwood, Rochdale",
    ),
    (
        False,
        "A new exhibition has opened at the Whitworth Art Gallery, with "
        "free entry throughout the summer.",
        "Arts News",
        "",
        "The Whitworth Art Gallery in Manchester is not Whitworth town",
    ),
    (
        False,
        "Roadworks in Heywood, Wiltshire will close the A350 overnight "
        "for a week from Monday.",
        "Wiltshire Council News",
        "",
        "Heywood in Wiltshire is not Heywood, Rochdale",
    ),
    (
        False,
        "Firefighters attended a barn blaze in Wardle, Cheshire, near "
        "Nantwich, in the early hours of this morning.",
        "Cheshire Fire Service",
        "",
        "Wardle in Cheshire is not Wardle, Rochdale",
    ),
    (
        False,
        "Emergency services attended a collision near Norden yesterday "
        "evening. The road was closed at the junction, BH20 5AJ, while "
        "recovery took place.",
        "Regional News",
        "",
        "A postcode outside the OL / M / BL areas is rival geography",
    ),
    (
        False,
        "Delays are expected at Hopwood Park services on the M42 after a "
        "lorry shed its load this morning.",
        "Motorway Traffic News",
        "",
        "Hopwood Park services in Worcestershire is not Hopwood, Heywood",
    ),
    # ------------------------------------------------------------------
    # New cases: genuine local stories must still pass.
    # ------------------------------------------------------------------
    (
        True,
        "A man has been arrested following a two-vehicle collision near "
        "Norden yesterday evening. Police closed the road while recovery "
        "took place.",
        "Regional News",
        "",
        "The same Norden wording with no rival geography anywhere must "
        "still be accepted",
    ),
    (
        True,
        "Roadworks in Castleton, Rochdale will continue for a further two "
        "weeks, the council has confirmed.",
        "Regional News",
        "",
        "An explicit Rochdale mention keeps the story local",
    ),
    (
        True,
        "A Rochdale man has been jailed after a hearing at Dorchester "
        "Crown Court, police confirmed.",
        "Court Reporter",
        "",
        "Rival geography must never override a genuine Rochdale mention",
    ),
    (
        True,
        "Crowds gathered at Hollingworth Lake for the annual open-water "
        "swim despite grey skies.",
        "Regional News",
        "",
        "A specific multi-word local place is strong evidence on its own",
    ),
    (
        True,
        "Flooding closed several roads in Littleborough this morning, "
        "with buses diverted via Smithy Bridge.",
        "Regional News",
        "",
        "Ordinary borough news wording must keep passing",
    ),
    (
        True,
        "Service update",
        "Rochdale Borough Council",
        "https://www.rochdale.gov.uk/news/london-marathon-fundraisers",
        "A trusted first-party source stays local even when the item "
        "mentions rival geography in its URL",
    ),
    (
        True,
        "Upcoming Bookstart events at Castleton Library are designed to "
        "cultivate a love for reading in infants and toddlers, encouraging "
        "parents to participate in reading activities.",
        "Eventbrite",
        "",
        "The gerund 'reading' must never be mistaken for the town of "
        "Reading (live over-veto found in impact analysis)",
    ),
    (
        True,
        "Terrence King is on trial for the alleged murder of 15-year-old "
        "Devon Simmonds-Caines in Middleton last year. The community in "
        "Middleton is grappling with the implications.",
        "BBC Manchester",
        "",
        "'Devon' as a person's first name must never count as the county "
        "of Devon (live over-veto found in impact analysis)",
    ),
    (
        False,
        "Two people were rescued from the water off the coast in Devon "
        "yesterday, near Middleton beach car park.",
        "Coastguard News",
        "",
        "'in Devon' used as a real place must still veto an otherwise "
        "ambiguous Middleton mention",
    ),
]

for expected, text, source_name, source_url, reason in CASES:
    actual = is_local(text, source_name, source_url)
    assert actual is expected, (
        f"{reason}: expected {expected}, got {actual} for {text!r} "
        f"(evidence: {locality_evidence(text, source_name, source_url)})"
    )

assert detect_area(
    "Middleton residents are invited to a council meeting"
) == "middleton"

# Person names must produce no area.
assert detect_area(
    "Queen Elizabeth II favoured Kate Middleton's wedding"
) == ""
assert detect_area(
    "Ella Langley achieves Billboard milestone"
) == ""
assert detect_area(
    "Actor David Wardle wins television award"
) == ""
assert detect_area(
    "Historian Bill Heywood receives national award"
) == ""

# An untrusted caller cannot force a non-local story into Rochdale.
assert detect_area(
    "Queen Elizabeth II favoured Kate Middleton's wedding",
    fallback="rochdale",
    source_name="BBC News",
) == ""

# A verified local first-party source may use an explicit fallback.
assert detect_area(
    "Service update",
    fallback="rochdale",
    source_name="Rochdale Borough Council",
    source_url="https://www.rochdale.gov.uk/news/example",
) == "rochdale"

assert detect_area(
    "Ella Langley will perform at Rochdale Town Hall"
) == "rochdale"

assert "langley" not in AREA_KEYWORDS

# The reported false positive: surname re-mentioned bare later in the piece
# must not be picked up as an area.
assert detect_area(
    "Royal experts have recently reflected on Kate Middleton's strong "
    "message directed at Prince Harry during his visit to the UK. The "
    "message from Middleton is seen as significant given the current "
    "climate surrounding the royal family."
) == ""

# ---------------------------------------------------------------------------
# New detect_area cases: namesakes must never be tagged as borough areas.
# ---------------------------------------------------------------------------
assert detect_area(
    "Lightnin' Willie and the Poorboys are set to perform at Norden Farm "
    "Centre for the Arts in Maidenhead."
) == ""

assert detect_area(
    "A man has been arrested following a two-vehicle collision near Norden.",
    source_name="Swanage News",
) == ""

assert detect_area(
    "Visitors flocked to the Blue John Cavern in Castleton in the Peak "
    "District over the weekend."
) == ""

assert detect_area(
    "A new independent café has opened in Meanwood, Leeds."
) == ""

# The same wording without rival geography must still resolve to the borough
# area, so genuine Norden news keeps its area tag.
assert detect_area(
    "A man has been arrested following a two-vehicle collision near Norden.",
    source_name="Regional News",
) == "norden"

assert detect_area(
    "Roadworks in Castleton, Rochdale will continue for a further two weeks."
) == "castleton"

print(
    f"Locality regression tests passed: {len(CASES)} classification cases "
    "plus area tests."
)

assert not is_local(
    "Local news update",
    "Rochdale Online",
    "https://www.rochdaleonline.co.uk/news/example",
)
