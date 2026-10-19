"""Deterministic exclusions for service dashboards that are not news articles."""
from urllib.parse import unquote, urlparse


def is_non_article_service_page(url: str) -> bool:
    """Ignore tracking queries and synthetic live-alert fragments."""
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    path = unquote(parsed.path).lower().rstrip("/")
    return (
        (host == "northernrailway.co.uk" or host.endswith(".northernrailway.co.uk"))
        and path == "/service-updates"
    )
