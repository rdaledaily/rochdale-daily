"""Contract regression tests for reader loyalty UI/API integration."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class LoyaltyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator=(ROOT/"scraper/generate_pages.py").read_text()
        cls.comments=(ROOT/"assets/js/article-comments.js").read_text()
        cls.api=(ROOT/"functions/api/comments.js").read_text()
        cls.sound=(ROOT/"assets/js/menu.js").read_text()
        cls.home=(ROOT/"index.html").read_text()
    def test_chime_on_home_and_generated_articles(self):
        self.assertIn('/assets/js/menu.js',self.home)
        self.assertIn('<script defer src="/assets/js/menu.js"></script>',self.generator)
        self.assertIn("rd_welcome_sound",self.sound)
        self.assertIn("button.addEventListener('click'",self.sound)
    def test_comment_like_contract(self):
        self.assertIn("action:'like',token:session.token,slug,id:btn.dataset.upvote",self.comments)
        self.assertIn('if (action === "like")',self.api)
        self.assertIn("likedByMe",self.api)
    def test_area_badges(self):
        self.assertIn('norden:"Norden"',self.api)
        self.assertIn("new Set(progress.slugs).size < 3",self.api)
        self.assertIn('c.badges',self.comments)
    def test_crime_comment_block(self):
        self.assertIn('new Set(["crime"])',self.api)
        self.assertIn("if (!gate.ok) return json",self.api)
    def test_author_can_delete_own_comment(self):
        # Ownership is checked server-side from the session token, never trusted from the page.
        self.assertIn("target.usernameLower !== author.usernameLower",self.api)
        self.assertIn("mine: Boolean(viewer) && c.usernameLower === viewer",self.api)
        self.assertIn("action:'delete',token:session.token,slug,id:btn.dataset.delete",self.comments)
    def test_comment_count_beside_byline(self):
        self.assertIn("article-comment-count",self.comments)
        self.assertIn("showTopCount(null)",self.comments)
if __name__=="__main__":unittest.main()
