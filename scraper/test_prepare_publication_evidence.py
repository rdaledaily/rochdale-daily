import unittest
from prepare_publication_evidence import enrich
class PreparationTests(unittest.TestCase):
    def test_prepares_recent_primary_draft_without_attesting(self):
        row={"source_url":"https://www.rochdale.gov.uk/news/article/1","published_at":"2026-10-10T10:00:00Z","ingested_at":"2026-10-10T10:01:00Z"}
        def stub(a):
            return {"evidence_sources":[{"url":a["source_url"],"captured_text":"This is a sample council source report with sufficient text to capture during the newsroom process."}],"evidence_candidates":{"headline":[]}}
        self.assertEqual(enrich([row],stub),1)
        self.assertFalse(row["primary_source_verified"])
    def test_old_story_preserved(self):
        row={"source_url":"https://www.rochdale.gov.uk/news/article/1","published_at":"2026-09-01T10:00:00Z","ingested_at":"2026-09-01T10:01:00Z"}
        self.assertEqual(enrich([row],lambda _:self.fail("should not fetch")),0)
if __name__=="__main__":unittest.main()
