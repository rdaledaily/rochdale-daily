import unittest
from html.parser import HTMLParser
from manual_articles import _content_html


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


if __name__ == '__main__':
    unittest.main()
