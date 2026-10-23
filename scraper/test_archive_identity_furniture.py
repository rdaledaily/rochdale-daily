"""Archive identity must ignore generated navigation and inline link markup."""
import unittest
from archive_integrity import page_parts, plan, apply

class ArchiveIdentityFurnitureTests(unittest.TestCase):
    def page(self, slug, body, canonical=None):
        return ('<html><head><meta name="robots" content="index,follow">'
                '<link rel="canonical" href="https://rochdaledaily.co.uk/articles/' +
                (canonical or slug) + '"></head><body><h1>Planning changes</h1>'
                '<div class="article-copy">' + body +
                '</div><details class="article-sources"></details></body></html>')

    def test_links_and_generated_sections_do_not_change_story_identity(self):
        copy = "<p>Councillor Jones (Reform UK, Castleton) discussed planning changes. " + "Local residents can attend planning meetings. " * 5 + "</p>"
        linked = copy.replace("Reform UK", '<a class="rd-auto-link" href="/news/topics/reform-uk">Reform UK</a>')
        linked += '<p data-rd-reader-ending="1">What do you think? Comment below.</p>'
        linked += '<section id="rd-archive-related"><h2>Related reporting</h2><ul><li>Other news</li></ul></section>'
        pages = {"alias": self.page("alias", copy, "primary"),
                 "primary": self.page("primary", linked),
                 "older-copy": self.page("older-copy", copy, "primary")}
        self.assertEqual(page_parts(pages["alias"])["body"], page_parts(pages["primary"])["body"])
        actions = plan(pages, {"alias", "primary"})
        self.assertEqual(actions["older-copy"]["canonical"], "primary")
        updated = {slug: apply(text, actions.get(slug, {})) for slug, text in pages.items()}
        next_actions = plan(updated, {"alias", "primary"})
        self.assertEqual(updated, {slug: apply(text, next_actions.get(slug, {})) for slug, text in updated.items()})

    def test_inline_markup_preserves_apostrophes_and_entities(self):
        plain = self.page("one", "<p>The council's planning &amp; housing policy.</p>")
        linked = self.page("one", '<p>The <a href="/news/topics/council">council</a>\'s planning &amp; housing policy.</p>')
        self.assertEqual(page_parts(plain)["body"], page_parts(linked)["body"])

if __name__ == "__main__":
    unittest.main()
