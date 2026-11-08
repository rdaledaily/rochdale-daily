import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from html.parser import HTMLParser
from manual_articles import _content_html
import generate_pages


class Parsed(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs).get('href'))
        if tag == 'script':
            self.scripts += 1


class ManualSourceLinks(unittest.TestCase):
    def test_source_query_and_sentence_punctuation(self):
        parsed = Parsed()
        parsed.feed(_content_html({'body': 'See https://example.org/report?a=1&b=2.'}))
        self.assertEqual(parsed.links, ['https://example.org/report?a=1&b=2'])

    def test_source_links_do_not_enable_raw_html(self):
        rendered = _content_html({'body': '<script>alert(1)</script> javascript:alert(1)'} )
        parsed = Parsed()
        parsed.feed(rendered)
        self.assertEqual(parsed.scripts, 0)
        self.assertEqual(parsed.links, [])
        self.assertIn('&lt;script&gt;', rendered)

    def test_editorial_article_citing_trusted_times_reaches_renderer(self):
        row = {'slug': 'corner-plot', 'title': 'Corner Plot', 'status': 'published',
               'source_name': 'Rochdale Daily', 'source_kind': 'editorial',
               'source_url': 'https://www.rochdaletimes.co.uk/story/',
               'content_html': '<p>33 private-rented flats.</p>'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'articles.json'
            path.write_text(json.dumps([row]))
            with patch.object(generate_pages, 'ARTICLES_JSON', path):
                self.assertEqual(len(generate_pages.load_articles(blocklist={})), 1)
                row['source_url'] = 'https://pressreader.com/story/'
                path.write_text(json.dumps([row]))
                self.assertEqual(generate_pages.load_articles(blocklist={}), [])


class ManualGallery(unittest.TestCase):
    """8 Nov 2026: editor-supplied parade photos shown under the story."""

    def test_gallery_figures_sit_before_the_source_line(self):
        import manual_articles
        body = "First paragraph.\n\nSource: supplied."
        gallery = [
            {"src": "assets/img/logo.png", "caption": "Not in cards, ignored."},
            {"src": "assets/img/cards/rochdale_cenotaph.jpg", "alt": "The Cenotaph", "caption": "The <Cenotaph>."},
            {"src": "assets/img/cards/does-not-exist.jpg", "caption": "Missing, ignored."},
            {"src": "javascript:alert(1)", "caption": "Ignored."},
        ]
        out = manual_articles._content_html({"body": body, "gallery": gallery})
        self.assertEqual(out.count("<figure"), 1)
        self.assertIn('src="/assets/img/cards/rochdale_cenotaph.jpg"', out)
        self.assertIn("The &lt;Cenotaph&gt;.", out)
        self.assertLess(out.index("<figure"), out.index("<p>Source:"))
        self.assertEqual(manual_articles._content_html({"body": body}), "<p>First paragraph.</p><p>Source: supplied.</p>")


if __name__ == '__main__':
    unittest.main()
