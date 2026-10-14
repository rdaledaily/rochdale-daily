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


if __name__ == '__main__':
    unittest.main()
