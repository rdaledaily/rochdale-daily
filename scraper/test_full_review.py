"""Tests for full_review: the editor's review of every article (12 Nov 2026).

The model is replaced by a scripted fake so these run in CI without network
or cost. Every case is a real failure from the 11-12 Nov review.
"""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import full_review as fr

WHEN = datetime(2026, 11, 12, 21, 30, tzinfo=timezone.utc)
URL = "https://www.rochdale.gov.uk/directory-record/2657/wardle-village-carol-concert-road-closure"
SOURCE = (
    "Wardle Village Carol Concert, road closure in Wardle on 24 December 2026. "
    "Expected start and finish 5.30pm-7.30pm on Thursday, 24 December 2026. "
    "Reason To hold the Wardle Village Christmas Eve Carol Concert. The part of Ramsden Road "
    "between the junctions with Crossfield Road and Wardle Fold will be temporarily closed. "
    "There will be no alternative route for vehicles. Organised by Rochdale Borough Council."
)
STORY = {
    "id": "9f8d8a4fb0a3d2c7f7",
    "slug": "road-closure-for-wardle-village-carol-concert",
    "title": "Road closure for Wardle Village Carol Concert on 24 December 2026",
    "excerpt": "Ramsden Road in Wardle will be temporarily closed for the Wardle Village Carol Concert.",
    "content_html": (
        "<p>Ramsden Road in Wardle will be temporarily closed on 24 December 2026 from 5.30pm to 7.30pm "
        "for the Wardle Village Carol Concert.</p>"
        "<p>A spokesperson from Rochdale Borough Council confirmed the details of the closure, "
        "emphasising the importance of ensuring safety during the event.</p>"
    ),
    "source_urls": [URL],
    "source_names": ["Rochdale Borough Council"],
    "category": "traffic",
    "area": "wardle",
    "published_at": "2026-11-11T22:03:11Z",
    "first_published_at": "2026-11-11T22:03:11Z",
}
FIXED = {
    "changed": True,
    "title": "Ramsden Road in Wardle to close for Christmas Eve carol concert",
    "excerpt": "Part of Ramsden Road in Wardle will close from 5.30pm to 7.30pm on Thursday 24 December 2026 for the carol concert.",
    "paragraphs": [
        "Part of Ramsden Road in Wardle will be closed between Crossfield Road and Wardle Fold from 5.30pm to 7.30pm on Thursday 24 December 2026.",
        "The closure is for the Wardle Village Christmas Eve Carol Concert. There will be no alternative route for vehicles.",
    ],
    "development": False,
}


class FakeClient:
    """Returns scripted JSON replies in order; records how often it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_):
        self.calls += 1
        reply = self.replies.pop(0) if self.replies else {"changed": False}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))])


def site(tmp: Path) -> Path:
    (tmp / "manual_articles.d").mkdir()
    (tmp / "reports").mkdir()
    (tmp / "story_blocklist.json").write_text(json.dumps({"slugs": [], "title_patterns": [], "source_urls": []}), encoding="utf-8")
    return tmp


def test_invented_statement_is_corrected_with_a_note():
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        verdict = fr.review(dict(STORY), FakeClient(FIXED), fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "corrected", verdict
        record = json.loads(Path(verdict["written_to"]).read_text(encoding="utf-8"))
        assert record["id"] == STORY["id"] and record["slug"] == STORY["slug"]
        assert "spokesperson" not in record["body"]
        note = record["corrections"][-1]
        assert note["date"] == "2026-11-12"
        assert note["note"].startswith("Corrected on 12 November 2026")
        assert "attributed a statement" in note["note"]
        assert record["editorial_lock"] is True


def test_story_that_cannot_be_fixed_is_taken_down():
    still_wrong = dict(FIXED, paragraphs=FIXED["paragraphs"] + [
        "A council spokesperson said the closure was essential for the safety of all concert-goers this year."])
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        client = FakeClient(still_wrong, still_wrong, still_wrong)
        verdict = fr.review(dict(STORY), client, fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "taken_down", verdict
        assert client.calls == 3
        blocked = json.loads((root / "story_blocklist.json").read_text(encoding="utf-8"))["slugs"]
        assert STORY["slug"] in blocked



def test_model_that_first_declines_is_told_what_is_wrong():
    seen = []

    class Recording(FakeClient):
        def _create(self, **kwargs):
            seen.append(kwargs["messages"][1]["content"])
            return super()._create(**kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        client = Recording({"changed": False}, FIXED)
        verdict = fr.review(dict(STORY), client, fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "corrected", verdict
        assert "attribute statements" in seen[1]

def test_unreadable_source_is_never_rewritten_or_taken_down():
    def down(url):
        raise ConnectionError("timeout")

    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        client = FakeClient(FIXED)
        verdict = fr.review(dict(STORY), client, fetcher=down, when=WHEN, root=root)
        assert verdict["outcome"] == "unchecked"
        assert client.calls == 0
        assert not list((root / "manual_articles.d").glob("*.json"))


def test_accurate_story_passes_untouched():
    accurate = dict(STORY, content_html="<p>Ramsden Road in Wardle will be temporarily closed on 24 December 2026 from 5.30pm to 7.30pm for the Wardle Village Carol Concert.</p>")
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        verdict = fr.review(accurate, FakeClient({"changed": False}), fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "passed", verdict
        assert not list((root / "manual_articles.d").glob("*.json"))



def test_cosmetic_rewrite_of_an_accurate_story_is_discarded():
    accurate = dict(STORY, content_html="<p>Ramsden Road in Wardle will be temporarily closed on 24 December 2026 from 5.30pm to 7.30pm for the Wardle Village Carol Concert.</p>")
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        verdict = fr.review(accurate, FakeClient(dict(FIXED, development=False)), fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "passed", verdict
        assert not list((root / "manual_articles.d").glob("*.json"))


def test_reported_development_is_published_as_an_update():
    accurate = dict(STORY, content_html="<p>Ramsden Road in Wardle will be temporarily closed on 24 December 2026 from 5.30pm to 7.30pm for the Wardle Village Carol Concert.</p>")
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        verdict = fr.review(accurate, FakeClient(dict(FIXED, development=True)), fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "corrected", verdict
        assert verdict["note"].startswith("Updated on 12 November 2026 with later information")

def test_hand_written_story_is_corrected_in_its_own_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        own = root / "manual_articles.d" / "wardle-closure.json"
        own.write_text(json.dumps({"id": STORY["id"], "slug": STORY["slug"], "title": STORY["title"],
                                   "body": "Old body.", "manual_article": True}), encoding="utf-8")
        row = dict(STORY, manual_article=True)
        verdict = fr.review(row, FakeClient(FIXED), fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "corrected", verdict
        assert verdict["written_to"] == str(own)
        record = json.loads(own.read_text(encoding="utf-8"))
        assert record["title"] == FIXED["title"] and record["corrections"]
        assert len(list((root / "manual_articles.d").glob("*.json"))) == 1


def test_story_with_no_source_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        verdict = fr.review(dict(STORY, source_urls=[], source_url=""), FakeClient(), fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict == {**verdict, "outcome": "unchecked", "reason": "no source recorded"}


def test_batch_resumes_and_orders_crime_first():
    accurate = "<p>Ramsden Road in Wardle will be temporarily closed on 24 December 2026 for the Wardle Village Carol Concert.</p>"
    rows = [
        dict(STORY, slug="community-new", category="community", content_html=accurate, first_published_at="2026-11-11T10:00:00Z"),
        dict(STORY, slug="crime-old", category="crime", content_html=accurate, first_published_at="2026-10-01T10:00:00Z"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        (root / "articles.json").write_text(json.dumps(rows), encoding="utf-8")
        counts = fr.run("live", 1, 5, client=FakeClient({"changed": False}, {"changed": False}), fetcher=lambda u: SOURCE, root=root)
        state = json.loads((root / "reports" / "full_review_state.json").read_text(encoding="utf-8"))
        assert list(state) == ["crime-old"] and counts["remaining"] == 1
        fr.run("live", 5, 5, client=FakeClient({"changed": False}), fetcher=lambda u: SOURCE, root=root)
        state = json.loads((root / "reports" / "full_review_state.json").read_text(encoding="utf-8"))
        assert set(state) == {"crime-old", "community-new"}


def test_archived_page_without_record_is_read_from_its_html():
    page = (
        '<html><head><meta property="og:image" content="https://rochdaledaily.co.uk/assets/img/cards/x.jpg">'
        '<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","datePublished":"2026-08-06T16:51:00Z","articleSection":"Crime"}]}</script>'
        '</head><body><h1>Rochdale woman banned from owning animals</h1><p class="article-standfirst">A woman was banned.</p>'
        '<div class="article-copy"><p>A woman, 44, was banned from owning animals.</p>'
        '<div class="ad-slot">ad</div><details class="article-sources"><summary>Sources</summary><ul>'
        '<li><a href="https://www.manchestereveningnews.co.uk/news/x-34416762">Open source 1</a></li></ul></details></div>'
        '</body></html>'
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "articles").mkdir()
        (root / "articles" / "woman-banned.html").write_text(page, encoding="utf-8")
        record = fr.page_record("woman-banned", root)
        assert record["title"] == "Rochdale woman banned from owning animals"
        assert record["source_urls"] == ["https://www.manchestereveningnews.co.uk/news/x-34416762"]
        assert record["category"] == "crime" and record["published_at"].startswith("2026-08-06")
        assert "ad" not in record["content_html"] and "44" in record["content_html"]



APPROVED = dict(STORY, slug="planning-decision", title="Council approves Wardle carol concert closure",
                content_html="<p>Rochdale Borough Council approved the plan for the Wardle Village Carol Concert closure on Ramsden Road.</p>")
REJECTED_SOURCE = SOURCE + " The council rejected the plan for a second closure on Ramsden Road after objections from residents."


def test_factual_error_the_checker_cannot_see_is_corrected_when_proven():
    # fidelity_issues tests words, not meaning: "approved" vs "rejected" passes it.
    from source_fidelity import fidelity_issues
    assert fidelity_issues("The council approved the plan.", "The council rejected the plan.") == []
    fix = dict(FIXED, title="Council rejects second Ramsden Road closure",
               paragraphs=["The council rejected the plan for a second closure on Ramsden Road after objections from residents."],
               factual_corrections=[{"was": "approved the plan", "now": "rejected the plan",
                                     "source_quote": "The council rejected the plan for a second closure on Ramsden Road"}])
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        verdict = fr.review(dict(APPROVED), FakeClient(fix), fetcher=lambda u: REJECTED_SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "corrected", verdict
        assert "reports differently" in verdict["note"]


def test_unproven_factual_claim_goes_to_the_editor():
    claim = dict(FIXED, factual_corrections=[{"was": "approved the plan", "now": "deferred the plan",
                                              "source_quote": "the plan was deferred until the next meeting of the committee"}])
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        verdict = fr.review(dict(APPROVED), FakeClient(claim), fetcher=lambda u: REJECTED_SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "flagged", verdict
        assert verdict["claims"][0]["now"] == "deferred the plan"
        assert not list((root / "manual_articles.d").glob("*.json"))


def test_hand_written_story_in_a_dated_subfolder_is_found():
    with tempfile.TemporaryDirectory() as tmp:
        root = site(Path(tmp))
        nested = root / "manual_articles.d" / "2026" / "10"
        nested.mkdir(parents=True)
        own = nested / "2026-10-24-wardle-closure.json"
        own.write_text(json.dumps({"id": STORY["id"], "slug": STORY["slug"], "title": STORY["title"],
                                   "body": "Old body.", "manual_article": True}), encoding="utf-8")
        verdict = fr.review(dict(STORY, manual_article=True), FakeClient(FIXED), fetcher=lambda u: SOURCE, when=WHEN, root=root)
        assert verdict["outcome"] == "corrected", verdict
        assert verdict["written_to"] == str(own)
        assert json.loads(own.read_text(encoding="utf-8"))["corrections"]

if __name__ == "__main__":
    failures = []
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures.append(name)
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(f"{len(failures)} full-review test(s) failed")
    print("all full-review tests passed")
