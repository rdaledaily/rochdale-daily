"""Regression for Codex findings across newsroom archive, legal review, and robots.

Run: PYTHONPATH=scraper python -m unittest scraper.test_codex_review_safeguards
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main, mock

import scraper as core
from independent_fact_review import verify
from audit_published_news import audit
import source_evidence_capture as capture


class CodexReviewFixes(TestCase):
    def test_unrelated_archive_stories_keep_distinct_slugs(self):
        originals=[
            {"slug":"missing-child-appeal","title":"Missing child appeal","source_url":"https://example.com/a",
             "source_kind":"event","category":"news","editorial_lock":True},
            {"slug":"police-misconduct-report","title":"Police misconduct report","source_url":"https://example.com/b",
             "source_kind":"event","category":"news","editorial_lock":True},
            {"slug":"curzon-road-murder","title":"Curzon Road murder","source_url":"https://example.com/c",
             "source_kind":"event","category":"news","editorial_lock":True},
        ]
        with mock.patch.object(core,"load_json_list",return_value=originals), \
             mock.patch.object(core,"load_story_blocklist",return_value={"slugs":[],"source_urls":[],"title_patterns":[]}), \
             mock.patch.object(core,"is_blocked_article",return_value=False), \
             mock.patch.object(core,"source_is_denied",return_value=False), \
             mock.patch.object(core,"article_is_low_quality",return_value=False), \
             mock.patch.object(core,"article_passes_locality",return_value=True), \
             mock.patch.object(core,"dedupe_article_records",side_effect=AssertionError("fuzzy merge called")):
            kept=core.recent_existing_articles()
        self.assertEqual([a["slug"] for a in kept],[a["slug"] for a in originals])

    def test_published_slug_cannot_be_reopened_after_takedown(self):
        url="https://www.rochdaletimes.co.uk/report-on-today/"
        blocked={"title_patterns":[],"source_urls":[],"slugs":["manually-removed-story"]}
        ledger={url:{"outcome":"published","reason":"","title":"Report on today",
                     "source_name":"Rochdale Times","urls":[url],
                     "published_slug":"manually-removed-story"}}
        with mock.patch.object(core,"load_rewrite_ledger",return_value=ledger), \
             mock.patch.object(core,"load_story_blocklist",return_value=blocked):
            stats=core.reconcile_rewrite_ledger_with_feed([])
            self.assertEqual(stats["deliberately_blocked"],1)
            self.assertEqual(ledger[url]["outcome"],"published")

    def test_legacy_ledger_without_slug_is_not_reopened_when_slugs_blocked(self):
        url="https://www.rochdaletimes.co.uk/old-report/"
        ledger={url:{"outcome":"published","reason":"","title":"Old report",
                     "source_name":"Rochdale Times","urls":[url]}}
        blocked={"title_patterns":[],"source_urls":[],"slugs":["deleted-old-report"]}
        with mock.patch.object(core,"load_rewrite_ledger",return_value=ledger), \
             mock.patch.object(core,"load_story_blocklist",return_value=blocked):
            stats=core.reconcile_rewrite_ledger_with_feed([])
            self.assertEqual(stats["deliberately_blocked"],1)
            self.assertEqual(ledger[url]["outcome"],"published")

    def test_missing_minors_and_sentencing_need_editor(self):
        original="A verified source reported an update that is unrelated to the claims."
        for title in ("Missing 16-year-old girl from Rochdale",
                      "Missing Rochdale teenager sought by police",
                      "Girl missing from Rochdale",
                      "Man jailed after sentencing in magistrates court"):
            row={"title":title,"content_html":"<p>Rochdale article</p>",
                 "evidence_sources":[{"url":"https://www.rochdale.gov.uk/news/article/100/report",
                                      "captured_text":original}]}
            verdict=verify(row,client=None)
            self.assertFalse(verdict["approved"],title)
            self.assertIn("human",verdict["reasons"][0].lower(),title)

    def test_duplicate_draft_is_counted_as_merged_not_two_publications(self):
        with TemporaryDirectory() as folder:
            pages=Path(folder)
            (pages/"one-real-story.html").write_text("Published",encoding="utf-8")
            status={"drafted_articles":[
                {"slug":"one-real-story","source_url":"https://example.com/a"},
                {"slug":"another-draft","source_url":"https://example.com/a"}]}
            feed=[{"slug":"one-real-story","source_url":"https://example.com/a"}]
            output=audit(status,feed,pages)
            self.assertEqual(output["new_articles"],1)
            self.assertEqual(output["drafts_not_published"],1)
            self.assertEqual(output["publication_health"],"partial")

    def test_robots_disallow_blocks_publisher_capture(self):
        capture._ROBOTS_CACHE.clear()
        class Response:
            status_code=200
            content=b"User-agent: *\nDisallow: /news-features/"
            text=content.decode("utf-8")
        class Session:
            requested=[]
            def get(self,url,**kwargs):
                self.requested.append(url)
                return Response()
        session=Session()
        url="https://www.rochvalleyradio.com/news-features/142/report"
        with mock.patch.object(capture,"safe_host",return_value="www.rochvalleyradio.com"):
            with self.assertRaises(PermissionError):
                capture.fetch_source(url,session=session)
        self.assertEqual(session.requested,["https://www.rochvalleyradio.com/robots.txt"])
        capture._ROBOTS_CACHE.clear()


if __name__=="__main__":
    main()
