"""One failing feed must not zero the RSS + Google News collector (19 Oct 2026).

From 15:23 BST on 19 Oct every run logged
    collector_errors: {"rss_and_google_news": "Remote end closed connection without response"}
with rss_and_google_news = 0 (normally 47-128 leads). feedparser 6 lets
http.client.RemoteDisconnected escape when a server hangs up, and
collect_rss_candidates had no per-feed guard, so one feed aborted the loop and
safe_collect recorded the whole collector as empty.

This test runs the REAL collect_rss_candidates against two local servers: one
that hangs up exactly that way, and one serving a valid local feed.

Run from the repository root:  python scraper/test_rss_feed_isolation_oct2026.py
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE.parent)

import scraper as core  # noqa: E402


def _hang_up_server() -> int:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)

    def serve():
        while True:
            conn, _ = listener.accept()
            conn.recv(4096)
            conn.close()  # read the request, then close without any response

    threading.Thread(target=serve, daemon=True).start()
    return listener.getsockname()[1]


def _good_feed_server() -> int:
    stamp = format_datetime(datetime.now(timezone.utc))
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title><link>https://example.org/</link>
<item><title>Rochdale lollipop lady Barbara makes her final crossing outside Rochdale school</title>
<link>https://www.rochdaletimes.co.uk/final-crossing-for-popular-lollipop-lady-barbara/</link>
<description>A much-loved Rochdale lollipop lady has retired after decades helping children cross Yorkshire Street in Rochdale.</description>
<pubDate>{stamp}</pubDate></item>
</channel></rss>""".encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def test_one_hanging_feed_costs_only_itself():
    bad, good = _hang_up_server(), _good_feed_server()
    saved_sources, saved_google = core.RSS_SOURCES, core.google_news_sources
    core.RSS_SOURCES = [
        {"name": "Feed That Hangs Up", "url": f"http://127.0.0.1:{bad}/feed/", "default_area": "rochdale"},
        {"name": "Rochdale Times", "url": f"http://127.0.0.1:{good}/feed/", "default_area": "rochdale",
         "trusted_local": True},
    ]
    core.google_news_sources = lambda: []
    try:
        candidates = core.collect_rss_candidates()
    finally:
        core.RSS_SOURCES, core.google_news_sources = saved_sources, saved_google

    titles = [c.source_title for c in candidates]
    assert any("lollipop lady Barbara" in t for t in titles), titles
    assert "Feed That Hangs Up" in core.FEED_FETCH_FAILURES, core.FEED_FETCH_FAILURES
    assert "RemoteDisconnected" in core.FEED_FETCH_FAILURES["Feed That Hangs Up"]
    assert "Rochdale Times" not in core.FEED_FETCH_FAILURES


def test_failures_are_reset_each_run():
    core.FEED_FETCH_FAILURES["stale"] = "from an earlier run"
    saved_sources, saved_google = core.RSS_SOURCES, core.google_news_sources
    core.RSS_SOURCES, core.google_news_sources = [], (lambda: [])
    try:
        core.collect_rss_candidates()
    finally:
        core.RSS_SOURCES, core.google_news_sources = saved_sources, saved_google
    assert core.FEED_FETCH_FAILURES == {}


def test_status_file_names_failing_feeds():
    source = (HERE / "scraper.py").read_text(encoding="utf-8")
    assert "'feed_fetch_failures': dict(FEED_FETCH_FAILURES)" in source


if __name__ == "__main__":
    tests = [value for key, value in sorted(globals().items()) if key.startswith("test_")]
    for test in tests:
        test()
        print("ok", test.__name__)
    print(f"{len(tests)} passed")
