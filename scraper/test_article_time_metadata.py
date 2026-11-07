#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import add_article_time_metadata as timing


class ArticleTimeMetadataTests(unittest.TestCase):
    def test_published_time_is_visible_and_semantic(self) -> None:
        article = {
            "slug": "test-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "title": "Test story",
        }
        markup = timing.metadata_markup(article)
        self.assertIn('datetime="2026-08-16T03:12:00Z"', markup)
        self.assertIn("Published 16 August 2026 at 04:12", markup)
        self.assertNotIn("Updated", markup)

    def test_routine_scrape_timestamp_is_not_shown_as_update(self) -> None:
        article = {
            "slug": "automated-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "last_updated_at": "2026-08-16T04:30:00Z",
            "scraped_at": "2026-08-16T04:31:00Z",
            "source_kind": "article",
        }
        markup = timing.metadata_markup(article)
        self.assertNotIn("Updated", markup)

    def test_verified_live_update_is_shown(self) -> None:
        article = {
            "slug": "live-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "live_story": True,
            "last_updated_at": "2026-08-16T04:40:00Z",
            "live_updates": [
                {"timestamp": "2026-08-16T03:12:00Z", "text": "Original report."},
                {"timestamp": "2026-08-16T04:25:00Z", "text": "Verified new development."},
            ],
        }
        markup = timing.metadata_markup(article)
        self.assertIn("Updated 16 August 2026 at 05:25", markup)
        self.assertNotIn("05:40", markup)

    def test_editorial_last_updated_time_is_allowed(self) -> None:
        article = {
            "slug": "manual-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
            "last_updated_at": "2026-08-16T04:10:00Z",
            "manual_article": True,
            "source_kind": "editorial",
        }
        published = timing.first_published(article)
        self.assertIsNotNone(published)
        self.assertEqual(
            timing.meaningful_update(article, published),
            datetime(2026, 8, 16, 4, 10, tzinfo=timezone.utc),
        )

    def test_injection_is_idempotent(self) -> None:
        article = {
            "slug": "test-story",
            "status": "published",
            "first_published_at": "2026-08-16T03:12:00Z",
        }
        page = '<div class="article-byline">By Rochdale Daily Newsdesk</div><p>Body</p>'
        once, changed = timing.inject(page, article)
        self.assertTrue(changed)
        twice, changed_again = timing.inject(once, article)
        self.assertFalse(changed_again)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(timing.START), 1)

    def test_developing_label_only_when_story_says_it_is_incomplete(self) -> None:
        """6 Nov 2026 (editor's rule): the label goes only on a story that
        states it is incomplete or waiting for information. A finished fire
        report does not get it from its headline; a story waiting on a press
        office does, whatever its headline."""
        import generate_pages as gp
        done = {"title": "Resident escapes fire at Lonsdale Court", "content_html":
                "<p>A fire broke out. All residents were evacuated safely and the building was made secure.</p>"}
        self.assertFalse(gp.is_developing_story(done))
        waiting = [
            "Rochdale Daily has asked the press office to confirm the full term and will update this report.",
            "This is a developing story and will be updated.",
            "At the time of publication, police had not released the cause.",
            "Further updates are expected as the situation develops.",
            "The operator has been contacted for comment.",
        ]
        for line in waiting:
            crime = {"title": "Police appeal after Rochdale burglary", "category": "crime", "content_html": f"<p>{line}</p>"}
            self.assertTrue(gp.is_developing_story(crime), line)
            self.assertTrue(gp.is_developing_story(dict(crime, category="news", police_matter=True)), line)
            # 7 Nov 2026 (editor's rule): only crime and police stories are
            # ever developing, whatever the copy says.
            self.assertFalse(gp.is_developing_story({"title": "Council contract", "category": "politics",
                                                     "content_html": f"<p>{line}</p>"}), line)
        incidental = [
            "The cost of the scheme has not been disclosed.",
            "Rochdale Daily will update this report if the council announces any further changes.",
            "Police warn of doorstep scams in Heywood.",
            "ONGOING STORY — Updated 3 September 2026 at 11:22.",
        ]
        for line in incidental:
            self.assertFalse(gp.is_developing_story({"title": "Crash on Edenfield Road", "content_html": f"<p>{line}</p>"}), line)
        # is_ongoing is set by the pipeline, not the copy: it does not count.
        self.assertFalse(gp.is_developing_story({"title": "x", "is_ongoing": True, "content_html": "<p>x</p>"}))
        self.assertTrue(gp.is_generated_card("assets/img/cards/x-place-generated-card.jpg"))
        self.assertFalse(gp.is_generated_card("assets/img/cards/warwick-mill.jpg"))

    def test_archived_pages_keep_label_only_if_copy_says_so(self) -> None:
        import tempfile
        from pathlib import Path
        import generate_pages as gp
        # Older pages carry the note with inline styles; both forms are swept.
        note = '<p class="developing-note" style="margin:12px 0">This is a developing story.</p>\n'
        page = '<div class="article-main">{n}<div class="article-copy"><p>{t}</p></div><section class="editorial-legal-note"><p>may be updated</p></section></div>'
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "old.html").write_text(page.format(n=note, t="The fire was put out."), encoding="utf-8")
            crime_meta = '<meta property="article:section" content="Crime">'
            (d / "wait.html").write_text(crime_meta + page.format(n=note, t="Awaiting confirmation from GMP."), encoding="utf-8")
            # Not crime: the label goes even though the copy is waiting, and so
            # does the ONGOING chip (7 Nov 2026, editor's rule).
            chip = '<nav class="article-breadcrumb"><a>News</a><span class="kicker-chip">ONGOING</span></nav>'
            (d / "council.html").write_text(chip + page.format(n=note, t="Awaiting a reply from the council."), encoding="utf-8")
            (d / "crimechip.html").write_text(crime_meta + chip + page.format(n="", t="Police are investigating."), encoding="utf-8")
            (d / "live.html").write_text(page.format(n=note, t="The fire was put out."), encoding="utf-8")
            self.assertEqual(gp.scrub_stale_developing_notes(d, {"live"}), 2)
            self.assertNotIn("developing-note", (d / "old.html").read_text())
            self.assertIn("developing-note", (d / "wait.html").read_text())
            council = (d / "council.html").read_text()
            self.assertNotIn("developing-note", council)
            self.assertNotIn("ONGOING", council)
            self.assertIn("ONGOING", (d / "crimechip.html").read_text())
            self.assertIn("developing-note", (d / "live.html").read_text())

    def test_page_dates_are_uk_not_utc(self) -> None:
        """23:30 UTC on 16 August is 00:30 on 17 August in Rochdale."""
        import generate_pages as gp
        self.assertEqual(gp.format_correction_date("2026-08-16T23:30:00Z"), "17 August 2026")
        self.assertEqual(gp.format_correction_date("2026-12-01T09:00:00Z"), "1 December 2026")


if __name__ == "__main__":
    unittest.main()
