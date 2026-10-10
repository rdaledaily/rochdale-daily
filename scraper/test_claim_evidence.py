import unittest
from claim_evidence import evidence_issues, is_primary

URL="https://www.rochdale.gov.uk/news/article/123"
TEXT="Rochdale Borough Council has approved the new community library at its meeting on Friday. The scheme will open in November."
class EvidenceTests(unittest.TestCase):
    def test_primary_host(self):
        self.assertTrue(is_primary(URL))
        self.assertFalse(is_primary("https://rochdale.gov.uk.evil.test/page"))
        self.assertFalse(is_primary("http://rochdale.gov.uk/page"))
        self.assertFalse(is_primary("https://www.manchestereveningnews.co.uk/article"))
    def test_missing_evidence(self):
        self.assertTrue(evidence_issues({"source_url":URL}))
    def test_valid_contract(self):
        row={"primary_source_verified":True,"source_review_verified":True,"evidence_sources":[{"url":URL,"captured_text":TEXT}],"verified_claims":[{"claim":"Council approved community library","source_url":URL,"supporting_excerpt":"Rochdale Borough Council has approved the new community library at its meeting on Friday."}]}
        self.assertEqual(evidence_issues(row),[])
    def test_made_up_quote(self):
        row={"primary_source_verified":True,"source_review_verified":True,"evidence_sources":[{"url":URL,"captured_text":TEXT}],"verified_claims":[{"claim":"Council spent £2m","source_url":URL,"supporting_excerpt":"The council spent two million pounds."}]}
        self.assertTrue(evidence_issues(row))
    def test_manual_not_retroactive(self):
        self.assertEqual(evidence_issues({"manual_article":True}),[])

if __name__=="__main__":unittest.main()
