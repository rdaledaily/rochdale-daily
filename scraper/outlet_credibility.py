"""Is a news outlet credible? A test, not a list (editor, 15 Nov 2026).

"Just because they're not on our list doesn't mean they're not trusted. A rule
needs to be created where if a news outlet is credible it should be used
whether it's on our list or not."  Trigger: the follow-up desk dropped The
Bolton News and The Sun reports of the M62 closure near Milnrow only because
neither was on its hard-coded publisher list.

An outlet is credible when it is accountable to someone outside itself:

  1. never, whatever else is true, if the paper has banned it
     (link_ban: denied sources, gambling/piracy, Rochdale Online, UKLFI ...);
  2. a public body: .gov.uk, .police.uk, .nhs.uk, .parliament.uk, .mod.uk,
     .ac.uk, .sch.uk;
  3. a press-regulated publisher: its own page carries the IPSO or IMPRESS
     mark, a link to the regulator, or the regulator's name in a regulation
     statement. IPSO expects members to carry its mark online; almost all UK
     local and national newspapers are IPSO members; IMPRESS covers the
     independent titles;
  4. a broadcaster licensed by Ofcom (BBC, ITV, Sky, Channel 4/5, Global,
     Bauer local radio) - these do not carry a press-regulator mark.

Anything else is "credibility not established": it is not used, and it is
reported by name so the editor can see what was left out (no fallback tier).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

PUBLIC_SUFFIXES = (".gov.uk", ".police.uk", ".nhs.uk", ".parliament.uk", ".mod.uk", ".ac.uk", ".sch.uk")
PUBLIC_HOSTS = {"gov.uk", "parliament.uk", "judiciary.uk"}
OFCOM_BROADCASTERS = {
    "bbc.co.uk": "BBC", "bbc.com": "BBC", "itv.com": "ITV News", "itvx.com": "ITV News",
    "news.sky.com": "Sky News", "sky.com": "Sky News", "channel4.com": "Channel 4 News",
    "channel5.com": "Channel 5", "lbc.co.uk": "LBC", "heart.co.uk": "Heart",
    "capitalfm.com": "Capital", "smoothradio.com": "Smooth Radio", "greatesthitsradio.co.uk": "Greatest Hits Radio",
    "hitsradio.co.uk": "Hits Radio", "planetradio.co.uk": "Hits Radio",
}
REGULATOR_LINK_RE = re.compile(r"""href=["']https?://(?:www\.)?(?:ipso\.co\.uk|impress\.press|impressorg\.com)""", re.I)
REGULATOR_TEXT_RE = re.compile(
    r"Independent Press Standards Organisation|regulated by (?:IPSO|IMPRESS|Impress)|"
    r"(?:IPSO|IMPRESS|Impress)[- ]regulated|IPSO (?:mark|logo)|Editors' Code of Practice",
    re.I,
)


def host_of(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")


def _suffix_match(host: str, table: dict[str, str] | set[str]) -> str:
    for suffix in sorted(table, key=len, reverse=True):
        if host == suffix or host.endswith("." + suffix):
            return suffix
    return ""


def banned(url: str) -> bool:
    try:
        from link_ban import is_banned_host
    except Exception:  # noqa: BLE001
        return False
    return is_banned_host(host_of(url))


def verdict_without_page(url: str) -> dict[str, Any] | None:
    """Decide from the address alone where that is enough, else None."""
    host = host_of(url)
    if not host:
        return {"credible": False, "basis": "no address"}
    if banned(url):
        return {"credible": False, "basis": "banned by the paper"}
    if host in PUBLIC_HOSTS or host.endswith(PUBLIC_SUFFIXES):
        return {"credible": True, "basis": "public body", "official": True}
    match = _suffix_match(host, OFCOM_BROADCASTERS)
    if match:
        return {"credible": True, "basis": "Ofcom-licensed broadcaster", "name": OFCOM_BROADCASTERS[match]}
    return None


def verdict_from_html(url: str, raw_html: str) -> dict[str, Any]:
    early = verdict_without_page(url)
    if early:
        return early
    if REGULATOR_LINK_RE.search(raw_html or ""):
        return {"credible": True, "basis": "links to its press regulator (IPSO/IMPRESS)"}
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    if REGULATOR_TEXT_RE.search(text):
        return {"credible": True, "basis": "states it is press-regulated (IPSO/IMPRESS)"}
    return {"credible": False, "basis": "credibility not established: no press regulator, public body or broadcaster licence found"}


def fetch_html(url: str, timeout: float = 12.0) -> str:
    """The whole page, footer included (fetch_text stops at 40,000 characters,
    which cuts off the footer where the regulator mark usually sits)."""
    import requests

    response = requests.get(
        url, timeout=(5, timeout), allow_redirects=True,
        headers={"User-Agent": "RochdaleDailyFactCheck/1.0 (+https://rochdaledaily.co.uk/editorial-standards.html)",
                 "Accept": "text/html"},
    )
    response.raise_for_status()
    return response.text[:3_000_000]


def assess(url: str, memory: dict[str, Any] | None = None, fetch=fetch_html) -> dict[str, Any]:
    """Verdict for the outlet behind ``url``; cached per host in ``memory``."""
    host = host_of(url)
    early = verdict_without_page(url)
    if early:
        return early
    if memory is not None and host in memory:
        return memory[host]
    try:
        verdict = verdict_from_html(url, fetch(url))
    except Exception as exc:  # noqa: BLE001
        # A failed read is not a verdict: not cached, tried again next time.
        return {"credible": False, "basis": f"page could not be read ({type(exc).__name__})", "retry": True}
    if memory is not None:
        memory[host] = verdict
    return verdict
