#!/usr/bin/env python3
"""Rochdale Daily — ModernGov access diagnostic.

WHY THIS EXISTS
---------------
The News-by-Ward voting records feature (ward_areas / council_roster /
council_votes) is blocked on reading Rochdale council's ModernGov site, which
plain requests from GitHub Actions have failed against before. Before building
a Playwright collector, this probe measures what actually works and what data
exists, so the collector is built against reality rather than assumption.

It answers four questions and writes the evidence to ./moderngov_probe_out/:
  1. Which hostname responds: rochdale.moderngov.co.uk, democracy.rochdale.gov.uk?
  2. Does plain HTTP (requests) get real pages, or is a browser required?
  3. If a browser is required, does Playwright/Chromium get real pages?
  4. Do the pages we need exist: committee list, member index, Council
     meetings list, and per-meeting attendance? Are recorded votes published
     as structured pages, or only inside minutes PDFs?

READ-ONLY: it fetches a handful of public pages politely (2s delay) and never
posts anything. Run from the moderngov-diagnostic workflow; results land in
the run's uploaded artifact. It always exits 0 — a blocked host is a finding,
not a failure.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

OUT_DIR = Path("moderngov_probe_out")
HOSTS = [
    "https://rochdale.moderngov.co.uk",
    "https://democracy.rochdale.gov.uk",
]
# The pages the votes feature needs. CId=156 is the full Council committee
# (democracy.rochdale.gov.uk/mgCommitteeDetails.aspx?ID=156).
PATHS = [
    ("committees", "/mgListCommittees.aspx?bcr=1"),
    ("members", "/mgMemberIndex.aspx?bcr=1"),
    ("council_meetings", "/ieListMeetings.aspx?CId=156&Year=0"),
    ("attendance_summary", "/mgUserAttendanceSummary.aspx?XXR=0"),
]
# Markers that distinguish a real ModernGov page from an error / challenge page.
REAL_PAGE_MARKERS = [
    re.compile(r"mgListCommittees|ieListDocuments|mgMemberIndex|mgCommitteeDetails", re.I),
    re.compile(r"modern\.?gov", re.I),
    re.compile(r"agenda|committee|councillor", re.I),
]
CHALLENGE_MARKERS = re.compile(
    r"cf-browser-verification|captcha|access denied|request unsuccessful|"
    r"attention required|just a moment", re.I
)
DELAY_SECONDS = 2.0

summary: list[str] = []
findings: dict[str, dict] = {}


def log(line: str) -> None:
    print(line, flush=True)
    summary.append(line)


def classify(status: int | None, body: str) -> str:
    if status is None:
        return "no-response"
    if status != 200:
        return f"http-{status}"
    if CHALLENGE_MARKERS.search(body or ""):
        return "challenge-page"
    if len(body or "") < 2000:
        return "thin-page"
    if any(marker.search(body) for marker in REAL_PAGE_MARKERS):
        return "real-page"
    return "unrecognised-page"


def save(name: str, body: str) -> None:
    (OUT_DIR / f"{name}.html").write_text(body or "", encoding="utf-8")


def probe_requests() -> None:
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": "RochdaleDaily-diagnostic/1.0 (news@rochdaledaily.co.uk)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    for host in HOSTS:
        for name, path in PATHS:
            key = f"requests {host} {name}"
            url = host + path
            try:
                response = session.get(url, timeout=30, allow_redirects=True)
                verdict = classify(response.status_code, response.text)
                save(f"requests_{host.split('//')[1].split('.')[0]}_{name}", response.text)
                findings[key] = {
                    "url": url,
                    "status": response.status_code,
                    "final_url": response.url,
                    "bytes": len(response.text),
                    "verdict": verdict,
                }
                log(f"  {verdict:<18} {key}  ({response.status_code}, {len(response.text)}B)")
            except Exception as exc:  # noqa: BLE001 — a diagnostic records, never raises
                findings[key] = {"url": url, "verdict": "exception", "error": str(exc)[:200]}
                log(f"  exception          {key}  ({str(exc)[:120]})")
            time.sleep(DELAY_SECONDS)


def probe_playwright() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("  playwright not installed — skipping browser stage")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            locale="en-GB",
        )
        for host in HOSTS:
            for name, path in PATHS:
                key = f"playwright {host} {name}"
                url = host + path
                try:
                    response = page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    body = page.content()
                    status = response.status if response else None
                    verdict = classify(status, body)
                    save(f"playwright_{host.split('//')[1].split('.')[0]}_{name}", body)
                    findings[key] = {
                        "url": url,
                        "status": status,
                        "final_url": page.url,
                        "bytes": len(body),
                        "verdict": verdict,
                    }
                    log(f"  {verdict:<18} {key}  ({status}, {len(body)}B)")
                    # From a working Council meetings list, follow one meeting to
                    # its agenda page and look for attendance / recorded-vote
                    # links — the pages the feature actually needs.
                    if name == "council_meetings" and verdict == "real-page":
                        meeting = page.query_selector("a[href*='ieListDocuments.aspx']")
                        if meeting:
                            meeting_url = meeting.get_attribute("href") or ""
                            if meeting_url and not meeting_url.startswith("http"):
                                meeting_url = host + "/" + meeting_url.lstrip("/")
                            page.goto(meeting_url, timeout=45000, wait_until="domcontentloaded")
                            page.wait_for_timeout(2000)
                            meeting_body = page.content()
                            save(f"playwright_{host.split('//')[1].split('.')[0]}_meeting_sample", meeting_body)
                            attendance = bool(re.search(r"mgAttendanceDetails|Attendance", meeting_body))
                            votes = bool(re.search(r"recorded vote|mgIssueHistory|voting", meeting_body, re.I))
                            findings[f"playwright {host} meeting_sample"] = {
                                "url": meeting_url,
                                "attendance_link_present": attendance,
                                "vote_markers_present": votes,
                            }
                            log(f"  meeting sample     {host}  attendance={attendance} vote_markers={votes}")
                except Exception as exc:  # noqa: BLE001
                    findings[key] = {"url": url, "verdict": "exception", "error": str(exc)[:200]}
                    log(f"  exception          {key}  ({str(exc)[:120]})")
                time.sleep(DELAY_SECONDS)
        browser.close()


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    log("ModernGov diagnostic — stage 1: plain requests")
    probe_requests()
    log("ModernGov diagnostic — stage 2: Playwright/Chromium")
    probe_playwright()

    real_requests = [k for k, v in findings.items() if k.startswith("requests") and v.get("verdict") == "real-page"]
    real_playwright = [k for k, v in findings.items() if k.startswith("playwright") and v.get("verdict") == "real-page"]
    log("")
    log("VERDICT")
    if real_requests:
        log(f"  Plain requests works for {len(real_requests)} page(s) — a browser may not be needed.")
    elif real_playwright:
        log(f"  Plain requests blocked; Playwright works for {len(real_playwright)} page(s) — build the collector on Playwright.")
    else:
        log("  Neither access path returned real pages from this runner. Inspect the saved HTML dumps —"
            " if they show a challenge page, ModernGov is blocking Actions IPs and the collector"
            " needs a different approach (e.g. a scheduled run from another network, or the"
            " council's published minutes documents instead).")

    (OUT_DIR / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    (OUT_DIR / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
