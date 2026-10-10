"""Integration checks for new automated stories and historic archive protection."""
import os
import tempfile
import unittest
from unittest.mock import patch
from article_gate import normalise_article

class PublicationEvidenceIntegration(unittest.TestCase):
    def base(self):
        return {"slug":"library-renovation","title":"Rochdale Council approves library renovation",
                "content_html":"<p>Rochdale Council has approved renovation works at a borough library. The decision was announced following a council meeting.</p>",
                "excerpt":"Council has approved a renovation.","source_url":"https://www.rochdale.gov.uk/news/article/999",
                "area":"rochdale","category":"news","source_kind":"news",
                "published_at":"2026-10-10T10:00:00Z",
                "first_published_at":"2026-10-10T10:00:00Z",
                "ingested_at":"2026-10-10T10:01:00Z"}
    def test_new_story_without_captured_evidence_is_published(self):
        """The evidence guard was removed on 9 October 2026 on the editor's instruction.

        While it ran, 12 newsroom runs attempted 10 stories and published none.
        """
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{"RD_REVIEW_DIR":d}):
            notes=[]
            kept=normalise_article(self.base(),notes,{"title_patterns":[],"source_urls":[],"slugs":[]})
            self.assertIsNotNone(kept)
            self.assertFalse(any("REJECTED" in x for x in notes), notes)
            self.assertEqual(os.listdir(d), [])
    def test_new_story_from_another_outlet_is_published(self):
        story=self.base()
        story["source_url"]="https://www.rochvalleyradio.com/news/local-news/library-renovation/"
        notes=[]
        self.assertIsNotNone(normalise_article(story,notes,{"title_patterns":[],"source_urls":[],"slugs":[]}))
        self.assertFalse(any("REJECTED" in x for x in notes), notes)
    def test_review_flags_are_advisory_and_never_stop_a_story(self):
        story=self.base()
        story["title"]="Entirely unrelated headline words zebra quantum marmalade"
        notes=[]
        self.assertIsNotNone(normalise_article(story,notes,{"title_patterns":[],"source_urls":[],"slugs":[]}))
        self.assertTrue(any("advisory review flags" in x for x in notes), notes)
    def test_no_lane_runs_the_evidence_step_any_more(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        for name in ("scraper/publish_newsroom_snapshot.sh",".github/workflows/scrape-fast.yml",".github/workflows/publish.yml",".github/workflows/scrape-kick.yml"):
            self.assertNotIn("prepare_publication_evidence.py",(root/name).read_text(encoding="utf-8"),name)
    def test_historical_story_is_kept(self):
        story=self.base()
        for key in ("published_at","first_published_at","ingested_at"):
            story[key]="2026-09-01T10:00:00Z"
        notes=[]
        self.assertIsNotNone(normalise_article(story,notes,{"title_patterns":[],"source_urls":[],"slugs":[]}))

if __name__=="__main__":unittest.main()
