from pathlib import Path
import re
import unittest

from normalise_public_theme import normalise_text, TOKEN_VERSIONED_HREF

ROOT = Path(__file__).resolve().parents[1]


class ThemeTokenRepairTests(unittest.TestCase):
    def test_font_tokens_are_inside_a_real_root_selector(self):
        css = (ROOT / "assets/css/rd-tokens.css").read_text()
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        root = re.search(r"(?:^|[;}])\s*:root\s*\{([^}]+)\}", css)
        self.assertIsNotNone(root, "Escaped newlines must not corrupt :root")
        for token in ("--font-body:", "--font-ui:", "--sans:", "--utility:"):
            self.assertIn(token, root.group(1))

    def test_existing_token_links_refresh_and_normalisation_is_idempotent(self):
        for href in ("/assets/css/rd-tokens.css", "/assets/css/rd-tokens.css?v=old"):
            html = '<html><head><link rel="stylesheet" href="' + href + '"></head></html>'
            result = normalise_text(Path("index.html"), html)
            self.assertIn('href="' + TOKEN_VERSIONED_HREF + '"', result)
            self.assertEqual(1, result.count("rd-tokens.css"))
            self.assertEqual(result, normalise_text(Path("index.html"), result))


if __name__ == "__main__":
    unittest.main()
