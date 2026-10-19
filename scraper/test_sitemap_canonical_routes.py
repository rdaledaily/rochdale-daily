import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
import generate_image_sitemap as images
import generate_news_sitemap as news
from generate_rss import item_xml


class SitemapCanonicalRoutes(unittest.TestCase):
    def setUp(self):
        self.row = {'slug':'newsroom-update','title':'Verified Rochdale newsroom update',
                    'published_at':'2026-10-19T12:00:00Z','status':'published',
                    'source_kind':'editorial','manual_article':True,
                    'image_url':'assets/img/cards/newsroom.jpg'}

    def test_news_generator_emits_direct_canonical(self):
        tree = news.build_sitemap([self.row],datetime(2026,10,19,13,tzinfo=timezone.utc))
        urls=[n.text for n in tree.getroot().findall('{'+news.SITEMAP_NS+'}url/{'+news.SITEMAP_NS+'}loc')]
        self.assertEqual(urls,['https://rochdaledaily.co.uk/articles/newsroom-update'])

    def test_image_generator_keeps_image_but_uses_direct_article_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            image=root/self.row['image_url']; image.parent.mkdir(parents=True); image.write_bytes(b'local image')
            source=root/'articles.json'; source.write_text(json.dumps([self.row]))
            output=root/'image-sitemap.xml'
            with patch.object(images,'ROOT',root),patch.object(images,'ARTICLES',source),patch.object(images,'OUTPUT',output):
                self.assertEqual(images.main(),0)
            tree=ET.parse(output)
            self.assertEqual(tree.findtext('{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc'),'https://rochdaledaily.co.uk/articles/newsroom-update')
            self.assertIn('https://rochdaledaily.co.uk/assets/img/cards/newsroom.jpg',output.read_text())

    def test_rss_link_and_guid_match_canonical(self):
        item=ET.fromstring(item_xml(self.row))
        self.assertEqual(item.findtext('link'),'https://rochdaledaily.co.uk/articles/newsroom-update')
        self.assertEqual(item.findtext('guid'),item.findtext('link'))


if __name__=='__main__': unittest.main()
