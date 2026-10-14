import unittest
import frontpage_source_quality as quality
import generate_pages
from locality_rules import TRUSTED_EDITORIAL_SOURCE_DOMAINS, has_disqualifying_evidence


class TrustedSources(unittest.TestCase):
    def test_both_publishers_are_allowed_by_renderer(self):
        for domain in TRUSTED_EDITORIAL_SOURCE_DOMAINS:
            self.assertFalse(generate_pages.source_is_denied('', 'https://www.'+domain+'/news/'))

    def test_direct_publisher_resolves_google_sports_discovery_wrapper(self):
        for domain in TRUSTED_EDITORIAL_SOURCE_DOMAINS:
            article={'category':'sport','title':'Rochdale club wins match','source_count':1,
                     'source_url':'https://www.'+domain+'/match/',
                     'source_urls':['https://news.google.com/articles/discovery']}
            self.assertFalse(quality.weak_single_source_sports_result(article))
        article={'category':'sport','title':'Rochdale club wins match','source_count':1,
                 'source_url':'https://news.google.com/articles/discovery'}
        self.assertTrue(quality.weak_single_source_sports_result(article))

    def test_editorial_trust_does_not_cancel_foreign_geography(self):
        for domain in TRUSTED_EDITORIAL_SOURCE_DOMAINS:
            self.assertTrue(has_disqualifying_evidence('A new estate in Middleton, Nova Scotia, Canada.', '', 'https://'+domain+'/news/'))


if __name__ == '__main__':
    unittest.main()
