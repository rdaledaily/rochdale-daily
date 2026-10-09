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
    def test_verified_model_output_with_matching_quote(self):
        import json
        from types import SimpleNamespace
        source="Rochdale Borough Council approved the library improvement plan at a meeting on Thursday."
        payload={"approved":True,"claims":[{"claim":"Council approved a library improvement plan","supported":True,"source_url":"https://www.rochdale.gov.uk/news/article/1","supporting_excerpt":source,"reason":""}],"reasons":[]}
        reply=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs:reply)))
        row={"title":"Council approves library improvement plan","content_html":"<p>Rochdale Borough Council approved the library improvement plan at a meeting on Thursday.</p>","evidence_sources":[{"url":"https://www.rochdale.gov.uk/news/article/1","captured_text":source}]}
        self.assertTrue(verify(row,client)["approved"])
    def test_hallucinated_supporting_quote_rejected(self):
        import json
        from types import SimpleNamespace
        source="Rochdale Borough Council approved the library improvement plan at a meeting on Thursday."
        payload={"approved":True,"claims":[{"claim":"Council approved £9m","supported":True,"source_url":"https://www.rochdale.gov.uk/news/article/1","supporting_excerpt":"Council approved nine million pounds for the project","reason":""}],"reasons":[]}
        reply=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs:reply)))
        row={"title":"Council approves library improvement plan","content_html":"<p>The plan was approved.</p>","evidence_sources":[{"url":"https://www.rochdale.gov.uk/news/article/1","captured_text":source}]}
        self.assertFalse(verify(row,client)["approved"])
if __name__=="__main__":unittest.main()
