import unittest
from independent_fact_review import verify
class VerificationTests(unittest.TestCase):
    def test_no_source_fails(self):
        self.assertFalse(verify({"title":"Council action"})["approved"])
    def test_sensitive_needs_human(self):
        a={"title":"Man charged with fraud","evidence_sources":[{"url":"https://www.gmp.police.uk/news/1","captured_text":"Police report from an official website describing an arrest, further action and an investigation."}]}
        self.assertFalse(verify(a)["approved"])
    def test_no_secret_does_not_pass(self):
        from unittest.mock import patch
        a={"title":"New library","content_html":"New library","evidence_sources":[{"url":"https://www.rochdale.gov.uk/news/1","captured_text":"Rochdale Council has proposed a new library in the borough following a meeting this week."}]}
        with patch.dict("os.environ",{},clear=True):self.assertFalse(verify(a)["approved"])
if __name__=="__main__":unittest.main()
