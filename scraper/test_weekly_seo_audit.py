"""Static SEO auditor contract with synthetic sitemap and article pages."""
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

from weekly_seo_audit import head_meta, report, site_path, markdown


def run() -> None:
    assert site_path(Path("/tmp/demo"), "https://rochdaledaily.co.uk/").name == "index.html"
    assert site_path(Path("/tmp/demo"), "https://other.example/") is None
    assert head_meta('<head><title>Example</title><meta name="description" content="Useful local news"><link rel="canonical" href="https://rochdaledaily.co.uk/"></head>')["title"] == "Example"
    with TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "articles").mkdir()
        (root / "wards").mkdir()
        (root / "assets/img/cards").mkdir(parents=True)
        (root / "index.html").write_text(
            '<head><title>Rochdale news</title><meta name="description" content="Useful news">'
            '<link rel="canonical" href="https://rochdaledaily.co.uk/"></head>', encoding="utf-8")
        (root / "rochdale.html").write_text(
            '<head><meta name="robots" content="noindex,follow">'
            '<link rel="canonical" href="https://rochdaledaily.co.uk/"></head>', encoding="utf-8")
        (root / "_redirects").write_text("/rochdale / 301\n", encoding="utf-8")
        (root / "wards/index.html").write_text(
            '<head><title>Wards</title><link rel="canonical" href="https://rochdaledaily.co.uk/wards/"></head>', encoding="utf-8")
        (root / "assets/img/cards/test.jpg").write_bytes(b"Photo" * 3000)
        (root / "articles/test.html").write_text(
            '<head><title>Useful article</title><meta name="description" content="Local details">'
            '<link rel="canonical" href="https://rochdaledaily.co.uk/articles/test.html"></head>'
            '<body><figure class="article-hero-image"><img src="/assets/img/cards/test.jpg" alt="test"></figure></body>',
            encoding="utf-8")
        sitemap = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
        for url in ("https://rochdaledaily.co.uk/", "https://rochdaledaily.co.uk/wards/",
                    "https://rochdaledaily.co.uk/articles/test.html"):
            elem = ET.SubElement(sitemap, "url")
            ET.SubElement(elem, "loc").text = url
        ET.ElementTree(sitemap).write(root / "sitemap.xml", encoding="utf-8", xml_declaration=True)
        result = report(root)
        assert result["pages_checked"] == 3, result
        assert result["issue_totals"].get("broken_hero_image", 0) == 0
        assert result["issue_totals"].get("legacy_preview_indexable", 0) == 0
        assert "week" in markdown(result).lower()
        (root / "assets/img/cards/test.jpg").unlink()
        result = report(root)
        assert result["issue_totals"]["broken_hero_image"] == 1, result
    print("Weekly static SEO auditor tests passed.")


if __name__ == "__main__":
    run()
