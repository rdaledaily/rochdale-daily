"""Find published contact emails for active Rochdale-borough limited companies.

Reads tools/business_companies.csv (Companies House export: name, number,
postcode district). For each company it guesses the company's own website from
its name, keeps a site only when the site itself shows it belongs to that
company (its company number, its postcode district, or a borough place name),
and collects the emails published on that site.

It never guesses an address. Every email in the output was found on the
business's own pages, and the page it came from is recorded.

Output: business_emails.csv (+ business_emails_summary.md for the job summary).
Nothing is committed: the workflow uploads both files as an artifact.
"""

from __future__ import annotations

import csv
import html
import os
import re
import socket
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from urllib import robotparser

import requests
from bs4 import BeautifulSoup

USER_AGENT = "RochdaleDailyBot/1.0 (+https://rochdaledaily.co.uk/contact.html)"
TIMEOUT = float(os.environ.get("FINDER_TIMEOUT", "10"))
WORKERS = int(os.environ.get("FINDER_WORKERS", "16"))
MAX_PAGES = 4  # homepage + up to 3 contact/about pages
INPUT = os.environ.get("FINDER_INPUT", "tools/business_companies.csv")
OUTPUT = os.environ.get("FINDER_OUTPUT", "business_emails.csv")
SUMMARY = os.environ.get("FINDER_SUMMARY", "business_emails_summary.md")
LIMIT = int(os.environ.get("FINDER_LIMIT") or "0")  # 0 = all rows

PLACES = (
    "rochdale", "heywood", "middleton", "littleborough", "milnrow", "newhey",
    "wardle", "smithy bridge", "castleton", "norden", "bamford", "whitworth",
    "spotland", "kirkholt", "balderstone", "shawclough", "healey", "alkrington",
)
SUFFIXES = re.compile(
    r"\b(limited|ltd|llp|plc|cic|uk|u\.k|group|holdings|company|co|services|"
    r"trading|enterprises?|solutions)\b\.?",
    re.I,
)
LEGAL = re.compile(r"\b(limited|ltd|llp|plc|cic|private)\b", re.I)
TLDS = (".co.uk", ".com", ".uk")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
BAD_EMAIL_PARTS = (
    "example.", "sentry", "wixpress", "domain.com", "yourdomain", "email.com",
    "@2x", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "godaddy",
    "squarespace", "@sentry", "noreply", "no-reply", "donotreply",
)
PREFERRED = ("info", "hello", "enquiries", "enquiry", "contact", "office",
             "admin", "sales", "mail", "press", "media", "marketing")
CONTACT_HINTS = ("contact", "get-in-touch", "getintouch", "about", "find-us", "reach")


def slugs(name: str) -> list[str]:
    """Plausible domain labels for a company name, most likely first."""
    base = html.unescape(name).lower()
    base = re.sub(r"\([^)]*\)", " ", base)  # (NW), (OLDHAM) ...
    variants = []
    for amp in (" and ", " ", ""):
        n = base.replace("&", amp)
        full = re.sub(r"[^a-z0-9 ]+", " ", n.replace("'", ""))
        full = LEGAL.sub(" ", full)
        trimmed = SUFFIXES.sub(" ", full)
        for v in (trimmed, full):
            words = v.split()
            while words and words[-1] == "and":
                words.pop()
            while words and words[0] == "and":
                words.pop(0)
            if not words:
                continue
            variants.append("".join(words))
            variants.append("-".join(words))
    out, seen = [], set()
    for v in variants:
        if 3 <= len(v) <= 63 and v not in seen and not v.startswith("-"):
            seen.add(v)
            out.append(v)
    return out[:6]


def candidate_domains(name: str) -> list[str]:
    return [s + t for s in slugs(name) for t in TLDS]


def resolves(domain: str) -> bool:
    try:
        socket.getaddrinfo(domain, 443)
        return True
    except OSError:
        return False


def decode_cfemail(hexstr: str) -> str:
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""


def clean_email(raw: str) -> str | None:
    e = raw.strip().strip(".,;:'\"").lower()
    e = e.split("?")[0]
    if not EMAIL_RE.fullmatch(e):
        return None
    if any(b in e for b in BAD_EMAIL_PARTS):
        return None
    return e


def emails_in(soup: BeautifulSoup, text: str) -> set[str]:
    found = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            e = clean_email(href[7:])
            if e:
                found.add(e)
        if "/cdn-cgi/l/email-protection#" in href:
            e = clean_email(decode_cfemail(href.split("#", 1)[1]))
            if e:
                found.add(e)
    for tag in soup.select("[data-cfemail]"):
        e = clean_email(decode_cfemail(tag.get("data-cfemail", "")))
        if e:
            found.add(e)
    for m in EMAIL_RE.findall(text):
        e = clean_email(m)
        if e:
            found.add(e)
    return found


def ownership_evidence(text: str, number: str, district: str) -> str | None:
    t = text.lower()
    num = number.lstrip("0")
    if number and (number.lower() in t or (len(num) >= 6 and re.search(rf"\b0*{num}\b", t))):
        return "company number"
    if district and re.search(rf"\b{re.escape(district.lower())}\s*\d[a-z]{{2}}\b", t):
        return "postcode"
    for p in PLACES:
        if re.search(rf"\b{p}\b", t):
            return f"place:{p}"
    return None


def rank(email: str, site_host: str) -> tuple:
    local, _, dom = email.partition("@")
    own = site_host.endswith(dom) or dom.endswith(site_host.removeprefix("www."))
    pref = PREFERRED.index(local) if local in PREFERRED else len(PREFERRED)
    return (0 if own else 1, pref, email)


class Fetcher:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"})
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
        with self._lock:
            cached = self._robots.get(root, "miss")
        if cached == "miss":
            rp = None
            try:
                r = self.s.get(root + "/robots.txt", timeout=TIMEOUT)
                if r.status_code == 200:  # only honour a real robots file
                    rp = robotparser.RobotFileParser()
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp = None
            with self._lock:
                self._robots[root] = rp
            cached = rp
        return cached is None or cached.can_fetch(USER_AGENT, url)

    def get(self, url: str):
        if not self.allowed(url):
            return None
        try:
            r = self.s.get(url, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            return None
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or "html" not in ctype:
            return None
        return r


def check_site(fetcher: Fetcher, domain: str, number: str, district: str):
    home = None
    for scheme in ("https://", "http://"):
        home = fetcher.get(scheme + domain + "/")
        if home is not None:
            break
    if home is None:
        return None
    host = urlparse(home.url).netloc.lower()
    pages = [home]
    soup = BeautifulSoup(home.text, "lxml")
    extra = []
    for a in soup.find_all("a", href=True):
        href = urljoin(home.url, a["href"])
        hp = urlparse(href)
        if hp.netloc.lower() != host:
            continue
        label = (hp.path + " " + a.get_text(" ")).lower()
        if any(h in label for h in CONTACT_HINTS) and href not in extra and href != home.url:
            extra.append(href)
    for url in extra[: MAX_PAGES - 1]:
        r = fetcher.get(url)
        if r is not None:
            pages.append(r)
    text_all, emails, sources = "", {}, {}
    for r in pages:
        sp = BeautifulSoup(r.text, "lxml")
        txt = sp.get_text(" ", strip=True)
        text_all += " " + txt
        for e in emails_in(sp, txt):
            sources.setdefault(e, r.url)
            emails[e] = True
    evidence = ownership_evidence(text_all, number, district)
    return {
        "website": home.url,
        "host": host,
        "evidence": evidence,
        "emails": sorted(emails, key=lambda e: rank(e, host)),
        "sources": sources,
    }


def find_for(company: dict, fetcher: Fetcher, resolver=resolves) -> dict:
    row = {
        "company_name": company["company_name"],
        "company_number": company["company_number"],
        "postcode_district": company["postcode_district"],
        "priority": company.get("priority", ""),
        "website": "", "email": "", "other_emails": "", "found_on": "",
        "evidence": "", "confidence": "", "note": "",
    }
    tried = 0
    for domain in candidate_domains(company["company_name"]):
        if not resolver(domain):
            continue
        tried += 1
        site = check_site(fetcher, domain, company["company_number"], company["postcode_district"])
        if site is None:
            continue
        if not site["evidence"]:
            row["note"] = row["note"] or f"site {site['host']} shows no Rochdale link"
            continue
        row["website"] = site["website"]
        row["evidence"] = site["evidence"]
        row["confidence"] = "high" if site["evidence"] in ("company number", "postcode") else "medium"
        if site["emails"]:
            row["email"] = site["emails"][0]
            row["other_emails"] = " ".join(site["emails"][1:4])
            row["found_on"] = site["sources"][row["email"]]
            row["note"] = ""
        else:
            row["note"] = "own site found, no email published"
        break
    if not row["website"] and not row["note"]:
        row["note"] = "no website found" if tried else "no matching domain"
    return row


def main() -> int:
    with open(INPUT, newline="", encoding="utf-8") as f:
        companies = list(csv.DictReader(f))
    if LIMIT:
        companies = companies[:LIMIT]
    fetcher = Fetcher()
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(lambda c: find_for(c, fetcher), companies))
    fields = list(rows[0].keys()) if rows else []
    rows.sort(key=lambda r: (r["email"] == "", r["confidence"] != "high", r["company_name"]))
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    with_email = [r for r in rows if r["email"]]
    sites = [r for r in rows if r["website"]]
    high = [r for r in with_email if r["confidence"] == "high"]
    lines = [
        "# Business email finder",
        "",
        f"- Companies checked: **{n}**",
        f"- Own website found (with a Rochdale link on it): **{len(sites)}**",
        f"- Published email found: **{len(with_email)}** ({len(high)} high confidence, "
        f"{len(with_email) - len(high)} medium)",
        f"- Website but no email published: **{len(sites) - len(with_email)}**",
        f"- No website found: **{n - len(sites)}**",
        f"- Run time: {int(time.time() - started)}s",
        "",
        "Download the `business-emails` artifact for the full list. "
        "High = the site shows the company number or the registered postcode district; "
        "medium = the site names a borough place.",
    ]
    with open(SUMMARY, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
