"""Banned links (gambling, betting, piracy, denied outlets) can never be published.

Run: python scraper/test_link_ban.py   (or pytest)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import link_ban  # noqa: E402
import locality_rules  # noqa: E402


def test_hosts():
    for url in (
        "https://news.bet365.com/en-gb/article/football-rochdale-liverpool-u21-prediction-and-tips/1",
        "https://www.bettingodds.com/football/league-two/20-10-2026/rochdale-vs-grimsby-town",
        "https://www.oddschecker.com/tips/football/x",
        "https://www.apwin.com/streams/rochdale-vs-swindon-town-03-10-2026/",
        "https://insights.betfred.com/football/match/x",
        "https://online-bookmakers.com/sports-betting/x",
        "https://www.rochdaleonline.co.uk/business/adtracking_advertid-1765-4079/",
        "https://uklfi.com/x",
    ):
        assert link_ban.is_banned_url(url), url
    for url in (
        "https://rochdaleafc.co.uk/preview-grimsby-town-h-2/",
        "https://www.rochdale.gov.uk/news",
        "https://www.gmp.police.uk/news/",
        "https://www.manchestereveningnews.co.uk/all-about/rochdale",
        "https://www.bbc.co.uk/sport/football",
        "https://www.tntsports.co.uk/football/league-two/x",
        "",
    ):
        assert not link_ban.is_banned_url(url), url


def test_sources_list_item_removed_and_renumbered():
    page = ('<details class="article-sources"><summary>Sources</summary><ul>'
            '<li><a href="https://rochdaleafc.co.uk/a">Open source 1</a></li>'
            '<li><a href="https://news.bet365.com/x" target="_blank">Open source 2</a></li>'
            '<li><a href="https://rochdaleafc.co.uk/b">Open source 3</a></li></ul></details>')
    out = link_ban.strip_html(page)
    assert "bet365" not in out
    assert ">Open source 2</a>" in out and "Open source 3" not in out


def test_only_banned_sources_drops_the_block():
    page = ('<p>x</p><details class="article-sources"><summary>Sources</summary><ul>'
            '<li><a href="https://www.apwin.com/x">Open source 1</a></li></ul></details>')
    assert link_ban.strip_html(page) == "<p>x</p>"


def test_body_anchor_unwrapped_keeps_text():
    out = link_ban.strip_html('<td><a href="https://www.rochdaleonline.co.uk/x">Rochdale Online</a></td>')
    assert out == "<td>Rochdale Online</td>"


def test_json_record():
    record = {"source_url": "https://rochdaleafc.co.uk/a", "source_count": 3,
              "source_urls": ["https://rochdaleafc.co.uk/a", "https://www.apwin.com/x", "https://www.bettingodds.com/y"],
              "content_html": '<p>See <a href="https://news.bet365.com/z">odds</a>.</p>',
              "evidence_sources": [{"url": "https://www.oddschecker.com/q"}, {"url": "https://rochdaleafc.co.uk/a"}]}
    clean = link_ban.strip_value(record)
    link_ban.recount_sources(clean)
    assert link_ban.banned_in_value(clean) == []
    assert clean["source_urls"] == ["https://rochdaleafc.co.uk/a"]
    assert clean["source_count"] == 1
    assert clean["content_html"] == "<p>See odds.</p>"
    assert len(clean["evidence_sources"]) == 1


def test_resolution_tombstone():
    data = {"k": {"url": "https://news.bet365.com/x", "at": "2026-09-01T00:00:00Z"},
            "ok": {"url": "https://rochdaleafc.co.uk/a", "at": "2026-09-01T00:00:00Z"}}
    out = link_ban.clean_resolutions(data)
    assert out["k"] == {"url": "", "blocked": "news.bet365.com", "at": "2026-09-01T00:00:00Z"}
    assert out["ok"] == data["ok"]
    import google_news_resolver as gnr
    from datetime import datetime, timezone
    assert gnr._cached_result(out["k"], datetime.now(timezone.utc)) == ""


def test_sweep_fixes_and_checks_a_tree():
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "articles").mkdir()
        (tmp / "articles" / "a.html").write_text(
            '<ul><li><a href="https://www.apwin.com/x">Open source 1</a></li></ul>', encoding="utf-8")
        (tmp / "articles.json").write_text(json.dumps([{"source_urls": ["https://bettingodds.com/x"]}]))
        (tmp / "story_blocklist.json").write_text(json.dumps({"source_urls": ["https://uklfi.com/x"]}))
        assert set(link_ban.sweep(tmp)) == {"articles/a.html", "articles.json"}
        link_ban.sweep(tmp, fix=True)
        assert link_ban.sweep(tmp) == {}
        # The blocklist exists to NAME banned URLs; it is never stripped.
        assert "uklfi" in (tmp / "story_blocklist.json").read_text()
    finally:
        shutil.rmtree(tmp)


def test_render_filter_fails_closed():
    import source_presentation as sp
    assert sp._denied_source("https://news.bet365.com/x")
    html = sp.generic_sources_markup({"source_url": "https://rochdaleafc.co.uk/a",
                                      "source_urls": ["https://www.apwin.com/x"]})
    assert "apwin" not in html and "rochdaleafc" in html


def _js_lists():
    text = (ROOT / "functions" / "_middleware.js").read_text(encoding="utf-8")
    block = text.split("// BANNED_LINK_LISTS_START", 1)[1].split("// BANNED_LINK_LISTS_END", 1)[0]
    domains = json.loads(re.search(r"BANNED_LINK_DOMAINS = (\[.*?\]);", block, re.S).group(1))
    pattern = json.loads(re.search(r"new RegExp\((\".*?\"), 'i'\)", block, re.S).group(1))
    return domains, pattern


def test_edge_lists_match_python():
    domains, pattern = _js_lists()
    expected = sorted(locality_rules.SOURCE_DENY_DOMAINS | locality_rules.GAMBLING_PIRACY_DENY_DOMAINS
                      | link_ban.EXTRA_DENY_DOMAINS)
    assert domains == expected, "functions/_middleware.js banned-domain list is out of step with Python"
    assert pattern == locality_rules.GAMBLING_PIRACY_HOST_RE.pattern


def test_edge_strip_behaviour():
    node = shutil.which("node")
    if not node:
        return
    script = (
        "import('" + (ROOT / "functions" / "_middleware.js").as_uri() + "').then(m => {"
        "const out = m.stripBannedLinksText('<a href=\"https://news.bet365.com/x\">odds</a> "
        "<a href=\"https://rochdaleafc.co.uk/\">club</a>');"
        "if (out !== 'odds <a href=\"https://rochdaleafc.co.uk/\">club</a>') { console.error(out); process.exit(1); }"
        "if (!m.isBannedLink('https://www.apwin.com/x') || m.isBannedLink('https://www.rochdale.gov.uk/')) process.exit(2);"
        "})"
    )
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_repository_has_no_banned_links():
    assert link_ban.sweep(ROOT) == {}, "run: python scraper/link_ban.py --fix"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as exc:
                failures += 1
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
