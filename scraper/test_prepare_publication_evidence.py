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
    def test_existing_evidence_is_reverified_without_refetch(self):
        row={"source_url":"https://www.rochdale.gov.uk/news/article/1","published_at":"2026-10-10T10:00:00Z","ingested_at":"2026-10-10T10:01:00Z",
             "evidence_sources":[{"url":"https://www.rochdale.gov.uk/news/article/1","captured_text":"The Rochdale council approved a new library at a meeting on Thursday and confirmed the new plans."}]}
        def reviewer(article):
            return {"approved":True,"claims":[{"claim":"Council approved a new library","source_url":row["source_url"],"supporting_excerpt":row["evidence_sources"][0]["captured_text"]}],"reasons":[]}
        self.assertEqual(enrich([row],lambda _:self.fail("unexpected refetch"),reviewer),1)
        self.assertTrue(row["primary_source_verified"])
    def test_failed_review_does_not_fabricate_approval(self):
        row={"source_url":"https://www.rochdale.gov.uk/news/article/1","published_at":"2026-10-10T10:00:00Z","ingested_at":"2026-10-10T10:01:00Z",
             "evidence_sources":[{"url":"https://www.rochdale.gov.uk/news/article/1","captured_text":"Rochdale Council announced the plans for an improved public library in the borough."}]}
        self.assertEqual(enrich([row],lambda _:self.fail("unexpected refetch"),lambda _:{"approved":False,"reasons":["Unsupported amount"],"claims":[]}),1)
        self.assertFalse(row["primary_source_verified"])
if __name__=="__main__":unittest.main()
