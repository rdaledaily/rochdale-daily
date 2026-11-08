"""Offline tests for tools/business_email_finder.py (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import business_email_finder as f  # noqa: E402


class Resp:
    def __init__(self, url, body, status=200, ctype="text/html"):
        self.url, self.text, self.status_code = url, body, status
        self.headers = {"content-type": ctype}


def make_fetcher(pages):
    fetcher = f.Fetcher()

    def get(url, timeout=None, allow_redirects=True):
        if url.endswith("/robots.txt"):
            return Resp(url, "", 404, "text/plain")
        if url in pages:
            return Resp(url, pages[url])
        raise f.requests.ConnectionError(url)

    fetcher.s.get = get
    return fetcher


def test_slugs_strip_suffixes_and_ampersand():
    s = f.slugs("SMART RANGE KITCHENS LIMITED")
    assert "smartrangekitchens" in s and "smart-range-kitchens" in s
    s2 = f.slugs("OTTI & RALPH LTD")
    assert "ottiandralph" in s2 and "ottiralph" in s2
    s3 = f.slugs("AAA SECURITY SHUTTERS (NW) LTD")
    assert all("nw" not in x for x in s3)


def test_finds_email_with_company_number_evidence():
    pages = {
        "https://smartrangekitchens.co.uk/": '<a href="/contact">Contact us</a> Smart Range Kitchens',
        "https://smartrangekitchens.co.uk/contact": 'Company no. 01234567 <a href="mailto:Info@SmartRangeKitchens.co.uk">email</a>',
    }
    row = f.find_for(
        {"company_name": "SMART RANGE KITCHENS LIMITED", "company_number": "01234567", "postcode_district": "OL16"},
        make_fetcher(pages),
        resolver=lambda d: d == "smartrangekitchens.co.uk",
    )
    assert row["email"] == "info@smartrangekitchens.co.uk"
    assert row["confidence"] == "high" and row["evidence"] == "company number"
    assert row["found_on"].endswith("/contact")


def test_rejects_same_name_site_with_no_rochdale_link():
    pages = {"https://acornbuilding.co.uk/": 'Acorn Building, Plymouth PL1 2AB <a href="mailto:hi@acornbuilding.co.uk">x</a>'}
    row = f.find_for(
        {"company_name": "ACORN BUILDING SERVICES LTD", "company_number": "09999999", "postcode_district": "OL12"},
        make_fetcher(pages),
        resolver=lambda d: d == "acornbuilding.co.uk",
    )
    assert row["email"] == "" and "no Rochdale link" in row["note"]


def test_cloudflare_obfuscated_email_and_postcode_evidence():
    key = 0x42
    enc = "%02x" % key + "".join("%02x" % (ord(c) ^ key) for c in "hello@glasslab.co.uk")
    pages = {"https://glasslab.co.uk/": f'Unit 6, Rochdale OL16 2AU <span data-cfemail="{enc}">[email]</span>'}
    row = f.find_for(
        {"company_name": "GLASSLAB LIMITED", "company_number": "12345678", "postcode_district": "OL16"},
        make_fetcher(pages),
        resolver=lambda d: d == "glasslab.co.uk",
    )
    assert row["email"] == "hello@glasslab.co.uk" and row["evidence"] == "postcode"


def test_junk_emails_ignored_and_own_domain_preferred():
    pages = {"https://ajsoff.co.uk/": "Heywood. a@sentry.io logo@2x.png bob@gmail.com shop@ajsoff.co.uk"}
    row = f.find_for(
        {"company_name": "AJS OFF LTD", "company_number": "1", "postcode_district": "OL10"},
        make_fetcher(pages),
        resolver=lambda d: d == "ajsoff.co.uk",
    )
    assert row["email"] == "shop@ajsoff.co.uk" and "bob@gmail.com" in row["other_emails"]
    assert row["confidence"] == "medium"


def test_robots_disallow_is_respected():
    fetcher = make_fetcher({"https://blocked.co.uk/": "Rochdale info@blocked.co.uk"})
    real = fetcher.s.get

    def get(url, timeout=None, allow_redirects=True):
        if url == "https://blocked.co.uk/robots.txt":
            return Resp(url, "User-agent: *\nDisallow: /", 200, "text/plain")
        return real(url, timeout=timeout)

    fetcher.s.get = get
    row = f.find_for(
        {"company_name": "BLOCKED LTD", "company_number": "1", "postcode_district": "OL11"},
        fetcher,
        resolver=lambda d: d == "blocked.co.uk",
    )
    assert row["email"] == ""
