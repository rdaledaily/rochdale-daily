"""Article template: Discover images, author schema, custom SEO fields, newsletter modal.

Editor's spec, 12 Nov 2026. The pop-up's behaviour in a real browser (second
article, 5 seconds, once per session, never for subscribers, never without
JavaScript or storage) was checked with Playwright when it was built; these
tests pin the markup and server-side output it depends on.
"""
import json
import re
import tempfile
from pathlib import Path

from PIL import Image

import generate_pages as gp
import og_images

ARTICLE = {
    "slug": "test-story",
    "title": "Rochdale test story headline for the template",
    "excerpt": "A short standfirst used as the default meta description.",
    "content_html": "<p>Body.</p>",
    "category": "news",
    "area": "rochdale",
    "first_published_at": "2026-11-12T10:00:00Z",
    "published_at": "2026-11-12T10:00:00Z",
    "byline": "Rochdale Daily Newsdesk",
}


def with_root(fn):
    def run():
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets/img/cards").mkdir(parents=True)
            Image.new("RGB", (1600, 1000), "navy").save(root / "assets/img/cards/big.jpg")
            Image.new("RGB", (800, 500), "teal").save(root / "assets/img/cards/small.jpg")
            old_root, old_author = og_images.ROOT, gp.SITE_AUTHOR_JSON
            og_images.ROOT = root
            og_images._cache.clear()
            gp.SITE_AUTHOR_JSON = root / "site_author.json"
            try:
                fn(root)
            finally:
                og_images.ROOT, gp.SITE_AUTHOR_JSON = old_root, old_author
                og_images._cache.clear()
    run.__name__ = fn.__name__
    return run


def schema(page):
    data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
    return next(n for n in data["@graph"] if n.get("@type") == "NewsArticle")


@with_root
def test_wide_image_gets_three_1200px_crops(root):
    page = gp.render_article_page(dict(ARTICLE, image_url="assets/img/cards/big.jpg"), [])
    tags = re.findall(r'<meta property="og:image(?::\w+)?" content="([^"]+)"', page)
    assert [t for t in tags if t.startswith("http")][0].endswith("-1200x675.jpg")
    for name, w, h in (("1200x675", 1200, 675), ("1200x900", 1200, 900), ("1200x1200", 1200, 1200)):
        files = list((root / "assets/img/og").glob(f"*-{name}.jpg"))
        assert len(files) == 1 and Image.open(files[0]).size == (w, h)
    assert [(i["width"], i["height"]) for i in schema(page)["image"]] == [(1200, 675), (1200, 900), (1200, 1200)]
    assert 'name="twitter:card" content="summary_large_image"' in page
    assert re.search(r'name="twitter:image" content="[^"]+-1200x675\.jpg"', page)


@with_root
def test_narrow_image_keeps_its_true_size(root):
    page = gp.render_article_page(dict(ARTICLE, image_url="assets/img/cards/small.jpg"), [])
    assert '<meta property="og:image:width" content="800">' in page
    assert '<meta property="og:image:height" content="500">' in page
    assert "1200" not in "".join(re.findall(r'og:image:(?:width|height)" content="(\d+)"', page))
    assert not (root / "assets/img/og").exists()


@with_root
def test_author_stays_newsdesk_until_configured(root):
    page = gp.render_article_page(dict(ARTICLE), [])
    author = schema(page)["author"]
    assert author == [{"@type": "Organization", "name": "Rochdale Daily Newsdesk", "url": "https://rochdaledaily.co.uk/about.html"}]
    assert "{AUTHOR" not in page and "[Author" not in page


@with_root
def test_configured_author_is_a_person_with_a_real_page(root):
    (root / "site_author.json").write_text(json.dumps({"name": "Jane Smith", "job_title": "", "bio": "Covers Rochdale."}), encoding="utf-8")
    page = gp.render_article_page(dict(ARTICLE), [])
    author = schema(page)["author"][0]
    assert author["@type"] == "Person" and author["name"] == "Jane Smith"
    assert author["url"] == "https://rochdaledaily.co.uk/author/jane-smith"
    assert author["jobTitle"] == "Local Reporter" and author["description"] == "Covers Rochdale."
    assert "By Jane Smith" in page
    written = gp.write_author_page(root)
    assert written.endswith("author/jane-smith.html") and "Jane Smith" in Path(written).read_text(encoding="utf-8")


@with_root
def test_custom_seo_title_and_description_win(root):
    page = gp.render_article_page(dict(ARTICLE, seo_title="Short SEO title", meta_description="Hand-written description."), [])
    assert "<title>Short SEO title | Rochdale Daily</title>" in page
    assert '<meta name="description" content="Hand-written description.">' in page
    plain = gp.render_article_page(dict(ARTICLE), [])
    assert 'content="A short standfirst used as the default meta description."' in plain


@with_root
def test_newsletter_modal_is_hidden_until_the_script_opens_it(root):
    page = gp.render_article_page(dict(ARTICLE), [])
    assert '<body class="single-article">' in page
    modal = re.search(r'<div id="rd-newsletter-modal"[^>]*>', page).group(0)
    assert " hidden " in modal and "display:flex" not in modal
    assert "rd_visit_count" in page and "rd_newsletter_prompted" in page and "rd_subscribed" in page
    assert "setTimeout(window.showNewsletterModal, 5000)" in page
    assert "jquery" not in page.lower()


if __name__ == "__main__":
    failures = []
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures.append(name)
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(f"{len(failures)} article-template test(s) failed")
    print("all article-template tests passed")
