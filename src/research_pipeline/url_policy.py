"""URL boundary checks for seeded public-source ingestion."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def _domain_matches(host: str, rule: str) -> bool:
    normalized = rule.lower().strip().lstrip(".")
    return host == normalized or host.endswith(f".{normalized}")


def validate_public_url(
    url: str,
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "only http and https URLs are allowed"
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False, "URL has no hostname"
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False, "local hostnames are not allowed"

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False, "non-public IP addresses are not allowed"

    blocked = blocked_domains or []
    if any(_domain_matches(host, rule) for rule in blocked):
        return False, f"domain is blocked: {host}"
    allowed = allowed_domains or []
    if allowed and not any(_domain_matches(host, rule) for rule in allowed):
        return False, f"domain is outside the allowlist: {host}"
    return True, None
