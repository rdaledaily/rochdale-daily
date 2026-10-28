"""Contract checks for in-page new article notifications."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class NewStoryAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script=(ROOT/"assets/js/new-story-alerts.js").read_text()
        cls.sound=(ROOT/"assets/js/menu.js").read_text()
        cls.home=(ROOT/"index.html").read_text()
        cls.generator=(ROOT/"scraper/generate_pages.py").read_text()
        cls.legacy=(ROOT/"post.html").read_text()
    def test_loaders(self):
        for page in (self.home,self.generator,self.legacy):
            self.assertIn('/assets/js/new-story-alerts.js',page)
    def test_opt_in_audio(self):
        self.assertIn('window.RochdaleDailyChime = () => { if (enabled) chime(); };',self.sound)
        self.assertIn('window.RochdaleDailyChime()',self.script)
    def test_safe_discovery(self):
        self.assertIn('if (baseline) {',self.script)
        self.assertIn('fresh.slice(-2).forEach(alertStory)',self.script)
        self.assertIn('INITIAL_ALERT_WINDOW = 45 * 60 * 1000',self.script)
        self.assertIn('MAX_ALERTS_PER_SESSION = 3',self.script)
        self.assertIn('}, 17000)',self.script)
        self.assertIn("card.contains(document.activeElement)",self.script)
        self.assertIn("card.matches(':hover')",self.script)
        self.assertIn("document.visibilityState === 'hidden'",self.script)
        self.assertIn('known.has(id(s))',self.script)
        self.assertIn('INTERVAL = 180000',self.script)
        self.assertIn("fetch('/articles/frontpage.json?new_story_check=",self.script)
    def test_no_untrusted_markup(self):
        self.assertIn('link.textContent = String(story.title)',self.script)
        self.assertIn('/^[a-z0-9][a-z0-9-]{0,180}$/i.test(slug)',self.script)
if __name__=="__main__":unittest.main()
