"""Regression tests for the October 2026 newsroom blockade.

Every title below is a real candidate from rewrite_ledger.json in the week to
19 Oct 2026. Run: PYTHONPATH=scraper python scraper/test_newsroom_unblock_oct2026.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import editorial_upgrade as eu  # noqa: E402
from locality_rules import source_is_denied  # noqa: E402
from story_blocklist import is_blocked_text, is_stream_spam_title, load_blocklist  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        FAILURES.append(label)


# --- piracy "watch free" pages ------------------------------------------
SPAM = [
    "++(+!LIVESTREAMs/FREE+)!Crewe vs Rochdale Live freeCrewe vs Rochdale - Universidad de Córdoba (UCO)",
    "[SPORT TV™]!Crewe vs Rochdale 𝐋𝐈𝐕𝐄 Ｓｔｒｅａｍｓ ＯＮ Ｔｖ Ｃｈａｎｎｅ - Universidad de Córdoba (UCO)",
    "![[[TOTAL SPORTEK>]]>>] Crewe Alex vs Rochdale AFC England League Two 𝐋𝐈𝐕𝐄 Ｓｔｒｅａｍｓ On TV - Universidad de",
    "[𝐒𝐓ream]HERE's*! Crewe - Rochdale Live Free Stream - Universidad de Córdoba (UCO)",
    "Here's Got the ways to watch!!!~ Rochdale AFC vs Crewe Alexandra FC En streaming - Universidad de Córdoba",
    "[ＬＩＶＥ ＴＶ ＣＨＡＮＮＥＬ ＦＲＥＥ] Rochdale vs. Crewe Match Live streaming free - Universidad de Córdoba (UCO)",
    "LIVESTREAMs]!REDDIT!] Rochdale vs Crewe Alexandra 𝐋𝐈𝐕𝐄 𝙵𝚛𝚎𝚎 𝚂𝚝𝚛𝚎𝚊𝚖𝚜 𝙾𝚗 𝚂𝚙𝚘𝚛𝚝'𝚜𝚃𝚟",
]
# "Crewe - Rochdale Live Free Stream" has no "vs": still caught by the domain.
for title in SPAM:
    blocked = is_stream_spam_title(title) or source_is_denied("Universidad de Córdoba (UCO)", "https://www.uco.es/scai/x")
    check(blocked, f"spam not blocked: {title[:60]}")
check(source_is_denied("", "https://www.uco.es/scai/visita_virtual/x.html"), "uco.es not denied")

REAL_SPORT = [
    "Crewe 3-2 Rochdale | League Two highlights - Sky Sports",
    "Jordan Gibson nets twice as Crewe beat Rochdale to remain unbeaten",
    "Rochdale vs Crewe: team news and kick-off time",
    "Dale Defeated At Stockport - Rochdale AFC",
]
for title in REAL_SPORT:
    check(not is_stream_spam_title(title), f"real sport wrongly treated as spam: {title}")

# --- Northern page furniture --------------------------------------------
blocklist = load_blocklist()
northern = ("Service updates Live train times, planned disruption and events Breadcrumb Home "
            "Service updates The route")
check(is_blocked_text(northern, "https://www.northernrailway.co.uk/service-updates#live-8b60", blocklist),
      "Northern service-updates boilerplate not blocked")
check(not is_blocked_text("Rochdale line closed between Smithy Bridge and Todmorden after landslip",
                          "https://www.northernrailway.co.uk/service-updates#live-1", blocklist),
      "a real Northern alert was blocked")

# --- model NON_LOCAL veto -----------------------------------------------
NON_LOCAL = [eu.GATE_REJECTION_PREFIX + "NON_LOCAL: the model determined the material is not about the Rochdale borough."]
borough = {
    "Heywood AODS": "Heywood AODS visit. Members of Heywood AODS visited the studio in Heywood town centre to talk about their new production.",
    "Springhill": "Springhill Hospice to host free will information clinic in Rochdale on Tuesday 27 October.",
    "AFC away": "Dale Defeated At Stockport. Rochdale AFC were beaten at Edgeley Park on Saturday.",
    "Peacocks": "Lisa Riley opens new Peacocks store at Rochdale Riverside.",
}
elsewhere = {
    "Bury school": "£13 million Millwood Primary School expansion officially opened in Bury.",
    "Queensland": "Fatal traffic crash, Rochdale South. Queensland Police News: a man died on Logan Road.",
    "Massachusetts": "Judith A. Bergin Obituary (2026) - Leicester/Rochdale, MA. Born in Worcester, Massachusetts.",
    "Failsworth": "Failsworth Tram Stop - Lift out of service.",
}
for name, text in borough.items():
    check(eu._borough_evidence_overrules_non_local(NON_LOCAL, text), f"borough story still vetoed: {name}")
for name, text in elsewhere.items():
    check(not eu._borough_evidence_overrules_non_local(NON_LOCAL, text), f"non-local story let through: {name}")
non_news = [eu.GATE_REJECTION_PREFIX + "NON_NEWS: the model classified this material as advert."]
check(not eu._borough_evidence_overrules_non_local(non_news, borough["Peacocks"]),
      "override must only ever touch NON_LOCAL")

# --- calendar-year gate --------------------------------------------------
# Judge the year rule itself, not the model self-classification fields.
os.environ["TRUST_MODEL_SELF_CLASSIFICATION"] = "false"
year = str(time.gmtime().tm_year)
check(eu._source_has_yearless_date("The service will be held on Saturday 17 October at St Chad's."),
      "yearless date not recognised")
check(eu._source_has_yearless_date("Kick-off is on October 24th."), "US-order yearless date not recognised")
check(not eu._source_has_yearless_date("The plan was approved on 17 October 2024."),
      "dated-with-year source treated as yearless")
check(not eu._source_has_yearless_date("Residents may 2 or 3 times object."), "modal 'may' misread")

draft = {
    "title": "Harvest thanksgiving service to be held in Rochdale on 17 October",
    "excerpt": "A harvest thanksgiving service will be held at St Chad's in Rochdale on Saturday 17 October " + year + ".",
    "paragraphs": ["The service takes place on 17 October " + year + " at St Chad's Church in Rochdale."],
}
source = "A harvest thanksgiving service will be held at St Chad's Church, Rochdale, on Saturday 17 October."
issues = eu.quality_issues(draft, source)
check(not any("unpublishable" in i for i in issues), f"test draft not reaching the year rule: {issues}")
check(not any("unsupported calendar year" in i for i in issues), f"current year still rejected: {issues}")
draft_old = dict(draft, paragraphs=["The church first held the service in 1998 and again in 2019."])
issues_old = eu.quality_issues(draft_old, source)
check(any("unsupported calendar year" in i and "2019" in i for i in issues_old),
      "an invented past year must still be rejected")

if FAILURES:
    print("FAILED:")
    for item in FAILURES:
        print(" -", item)
    raise SystemExit(1)
print("newsroom unblock regression: all checks passed")
