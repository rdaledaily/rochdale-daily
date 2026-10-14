import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ensure_article_images as images
_prior_meaningful_image = images.existing_meaningful_image
import frontpage_manual_publish as manual


def tearDownModule():
    images.existing_meaningful_image = _prior_meaningful_image


class ManualImageBoundary(unittest.TestCase):
    def test_valid_archive_card_does_not_rescan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / 'assets/img/cards/existing.jpg'
            image.parent.mkdir(parents=True)
            image.write_bytes(b'x' * 5000)
            with patch.object(manual, '_original_cards_enforce_article') as normalise:
                manual._cards_without_archive_rescan({'image_url': 'assets/img/cards/existing.jpg'}, root)
                normalise.assert_not_called()

    def test_invalid_image_still_uses_cards_normaliser(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article = {'image_url': 'https://example.org/image.jpg'}
            with patch.object(manual, '_original_cards_enforce_article', return_value='normalised') as normalise:
                self.assertEqual(manual._cards_without_archive_rescan(article, root), 'normalised')
                normalise.assert_called_once_with(article, root)

    def test_newspaper_pass_uses_manual_boundary_and_restores_it(self):
        import generate_newspaper_pages as newspaper
        previous = newspaper.cards_policy.enforce_article
        def render():
            self.assertIs(newspaper.cards_policy.enforce_article, manual._cards_without_archive_rescan)
        with patch.object(newspaper, 'main', side_effect=render):
            manual.render_main()
        self.assertIs(newspaper.cards_policy.enforce_article, previous)


if __name__ == '__main__':
    unittest.main()
