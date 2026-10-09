import unittest
from editorial_review import review_flags

class EditorialReviewTests(unittest.TestCase):
    def test_mismatched_headline_is_flagged(self):
        article={"title":"Rochdale football club launches weekly radio show","content_html":"<p>A midfielder is unavailable for Saturday's game against Swindon because of an ankle injury. The coach discussed team selection at training.</p>","manual_article":True}
        self.assertTrue(any("alignment" in f for f in review_flags(article)))
    def test_matching_headline_not_flagged(self):
        article={"title":"Council approves new library in Middleton","content_html":"<p>The council has approved a new library in Middleton, following a vote at its planning meeting.</p>","manual_article":True}
        self.assertFalse(any("alignment" in f for f in review_flags(article)))
    def test_sponsored_content_skipped(self):
        self.assertEqual(review_flags({"sponsored":True,"title":"test","content_html":""}),[])
    def test_sensitive_unsourced_flagged(self):
        article={"title":"Local man charged with fraud","content_html":"<p>A man was charged with fraud yesterday.</p>","manual_article":True}
        self.assertTrue(any("attribution" in f for f in review_flags(article)))

if __name__=="__main__":
    unittest.main()
