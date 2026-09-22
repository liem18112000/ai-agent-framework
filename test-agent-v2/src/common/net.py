"""Shared SSRF egress guard for every outbound fetcher (root cause #1).

One predicate — :func:`host_blocked` — used by all outbound fetchers (KGA web pages, Atlassian
attachment downloads) so a new sink can't independently regress the SSRF fix. Each fetcher keeps its
own httpx wiring (an event-hook per redirect hop, or a manual hop loop) but sources the *decision*
from here.
"""

from __future__ import annotations

import ipaddress
import socket

_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})


class BlockedHostError(ValueError):
    """SSRF guard tripped — the fetch (or a redirect hop) targeted a non-public host."""


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


def host_blocked(host: str | None) -> bool:
    """True if `host` is non-public: a private/loopback/link-local/reserved IP literal, a known
    internal name, or a hostname that *resolves* to such an address. Fail-open on a resolution error —
    a name that can't resolve can't be connected to anyway."""
    host = (host or "").strip().lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS:
        return True
    try:
        ipaddress.ip_address(host)  # bare IP literal (v4/v6, brackets already stripped by URL.host)
        return _ip_blocked(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return any(_ip_blocked(info[4][0]) for info in infos)
