#!/usr/bin/env python3
"""One publisher identity, and places that sit inside Rochdale borough, in every page's structured data.

Google News and Search weigh trust signals a publisher declares in its markup:
who publishes, the standards it works to, how it corrects mistakes and how
readers can complain. On 19 October 2026 the site declared none of them: the
publisher block on 1,711 article pages was a name, a URL and a logo.

Every NewsMediaOrganization named "Rochdale Daily" in any JSON-LD block is
replaced with the full publisher below (keeping its @id, if any), pointing at
the paper's own published policy pages.

Article places are also tied to the borough. "Heywood" alone is ambiguous to a
search engine; "Heywood, inside the Metropolitan Borough of Rochdale, Greater
Manchester" is what lets a Heywood story answer a search that alludes to
Rochdale without naming it.

Applied by normalise_public_theme.py, which every lane runs last, and checked
by CI through the theme check. generate_pages.py uses the same publisher.
"""
from __future__ import annotations

import json
import re
from typing import Any

SITE = "https://rochdaledaily.co.uk"
BOROUGH = {"@type": "AdministrativeArea", "name": "Metropolitan Borough of Rochdale",
           "containedInPlace": {"@type": "AdministrativeArea", "name": "Greater Manchester"}}

PUBLISHER: dict[str, Any] = {
    "@type": "NewsMediaOrganization",
    "name": "Rochdale Daily",
    "url": SITE + "/",
    "logo": {"@type": "ImageObject", "url": f"{SITE}/assets/img/logo.png"},
    "areaServed": BOROUGH,
    "publishingPrinciples": f"{SITE}/editorial-standards",
    "ethicsPolicy": f"{SITE}/editorial-standards",
    "verificationFactCheckingPolicy": f"{SITE}/editorial-standards#accuracy",
    "noBylinesPolicy": f"{SITE}/editorial-standards#automation",
    "correctionsPolicy": f"{SITE}/corrections-and-complaints",
    "actionableFeedbackPolicy": f"{SITE}/corrections-and-complaints",
    "masthead": f"{SITE}/about",
    "contactPoint": {"@type": "ContactPoint", "contactType": "newsdesk", "url": f"{SITE}/contact",
                     "areaServed": "GB", "availableLanguage": "en-GB"},
}

_BLOCK_RE = re.compile(r'(<script type="application/ld\+json"[^>]*>)(.*?)(</script>)', re.S)


def publisher(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    full = dict(PUBLISHER)
    if existing and existing.get("@id"):
        full = {"@id": existing["@id"], **full}
    return full


def place(name: str) -> dict[str, Any]:
    name = str(name or "").strip() or "Rochdale"
    return {
        "@type": "Place",
        "name": name,
        "address": {"@type": "PostalAddress", "addressLocality": name,
                    "addressRegion": "Greater Manchester", "addressCountry": "GB"},
        "containedInPlace": BOROUGH,
    }


def _enrich(node: Any) -> Any:
    if isinstance(node, list):
        return [_enrich(item) for item in node]
    if not isinstance(node, dict):
        return node
    if node.get("@type") == "NewsMediaOrganization" and node.get("name") == "Rochdale Daily":
        return publisher(node)
    out = {key: _enrich(value) for key, value in node.items()}
    location = out.get("contentLocation")
    if isinstance(location, dict) and location.get("@type") == "Place" and "containedInPlace" not in location:
        out["contentLocation"] = place(location.get("name", ""))
    return out


def enrich_text(text: str) -> str:
    """Rewrite only the JSON-LD blocks that change; anything unparseable is left as it is."""
    if "application/ld+json" not in text:
        return text

    def block(match: re.Match[str]) -> str:
        try:
            data = json.loads(match.group(2))
        except ValueError:
            return match.group(0)
        enriched = _enrich(data)
        if enriched == data:
            return match.group(0)
        body = json.dumps(enriched, ensure_ascii=False).replace("</", "<\\/")
        return match.group(1) + body + match.group(3)

    return _BLOCK_RE.sub(block, text)
