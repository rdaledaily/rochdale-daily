"""Route a few blocked public sources through the rd-relay Cloudflare Worker.

GMP, Rochdale AFC, the AFC Community Trust and Falinge Park answer GitHub
Actions' IPs with HTTP 403 for every page, robots.txt included (measured
4 Nov 2026). workers/rd-relay/worker.js fetches the same public pages from
Cloudflare, identified as Rochdale Daily, and enforces each site's robots.txt.

Configuration lives in scraper/feed_proxy.json (in the repo, so no workflow
or secret changes):
    {"base_url": "https://rd-relay.<account>.workers.dev", "hosts": [...]}
With base_url empty the relay is off and nothing changes.

No fallback: if the relay is off or a site refuses it, the feed reports a
shortfall in scraper_status.json; nothing else stands in for it. The MEN is
deliberately not on the list (it challenges bots on purpose).
"""
from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from requests.adapters import HTTPAdapter

CONFIG_PATH = Path(__file__).resolve().parent / 'feed_proxy.json'
_LOCK = threading.Lock()
STATS: Counter = Counter()


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'base_url': '', 'hosts': []}
    base = str(data.get('base_url') or '').strip().rstrip('/')
    if base and not base.startswith('https://'):
        base = ''
    hosts = sorted({str(h).strip().lower() for h in data.get('hosts') or [] if str(h).strip()})
    return {'base_url': base, 'hosts': hosts}


def covered(url: str, config: dict[str, Any]) -> bool:
    host = (urlparse(str(url or '')).hostname or '').lower()
    return bool(config.get('base_url')) and host in set(config.get('hosts') or [])


def relay_url(url: str, config: dict[str, Any]) -> str:
    return f"{config['base_url']}/fetch?url={quote(str(url), safe='')}"


class RelayAdapter(HTTPAdapter):
    """Sends a covered host's request to the relay, and hands back a response
    that looks like the site's own (original URL, upstream status)."""

    def __init__(self, config: dict[str, Any], **kwargs: Any):
        super().__init__(**kwargs)
        # Not "self.config": HTTPAdapter.__init__ claims that name.
        self.relay_config = config

    def send(self, request, **kwargs):  # type: ignore[override]
        original = request.url
        if not covered(original, self.relay_config):
            return super().send(request, **kwargs)
        request.url = relay_url(original, self.relay_config)
        response = super().send(request, **kwargs)
        final = response.headers.get('x-relay-final-url') or original
        response.url = final
        with _LOCK:
            STATS[f"{urlparse(original).hostname}: HTTP {response.status_code}"] += 1
        return response


def install(session: Any, config: dict[str, Any] | None = None, **adapter_kwargs: Any) -> dict[str, Any]:
    """Mount the relay on a requests session for each covered host. Returns
    the config in force. A no-op when base_url is empty."""
    config = config if config is not None else load_config()
    if not config.get('base_url'):
        return config
    adapter = RelayAdapter(config, **adapter_kwargs)
    for host in config['hosts']:
        session.mount(f'https://{host}/', adapter)
        session.mount(f'http://{host}/', adapter)
    return config


def status(config: dict[str, Any]) -> dict[str, Any]:
    return {
        'enabled': bool(config.get('base_url')),
        'relay': urlparse(config.get('base_url') or '').hostname or '',
        'hosts': list(config.get('hosts') or []),
        'responses': dict(sorted(STATS.items())),
    }
