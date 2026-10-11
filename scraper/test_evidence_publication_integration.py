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
    def test_new_story_without_final_evidence_attestation_is_kept(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{"RD_REVIEW_DIR":d}):
            notes=[]
            saved=normalise_article(self.base(),notes,{"title_patterns":[],"source_urls":[],"slugs":[]})
            self.assertIsNotNone(saved)
            self.assertEqual(saved["slug"],"library-renovation")
            self.assertFalse(any("REJECTED" in x for x in notes))
            self.assertFalse(os.path.exists(os.path.join(d,"library-renovation.json")))
    def test_historical_story_is_kept(self):
        story=self.base()
        for key in ("published_at","first_published_at","ingested_at"):
            story[key]="2026-09-01T10:00:00Z"
        notes=[]
        self.assertIsNotNone(normalise_article(story,notes,{"title_patterns":[],"source_urls":[],"slugs":[]}))

if __name__=="__main__":unittest.main()
