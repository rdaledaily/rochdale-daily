"""A rewrite that never says "Rochdale" is not binned when its source does.

17 Nov 2026: the Springhill Hospice break-ins rewrite named Molesworth Street
and "the Oldham Road shop" but not the town, and the final locality check
(which reads only the finished article) rejected it as non-local twice.

Run: PYTHONPATH=scraper python scraper/test_locality_source_evidence.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scraper as core  # noqa: E402

SOURCE = SimpleNamespace(
    source_title="Police probe 'horrific spate of attacks against hospice' - Rochdale Times",
    source_summary="Thieves have caused thousands of pounds worth of damage after four break-ins at Springhill Hospice shops.",
    source_body_excerpt=(
        "The hospice's home and furniture shop at Jacksons Corner, Molesworth Street, "
        "Rochdale, was targeted for the third time yesterday, after a break-in at the "
        "Oldham Road shop on Saturday morning."
    ),
    event_location="",
)

REWRITE = {
    "title": "Police investigate series of break-ins at Springhill Hospice shops",
    "excerpt": "Four break-ins at Springhill Hospice shops in two weeks have caused thousands of pounds of damage.",
    "content_html": "<p>The furniture shop at Jacksons Corner, Molesworth Street, was hit after a break-in at the Oldham Road shop.</p>",
    "source_name": "Rochdale Times",
    "source_url": "https://www.rochdaletimes.co.uk/police-probe-horrific-spate-of-attacks-against-hospice/",
    "area": "rochdale",
    "category": "crime",
}

FAILURES = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILURES.append(label)


evidence = core.source_locality_evidence(SOURCE)
check(evidence == ["Rochdale"], f"source evidence is the borough place only ({evidence})")
check(not core.article_passes_locality(REWRITE), "without evidence the rewrite alone is not provably local (old behaviour)")
check(core.article_passes_locality(dict(REWRITE, locality_evidence=evidence)), "with the source's place, the rewrite passes")

# The veto still wins: evidence from the source never rescues a rewrite that
# names a place outside the borough.
foreign = dict(REWRITE, content_html="<p>Police in Castleton, New York, are investigating break-ins.</p>",
               locality_evidence=["Castleton"])
check(not core.article_passes_locality(foreign), "foreign geography in the rewrite is still rejected")

# A source that never places the story in the borough gives no evidence.
elsewhere = SimpleNamespace(source_title="Break-ins at Leeds shops", source_summary="Shops in Leeds were hit.",
                            source_body_excerpt="", event_location="")
check(core.source_locality_evidence(elsewhere) == [], "no borough place in the source, no evidence")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("all locality source-evidence checks passed")
