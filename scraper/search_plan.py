"""Fewer, merged, rotated Google News searches (24 Nov 2026).

Measured over the three fast runs before 21:00 on 24 Nov 2026: the plan sent
60 Google News RSS searches every 20 minutes (~4,300 a day from GitHub's IPs).
Google answered up to 14 a run with a block page instead of RSS, and 26 of the
60 returned nothing in all three runs: 11 formal ward names news never uses,
8 single party-website searches and 7 single official-site searches. The MEN
was also searched twice with identical results.

This module rewrites the plan without losing coverage:
  * the 20 ward searches become 4 OR-grouped searches;
  * the party-website searches become one OR-of-sites search;
  * the official-site searches (GMP, council, TfGM, fire, NHS) become one;
  * the duplicate MEN fallback is dropped;
  * a short list of breaking-news searches runs every time, and everything
    else alternates between two halves, so each still runs every 40 minutes.
    Every search covers the last one or two days, so nothing is missed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")

# Every search across BOTH alternating halves, set by the last plan() call.
# The health check judges coverage on this, not on one run's half.
LAST_ROTATION: list = []

WARD_GROUP_SIZE = 5
WARD_TERMS = "(news OR police OR appeal OR traffic OR council OR charity OR event OR sport)"
BOROUGH = "(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow)"

PARTY_SITES = (
    "reformparty.uk", "restorebritain.org.uk", "workerspartygb.org", "rochdale.laboursites.org",
    "rochdalelibdems.org.uk", "rochdale.greenparty.org.uk", "hmnrconservatives.org.uk",
)
OFFICIAL_SITES = (
    "gmp.police.uk", "rochdale.gov.uk", "news.tfgm.com", "tfgm.com",
    "manchesterfire.gov.uk", "northerncarealliance.nhs.uk",
)
PARTY_LABELS = (
    "priority:reform-rochdale", "priority:restore-rochdale", "priority:workers-party-rochdale",
    "priority:labour-rochdale", "priority:libdem-rochdale", "priority:green-rochdale",
    "priority:conservative-rochdale",
)
OFFICIAL_LABELS = (
    "priority:crime-fast", "official-gmp:", "fallback:gmp-rochdale-today", "fallback:rochdale-council-today",
    "fallback:tfgm-rochdale-today", "fallback:fire-rochdale-today", "fallback:nca-rochdale-today",
)
DROP_LABELS = ("fallback:men-rochdale-today",)  # identical results to source:manchester-evening-news

# Breaking news: run on every pass.
EVERY_RUN = (
    "category:crime", "category:traffic", "priority:crime-web", "priority:roads",
    "source:manchester-evening-news", "source:rochdale-times", "source:roch-valley-radio",
    "official:sites",
)


def _starts(label: str, prefixes: Sequence[str]) -> bool:
    """Exact label match; entries ending in ':' match a numbered family."""
    return any(label == p or (p.endswith(":") and label.startswith(p)) for p in prefixes)


def shard_index(now: datetime | None = None) -> int:
    """0 or 1, alternating every 20-minute run slot."""
    current = now or datetime.now(timezone.utc)
    return (current.hour * 3 + current.minute // 20) % 2


def plan(specs: list[T], make: Callable[..., T], now: datetime | None = None) -> list[T]:
    """Return this run's searches. ``make`` builds a spec (label, query, category)."""
    wards = [s for s in specs if s.label.startswith("ward:")]
    kept: list[T] = []
    for s in specs:
        if s.label.startswith("ward:") or _starts(s.label, PARTY_LABELS + OFFICIAL_LABELS + DROP_LABELS):
            continue
        kept.append(s)

    merged: list[T] = []
    names = [s.ward or s.label.split(":", 1)[1] for s in wards]
    for i in range(0, len(names), WARD_GROUP_SIZE):
        group = names[i:i + WARD_GROUP_SIZE]
        query = "(" + " OR ".join(f'"{n}"' for n in group) + f") {WARD_TERMS} when:2d"
        merged.append(make(label=f"wards:{i // WARD_GROUP_SIZE + 1}", query=query, category="news"))
    if any(_starts(s.label, PARTY_LABELS) for s in specs):
        sites = " OR ".join(f"site:{d}" for d in PARTY_SITES)
        merged.append(make(label="parties:sites", query=f"({sites}) Rochdale when:2d", category="politics"))
    if any(_starts(s.label, OFFICIAL_LABELS) for s in specs):
        sites = " OR ".join(f"site:{d}" for d in OFFICIAL_SITES)
        merged.append(make(label="official:sites", query=f"({sites}) {BOROUGH} when:2d", category="news"))

    everything = kept + merged
    always = [s for s in everything if s.label in EVERY_RUN]
    rotating = [s for s in everything if s.label not in EVERY_RUN]
    LAST_ROTATION[:] = always + rotating
    return always + rotating[shard_index(now)::2]
