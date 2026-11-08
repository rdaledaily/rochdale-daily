from __future__ import annotations

import content_hygiene as hygiene


def main() -> int:
    payload = {
        "title": "Title \U0001f4f0",
        "body": "Body \U0001f4f0",
        "byline": "Rochdale Daily \U0001f4f0",
        "image_credit": "Photographer \U0001f4f7",
        "source_name": "Source \U0001f310",
        "image_alt": "Alt \U0001f5bc",
    }
    cleaned = hygiene.clean_json(payload)
    assert cleaned["title"] == "Title"
    assert cleaned["body"] == "Body"
    assert cleaned["byline"] == "Rochdale Daily"
    assert cleaned["image_credit"] == "Photographer"
    assert cleaned["source_name"] == "Source"
    assert cleaned["image_alt"] == "Alt"
    assert hygiene.has_public_text_violation({"byline": "Name \U0001f4f0"})
    assert not hygiene.has_public_text_violation(cleaned)
    assert not hygiene.has_public_text_violation({"internal_note": "Keep \U0001f4f0"})

    # A full publishing cleanup must reach a fixed point in one call. Some
    # feeds arrive encoded more than once; historically &amp;amp; or an encoded
    # emoji was revealed by pass one and only removed by pass two, causing the
    # canonical publisher's immediate verification pass to fail.
    encoded = (
        "  News &amp;amp; views &#x26;#x1F4F0; "
        "[source](https://example.com/?utm_source=chatgpt.com)   "
    )
    once = hygiene.clean_text(encoded)
    twice = hygiene.clean_text(once)
    assert once == twice
    assert once == "News & views"

    nested_payload = {
        "title": "Update &amp;amp; reaction",
        "body": "Details &#x26;#128240;",
        "source_url": "https://example.com/story?utm_source=chatgpt.com&id=7",
    }
    first_json = hygiene.clean_json(nested_payload)
    second_json = hygiene.clean_json(first_json)
    assert first_json == second_json
    assert first_json["title"] == "Update & reaction"
    assert first_json["body"] == "Details"
    assert first_json["source_url"] == "https://example.com/story?id=7"

    # 7 Nov 2026: a page is cleaned in its reader text only. Cleaning the whole
    # file removed the space in '.401 0 .955' inside the Facebook icon's path
    # data, breaking the share icons on 1,448 pages.
    page = ('<div><svg viewBox="0 0 24 24"><path d="M9 5.978.401 0 .955.042"/></svg>'
            '<p>Hello , world .</p><style>.a .b{x:1}</style><script>var a = b .c;</script></div>')
    out = hygiene.clean_html_text(page)
    assert '<path d="M9 5.978.401 0 .955.042"/>' in out, out
    assert "<style>.a .b{x:1}</style>" in out and "<script>var a = b .c;</script>" in out
    assert "<p>Hello, world.</p>" in out
    assert hygiene.clean_html_text(out) == out
    assert "<b>" not in hygiene.clean_html_text("<p>Tom &lt;b&gt; Jerry</p>")   # never creates a tag

    # 7 Nov 2026 review: what the verification pass rejects is removed from
    # markup too (metadata, links, JSON-LD), and entity whitespace beside an
    # inline element survives.
    head = ('<head><meta name="description" content="News 📰"><a href="https://x.org/p?utm_source=chatgpt.com">x</a>'
            '<script type="application/ld+json">{"d":"Hi 🎉"}</script></head>')
    fixed = hygiene.clean_html_text(head)
    assert not any(p.search(fixed) for p in hygiene.DETECTORS), fixed
    assert hygiene.clean_html_text(fixed) == fixed
    spaced = hygiene.clean_html_text("<p>Use <strong>bus</strong>&nbsp;services.</p>")
    assert "</strong>\xa0services" in spaced or "</strong> services" in spaced, spaced

    # Share rows are rebuilt from the official icons; an older page gets the
    # handler for the buttons its own script lacks; a second run changes nothing.
    import repair_share_icons as rs
    old_page = ('<html><body><h1>Old story</h1><div class="article-share" aria-label="Share this article">'
                '<button class="share-icon-button" data-share="copy" data-url="https://rochdaledaily.co.uk/articles/old">'
                '<svg><path d="M8 8h11v11H8z"/></svg></button></div>'
                '<script>if (action === "copy") {} if (action === "facebook") {} if (action === "whatsapp") {}</script></body></html>')
    fixed = rs.repair(old_page)
    for brand in ("brand-facebook", "brand-whatsapp", "brand-x", "brand-bluesky", "brand-email"):
        assert brand in fixed, brand
    assert 'id="rd-share-extra"' in fixed and 'data-title="Old story"' in fixed
    assert rs.repair(fixed) == fixed
    print("Content hygiene metadata and idempotency checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
