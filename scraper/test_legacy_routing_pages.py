from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LegacyRoutingPagesTests(unittest.TestCase):
    """Guard the two public query-string routes against design/runtime regressions."""

    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_retired_bundles_and_redirect_shims_cannot_return(self):
        for relative_path in ("category.html", "post.html"):
            html = self.read(relative_path)
            self.assertNotIn("styles.min.css", html)
            self.assertNotIn("app.min.js", html)
            self.assertNotRegex(html, r"http-equiv\s*=\s*[\"']refresh[\"']")
            self.assertNotIn("location.replace(", html)
            self.assertNotIn("location.href =", html)

    def test_both_pages_use_the_shared_newspaper_design_system(self):
        for relative_path in ("category.html", "post.html"):
            html = self.read(relative_path)
            self.assertIn('/assets/css/rd-tokens.css', html)
            self.assertIn('/assets/css/legacy-routing-pages.css', html)
            self.assertIn('/assets/js/menu.js', html)
            self.assertIn('/assets/js/cookie-consent.js', html)
            self.assertIn('class="rd-masthead"', html)
            self.assertIn('class="rd-primary-nav"', html)
            self.assertIn('class="rd-footer"', html)

    def test_every_local_runtime_asset_referenced_by_routes_exists(self):
        paths = {
            "assets/css/rd-tokens.css",
            "assets/css/legacy-routing-pages.css",
            "assets/js/menu.js",
            "assets/js/cookie-consent.js",
            "assets/js/category-page.js",
            "assets/js/post-page.js",
            "assets/js/article-comments.js",
            "assets/img/logo.svg",
            "articles.json",
        }
        for relative_path in paths:
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_route_styles_only_use_declared_design_tokens(self):
        css = self.read("assets/css/legacy-routing-pages.css")
        tokens = self.read("assets/css/rd-tokens.css")
        used = set(re.findall(r"var\((--[a-zA-Z0-9_-]+)", css))
        declared = set(re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", tokens))
        self.assertEqual(set(), used - declared)
        self.assertIn("var(--brand-navy)", css)
        self.assertIn("var(--brand-accent)", css)
        self.assertIn("var(--paper)", css)

    def test_category_page_has_a_complete_reader_contract(self):
        html = self.read("category.html")
        js = self.read("assets/js/category-page.js")
        for element_id in (
            "page-title",
            "page-standfirst",
            "story-search",
            "results-summary",
            "loading-state",
            "error-state",
            "empty-state",
            "story-results",
            "load-more",
        ):
            self.assertIn(f'id="{element_id}"', html)
        for signal in (
            "fetch('/articles.json'",
            "['type', 'category', 'section']",
            "['area', 'town', 'place']",
            "buildFilterHref(",
            "applyFilters()",
            "createLead(",
            "createCard(",
            "setCanonical(",
        ):
            self.assertIn(signal, js)
        self.assertIn('data-filter-area=""', html)

    def test_post_page_has_a_complete_safe_article_contract(self):
        html = self.read("post.html")
        js = self.read("assets/js/post-page.js")
        for element_id in (
            "article-title",
            "article-dek",
            "article-byline",
            "article-published",
            "article-body",
            "article-sources",
            "article-legal",
            "related-stories",
            "comments-root",
        ):
            self.assertIn(f'id="{element_id}"', html)
        for signal in (
            "fetch('/articles.json'",
            "['id', 'slug', 'story', 'story_key', 'article']",
            "sanitiseArticleHtml(",
            "script, style, iframe, object, embed",
            "setCanonical(",
            "NewsArticle",
            "/assets/js/article-comments.js",
        ):
            self.assertIn(signal, js)

    def test_route_pages_have_mobile_navigation_and_accessibility_hooks(self):
        css = self.read("assets/css/legacy-routing-pages.css")
        for relative_path in ("category.html", "post.html"):
            html = self.read(relative_path)
            self.assertIn('class="rd-skip-link"', html)
            self.assertIn('aria-controls="primary-menu"', html)
            self.assertIn('aria-expanded="false"', html)
        self.assertIn("@media (max-width: 900px)", css)
        self.assertIn(".rd-nav-list.open", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion", css)


if __name__ == "__main__":
    unittest.main()
